"""Config parsing (secrets from the environment, quiet hours) and the sent-log file."""

from __future__ import annotations

import json

from bap.alerting.config import AlertConfig
from bap.alerting.state import SentLog


def test_defaults_are_usable_without_a_file(tmp_path):
    cfg = AlertConfig.load(tmp_path / "missing.json")
    assert cfg.world == "cz8" and cfg.scope == "relevant"
    assert cfg.tab_match == "cz8.forgeofempires"
    assert cfg.trigger_lead_seconds == 240 and cfg.window_seconds == 1800
    assert cfg.side_rule == "battle_type" and cfg.notifier == "console"


def test_file_values_are_read(tmp_path):
    path = tmp_path / "alerting.json"
    path.write_text(json.dumps({"world": "cz1", "scope": "labeled",
                                "trigger_lead_minutes": 3, "window_minutes": 45,
                                "quiet_hours": [23, 7], "header": "GBG"}), encoding="utf-8")
    cfg = AlertConfig.load(path)
    assert (cfg.world, cfg.scope, cfg.header) == ("cz1", "labeled", "GBG")
    assert (cfg.trigger_lead_seconds, cfg.window_seconds) == (180, 2700)
    assert cfg.quiet_hours == (23, 7)


def test_the_old_lead_minutes_name_still_sets_the_trigger_lead():
    """``lead_minutes`` was the knob before batching existed; an existing config file
    should not silently fall back to the default."""
    assert AlertConfig.from_dict({"lead_minutes": 7}).trigger_lead_seconds == 420


def test_unknown_side_rule_is_rejected():
    assert AlertConfig.from_dict({"side_rule": "vibes"}).side_rule == "battle_type"


def test_broken_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "alerting.json"
    path.write_text("{oops", encoding="utf-8")
    assert AlertConfig.load(path).world == "cz8"


def test_unknown_scope_is_rejected():
    assert AlertConfig.from_dict({"scope": "everything"}).scope == "relevant"


def test_env_wins_over_file_for_secrets(monkeypatch):
    monkeypatch.setenv("GREEN_API_TOKEN", "from-env")
    cfg = AlertConfig.from_dict({"green_api": {"api_token": "from-file", "chat_id": "c"}})
    assert cfg.green_api.api_token == "from-env" and cfg.green_api.chat_id == "c"


def test_quiet_hours_wrap_over_midnight():
    cfg = AlertConfig.from_dict({"quiet_hours": [23, 7]})
    assert cfg.in_quiet_hours(23) and cfg.in_quiet_hours(3) and cfg.in_quiet_hours(6)
    assert not cfg.in_quiet_hours(7) and not cfg.in_quiet_hours(16)


def test_quiet_hours_daytime_window_and_none():
    assert AlertConfig.from_dict({"quiet_hours": [9, 12]}).in_quiet_hours(10)
    assert not AlertConfig.from_dict({}).in_quiet_hours(3)
    assert not AlertConfig.from_dict({"quiet_hours": [5, 5]}).in_quiet_hours(5)
    assert not AlertConfig.from_dict({"quiet_hours": "nonsense"}).in_quiet_hours(3)


def test_sent_log_round_trip(tmp_path):
    path = tmp_path / "state.json"
    log = SentLog(path)
    log.record(["1:100", "2:200"], now=1000)
    assert "1:100" in SentLog(path)


def test_sent_log_prunes_yesterday(tmp_path):
    path = tmp_path / "state.json"
    log = SentLog(path)
    log.record(["old:1"], now=0)
    log.record(["new:2"], now=48 * 3600)
    reloaded = SentLog(path)
    assert "new:2" in reloaded and "old:1" not in reloaded


def test_sent_log_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json", encoding="utf-8")
    log = SentLog(path)
    assert log.keys == frozenset()
    log.record(["a:1"], now=10)                 # and still writes cleanly afterwards
    assert "a:1" in SentLog(path)
