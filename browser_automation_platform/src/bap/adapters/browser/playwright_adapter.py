from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from bap.core.ports.browser_port import (
    BrowserManagerError,
    BrowserNotStartedError,
    BrowserPort,
    DuplicateTabError,
    TabHandle,
    TabId,
    TabLimitExceededError,
    TabNotFoundError,
    TabProfile,
)

logger = logging.getLogger(__name__)


@dataclass
class _TabEntry:
    tab_id: TabId
    context: BrowserContext
    page: Page
    owns_context: bool


class PlaywrightBrowserManager(BrowserPort):
    """BrowserPort implementation backed by Playwright's async API.

    One `Browser` process is launched by `start()`. Tabs are Playwright
    `Page`s, each optionally wrapped in its own `BrowserContext` for
    cookie/storage isolation (the default, and what "independent tabs"
    requires), or sharing a single context when isolation is deliberately
    disabled.
    """

    def __init__(
        self,
        *,
        headless: bool = False,
        max_tabs: int = 8,
        isolate_contexts_per_tab: bool = True,
        browser_engine: str = "chromium",
        executable_path: str | None = None,
    ) -> None:
        self._headless = headless
        self._max_tabs = max_tabs
        self._isolate_contexts_per_tab = isolate_contexts_per_tab
        self._browser_engine = browser_engine
        # Optional override for the browser binary. Needed in environments
        # where the binary lives outside Playwright's default lookup path;
        # None uses Playwright's own resolution.
        self._executable_path = executable_path

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._shared_context: BrowserContext | None = None
        self._tabs: dict[TabId, _TabEntry] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._browser is not None:
            logger.debug("start() called but browser is already running; ignoring")
            return

        self._playwright = await async_playwright().start()
        try:
            engine = getattr(self._playwright, self._browser_engine)
            launch_kwargs: dict = {"headless": self._headless}
            if self._executable_path:
                launch_kwargs["executable_path"] = self._executable_path
            self._browser = await engine.launch(**launch_kwargs)

            if not self._isolate_contexts_per_tab:
                self._shared_context = await self._browser.new_context()
        except Exception:
            # A partial start must not leak the driver subprocess. Tear down
            # whatever came up (best-effort) and re-raise the original error.
            await self._shutdown_driver_quietly()
            raise

        logger.info(
            "Browser started (engine=%s, headless=%s, isolate_contexts_per_tab=%s)",
            self._browser_engine,
            self._headless,
            self._isolate_contexts_per_tab,
        )

    async def stop(self) -> None:
        if self._browser is None and self._playwright is None:
            return

        # Best-effort teardown that always reaches _playwright.stop() — the step
        # that actually reaps the driver subprocess — even if an earlier close
        # fails. Failures are surfaced (first one re-raised) after the driver is
        # guaranteed stopped, so a caller still learns something went wrong
        # without risking an orphan process.
        errors = await self._shutdown_driver_quietly()
        logger.info("Browser stopped")
        if errors:
            raise errors[0]

    async def _shutdown_driver_quietly(self) -> list[Exception]:
        """Close tabs/contexts/browser and stop the Playwright driver, never
        raising. Returns the exceptions encountered (in order) so callers can
        decide whether to surface them. Idempotent and safe on a partial start."""
        errors: list[Exception] = []
        for tab_id in list(self._tabs.keys()):
            entry = self._tabs.pop(tab_id)
            try:
                await self._close_entry(entry)
            except Exception as exc:  # keep going; the driver must still stop
                errors.append(exc)
                logger.warning("error closing tab '%s' during stop", tab_id, exc_info=True)

        if self._shared_context is not None:
            try:
                await self._shared_context.close()
            except Exception as exc:
                errors.append(exc)
                logger.warning("error closing shared context during stop", exc_info=True)
            finally:
                self._shared_context = None

        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                errors.append(exc)
                logger.warning("error closing browser during stop", exc_info=True)
            finally:
                self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                errors.append(exc)
                logger.warning("error stopping Playwright driver during stop", exc_info=True)
            finally:
                self._playwright = None

        self._tabs.clear()
        return errors

    async def open_tab(self, profile: TabProfile) -> TabHandle:
        if self._browser is None:
            raise BrowserNotStartedError("Call start() before open_tab().")

        async with self._lock:
            if profile.id in self._tabs:
                raise DuplicateTabError(f"Tab '{profile.id}' is already open.")
            if len(self._tabs) >= self._max_tabs:
                raise TabLimitExceededError(
                    f"Cannot open tab '{profile.id}': max_tabs={self._max_tabs} reached."
                )

            owns_context = self._isolate_contexts_per_tab
            if owns_context:
                context = await self._browser.new_context(
                    viewport={"width": profile.viewport.width, "height": profile.viewport.height}
                )
            else:
                assert self._shared_context is not None
                context = self._shared_context

            try:
                page = await context.new_page()
                if profile.start_url:
                    await page.goto(profile.start_url)
            except Exception:
                if owns_context:
                    await context.close()
                raise

            self._tabs[profile.id] = _TabEntry(
                tab_id=profile.id, context=context, page=page, owns_context=owns_context
            )
            logger.info("Opened tab '%s' (url=%s)", profile.id, profile.start_url)
            return TabHandle(tab_id=profile.id, native=page)

    async def navigate(self, tab: TabHandle, url: str) -> None:
        entry = self._require_tab(tab.tab_id)
        await entry.page.goto(url)
        logger.info("Tab '%s' navigated to %s", tab.tab_id, url)

    async def close_tab(self, tab: TabHandle) -> None:
        async with self._lock:
            entry = self._tabs.pop(tab.tab_id, None)
            if entry is None:
                raise TabNotFoundError(f"Tab '{tab.tab_id}' is not open.")
        await self._close_entry(entry)
        logger.info("Closed tab '%s'", tab.tab_id)

    def list_tabs(self) -> list[TabId]:
        return list(self._tabs.keys())

    def context_and_page_counts(self) -> tuple[int, int]:
        """(contexts, pages) currently open in the live browser, or (0, 0) if
        it is not started. Used by the resource metrics adapter; keeps the
        Playwright `contexts`/`pages` access inside this adapter."""
        if self._browser is None:
            return (0, 0)
        contexts = self._browser.contexts
        return (len(contexts), sum(len(c.pages) for c in contexts))

    def _require_tab(self, tab_id: TabId) -> _TabEntry:
        entry = self._tabs.get(tab_id)
        if entry is None:
            raise TabNotFoundError(f"Tab '{tab_id}' is not open.")
        return entry

    async def _close_entry(self, entry: _TabEntry) -> None:
        try:
            if not entry.page.is_closed():
                await entry.page.close()
        finally:
            if entry.owns_context:
                await entry.context.close()


__all__ = ["PlaywrightBrowserManager", "BrowserManagerError"]
