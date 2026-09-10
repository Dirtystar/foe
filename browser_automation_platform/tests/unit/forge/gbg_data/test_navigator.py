"""Robust map navigator: scale + running offset, self-correcting from ground truth, drag to
reach off-screen provinces. Pure geometry, no browser."""

from __future__ import annotations

import pytest

from bap.forge.gbg_data.navigator import MapNavigator, estimate_scale


def test_estimate_scale_from_two_anchors():
    # flags 100px apart in map → 50px apart on screen ⇒ scale 0.5
    s = estimate_scale((0, 0), (0, 0), (30, 40), (60, 80))
    assert s == pytest.approx(0.5)


def test_estimate_scale_degenerate_is_none():
    assert estimate_scale((0, 0), (5, 5), (9, 9), (5, 5)) is None


def test_screen_for_and_learn_offset():
    nav = MapNavigator(scale=0.5)
    nav.learn_offset(screen=(300, 200), flag=(1000, 800))   # 300 = 0.5*1000 + off_x
    assert nav.off_x == -200 and nav.off_y == -200
    assert nav.screen_for((1000, 800)) == (300, 200)
    # another flag is now placed consistently
    assert nav.screen_for((1200, 800)) == (400, 200)


def test_apply_drag_shifts_all_flags():
    nav = MapNavigator(scale=1.0, off_x=0, off_y=0)
    before = nav.screen_for((500, 500))
    nav.apply_drag(-100, 50)                                 # we dragged the map left/down
    after = nav.screen_for((500, 500))
    assert after == (before[0] - 100, before[1] + 50)


def test_on_screen_bounds():
    nav = MapNavigator(scale=1.0)
    assert nav.on_screen((500, 400), 1536, 695, margin=60)
    assert not nav.on_screen((10, 400), 1536, 695, margin=60)     # too near left
    assert not nav.on_screen((500, -20), 1536, 695)               # above viewport


def test_drag_to_center_vector():
    nav = MapNavigator(scale=1.0, off_x=0, off_y=0)
    # flag at (2000,1500) is far off a 1536x695 screen; drag brings it to centre
    dx, dy = nav.drag_to_center((2000, 1500), 1536, 695)
    nav_after = MapNavigator(scale=1.0, off_x=dx, off_y=dy)
    assert nav_after.screen_for((2000, 1500)) == pytest.approx((768, 347.5))


def test_self_correction_converges():
    """True transform: scale 0.5, offset (-250,-180). We start with a wrong offset, click our
    guess for the target, the game tells us which province we ACTUALLY hit, we learn from it —
    and the corrected prediction lands on the true target."""
    true = MapNavigator(scale=0.5, off_x=-250, off_y=-180)
    flag_target = (1600, 900)

    nav = MapNavigator(scale=0.5, off_x=-200, off_y=-150)     # offset off by (50,30)
    guess = nav.screen_for(flag_target)
    # the province really under `guess` (what the game would report): invert the TRUE transform
    flag_hit = ((guess[0] - true.off_x) / true.scale, (guess[1] - true.off_y) / true.scale)
    nav.learn_offset(guess, flag_hit)                        # ground truth from the hit province
    corrected = nav.screen_for(flag_target)
    assert corrected == pytest.approx(true.screen_for(flag_target))   # now exact
