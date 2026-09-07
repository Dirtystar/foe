"""The message text, copying the format the guild already types by hand:

    21:34 🔴 D4A [20%]

``<Prague time it opens> <🔴 attack | 🔵 defence> <the guild's coordinate> [<attrition %>]``.

The percentage is the map's own badge (``gain_attrition_chance``, always one of 20/40/60/100
in the captured map). The game omits the field on provinces we own, so the bracket is simply
left off when there is no number — never guessed, never zero-filled.

A message carries every opening in the batch window, one line each, so the group gets one
notification instead of a burst.
"""

from __future__ import annotations

from bap.alerting.clock import prague_hhmm
from bap.alerting.schedule import DEFENSE

ATTACK_EMOJI = "🔴"
DEFENSE_EMOJI = "🔵"


def side_emoji(side: str) -> str:
    return DEFENSE_EMOJI if side == DEFENSE else ATTACK_EMOJI


def format_line(event, *, show_attrition: bool = True) -> str:
    line = f"{prague_hhmm(event.opens_at)} {side_emoji(event.side)} {event.label}"
    pct = getattr(event, "attrition_pct", None)
    if show_attrition and pct is not None:
        line += f" [{int(pct)}%]"
    return line


def format_message(events, *, header: str = "", show_attrition: bool = True) -> str:
    """One line per event, in time order. ``header`` is optional and empty by default —
    the guild asked for a message with nothing but the facts."""
    lines = [format_line(e, show_attrition=show_attrition) for e in events]
    if header:
        lines.insert(0, header)
    return "\n".join(lines)


def format_schedule(events, *, limit: int | None = None) -> str:
    """A richer, human-readable listing for the console/preview (not for WhatsApp)."""
    if not events:
        return "  (no upcoming openings in scope)"
    rows = events[:limit] if limit else events
    out = []
    for e in rows:
        owner = e.owner_clan or e.owner_colour or "?"
        out.append(f"  {format_line(e):<22} province {e.province_id:<3} "
                   f"{'defence' if e.side == DEFENSE else 'attack ':<8} "
                   f"{'ours ' if e.mine else 'enemy'} owner {owner}")
    if limit and len(events) > limit:
        out.append(f"  … and {len(events) - limit} more")
    return "\n".join(out)


__all__ = ["ATTACK_EMOJI", "DEFENSE_EMOJI", "side_emoji", "format_line", "format_message",
           "format_schedule"]
