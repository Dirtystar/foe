"""Offscreen tests for the Vision Debugger window and the World Manager's
Test Scan button — observe-only, never clicks."""

from __future__ import annotations

from concurrent.futures import Future

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.app.attended import TabAssignment
from bap.core.domain.models import BrowserTab
from bap.forge.detection.detector import load_bundled_templates
from bap.forge.worlds import World, WorldStore
from bap.gui.forge_debugger import DebuggerWindow, bgr_to_qimage
from bap.gui.main_window import MainWindow
from bap.gui.qt_bridge import QtReportBridge


def _frame_with_emblem(cx=900, cy=740):
    img = np.zeros((1080, 1920, 3), np.uint8)
    tpl = load_bundled_templates()[0][0]
    h, w = tpl.shape[:2]
    img[cy - h // 2:cy - h // 2 + h, cx - w // 2:cx - w // 2 + w] = tpl
    return img


def test_debugger_window_builds_and_shows_banner(qapp):
    win = DebuggerWindow(_frame_with_emblem(), source="test")
    try:
        assert "OBSERVE ONLY" in win.details.toPlainText()
        assert len(win._scan.detections) == 1
    finally:
        win.close()


def test_bgr_to_qimage_dimensions(qapp):
    img = _frame_with_emblem()
    q = bgr_to_qimage(img)
    assert q.width() == 1920 and q.height() == 1080


class _FakeService:
    def __init__(self):
        self._profile_ids = ("Main",)
        self.calls = []

    @property
    def profile_ids(self):
        return self._profile_ids

    def _f(self, v=None):
        f: Future = Future(); f.set_result(v); return f

    def start_runtime(self): self.calls.append("start")
    def stop_runtime(self): return self._f()
    def shutdown_runtime(self): return self._f()
    def open_browser(self): return self._f()
    def close_browser(self): return self._f()
    def scan_tabs(self): return self._f([])
    def add_world_session(self, spec): return self._f()
    def remove_world_session(self, pid): return self._f()
    def edit_world_session(self, spec): return self._f()
    def stop_loop(self): pass


def _forge_window(qapp, capture_callback=None):
    store = WorldStore()
    store.add(World(alias="Main", hostname="cz8.forgeofempires.com"))
    win = MainWindow(
        _FakeService(), QtReportBridge(), forge=True, world_store=store,
        assignment=TabAssignment(), capture_callback=capture_callback,
    )
    return win, store


def test_test_scan_button_exists(qapp):
    win, _ = _forge_window(qapp)
    try:
        assert win.test_scan_button.text().startswith("Test Scan")
    finally:
        win._browser_open = False
        win.close()


def test_test_scan_live_capture_opens_debugger(qapp):
    png = cv2.imencode(".png", _frame_with_emblem())[1].tobytes()
    captured = {}

    def cb(tab_id):
        captured["tab"] = tab_id
        return png

    win, _ = _forge_window(qapp, capture_callback=cb)
    try:
        # Assign a tab to the world and mark the browser open, then Test Scan.
        win._assignment.assign("Main", BrowserTab("tab-7", "cz8", "https://cz8.forgeofempires.com/"))
        win._browser_open = True
        win._selected_alias = "Main"
        win._on_test_scan()
        assert captured["tab"] == "tab-7"          # live read-only capture used
        assert win._debugger is not None            # observe-only debugger opened
        assert len(win._debugger._scan.detections) == 1
    finally:
        if win._debugger is not None:
            win._debugger.close()
        win._browser_open = False
        win.close()
