"""Thin adapter: runtime reports/callbacks -> Qt signals.

The Scheduler already emits a TickReport per tick through its `on_report`
callback (the established report stream). This bridge turns that callback —
and the RuntimeService's state/error callbacks — into Qt signals. Because
the bridge object lives on the UI thread, emitting from the runtime thread
is delivered via Qt's queued connection, so every slot runs on the UI
thread. No second event system is introduced; this only re-expresses the
existing stream in Qt's vocabulary.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from bap.core.engine.health import SessionHealth
from bap.core.engine.tab_session import TickReport


class QtReportBridge(QObject):
    report_received = Signal(object)         # TickReport
    state_changed = Signal(str)              # "running" / "stopped"
    error_occurred = Signal(str)
    health_changed = Signal(str, str, str)   # profile_id, health, reason

    def on_report(self, report: TickReport) -> None:
        """Passed to create_application(on_report=...); called on the runtime
        thread. Emitting is thread-safe and hops to the UI thread."""
        self.report_received.emit(report)

    def on_state_change(self, state: str) -> None:
        self.state_changed.emit(state)

    def on_error(self, message: str) -> None:
        self.error_occurred.emit(message)

    def on_health_change(self, profile_id: str, health: SessionHealth, reason: str) -> None:
        """Wired to Supervisor.on_health; reuses the same callback->signal
        pattern as state/error — not a new event system."""
        self.health_changed.emit(profile_id, health.value, reason)


__all__ = ["QtReportBridge"]
