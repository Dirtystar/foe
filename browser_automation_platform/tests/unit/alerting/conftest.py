"""Shared builders: a battleground snapshot shaped exactly like the game's, but tiny."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bap.forge.gbg_data.model import (
    Battleground,
    ConquestProgress,
    Participant,
    PlayerState,
    Province,
)

ME = 100
ENEMY = 200

# A summer afternoon: 14:00 UTC == 16:00 in Prague, so times in tests read like the alerts do.
NOW = int(datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc).timestamp())


def province(pid, *, owner=ENEMY, opens_in=None, siege_by=None, max_progress=132,
             attack_type=None, attrition=None):
    """``attack_type`` mirrors the game's ``isAttackBattleType``: the payload omits the key
    instead of sending ``false``, so ``None`` is the real "defence" shape. ``attrition`` is
    ``gainAttritionChance`` — absent on provinces we own."""
    return Province(
        id=pid,
        owner_id=owner,
        locked_until=None if opens_in is None else NOW + opens_in,
        is_attack_battle_type=attack_type,
        gain_attrition_chance=attrition,
        conquest_progress=(() if siege_by is None
                           else (ConquestProgress(siege_by, 10, max_progress),)),
    )


def battleground(provinces, *, focus=(), ignore=(), me=ME, server_time=None):
    return Battleground(
        map_id="test_map",
        provinces=tuple(provinces),
        participants={ME: Participant(ME, "Nase Cechy", "orange"),
                      ENEMY: Participant(ENEMY, "Souperi", "green")},
        player=PlayerState(participant_id=me),
        focus_ids=tuple(focus),
        ignore_ids=tuple(ignore),
        server_time=server_time,
        observed_at=datetime.fromtimestamp(NOW, tz=timezone.utc).isoformat(),
    )


@pytest.fixture
def now():
    return NOW
