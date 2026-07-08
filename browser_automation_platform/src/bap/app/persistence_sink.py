"""PersistenceSink: connects the report stream to a StateStorePort.

A transparent middle layer in the report path: it forwards every report and
health change downstream first (so storage can never delay or break the GUI,
recovery, or scheduler), then converts runtime objects into persistence DTOs
and hands them to the store. Storage is observational only — the runtime does
not read it back. Any storage failure is caught and surfaced through on_error,
never raised into the runtime.

Conversion (runtime -> DTO) lives here, in the app layer: core defines the DTO
vocabulary, the adapter stores it, and this layer bridges the two.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from bap.core.engine.health import SessionHealth
from bap.core.engine.tab_session import TickReport
from bap.core.ports.state_store_port import (
    ActionRecord,
    HealthEventRecord,
    StateStorePort,
    TickRecord,
)

ReportSink = Callable[[TickReport], object]
HealthSink = Callable[[str, SessionHealth, str], object]
ErrorSink = Callable[[str], object]


def tick_to_record(report: TickReport) -> TickRecord:
    m = report.metrics
    rules_matched = rules_total = None
    if report.evaluation is not None:
        results = report.evaluation.results
        rules_total = len(results)
        rules_matched = sum(1 for r in results if r.status.value == "matched")
    actions: tuple[ActionRecord, ...] = ()
    if report.execution is not None:
        actions = tuple(
            ActionRecord(
                rule_id=r.request.rule_id,
                action_type=r.request.action_type,
                status=r.status.value,
                error=str(r.error) if r.error is not None else None,
            )
            for r in report.execution.results
        )
    return TickRecord(
        timestamp=report.finished_at,
        profile_id=report.profile_id,
        tick_number=report.tick_number,
        status=report.status.value,
        duration_ms=m.total_ms if m else None,
        capture_ms=m.capture_ms if m else None,
        vision_ms=m.vision_ms if m else None,
        rules_ms=m.rules_ms if m else None,
        actions_ms=m.actions_ms if m else None,
        rules_matched=rules_matched,
        rules_total=rules_total,
        error=str(report.error) if report.error is not None else None,
        actions=actions,
    )


class PersistenceSink:
    def __init__(
        self,
        store: StateStorePort,
        *,
        report_sink: ReportSink | None = None,
        health_sink: HealthSink | None = None,
        on_error: ErrorSink | None = None,
    ) -> None:
        self._store = store
        self._report_sink = report_sink
        self._health_sink = health_sink
        self._on_error = on_error
        self._last_health: dict[str, str] = {}

    def on_report(self, report: TickReport) -> None:
        if self._report_sink is not None:
            self._report_sink(report)  # downstream first — never blocked by storage
        try:
            self._store.record_tick(tick_to_record(report))
        except Exception as exc:
            self._fail(exc)

    def on_health(self, profile_id: str, health: SessionHealth, reason: str) -> None:
        previous = self._last_health.get(profile_id)
        new_state = health.value
        self._last_health[profile_id] = new_state
        if self._health_sink is not None:
            self._health_sink(profile_id, health, reason)
        try:
            self._store.record_health(
                HealthEventRecord(
                    timestamp=datetime.now(timezone.utc),
                    profile_id=profile_id,
                    previous_state=previous,
                    new_state=new_state,
                    reason=reason,
                )
            )
        except Exception as exc:
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        if self._on_error is not None:
            self._on_error(f"persistence error: {exc}")


__all__ = ["PersistenceSink", "tick_to_record"]
