"""Forge World Manager GUI: worlds table + CRUD, hostname auto-reattachment,
explicit Open/Close Browser, and Start gating on the launch-time world set."""

from __future__ import annotations

from concurrent.futures import Future

import pytest

pytest.importorskip("PySide6")

from bap.app.attended import TabAssignment
from bap.core.domain.models import BrowserTab
from bap.forge.worlds import World, WorldStore
from bap.gui import forge_panel
from bap.gui.forge_panel import WorldDialog
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge


def _done(value=None):
    f: Future = Future()
    f.set_result(value)
    return f


class FakeService:
    def __init__(self, profile_ids=("Main", "Farm")):
        self._profile_ids = profile_ids
        self.calls = []

    @property
    def profile_ids(self):
        return self._profile_ids

    def start_runtime(self):
        self.calls.append("start")

    def stop_runtime(self):
        self.calls.append("stop")
        return _done()

    def shutdown_runtime(self):
        self.calls.append("shutdown")
        return _done()

    def add_world_session(self, spec):
        self.calls.append(("add_world_session", spec.profile_id))
        return _done()

    def remove_world_session(self, profile_id):
        self.calls.append(("remove_world_session", profile_id))
        return _done()

    def edit_world_session(self, spec):
        self.calls.append(("edit_world_session", spec.profile_id))
        return _done()

    def open_browser(self):
        self.calls.append("open_browser")
        return _done()

    def close_browser(self):
        self.calls.append("close_browser")
        return _done()

    def scan_tabs(self):
        self.calls.append("scan_tabs")
        return _done([])

    def tick_once(self):
        self.calls.append("tick")

    def stop_loop(self):
        self.calls.append("stop_loop")


def _store():
    store = WorldStore()  # path-less: no disk writes in tests
    store.add(World(alias="Main", hostname="cz8.forgeofempires.com"))
    store.add(World(alias="Farm", hostname="cz1.forgeofempires.com"))
    return store


@pytest.fixture
def forge_window(qapp):
    service = FakeService()
    store = _store()
    win = MainWindow(
        service, QtReportBridge(), forge=True, world_store=store, assignment=TabAssignment()
    )
    yield win, service, store
    win._browser_open = False  # avoid the exit prompt blocking teardown
    win.close()


def test_title_and_world_rows(forge_window):
    win, _, _ = forge_window
    assert "Forge" in win.windowTitle()
    assert win.worlds_table.rowCount() == 2
    assert win.worlds_table.item(0, 0).text() == "Main"
    assert win.worlds_table.item(0, 1).text() == "cz8.forgeofempires.com"
    assert set(win._pickers) == {"Main", "Farm"}


def test_browser_controls_state(forge_window):
    win, _, _ = forge_window
    assert win.scan_button.isEnabled() is False
    assert win.close_browser_button.isEnabled() is False
    win._bridge.browser_ready.emit()
    assert win.scan_button.isEnabled() is True
    assert win.close_browser_button.isEnabled() is True
    assert win.open_browser_button.isEnabled() is False


def test_close_browser_drives_service_and_resets(forge_window):
    win, service, _ = forge_window
    win._bridge.browser_ready.emit()
    win.close_browser_button.click()
    assert "close_browser" in service.calls
    win._bridge.browser_closed.emit()
    assert win.open_browser_button.isEnabled() is True
    assert win.scan_button.isEnabled() is False


def test_hostname_auto_reattach_on_scan(forge_window):
    win, _, _ = forge_window
    # Tab ids are unrelated to any prior session; matching is by hostname.
    tabs = [
        BrowserTab("tab-77", "cz8", "https://cz8.forgeofempires.com/game/index"),
        BrowserTab("tab-4", "cz1", "https://cz1.forgeofempires.com/game/index"),
        BrowserTab("tab-9", "mail", "https://mail.google.com/"),
    ]
    win._bridge.tabs_scanned.emit(tabs)

    assert win._pickers["Main"].currentData().tab_id == "tab-77"
    assert win._pickers["Farm"].currentData().tab_id == "tab-4"
    # Every launch-time world reattached -> Start is enabled.
    assert win.start_button.isEnabled() is True


def test_start_gate_when_a_world_has_no_matching_tab(forge_window):
    win, _, _ = forge_window
    win._bridge.tabs_scanned.emit(
        [BrowserTab("t1", "cz8", "https://cz8.forgeofempires.com/game")]  # Farm missing
    )
    assert win._pickers["Main"].currentData().tab_id == "t1"
    assert win._pickers["Farm"].currentData() is None
    assert win.start_button.isEnabled() is False  # Farm unassigned -> gated


def test_add_world_is_live_no_restart(forge_window, monkeypatch):
    win, service, store = forge_window
    new = World(alias="H", hostname="cz3.forgeofempires.com", max_weakening_pct=40)
    monkeypatch.setattr(WorldDialog, "get_world", staticmethod(lambda *a, **k: new))

    win._on_add_world()

    assert "H" in store.aliases()
    assert win.worlds_table.rowCount() == 3
    # Hot CRUD: the new world immediately gets a picker and a live plan entry.
    assert "H" in win._pickers
    assert ("add_world_session", "H") in service.calls


