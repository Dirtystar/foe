"""P0-1 regression: Forge capture is provably read-only.

A capture-only tick (rules 0/0, actions 0/0) must screenshot the tab without
clicking, typing, scrolling, focusing, evaluating, resizing the viewport, or
bringing the tab to front. These tests drive the adapter and a full tick through
a tripwire "page" that records any forbidden access.
"""

from __future__ import annotations

import asyncio
import base64

import pytest

from bap.adapters.capture.forge_capture import ForgeCanvasCaptureAdapter
from bap.app.attended import TabAssignment, make_tab_provider
from bap.app.composition import create_application
from bap.core.domain.models import BrowserTab, Rect, TabHandle
from bap.core.engine.scheduler import Scheduler
from bap.core.ports.browser_port import BrowserPort
from bap.forge.config import build_forge_config
from bap.forge.worlds import World, WorldStore

# A real 1x1 PNG so the adapter's dimension read succeeds.
_PNG_1x1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

# Anything that could mutate the page or switch tabs. Touching any of these
# during capture is a bug.
_FORBIDDEN = {
    "screenshot", "click", "fill", "type", "press", "tap", "hover", "focus",
    "bring_to_front", "evaluate", "evaluate_handle", "mouse", "keyboard",
    "touchscreen", "set_viewport_size", "goto", "reload", "add_init_script",
}


class SpyCDPSession:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def send(self, method, params=None):
        self.sent.append((method, params or {}))
        assert method == "Page.captureScreenshot", f"unexpected CDP call: {method}"
        return {"data": _PNG_1x1_B64}


class SpyContext:
    def __init__(self, session):
        self._session = session
        self.cdp_sessions_created = 0

    async def new_cdp_session(self, page):
        self.cdp_sessions_created += 1
        return self._session


class SpyPage:
    """Records any access to a mutating API and refuses it."""

    def __init__(self):
        object.__setattr__(self, "session", SpyCDPSession())
        object.__setattr__(self, "context", SpyContext(self.session))
        object.__setattr__(self, "forbidden_accessed", [])

    def __getattr__(self, name):
        if name in _FORBIDDEN:
            # Record then blow up — a forbidden call must never silently succeed.
            self.forbidden_accessed.append(name)
        raise AttributeError(name)


# --- adapter level ------------------------------------------------------------


async def test_capture_only_sends_capture_screenshot_and_nothing_else():
    adapter = ForgeCanvasCaptureAdapter()
    page = SpyPage()
    tab = TabHandle(tab_id="tab-1", native=page)

    for _ in range(5):
        img = await adapter.capture(tab)

    assert img.width == 1 and img.height == 1
    assert [m for m, _ in page.session.sent] == ["Page.captureScreenshot"] * 5
    # No mutating API was touched, and the CDP session is cached (created once).
    assert page.forbidden_accessed == []
    assert page.context.cdp_sessions_created == 1


async def test_capture_is_viewport_only_never_full_page():
    adapter = ForgeCanvasCaptureAdapter()
    page = SpyPage()
    await adapter.capture(TabHandle("t", page))
    _, params = page.session.sent[0]
    assert params["captureBeyondViewport"] is False  # never grows/relayouts the canvas
    assert params["fromSurface"] is True
    assert "clip" not in params  # viewport capture


async def test_region_capture_uses_clip_not_scroll():
    adapter = ForgeCanvasCaptureAdapter()
    page = SpyPage()
    await adapter.capture(TabHandle("t", page), Rect(x=10, y=20, w=100, h=50))
    _, params = page.session.sent[0]
    assert params["clip"] == {"x": 10, "y": 20, "width": 100, "height": 50, "scale": 1}


async def test_stale_session_is_recreated_once():
    adapter = ForgeCanvasCaptureAdapter()
    page = SpyPage()

    # First call: make the initial session raise, forcing a recreate.
    calls = {"n": 0}
    original_new = page.context.new_cdp_session

    class Boom:
        async def send(self, *a, **k):
            raise RuntimeError("session detached")

    async def flaky_new(p):
        calls["n"] += 1
        return Boom() if calls["n"] == 1 else await original_new(p)

    page.context.new_cdp_session = flaky_new
    img = await adapter.capture(TabHandle("t", page))
    assert img.width == 1
    assert calls["n"] == 2  # dropped the boom session, made a fresh one


# --- full tick level ----------------------------------------------------------


class FakeAttendedBrowser(BrowserPort):
    """Adopts tabs as SpyPage-backed handles; close_tab is a no-op (user owns tabs)."""

    def __init__(self, pages: dict[str, SpyPage]):
        self._pages = pages
        self.open = False

    async def start(self):
        self.open = True

    async def stop(self):
        self.open = False

    async def adopt_tab(self, tab_id: str) -> TabHandle:
        return TabHandle(tab_id=tab_id, native=self._pages[tab_id])

    async def open_tab(self, profile):
        return TabHandle(tab_id=profile.id, native=self._pages[profile.id])

    async def navigate(self, tab, url):
        pass

    async def close_tab(self, tab):
        pass

    def list_tabs(self):
        return list(self._pages)


async def _instant_sleep(_):
    await asyncio.sleep(0)


async def test_repeated_forge_ticks_perform_no_interaction():
    worlds = [
        World(alias="Main", hostname="cz8.forgeofempires.com", interval_ms=10),
        World(alias="Farm", hostname="cz1.forgeofempires.com", interval_ms=10),
    ]
    tabs = [
        BrowserTab("tab-a", "cz8", "https://cz8.forgeofempires.com/game"),
        BrowserTab("tab-b", "cz1", "https://cz1.forgeofempires.com/game"),
    ]
    pages = {"tab-a": SpyPage(), "tab-b": SpyPage()}
    browser = FakeAttendedBrowser(pages)

    store = WorldStore(worlds=worlds)
    assignment = TabAssignment()
    for alias, tab in store.match_tabs(tabs).items():
        assignment.assign(alias, tab)

    scheduler = Scheduler(sleep=_instant_sleep)
    app = create_application(
        build_forge_config(worlds),
        browser=browser,
        capture_port=ForgeCanvasCaptureAdapter(),
        tab_provider=make_tab_provider(browser, assignment),
        scheduler=scheduler,
    )
    await app.open_browser()
    await app.create_sessions()

    reports = []
    for _ in range(4):
        reports.extend(await scheduler.run_once())
    await app.stop_automation()

    # Every tick completed as pure capture: zero rules, zero actions, and not a
    # single forbidden page API touched on either world.
    for page in pages.values():
        assert page.forbidden_accessed == []
        assert [m for m, _ in page.session.sent] == ["Page.captureScreenshot"] * 4
    for r in reports:
        assert r.report.status.name == "COMPLETED"
        assert r.report.execution is None or len(r.report.execution.results) == 0
