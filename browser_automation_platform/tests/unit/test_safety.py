"""Safety ladder: clamping, jitter bounds, active windows, daily-cap keys."""

from __future__ import annotations

import random
import time

from bap.forge import safety


def test_levels_ordered_riskiest_to_safest():
    caps = [lvl.daily_cap if lvl.daily_cap is not None else 10**9 for lvl in safety.LEVELS]
    assert caps == sorted(caps, reverse=True)          # safer levels fight less
    # slowest max delay grows with safety
    maxes = [lvl.inter_ms[1] for lvl in safety.LEVELS]
    assert maxes == sorted(maxes)


def test_get_clamps():
    assert safety.get(-5) is safety.LEVELS[0]
    assert safety.get(999) is safety.LEVELS[-1]
    assert safety.get(2).name == "balanced"


def test_jitter_within_bounds():
    rng = random.Random(1)
    for lvl in safety.LEVELS:
        for _ in range(50):
            assert lvl.inter_ms[0] <= safety.jittered_inter(lvl, rng) <= lvl.inter_ms[1]
            assert lvl.reload_every[0] <= safety.jittered_reload(lvl, rng) <= lvl.reload_every[1]


def test_turbo_is_always_active():
    turbo = safety.get(0)
    for h in range(24):
        t = time.mktime((2026, 1, 1, h, 30, 0, 0, 0, -1))
        assert safety.is_active_now(turbo, t)
    assert safety.seconds_until_active(turbo) == 0


def test_active_window_respected():
    stealth = safety.get(4)                              # windows 9-12, 15-21
    inside = time.mktime((2026, 1, 1, 10, 0, 0, 0, 0, -1))
    outside = time.mktime((2026, 1, 1, 13, 0, 0, 0, 0, -1))
    assert safety.is_active_now(stealth, inside)
    assert not safety.is_active_now(stealth, outside)
    # at 13:00 the next window (15:00) is ~2h away
    assert 0 < safety.seconds_until_active(stealth, outside) <= 2 * 3600 + 60


def test_daily_key_and_cap():
    t = time.mktime((2026, 3, 4, 12, 0, 0, 0, 0, -1))
    assert safety.daily_key("cz8", t) == "20260304::cz8"
    bal = safety.get(2)                                  # cap 400
    assert not safety.cap_reached(399, bal)
    assert safety.cap_reached(400, bal)
    assert not safety.cap_reached(10**9, safety.get(0))  # turbo = unlimited


def test_roll_mistake_bounds():
    rng = random.Random(0)
    assert safety.roll_mistake(safety.get(0), rng) is False   # turbo: never
    hits = sum(safety.roll_mistake(safety.get(4), rng) for _ in range(2000))
    assert 150 < hits < 330                                    # ~12%
