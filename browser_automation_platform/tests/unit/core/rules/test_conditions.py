from datetime import datetime, timedelta, timezone

import pytest

from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import Observation, PageState
from bap.core.rules.conditions import (
    AndCondition,
    ComparisonOp,
    ConfidenceThresholdCondition,
    ExistsCondition,
    NotCondition,
    OrCondition,
    StalenessCondition,
    ValueComparisonCondition,
)
from bap.core.rules.models import Condition, ConditionResult, EvaluationContext

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)
CTX = EvaluationContext(now=NOW)


def make_state(**specs) -> PageState:
    """make_state(f1="x") or make_state(f1=dict(value=3, confidence=0.4, age_ms=500))."""
    fields = {}
    for name, spec in specs.items():
        if not isinstance(spec, dict):
            spec = {"value": spec}
        fields[name] = Observation(
            name=name,
            kind=ObservationKind.TEXT,
            analyzer="test",
            value=spec.get("value"),
            confidence=spec.get("confidence", 1.0),
            observed_at=NOW - timedelta(milliseconds=spec.get("age_ms", 0)),
        )
    return PageState(profile_id="p1", fields=fields)


class FixedCondition(Condition):
    """Records evaluations; returns a fixed outcome. For composite tests."""

    def __init__(self, matched: bool, reason: str = "fixed"):
        self.matched = matched
        self.reason = reason
        self.calls = 0

    def evaluate(self, state, context):
        self.calls += 1
        return ConditionResult(matched=self.matched, reason=self.reason)


# --- ExistsCondition ----------------------------------------------------------


def test_exists_matches_present_field():
    result = ExistsCondition(field="f1").evaluate(make_state(f1="x"), CTX)

    assert result.matched
    assert "present" in result.reason


def test_exists_fails_for_missing_field_with_reason():
    result = ExistsCondition(field="nope").evaluate(make_state(f1="x"), CTX)

    assert not result.matched
    assert result.reason == "field 'nope' missing"


def test_exists_requires_field_name():
    with pytest.raises(ValueError):
        ExistsCondition(field="")


# --- ValueComparisonCondition ---------------------------------------------------


@pytest.mark.parametrize(
    "op,expected,value,should_match",
    [
        (ComparisonOp.EQUALS, 42, 42, True),
        (ComparisonOp.EQUALS, 42, 41, False),
        (ComparisonOp.NOT_EQUALS, 42, 41, True),
        (ComparisonOp.NOT_EQUALS, 42, 42, False),
        (ComparisonOp.LESS_THAN, 100, 99, True),
        (ComparisonOp.LESS_THAN, 100, 100, False),
        (ComparisonOp.LESS_OR_EQUAL, 100, 100, True),
        (ComparisonOp.LESS_OR_EQUAL, 100, 101, False),
        (ComparisonOp.GREATER_THAN, 10, 11, True),
        (ComparisonOp.GREATER_THAN, 10, 10, False),
        (ComparisonOp.GREATER_OR_EQUAL, 10, 10, True),
        (ComparisonOp.GREATER_OR_EQUAL, 10, 9, False),
        (ComparisonOp.CONTAINS, "Count", "Count: 42", True),
        (ComparisonOp.CONTAINS, "Error", "Count: 42", False),
        (ComparisonOp.MATCHES_REGEX, r"Count:\s*\d+", "Count: 42", True),
        (ComparisonOp.MATCHES_REGEX, r"^\d+$", "Count: 42", False),
    ],
)
def test_value_comparison_operators(op, expected, value, should_match):
    condition = ValueComparisonCondition(field="f1", op=op, expected=expected)

    result = condition.evaluate(make_state(f1=value), CTX)

    assert result.matched is should_match
    assert op.value in result.reason


def test_value_comparison_missing_field_is_non_match():
    condition = ValueComparisonCondition(field="nope", op=ComparisonOp.EQUALS, expected=1)

    result = condition.evaluate(make_state(f1=1), CTX)

    assert not result.matched
    assert "missing" in result.reason


def test_value_comparison_incomparable_types_is_non_match_not_error():
    condition = ValueComparisonCondition(field="f1", op=ComparisonOp.LESS_THAN, expected=5)

    result = condition.evaluate(make_state(f1="abc"), CTX)

    assert not result.matched
    assert "not comparable" in result.reason


