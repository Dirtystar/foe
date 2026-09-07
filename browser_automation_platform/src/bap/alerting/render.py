"""The message text. Deliberately tiny — the group wants one glanceable line per province.

    16:25 🔵 A1X

``<Prague time it opens> <🔴 attack | 🔵 defence> <the guild's coordinate>``. When several
provinces open in the same tick they share one message, one line each, so the group gets a
single notification instead of a burst.
"""

from __future__ import annotations

from bap.alerting.clock import prague_hhmm
from bap.alerting.schedule import DEFENSE

ATTACK_EMOJI = "🔴"
DEFENSE_EMOJI = "🔵"


def side_emoji(side: str) -> str:
    return DEFENSE_EMOJI if side == DEFENSE else ATTACK_EMOJI


def format_line(event) -> str:
    return f"{prague_hhmm(event.opens_at)} {side_emoji(event.side)} {event.label}"


def format_message(events, *, header: str = "") -> str:
    """One line per event, in time order. ``header`` is optional and empty by default —
    the guild asked for a message with nothing but the facts."""
    lines = [format_line(e) for e in events]
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
        out.append(f"  {format_line(e):<16} province {e.province_id:<3} "
                   f"{'defence' if e.side == DEFENSE else 'attack ':<8} owner {owner}")
    if limit and len(events) > limit:
        out.append(f"  … and {len(events) - limit} more")
    return "\n".join(out)


__all__ = ["ATTACK_EMOJI", "DEFENSE_EMOJI", "side_emoji", "format_line", "format_message",
           "format_schedule"]
