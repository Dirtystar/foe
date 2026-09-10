"""Native leader marks (Cíl/Stop) parsed from getBattleground.battlegroundParticipants[].signals."""

from __future__ import annotations

from bap.forge.gbg_data.parser import parse_battleground

# Shape confirmed from a live capture: focus=Cíl/attack, ignore=Stop.
_SIGNALS = [
    {"provinceId": 2, "signal": "focus", "__class__": "GuildBattlegroundProvinceSignal"},
    {"provinceId": 20, "signal": "focus", "__class__": "GuildBattlegroundProvinceSignal"},
    {"provinceId": 11, "signal": "ignore", "__class__": "GuildBattlegroundProvinceSignal"},
    {"provinceId": 14, "signal": "ignore", "__class__": "GuildBattlegroundProvinceSignal"},
]


def _bg(participants):
    return {"map": {"id": "m1", "provinces": []},
            "currentParticipantId": 100,
            "battlegroundParticipants": participants}


def test_parses_our_guild_signals():
    bg = parse_battleground(_bg([{"participantId": 100, "signals": _SIGNALS}]))
    assert set(bg.focus_ids) == {2, 20}
    assert set(bg.ignore_ids) == {11, 14}


def test_prefers_our_participant_over_others():
    other = [{"provinceId": 99, "signal": "focus"}]
    bg = parse_battleground(_bg([
        {"participantId": 100, "signals": _SIGNALS},
        {"participantId": 200, "signals": other},   # a rival guild's marks — ignored
    ]))
    assert 99 not in bg.focus_ids and set(bg.focus_ids) == {2, 20}


def test_falls_back_to_all_when_id_key_differs():
    # participant id under an unexpected key → we can't match "me", so union all
    bg = parse_battleground(_bg([{"id": 100, "signals": _SIGNALS}]))
    assert set(bg.focus_ids) == {2, 20} and set(bg.ignore_ids) == {11, 14}


def test_no_signals_is_empty():
    bg = parse_battleground(_bg([{"participantId": 100}]))
    assert bg.focus_ids == () and bg.ignore_ids == ()


def test_missing_participants_is_empty():
    bg = parse_battleground({"map": {"id": "m", "provinces": []}})
    assert bg.focus_ids == () and bg.ignore_ids == ()