def test_value_comparison_none_value_ordered_op_is_non_match():
    condition = ValueComparisonCondition(field="f1", op=ComparisonOp.GREATER_THAN, expected=5)

    result = condition.evaluate(make_state(f1=None), CTX)

    assert not result.matched
    assert "not comparable" in result.reason


def test_value_comparison_none_equals_none_matches():
    condition = ValueComparisonCondition(field="f1", op=ComparisonOp.EQUALS, expected=None)

    assert condition.evaluate(make_state(f1=None), CTX).matched


def test_regex_on_non_string_value_is_non_match():
    condition = ValueComparisonCondition(
        field="f1", op=ComparisonOp.MATCHES_REGEX, expected=r"\d+"
    )

    result = condition.evaluate(make_state(f1=42), CTX)

    assert not result.matched


def test_invalid_regex_fails_at_construction():
    with pytest.raises(ValueError, match="Invalid regex"):
        ValueComparisonCondition(field="f1", op=ComparisonOp.MATCHES_REGEX, expected="(unclosed")


def test_regex_pattern_must_be_string():
    with pytest.raises(ValueError, match="string pattern"):
        ValueComparisonCondition(field="f1", op=ComparisonOp.MATCHES_REGEX, expected=42)


def test_op_must_be_enum():
    with pytest.raises(ValueError, match="ComparisonOp"):
        ValueComparisonCondition(field="f1", op="equals", expected=1)  # type: ignore[arg-type]


# --- ConfidenceThresholdCondition ------------------------------------------------


def test_confidence_at_threshold_matches():
    condition = ConfidenceThresholdCondition(field="f1", minimum=0.8)

    result = condition.evaluate(make_state(f1=dict(value="x", confidence=0.8)), CTX)

    assert result.matched
    assert "0.800" in result.reason


def test_confidence_below_threshold_fails_with_reason():
    condition = ConfidenceThresholdCondition(field="f1", minimum=0.8)

    result = condition.evaluate(make_state(f1=dict(value="x", confidence=0.42)), CTX)

    assert not result.matched
    assert "0.420" in result.reason and "0.800" in result.reason


def test_confidence_missing_field_is_non_match():
    condition = ConfidenceThresholdCondition(field="nope", minimum=0.5)

    assert not condition.evaluate(make_state(f1="x"), CTX).matched


@pytest.mark.parametrize("minimum", [-0.1, 1.1])
def test_confidence_threshold_validated_at_construction(minimum):
    with pytest.raises(ValueError):
        ConfidenceThresholdCondition(field="f1", minimum=minimum)


# --- StalenessCondition -----------------------------------------------------------


def test_observation_older_than_max_age_is_stale():
    condition = StalenessCondition(field="f1", max_age_ms=1000)

    result = condition.evaluate(make_state(f1=dict(value="x", age_ms=1500)), CTX)

    assert result.matched
    assert "exceeds" in result.reason


def test_fresh_observation_is_not_stale():
    condition = StalenessCondition(field="f1", max_age_ms=1000)

    result = condition.evaluate(make_state(f1=dict(value="x", age_ms=200)), CTX)

    assert not result.matched
    assert "within" in result.reason


def test_age_exactly_at_max_is_not_stale():
    condition = StalenessCondition(field="f1", max_age_ms=1000)

    result = condition.evaluate(make_state(f1=dict(value="x", age_ms=1000)), CTX)

    assert not result.matched


def test_staleness_missing_field_is_non_match():
    condition = StalenessCondition(field="nope", max_age_ms=1000)

    result = condition.evaluate(make_state(f1="x"), CTX)

    assert not result.matched
    assert "missing" in result.reason


def test_staleness_uses_context_now_not_wall_clock():
    condition = StalenessCondition(field="f1", max_age_ms=1000)
    state = make_state(f1=dict(value="x", age_ms=0))  # observed exactly at NOW
    later = EvaluationContext(now=NOW + timedelta(seconds=5))

    assert not condition.evaluate(state, CTX).matched
    assert condition.evaluate(state, later).matched


def test_negative_max_age_rejected():
    with pytest.raises(ValueError):
        StalenessCondition(field="f1", max_age_ms=-1)


# --- Composites --------------------------------------------------------------------


