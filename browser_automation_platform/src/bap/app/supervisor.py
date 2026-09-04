"""Supervisor: drives recovery from the existing report stream.

Sits in the report path (the composition root inserts it as the Scheduler's
on_report). For each TickReport it: (1) forwards the report unchanged to the
downstream sink, so the existing stream and the GUI keep working; (2) asks
the HealthMonitor to classify it; (3) triggers recovery or disabling through
SessionManager when the policy says so. No second event system is created —
recovery is observed on, and reflected back through, the same report stream,
and health changes ride the same plain-callback pattern the GUI already uses
for state/error.

Recovery runs as a separate asyncio task, never inline in on_report, so it
cannot deadlock the Scheduler job whose tick produced the report.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from bap.core.engine.health import (
    HealthMonitor,
    RecoveryDecision,
    ResourceAction,
    ResourcePressurePolicy,
    ResourcePressureState,
    SessionHealth,
)
from bap.core.engine.tab_session import TickReport
from bap.core.ports.browser_metrics_port import BrowserResourceSnapshot

ReportSink = Callable[[TickReport], Any]
HealthCallback = Callable[[str, SessionHealth, str], None]
TaskRunner = Callable[[Coroutine], Any]

# Health "profile" used for browser-level resource pressure so it rides the
# existing per-session health channel (persisted + shown) without a new bus.
BROWSER_HEALTH_ID = "__browser__"

_STATE_TO_HEALTH = {
    ResourcePressureState.NORMAL: SessionHealth.HEALTHY,
    ResourcePressureState.DEGRADED: SessionHealth.DEGRADED,
    ResourcePressureState.CRITICAL: SessionHealth.FAILED,
}


class Supervisor:
    def __init__(
        self,
        *,
        monitor: HealthMonitor,
        session_manager=None,
        sink: ReportSink | None = None,
        on_health: HealthCallback | None = None,
        task_runner: TaskRunner | None = None,
        resource_policy: ResourcePressurePolicy | None = None,
    ) -> None:
        self._monitor = monitor
        # Late-bindable: the manager is created by the composition root in the
        # same call that wires this Supervisor as on_report.
        self.session_manager = session_manager
        self._sink = sink
        self._on_health = on_health
        self._task_runner = task_runner or asyncio.ensure_future
        self._recovering: set[str] = set()
        self._last_health: dict[str, SessionHealth] = {}
        self._resource_policy = resource_policy or ResourcePressurePolicy()

    def on_report(self, report: TickReport) -> None:
        if self._sink is not None:
            self._sink(report)  # keep the existing stream intact

        decision = self._monitor.observe(report)
        self._emit_health(decision)

        if decision.should_recover:
            self._trigger_recovery(decision)
        elif decision.should_disable:
            self._trigger_disable(decision)

    # --- triggers -----------------------------------------------------------

    def _trigger_recovery(self, decision: RecoveryDecision) -> None:
        profile_id = decision.profile_id
        if profile_id in self._recovering or self.session_manager is None:
            return  # one recovery in flight per session; no duplicates
        self._recovering.add(profile_id)
        self._task_runner(self._recover(profile_id))

    async def _recover(self, profile_id: str) -> None:
        try:
            await self.session_manager.recover_session(profile_id)
            # health stays RECOVERING until the next healthy tick confirms it
        except Exception as exc:
            self._monitor.mark_failed(profile_id)
            self._notify(profile_id, SessionHealth.FAILED, f"recovery failed: {exc}")
        finally:
            self._recovering.discard(profile_id)

    def _trigger_disable(self, decision: RecoveryDecision) -> None:
        if self.session_manager is None:
            return
        self._task_runner(self._disable(decision.profile_id))

    async def _disable(self, profile_id: str) -> None:
        try:
            await self.session_manager.close_session(profile_id)
        except Exception:
            pass  # already gone; disabling is best-effort

    # --- resource pressure (browser-level health policy) --------------------

    def note_resource_pressure(
        self, snapshot: BrowserResourceSnapshot, breaches: tuple[str, ...]
    ) -> None:
        """Wired to ResourceMonitor.on_pressure. Escalates via the resource
        policy: brief pressure only degrades (a browser-level health signal);
        sustained pressure recovers all sessions to reclaim, and persistent
        pressure disables them. Observational first — recover/disable fire
        only at their thresholds. Never kills the browser directly."""
        decision = self._resource_policy.observe(tuple(breaches))
        if decision.changed:
            self._notify(
                BROWSER_HEALTH_ID, _STATE_TO_HEALTH[decision.state], decision.reason
            )
        if decision.action is ResourceAction.RECOVER:
            self._task_runner(self._recover_all(decision.reason))
        elif decision.action is ResourceAction.DISABLE:
            self._task_runner(self._disable_all(decision.reason))

    async def _recover_all(self, reason: str) -> None:
        if self.session_manager is None:
            return
        for profile_id in tuple(self.session_manager.profile_ids):
            try:
                await self.session_manager.recover_session(profile_id)
            except Exception as exc:
                self._monitor.mark_failed(profile_id)
                self._notify(profile_id, SessionHealth.FAILED, f"resource recovery failed: {exc}")

    async def _disable_all(self, reason: str) -> None:
        if self.session_manager is None:
            return
        for profile_id in tuple(self.session_manager.profile_ids):
            try:
                await self.session_manager.close_session(profile_id)
            except Exception:
                pass

    # --- health notification ------------------------------------------------

    def _emit_health(self, decision: RecoveryDecision) -> None:
        if self._last_health.get(decision.profile_id) == decision.health:
            return  # only report changes, not every healthy tick
        self._last_health[decision.profile_id] = decision.health
        self._notify(decision.profile_id, decision.health, decision.reason)

    def _notify(self, profile_id: str, health: SessionHealth, reason: str) -> None:
        self._last_health[profile_id] = health
        if self._on_health is not None:
            self._on_health(profile_id, health, reason)


__all__ = ["Supervisor"]
