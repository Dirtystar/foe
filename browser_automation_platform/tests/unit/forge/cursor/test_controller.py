"""The session cursor-preview controller (Milestone 5A): default-disabled,
one-shot movement, audit trail, and re-evaluation at move time.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from bap.adapters.cursor.fake_cursor import FakeCursorPreview
from bap.forge.cursor.audit import CursorPreviewAudit, EVENT_CURSOR_PREVIEW_ONLY
from bap.forge.cursor.controller import CursorPreviewController
from bap.forge.cursor.geometry import WindowGeometry
from bap.forge.cursor.preview import PreviewRequest
from bap.forge.detection.weakening import Decision

NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


def _geom():
    return WindowGeometry(window_x=100, window_y=50, window_w=1000, window_h=800,
                          content_offset_x=8, content_offset_y=72, device_pixel_ratio=1.0,
                          viewport_w=1000, viewport_h=800, capture_w=1000, capture_h=800,
                          monitor_scale=1.0, window_id="w1")


def _req(**kw):
    g = _geom()
    base = dict(
        enabled=True, live=True, browser_mode="external_chrome", window_owned=True,
        world_alias="H", hostname="cz8.forgeofempires.com", selected_alias="H",
        tab_id_at_scan="t1", current_tab_id="t1", target_point=(400, 300), pct=60,
        confidence=0.92, weakening_value=10, world_limit=80, decision=Decision.CONTINUE,
        capture_w=1000, capture_h=800, captured_at=NOW - timedelta(seconds=1),
        geometry_at_scan=g, current_geometry=g, max_age_s=5.0,
    )
    base.update(kw)
    return PreviewRequest(**base)


def _controller(tmp_path):
    return CursorPreviewController(FakeCursorPreview(), CursorPreviewAudit(tmp_path / "audit.jsonl"))


def test_disabled_by_default(tmp_path):
    ctl = _controller(tmp_path)
    assert ctl.enabled is False
    # preview reflects disabled even if the request says enabled.
    d = ctl.preview(_req(enabled=True), now=NOW)
    assert d.ok is False and d.code == "disabled"


def test_a_fresh_controller_is_disabled_again(tmp_path):
    # Models "resets to disabled on every launch": a new controller starts disabled.
    ctl = _controller(tmp_path); ctl.enable_for_session()
    assert ctl.enabled is True
    ctl2 = _controller(tmp_path)
    assert ctl2.enabled is False


def test_confirm_required_and_valid_move_happens_once(tmp_path):
    ctl = _controller(tmp_path); ctl.enable_for_session()
    cursor = ctl._cursor
    # Not confirmed -> no movement.
    r0 = ctl.confirm_and_move(_req(), confirmed=False, now=NOW)
    assert r0.moved is False and cursor.move_count == 0
    # Confirmed + valid -> exactly one move to the computed screen point.
    r1 = ctl.confirm_and_move(_req(), confirmed=True, now=NOW)
    assert r1.moved is True and cursor.move_count == 1
    assert cursor.last == (508, 422)      # 100+8+400, 50+72+300
    assert "NO CLICK PERFORMED" in r1.reason


def test_blocked_request_never_moves(tmp_path):
    ctl = _controller(tmp_path); ctl.enable_for_session()
    for kw in (dict(target_point=None), dict(pct=None), dict(decision=Decision.STOP),
               dict(decision=Decision.UNKNOWN), dict(captured_at=NOW - timedelta(seconds=30)),
               dict(current_tab_id="other"), dict(selected_alias="D"),
               dict(current_geometry=None)):
        r = ctl.confirm_and_move(_req(**kw), confirmed=True, now=NOW)
        assert r.moved is False
    assert ctl._cursor.move_count == 0


def test_world_switched_while_dialog_open_is_caught_at_move_time(tmp_path):
    ctl = _controller(tmp_path); ctl.enable_for_session()
    # preview passed, but by confirm time the operator switched World.
    good = _req()
    assert ctl.preview(good, now=NOW).ok is True
    switched = replace(good, selected_alias="D")
    r = ctl.confirm_and_move(switched, confirmed=True, now=NOW)
    assert r.moved is False and ctl._cursor.move_count == 0
    assert r.decision.code == "world_switched"


def test_audit_record_is_written_with_no_click_guarantee(tmp_path):
    audit = CursorPreviewAudit(tmp_path / "audit.jsonl")
    ctl = CursorPreviewController(FakeCursorPreview(), audit)
    ctl.enable_for_session()
    ctl.confirm_and_move(_req(), confirmed=True, now=NOW)
    records = audit.read_all()
    assert len(records) == 1
    rec = records[0]
    assert rec["event"] == EVENT_CURSOR_PREVIEW_ONLY
    assert rec["no_click"] is True
    assert rec["moved"] is True
    assert rec["operator_confirmed"] is True
    assert rec["world"] == "H"
    assert rec["requested_screen_point"] == [508, 422]
    assert rec["coordinate_trace"] is not None
    assert rec["weakening_decision"] == "CONTINUE"


def test_blocked_move_is_also_audited(tmp_path):
    audit = CursorPreviewAudit(tmp_path / "audit.jsonl")
    ctl = CursorPreviewController(FakeCursorPreview(), audit)
    ctl.enable_for_session()
    ctl.confirm_and_move(_req(decision=Decision.STOP), confirmed=True, now=NOW)
    rec = audit.read_all()[0]
    assert rec["moved"] is False and rec["blocked_code"] == "weakening_blocked"
    assert rec["no_click"] is True


def test_cancel_writes_no_audit_and_no_move(tmp_path):
    audit = CursorPreviewAudit(tmp_path / "audit.jsonl")
    ctl = CursorPreviewController(FakeCursorPreview(), audit)
    ctl.enable_for_session()
    ctl.confirm_and_move(_req(), confirmed=False, now=NOW)
    assert ctl._cursor.move_count == 0
    assert audit.read_all() == []
