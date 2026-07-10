"""Attended (user-driven) browser adapter.

Launches a **visible, persistent** Chromium context the user drives themselves —
opening, logging into, and navigating tabs. BAP then *scans* those tabs and
*adopts* the ones the user assigns to sessions, instead of opening its own and
navigating to a configured URL.

Persistent context = a real on-disk Chromium profile (`user_data_dir`), so
logins and cookies survive restarts. Those are managed by Chromium itself — we
never read or store credentials.

Playwright types live only here; the rest of the app sees `BrowserTab`,
`TabHandle`, and the `BrowserPort` / `TabSourcePort` contracts.
"""

from __future__ import annotations

import logging

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from bap.core.domain.models import BrowserTab
from bap.core.ports.browser_port import (
    BrowserNotStartedError,
    BrowserPort,
    TabHandle,
    TabId,
    TabNotFoundError,
    TabProfile,
)

logger = logging.getLogger(__name__)


class AttendedBrowserManager(BrowserPort):
    """A BrowserPort backed by a persistent, headed context, plus tab
    discovery/adoption (`TabSourcePort`). Session tabs are the user's own tabs,
    so `close_tab` deliberately does not close them — only `stop()` tears the
    whole window down."""

    def __init__(
        self,
        *,
        user_data_dir: str,
        browser_engine: str = "chromium",
        executable_path: str | None = None,
        headless: bool = False,
    ) -> None:
        self._user_data_dir = user_data_dir
        self._browser_engine = browser_engine
        self._executable_path = executable_path
        # Attended mode is visible by default (the user drives it); headless is
        # only for automated tests with no display.
        self._headless = headless

        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._by_id: dict[str, Page] = {}
        self._ids: dict[Page, str] = {}
        self._counter = 0

    # --- BrowserPort lifecycle ---------------------------------------------

    async def start(self) -> None:
        """Open the visible browser window (a persistent Chromium profile)."""
        if self._context is not None:
            logger.debug("start() called but attended browser is already open; ignoring")
            return
        self._playwright = await async_playwright().start()
        try:
            engine = getattr(self._playwright, self._browser_engine)
            launch_kwargs: dict = {"headless": self._headless}
            if self._executable_path:
                launch_kwargs["executable_path"] = self._executable_path
            self._context = await engine.launch_persistent_context(
                self._user_data_dir, **launch_kwargs
            )
        except Exception:
            await self._shutdown_quietly()
            raise
        logger.info("Attended browser opened (profile=%s)", self._user_data_dir)

    async def stop(self) -> None:
        if self._context is None and self._playwright is None:
            return
        errors = await self._shutdown_quietly()
        logger.info("Attended browser closed")
        if errors:
            raise errors[0]

    async def _shutdown_quietly(self) -> list[Exception]:
        errors: list[Exception] = []
        if self._context is not None:
            try:
                await self._context.close()
            except Exception as exc:  # keep going; the driver must still stop
                errors.append(exc)
                logger.warning("error closing attended context", exc_info=True)
            finally:
                self._context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                errors.append(exc)
                logger.warning("error stopping Playwright driver", exc_info=True)
            finally:
                self._playwright = None
        self._by_id.clear()
        self._ids.clear()
        return errors

    # --- TabSourcePort: discover + adopt -----------------------------------

    async def scan_tabs(self) -> list[BrowserTab]:
        """List the tabs currently open in the attended browser."""
        if self._context is None:
            raise BrowserNotStartedError("Open the browser before scanning tabs.")
        tabs: list[BrowserTab] = []
        for page in list(self._context.pages):
            if page.is_closed():
                continue
            tab_id = self._id_for(page)
            try:
                title = await page.title()
            except Exception:  # a page mid-navigation may refuse; fall back to URL
                title = ""
            tabs.append(BrowserTab(tab_id=tab_id, title=title or page.url, url=page.url))
        self._prune_closed()
        return tabs

    async def adopt_tab(self, tab_id: str) -> TabHandle:
        """Return an opaque handle to the already-open tab with this id."""
        page = self._by_id.get(tab_id)
        if page is None or page.is_closed():
            self._prune_closed()
            raise TabNotFoundError(f"Tab '{tab_id}' is no longer open.")
        return TabHandle(tab_id=tab_id, native=page)

    def _id_for(self, page: Page) -> str:
        existing = self._ids.get(page)
        if existing is not None:
            return existing
        self._counter += 1
        tab_id = f"tab-{self._counter}"
        self._ids[page] = tab_id
        self._by_id[tab_id] = page
        return tab_id

    def _prune_closed(self) -> None:
        for tab_id, page in list(self._by_id.items()):
            if page.is_closed():
                self._by_id.pop(tab_id, None)
                self._ids.pop(page, None)

    # --- BrowserPort tab operations ----------------------------------------

    async def open_tab(self, profile: TabProfile) -> TabHandle:
        """Open a fresh tab (used only as a fallback; attended sessions adopt
        existing tabs instead). Navigates to start_url when the profile has one."""
        if self._context is None:
            raise BrowserNotStartedError("Call start() before open_tab().")
        page = await self._context.new_page()
        if profile.start_url:
            await page.goto(profile.start_url)
        tab_id = self._id_for(page)
        return TabHandle(tab_id=tab_id, native=page)

    async def navigate(self, tab: TabHandle, url: str) -> None:
        await tab.native.goto(url)

    async def close_tab(self, tab: TabHandle) -> None:
        # The user owns these tabs — never close them from under them. Session
        # shutdown/recovery just detaches; stop() closes the whole window.
        return None

    def list_tabs(self) -> list[TabId]:
        return [tid for tid, page in self._by_id.items() if not page.is_closed()]


__all__ = ["AttendedBrowserManager"]
