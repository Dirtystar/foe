"""Snapshot → "which provinces open, when, and on which side of the fight".

A GBG province is **locked** for a cooldown after it changes hands; ``province.lockedUntil``
is the unix second at which it opens again and fighting there can resume. One
``getBattleground`` snapshot therefore already describes every opening for the next few hours
— the alert does not need a live feed, only a reasonably fresh snapshot.

Side of the fight:

- the province is **ours** → when it opens the enemy can siege it → **defence** 🔵
- the province is someone else's → when it opens **we** can siege it → **attack** 🔴

Scope decides how much of a 60-province map is worth announcing:

``labeled``   only provinces the guild named in the labels file (its front line) — the
              sharpest filter, and it needs no game data at all.
``relevant``  ours, plus provinces our commander marked *focus*, plus provinces where our
              guild already has conquest progress. (default)
``mine``      only our own provinces (defence watch).
``all``       every locked province on the map.

Provinces the commander marked *ignore* ("Stop") are dropped from attack alerts — we are
explicitly told not to fight there — but never from defence alerts.
"""

from __future__ import annotations

from dataclasses import dataclass

ATTACK = "attack"
DEFENSE = "defense"
SCOPES = ("labeled", "relevant", "mine", "all")


@dataclass(frozen=True)
class UnlockEvent:
    """One province opening at one time."""

    province_id: int
    opens_at: int                       # unix seconds, game-server clock
    side: str                           # ATTACK | DEFENSE
    label: str                          # "A1X" — what the guild calls this province
    owner_colour: str | None = None
    owner_clan: str | None = None

    @property
    def key(self) -> str:
        """Identity of *this* opening — a province re-locking later is a new event."""
        return f"{self.province_id}:{self.opens_at}"


def _we_are_sieging(province, me) -> bool:
    return any(cp.participant_id == me for cp in (province.conquest_progress or ()))


def in_scope(bg, province, *, scope: str, named_ids=frozenset()) -> bool:
    me = bg.player.participant_id if bg.player else None
    mine = me is not None and province.owner_id == me
    if scope == "all":
        return True
    if scope == "mine":
        return mine
    if scope == "labeled":
        return province.id in named_ids
    # "relevant"
    return mine or province.id in (bg.focus_ids or ()) or _we_are_sieging(province, me)


def unlock_events(bg, *, labels=None, scope: str = "relevant", now: float,
                  horizon_seconds: int | None = None) -> list[UnlockEvent]:
    """Every still-locked province in scope, as :class:`UnlockEvent`s sorted by time.

    ``now`` is on the **game clock** (see :func:`bap.alerting.clock.game_now`). Provinces that
    are already open are not events — they have nothing left to announce.
    """
    if bg is None:
        return []
    me = bg.player.participant_id if bg.player else None
    named = labels.named_ids() if labels is not None else frozenset()
    ignore = set(bg.ignore_ids or ())
    out: list[UnlockEvent] = []
    for p in bg.provinces:
        opens = p.locked_until
        if not opens or opens <= now:
            continue
        if horizon_seconds is not None and opens > now + horizon_seconds:
            continue
        if not in_scope(bg, p, scope=scope, named_ids=named):
            continue
        side = DEFENSE if (me is not None and p.owner_id == me) else ATTACK
        if side == ATTACK and p.id in ignore:
            continue                                  # commander said "Stop" — don't call it
        owner = bg.participants.get(p.owner_id) if p.owner_id is not None else None
        out.append(UnlockEvent(
            province_id=p.id,
            opens_at=int(opens),
            side=side,
            label=labels.label(p.id) if labels is not None else f"#{p.id}",
            owner_colour=getattr(owner, "colour", None),
            owner_clan=getattr(owner, "clan_name", None),
        ))
    out.sort(key=lambda e: (e.opens_at, e.province_id))
    return out


def due_events(events, *, now: float, lead_seconds: int, stale_seconds: int = 300,
               already_sent=frozenset()) -> list[UnlockEvent]:
    """The events to announce right now: close enough to the opening (``lead_seconds``
    ahead), not so long past it that the news is stale, and not announced before.

    ``stale_seconds`` matters after a restart or a gap in snapshots — we would rather stay
    quiet than tell the group about an opening that happened ten minutes ago.
    """
    return [e for e in events
            if (now >= e.opens_at - lead_seconds)
            and (e.opens_at > now - stale_seconds)
            and e.key not in already_sent]


__all__ = ["ATTACK", "DEFENSE", "SCOPES", "UnlockEvent", "unlock_events", "due_events",
           "in_scope"]
