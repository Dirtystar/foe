"""“Leave for commander”: leave-margin math from native conquest progress."""

from __future__ import annotations

from bap.forge.gbg_data import closing
from bap.forge.gbg_data.model import Battleground, ConquestProgress, PlayerState, Province


def _bg(me=100):
    return Battleground(map_id="m", provinces=(), participants={},
                        player=PlayerState(participant_id=me))


def _prov(pid, cps):
    return Province(id=pid, conquest_progress=tuple(
        ConquestProgress(participant_id=p, progress=pr, max_progress=mx) for p, pr, mx in cps))


def test_our_progress_picks_our_guild():
    bg = _bg(me=100)
    p = _prov(1, [(200, 10, 132), (100, 38, 132)])   # rival + ours
    assert closing.our_progress(bg, p) == (38, 132)


def test_room_and_leave_and_cap():
    bg = _bg(me=100)
    # progress 128/132, margin 3 → stop line at 129 → room = 1
    p = _prov(1, [(100, 128, 132)])
    assert closing.room_before_close(bg, p, 3) == 1
    assert closing.fight_cap(bg, p, 3) == 1
    assert closing.should_leave(bg, p, 3) is False
    # progress 130/132, margin 3 → stop line 129 → room = -1 → leave it
    p2 = _prov(2, [(100, 130, 132)])
    assert closing.room_before_close(bg, p2, 3) == -1
    assert closing.should_leave(bg, p2, 3) is True
    assert closing.fight_cap(bg, p2, 3) == 0


def test_not_our_siege_returns_none():
    bg = _bg(me=100)
    p = _prov(1, [(200, 50, 132)])                    # only a rival guild is taking it
    assert closing.our_progress(bg, p) is None
    assert closing.room_before_close(bg, p, 3) is None
    assert closing.should_leave(bg, p, 3) is False    # feature doesn't apply → don't skip
    assert closing.fight_cap(bg, p, 3) is None


def test_no_progress_at_all():
    bg = _bg(me=100)
    p = _prov(1, [])
    assert closing.should_leave(bg, p, 3) is False
    assert closing.fight_cap(bg, p, 3) is None


def test_unknown_participant_is_safe():
    bg = _bg(me=None)                                 # can't tell which guild is ours
    p = _prov(1, [(100, 130, 132)])
    assert closing.our_progress(bg, p) is None
    assert closing.should_leave(bg, p, 3) is False
