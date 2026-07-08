"""Helper for building TickReports in GUI tests (not collected by pytest)."""

from __future__ import annotations

from datetime import datetime, timezone

from bap.core.actions.action_executor import ExecutionReport
from bap.core.domain.models import ActionRequest
from bap.core.engine.tab_session import TickMetrics, TickReport, TickStatus
from bap.core.ports.action_handler_port import ActionResult, ActionStatus
from bap.core.rules.rule_engine import EvaluationReport, RuleEvaluationResult, RuleStatus


def make_report(
    *,
    profile_id="p1",
    tick=1,
    status=TickStatus.COMPLETED,
    matched=0,
    rules_total=0,
    actions_ok=0,
    actions_total=0,
    error=None,
    vision=None,
    metrics=None,
) -> TickReport:
    now = datetime.now(timezone.utc)

    evaluation = None
    if status is TickStatus.COMPLETED:
        results = tuple(
            RuleEvaluationResult(
                rule_id=f"r{i}",
                status=RuleStatus.MATCHED if i < matched else RuleStatus.NOT_MATCHED,
            )
            for i in range(rules_total)
        )
        evaluation = EvaluationReport(results=results, actions=())

    execution = None
    if status is TickStatus.COMPLETED:
        results = tuple(
            ActionResult(
                request=ActionRequest(action_type="click"),
                status=ActionStatus.SUCCEEDED if i < actions_ok else ActionStatus.FAILED,
            )
            for i in range(actions_total)
        )
        execution = ExecutionReport(results=results)

    return TickReport(
        profile_id=profile_id,
        tick_number=tick,
        status=status,
        started_at=now,
        finished_at=now,
        evaluation=evaluation,
        execution=execution,
        error=error,
        vision=vision,
        metrics=metrics,
    )


def sample_metrics(total=42.0, capture=5.0, vision=30.0, rules=1.0, actions=6.0) -> TickMetrics:
    return TickMetrics(
        total_ms=total, capture_ms=capture, vision_ms=vision, rules_ms=rules, actions_ms=actions
    )
