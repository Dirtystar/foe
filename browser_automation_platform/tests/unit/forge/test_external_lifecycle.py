"""External-Chrome lifecycle through the real Application/BrowserController
(Milestone 4.16). Proves the non-ownership guarantees end to end:

  Attach            -> connects
  Stop automation   -> stays attached; Chrome untouched
  Disconnect        -> detaches; Chrome stays open
  application exit  -> disconnects; Chrome stays open
"""

from __future__ import annotations

import asyncio

from bap.app.attended import TabAssignment, make_tab_provider
from bap.app.composition import create_application
from bap.app.stubs import StubCapturePort
from bap.core.domain.enums import BrowserOwnership
from bap.core.domain.models import BrowserTab, TabHandle
from bap.core.engine.scheduler import Scheduler
from bap.core.ports.browser_port import BrowserPort
from bap.forge.config import build_forge_config
from bap.forge.worlds import World, WorldStore


class FakeExternalChrome(BrowserPort):
    """A read-only CDP guest of an operator-owned Chrome. ``chrome_alive`` models
    the real Chrome process: start()/stop() only connect/disconnect and must NEVER
    flip it to False — BAP does not own or close it."""

    ownership = BrowserOwnership.EXTERNAL

    def __init__(self, tabs):
        self._tabs = tabs
        self.chrome_alive = True     # the operator's Chrome; never killed by BAP
        self.attached = False
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def start(self):
        self.attached = True
        self.connect_calls += 1

    async def stop(self):
        # Disconnect only — the operator's Chrome keeps running.
        self.attached = False
        self.disconnect_calls += 1

    async def scan_tabs(self):
        return list(self._tabs)

    async def adopt_tab(self, tab_id):
        return TabHandle(tab_id=tab_id, native=object())

    async def open_tab(self, profile):
        raise AssertionError("external guest must never open tabs")

    async def navigate(self, tab, url):
        raise AssertionError("external guest must never navigate")

    async def close_tab(self, tab):
        return None

    def list_tabs(self):
        return [t.tab_id for t in self._tabs]


async def _instant_sleep(_seconds):
    await asyncio.sleep(0)


def _build_app():
    worlds = [World(alias="H", hostname="cz8.forgeofempires.com", interval_ms=10)]
    tabs = [BrowserTab("cdp-tab-1", "Forge H", "https://cz8.forgeofempires.com/game/index")]
    browser = FakeExternalChrome(tabs)
    store = WorldStore(worlds=worlds)
    assignment = TabAssignment()
    for alias, tab in store.match_tabs(tabs).items():
        assignment.assign(alias, tab)
    app = create_application(
        build_forge_config(worlds), browser=browser, capture_port=StubCapturePort(),
        tab_provider=make_tab_provider(browser, assignment),
        scheduler=Scheduler(sleep=_instant_sleep),
    )
    return app, browser


def test_controller_reports_external_ownership():
    app, _ = _build_app()
    assert app.browser_controller.ownership is BrowserOwnership.EXTERNAL
    assert app.browser_controller.owns_process is False


async def test_attach_then_stop_automation_keeps_chrome_and_connection():
    app, browser = _build_app()
    await app.open_browser()                       # "Attach Chrome"
    assert browser.attached is True and browser.chrome_alive is True

    await app.start()
    assert app.manager.session_count == 1

    await app.stop_automation()                    # Stop button
    assert browser.attached is True                # still attached
    assert browser.disconnect_calls == 0           # Stop never disconnects
    assert browser.chrome_alive is True            # Chrome untouched


async def test_disconnect_detaches_without_closing_chrome():
    app, browser = _build_app()
    await app.open_browser()
    await app.close_browser()                      # "Disconnect"
    assert browser.attached is False
    assert browser.disconnect_calls == 1
    assert browser.chrome_alive is True            # Chrome stays open


async def test_application_exit_disconnects_but_leaves_chrome_open():
    app, browser = _build_app()
    await app.open_browser()
    await app.start()

    await app.stop()                               # Exit path
    assert browser.attached is False               # disconnected
    assert browser.chrome_alive is True            # operator's Chrome survives
    assert app.manager.session_count == 0
