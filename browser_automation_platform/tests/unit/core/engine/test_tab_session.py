from datetime import datetime, timezone

import pytest

from bap.core.actions.action_executor import ActionExecutor
from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import (
    ActionRequest,
    ImageData,
    Observation,
    Rect,
    TabHandle,
)
from bap.core.ports.action_handler_port import (
    ActionHandlerPort,
    ActionResult,
    ActionStatus,
)
from bap.core.ports.capture_port import CaptureError, CapturePort
from bap.core.ports.vision_analyzer_port import AnalyzerContext, VisionAnalyzerPort
from bap.core.rules.conditions import ComparisonOp, ValueComparisonCondition
from bap.core.rules.models import Rule
from bap.core.rules.rule_engine import RuleEngine, RuleStatus
from bap.core.vision.aggregator import Aggregator
from bap.core.vision.pipeline import AnalyzerBinding, VisionPipeline
from bap.core.engine.tab_session import CaptureBinding, TabSession, TickStatus

TAB = TabHandle(tab_id="tab1", native=object())


def make_image(tag: str = "img") -> ImageData:
    return ImageData(
        data=b"\x89PNG\r\n\x1a\n",
        width=100,
        height=20,
        tab_id="tab1",
        captured_at=datetime.now(timezone.utc),
        selector=tag,
    )


class FakeCapture(CapturePort):
    """Returns one queued image per call; records calls; can fail on demand."""

    def __init__(self, fail_on_call: int | None = None):
        self.calls: list[tuple[TabHandle, object]] = []
        self.fail_on_call = fail_on_call

    async def capture(self, tab, target=None):
        self.calls.append((tab, target))
        if self.fail_on_call == len(self.calls):
            raise CaptureError("page crashed")
        return make_image(tag=f"capture-{len(self.calls)}")


class StubAnalyzer(VisionAnalyzerPort):
    def __init__(self, name: str, value, *, error: Exception | None = None):
        self._name = name
        self._value = value
        self._error = error
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def analyze(self, image, context):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return [
            Observation(
                name=f"{context.target_name}.value",
                kind=ObservationKind.TEXT,
                analyzer=self._name,
                value=self._value,
            )
        ]


class RecordingHandler(ActionHandlerPort):
    def __init__(self, action_type: str = "click", *, error: Exception | None = None):
        self._action_type = action_type
        self._error = error
        self.calls: list[tuple[ActionRequest, object]] = []

    @property
    def action_type(self) -> str:
        return self._action_type

    async def execute(self, request, context):
        self.calls.append((request, context))
        if self._error is not None:
            raise self._error
        return ActionResult(request=request, status=ActionStatus.SUCCEEDED)


def pipeline_for(target_name: str, *analyzers) -> VisionPipeline:
    ctx = AnalyzerContext(profile_id="p1", target_name=target_name)
    return VisionPipeline([AnalyzerBinding(analyzer=a, context=ctx) for a in analyzers])


def counter_rule(threshold: int = 100, **kwargs) -> Rule:
    return Rule(
        id=kwargs.pop("rule_id", "r1"),
        condition=ValueComparisonCondition(
            field="header.value", op=ComparisonOp.LESS_THAN, expected=threshold
        ),
        actions=(ActionRequest(action_type="click", params={"target": "#btn"}),),
        **kwargs,
    )


def make_session(
    *,
    capture: CapturePort | None = None,
    bindings=None,
    rules=(),
    handlers=None,
    aggregator=None,
    analyzer_value=42,
):
    if bindings is None:
        bindings = [
            CaptureBinding(
                target=None,
                pipeline=pipeline_for("header", StubAnalyzer("ocr", analyzer_value)),
            )
        ]
    return TabSession(
        profile_id="p1",
        tab=TAB,
        capture_port=capture if capture is not None else FakeCapture(),
        bindings=bindings,
        aggregator=aggregator if aggregator is not None else Aggregator(),
        rule_engine=RuleEngine(list(rules)),
        action_executor=ActionExecutor(handlers if handlers is not None else [RecordingHandler()]),
    )


# --- Successful full tick -------------------------------------------------------


async def test_successful_tick_runs_every_stage_in_order():
    handler = RecordingHandler()
    session = make_session(rules=[counter_rule()], handlers=[handler])

    report = await session.tick()

    assert report.completed
    assert report.status is TickStatus.COMPLETED
    assert report.profile_id == "p1"
    assert report.tick_number == 1
    assert len(report.captures) == 1
    assert report.vision.fully_succeeded
    assert report.page_state.value_of("header.value") == 42
    assert report.evaluation.results[0].status is RuleStatus.MATCHED
    assert report.execution.fully_succeeded
    assert len(handler.calls) == 1
    assert handler.calls[0][0].rule_id == "r1"  # provenance survived the whole loop
    assert report.finished_at >= report.started_at


async def test_tick_numbers_increment():
    session = make_session()

    first, second = await session.tick(), await session.tick()

    assert (first.tick_number, second.tick_number) == (1, 2)
    assert session.ticks_run == 2


# --- Capture failure ---------------------------------------------------------------


async def test_capture_failure_stops_tick_safely():
    handler = RecordingHandler()
    session = make_session(capture=FakeCapture(fail_on_call=1), rules=[counter_rule()],
                           handlers=[handler])

    report = await session.tick()  # must not raise

    assert report.status is TickStatus.CAPTURE_FAILED
    assert isinstance(report.error, CaptureError)
    assert report.captures == ()
    assert report.vision is None
    assert report.page_state is None
    assert report.evaluation is None
    assert report.execution is None
    assert handler.calls == []  # nothing downstream ran


