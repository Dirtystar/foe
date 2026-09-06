"""“Leave for commander” — stop N fights before a province closes, from native progress data.

A GBG province is captured when a guild's conquest **progress** reaches **maxProgress**
(``getBattleground`` → ``province.conquest_progress[] = {participant_id, progress, max_progress}``).
Commanders time the final blows themselves, so a considerate bot leaves a margin: it never
delivers the last few fights on a province our own guild is taking.

This is pure data (independent of how many times *we* clicked — many players hit the same
province), exactly what we want. These helpers read our guild's progress and say whether to
**leave** a province alone, and at most how many fights we may still do on it (``room``).

Note: ``getBattleground`` only refreshes on GBG entry, so ``progress`` here is the value at
entry. We therefore gate conservatively — skip provinces already within the margin, and cap a
province's fight loop to the room measured at entry. (Live per-fight refinement is a follow-up.)
"""

from __future__ import annotations


def our_progress(bg, province, me=None):
    """(progress, max_progress) for *our* guild's siege of ``province``, or None if we're not
    conquering it. ``me`` defaults to the current participant id from the snapshot."""
    me = (bg.player.participant_id if (me is None and bg and bg.player) else me)
    if me is None:
        return None
    for cp in getattr(province, "conquest_progress", ()) or ():
        if cp.participant_id == me:
            return cp.progress, cp.max_progress
    return None


def room_before_close(bg, province, margin, me=None):
    """Fights we may still do before hitting the leave-margin: ``(max - margin) - progress``.
    None when our guild isn't conquering this province (feature doesn't apply)."""
    op = our_progress(bg, province, me)
    if op is None:
        return None
    progress, mx = op
    if not mx:
        return None
    return (mx - margin) - progress


def should_leave(bg, province, margin, me=None) -> bool:
    """True → don't fight this province at all this round: it's already within ``margin`` of
    closing for our guild (leave the last blows to the commander)."""
    r = room_before_close(bg, province, margin, me)
    return r is not None and r <= 0


def fight_cap(bg, province, margin, me=None):
    """Max fights we may do on this province before the leave-margin (>=0), or None if the
    feature doesn't apply (we're not the ones conquering it)."""
    r = room_before_close(bg, province, margin, me)
    return None if r is None else max(0, r)


__all__ = ["our_progress", "room_before_close", "should_leave", "fight_cap"]
