"""Round-robin scheduler: rotate over worlds, fight each to its own attrition limit, mark
Done and keep the rest running. Fail-safe on unknown attrition. Pure logic, no browser."""

from __future__ import annotations

import json
from collections import defaultdict

import pytest

from bap.forge.action.round_robin import (
    UNLIMITED,
    WorldPlan,
    load_world_plans,
    run_round_robin,
)


class _Sim:
    """Fake game: attrition == number of fights on that world (enough to test scheduling)."""
    def __init__(self):
        self.fights = defaultdict(int)
    def fight_once(self, w):
        self.fights[w.name] += 1
    def attrition(self, w):
        return self.fights[w.name]


def _w(name, limit, **kw):
    return WorldPlan(name=name, x=1, y=2, max_attrition=limit, **kw)


def test_each_world_fights_to_its_own_limit():
    sim = _Sim()
    worlds = [_w("A", 2), _w("B", 6)]
    status = run_round_robin(worlds, sim.fight_once, sim.attrition, sleep=lambda s: None)
    assert status["A"].done and status["A"].fights == 2 and status["A"].reason == "attrition_limit"
    assert status["B"].done and status["B"].fights == 6
    assert all(s.done for s in status.values())


def test_rotation_is_fair_across_worlds():
    sim = _Sim()
    worlds = [_w("A", 999), _w("B", 999)]
    # cap total at 4 with burst 2 → each world fought twice before the cap
    status = run_round_robin(worlds, sim.fight_once, sim.attrition, burst=2,
                             max_total_fights=4, sleep=lambda s: None)
    assert sim.fights["A"] == 2 and sim.fights["B"] == 2


def test_done_world_left_alone_others_continue():
    sim = _Sim()
    worlds = [_w("A", 1), _w("B", 5)]
    status = run_round_robin(worlds, sim.fight_once, sim.attrition, burst=3,
                             sleep=lambda s: None)
    assert status["A"].fights == 1 and status["B"].fights == 5    # A stopped early, B ran on


def test_unknown_attrition_world_is_skipped_not_fought():
    sim = _Sim()
    worlds = [_w("A", 5)]
    status = run_round_robin(worlds, sim.fight_once, lambda w: None, sleep=lambda s: None)
    assert sim.fights["A"] == 0                      # never fought blind
    assert not status["A"].done and status["A"].reason == "no_data"


def test_unlimited_runs_until_total_cap():
    sim = _Sim()
    worlds = [_w("A", UNLIMITED)]
    status = run_round_robin(worlds, sim.fight_once, sim.attrition, max_total_fights=10,
                             sleep=lambda s: None)
    assert sim.fights["A"] == 10 and status["A"].reason == "max_total_fights"


def test_should_stop_halts_everything():
    sim = _Sim()
    worlds = [_w("A", 999), _w("B", 999)]
    calls = {"n": 0}
    def _stop():
        calls["n"] += 1
        return calls["n"] > 5
    status = run_round_robin(worlds, sim.fight_once, sim.attrition, burst=2,
                             sleep=lambda s: None, should_stop=_stop)
    assert not all(s.done for s in status.values())  # stopped before finishing


def test_events_report_done(capsys):
    sim = _Sim()
    events = []
    run_round_robin([_w("A", 2)], sim.fight_once, sim.attrition, sleep=lambda s: None,
                    on_event=lambda kind, w, st: events.append((kind, w.name)))
    assert ("done", "A") in events


# --- config loader ----------------------------------------------------------

def test_load_world_plans(tmp_path):
    cfg = tmp_path / "worlds.json"
    cfg.write_text(json.dumps({"worlds": [
        {"name": "cz6", "x": 1145, "y": 788, "max_attrition": 50, "tab": "cz6"},
        {"name": "cz8", "x": 1145, "y": 788},        # defaults: unlimited, key r
    ]}))
    worlds = load_world_plans(cfg)
    assert [w.name for w in worlds] == ["cz6", "cz8"]
    assert worlds[0].max_attrition == 50 and worlds[0].tab == "cz6"
    assert worlds[1].max_attrition == UNLIMITED and worlds[1].key == "r"


def test_load_world_plans_tolerates_trailing_commas(tmp_path):
    # a common hand-edit slip — trailing commas before } and ]
    cfg = tmp_path / "worlds.json"
    cfg.write_text(
        '{"worlds": [\n'
        '  {"name": "cz7", "tab": "cz7", "x": 1145, "y": 788, "max_attrition": 10,},\n'
        '  {"name": "cz5", "tab": "cz5", "x": 1145, "y": 788, "max_attrition": 10,},\n'
        ']}\n')
    worlds = load_world_plans(cfg)
    assert [w.name for w in worlds] == ["cz7", "cz5"]
    assert worlds[0].max_attrition == 10


def test_load_world_plans_empty_is_error(tmp_path):
    cfg = tmp_path / "empty.json"
    cfg.write_text(json.dumps({"worlds": []}))
    with pytest.raises(ValueError):
        load_world_plans(cfg)
