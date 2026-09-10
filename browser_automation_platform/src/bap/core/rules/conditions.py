"""Built-in Condition implementations (Strategy).

Every condition is a frozen dataclass: stateless, immutable, safe to share
between rules and tabs. They read a PageState snapshot and return a
ConditionResult — never raising during evaluation. Anything unexpected
(missing field, incomparable types) is a non-match with the explanation in
`reason`, because a rule pack must not be able to crash a tick. Errors that
indicate a broken *configuration* (bad regex, threshold out of range) do
raise, at construction time, so they surface at config load.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from bap.core.domain.models import AttributeValue, PageState
from bap.core.rules.models import Condition, ConditionResult, EvaluationContext


def _missing(field_name: str) -> ConditionResult:
    return ConditionResult(matched=False, reason=f"field '{field_name}' missing")


@dataclass(frozen=True)
class ExistsCondition(Condition):
    """Matches when the PageState has an observation for `field`."""

    field: str

    def __post_init__(self) -> None:
        if not self.field:
            raise ValueError("ExistsCondition.field must be non-empty.")

    def evaluate(self, state: PageState, context: EvaluationContext) -> ConditionResult:
        if state.has(self.field):
            return ConditionResult(matched=True, reason=f"field '{self.field}' present")
        return _missing(self.field)


class ComparisonOp(Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    LESS_THAN = "less_than"
    LESS_OR_EQUAL = "less_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_OR_EQUAL = "greater_or_equal"
    CONTAINS = "contains"
    MATCHES_REGEX = "matches_regex"


@dataclass(frozen=True)
class ValueComparisonCondition(Condition):
    """Compares an observation's value against an expected value.

    A missing field or a type-incomparable pair (e.g. "abc" < 5) is a
    non-match whose reason says why — not an exception.
    """

    field: str
    op: ComparisonOp
    expected: AttributeValue

    def __post_init__(self) -> None:
        if not self.field:
            raise ValueError("ValueComparisonCondition.field must be non-empty.")
        if not isinstance(self.op, ComparisonOp):
            raise ValueError(f"op must be a ComparisonOp, got {self.op!r}.")
        if self.op is ComparisonOp.MATCHES_REGEX:
            if not isinstance(self.expected, str):
                raise ValueError("matches_regex expects a string pattern.")
            try:
                re.compile(self.expected)
            except re.error as exc:
                raise ValueError(f"Invalid regex {self.expected!r}: {exc}") from exc

    def evaluate(self, state: PageState, context: EvaluationContext) -> ConditionResult:
        obs = state.get(self.field)
        if obs is None:
            return _missing(self.field)
        actual = obs.value
        try:
            matched = self._compare(actual)
        except TypeError:
            return ConditionResult(
                matched=False,
                reason=(
                    f"field '{self.field}': {actual!r} is not comparable "
                    f"with {self.expected!r} ({self.op.value})"
                ),
            )
        return ConditionResult(
            matched=matched,
            reason=(
                f"field '{self.field}': {actual!r} {self.op.value} {self.expected!r}"
                f" -> {'matched' if matched else 'failed'}"
            ),
        )

    def _compare(self, actual: AttributeValue | None) -> bool:
        op, expected = self.op, self.expected
        if op is ComparisonOp.EQUALS:
            return actual == expected
        if op is ComparisonOp.NOT_EQUALS:
            return actual != expected
        if actual is None:
            raise TypeError("no value to compare")
        if op is ComparisonOp.LESS_THAN:
            return actual < expected
        if op is ComparisonOp.LESS_OR_EQUAL:
            return actual <= expected
        if op is ComparisonOp.GREATER_THAN:
            return actual > expected
        if op is ComparisonOp.GREATER_OR_EQUAL:
            return actual >= expected
        if op is ComparisonOp.CONTAINS:
            return str(expected) in actual
        if op is ComparisonOp.MATCHES_REGEX:
            if not isinstance(actual, str):
                raise TypeError("regex needs a string value")
            return re.search(expected, actual) is not None
        raise TypeError(f"unhandled op {op}")  # pragma: no cover


@dataclass(frozen=True)
class ConfidenceThresholdCondition(Condition):
    """Matches when the observation exists with confidence >= `minimum`."""

    field: str
    minimum: float

    def __post_init__(self) -> None:
        if not self.field:
            raise ValueError("ConfidenceThresholdCondition.field must be non-empty.")
        if not 0.0 <= self.minimum <= 1.0:
            raise ValueError(f"minimum must be in [0.0, 1.0], got {self.minimum}.")

    def evaluate(self, state: PageState, context: EvaluationContext) -> ConditionResult:
        obs = state.get(self.field)
        if obs is None:
            return _missing(self.field)
        matched = obs.confidence >= self.minimum
        return ConditionResult(
            matched=matched,
            reason=(
                f"field '{self.field}': confidence {obs.confidence:.3f} "
                f"{'>=' if matched else '<'} threshold {self.minimum:.3f}"
            ),
        )


@dataclass(frozen=True)
class StalenessCondition(Condition):
    """Matches when the observation is OLDER than `max_age_ms` at context.now.

    It detects staleness; wrap in NotCondition to require freshness. A
    missing field is a non-match (unknown is not stale) — combine with
    ExistsCondition when "missing or stale" is the intent.
    """

    field: str
    max_age_ms: int

    def __post_init__(self) -> None:
        if not self.field:
            raise ValueError("StalenessCondition.field must be non-empty.")
        if self.max_age_ms < 0:
            raise ValueError(f"max_age_ms must be >= 0, got {self.max_age_ms}.")

    def evaluate(self, state: PageState, context: EvaluationContext) -> ConditionResult:
        obs = state.get(self.field)
        if obs is None:
            return _missing(self.field)
        age_ms = (context.now - obs.observed_at).total_seconds() * 1000.0
        matched = age_ms > self.max_age_ms
        return ConditionResult(
            matched=matched,
            reason=(
                f"field '{self.field}': age {age_ms:.0f}ms "
                f"{'exceeds' if matched else 'within'} max {self.max_age_ms}ms"
            ),
        )


def _normalized_children(name: str, children: Sequence[Condition]) -> tuple[Condition, ...]:
    result = tuple(children)
    if not result:
        raise ValueError(f"{name} requires at least one child condition.")
    if any(not isinstance(c, Condition) for c in result):
        raise ValueError(f"{name} children must all be Condition instances.")
    return result


@dataclass(frozen=True)
class AndCondition(Condition):
    """Matches when every child matches. Short-circuits on the first failure;
    the trace contains results for every child evaluated up to that point."""

    children: tuple[Condition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "children", _normalized_children("AndCondition", self.children))

    def evaluate(self, state: PageState, context: EvaluationContext) -> ConditionResult:
        results: list[ConditionResult] = []
        for index, child in enumerate(self.children):
            result = child.evaluate(state, context)
            results.append(result)
            if not result.matched:
                return ConditionResult(
                    matched=False,
                    reason=f"and: child {index + 1}/{len(self.children)} failed",
                    children=tuple(results),
                )
        return ConditionResult(
            matched=True,
            reason=f"and: all {len(self.children)} children matched",
            children=tuple(results),
        )


@dataclass(frozen=True)
class OrCondition(Condition):
    """Matches when any child matches. Short-circuits on the first match."""

    children: tuple[Condition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "children", _normalized_children("OrCondition", self.children))

    def evaluate(self, state: PageState, context: EvaluationContext) -> ConditionResult:
        results: list[ConditionResult] = []
        for index, child in enumerate(self.children):
            result = child.evaluate(state, context)
            results.append(result)
            if result.matched:
                return ConditionResult(
                    matched=True,
                    reason=f"or: child {index + 1}/{len(self.children)} matched",
                    children=tuple(results),
                )
        return ConditionResult(
            matched=False,
            reason=f"or: none of {len(self.children)} children matched",
            children=tuple(results),
        )


@dataclass(frozen=True)
class NotCondition(Condition):
    """Inverts its child. The child's result is kept in the trace."""

    child: Condition

    def __post_init__(self) -> None:
        if not isinstance(self.child, Condition):
            raise ValueError("NotCondition.child must be a Condition instance.")

    def evaluate(self, state: PageState, context: EvaluationContext) -> ConditionResult:
        result = self.child.evaluate(state, context)
        return ConditionResult(
            matched=not result.matched,
            reason=f"not: child {'matched' if result.matched else 'failed'}",
            children=(result,),
        )


__all__ = [
    "AndCondition",
    "ComparisonOp",
    "ConfidenceThresholdCondition",
    "ExistsCondition",
    "NotCondition",
    "OrCondition",
    "StalenessCondition",
    "ValueComparisonCondition",
]
