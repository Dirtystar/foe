"""Map layout + map→screen transform (foundation of province auto-selection, B3).
Proven against the real map-data fixture. Pure geometry, no browser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bap.forge.gbg_data.advisor import rank_targets
from bap.forge.gbg_data.map_layout import (
    MapTransform,
    parse_map_data,
    province_screen_point,
)
from bap.forge.gbg_data.parser import parse_battleground

_SAMPLES = Path(__file__).parents[4] / "dataset" / "api_samples"
_MAP = _SAMPLES / "map_data.volcano_archipelago.sample.json"
_BG = _SAMPLES / "getBattleground.sample.json"


@pytest.fixture(scope="module")
def layout():
    return parse_map_data(json.loads(_MAP.read_text(encoding="utf-8")))


def test_parses_all_province_flags(layout):
    assert layout is not None
    assert layout.width == 2500 and layout.height == 1960
    assert len(layout.flags) == 60
    assert layout.flag(0) == (1249.0, 816.0)


def test_every_battleground_province_has_a_flag(layout):
    bg = parse_battleground(json.loads(_BG.read_text(encoding="utf-8")))
    ids = {p.id for p in bg.provinces}
    assert ids <= set(layout.flags)              # every target has a known position


def test_parse_map_data_rejects_non_map():
    assert parse_map_data({"foo": 1}) is None
    assert parse_map_data([]) is None


# --- transform + calibration -------------------------------------------------

def test_two_point_calibration_then_place_any_province(layout):
    # pretend the map renders at 0.5 scale, offset (100, 60): screen = 0.5*map + off
    true = MapTransform(0.5, 0.5, 100.0, 60.0)
    a_id, b_id = 0, 5                             # two provinces apart in x and y
    a_map, b_map = layout.flag(a_id), layout.flag(b_id)
    a_scr, b_scr = true.to_screen(*a_map), true.to_screen(*b_map)

    solved = MapTransform.from_two_points(a_map, a_scr, b_map, b_scr)
    assert solved.scale_x == pytest.approx(0.5) and solved.off_x == pytest.approx(100.0)
    # any other province now lands where the true transform says
    for pid in (1, 2, 10, 42):
        got = province_screen_point(layout, solved, pid)
        want = true.to_screen(*layout.flag(pid))
        assert got == pytest.approx(want)


def test_calibration_needs_distinct_axes(layout):
    with pytest.raises(ValueError):
        MapTransform.from_two_points((10, 20), (0, 0), (10, 99), (5, 5))   # same x


def test_province_screen_point_unknown_id_is_none(layout):
    assert province_screen_point(layout, MapTransform(1, 1, 0, 0), 9999) is None


# --- % allowlist selection ---------------------------------------------------

def test_allowlist_filters_targets_by_percentage():
    bg = parse_battleground(json.loads(_BG.read_text(encoding="utf-8")))
    only20 = rank_targets(bg, include_locked=True, allowed_pcts={20})
    assert only20 and all(t.gain_attrition_chance == 20 for t in only20)
    none_allowed = rank_targets(bg, include_locked=True, allowed_pcts={80})
    assert none_allowed == []                    # sample has no open 80% attackable target
