"""M5A.1 staleness + one-shot move with measured/calibrated geometry.

Ties the calibrated WindowGeometry into the real gate + controller: a valid request
reaches move_to exactly once at the calibrated screen point, and any window
move/resize/viewport/DPR/zoom change since the scan blocks the move.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from bap.adapters.cursor.fake_cursor import FakeCursorPreview
from bap.forge.cursor.audit import CursorPreviewAudit
from bap.forge.cursor.controller import CursorPreviewController
from bap.forge.cursor.geometry import WindowGeometry
from bap.forge.cursor.preview import PreviewRequest, evaluate_preview
from bap.forge.detection.weakening import Decision

NOW = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


def _calibrated(content_rect=(200, 100, 1200, 900), cap=(1000, 800), dpr=1.0, ms=1.0,
                zoom=1.0, wid="w1"):
    return WindowGeometry(
        window_x=content_rect[0], window_y=content_rect[1],
        window_w=content_rect[2] - content_rect[0], window_h=content_rect[3] - content_rect[1],
        content_offset_x=0, content_offset_y=0, device_pixel_ratio=dpr, zoom=zoom,
        viewport_w=cap[0], viewport_h=cap[1], capture_w=cap[0], capture_h=cap[1],
        monitor_scale=ms, window_id=wid, monitor_id="m", content_rect=content_rect,
        source="operator_calibrated", native_window_id=wid)


def _req(scan_geom, now_geom, *, browser_mode="external_chrome", **kw):
    base = dict(
        enabled=True, live=True, browser_mode=browser_mode, window_owned=True,
        world_alias="H", hostname="cz8.forgeofempires.com", selected_alias="H",
        tab_id_at_scan="t1", current_tab_id="t1", target_point=(500, 400), pct=60,
        confidence=0.9, weakening_value=10, world_limit=80, decision=Decision.CONTINUE,
        capture_w=1000, capture_h=800, captured_at=NOW - timedelta(seconds=1),
        geometry_at_scan=scan_geom, current_geometry=now_geom, max_age_s=5.0,
    )
    base.update(kw)
    return PreviewRequest(**base)


@pytest.mark.parametrize("browser_mode", ["external_chrome", "managed_chromium"])
def test_valid_calibrated_request_moves_once(tmp_path, browser_mode):
    g = _calibrated()
    ctl = CursorPreviewController(FakeCursorPreview(), CursorPreviewAudit(tmp_path / "a.jsonl"))
    ctl.enable_for_session()
    r = ctl.confirm_and_move(_req(g, g, browser_mode=browser_mode), confirmed=True, now=NOW)
    assert r.moved is True
    assert r.screen_point == (700, 500)      # 200 + 0.5*1000, 100 + 0.5*800
    assert ctl._cursor.move_count == 1
    assert ctl._audit.read_all()[0]["window_geometry"]["source"] == "operator_calibrated"


def test_window_moved_after_scan_blocks():
    scan = _calibrated(content_rect=(200, 100, 1200, 900))
    moved = _calibrated(content_rect=(300, 100, 1300, 900))    # dragged 100px right
    d = evaluate_preview(_req(scan, moved), now=NOW)
    assert d.ok is False and d.code == "geometry_changed"


def test_window_resized_after_scan_blocks():
    scan = _calibrated(content_rect=(200, 100, 1200, 900))
    resized = _calibrated(content_rect=(200, 100, 1100, 850))
    d = evaluate_preview(_req(scan, resized), now=NOW)
    assert d.ok is False and d.code == "geometry_changed"


def test_viewport_change_after_scan_blocks():
    scan = _calibrated(cap=(1000, 800))
    changed = _calibrated(cap=(800, 600))
    d = evaluate_preview(_req(scan, changed, capture_w=1000, capture_h=800), now=NOW)
    assert d.ok is False and d.code == "geometry_changed"


def test_dpr_or_zoom_change_after_scan_blocks():
    scan = _calibrated(dpr=1.0, zoom=1.0)
    dpr_changed = _calibrated(dpr=1.25, zoom=1.0)
    zoom_changed = _calibrated(dpr=1.0, zoom=1.1)
    assert evaluate_preview(_req(scan, dpr_changed), now=NOW).code == "geometry_changed"
    assert evaluate_preview(_req(scan, zoom_changed), now=NOW).code == "geometry_changed"


def test_geometry_lost_after_scan_blocks_not_guesses():
    scan = _calibrated()
    d = evaluate_preview(_req(scan, None), now=NOW)          # re-measure returned nothing
    assert d.ok is False and d.code == "no_geometry"


def test_decision_fields_expose_geometry_diagnostics():
    g = _calibrated(content_rect=(200, 100, 1200, 900), dpr=1.25, ms=1.25)
    f = evaluate_preview(_req(g, g), now=NOW).fields
    assert f["content_rect"] == [200, 100, 1200, 900]
    assert f["dpr"] == 1.25 and f["monitor_scale"] == 1.25
    assert f["geometry_source"] == "operator-calibrated"
    assert f["window_rect"] == [200, 100, 1000, 800]
