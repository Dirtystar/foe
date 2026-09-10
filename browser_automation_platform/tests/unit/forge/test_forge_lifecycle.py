"""End-to-end Forge lifecycle: build a config from Worlds, run it through the
real Application/SessionManager/BrowserController, and prove the P0 contract:

  Stop  -> automation stops, the browser and its tabs STAY OPEN
  Close -> the browser closes explicitly
"""

from __future__ import annotations

import asyncio

import pytest

from bap.app.attended import TabAssignment, make_tab_provider
from bap.app.composition import create_application
from bap.app.stubs import StubCapturePort
from bap.core.domain.models import BrowserTab, TabHandle
from bap.core.engine.scheduler import Scheduler
from bap.core.ports.browser_port import BrowserPort
from bap.forge.config import build_forge_config
from bap.forge.worlds import World, WorldStore


class FakeAttendedBrowser(BrowserPort):
    """A persistent, user-driven browser: close_tab is a no-op (the user owns
    the tabs); only stop() tears the window down. Tracks open/closed state."""

    def __init__(self, tabs: list[BrowserTab]):
        self._tabs = tabs
        self.open = False
        self.start_calls = 0
        self.stop_calls = 0
        self.closed_tab_ids: list[str] = []

    async def start(self):
        self.open = True
        self.start_calls += 1

    async def stop(self):
        self.open = False
        self.stop_calls += 1

    async def scan_tabs(self):
        return list(self._tabs)

    async def adopt_tab(self, tab_id: str) -> TabHandle:
        return TabHandle(tab_id=tab_id, native=object())

    async def open_tab(self, profile):  # not used in attended mode
        return TabHandle(tab_id=profile.id, native=object())

    async def navigate(self, tab, url):
        pass

    async def close_tab(self, tab):
        # User owns attended tabs — never closed from under them.
        self.closed_tab_ids.append(tab.tab_id)

    def list_tabs(self):
        return [t.tab_id for t in self._tabs]


async def _instant_sleep(_seconds):
    await asyncio.sleep(0)


def _build_app():
    worlds = [
        World(alias="Main", hostname="cz8.forgeofempires.com", interval_ms=10),
        World(alias="Farm", hostname="cz1.forgeofempires.com", interval_ms=10),
    ]
    tabs = [
        BrowserTab("tab-77", "cz8", "https://cz8.forgeofempires.com/game/index"),
        BrowserTab("tab-4", "cz1", "https://cz1.forgeofempires.com/game/index"),
    ]
    cfg = build_forge_config(worlds)
    browser = FakeAttendedBrowser(tabs)

    # Reattach worlds to open tabs by hostname (never tab id), exactly as the GUI does.
    store = WorldStore(worlds=worlds)
    assignment = TabAssignment()
    for alias, tab in store.match_tabs(tabs).items():
        assignment.assign(alias, tab)

    app = create_application(
        cfg,
        browser=browser,
        capture_port=StubCapturePort(),
        tab_provider=make_tab_provider(browser, assignment),
        scheduler=Scheduler(sleep=_instant_sleep),
    )
    return app, browser


async def test_stop_keeps_browser_open_close_tears_it_down():
    app, browser = _build_app()

    await app.open_browser()
    assert browser.open is True

    await app.start()
    assert browser.open is True
    assert app.manager.session_count == 2  # both worlds adopted their tabs

    # STOP: automation only. Browser and tabs must survive.
    await app.stop_automation()
    assert browser.open is True
    assert browser.stop_calls == 0
    assert app.manager.session_count == 0  # sessions detached, ready to restart

    # Restart automation on the same still-open browser.
    await app.start()
    assert app.manager.session_count == 2

    await app.stop_automation()

    # CLOSE: explicit browser teardown.
    await app.close_browser()
    assert browser.open is False
    assert browser.stop_calls == 1


async def test_full_shutdown_closes_browser():
    app, browser = _build_app()
    await app.open_browser()
    await app.start()

    await app.stop()  # Exit path: stop automation + close browser

    assert browser.open is False
    assert browser.stop_calls == 1
    assert app.manager.session_count == 0


async def test_forge_capture_uses_no_selector():
    # The P0-C guarantee, asserted on the config the app actually runs.
    app, _ = _build_app()
    for profile in app.config.profiles:
        for binding in profile.capture_bindings:
            assert binding.target == "full_page"
            assert binding.selector is None
