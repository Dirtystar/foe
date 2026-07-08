import pytest

pytest.importorskip("PySide6")

from bap.core.engine.tab_session import TickStatus
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge

from _reports import make_report


class FakeService:
    def __init__(self, profile_ids=("p1", "p2")):
        self._profile_ids = profile_ids
        self.calls = []

    @property
    def profile_ids(self):
        return self._profile_ids

    def start_runtime(self):
        self.calls.append("start")

    def stop_runtime(self):
        self.calls.append("stop")

    def tick_once(self):
        self.calls.append("tick")

    def stop_loop(self):
        self.calls.append("stop_loop")


def _cell(window, row, col):
    return window.table.item(row, col).text()


@pytest.fixture
def window(qapp):
    service = FakeService()
    bridge = QtReportBridge()
    win = MainWindow(service, bridge)
    yield win, service, bridge
    win.close()


# --- construction -------------------------------------------------------------


def test_window_builds_a_row_per_session(window):
    win, _, _ = window

    assert win.table.rowCount() == 2
    assert _cell(win, 0, 0) == "p1"
    assert _cell(win, 1, 0) == "p2"


def test_controls_exist_and_reflect_stopped_state(window):
    win, _, _ = window

    assert win.start_button.isEnabled()
    assert not win.stop_button.isEnabled()
    assert win.tick_button.isEnabled()
    assert win.state_label.text() == "stopped"


# --- control commands ---------------------------------------------------------


def test_buttons_invoke_service_commands(window):
    win, service, bridge = window

    win.start_button.click()  # enabled while stopped
    win.tick_button.click()   # enabled while stopped
    bridge.state_changed.emit("running")  # Stop becomes enabled, Start/Tick disabled
    win.stop_button.click()

    assert service.calls == ["start", "tick", "stop"]


def test_disabled_buttons_do_not_invoke_commands_for_current_state(window):
    win, service, _ = window
    # In the stopped state Stop is disabled; clicking it must be a no-op.
    win.stop_button.click()

    assert service.calls == []


# --- event-to-view updates ----------------------------------------------------


def test_report_updates_the_matching_session_row(window):
    win, _, bridge = window

    bridge.report_received.emit(
        make_report(profile_id="p2", tick=4, matched=1, rules_total=2, actions_ok=1, actions_total=1)
    )

    assert _cell(win, 1, 1) == "completed"
    assert _cell(win, 1, 2) == "4"
    assert _cell(win, 1, 3) == "1/2 matched"
    assert _cell(win, 1, 4) == "1/1 ok"
    assert "[p2] tick #4" in win.log.toPlainText()


def test_report_for_unknown_profile_appends_a_new_row(window):
    win, _, bridge = window

    bridge.report_received.emit(make_report(profile_id="late", tick=1))

    assert win.table.rowCount() == 3
    assert _cell(win, 2, 0) == "late"


def test_runtime_failure_is_shown_in_the_row_and_log(window):
    win, _, bridge = window

    bridge.report_received.emit(
        make_report(profile_id="p1", status=TickStatus.INTERNAL_ERROR, error=RuntimeError("boom"))
    )

    assert _cell(win, 0, 1) == "internal_error"
    assert "boom" in _cell(win, 0, 5)
    assert "boom" in win.log.toPlainText()


def test_error_signal_is_logged(window):
    win, _, bridge = window

    bridge.error_occurred.emit("scheduler exploded")

    assert "ERROR: scheduler exploded" in win.log.toPlainText()


def test_state_change_toggles_controls(window):
    win, _, bridge = window

    bridge.state_changed.emit("running")

    assert not win.start_button.isEnabled()
    assert win.stop_button.isEnabled()
    assert not win.tick_button.isEnabled()
    assert win.state_label.text() == "running"


def test_close_stops_the_runtime_loop(window):
    win, service, _ = window

    win.close()

    assert "stop_loop" in service.calls
