"""The browser glue, without a browser: only the watched world's game data reaches the engine."""

from __future__ import annotations

import pytest

import json

from conftest import ME, battleground, province

from bap.alerting.config import AlertConfig
from bap.alerting.engine import AlertEngine
from bap.alerting.labels import LabelBook
from bap.alerting.notifiers import NullNotifier
from bap.alerting.state import SentLog
from bap.alerting.watcher import make_handler, run_watch
from bap.forge.gbg_data.live import LiveGbgReader


class FakeResponse:
    def __init__(self, url: str, body, raises: bool = False) -> None:
        self.url = url
        self._body = body
        self._raises = raises

    def text(self) -> str:
        if self._raises:
            raise RuntimeError("body already consumed")
        return self._body if isinstance(self._body, str) else json.dumps(self._body)


def _engine(tmp_path):
    cfg = AlertConfig.from_dict({"trigger_lead_minutes": 10})   # the sample opens in 5 min
    return AlertEngine(cfg, NullNotifier(), SentLog(tmp_path / "s.json"),
                       LabelBook(overrides={}, auto={}))


def _game_json(response_data):
    return [{"requestClass": "GuildBattlegroundService", "requestMethod": "getBattleground",
             "responseData": response_data}]


def _battleground_payload(now):
    return {"map": {"id": "test_map",
                    "provinces": [{"id": 1, "ownerId": ME, "lockedUntil": now + 300}]},
            "battlegroundParticipants": [{"participantId": ME, "clan": {"name": "Nase"},
                                          "colour": "orange"}],
            "currentParticipantId": ME}


def test_a_battleground_response_reaches_the_engine(tmp_path, now):
    engine = _engine(tmp_path)
    handler = make_handler(LiveGbgReader(), engine)
    handler(FakeResponse("https://cz8.forgeofempires.com/game/json",
                         _game_json(_battleground_payload(now))))
    assert engine.snapshot is not None
    assert [e.province_id for e in engine.upcoming(now)] == [1]


def test_the_map_asset_supplies_labels(tmp_path, now):
    engine = _engine(tmp_path)
    handler = make_handler(LiveGbgReader(), engine)
    handler(FakeResponse("https://foede.innogamescdn.com/map/data/test_map",
                         {"size": {"width": 2500, "height": 1960},
                          "provinces": [{"id": 1, "flag": {"x": 0, "y": 0}}]}))
    assert engine.labels.label(1) == "A1"


def test_unrelated_traffic_is_ignored(tmp_path):
    engine = _engine(tmp_path)
    handler = make_handler(LiveGbgReader(), engine)
    handler(FakeResponse("https://cz8.forgeofempires.com/static/app.js", "not json"))
    assert engine.snapshot is None


def test_an_unreadable_body_never_raises(tmp_path):
    engine = _engine(tmp_path)
    handler = make_handler(LiveGbgReader(), engine)
    handler(FakeResponse("https://cz8.forgeofempires.com/game/json", "", raises=True))
    assert engine.snapshot is None


def test_a_later_snapshot_replaces_the_earlier_one(tmp_path, now):
    engine = _engine(tmp_path)
    handler = make_handler(LiveGbgReader(), engine)
    handler(FakeResponse("/game/json", _game_json(_battleground_payload(now))))
    later = _battleground_payload(now)
    later["map"]["provinces"][0]["lockedUntil"] = now + 900
    handler(FakeResponse("/game/json", _game_json(later)))
    assert engine.upcoming(now)[0].opens_at == now + 900


def test_the_snapshot_drives_a_real_alert(tmp_path, now):
    """The whole chain in one place: response → reader → engine → message."""
    engine = _engine(tmp_path)
    handler = make_handler(LiveGbgReader(), engine)
    handler(FakeResponse("/game/json", _game_json(_battleground_payload(now))))
    assert [e.province_id for e in engine.tick(now)] == [1]
    assert engine.notifier.sent == ["16:05 🔵 #1"]


def test_no_cdp_endpoint_falls_back_without_importing_the_farmer(tmp_path):
    """Regression: `run_watch` used to reach into `bap.forge.browser_settings` for the
    default CDP address. That module isn't in the hand-out bundle's file list (only
    `bap.forge.gbg_data` is), so `bap-alert run` without an explicit `--cdp` broke for anyone
    running from the ZIP — caught live, not by this suite, which is the bug this test exists
    to make impossible to reintroduce quietly.
    """
    import bap.alerting.watcher as watcher_module

    cfg = AlertConfig.from_dict({})
    assert cfg.cdp == ""                                # nothing configured either
    seen = {}

    def fake_connect(endpoint):
        seen["endpoint"] = endpoint
        raise RuntimeError("stop before actually touching a browser")

    with pytest.raises(RuntimeError, match="stop before"):
        run_watch(cfg, _engine(tmp_path), connect=fake_connect, once=True)
    assert seen["endpoint"] == watcher_module.DEFAULT_CDP_ENDPOINT == "http://127.0.0.1:9222"


def test_no_alerting_module_reaches_into_the_farmer_outside_gbg_data():
    """The whole subproject's rule is "shares no code path with the farmer's clicking code" —
    make that a fact about the source, not just an intention, so a stray `from bap.forge.x
    import y` (which works fine in the full dev checkout, and only breaks for someone running
    the small hand-out ZIP) gets caught here instead of live, by a guild officer, today."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[3] / "src" / "bap" / "alerting"
    offenders = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module
                if mod == "bap.forge" or mod.startswith("bap.forge.") and not (
                        mod == "bap.forge.gbg_data" or mod.startswith("bap.forge.gbg_data.")):
                    offenders.append(f"{path.name}:{node.lineno} imports from {mod}")
    assert not offenders, "\n".join(offenders)
