"""Real Windows browser geometry (Milestone 5A.1): CDP measurement, content-origin
calibration (persistence + invalidation), native-window association, and the
calibrated image→screen transform across scaling / monitors / negative coordinates.
"""

from __future__ import annotations

import pytest

from bap.forge.cursor.geometry import WindowGeometry, image_to_screen
from bap.forge.cursor.window_geometry import (
    CalibrationKey,
    ContentOriginCalibration,
    GeometryMeasurement,
    build_window_geometry,
    measure_via_cdp,
    resolve_native_window,
)


def _send(bounds, vp=(960, 600), state="normal", scale=1.0):
    def send(method, params):
        if method in ("Browser.getWindowForTarget",):
            return {"windowId": 7, "bounds": {**bounds, "windowState": state}}
        if method == "Browser.getWindowBounds":
            return {"bounds": {**bounds, "windowState": state}}
        if method == "Page.getLayoutMetrics":
            return {"cssLayoutViewport": {"clientWidth": vp[0], "clientHeight": vp[1]},
                    "visualViewport": {"scale": scale}}
        raise AssertionError(method)
    return send


# --- CDP measurement ----------------------------------------------------------

def test_measure_derives_dpr_from_capture_over_viewport():
    m = measure_via_cdp(_send({"left": 100, "top": 50, "width": 1000, "height": 800}),
                        capture_w=1200, capture_h=750, monitor_scale=1.25, windows_dpi=120)
    assert m.device_pixel_ratio == 1.25          # 1200/960
    assert (m.window_x, m.window_y, m.window_w, m.window_h) == (100, 50, 1000, 800)
    assert m.native_window_id == "7"
    assert m.windows_dpi == 120


def test_measure_reports_maximized_state():
    m = measure_via_cdp(_send({"left": 0, "top": 0, "width": 1920, "height": 1080}, state="maximized"),
                        capture_w=1920, capture_h=1080)
    assert m.window_state == "maximized"


# --- content-origin calibration ----------------------------------------------

def _key(**kw):
    base = dict(browser_mode="external_chrome", endpoint="http://127.0.0.1:9222",
                capture_w=1920, capture_h=1080, viewport_w=1920, viewport_h=1080,
                device_pixel_ratio=1.0, zoom=1.0, monitor_scale=1.0, monitor_id="primary")
    base.update(kw)
    return CalibrationKey(**base)


def test_calibration_persists_and_reloads(tmp_path):
    path = tmp_path / "cal.json"
    cal = ContentOriginCalibration(path)
    cal.set(_key(), (100, 200, 2020, 1280))
    reloaded = ContentOriginCalibration.load(path)
    assert reloaded.get(_key()) == (100, 200, 2020, 1280)


def test_calibration_is_not_reused_when_any_key_changes(tmp_path):
    cal = ContentOriginCalibration(tmp_path / "cal.json")
    cal.set(_key(), (100, 200, 2020, 1280))
    # Any factor that would move the content invalidates the match.
    assert cal.get(_key(zoom=1.25)) is None
    assert cal.get(_key(device_pixel_ratio=1.25)) is None
    assert cal.get(_key(monitor_scale=1.5)) is None
    assert cal.get(_key(viewport_w=1600)) is None
    assert cal.get(_key(endpoint="other")) is None
    assert cal.get(_key(browser_mode="managed_chromium")) is None
    assert cal.get(_key()) == (100, 200, 2020, 1280)   # exact key still hits


def test_calibration_rejects_degenerate_rectangle(tmp_path):
    cal = ContentOriginCalibration(tmp_path / "cal.json")
    with pytest.raises(ValueError):
        cal.set(_key(), (100, 100, 100, 200))          # zero width


# --- build_window_geometry ----------------------------------------------------

def test_build_blocks_when_content_origin_unknown():
    m = measure_via_cdp(_send({"left": 0, "top": 0, "width": 1000, "height": 800}),
                        capture_w=960, capture_h=600)
    geom, source = build_window_geometry(m, browser_mode="external_chrome", endpoint="e")
    assert geom is None and source == "content_origin_unavailable"


