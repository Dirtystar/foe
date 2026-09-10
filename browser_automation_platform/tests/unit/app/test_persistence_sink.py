from datetime import datetime, timezone

import pytest

from bap.app.persistence_sink import PersistenceSink, tick_to_record
from bap.core.actions.action_executor import ExecutionReport
from bap.core.domain.models import ActionRequest
from bap.core.engine.health import SessionHealth
from bap.core.engine.tab_session import TickMetrics, TickReport, TickStatus
from bap.core.ports.action_handler_port import ActionResult, ActionStatus
from bap.core.ports.state_store_port import HealthEventRecord, StateStorePort, TickRecord
from bap.core.rules.rule_engine import EvaluationReport, RuleEvaluationResult, RuleStatus

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def make_report(*, status=TickStatus.COMPLETED, with_data=True, error=None) -> TickReport:
    evaluation = execution = metrics = None
    if with_data:
        evaluation = EvaluationReport(
            results=(
                RuleEvaluationResult(rule_id="r1", status=RuleStatus.MATCHED),
                RuleEvaluationResult(rule_id="r2", status=RuleStatus.NOT_MATCHED),
            ),
            actions=(),
        )
        execution = ExecutionReport(
            results=(
                ActionResult(
                    request=ActionRequest(action_type="click", rule_id="r1"),
                    status=ActionStatus.SUCCEEDED,
                ),
                ActionResult(
                    request=ActionRequest(action_type="wait", rule_id="r1"),
                    status=ActionStatus.FAILED,
                    error=RuntimeError("boom"),
                ),
            )
        )
        metrics = TickMetrics(total_ms=42, capture_ms=5, vision_ms=30, rules_ms=1, actions_ms=6)
    return TickReport(
        profile_id="p1",
        tick_number=3,
        status=status,
        started_at=NOW,
        finished_at=NOW,
        evaluation=evaluation,
        execution=execution,
        metrics=metrics,
        error=error,
    )


class RecordingStore(StateStorePort):
    def __init__(self, *, fail=False):
        self.ticks = []
        self.health = []
        self.closed = False
        self._fail = fail

    def record_tick(self, tick):
        if self._fail:
            raise RuntimeError("disk full")
        self.ticks.append(tick)

    def record_health(self, event):
        if self._fail:
            raise RuntimeError("disk full")
        self.health.append(event)

    def close(self):
        self.closed = True


# --- conversion ---------------------------------------------------------------


def test_tick_to_record_maps_metrics_rules_and_actions():
    record = tick_to_record(make_report())

    assert isinstance(record, TickRecord)
    assert record.profile_id == "p1"
    assert record.tick_number == 3
    assert record.status == "completed"
    assert (record.duration_ms, record.capture_ms, record.vision_ms) == (42, 5, 30)
    assert (record.rules_matched, record.rules_total) == (1, 2)
    assert [(a.action_type, a.status, a.error) for a in record.actions] == [
        ("click", "succeeded", None),
        ("wait", "failed", "boom"),
    ]
    assert record.actions[0].rule_id == "r1"  # provenance preserved into storage


def test_tick_to_record_handles_missing_stages():
    record = tick_to_record(
        make_report(status=TickStatus.CAPTURE_FAILED, with_data=False, error=RuntimeError("x"))
    )

    assert record.status == "capture_failed"
    assert record.duration_ms is None
    assert record.rules_total is None
    assert record.actions == ()
    assert record.error == "x"


# --- sink behaviour -----------------------------------------------------------


def test_report_is_forwarded_downstream_and_stored():
    store = RecordingStore()
    forwarded = []
    sink = PersistenceSink(store, report_sink=forwarded.append)

    report = make_report()
    sink.on_report(report)

    assert forwarded == [report]  # downstream still sees the runtime object
    assert len(store.ticks) == 1  # DTO stored


def test_health_change_is_forwarded_and_stored_with_previous_state():
    store = RecordingStore()
    forwarded = []
    sink = PersistenceSink(store, health_sink=lambda p, h, r: forwarded.append((p, h)))

    sink.on_health("p1", SessionHealth.DEGRADED, "one failure")
    sink.on_health("p1", SessionHealth.RECOVERING, "attempt 1")

    assert forwarded == [("p1", SessionHealth.DEGRADED), ("p1", SessionHealth.RECOVERING)]
    assert [(e.previous_state, e.new_state) for e in store.health] == [
        (None, "degraded"),
        ("degraded", "recovering"),
    ]


def test_storage_failure_never_breaks_the_runtime():
    store = RecordingStore(fail=True)
    forwarded = []
    errors = []
    sink = PersistenceSink(
        store, report_sink=forwarded.append, on_error=errors.append
    )

    sink.on_report(make_report())  # must not raise

    assert forwarded  # downstream still ran
    assert errors and "persistence error" in errors[0]


def test_storage_failure_on_health_is_contained():
    store = RecordingStore(fail=True)
    errors = []
    sink = PersistenceSink(store, on_error=errors.append)

    sink.on_health("p1", SessionHealth.FAILED, "gave up")  # must not raise

    assert errors and "persistence error" in errors[0]