def test_and_matches_when_all_children_match():
    result = AndCondition(children=(FixedCondition(True), FixedCondition(True))).evaluate(
        make_state(), CTX
    )

    assert result.matched
    assert result.reason == "and: all 2 children matched"
    assert len(result.children) == 2


def test_and_fails_and_short_circuits_on_first_failure():
    first = FixedCondition(True)
    failing = FixedCondition(False)
    never_reached = FixedCondition(True)

    result = AndCondition(children=(first, failing, never_reached)).evaluate(make_state(), CTX)

    assert not result.matched
    assert result.reason == "and: child 2/3 failed"
    assert len(result.children) == 2
    assert never_reached.calls == 0


def test_or_matches_and_short_circuits_on_first_match():
    failing = FixedCondition(False)
    matching = FixedCondition(True)
    never_reached = FixedCondition(True)

    result = OrCondition(children=(failing, matching, never_reached)).evaluate(make_state(), CTX)

    assert result.matched
    assert result.reason == "or: child 2/3 matched"
    assert never_reached.calls == 0


def test_or_fails_when_no_child_matches():
    result = OrCondition(children=(FixedCondition(False), FixedCondition(False))).evaluate(
        make_state(), CTX
    )

    assert not result.matched
    assert result.reason == "or: none of 2 children matched"
    assert len(result.children) == 2


def test_not_inverts_and_keeps_child_trace():
    result = NotCondition(child=FixedCondition(True, reason="inner detail")).evaluate(
        make_state(), CTX
    )

    assert not result.matched
    assert result.children[0].reason == "inner detail"

    assert NotCondition(child=FixedCondition(False)).evaluate(make_state(), CTX).matched


def test_nested_composite_evaluates_and_traces_recursively():
    # (f1 exists AND (f1 >= 100 OR NOT confidence(f1) >= 0.9))
    state = make_state(f1=dict(value=42, confidence=0.5))
    condition = AndCondition(
        children=(
            ExistsCondition(field="f1"),
            OrCondition(
                children=(
                    ValueComparisonCondition(
                        field="f1", op=ComparisonOp.GREATER_OR_EQUAL, expected=100
                    ),
                    NotCondition(child=ConfidenceThresholdCondition(field="f1", minimum=0.9)),
                )
            ),
        )
    )

    result = condition.evaluate(state, CTX)

    assert result.matched  # exists=yes; 42>=100 no, but confidence 0.5 < 0.9 so NOT matches
    or_result = result.children[1]
    assert or_result.reason == "or: child 2/2 matched"
    not_result = or_result.children[1]
    assert not_result.children[0].reason.startswith("field 'f1': confidence 0.500")


def test_reason_trace_shows_why_a_nested_composite_failed():
    state = make_state(f1=dict(value="Count: 42"))
    condition = AndCondition(
        children=(
            ExistsCondition(field="f1"),
            ValueComparisonCondition(field="f1", op=ComparisonOp.CONTAINS, expected="Error"),
        )
    )

    result = condition.evaluate(state, CTX)

    assert not result.matched
    assert result.reason == "and: child 2/2 failed"
    assert "'Error'" in result.children[1].reason
    assert "failed" in result.children[1].reason


@pytest.mark.parametrize("composite", [AndCondition, OrCondition])
def test_composites_require_children(composite):
    with pytest.raises(ValueError, match="at least one child"):
        composite(children=())


@pytest.mark.parametrize("composite", [AndCondition, OrCondition])
def test_composites_reject_non_condition_children(composite):
    with pytest.raises(ValueError, match="Condition instances"):
        composite(children=(FixedCondition(True), "f1 == 2"))


def test_not_rejects_non_condition_child():
    with pytest.raises(ValueError, match="Condition instance"):
        NotCondition(child="f1 == 2")  # type: ignore[arg-type]


def test_single_child_composites_are_allowed():
    assert AndCondition(children=(FixedCondition(True),)).evaluate(make_state(), CTX).matched
    assert OrCondition(children=(FixedCondition(True),)).evaluate(make_state(), CTX).matched


def test_conditions_are_reusable_and_stateless_across_states():
    condition = ValueComparisonCondition(field="f1", op=ComparisonOp.LESS_THAN, expected=100)

    assert condition.evaluate(make_state(f1=50), CTX).matched
    assert not condition.evaluate(make_state(f1=150), CTX).matched
    assert condition.evaluate(make_state(f1=50), CTX).matched
