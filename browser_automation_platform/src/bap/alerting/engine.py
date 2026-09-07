"""The alerting brain: snapshots in, WhatsApp messages out — with no browser anywhere.

Keeping this browser-free is the point: everything that decides *what* gets said and *when*
is exercised by unit tests, and :mod:`bap.alerting.watcher` only has to shovel game responses
into :meth:`AlertEngine.on_snapshot` and call :meth:`AlertEngine.tick` on a timer.

Why a timer at all, when one snapshot already lists hours of openings? Because we announce a
few minutes *before* the opening, not when we learn about it. Three hours of notice and
people ignore the message; the guild's own rule of thumb is two to five minutes, which is
just enough time to gather.

Messages are **batched**: the engine stays silent until the soonest unannounced opening is
``trigger_lead`` away, then sends every opening inside ``window`` in one message. See
:func:`bap.alerting.schedule.plan_batch`.
"""

from __future__ import annotations

import logging
import time

from bap.alerting import clock
from bap.alerting.labels import LabelBook
from bap.alerting.render import format_line, format_message
from bap.alerting.schedule import plan_batch, unlock_events

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
        self._window_end: float | None = None   # game clock; end of the announced window
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
                             horizon_seconds=self.cfg.horizon_seconds,
                             side_rule=self.cfg.side_rule)

    # ---------------------------------------------------------------- output

    def tick(self, now: float | None = None):
        """Send the batch that just became due. Returns the events announced (possibly none).

        Quiet hours suppress the *message*, not the bookkeeping: the openings are marked as
        handled so the group doesn't get a pile of stale lines the moment the window ends.
        """
        if self._bg is None:
            return []
        now = time.time() if now is None else now
        game_now = clock.game_now(self._bg, now)
        batch = plan_batch(self.upcoming(now), now=game_now,
                           trigger_lead_seconds=self.cfg.trigger_lead_seconds,
                           window_seconds=self.cfg.window_seconds,
                           stale_seconds=self.cfg.stale_seconds,
                           already_sent=self.sent.keys,
                           window_end=self._window_end)
        self._window_end = batch.window_end
        if not batch:
            return []
        events = list(batch.events)
        if self.cfg.in_quiet_hours(clock.prague_hour(int(game_now))):
            logger.info("quiet hours — suppressing %d opening(s)", len(events))
            self.sent.record([e.key for e in events], now=now)
            return []
        text = format_message(events, header=self.cfg.header,
                              show_attrition=self.cfg.show_attrition,
                              template=self.cfg.message_template)
        if not self.notifier.send(text):
            logger.warning("send failed — will retry the same openings next tick")
            self._window_end = None         # not recorded → re-planned while still fresh
            return []
        self.sent.record([e.key for e in events], now=now)
        self.messages_sent += 1
        logger.info("sent %d opening(s)%s", len(events), " (re-send)" if batch.resend else "")
        return events

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
