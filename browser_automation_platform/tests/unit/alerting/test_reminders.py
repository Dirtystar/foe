"""Static reminders: load, dedup, and the anchor+interval time-window match — no game involved."""

from __future__ import annotations

import json

from bap.alerting.reminders import ReminderState, Reminder, due_now, load_reminders

# 2026-02-10 09:00 Prague time (CET, winter) as a fixed reference point.
_REF_DATE = "2026-02-10"
_REF_0900 = 1770710400


def test_missing_file_means_no_reminders(tmp_path):
    assert load_reminders(str(tmp_path / "nope.json")) == []


def test_loads_reminders(tmp_path):
    p = tmp_path / "reminders.json"
    p.write_text(json.dumps({"reminders": [
        {"id": "a", "anchor_date": "2026-02-10", "every_days": 7, "time": "09:00", "text": "hi"},
    ]}), encoding="utf-8")
    out = load_reminders(str(p))
    assert out == [Reminder(id="a", anchor_date="2026-02-10", every_days=7, time="09:00",
                            text="hi")]


def test_bad_anchor_date_raises(tmp_path):
    p = tmp_path / "reminders.json"
    p.write_text(json.dumps({"reminders": [{"id": "a", "anchor_date": "10.2.2026",
                                            "every_days": 7, "time": "09:00", "text": "hi"}]}),
                encoding="utf-8")
    try:
        load_reminders(str(p))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "anchor_date" in str(exc)


def test_bad_every_days_raises(tmp_path):
    p = tmp_path / "reminders.json"
    p.write_text(json.dumps({"reminders": [{"id": "a", "anchor_date": "2026-02-10",
                                            "every_days": 0, "time": "09:00", "text": "hi"}]}),
                encoding="utf-8")
    try:
        load_reminders(str(p))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "every_days" in str(exc)


def test_fires_on_the_anchor_day_once(tmp_path):
    reminders = [Reminder(id="a", anchor_date=_REF_DATE, every_days=7, time="09:00", text="hi")]
    state = ReminderState(str(tmp_path / "state.json"))
    assert [r.id for r in due_now(reminders, state, now=_REF_0900)] == ["a"]
    state.mark_sent("a", _REF_DATE)
    assert due_now(reminders, state, now=_REF_0900 + 30 * 60) == []   # already sent today


def test_fires_again_after_the_interval(tmp_path):
    reminders = [Reminder(id="a", anchor_date=_REF_DATE, every_days=14, time="09:00", text="hi")]
    state = ReminderState(str(tmp_path / "state.json"))
    two_weeks_later = _REF_0900 + 14 * 86400
    one_week_later = _REF_0900 + 7 * 86400
    assert due_now(reminders, state, now=one_week_later) == []        # off-cycle
    assert [r.id for r in due_now(reminders, state, now=two_weeks_later)] == ["a"]


def test_before_anchor_or_too_early_does_not_fire(tmp_path):
    reminders = [Reminder(id="a", anchor_date=_REF_DATE, every_days=7, time="09:00", text="hi")]
    state = ReminderState(str(tmp_path / "state.json"))
    assert due_now(reminders, state, now=_REF_0900 - 10 * 86400) == []   # before it ever starts
    assert due_now(reminders, state, now=_REF_0900 - 300) == []          # same day, 5 min early


def test_state_survives_a_restart(tmp_path):
    path = str(tmp_path / "state.json")
    ReminderState(path).mark_sent("a", _REF_DATE)
    assert ReminderState(path).already_sent_today("a", _REF_DATE)
