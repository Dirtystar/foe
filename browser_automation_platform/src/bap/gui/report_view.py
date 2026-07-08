"""Pure presentation helpers: TickReport -> display strings.

Kept Qt-free so the mapping logic is unit-tested directly. The window uses
these to fill table cells and log lines; it holds no automation logic of its
own — it only formats reports it is handed.
"""

from __future__ import annotations

from dataclasses import dataclass

from bap.core.engine.tab_session import TickReport


@dataclass(frozen=True)
class SessionRow:
    profile_id: str
    status: str
    last_tick: str
    rules: str
    actions: str
    error: str
    timing: str


def _rules_summary(report: TickReport) -> str:
    if report.evaluation is None:
        return "-"
    results = report.evaluation.results
    matched = sum(1 for r in results if r.status.value == "matched")
    return f"{matched}/{len(results)} matched"


def _actions_summary(report: TickReport) -> str:
    if report.execution is None:
        return "-"
    results = report.execution.results
    succeeded = sum(1 for r in results if r.succeeded)
    return f"{succeeded}/{len(results)} ok"


def _error_summary(report: TickReport) -> str:
    if report.error is not None:
        return f"{type(report.error).__name__}: {report.error}"
    if report.vision is not None and report.vision.failures:
        names = ", ".join(f.analyzer for f in report.vision.failures)
        return f"vision failed: {names}"
    if report.execution is not None and report.execution.failures:
        return f"{len(report.execution.failures)} action failure(s)"
    return ""


def _timing_summary(report: TickReport) -> str:
    m = report.metrics
    if m is None:
        return "-"
    return (
        f"{m.total_ms:.0f}ms "
        f"(cap {m.capture_ms:.0f}/vis {m.vision_ms:.0f}/"
        f"rul {m.rules_ms:.0f}/act {m.actions_ms:.0f})"
    )


def row_for(report: TickReport) -> SessionRow:
    return SessionRow(
        profile_id=report.profile_id,
        status=report.status.value,
        last_tick=str(report.tick_number),
        rules=_rules_summary(report),
        actions=_actions_summary(report),
        error=_error_summary(report),
        timing=_timing_summary(report),
    )


def log_line(report: TickReport) -> str:
    row = row_for(report)
    base = (
        f"[{row.profile_id}] tick #{row.last_tick} -> {row.status} "
        f"| rules {row.rules} | actions {row.actions} | {row.timing}"
    )
    return f"{base} | {row.error}" if row.error else base


__all__ = ["SessionRow", "log_line", "row_for"]
