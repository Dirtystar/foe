"""Live GBG reader core: feed /game/json bodies, keep the freshest battleground snapshot,
and expose ranked targets. Transport-agnostic — no browser needed. Read-only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bap.forge.gbg_data import LiveGbgReader, make_response_handler, render

_FIXTURE = (Path(__file__).parents[4]
            / "dataset" / "api_samples" / "getBattleground.sample.json")


@pytest.fixture(scope="module")
def bg_body() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def _game_json_batch(bg_obj) -> list:
    return [
        {"requestClass": "TimeService", "requestMethod": "updateTime",
         "responseData": {"time": 1788206320}},
        {"requestClass": "GuildBattlegroundService", "requestMethod": "getBattleground",
         "responseData": bg_obj},
    ]


def test_feed_dict_updates_snapshot(bg_body):
    r = LiveGbgReader()
    assert r.snapshot is None
    assert r.feed(json.loads(bg_body)) is True
    assert r.snapshot is not None and len(r.snapshot.provinces) == 60
    assert r.update_count == 1
    assert r.targets(), "advisor should surface targets from the live snapshot"


def test_feed_accepts_raw_string_and_batch(bg_body):
    r = LiveGbgReader()
    batch = _game_json_batch(json.loads(bg_body))
    assert r.feed(json.dumps(batch)) is True          # raw string of a /game/json array
    assert r.snapshot.server_time == 1788206320


def test_non_battleground_body_is_ignored_keeping_last_good(bg_body):
    r = LiveGbgReader()
    r.feed(json.loads(bg_body))
    good = r.snapshot
    # a typical /game/json with no battleground (e.g. just time/messages)
    assert r.feed('[{"requestClass":"TimeService","responseData":{"time":1}}]') is False
    assert r.snapshot is good and r.update_count == 1  # unchanged, last good kept


@pytest.mark.parametrize("junk", ["not json", "", "{", b"\xff\xfe", "null", "[]"])
def test_garbage_never_raises_and_never_updates(junk):
    r = LiveGbgReader()
    assert r.feed(junk) is False and r.snapshot is None


def test_targets_empty_before_any_feed():
    assert LiveGbgReader().targets() == []


# --- response-handler wiring (fake Response, no browser) ---------------------

class _FakeResp:
    def __init__(self, url, body): self.url = url; self._b = body
    def text(self): return self._b


def test_handler_filters_and_feeds_on_game_json(bg_body):
    r = LiveGbgReader()
    seen = []
    handle = make_response_handler(r, on_update=lambda rr: seen.append(rr.update_count))
    handle(_FakeResp("https://cz6.forgeofempires.com/other", bg_body))   # wrong URL → ignored
    assert r.snapshot is None and seen == []
    handle(_FakeResp("https://cz6.forgeofempires.com/game/json?h=x", bg_body))
    assert r.snapshot is not None and seen == [1]


def test_handler_survives_body_read_error():
    r = LiveGbgReader()
    class _Boom:
        url = "https://x/game/json"
        def text(self): raise RuntimeError("no body")
    make_response_handler(r)( _Boom() )                 # must not raise
    assert r.snapshot is None


def _battle_body(level):
    """A /game/json battle response carrying getPlayerParticipant (live attrition)."""
    return json.dumps([
        {"requestClass": "TimeService", "requestMethod": "updateTime",
         "responseData": {"time": 1}},
        {"requestClass": "GuildBattlegroundService", "requestMethod": "getPlayerParticipant",
         "responseData": {"activeTrial": 30,
                          "attrition": {"level": level, "negotiationMultiplier": 3}}},
    ])


def test_attrition_updates_live_from_battle_response():
    r = LiveGbgReader()
    assert r.attrition_level is None
    assert r.feed(_battle_body(1)) is True
    assert r.attrition_level == 1               # from getPlayerParticipant, no full battleground
    assert r.snapshot is None                   # a battle response has no map
    assert r.feed(_battle_body(2)) is True
    assert r.attrition_level == 2               # climbs live as you fight


def test_battleground_sets_attrition_then_battles_refine_it(bg_body):
    r = LiveGbgReader()
    r.feed(bg_body)                             # full battleground → baseline attrition + map
    assert r.snapshot is not None
    base = r.attrition_level
    assert base is not None
    r.feed(_battle_body(base + 5))              # a later battle updates just attrition
    assert r.attrition_level == base + 5
    assert r.snapshot is not None               # map snapshot retained


def test_battle_without_attrition_is_ignored():
    r = LiveGbgReader()
    body = json.dumps([{"requestClass": "BattlefieldService",
                        "requestMethod": "getArmyPreview", "responseData": {"foo": 1}}])
    assert r.feed(body) is False and r.attrition_level is None


def test_render_before_and_after(bg_body):
    r = LiveGbgReader()
    assert "waiting for GBG data" in render(r)
    r.feed(json.loads(bg_body))
    out = render(r)
    assert "attrition" in out and "province" in out
