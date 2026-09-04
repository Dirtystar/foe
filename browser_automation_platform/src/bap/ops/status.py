"""Operational readiness/health status.

A small state object the lifecycle drives (starting -> ready -> stopping ->
stopped) and that also *derives* DEGRADED from the existing health flow: it is
wired as one more on_health observer (no new event bus), flipping ready<->
degraded as sessions/browser report health while running. Changes are pushed
through a single on_change callback, which the composition root fans out to
logs, the GUI, and (optionally) persistence — reusing the established
callback pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from bap.core.engine.health import SessionHealth


class OperationalStatus(Enum):
    STARTING = "starting"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"


_RUNNING = {OperationalStatus.READY, OperationalStatus.DEGRADED}


class OperationalState:
    def __init__(self, on_change: Callable[[OperationalStatus, str], None] | None = None) -> None:
        self._status = OperationalStatus.STOPPED
        self._on_change = on_change
        self._health: dict[str, SessionHealth] = {}

    @property
    def status(self) -> OperationalStatus:
        return self._status

    def transition(self, status: OperationalStatus, reason: str = "") -> None:
        if status is self._status:
            return
        self._status = status
        if status not in _RUNNING:
            # leaving the running phase: forget health so a later start is clean
            if status in (OperationalStatus.STOPPING, OperationalStatus.STOPPED):
                self._health.clear()
        if self._on_change is not None:
            self._on_change(status, reason)

    def observe_health(self, profile_id: str, health: SessionHealth, reason: str = "") -> None:
        """Wired into the on_health callback chain. Derives ready<->degraded
        while running; ignored during starting/stopping/stopped so lifecycle
        transitions are not overridden by late health events."""
        self._health[profile_id] = health
        if self._status not in _RUNNING:
            return
        degraded = any(h is not SessionHealth.HEALTHY for h in self._health.values())
        target = OperationalStatus.DEGRADED if degraded else OperationalStatus.READY
        if target is not self._status:
            detail = reason if degraded else "all sessions healthy"
            self.transition(target, detail)


__all__ = ["OperationalState", "OperationalStatus"]
