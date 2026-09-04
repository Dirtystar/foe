"""Rule-layer domain models.

The flow this layer implements:

    PageState -> Condition evaluation -> Rule match -> ActionRequest

Everything here is browser-ignorant: conditions read a PageState snapshot,
rules pair a condition with the ActionRequests to emit on match. Nothing in
this package executes anything — producing ActionRequests is the boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bap.core.domain.models import ActionRequest, PageState


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class EvaluationContext:
    """Ambient facts for one evaluation cycle.

    `now` exists so time-based conditions (age/staleness of an observation)
    are deterministic and testable: the engine creates one context per cycle
    and every condition sees the same instant, never calling the clock itself.
    """

    now: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class ConditionResult:
    """Outcome of one condition evaluation.

    `reason` is a human-readable explanation ("field 'x' missing",
    "0.42 < threshold 0.8") surfaced by trace/debug views, so rule packs can
    be diagnosed without a debugger. Composite conditions (AND/OR/NOT) keep
    their children's outcomes for the same purpose.
    """

    matched: bool
    reason: str = ""
    children: tuple[ConditionResult, ...] = ()

    def __bool__(self) -> bool:
        return self.matched


class Condition(ABC):
    """A pure predicate over a PageState snapshot.

    Implementations (Strategy) must be stateless and side-effect free:
    same (state, context) in, same ConditionResult out. Future built-ins —
    observation-exists, value comparison, confidence threshold, staleness —
    and plugin conditions all implement exactly this.
    """

    @abstractmethod
    def evaluate(self, state: PageState, context: EvaluationContext) -> ConditionResult: ...


@dataclass(frozen=True)
class Rule:
    """One unit of automation policy: when `condition` matches, emit `actions`.

    `cooldown_ms` is declarative data — the engine enforces it using runtime
    state; the rule itself stays immutable and stateless. Disabled rules are
    kept in the pack (visible, toggleable) but never evaluated.
    """

    id: str
    condition: Condition
    actions: tuple[ActionRequest, ...]
    enabled: bool = True
    cooldown_ms: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Rule.id must be non-empty.")
        if not isinstance(self.condition, Condition):
            raise ValueError(f"Rule.condition must be a Condition, got {self.condition!r}.")
        if isinstance(self.actions, Sequence) and not isinstance(self.actions, tuple):
            object.__setattr__(self, "actions", tuple(self.actions))
        if not self.actions:
            raise ValueError(f"Rule '{self.id}' must declare at least one action.")
        if any(not isinstance(a, ActionRequest) for a in self.actions):
            raise ValueError(f"Rule '{self.id}' actions must all be ActionRequest instances.")
        if self.cooldown_ms < 0:
            raise ValueError(f"Rule '{self.id}' cooldown_ms must be >= 0.")


__all__ = ["Condition", "ConditionResult", "EvaluationContext", "Rule"]
