from datetime import datetime, timedelta, timezone

import pytest

from bap.core.domain.models import ActionRequest, PageState
from bap.core.rules.models import Condition, ConditionResult, EvaluationContext, Rule
from bap.core.rules.rule_engine import RuleEngine, RuleStatus

T0 = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)
STATE = PageState(profile_id="p1")


def at(ms: int) -> EvaluationContext:
    return EvaluationContext(now=T0 + timedelta(milliseconds=ms))


class FixedCondition(Condition):
    def __init__(self, matched: bool, reason: str = "fixed"):
        self.matched = matched
        self.reason = reason
        self.calls = 0

    def evaluate(self, state, context):
        self.calls += 1
        return ConditionResult(matched=self.matched, reason=self.reason)


class RaisingCondition(Condition):
    def evaluate(self, state, context):
        raise RuntimeError("plugin bug")


def rule(rule_id: str, condition: Condition, *, enabled=True, cooldown_ms=0, n_actions=1) -> Rule:
    actions = tuple(
        ActionRequest(action_type="click", params={"target": f"#{rule_id}-{i}"})
        for i in range(n_actions)
    )
    return Rule(
        id=rule_id, condition=condition, actions=actions, enabled=enabled, cooldown_ms=cooldown_ms
    )


# --- Matching and action collection -------------------------------------------


def test_matched_rule_emits_actions_stamped_with_rule_id():
    engine = RuleEngine([rule("r1", FixedCondition(True))])

    report = engine.evaluate(STATE, at(0))

    assert report.results[0].status is RuleStatus.MATCHED
    assert len(report.actions) == 1
    assert report.actions[0].rule_id == "r1"
    assert report.actions[0].action_type == "click"
    assert report.actions[0].params["target"] == "#r1-0"  # params survive stamping


def test_multiple_matching_rules_collect_actions_in_declaration_order():
    engine = RuleEngine(
        [
            rule("r1", FixedCondition(True), n_actions=2),
            rule("r2", FixedCondition(False)),
            rule("r3", FixedCondition(True)),
        ]
    )

    report = engine.evaluate(STATE, at(0))

    assert [r.status for r in report.results] == [
        RuleStatus.MATCHED,
        RuleStatus.NOT_MATCHED,
        RuleStatus.MATCHED,
    ]
    assert [a.rule_id for a in report.actions] == ["r1", "r1", "r3"]


def test_every_rule_gets_a_result_even_when_nothing_matches():
    engine = RuleEngine([rule("r1", FixedCondition(False)), rule("r2", FixedCondition(False))])

    report = engine.evaluate(STATE, at(0))

    assert len(report.results) == 2
    assert report.actions == ()


def test_rule_templates_are_not_mutated_by_stamping():
    r = rule("r1", FixedCondition(True))
    engine = RuleEngine([r])

    engine.evaluate(STATE, at(0))

    assert r.actions[0].rule_id is None  # original template untouched


# --- Disabled rules -------------------------------------------------------------


def test_disabled_rule_is_skipped_without_evaluating_its_condition():
    condition = FixedCondition(True)
    engine = RuleEngine([rule("r1", condition, enabled=False)])

    report = engine.evaluate(STATE, at(0))

    assert report.results[0].status is RuleStatus.DISABLED
    assert report.results[0].condition_result is None
    assert report.actions == ()
    assert condition.calls == 0


# --- Cooldown --------------------------------------------------------------------


def test_cooldown_suppresses_refire_within_window():
    condition = FixedCondition(True)
    engine = RuleEngine([rule("r1", condition, cooldown_ms=1000)])

    first = engine.evaluate(STATE, at(0))
    second = engine.evaluate(STATE, at(500))

    assert first.results[0].status is RuleStatus.MATCHED
    assert second.results[0].status is RuleStatus.ON_COOLDOWN
    assert second.results[0].condition_result is None
    assert second.actions == ()
    assert condition.calls == 1  # condition not evaluated while cooling down


def test_rule_fires_again_once_cooldown_has_elapsed():
    engine = RuleEngine([rule("r1", FixedCondition(True), cooldown_ms=1000)])

    engine.evaluate(STATE, at(0))
    boundary = engine.evaluate(STATE, at(1000))

    assert boundary.results[0].status is RuleStatus.MATCHED


