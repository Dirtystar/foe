"""Attended GUI: tab picker populates, and Start is gated until every session
has a tab assigned."""

from __future__ import annotations

from concurrent.futures import Future

import pytest

pytest.importorskip("PySide6")

from bap.app.attended import TabAssignment
from bap.core.domain.models import BrowserTab
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge


class FakeService:
    def __init__(self, profile_ids=("session_1", "session_2")):
        self._profile_ids = profile_ids
        self.calls = []

    @property
    def profile_ids(self):
        return self._profile_ids

    def start_runtime(self):
        self.calls.append("start")

    def stop_runtime(self):
        self.calls.append("stop")

    def shutdown_runtime(self):
        self.calls.append("shutdown")
        f: Future = Future()
        f.set_result(None)
        return f

    def close_browser(self):
        self.calls.append("close_browser")
        f: Future = Future()
        f.set_result(None)
        return f

    def tick_once(self):
        self.calls.append("tick")

    def stop_loop(self):
        self.calls.append("stop_loop")

    def open_browser(self):
        self.calls.append("open_browser")
        f: Future = Future()
        f.set_result(None)
        return f

    def scan_tabs(self):
        self.calls.append("scan_tabs")
        f: Future = Future()
        f.set_result([BrowserTab("tab-1", "Dashboard", "https://x/")])
        return f


@pytest.fixture
def attended_window(qapp):
    service = FakeService()
    bridge = QtReportBridge()
    assignment = TabAssignment()
    win = MainWindow(service, bridge, attended=True, assignment=assignment)
    yield win, service, bridge, assignment
    win.close()


_TABS = [BrowserTab("tab-1", "Dashboard", "https://x/"), BrowserTab("tab-2", "Mail", "https://m/")]


def test_attended_panel_has_a_picker_per_session(attended_window):
    win, _, _, _ = attended_window
    assert set(win._pickers) == {"session_1", "session_2"}
    assert win.scan_button.isEnabled() is False       # until browser opened
    assert win.start_button.isEnabled() is False      # until assigned


def test_browser_ready_enables_scan(attended_window):
    win, _, bridge, _ = attended_window
    bridge.browser_ready.emit()
    assert win.scan_button.isEnabled() is True


def test_scan_signal_populates_pickers(attended_window):
    win, _, bridge, _ = attended_window
    bridge.tabs_scanned.emit(_TABS)
    combo = win._pickers["session_1"]
    assert combo.count() == 3                          # placeholder + 2 tabs
    assert combo.isEnabled() is True
    assert "Dashboard" in combo.itemText(1)


def test_start_gate_requires_every_session_assigned(attended_window):
    win, _, _, assignment = attended_window
    win._populate_tab_pickers(_TABS)
    assert win.start_button.isEnabled() is False       # none picked yet

    win._pickers["session_1"].setCurrentIndex(1)       # only one assigned
    assert win.start_button.isEnabled() is False

    win._pickers["session_2"].setCurrentIndex(2)       # now both
    assert win.start_button.isEnabled() is True
    assert {k: v.tab_id for k, v in assignment.as_dict().items()} == {
        "session_1": "tab-1", "session_2": "tab-2",
    }

    win._pickers["session_1"].setCurrentIndex(0)       # unassign one -> gate closes
    assert win.start_button.isEnabled() is False


def test_scan_button_drives_the_service(attended_window):
    win, service, bridge, _ = attended_window
    bridge.browser_ready.emit()
    win.scan_button.click()
    assert "scan_tabs" in service.calls


def test_open_browser_button_drives_the_service(attended_window):
    win, service, _, _ = attended_window
    win.open_browser_button.click()
    assert "open_browser" in service.calls


def test_previous_assignment_is_preselected(qapp):
    service = FakeService()
    assignment = TabAssignment()
    assignment.assign("session_1", BrowserTab("tab-2", "Mail", "https://m/"))
    win = MainWindow(service, QtReportBridge(), attended=True, assignment=assignment)
    try:
        win._populate_tab_pickers(_TABS)
        # session_1 remembered tab-2 (index 2); the picker restores it.
        assert win._pickers["session_1"].currentData().tab_id == "tab-2"
    finally:
        win.close()
