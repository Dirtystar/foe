"""Milestone — OpenAndVerifyController.open_province_and_observe: one gated click,
then an honest observation of the resulting UI state. No %-read, no retry, no second
click; blocked before any click when the gate fails."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from bap.adapters.cursor.fake_cursor import FakeCursorPreview
from bap.adapters.input.fake_click import FakeClick
from bap.forge.click.audit import ClickAudit
from bap.forge.click.open_verify import (
    BLOCKED,
    NOT_CONFIRMED,
    OBSERVED,
    OpenAndVerifyController,
)
from bap.forge.click.panel_reader import PanelReading
from bap.forge.cursor.geometry import WindowGeometry
from bap.forge.cursor.preview import PreviewRequest
from bap.forge.detection.weakening import Decision
from bap.forge.state.screen_state import ScreenState, StateEvidence, StateSignal

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


def _fake_detectors(map_score, panel_score):
    def _mk(state, score):
        def _det(image, ctx):
            return StateEvidence(score, [StateSignal(state, "sig", score)])
        return _det
    return {ScreenState.GBG_MAP: _mk(ScreenState.GBG_MAP, map_score),
            ScreenState.PROVINCE_PANEL: _mk(ScreenState.PROVINCE_PANEL, panel_score)}


class _Reader:  # required by the controller ctor; unused by this flow
    def read(self, image):
        return PanelReading(True, 20, 0.9, "blue", "x", (0, 0))


def _ctl(click, tmp_path, *, present=True, cursor_pos=None):
    return OpenAndVerifyController(
        FakeCursorPreview(), click, _Reader(), ClickAudit(tmp_path / "click_audit.jsonl"),
        capture_fn=lambda: np.zeros((80, 120, 3), np.uint8),
        panel_present_fn=lambda i: present, cursor_pos_fn=cursor_pos,
        sleep_fn=lambda s: None)


def test_not_confirmed_no_click(tmp_path):
    click = FakeClick()
    c = _ctl(click, tmp_path); c.enable_for_session()
    r = c.open_province_and_observe(_req(), confirmed=False, now=NOW)
    assert r.outcome == NOT_CONFIRMED and r.clicked is False and click.count == 0


def test_disabled_blocks_no_click(tmp_path):
    click = FakeClick()
    c = _ctl(click, tmp_path)   # not enabled
    r = c.open_province_and_observe(_req(), confirmed=True, now=NOW)
    assert r.outcome == BLOCKED and r.blocked_code == "disabled" and click.count == 0


def test_gate_failure_blocks_before_click(tmp_path):
    click = FakeClick()
    c = _ctl(click, tmp_path); c.enable_for_session()
    r = c.open_province_and_observe(_req(current_tab_id="t2"), confirmed=True, now=NOW)
    assert r.outcome == BLOCKED and r.blocked_code == "tab_changed" and click.count == 0


def test_observed_province_panel_one_click_confirmed(tmp_path):
    click = FakeClick()
    c = _ctl(click, tmp_path, cursor_pos=lambda: (400, 300)); c.enable_for_session()
    r = c.open_province_and_observe(
        _req(), confirmed=True, now=NOW, detectors=_fake_detectors(0.1, 0.9),
        capture_dir=tmp_path)
    assert r.outcome == OBSERVED and r.clicked is True
    assert r.observed is ScreenState.PROVINCE_PANEL and r.confirmed is True
    assert click.count == 1                      # exactly one click
    events = [e["event"] for e in ClickAudit(tmp_path / "click_audit.jsonl").read_all()]
    assert "PROVINCE_OPEN_OBSERVED" in events


def test_observed_unknown_reported_and_captured_no_retry(tmp_path):
    click = FakeClick()
    c = _ctl(click, tmp_path); c.enable_for_session()
    r = c.open_province_and_observe(
        _req(), confirmed=True, now=NOW, detectors=_fake_detectors(0.80, 0.78),
        capture_dir=tmp_path)
    assert r.outcome == OBSERVED and r.observed is ScreenState.UNKNOWN
    assert r.confirmed is False
    assert click.count == 1                      # clicked once, then STOP (no retry)
    assert r.observation.captured_path is not None


def test_still_gbg_map_reported_honestly(tmp_path):
    click = FakeClick()
    c = _ctl(click, tmp_path); c.enable_for_session()
    r = c.open_province_and_observe(
        _req(), confirmed=True, now=NOW, detectors=_fake_detectors(0.95, 0.05),
        capture_dir=tmp_path)
    assert r.observed is ScreenState.GBG_MAP     # not reinterpreted
    assert r.confirmed is False and click.count == 1


def test_cursor_moved_blocks_no_click(tmp_path):
    click = FakeClick()
    c = _ctl(click, tmp_path, cursor_pos=lambda: (999, 999)); c.enable_for_session()
    r = c.open_province_and_observe(_req(), confirmed=True, now=NOW,
                                    detectors=_fake_detectors(0.1, 0.9))
    assert r.outcome == BLOCKED and r.blocked_code == "cursor_moved" and click.count == 0
