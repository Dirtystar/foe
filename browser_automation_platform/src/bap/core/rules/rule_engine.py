"""RuleEngine: evaluates a rule pack against one PageState snapshot.

The engine is the only stateful piece of the rules layer, and its state is
exactly one thing: when each rule last fired (for cooldown enforcement),
in memory only. Rules stay immutable, conditions stay stateless, and nothing
here executes actions — the output is data for the ActionExecutor.

One engine instance belongs to one tab: rule packs may be shared across
tabs, but cooldowns are per-tab runtime facts, so each TabSession gets its
own engine over the same (immutable, shareable) rules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum

from bap.core.domain.models import ActionRequest, PageState
from bap.core.rules.models import ConditionResult, EvaluationContext, Rule


class RuleStatus(Enum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    DISABLED = "disabled"
    ON_COOLDOWN = "on_cooldown"
    ERROR = "error"


@dataclass(frozen=True)
class RuleEvaluationResult:
    """What happened to one rule during one evaluation cycle.

    `condition_result` preserves the full reason trace for MATCHED /
    NOT_MATCHED / ERROR; it is None when the condition was never evaluated
    (DISABLED, ON_COOLDOWN). `actions` is non-empty only for MATCHED.
    """

    rule_id: str
    status: RuleStatus
    condition_result: ConditionResult | None = None
    actions: tuple[ActionRequest, ...] = ()


@dataclass(frozen=True)
class EvaluationReport:
    """One result per rule (in declaration order) plus the collected actions
    of every matched rule, ready for the ActionExecutor."""

    results: tuple[RuleEvaluationResult, ...]
    actions: tuple[ActionRequest, ...]


class RuleEngine:
    def __init__(self, rules: Sequence[Rule]) -> None:
        self._rules = tuple(rules)
        seen: set[str] = set()
        for rule in self._rules:
            if rule.id in seen:
                raise ValueError(f"Duplicate rule id '{rule.id}' in rule pack.")
            seen.add(rule.id)
        self._last_fired: dict[str, datetime] = {}

    def evaluate(
        self, state: PageState, context: EvaluationContext | None = None
    ) -> EvaluationReport:
        """Evaluate every rule, in declaration order, against one snapshot.

        Cooldown and staleness both measure against context.now, so a whole
        cycle sees one consistent instant. A rule's cooldown starts only when
        it matches; while cooling down its condition is not evaluated at all.
        """
        context = context if context is not None else EvaluationContext()

        results: list[RuleEvaluationResult] = []
        actions: list[ActionRequest] = []

        for rule in self._rules:
            result = self._evaluate_rule(rule, state, context)
            results.append(result)
            actions.extend(result.actions)

        return EvaluationReport(results=tuple(results), actions=tuple(actions))

    def _evaluate_rule(
        self, rule: Rule, state: PageState, context: EvaluationContext
    ) -> RuleEvaluationResult:
        if not rule.enabled:
            return RuleEvaluationResult(rule_id=rule.id, status=RuleStatus.DISABLED)

        if self._on_cooldown(rule, context.now):
            return RuleEvaluationResult(rule_id=rule.id, status=RuleStatus.ON_COOLDOWN)

        try:
            condition_result = rule.condition.evaluate(state, context)
        except Exception as exc:
            # Built-in conditions are total; this guards plugin conditions so
            # one broken rule cannot take down the whole evaluation cycle.
            return RuleEvaluationResult(
                rule_id=rule.id,
                status=RuleStatus.ERROR,
                condition_result=ConditionResult(
                    matched=False,
                    reason=f"condition raised {type(exc).__name__}: {exc}",
                ),
            )

        if not condition_result.matched:
            return RuleEvaluationResult(
                rule_id=rule.id,
                status=RuleStatus.NOT_MATCHED,
                condition_result=condition_result,
            )

        self._last_fired[rule.id] = context.now
        stamped = tuple(replace(action, rule_id=rule.id) for action in rule.actions)
        return RuleEvaluationResult(
            rule_id=rule.id,
            status=RuleStatus.MATCHED,
            condition_result=condition_result,
            actions=stamped,
        )

    def _on_cooldown(self, rule: Rule, now: datetime) -> bool:
        if rule.cooldown_ms <= 0:
            return False
        last = self._last_fired.get(rule.id)
        if last is None:
            return False
        elapsed_ms = (now - last).total_seconds() * 1000.0
        return elapsed_ms < rule.cooldown_ms


__all__ = ["EvaluationReport", "RuleEngine", "RuleEvaluationResult", "RuleStatus"]
