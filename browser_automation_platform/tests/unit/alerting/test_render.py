"""The message is the product: `16:25 🔵 A1X`, nothing more."""

from __future__ import annotations

from conftest import ME, battleground, province

from bap.alerting.labels import LabelBook
from bap.alerting.render import format_line, format_message, format_schedule
from bap.alerting.schedule import unlock_events


def _events(now, labels=None, **kw):
    bg = battleground([province(1, owner=ME, opens_in=1500, **kw),
                       province(2, opens_in=3000, siege_by=ME)])
    return unlock_events(bg, labels=labels, now=now)


def test_line_is_time_emoji_label(now):
    labels = LabelBook(overrides={1: "A1X"}, auto={})
    defence, attack = _events(now, labels)
    assert format_line(defence) == "16:25 🔵 A1X"       # NOW is 16:00 Prague + 25 min
    assert format_line(attack) == "16:50 🔴 #2"


def test_message_is_one_line_per_opening(now):
    assert format_message(_events(now)) == "16:25 🔵 #1\n16:50 🔴 #2"


def test_header_is_opt_in(now):
    assert format_message(_events(now)[:1], header="GBG:") == "GBG:\n16:25 🔵 #1"
    assert "\n" not in format_message(_events(now)[:1])


def test_empty_message_is_empty(now):
    assert format_message([]) == ""


def test_schedule_view_is_for_humans_not_whatsapp(now):
    text = format_schedule(_events(now))
    assert "province 1" in text and "defence" in text and "Souperi" in text
    assert "(no upcoming openings in scope)" in format_schedule([])
    assert "and 1 more" in format_schedule(_events(now), limit=1)
