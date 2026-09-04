"""Rank the best provinces to attack — purely from the structured data.

This is the Phase-1 "brain": given a parsed :class:`Battleground`, it explains which
provinces are the best attack targets and why, using the exact fields the pixel pipeline
could only approximate — chiefly ``gain_attrition_chance`` (lower = you gain attrition less
often = better to farm). It is **advisory and read-only**: it selects and explains, it does
not click and it does not decide to act. Acting on a suggestion is a later, separate step.
"""

from __future__ import annotations

from dataclasses import dataclass

from bap.forge.gbg_data.model import Battleground, Province


@dataclass(frozen=True)
class TargetSuggestion:
    """One ranked attack candidate, with the facts behind the ranking."""

    province_id: int
    gain_attrition_chance: int | None
    owner_colour: str
    owner_name: str
    building_fraction: str | None
    locked: bool
    locked_until: int | None
    under_siege: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "province_id": self.province_id,
            "gain_attrition_chance": self.gain_attrition_chance,
            "owner_colour": self.owner_colour,
            "owner_name": self.owner_name,
            "building_fraction": self.building_fraction,
            "locked": self.locked,
            "locked_until": self.locked_until,
            "under_siege": self.under_siege,
            "reason": self.reason,
        }


def _now_from(bg: Battleground, now: int | None) -> int:
    if now is not None:
        return now
    if bg.server_time is not None:
        return bg.server_time
    import time
    return int(time.time())


def is_attack_candidate(bg: Battleground, p: Province, now: int) -> bool:
    """A province worth ranking as an attack target: attack-type, not our own, and with a
    known attrition chance (the game exposes it for provinces you can currently act on)."""
    if p.is_attack_battle_type is not True:
        return False
    if bg.is_mine(p):
        return False
    if p.gain_attrition_chance is None:
        return False
    return True


def rank_targets(bg: Battleground, *, now: int | None = None,
                 include_locked: bool = False, allowed_pcts=None) -> list[TargetSuggestion]:
    """Return attack candidates, best first. Ordering: **lowest attrition chance wins**,
    open (unlocked) before locked, then soonest-to-unlock, then province id for stability.

    By default locked provinces are excluded; pass ``include_locked=True`` to keep them
    (flagged), e.g. to plan ahead for when they open. ``allowed_pcts`` (e.g. ``{20, 40}``)
    restricts to provinces whose ``gain_attrition_chance`` is in that set — the per-world
    "only attack these %" allowlist; ``None`` means all.
    """
    ref = _now_from(bg, now)
    allow = set(allowed_pcts) if allowed_pcts is not None else None
    out: list[TargetSuggestion] = []
    for p in bg.provinces:
        if not is_attack_candidate(bg, p, ref):
            continue
        if allow is not None and p.gain_attrition_chance not in allow:
            continue
        locked = p.is_locked(ref)
        if locked and not include_locked:
            continue
        owner = bg.owner_of(p)
        under_siege = bool(p.conquest_progress)
        bits = [f"attrition {p.gain_attrition_chance}%"]
        if owner:
            bits.append(f"{owner.colour} ({owner.clan_name})")
        if locked:
            bits.append("locked")
        if under_siege:
            bits.append("under siege")
        out.append(TargetSuggestion(
            province_id=p.id,
            gain_attrition_chance=p.gain_attrition_chance,
            owner_colour=owner.colour if owner else "",
            owner_name=owner.clan_name if owner else "",
            building_fraction=p.building_fraction,
            locked=locked,
            locked_until=p.locked_until,
            under_siege=under_siege,
            reason=", ".join(bits),
        ))

    def _key(s: TargetSuggestion):
        return (
            s.locked,                                        # open first
            s.gain_attrition_chance if s.gain_attrition_chance is not None else 999,
            s.locked_until if s.locked_until is not None else 1 << 62,
            s.province_id,
        )

    out.sort(key=_key)
    return out


__all__ = ["TargetSuggestion", "rank_targets", "is_attack_candidate"]
