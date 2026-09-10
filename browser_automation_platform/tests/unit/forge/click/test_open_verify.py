"""M6A.1 — Open & Verify controller: one click max, manual confirm required, and
map-vs-panel MATCH / MISMATCH / UNKNOWN / TIMEOUT all end in a hard STOP with no
retry and no second click."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from bap.adapters.cursor.fake_cursor import FakeCursorPreview
from bap.adapters.input.fake_click import FakeClick
from bap.forge.click.audit import (
    EVENT_CLICK_ARMED,
    EVENT_CLICK_EXECUTED,
    EVENT_PANEL_VERIFY_MATCH,
    EVENT_PANEL_VERIFY_MISMATCH,
    EVENT_PANEL_VERIFY_UNKNOWN,
    ClickAudit,
)
from bap.forge.click.open_verify import (
    BLOCKED,
    NOT_CONFIRMED,
    PANEL_TIMEOUT,
    VERIFY_MATCH,
    VERIFY_MISMATCH,
    VERIFY_UNKNOWN,
    OpenAndVerifyController,
)
from bap.forge.click.panel_reader import PanelReading
from bap.forge.cursor.geometry import WindowGeometry
from bap.forge.cursor.preview import PreviewRequest
from bap.forge.detection.weakening import Decision

NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)


def _geom(**kw):
    base = dict(window_x=0, window_y=0, window_w=1000, window_h=800,
                content_offset_x=0, content_offset_y=0, device_pixel_ratio=1.0,
                viewport_w=1000, viewport_h=800, capture_w=1000, capture_h=800,
                monitor_scale=1.0, window_id="w1")
    base.update(kw)
    return WindowGeometry(**base)


def _req(**kw):
    g = _geom()
    base = dict(
        enabled=True, live=True, browser_mode="external_chrome", window_owned=True,
        world_alias="H", hostname="cz8.forgeofempires.com", selected_alias="H",
        tab_id_at_scan="t1", current_tab_id="t1", target_point=(400, 300), pct=20,
        confidence=0.9, weakening_value=10, world_limit=80, decision=Decision.CONTINUE,
        capture_w=1000, capture_h=800, captured_at=NOW - timedelta(seconds=1),
        geometry_at_scan=g, current_geometry=g, max_age_s=5.0,
    )
    base.update(kw)
    return PreviewRequest(**base)


@dataclass
class _FakeReader:
    """A stand-in for PanelReader returning a fixed reading (independent of images)."""

    reading: PanelReading

    def read(self, image):
        return self.reading


def _reading(pct, ok=True, color="blue"):
    return PanelReading(ok=ok, pct=pct, confidence=0.9, color_group=color,
                        reason="fake", pill_center=(1469, 773))


class _Panel:
    """capture_fn/panel_present_fn helper: panel appears after `after` polls."""

    def __init__(self, after=0, ever=True):
        self.after, self.ever, self.n = after, ever, 0

    def capture(self):
        return object()  # sentinel image; the fake reader ignores it

    def present(self, _img):
        self.n += 1
        return self.ever and self.n > self.after


def _ctl(click, reader, panel, tmp_path, *, cursor=None, cursor_pos=None):
    return OpenAndVerifyController(
        cursor or FakeCursorPreview(), click, reader,
        ClickAudit(tmp_path / "click_audit.jsonl"),
        capture_fn=panel.capture, panel_present_fn=panel.present,
        cursor_pos_fn=cursor_pos, sleep_fn=lambda s: None,
    )


# --- confirmation + enablement -------------------------------------------------

def test_no_click_without_confirmation(tmp_path):
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(20)), _Panel(), tmp_path)
    c.enable_for_session()
    res = c.open_and_verify(_req(), map_pct=20, map_confidence=0.9, confirmed=False, now=NOW)
    assert res.state == NOT_CONFIRMED and res.clicked is False
    assert click.count == 0


def test_no_click_when_disabled(tmp_path):
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(20)), _Panel(), tmp_path)
    # not enabled
    res = c.open_and_verify(_req(), map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == BLOCKED and res.blocked_code == "disabled"
    assert click.count == 0


# --- the happy path: exactly one click, MATCH ---------------------------------

def test_exact_match_succeeds_with_exactly_one_click(tmp_path):
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(20)), _Panel(after=0), tmp_path,
             cursor_pos=lambda: (400, 300))
    c.enable_for_session()
    res = c.open_and_verify(_req(pct=20), map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == VERIFY_MATCH and res.matched is True
    assert res.clicked is True
    assert click.count == 1                      # exactly one click
    assert click.clicks == [(400, 300)]
    events = [r["event"] for r in ClickAudit(tmp_path / "click_audit.jsonl").read_all()]
    assert EVENT_CLICK_ARMED in events and EVENT_CLICK_EXECUTED in events
    assert EVENT_PANEL_VERIFY_MATCH in events


# --- verification outcomes all STOP -------------------------------------------

def test_panel_unknown_hard_stops(tmp_path):
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(None, ok=False)), _Panel(), tmp_path)
    c.enable_for_session()
    res = c.open_and_verify(_req(), map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == VERIFY_UNKNOWN and res.stopped is True
    assert click.count == 1                      # clicked once, then STOP (no retry)
    events = [r["event"] for r in ClickAudit(tmp_path / "click_audit.jsonl").read_all()]
    assert EVENT_PANEL_VERIFY_UNKNOWN in events


def test_map_panel_mismatch_hard_stops(tmp_path):
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(60)), _Panel(), tmp_path)
    c.enable_for_session()
    res = c.open_and_verify(_req(pct=20), map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == VERIFY_MISMATCH and res.stopped is True
    assert click.count == 1
    events = [r["event"] for r in ClickAudit(tmp_path / "click_audit.jsonl").read_all()]
    assert EVENT_PANEL_VERIFY_MISMATCH in events


def test_product_safety_20_map_40_panel_blocks(tmp_path):
    """The flagship guard: map says 20 but the panel independently reads 40 → STOP."""
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(40)), _Panel(), tmp_path)
    c.enable_for_session()
    res = c.open_and_verify(_req(pct=20), map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == VERIFY_MISMATCH
    assert res.panel.pct == 40 and res.map_pct == 20
    assert click.count == 1                      # no second/battle click follows a mismatch


def test_panel_timeout_stops_no_retry(tmp_path):
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(20)), _Panel(ever=False), tmp_path)
    c.enable_for_session()
    res = c.open_and_verify(_req(), map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == PANEL_TIMEOUT and res.clicked is True
    assert click.count == 1                      # one click, panel never opened, STOP


# --- gates block before any click ---------------------------------------------

@pytest.mark.parametrize("kw,code", [
    (dict(current_tab_id="t2"), "tab_changed"),
    (dict(selected_alias="D"), "world_switched"),
    (dict(geometry_at_scan=None), "no_geometry"),
    (dict(decision=Decision.STOP), "weakening_blocked"),
    (dict(pct=None), "unknown_pct"),
])
def test_gate_failures_block_before_click(tmp_path, kw, code):
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(20)), _Panel(), tmp_path)
    c.enable_for_session()
    res = c.open_and_verify(_req(**kw), map_pct=kw.get("pct", 20),
                            map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == BLOCKED and res.blocked_code == code
    assert click.count == 0


def test_window_moved_between_scan_and_click_blocks(tmp_path):
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(20)), _Panel(), tmp_path)
    c.enable_for_session()
    req = _req(geometry_at_scan=_geom(window_x=0), current_geometry=_geom(window_x=40))
    res = c.open_and_verify(req, map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == BLOCKED and res.blocked_code == "geometry_changed"
    assert click.count == 0


def test_click_age_tighter_than_move_bar(tmp_path):
    # 3s old: passes the 5s move preview but fails the 2s click bound.
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(20)), _Panel(), tmp_path)
    c.enable_for_session()
    req = _req(captured_at=NOW - timedelta(seconds=3))
    res = c.open_and_verify(req, map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == BLOCKED and res.blocked_code == "expired_click"
    assert click.count == 0


def test_cursor_not_on_target_blocks(tmp_path):
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(20)), _Panel(), tmp_path,
             cursor_pos=lambda: (999, 999))   # cursor elsewhere
    c.enable_for_session()
    res = c.open_and_verify(_req(), map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == BLOCKED and res.blocked_code == "cursor_moved"
    assert click.count == 0


def test_fail_closed_audit_refuses_click(tmp_path):
    click = FakeClick()

    class _BadAudit(ClickAudit):
        def record_or_raise(self, event, entry=None):
            raise OSError("disk full")

    c = OpenAndVerifyController(
        FakeCursorPreview(), click, _FakeReader(_reading(20)),
        _BadAudit(tmp_path / "a.jsonl"),
        capture_fn=lambda: object(), panel_present_fn=lambda i: True,
        sleep_fn=lambda s: None)
    c.enable_for_session()
    res = c.open_and_verify(_req(), map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert res.state == BLOCKED and res.blocked_code == "audit_unavailable"
    assert click.count == 0                      # no trail → no click


# --- structural: no automatic retry / no second click reachable ---------------

def test_controller_has_no_retry_or_loop_method():
    names = dir(OpenAndVerifyController)
    for bad in ("retry", "loop", "run_forever", "battle", "click_again", "repeat"):
        assert bad not in names


def test_single_invocation_never_clicks_twice(tmp_path):
    # Even on a mismatch (a tempting place to "try again"), exactly one click.
    click = FakeClick()
    c = _ctl(click, _FakeReader(_reading(40)), _Panel(after=2), tmp_path)
    c.enable_for_session()
    c.open_and_verify(_req(pct=20), map_pct=20, map_confidence=0.9, confirmed=True, now=NOW)
    assert click.count == 1
