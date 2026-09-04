"""ActionExecutor: runs the ActionRequests a rule evaluation produced.

The action layer's only orchestrator. It resolves each request to its
registered handler and executes them strictly in declaration order — actions
are side effects, so unlike vision analyzers they must never run
concurrently within one batch. Failures are contained per action: a missing
handler, a raising handler, or a handler returning garbage becomes a FAILED /
NO_HANDLER result and the remaining actions still run. The caller
(TabSession) reads the ExecutionReport and decides what a partial failure
means — same philosophy as VisionResult and EvaluationReport.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bap.core.domain.models import ActionRequest
from bap.core.ports.action_handler_port import (
    ActionContext,
    ActionHandlerPort,
    ActionResult,
    ActionStatus,
)


@dataclass(frozen=True)
class ExecutionReport:
    """One ActionResult per request, in the order they were executed."""

    results: tuple[ActionResult, ...]

    @property
    def fully_succeeded(self) -> bool:
        return all(r.succeeded for r in self.results)

    @property
    def failures(self) -> tuple[ActionResult, ...]:
        return tuple(r for r in self.results if not r.succeeded)


class ActionExecutor:
    """Executes ActionRequests through registered ActionHandlerPorts.

    Handlers are injected at construction (one per action type — a duplicate
    is a wiring bug and fails fast, mirroring RuleEngine's duplicate-id
    check). The executor holds no other state and no policy: retries,
    throttling, and reacting to failures belong to callers or future
    decorating handlers.
    """

    def __init__(self, handlers: Sequence[ActionHandlerPort]) -> None:
        registry: dict[str, ActionHandlerPort] = {}
        for handler in handlers:
            action_type = handler.action_type
            if not action_type:
                raise ValueError(f"Handler {handler!r} declares an empty action_type.")
            if action_type in registry:
                raise ValueError(f"Duplicate handler for action type '{action_type}'.")
            registry[action_type] = handler
        self._registry = registry

    @property
    def supported_action_types(self) -> tuple[str, ...]:
        return tuple(self._registry)

    async def execute(
        self, requests: Sequence[ActionRequest], context: ActionContext
    ) -> ExecutionReport:
        results = [await self._execute_one(request, context) for request in requests]
        return ExecutionReport(results=tuple(results))

    async def _execute_one(
        self, request: ActionRequest, context: ActionContext
    ) -> ActionResult:
        handler = self._registry.get(request.action_type)
        if handler is None:
            return ActionResult(
                request=request,
                status=ActionStatus.NO_HANDLER,
                message=f"no handler registered for action type '{request.action_type}'",
            )
        try:
            result = await handler.execute(request, context)
            if not isinstance(result, ActionResult):
                return ActionResult(
                    request=request,
                    status=ActionStatus.FAILED,
                    message=(
                        f"handler '{handler.action_type}' returned "
                        f"{type(result).__name__} instead of ActionResult"
                    ),
                )
            return result
        except Exception as exc:
            return ActionResult(
                request=request,
                status=ActionStatus.FAILED,
                message=f"handler raised {type(exc).__name__}: {exc}",
                error=exc,
            )


__all__ = ["ActionExecutor", "ExecutionReport"]