def test_cooldown_starts_only_on_match_not_on_evaluation():
    condition = FixedCondition(False)
    engine = RuleEngine([rule("r1", condition, cooldown_ms=10_000)])

    engine.evaluate(STATE, at(0))
    condition.matched = True
    report = engine.evaluate(STATE, at(1))

    assert report.results[0].status is RuleStatus.MATCHED


def test_zero_cooldown_fires_every_cycle():
    engine = RuleEngine([rule("r1", FixedCondition(True), cooldown_ms=0)])

    assert engine.evaluate(STATE, at(0)).results[0].status is RuleStatus.MATCHED
    assert engine.evaluate(STATE, at(1)).results[0].status is RuleStatus.MATCHED


def test_cooldowns_are_tracked_per_rule():
    engine = RuleEngine(
        [
            rule("fast", FixedCondition(True), cooldown_ms=100),
            rule("slow", FixedCondition(True), cooldown_ms=5000),
        ]
    )

    engine.evaluate(STATE, at(0))
    report = engine.evaluate(STATE, at(200))

    assert report.results[0].status is RuleStatus.MATCHED  # fast: cooldown elapsed
    assert report.results[1].status is RuleStatus.ON_COOLDOWN  # slow: still cooling


def test_cooldown_uses_context_now_not_wall_clock():
    engine = RuleEngine([rule("r1", FixedCondition(True), cooldown_ms=1000)])

    engine.evaluate(STATE, at(0))
    # Wall-clock time barely advanced, but the injected clock jumped 2s.
    report = engine.evaluate(STATE, at(2000))

    assert report.results[0].status is RuleStatus.MATCHED


# --- Trace preservation -----------------------------------------------------------


def test_not_matched_result_preserves_the_condition_trace():
    engine = RuleEngine([rule("r1", FixedCondition(False, reason="field 'x' missing"))])

    report = engine.evaluate(STATE, at(0))

    result = report.results[0]
    assert result.status is RuleStatus.NOT_MATCHED
    assert result.condition_result.reason == "field 'x' missing"


def test_matched_result_also_preserves_the_trace():
    engine = RuleEngine([rule("r1", FixedCondition(True, reason="all good"))])

    report = engine.evaluate(STATE, at(0))

    assert report.results[0].condition_result.reason == "all good"


# --- Error containment --------------------------------------------------------------


def test_raising_condition_becomes_error_result_and_others_still_run():
    engine = RuleEngine([rule("bad", RaisingCondition()), rule("good", FixedCondition(True))])

    report = engine.evaluate(STATE, at(0))

    bad, good = report.results
    assert bad.status is RuleStatus.ERROR
    assert "plugin bug" in bad.condition_result.reason
    assert good.status is RuleStatus.MATCHED
    assert [a.rule_id for a in report.actions] == ["good"]


def test_error_rule_emits_no_actions_and_starts_no_cooldown():
    engine = RuleEngine([rule("bad", RaisingCondition(), cooldown_ms=10_000)])

    first = engine.evaluate(STATE, at(0))
    second = engine.evaluate(STATE, at(1))

    assert first.results[0].status is RuleStatus.ERROR
    assert second.results[0].status is RuleStatus.ERROR  # not ON_COOLDOWN
    assert first.actions == second.actions == ()


# --- Construction and determinism -----------------------------------------------------


def test_duplicate_rule_ids_rejected_at_construction():
    with pytest.raises(ValueError, match="Duplicate rule id"):
        RuleEngine([rule("r1", FixedCondition(True)), rule("r1", FixedCondition(False))])


def test_empty_rule_pack_produces_empty_report():
    report = RuleEngine([]).evaluate(STATE, at(0))

    assert report.results == ()
    assert report.actions == ()


def test_evaluation_is_deterministic_for_identical_inputs():
    def build():
        return RuleEngine(
            [rule("r1", FixedCondition(True)), rule("r2", FixedCondition(False))]
        ).evaluate(STATE, at(0))

    first, second = build(), build()

    assert [r.status for r in first.results] == [r.status for r in second.results]
    assert [a.rule_id for a in first.actions] == [a.rule_id for a in second.actions]


def test_context_defaults_to_now_when_omitted():
    engine = RuleEngine([rule("r1", FixedCondition(True))])

    report = engine.evaluate(STATE)

    assert report.results[0].status is RuleStatus.MATCHED
