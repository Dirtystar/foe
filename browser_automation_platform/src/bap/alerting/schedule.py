"""Snapshot → "which provinces open, when, and on which side of the fight".

A GBG province is **locked** for a cooldown after it changes hands; ``province.lockedUntil``
is the unix second at which it opens again and fighting there can resume. One
``getBattleground`` snapshot therefore already describes every opening for the next few hours
— the alert does not need a live feed, only a reasonably fresh snapshot.

Side of the fight — there are two candidate rules and the config picks one:

``battle_type`` *(default)*
    ``province.is_attack_battle_type`` — a per-province flag, independent of who owns it
    (38 attack / 22 defence in the captured map, both mixing owners). This is the rule that
    matches the group's own messages: their blue lines carry a ``[20%]`` badge, and
    ``gain_attrition_chance`` is absent on **every** province we own (22 of 22 in the
    capture), so a blue line simply cannot mean "our province".
``owner``
    ``province.owner_id == currentParticipantId`` — ours → the enemy sieges it when it opens
    (defence), theirs → we can (attack). Kept because the flag's meaning is not yet confirmed
    against a live map; see ``docs/FOE_ALERTING.md`` §8.

Either way the commander's *ignore* ("Stop") mark suppresses a province we do **not** own —
we are told not to fight there — and never one of ours, whichever colour it is shown in.

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
SIDE_RULES = ("battle_type", "owner")


@dataclass(frozen=True)
class UnlockEvent:
    """One province opening at one time."""

    province_id: int
    opens_at: int                       # unix seconds, game-server clock
    side: str                           # ATTACK | DEFENSE
    label: str                          # "A1X" — what the guild calls this province
    attrition_pct: int | None = None    # the map's "%" badge (gain_attrition_chance)
    owner_colour: str | None = None
    owner_clan: str | None = None
    mine: bool = False                  # do we own it? (independent of ``side``)

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


def side_of(province, *, mine: bool, rule: str = "battle_type") -> str:
    """Which colour this province is announced in — see the module docstring for the two
    rules. An unknown rule falls back to ``battle_type``; a province with no
    ``is_attack_battle_type`` reported is treated as defence (the game omits the flag rather
    than sending ``false``)."""
    if rule == "owner":
        return DEFENSE if mine else ATTACK
    return ATTACK if province.is_attack_battle_type else DEFENSE


def unlock_events(bg, *, labels=None, scope: str = "relevant", now: float,
                  horizon_seconds: int | None = None,
                  side_rule: str = "battle_type") -> list[UnlockEvent]:
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
        mine = me is not None and p.owner_id == me
        if not mine and p.id in ignore:
            continue                    # commander said "Stop" — we are not to fight there
        owner = bg.participants.get(p.owner_id) if p.owner_id is not None else None
        out.append(UnlockEvent(
            province_id=p.id,
            opens_at=int(opens),
            side=side_of(p, mine=mine, rule=side_rule),
            label=labels.label(p.id) if labels is not None else f"#{p.id}",
            attrition_pct=p.gain_attrition_chance,
            owner_colour=getattr(owner, "colour", None),
            owner_clan=getattr(owner, "clan_name", None),
            mine=mine,
        ))
    out.sort(key=lambda e: (e.opens_at, e.province_id))
    return out


@dataclass(frozen=True)
class Batch:
    """One message's worth of openings, plus the window it covers.

    ``window_end`` is carried back into the next call so a province that only appears in a
    later snapshot but opens inside the window we already announced triggers a re-send
    instead of being silently dropped.
    """

    events: tuple[UnlockEvent, ...]
    window_end: float | None
    resend: bool = False                # True → this repeats a window already announced

    def __bool__(self) -> bool:
        return bool(self.events)


def plan_batch(events, *, now: float, trigger_lead_seconds: int, window_seconds: int,
               stale_seconds: int = 300, already_sent=frozenset(),
               window_end: float | None = None) -> Batch:
    """Decide whether to speak now, and with which lines.

    The group does not want one message per province — 60 provinces unlocking over a few
    hours is a notification every four minutes. Instead we stay silent until the **soonest
    unannounced** opening is ``trigger_lead_seconds`` away, and then send everything opening
    within ``window_seconds`` in one message. That is what the guild does by hand, and it
    collapses the traffic by roughly an order of magnitude.

    Two things can make us speak:

    1. the soonest unannounced opening reaches its lead → open a new window;
    2. a *new* opening lands inside the window we last announced → repeat that window, so the
       group's latest message is always the complete picture.

    ``stale_seconds`` keeps a restart from announcing an opening that already happened.
    """
    fresh = [e for e in events if e.opens_at > now - stale_seconds]
    unsent = [e for e in fresh if e.key not in already_sent]

    if window_end is not None and now <= window_end:
        newcomers = [e for e in unsent if e.opens_at <= window_end]
        if newcomers:
            return Batch(tuple(e for e in fresh if e.opens_at <= window_end),
                         window_end, resend=True)
        return Batch((), window_end)

    if not unsent:
        return Batch((), None)
    if now < unsent[0].opens_at - trigger_lead_seconds:
        return Batch((), None)          # nothing close enough yet — stay quiet
    end = now + window_seconds
    return Batch(tuple(e for e in fresh if e.opens_at <= end), end)


__all__ = ["ATTACK", "DEFENSE", "SCOPES", "SIDE_RULES", "Batch", "UnlockEvent",
           "unlock_events", "plan_batch", "in_scope", "side_of"]
