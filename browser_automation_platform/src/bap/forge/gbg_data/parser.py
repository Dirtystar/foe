"""Parse the game's Guild-Battlegrounds JSON into the typed model — defensively.

Two entry points:

- :func:`parse_battleground` — from a `GuildBattlegroundService.getBattleground`
  ``responseData`` dict (the `{league, map, battlegroundParticipants, …}` object).
- :func:`parse_game_json` — from a raw ``/game/json`` response (a list of `ServerResponse`
  objects); it finds the getBattleground entry and parses it, and picks up the server clock
  from a `TimeService.updateTime` entry when present.

Both are best-effort: anything missing or the wrong type becomes ``None`` / is skipped, and
an unrecognisable payload returns ``None`` instead of raising. Read-only — no side effects.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from bap.forge.gbg_data.model import (
    Battleground,
    ConquestProgress,
    Participant,
    PlayerState,
    Province,
)

logger = logging.getLogger("bap.forge.gbg_data")

_BG_CLASS = "GuildBattlegroundService"
_BG_METHOD = "getBattleground"


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def parse_participant(d: dict) -> Participant | None:
    pid = _as_int(d.get("participantId"))
    if pid is None:
        return None
    clan = d.get("clan") or {}
    return Participant(
        participant_id=pid,
        clan_name=str(clan.get("name", "")),
        colour=str(d.get("colour", "")),
        victory_points=_as_int(d.get("victoryPoints")),
    )


def parse_conquest(d: dict) -> ConquestProgress | None:
    pid = _as_int(d.get("participantId"))
    prog = _as_int(d.get("progress"))
    mx = _as_int(d.get("maxProgress"))
    if pid is None or prog is None or mx is None:
        return None
    return ConquestProgress(participant_id=pid, progress=prog, max_progress=mx)


def parse_province(d: dict) -> Province:
    cps = tuple(c for c in (parse_conquest(x) for x in (d.get("conquestProgress") or [])
                            if isinstance(x, dict)) if c is not None)
    return Province(
        id=_as_int(d.get("id")) or 0,          # the first province omits "id" → 0
        owner_id=_as_int(d.get("ownerId")),
        locked_until=_as_int(d.get("lockedUntil")),
        gain_attrition_chance=_as_int(d.get("gainAttritionChance")),
        used_building_slots=_as_int(d.get("usedBuildingSlots")),
        total_building_slots=_as_int(d.get("totalBuildingSlots")),
        is_attack_battle_type=d.get("isAttackBattleType")
            if isinstance(d.get("isAttackBattleType"), bool) else None,
        victory_points=_as_int(d.get("victoryPoints")),
        victory_points_bonus=_as_int(d.get("victoryPointsBonus")),
        conquest_progress=cps,
    )


def parse_player(d: dict) -> PlayerState:
    attr = d.get("attrition") or {}
    return PlayerState(
        participant_id=None,  # set by the caller from currentParticipantId
        attrition_level=_as_int(attr.get("level")),
        negotiation_multiplier=_as_int(attr.get("negotiationMultiplier")),
        active_trial=_as_int(d.get("activeTrial")),
    )


def parse_player_participant(response_data) -> PlayerState | None:
    """Parse a `GuildBattlegroundService.getPlayerParticipant` responseData — the player's
    attrition as it updates **during fighting** (bundled in the battle response). Returns
    None if it doesn't carry attrition."""
    if not isinstance(response_data, dict) or "attrition" not in response_data:
        return None
    return parse_player(response_data)


def parse_player_from_game_json(batch) -> PlayerState | None:
    """Find a `getPlayerParticipant` (live attrition during battles) in a `/game/json`
    batch. Returns None if absent."""
    if not isinstance(batch, list):
        return None
    for r in batch:
        if (isinstance(r, dict) and r.get("requestClass") == _BG_CLASS
                and r.get("requestMethod") == "getPlayerParticipant"):
            return parse_player_participant(r.get("responseData"))
    return None


def parse_battleground(response_data, *, server_time: int | None = None,
                       observed_at: str | None = None) -> Battleground | None:
    """Parse a getBattleground ``responseData`` dict into a :class:`Battleground`.
    Returns ``None`` if it does not look like a battleground payload."""
    if not isinstance(response_data, dict) or "map" not in response_data:
        return None
    try:
        mp = response_data.get("map") or {}
        provinces = tuple(parse_province(p) for p in (mp.get("provinces") or [])
                          if isinstance(p, dict))
        participants = {}
        for p in (response_data.get("battlegroundParticipants") or []):
            if isinstance(p, dict):
                part = parse_participant(p)
                if part is not None:
                    participants[part.participant_id] = part
        player = parse_player(response_data.get("currentPlayerParticipant") or {})
        me = _as_int(response_data.get("currentParticipantId"))
        if me is not None:
            player = PlayerState(
                participant_id=me, attrition_level=player.attrition_level,
                negotiation_multiplier=player.negotiation_multiplier,
                active_trial=player.active_trial)
        pending = mp.get("pendingUpdate") or {}
        return Battleground(
            map_id=mp.get("id"),
            provinces=provinces,
            participants=participants,
            player=player,
            ends_at=_as_int(response_data.get("endsAt")),
            pending_update_at=_as_int(pending.get("updateAt")),
            pending_province_ids=tuple(
                x for x in (_as_int(i) for i in (pending.get("provinceIds") or [])) if x is not None),
            server_time=server_time,
            observed_at=observed_at or _now_iso(),
        )
    except Exception:  # never crash the reader on a shape we didn't expect
        logger.warning("failed to parse getBattleground payload", exc_info=True)
        return None


def _server_time_from_batch(batch: list) -> int | None:
    for r in batch:
        if isinstance(r, dict) and r.get("requestClass") == "TimeService":
            t = (r.get("responseData") or {})
            return _as_int(t.get("time")) if isinstance(t, dict) else None
    return None


def parse_game_json(batch, *, observed_at: str | None = None) -> Battleground | None:
    """Parse a raw ``/game/json`` response array: find the getBattleground entry (and the
    server clock) and parse it. Returns ``None`` if the batch carries no battleground."""
    if not isinstance(batch, list):
        return None
    server_time = _server_time_from_batch(batch)
    for r in batch:
        if (isinstance(r, dict) and r.get("requestClass") == _BG_CLASS
                and r.get("requestMethod") == _BG_METHOD):
            return parse_battleground(r.get("responseData"), server_time=server_time,
                                      observed_at=observed_at)
    return None


def parse(obj, *, observed_at: str | None = None) -> Battleground | None:
    """Convenience: accept either a raw /game/json list, a getBattleground responseData
    dict, or a single ServerResponse wrapper, and parse whichever it is."""
    if isinstance(obj, list):
        return parse_game_json(obj, observed_at=observed_at)
    if isinstance(obj, dict):
        if "map" in obj:
            return parse_battleground(obj, observed_at=observed_at)
        if obj.get("requestClass") == _BG_CLASS:
            return parse_battleground(obj.get("responseData"), observed_at=observed_at)
    return None


__all__ = ["parse", "parse_battleground", "parse_game_json",
           "parse_player_participant", "parse_player_from_game_json"]
