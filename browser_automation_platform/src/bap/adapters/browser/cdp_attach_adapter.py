"""External-Chrome attach adapter (Milestone 4.16) — a read-only CDP guest.

BAP attaches to a Chrome the **operator** launched with remote debugging, over
the Chrome DevTools Protocol, and simply observes the tabs already open. It is a
guest, not an owner:

  - it **never launches** Chrome (the operator runs the documented command);
  - it **never closes** Chrome — ``stop()`` disconnects the CDP client only, so
    quitting BAP, Disconnecting, or stopping automation all leave Chrome running;
  - it **writes nothing** to the profile and delivers **no input** — capture stays
    the same read-only ``Page.captureScreenshot`` used in managed mode.

Ownership is declared explicitly (``ownership = EXTERNAL``) so the
BrowserController knows a close here must not tear the process down.

Playwright types live only in this adapter; the rest of the app sees
``BrowserTab``, ``TabHandle``, and the ``BrowserPort`` / ``TabSourcePort``
contracts. ``connect_over_cdp`` is injectable so unit tests drive a faithful fake
CDP endpoint with no real Chrome.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse
from urllib.request import urlopen

from bap.core.domain.enums import BrowserOwnership
from bap.core.domain.models import BrowserTab
from bap.core.ports.browser_port import (
    BrowserManagerError,
    BrowserNotStartedError,
    BrowserPort,
    TabHandle,
    TabId,
    TabNotFoundError,
    TabProfile,
)

logger = logging.getLogger(__name__)

DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9222"


class CdpConnectionError(BrowserManagerError):
    """The external Chrome could not be reached / connected. Recoverable: the
    operator launches (or relaunches) Chrome and attaches again."""


def normalize_endpoint(endpoint: str | None) -> str:
    """Normalise a CDP endpoint to an ``http://host:port`` form. Accepts a bare
    ``host:port`` or ``:port`` and defaults the scheme/host to localhost."""
    text = (endpoint or "").strip() or DEFAULT_CDP_ENDPOINT
    if text.isdigit():  # a bare port -> localhost:port
        text = f"127.0.0.1:{text}"
    if "://" not in text:
        text = "http://" + text.lstrip("/")
    parsed = urlparse(text)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    return f"http://{host}:{port}"


def is_localhost_endpoint(endpoint: str | None) -> bool:
    """True when the endpoint targets the local machine. External debugging ports
    must stay on localhost; anything else is flagged to the operator."""
    host = urlparse(normalize_endpoint(endpoint)).hostname or ""
    return host in {"127.0.0.1", "localhost", "::1", "0.0.0.0"} or host.startswith("127.")


# An HTTP fetcher (url -> raw bytes); injectable so tests need no network.
FetchFn = Callable[[str], bytes]


def _default_fetch(url: str) -> bytes:
    with urlopen(url, timeout=3.0) as resp:  # localhost only in practice
        return resp.read()


def probe_cdp(endpoint: str | None, *, fetch: FetchFn | None = None) -> dict:
    """Test whether an external Chrome is reachable at ``endpoint`` WITHOUT
    connecting a driver — a plain GET of ``/json/version`` and ``/json`` (the CDP
    HTTP discovery endpoints). Returns a status dict; never raises for an
    unreachable endpoint (that is a normal 'Not running' result), so the UI can
    show a clear state.

    Keys: ``reachable`` (bool), ``endpoint``, ``localhost`` (bool), and when
    reachable ``browser`` (version string), ``tabs`` (page count), ``forge_tabs``
    (Forge-hostname page count), plus ``error`` when not reachable.
    """
    from bap.forge.worlds import is_forge_hostname

    ep = normalize_endpoint(endpoint)
    fetch = fetch or _default_fetch
    out: dict = {"reachable": False, "endpoint": ep, "localhost": is_localhost_endpoint(ep)}
    try:
        version = json.loads(fetch(ep + "/json/version").decode("utf-8"))
    except Exception as exc:  # connection refused / not running / bad response
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    out["reachable"] = True
    out["browser"] = str(version.get("Browser", "Chrome"))
    try:
        pages = json.loads(fetch(ep + "/json").decode("utf-8"))
        page_list = [p for p in pages if p.get("type", "page") == "page"]
        out["tabs"] = len(page_list)
        out["forge_tabs"] = sum(1 for p in page_list if is_forge_hostname(p.get("url", "")))
    except Exception:
        out["tabs"] = None
        out["forge_tabs"] = None
    return out


# connect_over_cdp(endpoint) -> a connected browser object (Playwright Browser, or
# a fake in tests). Injectable so the unit suite needs no real Chrome.
ConnectFn = Callable[[str], Awaitable[object]]


class CdpAttachBrowserManager(BrowserPort):
    """A read-only ``BrowserPort`` + ``TabSourcePort`` backed by an operator-owned
    Chrome reached over CDP. Its lifecycle connects and disconnects; it never
    launches or closes the browser process."""

    ownership = BrowserOwnership.EXTERNAL

    def __init__(
        self,
        endpoint: str = DEFAULT_CDP_ENDPOINT,
        *,
        connect: ConnectFn | None = None,
    ) -> None:
        self._endpoint = normalize_endpoint(endpoint)
        self._connect = connect  # None -> real Playwright connect_over_cdp
        self._playwright = None
        self._browser = None
        self._by_id: dict[str, object] = {}
        self._ids: dict[object, str] = {}
        self._counter = 0

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def connected(self) -> bool:
        return self._browser is not None

    # --- BrowserPort lifecycle: connect / disconnect (never launch / close) ---

    async def start(self) -> None:
        """Attach to the operator's Chrome over CDP. Never launches Chrome. Raises
        CdpConnectionError (recoverably) if the endpoint is unreachable; leaves the
        adapter cleanly disconnected so a later retry works."""
        if self._browser is not None:
            logger.debug("start() called but already attached; ignoring")
            return
        try:
            self._browser = await self._open_connection()
        except Exception as exc:
            await self._disconnect_quietly()
            raise CdpConnectionError(
                f"Could not attach to external Chrome at {self._endpoint}: {exc}. "
                "Launch Chrome with --remote-debugging-port and try again."
            ) from exc
        logger.info("Attached to external Chrome at %s (read-only guest)", self._endpoint)

    async def stop(self) -> None:
        """Disconnect the CDP client. This NEVER closes the operator's Chrome — it
        only drops BAP's connection. Idempotent."""
        if self._browser is None and self._playwright is None:
            return
        await self._disconnect_quietly()
        logger.info("Disconnected from external Chrome (Chrome left running)")

    async def _open_connection(self) -> object:
        if self._connect is not None:
            return await self._connect(self._endpoint)
        # Real path: Playwright connect_over_cdp. Imported lazily so the unit
        # suite (which injects a fake) needs no Playwright/Chrome.
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        return await self._playwright.chromium.connect_over_cdp(self._endpoint)

    async def _disconnect_quietly(self) -> None:
        browser, self._browser = self._browser, None
        if browser is not None:
            try:
                # For a connect_over_cdp browser this closes only BAP's CDP
                # connection; the operator's Chrome process keeps running.
                await browser.close()
            except Exception:
                logger.warning("error disconnecting CDP client", exc_info=True)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.warning("error stopping Playwright driver", exc_info=True)
            finally:
                self._playwright = None
        self._by_id.clear()
        self._ids.clear()
        self._counter = 0

    # --- TabSourcePort: discover + adopt ------------------------------------

    def _pages(self) -> list[object]:
        pages: list[object] = []
        for context in list(getattr(self._browser, "contexts", [])):
            pages.extend(list(context.pages))
        return pages

    async def scan_tabs(self) -> list[BrowserTab]:
        """List every open tab in the attached Chrome (id/title/url only). All
        tabs are listed for transparency; only Forge worlds are ever captured."""
        if self._browser is None:
            raise BrowserNotStartedError("Attach to external Chrome before scanning tabs.")
        tabs: list[BrowserTab] = []
        for page in self._pages():
            if page.is_closed():
                continue
            tab_id = self._id_for(page)
            try:
                title = await page.title()
            except Exception:
                title = ""
            tabs.append(BrowserTab(tab_id=tab_id, title=title or page.url, url=page.url))
        self._prune_closed()
        return tabs

    async def adopt_tab(self, tab_id: str) -> TabHandle:
        page = self._by_id.get(tab_id)
        if page is None or page.is_closed():
            self._prune_closed()
            raise TabNotFoundError(f"Tab '{tab_id}' is no longer open in external Chrome.")
        return TabHandle(tab_id=tab_id, native=page)

    def _id_for(self, page: object) -> str:
        existing = self._ids.get(page)
        if existing is not None:
            return existing
        self._counter += 1
        tab_id = f"cdp-tab-{self._counter}"
        self._ids[page] = tab_id
        self._by_id[tab_id] = page
        return tab_id

    def _prune_closed(self) -> None:
        for tab_id, page in list(self._by_id.items()):
            if page.is_closed():
                self._by_id.pop(tab_id, None)
                self._ids.pop(page, None)

    # --- BrowserPort tab operations (guest semantics) -----------------------

    async def open_tab(self, profile: TabProfile) -> TabHandle:
        # Observe-only guest: BAP never opens or navigates tabs in the operator's
        # Chrome. Sessions adopt existing tabs via the tab provider instead.
        raise BrowserManagerError(
            "External Chrome is observe-only: BAP does not open tabs. "
            "Open the Forge world tab in Chrome yourself, then Scan & Reattach."
        )

    async def navigate(self, tab: TabHandle, url: str) -> None:
        # Never navigate the operator's tabs.
        raise BrowserManagerError("External Chrome is observe-only: BAP does not navigate tabs.")

    async def close_tab(self, tab: TabHandle) -> None:
        # The operator owns these tabs — never close them.
        return None

    def list_tabs(self) -> list[TabId]:
        return [tid for tid, page in self._by_id.items() if not page.is_closed()]


__all__ = [
    "DEFAULT_CDP_ENDPOINT",
    "CdpAttachBrowserManager",
    "CdpConnectionError",
    "normalize_endpoint",
    "is_localhost_endpoint",
    "probe_cdp",
]
