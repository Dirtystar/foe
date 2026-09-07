"""The alerting brain: snapshots in, WhatsApp messages out — with no browser anywhere.

Keeping this browser-free is the point: everything that decides *what* gets said and *when*
is exercised by unit tests, and :mod:`bap.alerting.watcher` only has to shovel game responses
into :meth:`AlertEngine.on_snapshot` and call :meth:`AlertEngine.tick` on a timer.

Why a timer at all, when one snapshot already lists hours of openings? Because we announce a
few minutes *before* each opening, not when we learn about it — the group wants "16:25 🔵 A1X"
to land while it is still actionable.
"""

from __future__ import annotations

import logging
import time

from bap.alerting import clock
from bap.alerting.labels import LabelBook
from bap.alerting.render import format_line, format_message
from bap.alerting.schedule import due_events, unlock_events

logger = logging.getLogger("bap.alerting")


class AlertEngine:
    """Holds the latest battleground snapshot and posts due openings exactly once."""

    def __init__(self, cfg, notifier, sent_log, labels: LabelBook | None = None) -> None:
        self.cfg = cfg
        self.notifier = notifier
        self.sent = sent_log
        self.labels = labels or LabelBook(overrides={}, auto={})
        self._bg = None
        self._snapshot_at: float | None = None
        self.messages_sent = 0

    # ------------------------------------------------------------------ input

    def on_snapshot(self, bg, *, now: float | None = None) -> None:
        """Accept a fresh :class:`~bap.forge.gbg_data.model.Battleground`."""
        if bg is None:
            return
        self._bg = bg
        self._snapshot_at = time.time() if now is None else now

    def on_layout(self, layout) -> None:
        """Adopt the static map asset once it goes past — it gives the auto grid labels."""
        if layout is not None:
            self.labels = self.labels.with_layout(layout)

    @property
    def snapshot(self):
        return self._bg

    def snapshot_age(self, now: float | None = None) -> float | None:
        if self._snapshot_at is None:
            return None
        return (time.time() if now is None else now) - self._snapshot_at

    # ------------------------------------------------------------- scheduling

    def upcoming(self, now: float | None = None):
        """Every in-scope opening still ahead of us, soonest first."""
        if self._bg is None:
            return []
        now = time.time() if now is None else now
        return unlock_events(self._bg, labels=self.labels, scope=self.cfg.scope,
                             now=clock.game_now(self._bg, now),
                             horizon_seconds=self.cfg.horizon_seconds)

    # ---------------------------------------------------------------- output

    def tick(self, now: float | None = None):
        """Send anything that just became due. Returns the events announced (possibly none).

        Quiet hours suppress the *message*, not the bookkeeping: the openings are marked as
        handled so the group doesn't get a pile of stale lines the moment the window ends.
        """
        if self._bg is None:
            return []
        now = time.time() if now is None else now
        game_now = clock.game_now(self._bg, now)
        due = due_events(self.upcoming(now), now=game_now,
                         lead_seconds=self.cfg.lead_seconds,
                         stale_seconds=self.cfg.stale_seconds,
                         already_sent=self.sent.keys)
        if not due:
            return []
        if self.cfg.in_quiet_hours(clock.prague_hour(int(game_now))):
            logger.info("quiet hours — suppressing %d opening(s)", len(due))
            self.sent.record([e.key for e in due], now=now)
            return []
        text = format_message(due, header=self.cfg.header)
        if not self.notifier.send(text):
            logger.warning("send failed — will retry the same openings next tick")
            return []                       # not recorded → retried while still fresh
        self.sent.record([e.key for e in due], now=now)
        self.messages_sent += 1
        return due

    # ----------------------------------------------------------------- status

    def status_line(self, now: float | None = None) -> str:
        if self._bg is None:
            return "waiting for GBG data — open Guild Battlegrounds on the watched world"
        age = self.snapshot_age(now)
        nxt = self.upcoming(now)
        head = (f"snapshot {int(age)}s old" if age is not None else "snapshot ready")
        if not nxt:
            return f"{head}; no openings in scope"
        return f"{head}; {len(nxt)} upcoming, next {format_line(nxt[0])}"


__all__ = ["AlertEngine"]
