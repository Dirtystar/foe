"""The strict manual gate (Milestone 5A): every blocking condition + the one
happy path. Each failure returns a specific code and never a screen point.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bap.forge.cursor.geometry import WindowGeometry
from bap.forge.cursor.preview import PreviewRequest, evaluate_preview
from bap.forge.detection.weakening import Decision

NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


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
        tab_id_at_scan="t1", current_tab_id="t1", target_point=(400, 300), pct=60,
        confidence=0.92, weakening_value=10, world_limit=80, decision=Decision.CONTINUE,
        capture_w=1000, capture_h=800, captured_at=NOW - timedelta(seconds=1),
        geometry_at_scan=g, current_geometry=g, max_age_s=5.0,
    )
    base.update(kw)
    return PreviewRequest(**base)


def test_happy_path_allows_and_computes_screen_point():
    d = evaluate_preview(_req(), now=NOW)
    assert d.ok is True and d.code == "ok"
    assert d.screen_point == (400, 300)
    assert d.fields["pct"] == 60 and d.fields["decision"] == "CONTINUE"


@pytest.mark.parametrize("kw,code", [
    (dict(enabled=False), "disabled"),
    (dict(window_owned=False), "no_window"),
    (dict(browser_mode=None), "no_window"),
    (dict(live=False), "not_live"),
    (dict(selected_alias="D"), "world_switched"),
    (dict(current_tab_id="t2"), "tab_changed"),
    (dict(current_tab_id=None), "tab_changed"),
    (dict(target_point=None), "no_target"),
    (dict(pct=None), "unknown_pct"),
    (dict(decision=Decision.STOP), "weakening_blocked"),
    (dict(decision=Decision.UNKNOWN), "weakening_blocked"),
    (dict(target_point=(2000, 300)), "out_of_viewport"),
    (dict(captured_at=NOW - timedelta(seconds=9)), "expired"),
    (dict(captured_at=None), "no_timestamp"),
    (dict(geometry_at_scan=None), "no_geometry"),
    (dict(current_geometry=None), "no_geometry"),
])
def test_each_condition_blocks_with_its_code(kw, code):
    d = evaluate_preview(_req(**kw), now=NOW)
    assert d.ok is False
    assert d.code == code
    assert d.screen_point is None


def test_window_moved_between_scan_and_now_blocks():
    scan_geom = _geom(window_x=0)
    now_geom = _geom(window_x=37)          # window dragged 37px right
    d = evaluate_preview(_req(geometry_at_scan=scan_geom, current_geometry=now_geom), now=NOW)
    assert d.ok is False and d.code == "geometry_changed"


def test_dpr_or_zoom_change_blocks():
    scan_geom = _geom(device_pixel_ratio=1.0)
    now_geom = _geom(device_pixel_ratio=1.25)
    d = evaluate_preview(_req(geometry_at_scan=scan_geom, current_geometry=now_geom), now=NOW)
    assert d.ok is False and d.code == "geometry_changed"


def test_managed_chromium_is_an_accepted_mode():
    d = evaluate_preview(_req(browser_mode="managed_chromium"), now=NOW)
    assert d.ok is True