def test_remove_world_drops_session_not_tab(forge_window, monkeypatch):
    win, service, store = forge_window
    monkeypatch.setattr(forge_panel, "confirm_remove", lambda *a, **k: True)
    win._selected_alias = "Farm"

    win._on_remove_world()

    assert store.aliases() == ["Main"]
    assert win.worlds_table.rowCount() == 1
    assert "Farm" not in win._pickers  # picker removed live
    assert ("remove_world_session", "Farm") in service.calls


def test_edit_world_applies_live(forge_window, monkeypatch):
    win, service, store = forge_window
    edited = World(alias="Main", hostname="cz8.forgeofempires.com", interval_ms=2500)
    monkeypatch.setattr(WorldDialog, "get_world", staticmethod(lambda *a, **k: edited))
    win._selected_alias = "Main"

    win._on_edit_world()

    assert store.get("Main").interval_ms == 2500
    assert ("edit_world_session", "Main") in service.calls


def test_stop_is_automation_only_never_closes_browser(forge_window):
    # The Stop button must route to stop_runtime (automation only); the browser
    # close is a separate, explicit control.
    win, service, _ = forge_window
    win._on_stop_clicked()
    assert "stop" in service.calls
    assert "close_browser" not in service.calls


def test_capture_only_status_is_shown(forge_window):
    win, _, _ = forge_window
    assert "CAPTURE ONLY" in win.forge_status.text()
    # Per-world rules/actions columns both read 0 (observe-only).
    header = [win.worlds_table.horizontalHeaderItem(c).text()
              for c in range(win.worlds_table.columnCount())]
    assert "Rules" in header and "Actions" in header
    rules_col, actions_col = header.index("Rules"), header.index("Actions")
    assert win.worlds_table.item(0, rules_col).text() == "0"
    assert win.worlds_table.item(0, actions_col).text() == "0"


def test_monitor_table_says_world_not_profile(forge_window):
    win, _, _ = forge_window
    assert win.table.horizontalHeaderItem(0).text() == "World"


def test_exit_prompt_keep_browser_open(forge_window, monkeypatch):
    win, service, _ = forge_window
    win._browser_open = True
    monkeypatch.setattr(win, "_ask_exit_choice", lambda: "keep")

    win.close()

    # Keeping Chromium => automation-only stop, never a full shutdown/close.
    assert "stop" in service.calls
    assert "shutdown" not in service.calls


def test_exit_prompt_cancel_aborts_close(forge_window, monkeypatch):
    win, service, _ = forge_window
    win._browser_open = True
    monkeypatch.setattr(win, "_ask_exit_choice", lambda: "cancel")

    from PySide6.QtGui import QCloseEvent

    event = QCloseEvent()
    win.closeEvent(event)

    assert event.isAccepted() is False
    assert "shutdown" not in service.calls and "stop" not in service.calls
    win._browser_open = False  # let the fixture teardown close cleanly


# --- WorldDialog validation (no exec) ----------------------------------------


def test_world_dialog_builds_valid_world(qapp):
    dialog = WorldDialog(existing=None)
    dialog.alias_edit.setText("New")
    dialog.host_edit.setText("https://cz5.forgeofempires.com/game/index")
    dialog._on_accept()
    world = dialog.world()
    assert world is not None
    assert world.alias == "New"
    assert world.hostname == "cz5.forgeofempires.com"


def test_world_dialog_rejects_non_forge_host_with_message(qapp):
    dialog = WorldDialog(existing=None)
    dialog.alias_edit.setText("Bad")
    dialog.host_edit.setText("https://example.com/game")
    dialog._on_accept()
    assert dialog.world() is None
    assert "not a Forge server" in dialog.error_label.text()


def test_world_dialog_prefills_from_scanned_tab(qapp):
    tabs = [
        BrowserTab("t1", "cz8 | Main", "https://cz8.forgeofempires.com/game/index"),
        BrowserTab("t2", "mail", "https://mail.google.com/"),  # non-forge, filtered out
    ]
    dialog = WorldDialog(existing=None, detected_tabs=tabs)
    # Only the Forge tab is offered (placeholder + 1).
    assert dialog.detected_combo is not None
    assert dialog.detected_combo.count() == 2

    dialog.detected_combo.setCurrentIndex(1)  # pick the cz8 tab
    assert dialog.host_edit.text() == "cz8.forgeofempires.com"  # hostname auto-filled
    assert dialog.title_edit.text() == "cz8 | Main"

    dialog.alias_edit.setText("Main")  # user only types the alias
    dialog._on_accept()
    world = dialog.world()
    assert world is not None
    assert world.hostname == "cz8.forgeofempires.com"
    assert world.last_url == "https://cz8.forgeofempires.com/game/index"
