"""Which openings are events, whose side they are on, and when they become due."""

from __future__ import annotations

from conftest import ENEMY, ME, battleground, province

from bap.alerting.labels import LabelBook
from bap.alerting.schedule import ATTACK, DEFENSE, due_events, unlock_events


def _events(bg, *, now, scope="relevant", labels=None, horizon=None):
    return unlock_events(bg, labels=labels, scope=scope, now=now, horizon_seconds=horizon)


def test_our_province_is_defence_theirs_is_attack(now):
    bg = battleground([province(1, owner=ME, opens_in=600),
                       province(2, owner=ENEMY, opens_in=900, siege_by=ME)])
    sides = {e.province_id: e.side for e in _events(bg, now=now)}
    assert sides == {1: DEFENSE, 2: ATTACK}


def test_already_open_provinces_are_not_events(now):
    bg = battleground([province(1, owner=ME, opens_in=-60), province(2, owner=ME)])
    assert _events(bg, now=now) == []


def test_events_are_sorted_by_time(now):
    bg = battleground([province(1, owner=ME, opens_in=900),
                       province(2, owner=ME, opens_in=300),
                       province(3, owner=ME, opens_in=600)])
    assert [e.province_id for e in _events(bg, now=now)] == [2, 3, 1]


def test_horizon_drops_far_future_openings(now):
    bg = battleground([province(1, owner=ME, opens_in=600),
                       province(2, owner=ME, opens_in=20 * 3600)])
    assert [e.province_id for e in _events(bg, now=now, horizon=12 * 3600)] == [1]


def test_scope_relevant_keeps_ours_focus_and_our_sieges(now):
    bg = battleground([province(1, owner=ME, opens_in=600),          # ours
                       province(2, owner=ENEMY, opens_in=600),       # nothing to do with us
                       province(3, owner=ENEMY, opens_in=600),       # commander marked focus
                       province(4, owner=ENEMY, opens_in=600, siege_by=ME)],
                      focus=(3,))
    assert {e.province_id for e in _events(bg, now=now)} == {1, 3, 4}


def test_scope_all_and_mine(now):
    bg = battleground([province(1, owner=ME, opens_in=600),
                       province(2, owner=ENEMY, opens_in=600)])
    assert {e.province_id for e in _events(bg, now=now, scope="all")} == {1, 2}
    assert {e.province_id for e in _events(bg, now=now, scope="mine")} == {1}


def test_scope_labeled_follows_the_guilds_own_list(now):
    labels = LabelBook(overrides={2: "A1X"}, auto={})
    bg = battleground([province(1, owner=ME, opens_in=600),
                       province(2, owner=ENEMY, opens_in=600)])
    events = _events(bg, now=now, scope="labeled", labels=labels)
    assert [(e.province_id, e.label) for e in events] == [(2, "A1X")]


def test_stop_marked_provinces_are_not_announced_as_attacks(now):
    bg = battleground([province(1, owner=ENEMY, opens_in=600, siege_by=ME),
                       province(2, owner=ENEMY, opens_in=600, siege_by=ME)], ignore=(2,))
    assert [e.province_id for e in _events(bg, now=now)] == [1]


def test_stop_mark_never_silences_a_defence(now):
    bg = battleground([province(1, owner=ME, opens_in=600)], ignore=(1,))
    assert [e.side for e in _events(bg, now=now)] == [DEFENSE]


def test_owner_is_carried_for_the_console_view(now):
    bg = battleground([province(1, owner=ENEMY, opens_in=600, siege_by=ME)])
    e = _events(bg, now=now)[0]
    assert (e.owner_clan, e.owner_colour) == ("Souperi", "green")


def test_key_identifies_one_opening(now):
    bg = battleground([province(1, owner=ME, opens_in=600)])
    e = _events(bg, now=now)[0]
    assert e.key == f"1:{now + 600}"


def test_no_snapshot_no_events(now):
    assert unlock_events(None, now=now) == []


# ------------------------------------------------------------------ due_events

def test_due_only_within_the_lead_window(now):
    bg = battleground([province(1, owner=ME, opens_in=300),
                       province(2, owner=ME, opens_in=3600)])
    events = _events(bg, now=now)
    due = due_events(events, now=now, lead_seconds=600)
    assert [e.province_id for e in due] == [1]           # 5 min away, lead is 10


def test_stale_openings_stay_quiet(now):
    bg = battleground([province(1, owner=ME, opens_in=-60)])
    # build the event as if it had been seen earlier, then evaluate it much later
    events = _events(bg, now=now - 600)
    assert due_events(events, now=now, lead_seconds=600, stale_seconds=30) == []
    assert due_events(events, now=now, lead_seconds=600, stale_seconds=300) != []


def test_already_sent_is_never_repeated(now):
    bg = battleground([province(1, owner=ME, opens_in=300)])
    events = _events(bg, now=now)
    assert due_events(events, now=now, lead_seconds=600,
                      already_sent={events[0].key}) == []
