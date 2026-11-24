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

#: The guild's own layout. Editable in the UI, so keep the placeholder set small and obvious.
DEFAULT_TEMPLATE = "{time} {emoji} {label} {pct}"

#: What each placeholder means, in the order the UI lists them.
PLACEHOLDERS = (
    ("{time}", "opening time in Prague, HH:MM"),
    ("{emoji}", "🔴 attack / 🔵 defence"),
    ("{label}", "the guild's coordinate, e.g. D4A"),
    ("{pct}", "the attrition badge as [20%] — empty when the game reports none"),
    ("{pct_num}", "the same number bare, e.g. 20 — empty when there is none"),
    ("{side}", "the word: attack / defence"),
    ("{id}", "the province id the game uses"),
)


def side_emoji(side: str) -> str:
    return DEFENSE_EMOJI if side == DEFENSE else ATTACK_EMOJI


def line_fields(event, *, show_attrition: bool = True) -> dict:
    """The placeholder values for one opening. A province with no attrition badge yields
    empty strings, never ``0%`` — the game omits the field rather than reporting zero."""
    pct = getattr(event, "attrition_pct", None)
    if not show_attrition:
        pct = None
    return {
        "time": prague_hhmm(event.opens_at),
        "emoji": side_emoji(event.side),
        "label": event.label,
        "pct": "" if pct is None else f"[{int(pct)}%]",
        "pct_num": "" if pct is None else str(int(pct)),
        "side": "defence" if event.side == DEFENSE else "attack",
        "id": str(event.province_id),
    }


def format_line(event, *, show_attrition: bool = True, template: str = DEFAULT_TEMPLATE) -> str:
    """Render one opening. An unknown placeholder is left alone rather than raising, so a
    half-typed template in the UI still previews instead of blowing up."""
    fields = line_fields(event, show_attrition=show_attrition)
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", value)
    # An empty {pct} would otherwise leave a double space or a trailing one.
    return " ".join(out.split())


def format_message(events, *, header: str = "", show_attrition: bool = True,
                   template: str = DEFAULT_TEMPLATE) -> str:
    """One line per event, in time order. ``header`` is optional and empty by default —
    the guild asked for a message with nothing but the facts."""
    lines = [format_line(e, show_attrition=show_attrition, template=template)
             for e in events]
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


__all__ = ["ATTACK_EMOJI", "DEFENSE_EMOJI", "DEFAULT_TEMPLATE", "PLACEHOLDERS", "side_emoji",
           "line_fields", "format_line", "format_message", "format_schedule"]
