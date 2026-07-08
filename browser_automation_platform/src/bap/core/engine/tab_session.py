"""TabSession: the per-tab runtime coordinator.

Owns one tab's automation loop and nothing else. A tick wires the existing
layers together in fixed order — capture, vision, aggregate, evaluate,
execute — and returns everything that happened as one immutable TickReport.
Pure orchestration: every step's logic lives in the injected collaborator
(Template Method with delegation), and TabSession never inspects rule or
action semantics.

tick() never raises: infrastructure failures become failed TickReports, so
the future Scheduler can call it blindly on a timer without a try/except at
the boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from bap.core.actions.action_executor import ActionExecutor, ExecutionReport
from bap.core.domain.models import ImageData, Observation, PageState, TabHandle
from bap.core.ports.action_handler_port import ActionContext
from bap.core.ports.capture_port import CapturePort, CaptureTarget
from bap.core.rules.models import EvaluationContext
from bap.core.rules.rule_engine import EvaluationReport, RuleEngine
from bap.core.vision.aggregator import Aggregator
from bap.core.vision.pipeline import AnalyzerFailure, VisionPipeline, VisionResult


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CaptureBinding:
    """One capture target and the vision pipeline configured for it.

    A profile with several watched regions becomes several bindings; the
    tick captures and analyzes them in declaration order.
    """

    target: CaptureTarget
    pipeline: VisionPipeline


class TickStatus(Enum):
    COMPLETED = "completed"
    CAPTURE_FAILED = "capture_failed"
    VISION_FAILED = "vision_failed"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True)
class TickReport:
    """Everything one tick produced, stage by stage.

    Stages that were never reached (because an earlier one failed) are None,
    so the report distinguishes "did not run" from "ran and found nothing".
    Rule and action failures do NOT fail the tick — they are data inside
    `evaluation` / `execution`, per those layers' contracts; the tick-level
    status covers only the stages TabSession itself is responsible for.
    """

    profile_id: str
    tick_number: int
    status: TickStatus
    started_at: datetime
    finished_at: datetime
    captures: tuple[ImageData, ...] = ()
    vision: VisionResult | None = None
    page_state: PageState | None = None
    evaluation: EvaluationReport | None = None
    execution: ExecutionReport | None = None
    error: Exception | None = None

    @property
    def completed(self) -> bool:
        return self.status is TickStatus.COMPLETED


class TabSession:
    """Coordinates the automation loop for exactly one tab.

    Owns the per-tab runtime: the tick counter, its RuleEngine instance
    (which owns cooldowns) and its ActionExecutor (which owns handlers).
    The rules inside the engine remain immutable and shareable; the tab
    handle stays opaque — only the injected ports know what is behind it.
    """

    def __init__(
        self,
        *,
        profile_id: str,
        tab: TabHandle,
        capture_port: CapturePort,
        bindings: Sequence[CaptureBinding],
        aggregator: Aggregator,
        rule_engine: RuleEngine,
        action_executor: ActionExecutor,
    ) -> None:
        if not profile_id:
            raise ValueError("TabSession.profile_id must be non-empty.")
        self._profile_id = profile_id
        self._tab = tab
        self._capture_port = capture_port
        self._bindings = tuple(bindings)
        self._aggregator = aggregator
        self._rule_engine = rule_engine
        self._action_executor = action_executor
        self._tick_counter = 0

    @property
    def profile_id(self) -> str:
        return self._profile_id

    @property
    def ticks_run(self) -> int:
        return self._tick_counter

    async def tick(self) -> TickReport:
        self._tick_counter += 1
        started_at = _utc_now()

        def report(status: TickStatus, **stages) -> TickReport:
            return TickReport(
                profile_id=self._profile_id,
                tick_number=self._tick_counter,
                status=status,
                started_at=started_at,
                finished_at=_utc_now(),
                **stages,
            )

        try:
            # 1+2. capture every binding's target, run its vision pipeline
            captures: list[ImageData] = []
            observations: list[Observation] = []
            failures: list[AnalyzerFailure] = []
            for binding in self._bindings:
                try:
                    image = await self._capture_port.capture(self._tab, binding.target)
                except Exception as exc:
                    return report(
                        TickStatus.CAPTURE_FAILED, captures=tuple(captures), error=exc
                    )
                captures.append(image)
                result = await binding.pipeline.run(image)
                observations.extend(result.observations)
                failures.extend(result.failures)

            vision = VisionResult(observations=tuple(observations), failures=tuple(failures))
            if vision.failures:
                # Conservative policy: never evaluate rules against a scene we
                # only partially understood — acting on it could be worse than
                # skipping a tick. Revisit as a configurable policy if needed.
                return report(
                    TickStatus.VISION_FAILED, captures=tuple(captures), vision=vision
                )

            # 3. aggregate observations into one snapshot
            page_state = self._aggregator.build_page_state(self._profile_id, vision.observations)

            # 4. evaluate rules (engine owns cooldowns and error containment)
            evaluation = self._rule_engine.evaluate(page_state, EvaluationContext())

            # 5. execute matched actions (executor owns failure containment)
            execution = await self._action_executor.execute(
                evaluation.actions,
                ActionContext(tab=self._tab, profile_id=self._profile_id),
            )

            # 6. the report IS the published result; event fan-out is a
            # later adapter between the Scheduler and the EventBus.
            return report(
                TickStatus.COMPLETED,
                captures=tuple(captures),
                vision=vision,
                page_state=page_state,
                evaluation=evaluation,
                execution=execution,
            )
        except Exception as exc:
            # Collaborators contain their own failures; this catches wiring
            # bugs so nothing ever propagates into the scheduler.
            return report(TickStatus.INTERNAL_ERROR, error=exc)


__all__ = ["CaptureBinding", "TabSession", "TickReport", "TickStatus"]
