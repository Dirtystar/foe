"""Vision Debugger cursor-preview section (Milestone 5A) — offscreen.

Proves the UI wiring: disabled by default, enable is explicit, a blocked gate shows
the reason and never moves, a confirmed valid request moves the cursor exactly once
and reports NO CLICK, Cancel moves nothing, and a debugger with no controller (Scan
All / offline) offers no movement at all.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("PySide6")
np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from bap.adapters.cursor.fake_cursor import FakeCursorPreview
from bap.forge.cursor.audit import CursorPreviewAudit
from bap.forge.cursor.controller import CursorPreviewController
from bap.forge.cursor.geometry import WindowGeometry
from bap.forge.cursor.preview import PreviewRequest
from bap.forge.detection.detector import load_bundled_templates
from bap.forge.detection.weakening import Decision
from bap.gui.forge_debugger import DebuggerWindow


def _frame_with_emblem(cx=900, cy=740):
    img = np.zeros((1080, 1920, 3), np.uint8)
    tpl = load_bundled_templates()[0][0]
    h, w = tpl.shape[:2]
    img[cy - h // 2:cy - h // 2 + h, cx - w // 2:cx - w // 2 + w] = tpl
    return img


class _ValidContext:
    """A cursor context that returns a fully-valid PreviewRequest, so the GUI move
    path is deterministic without fabricating a live CONTINUE scan."""

    def __init__(self):
        self.cursor_position_getter = None
        g = WindowGeometry(window_x=100, window_y=50, window_w=1000, window_h=800,
                           content_offset_x=8, content_offset_y=72, device_pixel_ratio=1.0,
                           viewport_w=1920, viewport_h=1080, capture_w=1920, capture_h=1080,
                           monitor_scale=1.0, window_id="w1")
        self._g = g

    def build_request(self, *, enabled, target_point, pct, confidence, weakening_value,
                      world_limit, decision):
        return PreviewRequest(
            enabled=enabled, live=True, browser_mode="external_chrome", window_owned=True,
            world_alias="H", hostname="cz8.forgeofempires.com", selected_alias="H",
            tab_id_at_scan="t1", current_tab_id="t1", target_point=(900, 740), pct=60,
            confidence=0.9, weakening_value=10, world_limit=80, decision=Decision.CONTINUE,
            capture_w=1920, capture_h=1080, captured_at=datetime.now(timezone.utc),
            geometry_at_scan=self._g, current_geometry=self._g, max_age_s=5.0)


def _debugger(controller=None, context=None):
    return DebuggerWindow(_frame_with_emblem(), source="H (live)",
                          cursor_controller=controller, cursor_context=context)


def test_section_unavailable_without_controller(qapp):
    win = _debugger(controller=None, context=None)
    try:
        assert "UNAVAILABLE" in win.cursor_state_label.text()
        assert win.enable_cursor_button.isEnabled() is False
        assert win.preview_cursor_button.isEnabled() is False
    finally:
        win.close()


def test_disabled_by_default_then_enable_for_session(qapp, tmp_path):
    ctl = CursorPreviewController(FakeCursorPreview(), CursorPreviewAudit(tmp_path / "a.jsonl"))
    win = _debugger(controller=ctl, context=_ValidContext())
    try:
        assert "DISABLED" in win.cursor_state_label.text()
        assert win.preview_cursor_button.isEnabled() is False
        win._on_enable_cursor_preview()
        assert ctl.enabled is True
        assert "ENABLED" in win.cursor_state_label.text()
        assert win.preview_cursor_button.isEnabled() is True
    finally:
        win.close()


def test_confirmed_valid_request_moves_once_and_reports_no_click(qapp, tmp_path, monkeypatch):
    cursor = FakeCursorPreview()
    ctl = CursorPreviewController(cursor, CursorPreviewAudit(tmp_path / "a.jsonl"))
    win = _debugger(controller=ctl, context=_ValidContext())
    try:
        win._on_enable_cursor_preview()
        monkeypatch.setattr(win, "_confirm_cursor_move", lambda decision: True)  # operator confirms
        win._on_preview_cursor_target()
        assert cursor.move_count == 1
        assert cursor.last == (1008, 862)                 # 100+8+900, 50+72+740
        assert "NO CLICK PERFORMED" in win.cursor_result_label.text()
    finally:
        win.close()


def test_cancel_moves_nothing(qapp, tmp_path, monkeypatch):
    cursor = FakeCursorPreview()
    ctl = CursorPreviewController(cursor, CursorPreviewAudit(tmp_path / "a.jsonl"))
    win = _debugger(controller=ctl, context=_ValidContext())
    try:
        win._on_enable_cursor_preview()
        monkeypatch.setattr(win, "_confirm_cursor_move", lambda decision: False)  # Cancel
        win._on_preview_cursor_target()
        assert cursor.move_count == 0
        assert "Cancelled" in win.cursor_result_label.text()
    finally:
        win.close()


def test_blocked_gate_shows_reason_and_never_moves(qapp, tmp_path, monkeypatch):
    # A context that yields an UNKNOWN-percentage request → blocked, no dialog.
    class _BlockCtx(_ValidContext):
        def build_request(self, **kw):
            from dataclasses import replace
            return replace(super().build_request(**kw), pct=None)

    cursor = FakeCursorPreview()
    ctl = CursorPreviewController(cursor, CursorPreviewAudit(tmp_path / "a.jsonl"))
    win = _debugger(controller=ctl, context=_BlockCtx())
    try:
        win._on_enable_cursor_preview()
        # If the gate blocks, the confirm dialog must never be reached.
        monkeypatch.setattr(win, "_confirm_cursor_move",
                            lambda d: pytest.fail("must not confirm a blocked request"))
        win._on_preview_cursor_target()
        assert cursor.move_count == 0
        assert "Blocked" in win.cursor_result_label.text()
    finally:
        win.close()


def test_enable_required_before_preview_can_move(qapp, tmp_path, monkeypatch):
    # Without enabling, the gate blocks with "disabled" even if confirmed.
    cursor = FakeCursorPreview()
    ctl = CursorPreviewController(cursor, CursorPreviewAudit(tmp_path / "a.jsonl"))
    win = _debugger(controller=ctl, context=_ValidContext())
    try:
        monkeypatch.setattr(win, "_confirm_cursor_move", lambda d: True)
        win._on_preview_cursor_target()               # never enabled
        assert cursor.move_count == 0
        assert "Blocked" in win.cursor_result_label.text()
    finally:
        win.close()