def test_build_uses_operator_calibration_and_marks_source(tmp_path):
    m = measure_via_cdp(_send({"left": 100, "top": 50, "width": 1000, "height": 800}),
                        capture_w=960, capture_h=600)
    cal = ContentOriginCalibration(tmp_path / "c.json")
    key = CalibrationKey("external_chrome", "e", 960, 600, 960, 600, 1.0, 1.0, 1.0, "primary")
    cal.set(key, (140, 190, 1100, 790))
    geom, source = build_window_geometry(m, browser_mode="external_chrome", endpoint="e", calibration=cal)
    assert source == "operator_calibrated"
    assert geom.is_calibrated and geom.content_rect == (140, 190, 1100, 790)
    assert geom.content_offset_x == 40 and geom.content_offset_y == 140   # rect - window origin


# --- native-window association ------------------------------------------------

def test_association_unique_ambiguous_and_missing():
    cands = [{"hwnd": 1, "rect": (100, 50, 1000, 800)}, {"hwnd": 2, "rect": (0, 0, 500, 400)}]
    win, reason = resolve_native_window((100, 50, 1000, 800), cands)
    assert win["hwnd"] == 1 and reason is None
    # two near-identical windows → ambiguous, block.
    amb = [{"hwnd": 1, "rect": (100, 50, 1000, 800)}, {"hwnd": 3, "rect": (101, 51, 1001, 801)}]
    win, reason = resolve_native_window((100, 50, 1000, 800), amb)
    assert win is None and "ambiguous" in reason
    # none match → block.
    win, reason = resolve_native_window((100, 50, 1000, 800), [{"hwnd": 9, "rect": (0, 0, 10, 10)}])
    assert win is None and "no native window" in reason


# --- calibrated transform: scaling / monitors / negative ----------------------

def _calibrated(content_rect, cap=(1000, 800), vp=(1000, 800), dpr=1.0, ms=1.0, wid="w"):
    return WindowGeometry(
        window_x=content_rect[0], window_y=content_rect[1],
        window_w=content_rect[2] - content_rect[0], window_h=content_rect[3] - content_rect[1],
        content_offset_x=0, content_offset_y=0, device_pixel_ratio=dpr, zoom=1.0,
        viewport_w=vp[0], viewport_h=vp[1], capture_w=cap[0], capture_h=cap[1],
        monitor_scale=ms, window_id=wid, monitor_id="m", content_rect=content_rect,
        source="operator_calibrated", native_window_id=wid)


@pytest.mark.parametrize("content_rect,cap,point,expected", [
    # 100%: content rect == capture size at screen origin (200,100)
    ((200, 100, 1200, 900), (1000, 800), (500, 400), (700, 500)),
    # 125%: an 800x600 CSS viewport occupies 1000x750 physical; capture is 1000x750 device
    ((0, 0, 1000, 750), (1000, 750), (500, 375), (500, 375)),
    # 150%: content rect is 1.5x the css viewport extent
    ((0, 0, 1500, 1125), (1000, 750), (1000, 750), (1500, 1125)),
    # second monitor to the right
    ((1920, 0, 2920, 800), (1000, 800), (500, 400), (2420, 400)),
    # negative monitor (left of primary)
    ((-1920, -100, -920, 700), (1000, 800), (500, 400), (-1420, 300)),
])
def test_calibrated_transform_maps_across_scaling_and_monitors(content_rect, cap, point, expected):
    g = _calibrated(content_rect, cap=cap, vp=cap)
    assert image_to_screen(point, g).screen_physical == expected


def test_calibrated_geometry_is_flagged_and_traced():
    g = _calibrated((100, 100, 1100, 900))
    t = image_to_screen((0, 0), g)
    assert t.screen_physical == (100, 100)        # top-left maps to content origin
    assert g.is_calibrated is True
    assert t.to_dict()["screen_physical"] == [100, 100]
