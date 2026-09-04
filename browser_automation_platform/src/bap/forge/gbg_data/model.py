"""Typed model of the Guild-Battlegrounds structured data (the game's own JSON).

These mirror the real `GuildBattlegroundService.getBattleground` payload confirmed from a
live capture (see `docs/design/GBG_API_SCHEMA.md`; fixtures in `dataset/api_samples/`).
Every field is optional-friendly: a missing/malformed value becomes ``None`` rather than
raising, so a game-side change degrades gracefully instead of crashing the reader.

This is a **read-only** perception model. It describes what the game says; it decides
nothing and clicks nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Participant:
    """A guild taking part in this battleground (maps to a territory colour)."""

    participant_id: int
    clan_name: str
    colour: str
    victory_points: int | None = None


@dataclass(frozen=True)
class ConquestProgress:
    """One guild's siege progress on a province."""

    participant_id: int
    progress: int
    max_progress: int

    @property
    def fraction(self) -> float | None:
        if not self.max_progress:
            return None
        return self.progress / self.max_progress


@dataclass(frozen=True)
class Province:
    """A single GBG province/sector as the game reports it."""

    id: int
    owner_id: int | None = None
    locked_until: int | None = None                 # unix seconds; when it next opens
    gain_attrition_chance: int | None = None        # 0/20/40/60/80/100 — the map "%" badge
    used_building_slots: int | None = None
    total_building_slots: int | None = None
    is_attack_battle_type: bool | None = None       # attack vs negotiate
    victory_points: int | None = None
    victory_points_bonus: int | None = None
    conquest_progress: tuple[ConquestProgress, ...] = ()

    def is_locked(self, now: int) -> bool:
        """True when the province is still on cooldown at ``now`` (unix seconds)."""
        return self.locked_until is not None and self.locked_until > now

    @property
    def building_fraction(self) -> str | None:
        if self.total_building_slots is None:
            return None
        return f"{self.used_building_slots or 0}/{self.total_building_slots}"


@dataclass(frozen=True)
class PlayerState:
    """The current player's own battleground state."""

    participant_id: int | None = None
    attrition_level: int | None = None              # how weakened *you* already are
    negotiation_multiplier: int | None = None
    active_trial: int | None = None


@dataclass(frozen=True)
class Battleground:
    """The whole battleground snapshot, plus when we observed it."""

    map_id: str | None
    provinces: tuple[Province, ...]
    participants: dict[int, Participant]
    player: PlayerState
    ends_at: int | None = None
    pending_update_at: int | None = None
    pending_province_ids: tuple[int, ...] = ()
    server_time: int | None = None                  # game's own clock, if the batch carried it
    observed_at: str = ""                            # ISO timestamp we parsed it (freshness)
    raw_source: str = "game_json"

    def owner_of(self, province: Province) -> Participant | None:
        if province.owner_id is None:
            return None
        return self.participants.get(province.owner_id)

    def is_mine(self, province: Province) -> bool:
        return (self.player.participant_id is not None
                and province.owner_id == self.player.participant_id)


__all__ = [
    "Participant", "ConquestProgress", "Province", "PlayerState", "Battleground",
]
