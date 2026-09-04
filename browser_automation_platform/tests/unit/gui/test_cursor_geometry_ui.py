"""M5A.1 GUI wiring: the debugger's Set-Browser-Content-Origin action, and
MainWindow building a calibrated WindowGeometry from the persisted content origin.
"""

from __future__ import annotations

from concurrent.futures import Future

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")

from bap.app.attended import TabAssignment
from bap.forge.browser_settings import BrowserMode, BrowserSettings
from bap.forge.cursor.context import CursorPreviewContext
from bap.forge.worlds import World, WorldStore
from bap.gui.forge_debugger import DebuggerWindow
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge


def _frame():
    return np.zeros((1080, 1920, 3), np.uint8)


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


def _main_window(qapp, settings=None):
    store = WorldStore()
    store.add(World(alias="H", hostname="cz8.forgeofempires.com"))
    return MainWindow(_FakeService(), QtReportBridge(), forge=True, world_store=store,
                      assignment=TabAssignment(),
                      browser_settings=settings or BrowserSettings(mode=BrowserMode.EXTERNAL))


def test_set_content_origin_button_runs_calibration(qapp):
    called = {"n": 0}

    def calibrate():
        called["n"] += 1
        return True

    ctx = CursorPreviewContext(
        world_alias="H", hostname="cz8.forgeofempires.com", browser_mode="external_chrome",
        tab_id_at_scan="t1", live=True, captured_at=None, capture_w=1920, capture_h=1080,
        calibrate_content_origin=calibrate)

    class _Ctl:
        enabled = False
        def enable_for_session(self): pass
    win = DebuggerWindow(_frame(), source="H (live)", cursor_controller=_Ctl(), cursor_context=ctx)
    try:
        assert win.calibrate_origin_button.isEnabled() is True
        win._on_calibrate_content_origin()
        assert called["n"] == 1
        assert "saved" in win.cursor_result_label.text().lower()
    finally:
        win.close()


def test_mainwindow_builds_calibrated_geometry_from_persisted_origin(qapp, tmp_path, monkeypatch):
    import bap.forge.cursor.window_geometry as wg

    monkeypatch.setattr(wg, "default_calibration_path", lambda: tmp_path / "cal.json")
    win = _main_window(qapp)
    try:
        img = _frame()
        meta = {"browser_mode": "external_chrome", "cdp_endpoint": "http://127.0.0.1:9222",
                "device_pixel_ratio": 1.0, "zoom": 1.0}
        # No calibration yet → geometry unavailable → gate would block.
        assert win._window_geometry(img, meta) is None
        # Persist a content origin for the exact key, then geometry is available.
        key = win._calibration_key(img, meta)
        win._content_calibration().set(key, (100, 200, 2020, 1280))
        geom = win._window_geometry(img, meta)
        assert geom is not None
        assert geom.is_calibrated is True
        assert geom.content_rect == (100, 200, 2020, 1280)
        # And the transform maps a viewport-centre point onto that content rect.
        from bap.forge.cursor.geometry import image_to_screen
        t = image_to_screen((960, 540), geom)
        assert t.screen_physical == (100 + 960, 200 + 540) == (1060, 740)
    finally:
        win.close()


def test_geometry_key_changes_invalidate_calibration(qapp, tmp_path, monkeypatch):
    import bap.forge.cursor.window_geometry as wg

    monkeypatch.setattr(wg, "default_calibration_path", lambda: tmp_path / "cal.json")
    win = _main_window(qapp)
    try:
        img = _frame()
        meta = {"browser_mode": "external_chrome", "cdp_endpoint": "e",
                "device_pixel_ratio": 1.0, "zoom": 1.0}
        win._content_calibration().set(win._calibration_key(img, meta), (0, 0, 1920, 1080))
        assert win._window_geometry(img, meta) is not None
        # A changed zoom is a different key → no calibration match → geometry gone.
        meta_zoomed = {**meta, "zoom": 1.25}
        assert win._window_geometry(img, meta_zoomed) is None
    finally:
        win.close()
