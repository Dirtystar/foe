"""Static WhatsApp reminders — unrelated to GBG, same chat, same notifier.

A handful of fixed-text messages on a fixed cadence (weekly, every two weeks, ...), sent
through whichever notifier the alerter is already configured with (Green API, same
``chat_id`` as the GBG alerts). No game data is involved, so this runs independently of
``run``/``serve``/the browser — see ``bap-alert remind``. It is also the half meant to run
somewhere other than a guild officer's own PC: nothing here needs a browser or a live game
session, just Python and the notifier's credentials, so a scheduler with no PC behind it
(cron, a scheduled CI job, ...) can call it on a timer.

Cadence is one ``anchor_date`` (the first occurrence, Prague-local) plus ``every_days`` — a
weekly message is ``every_days: 7`` from any date that already falls on the right weekday; a
fortnightly one is ``every_days: 14`` from its first real occurrence. One model covers both
instead of a separate "weekday" special case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from bap.alerting.clock import prague_time


@dataclass(frozen=True)
class Reminder:
    id: str
    anchor_date: str   # "YYYY-MM-DD", Prague-local — the first occurrence
    every_days: int    # 7 = weekly, 14 = every two weeks, ...
    time: str          # "HH:MM", Prague-local
    text: str


def load_reminders(path: str) -> list[Reminder]:
    """Read ``{"reminders": [{"id", "anchor_date", "every_days", "time", "text"}, ...]}``.

    A missing file means no reminders configured yet — not an error, since this is meant to
    be hand-edited by a non-developer. A malformed anchor date or interval raises, so a typo
    is caught at startup rather than silently never firing.
    """
    p = Path(path)
    if not p.is_file():
        return []
    obj = json.loads(p.read_text(encoding="utf-8"))
    out = []
    for i, r in enumerate(obj.get("reminders") or []):
        anchor = str(r.get("anchor_date", ""))
        try:
            date.fromisoformat(anchor)
        except ValueError:
            raise ValueError(f"reminder {i}: anchor_date must be YYYY-MM-DD, got {anchor!r}")
        every_days = r.get("every_days")
        if not isinstance(every_days, int) or every_days < 1:
            raise ValueError(f"reminder {i}: every_days must be a positive integer, "
                             f"got {every_days!r}")
        out.append(Reminder(id=str(r.get("id") or f"reminder{i}"), anchor_date=anchor,
                            every_days=every_days, time=str(r.get("time", "")),
                            text=str(r.get("text", ""))))
    return out


class ReminderState:
    """Tracks the Prague-local date each reminder id last sent on, so a restart — or a poll
    loop checking the same slot twice — never double-sends."""

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
           window_minutes: int = 300) -> list[Reminder]:
    """Reminders due at ``now`` (Prague-local) and not yet sent today.

    ``window_minutes`` tolerates the caller not polling on the exact minute. Widening it is
    safe: the per-day dedup in ``state`` (not the window) is what stops a second poll inside
    the same window from double-sending, so long as ``state`` is persisted between calls — the
    only cost of a wide window is a reminder arriving late on a day its poller was, rather than
    being silently skipped for the rest of that cycle. The default is generous (5 h) because an
    external scheduler's actual polling cadence can run far looser than configured — observed
    live, a GitHub Actions `schedule` trigger meant to fire every 30 min instead landed multiple
    hours apart, which with the old ~35-min window missed a reminder outright. It can still miss
    one that's due late in the day if the next poll lands after local midnight, since "due today"
    resets then; shrink the window instead if sending late is worse than not sending.
    """
    local = prague_time(now)
    today = local_date(now)
    today_date = local.date()
    minutes_now = local.hour * 60 + local.minute
    due = []
    for r in reminders:
        if state.already_sent_today(r.id, today):
            continue
        try:
            anchor = date.fromisoformat(r.anchor_date)
            hh, mm = r.time.split(":")
            target = int(hh) * 60 + int(mm)
        except ValueError:
            continue
        days_since = (today_date - anchor).days
        if days_since < 0 or days_since % r.every_days != 0:
            continue
        if 0 <= minutes_now - target <= window_minutes:
            due.append(r)
    return due


__all__ = ["Reminder", "load_reminders", "ReminderState", "local_date", "due_now"]
