"""Static weekly WhatsApp reminders — unrelated to GBG, same chat, same notifier.

Three messages a week to start: a fixed weekday + time (Prague-local) and a fixed line of
text, sent through whichever notifier the alerter is already configured with (Green API, same
``chat_id`` as the GBG alerts). No game data is involved, so this runs independently of
``run``/``serve``/the browser — see ``bap-alert remind``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bap.alerting.clock import prague_time

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Reminder:
    id: str
    weekday: str      # one of WEEKDAYS, Prague-local
    time: str         # "HH:MM", Prague-local
    text: str


def load_reminders(path: str) -> list[Reminder]:
    """Read ``{"reminders": [{"id", "weekday", "time", "text"}, ...]}`` from ``path``.

    A missing file means no reminders configured yet — not an error, since this is meant to
    be hand-edited by a non-developer. A malformed weekday raises, so a typo is caught at
    startup rather than silently never firing.
    """
    p = Path(path)
    if not p.is_file():
        return []
    obj = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for i, r in enumerate(obj.get("reminders") or []):
        weekday = str(r.get("weekday", "")).strip().lower()[:3]
        if weekday not in WEEKDAYS:
            raise ValueError(f"reminder {i}: weekday must be one of {WEEKDAYS}, "
                             f"got {r.get('weekday')!r}")
        out.append(Reminder(id=str(r.get("id") or f"reminder{i}"), weekday=weekday,
                            time=str(r.get("time", "")), text=str(r.get("text", ""))))
    return out


class ReminderState:
    """Tracks the Prague-local date each reminder id last sent on, so a restart — or a poll
    loop landing on the same slot twice — never double-sends."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._sent: dict[str, str] = {}
        if self._path.is_file():
            try:
                self._sent = json.loads(self._path.read_text(encoding="utf-8")).get("sent", {})
            except (json.JSONDecodeError, OSError):
                self._sent = {}

    def already_sent_today(self, reminder_id: str, today: str) -> bool:
        return self._sent.get(reminder_id) == today

    def mark_sent(self, reminder_id: str, today: str) -> None:
        self._sent[reminder_id] = today
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps({"sent": self._sent}, indent=1), encoding="utf-8")
        tmp.replace(self._path)


def local_date(now: float) -> str:
    return prague_time(now).strftime("%Y-%m-%d")


def due_now(reminders: list[Reminder], state: ReminderState, *, now: float,
           window_minutes: int = 2) -> list[Reminder]:
    """Reminders whose weekday+time matches ``now`` (Prague-local) and were not yet sent today.

    ``window_minutes`` tolerates the poll loop not landing on the exact minute — a 30-60s poll
    with a 2-minute window never misses a slot, and the per-day state stops a double-send even
    if the loop lingers in the window on the next tick.
    """
    local = prague_time(now)
    today = local_date(now)
    weekday = WEEKDAYS[local.weekday()]
    minutes_now = local.hour * 60 + local.minute
    due = []
    for r in reminders:
        if r.weekday != weekday or state.already_sent_today(r.id, today):
            continue
        try:
            hh, mm = r.time.split(":")
            target = int(hh) * 60 + int(mm)
        except ValueError:
            continue
        if 0 <= minutes_now - target <= window_minutes:
            due.append(r)
    return due


__all__ = ["WEEKDAYS", "Reminder", "load_reminders", "ReminderState", "local_date", "due_now"]
