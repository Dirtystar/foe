from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from bap.core.domain.models import ActionRequest, TabHandle


@dataclass(frozen=True)
class ActionContext:
    """Where an action executes: the tab it targets and the owning profile.

    The TabHandle stays opaque here — only concrete adapters (a future
    Playwright handler) unwrap `tab.native`. Handlers must treat the context
    as read-only ambient facts, mirroring EvaluationContext in the rules
    layer.
    """

    tab: TabHandle
    profile_id: str

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("ActionContext.profile_id must be non-empty.")


class ActionStatus(Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NO_HANDLER = "no_handler"


@dataclass(frozen=True)
class ActionResult:
    """Outcome of executing (or failing to execute) one ActionRequest.

    Mirrors RuleEvaluationResult: the request is kept whole for provenance
    (its rule_id says which rule asked for this), `message` is the
    human-readable explanation, and `error` carries the exception when one
    was contained.
    """

    request: ActionRequest
    status: ActionStatus
    message: str = ""
    error: Exception | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, ActionRequest):
            raise ValueError(f"ActionResult.request must be an ActionRequest, got {self.request!r}.")
        if not isinstance(self.status, ActionStatus):
            raise ValueError(f"ActionResult.status must be an ActionStatus, got {self.status!r}.")

    @property
    def succeeded(self) -> bool:
        return self.status is ActionStatus.SUCCEEDED


class ActionHandlerError(Exception):
    """Base class for handler failures with domain meaning."""


class ActionHandlerPort(ABC):
    """Contract for executing exactly one action type (Strategy).

    A handler owns the side effect and nothing else: no resolution, no
    ordering, no retry policy — that is the ActionExecutor's job. Handlers
    should be stateless; per-execution facts arrive via the context. Report
    domain-level failure by returning a FAILED result; raising is also safe
    (the executor contains it) but reserves the exception path for the
    unexpected.
    """

    @property
    @abstractmethod
    def action_type(self) -> str:
        """The ActionRequest.action_type this handler executes (registry key)."""

    @abstractmethod
    async def execute(self, request: ActionRequest, context: ActionContext) -> ActionResult: ...


__all__ = [
    "ActionContext",
    "ActionHandlerError",
    "ActionHandlerPort",
    "ActionResult",
    "ActionStatus",
]
