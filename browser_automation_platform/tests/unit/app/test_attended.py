"""Attended-mode glue: assignment, tab provider gating, and local persistence."""

from __future__ import annotations

import pytest

from bap.app.attended import (
    TabAssignment,
    UnassignedSessionError,
    load_assignment,
    make_tab_provider,
    save_assignment,
)
from bap.core.domain.models import BrowserTab, TabHandle, TabProfile
from bap.core.engine.session_manager import SessionSpec


def _spec(profile_id: str) -> SessionSpec:
    return SessionSpec(tab_profile=TabProfile(id=profile_id), interval_ms=500)


class _FakeSource:
    def __init__(self):
        self.adopted: list[str] = []

    async def scan_tabs(self):
        return []

    async def adopt_tab(self, tab_id: str) -> TabHandle:
        self.adopted.append(tab_id)
        return TabHandle(tab_id=tab_id, native=object())


# --- picker mapping / gating --------------------------------------------------


def test_unassigned_and_all_assigned():
    a = TabAssignment()
    assert a.unassigned(["s0", "s1"]) == ["s0", "s1"]
    assert a.all_assigned(["s0", "s1"]) is False

    a.assign("s0", BrowserTab(tab_id="tab-1", title="A", url="https://a/"))
    assert a.unassigned(["s0", "s1"]) == ["s1"]
    assert a.all_assigned(["s0"]) is True

    a.clear("s0")
    assert a.unassigned(["s0"]) == ["s0"]


async def test_tab_provider_adopts_the_assigned_tab():
    source = _FakeSource()
    assignment = TabAssignment()
    assignment.assign("s0", BrowserTab(tab_id="tab-7", title="Dash", url="https://x/"))
    provide = make_tab_provider(source, assignment)

    handle = await provide(_spec("s0"))

    assert handle.tab_id == "tab-7"
    assert source.adopted == ["tab-7"]


async def test_tab_provider_blocks_start_without_assignment():
    provide = make_tab_provider(_FakeSource(), TabAssignment())
    with pytest.raises(UnassignedSessionError, match="s0"):
        await provide(_spec("s0"))


# --- local persistence (metadata only) ----------------------------------------


def test_save_and_load_roundtrip(tmp_path):
    a = TabAssignment()
    a.assign("s0", BrowserTab(tab_id="tab-1", title="Alpha", url="https://a/"))
    a.assign("s1", BrowserTab(tab_id="tab-2", title="Bravo", url="https://b/"))
    path = tmp_path / "sub" / "assignment.json"

    save_assignment(path, a)
    loaded = load_assignment(path)

    assert loaded.get("s0") == BrowserTab(tab_id="tab-1", title="Alpha", url="https://a/")
    assert loaded.get("s1").url == "https://b/"


def test_saved_file_contains_no_credentials(tmp_path):
    a = TabAssignment()
    a.assign("s0", BrowserTab(tab_id="tab-1", title="Alpha", url="https://a/"))
    path = tmp_path / "assignment.json"
    save_assignment(path, a)
    text = path.read_text()
    assert "tab-1" in text and "Alpha" in text
    for forbidden in ("cookie", "password", "token", "credential"):
        assert forbidden not in text.lower()


def test_load_missing_file_is_empty(tmp_path):
    assert load_assignment(tmp_path / "nope.json").as_dict() == {}


def test_load_corrupt_file_is_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert load_assignment(p).as_dict() == {}


# --- end to end through create_application ------------------------------------


class _FakeAttendedBrowser(_FakeSource):
    """A BrowserPort that also discovers/adopts tabs, over no real browser."""

    def __init__(self):
        super().__init__()
        self.started = False

    async def start(self):
        self.started = True

    async def stop(self):
        self.started = False

    async def open_tab(self, profile):  # never used in attended mode
        raise AssertionError("attended sessions must adopt, not open_tab")

    async def navigate(self, tab, url):
        pass

    async def close_tab(self, tab):
        pass

    def list_tabs(self):
        return []


def _attended_app(assignment):
    from bap.app.composition import create_application
    from bap.config.config_loader import load_config_from_string
    from tests.loadkit import make_config

    browser = _FakeAttendedBrowser()
    return create_application(
        load_config_from_string(make_config(1)),
        browser=browser,
        tab_provider=make_tab_provider(browser, assignment),
    ), browser


async def test_session_adopts_assigned_tab_and_ticks():
    assignment = TabAssignment()
    assignment.assign("s0", BrowserTab(tab_id="tab-1", title="Dash", url="https://x/"))
    app, browser = _attended_app(assignment)

    await app.create_sessions()
    assert browser.adopted == ["tab-1"]          # adopted, not opened
    await app.scheduler.run_once()               # the normal tick pipeline runs
    await app.stop()


async def test_start_is_blocked_when_a_session_is_unassigned():
    app, _ = _attended_app(TabAssignment())      # nothing assigned
    with pytest.raises(UnassignedSessionError, match="s0"):
        await app.create_sessions()
    await app.stop()
