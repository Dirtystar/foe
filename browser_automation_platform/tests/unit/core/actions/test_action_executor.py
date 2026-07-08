from dataclasses import FrozenInstanceError

import pytest

from bap.core.actions.action_executor import ActionExecutor, ExecutionReport
from bap.core.domain.models import ActionRequest, TabHandle
from bap.core.ports.action_handler_port import (
    ActionContext,
    ActionHandlerPort,
    ActionResult,
    ActionStatus,
)

CTX = ActionContext(tab=TabHandle(tab_id="tab1", native=None), profile_id="p1")


class RecordingHandler(ActionHandlerPort):
    """Succeeds by default; optionally raises or returns a rogue value.
    Records every (request, context) it sees, and can share a log with other
    handlers so cross-handler ordering is observable."""

    def __init__(self, action_type: str, *, error: Exception | None = None,
                 rogue_return=None, shared_log: list | None = None):
        self._action_type = action_type
        self._error = error
        self._rogue_return = rogue_return
        self.calls: list[tuple[ActionRequest, ActionContext]] = []
        self.shared_log = shared_log

    @property
    def action_type(self) -> str:
        return self._action_type

    async def execute(self, request, context):
        self.calls.append((request, context))
        if self.shared_log is not None:
            self.shared_log.append(request.params.get("tag", self._action_type))
        if self._error is not None:
            raise self._error
        if self._rogue_return is not None:
            return self._rogue_return
        return ActionResult(request=request, status=ActionStatus.SUCCEEDED, message="ok")


def req(action_type: str, **params) -> ActionRequest:
    return ActionRequest(action_type=action_type, params=params, rule_id="r1")


# --- Registration ---------------------------------------------------------------


def test_registered_handlers_are_exposed_by_action_type():
    executor = ActionExecutor([RecordingHandler("click"), RecordingHandler("navigate")])

    assert executor.supported_action_types == ("click", "navigate")


def test_duplicate_action_type_rejected_at_construction():
    with pytest.raises(ValueError, match="Duplicate handler"):
        ActionExecutor([RecordingHandler("click"), RecordingHandler("click")])


def test_empty_action_type_rejected_at_construction():
    with pytest.raises(ValueError, match="empty action_type"):
        ActionExecutor([RecordingHandler("")])


# --- Execution ------------------------------------------------------------------


async def test_single_action_executes_and_succeeds():
    handler = RecordingHandler("click")
    executor = ActionExecutor([handler])
    request = req("click", target="#btn")

    report = await executor.execute([request], CTX)

    assert report.fully_succeeded
    assert report.results[0].request is request
    assert report.results[0].status is ActionStatus.SUCCEEDED
    assert handler.calls[0][0] is request


async def test_actions_execute_in_declaration_order_across_handlers():
    log: list[str] = []
    executor = ActionExecutor(
        [RecordingHandler("click", shared_log=log), RecordingHandler("type", shared_log=log)]
    )

    await executor.execute(
        [req("type", tag="first"), req("click", tag="second"), req("type", tag="third")], CTX
    )

    assert log == ["first", "second", "third"]


async def test_multiple_actions_produce_one_result_each_in_order():
    executor = ActionExecutor([RecordingHandler("click"), RecordingHandler("type")])
    requests = [req("click"), req("type"), req("click")]

    report = await executor.execute(requests, CTX)

    assert len(report.results) == 3
    assert [r.request for r in report.results] == requests


async def test_unknown_action_type_is_reported_not_raised_and_rest_run():
    handler = RecordingHandler("click")
    executor = ActionExecutor([handler])

    report = await executor.execute([req("teleport"), req("click")], CTX)

    unknown, clicked = report.results
    assert unknown.status is ActionStatus.NO_HANDLER
    assert "teleport" in unknown.message
    assert clicked.status is ActionStatus.SUCCEEDED
    assert not report.fully_succeeded
    assert report.failures == (unknown,)


async def test_raising_handler_is_contained_and_rest_run():
    boom = RuntimeError("element vanished")
    executor = ActionExecutor(
        [RecordingHandler("click", error=boom), RecordingHandler("type")]
    )

    report = await executor.execute([req("click"), req("type")], CTX)

    failed, ok = report.results
    assert failed.status is ActionStatus.FAILED
    assert failed.error is boom
    assert "element vanished" in failed.message
    assert ok.status is ActionStatus.SUCCEEDED


async def test_handler_returning_non_action_result_is_a_failure():
    executor = ActionExecutor([RecordingHandler("click", rogue_return="done")])

    report = await executor.execute([req("click")], CTX)

    assert report.results[0].status is ActionStatus.FAILED
    assert "instead of ActionResult" in report.results[0].message


async def test_handler_may_report_domain_failure_by_returning_failed_result():
    class Refusing(ActionHandlerPort):
        @property
        def action_type(self) -> str:
            return "click"

        async def execute(self, request, context):
            return ActionResult(
                request=request, status=ActionStatus.FAILED, message="target off-screen"
            )

    report = await ActionExecutor([Refusing()]).execute([req("click")], CTX)

    assert report.results[0].status is ActionStatus.FAILED
    assert report.results[0].error is None


async def test_empty_request_list_produces_empty_successful_report():
    report = await ActionExecutor([RecordingHandler("click")]).execute([], CTX)

    assert report.results == ()
    assert report.fully_succeeded


async def test_execution_is_deterministic_for_identical_inputs():
    async def run():
        executor = ActionExecutor([RecordingHandler("click"), RecordingHandler("type")])
        return await executor.execute([req("click"), req("nope"), req("type")], CTX)

    first, second = await run(), await run()

    assert [r.status for r in first.results] == [r.status for r in second.results]
    assert [r.request.action_type for r in first.results] == [
        r.request.action_type for r in second.results
    ]


async def test_context_is_propagated_unchanged_to_every_handler():
    click, type_ = RecordingHandler("click"), RecordingHandler("type")
    executor = ActionExecutor([click, type_])

    await executor.execute([req("click"), req("type")], CTX)

    assert click.calls[0][1] is CTX
    assert type_.calls[0][1] is CTX


# --- Models ----------------------------------------------------------------------


def test_action_context_requires_profile_id():
    with pytest.raises(ValueError, match="profile_id"):
        ActionContext(tab=TabHandle(tab_id="t", native=None), profile_id="")


def test_action_result_validates_and_is_immutable():
    result = ActionResult(request=req("click"), status=ActionStatus.SUCCEEDED)

    assert result.succeeded
    with pytest.raises(FrozenInstanceError):
        result.status = ActionStatus.FAILED  # type: ignore[misc]
    with pytest.raises(ValueError, match="ActionStatus"):
        ActionResult(request=req("click"), status="succeeded")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ActionRequest"):
        ActionResult(request="click", status=ActionStatus.SUCCEEDED)  # type: ignore[arg-type]


def test_execution_report_failures_view():
    ok = ActionResult(request=req("a"), status=ActionStatus.SUCCEEDED)
    bad = ActionResult(request=req("b"), status=ActionStatus.FAILED)
    report = ExecutionReport(results=(ok, bad))

    assert not report.fully_succeeded
    assert report.failures == (bad,)