async def test_second_capture_failing_keeps_first_capture_in_report():
    binding = CaptureBinding(target=None, pipeline=pipeline_for("a", StubAnalyzer("s", 1)))
    binding2 = CaptureBinding(
        target=Rect(0, 0, 10, 10), pipeline=pipeline_for("b", StubAnalyzer("s2", 2))
    )
    session = make_session(capture=FakeCapture(fail_on_call=2), bindings=[binding, binding2])

    report = await session.tick()

    assert report.status is TickStatus.CAPTURE_FAILED
    assert len(report.captures) == 1


# --- Vision failure ------------------------------------------------------------------


async def test_vision_failure_produces_failed_tick_and_skips_rules():
    rule = counter_rule()
    handler = RecordingHandler()
    bindings = [
        CaptureBinding(
            target=None,
            pipeline=pipeline_for(
                "header",
                StubAnalyzer("ok", 42),
                StubAnalyzer("broken", 0, error=RuntimeError("lens cap")),
            ),
        )
    ]
    session = make_session(bindings=bindings, rules=[rule], handlers=[handler])

    report = await session.tick()

    assert report.status is TickStatus.VISION_FAILED
    assert len(report.vision.failures) == 1
    assert report.vision.observations != ()  # partial data preserved for diagnosis
    assert report.page_state is None  # ...but never acted upon
    assert report.evaluation is None
    assert handler.calls == []


# --- Rule outcomes -----------------------------------------------------------------


async def test_rules_matching_nothing_complete_with_empty_execution():
    session = make_session(rules=[counter_rule(threshold=10)], analyzer_value=42)

    report = await session.tick()

    assert report.completed
    assert report.evaluation.results[0].status is RuleStatus.NOT_MATCHED
    assert report.evaluation.actions == ()
    assert report.execution.results == ()
    assert report.execution.fully_succeeded


async def test_rules_producing_actions_reach_the_executor():
    handler = RecordingHandler()
    session = make_session(
        rules=[counter_rule(rule_id="r1"), counter_rule(rule_id="r2")], handlers=[handler]
    )

    report = await session.tick()

    assert [a.rule_id for a in report.evaluation.actions] == ["r1", "r2"]
    assert [c[0].rule_id for c in handler.calls] == ["r1", "r2"]


async def test_action_failure_does_not_crash_the_tick():
    handler = RecordingHandler(error=RuntimeError("element vanished"))
    session = make_session(rules=[counter_rule()], handlers=[handler])

    report = await session.tick()  # must not raise

    assert report.completed  # action failures are execution data, not tick failures
    assert not report.execution.fully_succeeded
    assert "element vanished" in report.execution.failures[0].message


# --- Determinism and wiring -----------------------------------------------------------


async def test_bindings_are_processed_in_declaration_order():
    capture = FakeCapture()
    bindings = [
        CaptureBinding(target=None, pipeline=pipeline_for("first", StubAnalyzer("a", 1))),
        CaptureBinding(
            target=Rect(0, 0, 5, 5), pipeline=pipeline_for("second", StubAnalyzer("b", 2))
        ),
    ]
    session = make_session(capture=capture, bindings=bindings)

    report = await session.tick()

    assert [t for _, t in capture.calls] == [None, Rect(0, 0, 5, 5)]
    assert [o.name for o in report.vision.observations] == ["first.value", "second.value"]


async def test_injected_dependencies_receive_the_sessions_tab_and_profile():
    capture = FakeCapture()
    handler = RecordingHandler()
    session = make_session(capture=capture, rules=[counter_rule()], handlers=[handler])

    await session.tick()

    assert capture.calls[0][0] is TAB
    action_context = handler.calls[0][1]
    assert action_context.tab is TAB
    assert action_context.profile_id == "p1"


async def test_ticks_are_independent_when_no_layer_holds_state():
    session = make_session(rules=[counter_rule()])

    first, second = await session.tick(), await session.tick()

    assert first.status == second.status
    assert first.page_state.value_of("header.value") == second.page_state.value_of("header.value")
    assert [r.status for r in first.evaluation.results] == [
        r.status for r in second.evaluation.results
    ]


async def test_cooldown_state_lives_in_the_engine_not_the_session():
    session = make_session(rules=[counter_rule(cooldown_ms=60_000)])

    first, second = await session.tick(), await session.tick()

    assert first.evaluation.results[0].status is RuleStatus.MATCHED
    assert second.evaluation.results[0].status is RuleStatus.ON_COOLDOWN


async def test_collaborator_wiring_bug_becomes_internal_error_not_a_raise():
    class BrokenAggregator(Aggregator):
        def build_page_state(self, profile_id, observations):
            raise RuntimeError("wiring bug")

    session = make_session(aggregator=BrokenAggregator())

    report = await session.tick()  # must not raise through the scheduler boundary

    assert report.status is TickStatus.INTERNAL_ERROR
    assert isinstance(report.error, RuntimeError)


def test_session_requires_profile_id():
    with pytest.raises(ValueError, match="profile_id"):
        TabSession(
            profile_id="",
            tab=TAB,
            capture_port=FakeCapture(),
            bindings=[],
            aggregator=Aggregator(),
            rule_engine=RuleEngine([]),
            action_executor=ActionExecutor([]),
        )
