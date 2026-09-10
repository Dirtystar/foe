"""The image→screen coordinate contract (Milestone 5A).

Covers the required cases: 100 % and 125 % Windows scaling, two monitors, negative
monitor coordinates, DPR, page zoom, and capture≠viewport rescaling. Pure math —
no cursor moves.
"""

from __future__ import annotations

from bap.forge.cursor.geometry import WindowGeometry, image_to_screen, point_in_capture


def _geom(**kw):
    base = dict(window_x=0, window_y=0, window_w=1000, window_h=800,
                content_offset_x=0, content_offset_y=0, device_pixel_ratio=1.0,
                viewport_w=1000, viewport_h=800, capture_w=1000, capture_h=800,
                monitor_scale=1.0, window_id="w1")
    base.update(kw)
    return WindowGeometry(**base)


def test_100_percent_scaling_adds_window_and_content_offset():
    g = _geom(window_x=100, window_y=50, content_offset_x=8, content_offset_y=72)
    t = image_to_screen((480, 300), g)
    assert t.viewport_css == (480.0, 300.0)          # DPR 1, capture==viewport
    assert t.screen_physical == (100 + 8 + 480, 50 + 72 + 300) == (588, 422)


def test_125_percent_scaling_applies_monitor_scale_once():
    # DPR 1.25 capture (1250x1000) of an 800x625 CSS viewport; 125% monitor scale.
    g = _geom(window_x=0, window_y=0, content_offset_x=0, content_offset_y=100,
              device_pixel_ratio=1.25, viewport_w=800, viewport_h=625,
              capture_w=1000, capture_h=781, monitor_scale=1.25)
    t = image_to_screen((500, 390), g)
    # image 500 -> css 500*800/1000 = 400; +offset(0,100) -> (400, 100+312) ; *1.25
    assert round(t.viewport_css[0], 1) == 400.0
    assert t.screen_physical[0] == int(round((0 + 0 + 400) * 1.25)) == 500


def test_second_monitor_to_the_right():
    g = _geom(window_x=1920, window_y=0, content_offset_x=8, content_offset_y=72)
    t = image_to_screen((480, 300), g)
    assert t.screen_physical == (1920 + 8 + 480, 372) == (2408, 372)


def test_negative_monitor_coordinates_are_preserved():
    # A monitor left of the primary: window origin is negative.
    g = _geom(window_x=-1920, window_y=-200, content_offset_x=8, content_offset_y=72)
    t = image_to_screen((480, 300), g)
    assert t.screen_physical == (-1920 + 8 + 480, -200 + 72 + 300) == (-1432, 172)


def test_negative_coordinates_with_scaling():
    g = _geom(window_x=-1000, window_y=0, content_offset_x=0, content_offset_y=0,
              monitor_scale=1.5)
    t = image_to_screen((200, 100), g)
    assert t.screen_physical == (int(round(-800 * 1.5)), 150) == (-1200, 150)


def test_capture_larger_than_viewport_rescales_correctly():
    # Retina-like: capture is 2x the CSS viewport.
    g = _geom(viewport_w=800, viewport_h=600, capture_w=1600, capture_h=1200,
              device_pixel_ratio=2.0, content_offset_x=0, content_offset_y=0)
    t = image_to_screen((1600, 1200), g)      # bottom-right device px
    assert t.viewport_css == (800.0, 600.0)   # maps to CSS viewport corner


def test_falls_back_to_inverse_dpr_when_viewport_unknown():
    g = WindowGeometry(window_x=0, window_y=0, window_w=1000, window_h=800,
                       content_offset_x=0, content_offset_y=0, device_pixel_ratio=2.0,
                       viewport_w=None, viewport_h=None, capture_w=None, capture_h=None,
                       monitor_scale=1.0, window_id="w")
    t = image_to_screen((400, 200), g)
    assert t.viewport_css == (200.0, 100.0)   # divided by DPR once


def test_point_in_capture_bounds():
    assert point_in_capture((0, 0), 100, 80) is True
    assert point_in_capture((99, 79), 100, 80) is True
    assert point_in_capture((100, 80), 100, 80) is False
    assert point_in_capture((-1, 10), 100, 80) is False


def test_trace_records_every_stage():
    g = _geom(window_x=10, window_y=20, content_offset_x=5, content_offset_y=6,
              monitor_scale=1.25)
    d = image_to_screen((40, 30), g).to_dict()
    for key in ("image", "viewport_css", "content_css", "screen_logical",
                "screen_physical", "monitor_scale", "window_origin", "content_offset"):
        assert key in d
