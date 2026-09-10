"""FoE-Helper-free calibration helpers: probe grid and geometric centrality."""

from __future__ import annotations

from bap.forge.action.native_calibrate import centrality, probe_points


def test_probe_points_stay_in_bounds_and_avoid_ui():
    pts = probe_points(1536, 695, right_ui=120, bottom_ui=90, margin=110)
    assert pts
    for x, y in pts:
        assert 110 <= x <= 1536 - 120 - 110 + 1     # inside margins, left of the right UI strip
        assert 110 <= y <= 695 - 90 - 110 + 1        # above the bottom bar


def test_probe_points_centre_first():
    vw, vh = 1600, 900
    pts = probe_points(vw, vh, cols=5, rows=4)
    cx = pts[0][0]
    # the first point is nearest the map-area centre; the last is a corner (farther out)
    mid_x = (110 + (vw - 120 - 110)) / 2
    assert abs(cx - mid_x) < abs(pts[-1][0] - mid_x) or abs(pts[0][1]) < abs(pts[-1][1])


def test_probe_points_unique():
    pts = probe_points(1536, 695)
    assert len(pts) == len(set(pts))


def test_centrality_central_lower_than_edge():
    flags = {1: (0, 0), 2: (10, 0), 3: (5, 0), 4: (5, 8)}
    c = centrality(flags)
    # province 3 sits at the centroid-ish middle; province 1/2 are the extremes
    assert c[3] < c[1] and c[3] < c[2]


def test_centrality_empty():
    assert centrality({}) == {}
    assert centrality(None) == {}


def test_centrality_orders_a_line():
    # points on a line; the middle one is most central
    flags = {i: (i * 10, 0) for i in range(5)}     # 0,10,20,30,40 → centroid at 20 → id 2
    c = centrality(flags)
    assert min(c, key=c.get) == 2
