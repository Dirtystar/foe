"""Gated autoplay loop: fight until the REAL live attrition reaches the limit, with a hard
cap and an attrition-unknown fail-safe. Attrition is read live (never estimated from the
fight count — a province's % makes attrition probabilistic). Pure logic, no browser."""

from __future__ import annotations

from bap.forge.action.autoplay import run_autoplay_loop


class _Clicker:
    def __init__(self): self.clicks = []; self.keys = []
    def click_xy(self, x, y): self.clicks.append((x, y))
    def press(self, k): self.keys.append(k)


def _reads(values):
    """get_attrition() that walks through `values`, holding the last (simulates the live
    reading refreshing between fights)."""
    seq = list(values)
    state = {"i": 0}
    def _get():
        i = min(state["i"], len(seq) - 1)
        state["i"] += 1
        return seq[i]
    return _get


def test_fights_until_live_attrition_limit():
    c = _Clicker()
    # attrition read before each fight; it climbs slowly (many fights per +1 in reality)
    r = run_autoplay_loop(c, _reads([10, 10, 11, 11, 12, 12, 50]), 10, 20,
                          max_attrition=50, sleep=lambda s: None)
    assert r.reason == "attrition_limit"
    assert r.fights == 6                       # fought until the reading hit 50
    assert c.keys == ["r"] * 6


def test_never_fights_at_or_over_limit():
    c = _Clicker()
    r = run_autoplay_loop(c, lambda: 50, 1, 2, max_attrition=50, sleep=lambda s: None)
    assert r.fights == 0 and r.reason == "attrition_limit"


def test_attrition_unknown_is_failsafe_stop():
    c = _Clicker()
    r = run_autoplay_loop(c, lambda: None, 1, 2, max_attrition=50, sleep=lambda s: None)
    assert r.fights == 0 and r.reason == "attrition_unknown"
    assert c.clicks == []                      # never fight blind


def test_attrition_going_unknown_midway_stops():
    c = _Clicker()
    r = run_autoplay_loop(c, _reads([10, 20, None, 30]), 1, 2, max_attrition=99,
                          sleep=lambda s: None)
    assert r.fights == 2 and r.reason == "attrition_unknown"


def test_max_clicks_hard_cap():
    c = _Clicker()
    # attrition never reaches the limit (e.g. a 0% province) → the cap protects us
    r = run_autoplay_loop(c, lambda: 5, 1, 2, max_attrition=999, max_clicks=7,
                          sleep=lambda s: None)
    assert r.fights == 7 and r.reason == "max_clicks"


def test_should_stop_halts():
    c = _Clicker()
    calls = {"n": 0}
    def _stop():
        calls["n"] += 1
        return calls["n"] > 2
    r = run_autoplay_loop(c, lambda: 0, 1, 2, max_attrition=999, max_clicks=100,
                          sleep=lambda s: None, should_stop=_stop)
    assert r.fights == 2 and r.reason == "stopped"


def test_no_key_means_no_press():
    c = _Clicker()
    run_autoplay_loop(c, _reads([0, 1, 2]), 1, 2, max_attrition=999, max_clicks=2,
                      key=None, sleep=lambda s: None)
    assert c.keys == []


def test_result_reports_final_attrition():
    c = _Clicker()
    r = run_autoplay_loop(c, _reads([10, 20, 60]), 1, 2, max_attrition=50,
                          sleep=lambda s: None)
    assert r.final_attrition == 60 and r.reason == "attrition_limit"
