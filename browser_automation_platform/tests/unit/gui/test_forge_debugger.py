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


def _forge_window(qapp, capture_callback=None, worlds=(("Main", "cz8.forgeofempires.com"),)):
    store = WorldStore()
    for alias, host in worlds:
        store.add(World(alias=alias, hostname=host))
    win = MainWindow(
        _FakeService(), QtReportBridge(), forge=True, world_store=store,
        assignment=TabAssignment(), capture_callback=capture_callback,
    )
    return win, store


def test_test_scan_combo_routes_to_explicitly_selected_world(qapp):
    # With H and F both attached, selecting F must scan F — never the first World.
    calls = []

    def cb(tab_id):
        calls.append(tab_id)
        return cv2.imencode(".png", _frame_with_emblem())[1].tobytes()

    win, _ = _forge_window(qapp, capture_callback=cb,
                           worlds=(("H", "cz8.forgeofempires.com"), ("F", "cz6.forgeofempires.com")))
    try:
        win._assignment.assign("H", BrowserTab("tab-H", "cz8", "https://cz8.forgeofempires.com/"))
        win._assignment.assign("F", BrowserTab("tab-F", "cz6", "https://cz6.forgeofempires.com/"))
        win._browser_open = True
        win._refresh_test_scan_combo()
        idx = win.test_scan_combo.findData("F")
        win.test_scan_combo.setCurrentIndex(idx)
        assert "Alias: F" in win.test_scan_target_label.text()
        win._on_test_scan_live()
        assert calls == ["tab-F"]                  # F scanned F, not the first World
    finally:
        if win._debugger is not None:
            win._debugger.close()
        win._browser_open = False
        win.close()


def test_scan_all_opens_summary_with_one_row_per_world(qapp):
    def cb(tab_id):
        return cv2.imencode(".png", _frame_with_emblem())[1].tobytes()

    win, _ = _forge_window(qapp, capture_callback=cb,
                           worlds=(("H", "cz8.forgeofempires.com"), ("F", "cz6.forgeofempires.com")))
    try:
        win._assignment.assign("H", BrowserTab("tab-H", "cz8", "https://cz8.forgeofempires.com/"))
        win._assignment.assign("F", BrowserTab("tab-F", "cz6", "https://cz6.forgeofempires.com/"))
        win._browser_open = True
        win._refresh_test_scan_combo()
        win._on_scan_all()
        table = win._scan_all_window.table
        assert table.rowCount() == 2
        aliases = {table.item(r, 0).text() for r in range(2)}
        assert aliases == {"H", "F"}
        # Each row has an inspectable "Open result" button (last column).
        assert win._scan_all_window.table.cellWidget(0, table.columnCount() - 1) is not None
    finally:
        if getattr(win, "_scan_all_window", None) is not None:
            win._scan_all_window.close()
        win._browser_open = False
        win.close()


def test_annotate_preview_has_no_banner_over_top_bar(qapp):
    # The debugger's rendered image must not paint a banner over the top rows —
    # that is where the Forge weakening top bar lives.
    from bap.forge.detection.scan import annotate
    img = np.full((900, 1600, 3), 180, np.uint8)
    win = DebuggerWindow(img, source="live")
    try:
        vis = annotate(img, win._scan)
        assert np.array_equal(vis[0:6, :, :], img[0:6, :, :])   # top strip untouched
        # Observe-only status still present outside the image.
        assert "OBSERVE ONLY" in win.details.toPlainText()
        assert "OBSERVE ONLY" in win.windowTitle()
    finally:
        win.close()


def test_label_in_review_mode_saves_frame_and_opens_review(qapp, tmp_path):
    img = _frame_with_emblem()
    win = DebuggerWindow(img, source="H (live)", live_review_dir=tmp_path)
    try:
        win._on_label_review()
        # The live capture was persisted as a Review-Mode frame under the world tag.
        frames = list((tmp_path / "frames").glob("H_*.png"))
        assert len(frames) == 1
        assert win._review is not None                 # Review Mode window opened
    finally:
        if win._review is not None:
            win._review.close()
        win.close()


def test_test_scan_buttons_exist(qapp):
    win, _ = _forge_window(qapp)
    try:
        assert win.test_scan_live_button.text() == "Test Scan Live World"
        assert win.open_offline_button.text().startswith("Open Offline")
        assert win.scan_all_button.text().startswith("Scan All")
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
        # Assign a tab to the world and mark the browser open, then Test Scan Live.
        win._assignment.assign("Main", BrowserTab("tab-7", "cz8", "https://cz8.forgeofempires.com/"))
        win._browser_open = True
        win._refresh_test_scan_combo()
        win._on_test_scan_live()
        assert captured["tab"] == "tab-7"          # live read-only capture used
        assert win._debugger is not None            # observe-only debugger opened
        assert len(win._debugger._scan.detections) == 1
    finally:
        if win._debugger is not None:
            win._debugger.close()
        win._browser_open = False
        win.close()


def test_test_scan_live_disabled_and_errors_when_unattached(qapp, monkeypatch):
    # No tab assigned: Live is disabled, and invoking it never opens a file
    # picker or scans another World — it reports a clear error.
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    def _no_picker(*a, **k):
        raise AssertionError("offline file picker must not open for a broken live mapping")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(_no_picker))
    warnings = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.setdefault("shown", a)))

    win, _ = _forge_window(qapp)
    try:
        win._browser_open = True
        win._refresh_test_scan_combo()
        assert win.test_scan_live_button.isEnabled() is False   # unattached -> disabled
        win._on_test_scan_live()
        assert win._debugger is None
        assert "shown" in warnings                              # clear error surfaced
    finally:
        win._browser_open = False
        win.close()
