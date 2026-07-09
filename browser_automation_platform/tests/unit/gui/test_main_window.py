import pytest

pytest.importorskip("PySide6")

from bap.core.engine.tab_session import TickStatus
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge

from _reports import make_report, sample_metrics


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


def test_operational_status_label_reflects_status_signal(window):
    win, _, bridge = window

    assert win.status_label.text() == "stopped"
    bridge.status_changed.emit("ready", "started")
    assert win.status_label.text() == "ready"
    bridge.status_changed.emit("degraded", "session s0 failed")
    assert win.status_label.text() == "degraded"


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


def _column(win, title):
    for col in range(win.table.columnCount()):
        if win.table.horizontalHeaderItem(col).text() == title:
            return col
    raise AssertionError(f"column {title!r} not found")


def test_report_timing_is_shown_in_the_timing_column(window):
    win, _, bridge = window

    bridge.report_received.emit(
        make_report(profile_id="p1", tick=2, metrics=sample_metrics(total=42, vision=30))
    )

    timing_col = _column(win, "Timing")
    assert "42ms" in _cell(win, 0, timing_col)
    assert "vis 30" in _cell(win, 0, timing_col)


def test_health_change_updates_health_column_and_log(window):
    win, _, bridge = window

    bridge.health_changed.emit("p2", "recovering", "recovery attempt 1 after capture_failed")

    health_col = _column(win, "Health")
    assert _cell(win, 1, health_col) == "recovering"
    assert "HEALTH [p2] -> recovering" in win.log.toPlainText()


def test_new_rows_seed_a_health_cell(window):
    win, _, bridge = window

    bridge.report_received.emit(make_report(profile_id="late", tick=1))

    health_col = _column(win, "Health")
    assert _cell(win, 2, health_col) == "healthy"


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


# --- non-developer tooling (menu) ---------------------------------------------


def _menu_actions(win, title):
    for action in win.menuBar().actions():
        if action.text() == title and action.menu() is not None:
            return [a.text() for a in action.menu().actions() if a.text()]
    return []


def test_tools_and_help_menus_present(window):
    win, _, _ = window

    top = [a.text() for a in win.menuBar().actions()]
    assert "&Tools" in top and "&Help" in top
    tools = _menu_actions(win, "&Tools")
    assert "Install browser…" in tools
    assert "Export diagnostics…" in tools
    assert "Open data folder" in tools


def test_export_diagnostics_action_invokes_ops(window, monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    import bap.gui.main_window as mw
    import bap.ops.diagnostics as diag

    out = tmp_path / "bap-diagnostics.zip"
    out.write_text("zip")
    called = {}

    def fake_export(*a, **k):
        called["yes"] = True
        return out

    monkeypatch.setattr(diag, "export_diagnostics", fake_export)
    monkeypatch.setattr(mw, "QMessageBox", MagicMock())          # non-blocking
    monkeypatch.setattr(mw, "QDesktopServices", MagicMock())

    win, _, _ = window
    win._export_diagnostics()

    assert called.get("yes") is True
