"""Gated autoplay loop: fight until attrition reaches the limit, with a hard cap and an
attrition-unknown fail-safe. Pure logic — no browser."""

from __future__ import annotations

from bap.forge.action.autoplay import run_autoplay_loop


class _Clicker:
    def __init__(self): self.clicks = []; self.keys = []
    def click_xy(self, x, y): self.clicks.append((x, y))
    def press(self, k): self.keys.append(k)


def _rising(values):
    """get_attrition() that walks through `values`, holding the last one."""
    seq = list(values)
    state = {"i": 0}
    def _get():
        i = min(state["i"], len(seq) - 1)
        state["i"] += 1
        return seq[i]
    return _get


def test_fights_until_attrition_limit():
    c = _Clicker()
    # attrition read before each fight: 47,48,49,50,... limit 50 → stop at the 50 read
    r = run_autoplay_loop(c, _rising([47, 48, 49, 50, 51]), 10, 20,
                          max_attrition=50, sleep=lambda s: None)
    assert r.reason == "attrition_limit"
    assert r.fights == 3                      # fought at 47,48,49; stopped at 50
    assert c.clicks == [(10, 20)] * 3
    assert c.keys == ["r", "r", "r"]


def test_never_fights_at_or_over_limit():
    c = _Clicker()
    r = run_autoplay_loop(c, _rising([50]), 1, 2, max_attrition=50, sleep=lambda s: None)
    assert r.fights == 0 and r.reason == "attrition_limit"   # already at ceiling → no fight


def test_attrition_unknown_is_failsafe_stop():
    c = _Clicker()
    r = run_autoplay_loop(c, lambda: None, 1, 2, max_attrition=50, sleep=lambda s: None)
    assert r.fights == 0 and r.reason == "attrition_unknown"
    assert c.clicks == []                     # never fight blind


def test_max_clicks_hard_cap():
    c = _Clicker()
    r = run_autoplay_loop(c, lambda: 0, 1, 2, max_attrition=999, max_clicks=5,
                          sleep=lambda s: None)
    assert r.fights == 5 and r.reason == "max_clicks"


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
    run_autoplay_loop(c, _rising([0, 1, 2]), 1, 2, max_attrition=999, max_clicks=2,
                      key=None, sleep=lambda s: None)
    assert c.keys == []


def test_result_reports_final_attrition():
    c = _Clicker()
    r = run_autoplay_loop(c, _rising([10, 20, 60]), 1, 2, max_attrition=50,
                          sleep=lambda s: None)
    assert r.final_attrition == 60 and r.reason == "attrition_limit"
