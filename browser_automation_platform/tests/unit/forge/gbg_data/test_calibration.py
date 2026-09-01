"""Calibration: capture map/data live, learn which province a click opened (provinceId
from the request), and solve+persist the map→screen transform. Pure logic, no browser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bap.forge.gbg_data.calibration import (
    CalibrationSample,
    load_calibration,
    save_calibration,
    solve_transform,
)
from bap.forge.gbg_data.live import LiveGbgReader
from bap.forge.gbg_data.map_layout import MapTransform, parse_map_data
from bap.forge.gbg_data.parser import parse_province_id_from_game_json

_MAP = (Path(__file__).parents[4] / "dataset" / "api_samples"
        / "map_data.volcano_archipelago.sample.json")


@pytest.fixture(scope="module")
def layout():
    return parse_map_data(json.loads(_MAP.read_text(encoding="utf-8")))


# --- live capture of the map/data asset -------------------------------------

def test_reader_captures_map_layout_from_map_data():
    r = LiveGbgReader()
    assert r.map_layout is None
    assert r.feed(_MAP.read_text(encoding="utf-8")) is True
    assert r.map_layout is not None and len(r.map_layout.flags) == 60


# --- provinceId from a request batch ----------------------------------------

def test_province_id_from_getarmyinfo_request():
    # the real shape opening a province fires (from the battle HAR)
    batch = [{"requestClass": "ArmyUnitManagementService", "requestMethod": "getArmyInfo",
              "requestData": [{"__class__": "BattlegroundArmyContext",
                               "battleType": "battleground", "provinceId": 2}]}]
    assert parse_province_id_from_game_json(batch) == 2


def test_province_id_absent_is_none():
    assert parse_province_id_from_game_json(
        [{"requestClass": "TimeService", "requestData": []}]) is None
    assert parse_province_id_from_game_json("nope") is None


# --- solve from two province clicks -----------------------------------------

def test_solve_transform_from_two_clicks_places_all(layout):
    true = MapTransform(0.5, 0.5, 100.0, 60.0)                 # pretend render transform
    a_id, b_id = 0, 5
    a = CalibrationSample(a_id, true.to_screen(*layout.flag(a_id)))
    b = CalibrationSample(b_id, true.to_screen(*layout.flag(b_id)))
    solved = solve_transform(layout, a, b)
    for pid in (1, 2, 10, 42):
        got = solved.to_screen(*layout.flag(pid))
        assert got == pytest.approx(true.to_screen(*layout.flag(pid)))


def test_solve_transform_rejects_unknown_province(layout):
    with pytest.raises(ValueError):
        solve_transform(layout, CalibrationSample(0, (1, 1)),
                        CalibrationSample(9999, (2, 2)))


# --- persistence ------------------------------------------------------------

def test_save_and_load_calibration_roundtrip(tmp_path):
    store = tmp_path / "calib.json"
    t = MapTransform(0.5, 0.6, 100.0, 60.0)
    save_calibration(store, "cz6", "volcano_archipelago", t)
    got = load_calibration(store, "cz6", "volcano_archipelago")
    assert got == t
    # a different world/map is independent
    assert load_calibration(store, "cz8", "volcano_archipelago") is None
    save_calibration(store, "cz8", "other_map", MapTransform(1, 1, 0, 0))
    assert load_calibration(store, "cz6", "volcano_archipelago") == t   # still there


def test_load_missing_calibration_is_none(tmp_path):
    assert load_calibration(tmp_path / "none.json", "cz6", "m") is None
