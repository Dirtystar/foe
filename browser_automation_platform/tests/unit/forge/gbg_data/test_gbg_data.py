"""Phase-1 GBG structured-data reader: parse the game's JSON and rank attack targets.

Proven against the real sanitized capture in `dataset/api_samples/` plus synthetic edge
cases. Read-only — no game interaction anywhere in these tests.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from bap.forge.gbg_data import (
    Battleground,
    Participant,
    PlayerState,
    Province,
    parse,
    parse_battleground,
    parse_game_json,
    rank_targets,
)
from bap.forge.gbg_data.advisor import is_attack_candidate

_FIXTURE = (Path(__file__).parents[4]
            / "dataset" / "api_samples" / "getBattleground.sample.json")


@pytest.fixture(scope="module")
def real_bg() -> Battleground:
    bg = parse_battleground(json.loads(_FIXTURE.read_text(encoding="utf-8")))
    assert bg is not None
    return bg


# --- parsing the real payload ------------------------------------------------

def test_parses_real_capture(real_bg):
    assert real_bg.map_id == "volcano_archipelago"
    assert len(real_bg.provinces) == 60
    assert len(real_bg.participants) == 7
    assert real_bg.player.participant_id == 103787       # Piráti
    assert real_bg.player.attrition_level == 67
    assert real_bg.observed_at                            # freshness stamped


def test_attrition_chance_distribution_matches_pixel_value_space(real_bg):
    dist = collections.Counter(p.gain_attrition_chance for p in real_bg.provinces)
    # the exact 20/40/60/80/100 space the pixel classifier tries to OCR
    assert dist[20] == 17 and dist[40] == 4 and dist[60] == 5 and dist[100] == 12
    assert all((v is None or v % 20 == 0) for v in dist)


def test_owner_mapping_and_is_mine(real_bg):
    mine = [p for p in real_bg.provinces if real_bg.is_mine(p)]
    assert mine, "player should own at least one province"
    p = mine[0]
    owner = real_bg.owner_of(p)
    assert owner is not None and owner.colour == "orange" and owner.clan_name == "Piráti"


def test_conquest_progress_parsed(real_bg):
    sieged = [p for p in real_bg.provinces if p.conquest_progress]
    assert sieged, "sample has provinces under siege"
    cp = sieged[0].conquest_progress[0]
    assert cp.max_progress > 0 and 0.0 <= (cp.fraction or 0) <= 1.0


# --- advisor -----------------------------------------------------------------

def test_advisor_ranks_real_targets_by_attrition(real_bg):
    targets = rank_targets(real_bg)                       # open, not mine
    assert targets, "expected some open attack targets"
    chances = [t.gain_attrition_chance for t in targets]
    assert chances == sorted(chances)                     # lowest attrition first
    assert all(t.owner_colour != "orange" for t in targets)   # never my own
    assert not any(t.locked for t in targets)             # locked excluded by default


def test_include_locked_returns_more(real_bg):
    open_only = rank_targets(real_bg)
    with_locked = rank_targets(real_bg, include_locked=True)
    assert len(with_locked) >= len(open_only)
    # every open target still appears, and locked ones sort after open ones
    assert [t.locked for t in with_locked] == sorted(t.locked for t in with_locked)


# --- parser entry points & defensiveness ------------------------------------

def test_parse_game_json_batch_finds_battleground():
    batch = [
        {"requestClass": "TimeService", "requestMethod": "updateTime",
         "responseData": {"time": 1788206320}},
        {"requestClass": "GuildBattlegroundService", "requestMethod": "getBattleground",
         "responseData": {"map": {"id": "m", "provinces": []},
                          "battlegroundParticipants": [], "currentParticipantId": 5,
                          "currentPlayerParticipant": {"attrition": {"level": 3}}}},
    ]
    bg = parse_game_json(batch)
    assert bg is not None and bg.server_time == 1788206320
    assert bg.player.participant_id == 5 and bg.player.attrition_level == 3


@pytest.mark.parametrize("bad", [None, 42, "x", {}, {"foo": 1}, [], [1, 2]])
def test_parse_rejects_non_battleground(bad):
    assert parse(bad) is None


def test_parser_survives_malformed_province():
    data = {"map": {"id": "m", "provinces": [
        {"id": 1, "ownerId": "notint", "gainAttritionChance": None},
        "garbage",                                        # skipped, no crash
        {"conquestProgress": [{"bad": 1}]},               # bad siege entry dropped
    ]}, "battlegroundParticipants": ["nope"], "currentParticipantId": 1,
        "currentPlayerParticipant": {}}
    bg = parse_battleground(data)
    assert bg is not None and len(bg.provinces) == 2      # "garbage" string skipped
    assert bg.provinces[0].owner_id is None               # unparseable → None


# --- advisor edge cases (synthetic, deterministic) --------------------------

def _bg(provinces, *, me=1, parts=None, server_time=1000):
    participants = parts or {2: Participant(2, "Foe", "red"), 1: Participant(1, "Me", "orange")}
    return Battleground(map_id="m", provinces=tuple(provinces), participants=participants,
                        player=PlayerState(participant_id=me, attrition_level=0),
                        server_time=server_time)


def test_candidate_excludes_own_and_negotiate_and_unknown():
    mine = Province(id=1, owner_id=1, gain_attrition_chance=20, is_attack_battle_type=True)
    negotiate = Province(id=2, owner_id=2, gain_attrition_chance=20, is_attack_battle_type=False)
    unknown = Province(id=3, owner_id=2, gain_attrition_chance=None, is_attack_battle_type=True)
    good = Province(id=4, owner_id=2, gain_attrition_chance=20, is_attack_battle_type=True)
    bg = _bg([mine, negotiate, unknown, good])
    assert not is_attack_candidate(bg, mine, 1000)
    assert not is_attack_candidate(bg, negotiate, 1000)
    assert not is_attack_candidate(bg, unknown, 1000)
    assert is_attack_candidate(bg, good, 1000)
    assert [t.province_id for t in rank_targets(bg)] == [4]


def test_locked_excluded_then_sorted_after_open():
    open20 = Province(id=1, owner_id=2, gain_attrition_chance=20, is_attack_battle_type=True)
    open40 = Province(id=2, owner_id=2, gain_attrition_chance=40, is_attack_battle_type=True)
    locked10 = Province(id=3, owner_id=2, gain_attrition_chance=20,
                        is_attack_battle_type=True, locked_until=5000)
    bg = _bg([open40, locked10, open20], server_time=1000)
    assert [t.province_id for t in rank_targets(bg)] == [1, 2]          # locked dropped, 20<40
    both = rank_targets(bg, include_locked=True)
    assert [t.province_id for t in both] == [1, 2, 3]                   # locked sorts last
