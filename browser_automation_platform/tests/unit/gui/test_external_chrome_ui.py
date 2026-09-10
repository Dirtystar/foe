"""Worlds-page External-Chrome connection UI (Milestone 4.16) — offscreen.

In External Chrome mode the Browser card shows the CDP endpoint, Test Connection,
Attach, and Disconnect — and never an "Open Browser" button (BAP does not open the
operator's Chrome). Managed mode is unchanged. Observe-only throughout.
"""

from __future__ import annotations

from concurrent.futures import Future

import pytest

pytest.importorskip("PySide6")

from bap.app.attended import TabAssignment
from bap.forge.browser_settings import BrowserMode, BrowserSettings
from bap.forge.worlds import World, WorldStore
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge


class _FakeService:
    def __init__(self):
        self._profile_ids = ()

    @property
    def profile_ids(self):
        return self._profile_ids

    def _f(self, v=None):
        f: Future = Future(); f.set_result(v); return f

    def start_runtime(self): pass
    def stop_runtime(self): return self._f()
    def shutdown_runtime(self): return self._f()
    def open_browser(self): return self._f()
    def close_browser(self): return self._f()
    def scan_tabs(self): return self._f([])
    def stop_loop(self): pass


def _window(qapp, settings):
    store = WorldStore()
    store.add(World(alias="H", hostname="cz8.forgeofempires.com"))
    return MainWindow(
        _FakeService(), QtReportBridge(), forge=True, world_store=store,
        assignment=TabAssignment(), browser_settings=settings,
    )


def test_external_mode_shows_cdp_controls_and_no_open_browser(qapp):
    win = _window(qapp, BrowserSettings(mode=BrowserMode.EXTERNAL, cdp_endpoint="http://127.0.0.1:9222"))
    try:
        assert win._external_chrome is True
        assert win.browser_mode_combo.currentData() == BrowserMode.EXTERNAL.value
        assert win.cdp_endpoint_edit.text() == "http://127.0.0.1:9222"
        assert win.test_conn_button.text() == "Test Connection"
        # The lifecycle buttons are Attach / Disconnect — never "Open Browser".
        assert win.open_browser_button.text() == "Attach Chrome"
        assert win.close_browser_button.text() == "Disconnect"
        assert "Open Browser" not in win.open_browser_button.text()
        # Localhost endpoint: no warning; the launch command is shown.
        assert win.localhost_warning_label.text() == ""
        assert "--remote-debugging-port=9222" in win.launch_command_label.text()
    finally:
        win.close()


def test_managed_mode_keeps_open_close(qapp):
    win = _window(qapp, BrowserSettings(mode=BrowserMode.MANAGED))
    try:
        assert win._external_chrome is False
        assert win.open_browser_button.text() == "Open Browser"
        assert win.close_browser_button.text() == "Close Browser"
    finally:
        win.close()


def test_non_localhost_endpoint_warns(qapp):
    win = _window(qapp, BrowserSettings(mode=BrowserMode.EXTERNAL, cdp_endpoint="http://10.0.0.9:9222"))
    try:
        win.cdp_endpoint_edit.setText("http://10.0.0.9:9222")
        win._refresh_external_chrome_ui()
        assert "not localhost" in win.localhost_warning_label.text()
    finally:
        win.close()


def test_test_connection_updates_status(qapp, monkeypatch, tmp_path):
    import bap.adapters.browser.cdp_attach_adapter as cdp
    import bap.forge.browser_settings as bs

    monkeypatch.setattr(bs, "default_settings_path", lambda: tmp_path / "browser_settings.json")
    monkeypatch.setattr(cdp, "probe_cdp",
                        lambda ep, **k: {"reachable": True, "browser": "Chrome/120",
                                         "tabs": 3, "forge_tabs": 2, "localhost": True})
    win = _window(qapp, BrowserSettings(mode=BrowserMode.EXTERNAL))
    try:
        win._on_test_connection()
        assert "Reachable" in win.connection_status_label.text()
        assert "Chrome/120" in win.connection_status_label.text()
    finally:
        win.close()


def test_mode_change_persists_and_notes_restart(qapp, monkeypatch, tmp_path):
    import bap.forge.browser_settings as bs

    path = tmp_path / "browser_settings.json"
    monkeypatch.setattr(bs, "default_settings_path", lambda: path)
    # Launched Managed; switch the dropdown to External -> persisted + restart note.
    win = _window(qapp, BrowserSettings(mode=BrowserMode.MANAGED))
    try:
        idx = win.browser_mode_combo.findData(BrowserMode.EXTERNAL.value)
        win.browser_mode_combo.setCurrentIndex(idx)
        assert bs.load_browser_settings(path).mode is BrowserMode.EXTERNAL
        assert "Restart" in win.browser_mode_note.text()
    finally:
        win.close()
