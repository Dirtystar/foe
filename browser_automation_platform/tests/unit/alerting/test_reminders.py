"""Weekly static reminders: load, dedup, and the time-window match — no game involved."""

from __future__ import annotations

import json

from bap.alerting.reminders import ReminderState, Reminder, due_now, load_reminders

# A Monday 09:00 Prague time (CET, winter) as a fixed reference point.
_MONDAY_0900 = 1739174400


def test_missing_file_means_no_reminders(tmp_path):
    assert load_reminders(str(tmp_path / "nope.json")) == []


def test_loads_and_normalises_weekday(tmp_path):
    p = tmp_path / "reminders.json"
    p.write_text(json.dumps({"reminders": [
        {"id": "a", "weekday": "Monday", "time": "09:00", "text": "hi"},
    ]}), encoding="utf-8")
    out = load_reminders(str(p))
    assert out == [Reminder(id="a", weekday="mon", time="09:00", text="hi")]


def test_bad_weekday_raises(tmp_path):
    p = tmp_path / "reminders.json"
    p.write_text(json.dumps({"reminders": [{"id": "a", "weekday": "whoops", "time": "09:00",
                                            "text": "hi"}]}), encoding="utf-8")
    try:
        load_reminders(str(p))
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "weekday" in str(exc)


def test_fires_inside_the_window_once(tmp_path):
    reminders = [Reminder(id="a", weekday="mon", time="09:00", text="hi")]
    state = ReminderState(str(tmp_path / "state.json"))
    assert [r.id for r in due_now(reminders, state, now=_MONDAY_0900)] == ["a"]
    state.mark_sent("a", "2025-02-10")
    assert due_now(reminders, state, now=_MONDAY_0900 + 30) == []   # already sent today


def test_wrong_weekday_or_too_early_does_not_fire(tmp_path):
    reminders = [Reminder(id="a", weekday="tue", time="09:00", text="hi")]
    state = ReminderState(str(tmp_path / "state.json"))
    assert due_now(reminders, state, now=_MONDAY_0900) == []

    reminders = [Reminder(id="a", weekday="mon", time="09:00", text="hi")]
    assert due_now(reminders, state, now=_MONDAY_0900 - 300) == []   # 5 min early


def test_state_survives_a_restart(tmp_path):
    path = str(tmp_path / "state.json")
    ReminderState(path).mark_sent("a", "2025-02-10")
    assert ReminderState(path).already_sent_today("a", "2025-02-10")
