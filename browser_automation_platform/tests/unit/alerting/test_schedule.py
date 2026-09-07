"""Which openings are events, whose side they are on, and when they become due."""

from __future__ import annotations

from conftest import ENEMY, ME, battleground, province

from bap.alerting.labels import LabelBook
from bap.alerting.schedule import ATTACK, DEFENSE, plan_batch, unlock_events


def _events(bg, *, now, scope="relevant", labels=None, horizon=None, side_rule="owner"):
    return unlock_events(bg, labels=labels, scope=scope, now=now, horizon_seconds=horizon,
                         side_rule=side_rule)


def test_owner_rule_our_province_is_defence_theirs_is_attack(now):
    bg = battleground([province(1, owner=ME, opens_in=600),
                       province(2, owner=ENEMY, opens_in=900, siege_by=ME)])
    sides = {e.province_id: e.side for e in _events(bg, now=now)}
    assert sides == {1: DEFENSE, 2: ATTACK}


def test_battle_type_rule_follows_the_flag_not_the_owner(now):
    """The guild's colours track ``isAttackBattleType``, which is independent of ownership —
    our own province can be an attack province and an enemy one a defence province."""
    bg = battleground([province(1, owner=ME, opens_in=600, attack_type=True),
                       province(2, owner=ENEMY, opens_in=900, siege_by=ME)],
                      focus=(2,))
    sides = {e.province_id: e.side for e in _events(bg, now=now, side_rule="battle_type")}
    assert sides == {1: ATTACK, 2: DEFENSE}


def test_ownership_is_reported_separately_from_the_colour(now):
    bg = battleground([province(1, owner=ME, opens_in=600, attack_type=True)])
    e = _events(bg, now=now, side_rule="battle_type")[0]
    assert (e.side, e.mine) == (ATTACK, True)


def test_attrition_badge_is_carried_through(now):
    bg = battleground([province(1, owner=ENEMY, opens_in=600, siege_by=ME, attrition=40),
                       province(2, owner=ME, opens_in=600)])
    pct = {e.province_id: e.attrition_pct for e in _events(bg, now=now)}
    assert pct == {1: 40, 2: None}          # the game omits it on provinces we own


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


def test_stop_marked_enemy_provinces_are_not_announced(now):
    bg = battleground([province(1, owner=ENEMY, opens_in=600, siege_by=ME),
                       province(2, owner=ENEMY, opens_in=600, siege_by=ME)], ignore=(2,))
    assert [e.province_id for e in _events(bg, now=now)] == [1]


def test_stop_mark_is_about_ownership_not_the_displayed_colour(now):
    """A Stop mark means "do not fight there", so it silences an enemy province whichever
    colour the battle-type flag gives it — and never one of ours."""
    bg = battleground([province(1, owner=ENEMY, opens_in=600, siege_by=ME, attack_type=None),
                       province(2, owner=ME, opens_in=600, attack_type=True)],
                      ignore=(1, 2))
    assert [e.province_id for e in _events(bg, now=now, side_rule="battle_type")] == [2]


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


# ------------------------------------------------------------------- plan_batch

LEAD = 4 * 60
WINDOW = 30 * 60


def _plan(events, *, now, sent=frozenset(), window_end=None, lead=LEAD, window=WINDOW):
    return plan_batch(events, now=now, trigger_lead_seconds=lead, window_seconds=window,
                      already_sent=sent, window_end=window_end)


def test_silence_until_the_soonest_opening_reaches_the_lead(now):
    bg = battleground([province(1, owner=ME, opens_in=600),      # 10 min away, lead is 4
                       province(2, owner=ME, opens_in=900)])
    assert not _plan(_events(bg, now=now), now=now)


def test_one_message_carries_the_whole_window(now):
    """The point of batching: the trigger is one province, but the message lists everything
    opening within the window, so the group gets one notification instead of five."""
    bg = battleground([province(1, owner=ME, opens_in=120),      # triggers (inside the lead)
                       province(2, owner=ME, opens_in=900),
                       province(3, owner=ME, opens_in=1500),
                       province(4, owner=ME, opens_in=4 * 3600)])   # beyond the window
    batch = _plan(_events(bg, now=now), now=now)
    assert [e.province_id for e in batch.events] == [1, 2, 3]
    assert batch.window_end == now + WINDOW
    assert not batch.resend


def test_a_new_opening_inside_an_announced_window_repeats_the_window(now):
    """A later snapshot can add a province that opens inside a window we already announced.
    The group's latest message must stay the complete picture, so we repeat the window."""
    bg = battleground([province(1, owner=ME, opens_in=120),
                       province(2, owner=ME, opens_in=900),
                       province(3, owner=ME, opens_in=1200)])     # the newcomer
    events = _events(bg, now=now)
    already = {e.key for e in events if e.province_id in (1, 2)}
    batch = _plan(events, now=now + 60, sent=already, window_end=now + WINDOW)
    assert batch.resend
    assert [e.province_id for e in batch.events] == [1, 2, 3]     # not just the newcomer


def test_an_open_window_with_nothing_new_stays_quiet(now):
    bg = battleground([province(1, owner=ME, opens_in=120),
                       province(2, owner=ME, opens_in=900)])
    events = _events(bg, now=now)
    batch = _plan(events, now=now + 60, sent={e.key for e in events},
                  window_end=now + WINDOW)
    assert not batch
    assert batch.window_end == now + WINDOW          # the window is still ours to watch


def test_a_new_opening_beyond_the_window_does_not_repeat_it(now):
    bg = battleground([province(1, owner=ME, opens_in=120),
                       province(2, owner=ME, opens_in=WINDOW + 600)])
    events = _events(bg, now=now)
    batch = _plan(events, now=now + 60, sent={events[0].key}, window_end=now + WINDOW)
    assert not batch


def test_the_window_expires_and_the_next_opening_starts_a_new_one(now):
    bg = battleground([province(1, owner=ME, opens_in=WINDOW + 120)])
    events = _events(bg, now=now)
    later = now + WINDOW + 1
    batch = _plan(events, now=later, window_end=now + WINDOW)
    assert [e.province_id for e in batch.events] == [1]
    assert batch.window_end == later + WINDOW


def test_stale_openings_stay_quiet(now):
    bg = battleground([province(1, owner=ME, opens_in=-60)])
    # build the event as if it had been seen earlier, then evaluate it much later
    events = _events(bg, now=now - 600)
    assert not plan_batch(events, now=now, trigger_lead_seconds=LEAD,
                          window_seconds=WINDOW, stale_seconds=30)
    assert plan_batch(events, now=now, trigger_lead_seconds=LEAD,
                      window_seconds=WINDOW, stale_seconds=300)


def test_already_sent_never_triggers_a_new_window(now):
    bg = battleground([province(1, owner=ME, opens_in=120),
                       province(2, owner=ME, opens_in=4 * 3600)])
    events = _events(bg, now=now)
    assert not _plan(events, now=now, sent={events[0].key})
