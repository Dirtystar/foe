from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import ActionRequest, Observation, PageState
from bap.core.rules.models import Condition, ConditionResult, EvaluationContext, Rule


class StubCondition(Condition):
    """Configurable pure condition used to exercise the contracts."""

    def __init__(self, matched: bool, reason: str = ""):
        self._result = ConditionResult(matched=matched, reason=reason)
        self.seen: list[tuple[PageState, EvaluationContext]] = []

    def evaluate(self, state, context):
        self.seen.append((state, context))
        return self._result


def make_state(**fields) -> PageState:
    observations = {
        name: Observation(name=name, kind=ObservationKind.TEXT, analyzer="t", value=value)
        for name, value in fields.items()
    }
    return PageState(profile_id="p1", fields=observations)


def click(rule_id=None) -> ActionRequest:
    return ActionRequest(action_type="click", params={"target": "#btn"}, rule_id=rule_id)


# --- ActionRequest ------------------------------------------------------------


def test_action_request_holds_type_params_and_provenance():
    request = ActionRequest(
        action_type="navigate", params={"url": "https://example.com"}, rule_id="r1"
    )

    assert request.action_type == "navigate"
    assert request.params["url"] == "https://example.com"
    assert request.rule_id == "r1"


def test_action_request_requires_action_type():
    with pytest.raises(ValueError, match="action_type"):
        ActionRequest(action_type="")


def test_action_request_is_immutable_including_params():
    request = click()

    with pytest.raises(FrozenInstanceError):
        request.action_type = "type"  # type: ignore[misc]
    with pytest.raises(TypeError):
        request.params["target"] = "#other"  # type: ignore[index]


def test_action_request_params_are_copied_from_caller():
    source = {"url": "https://a.example"}
    request = ActionRequest(action_type="navigate", params=source)
    source["url"] = "https://evil.example"

    assert request.params["url"] == "https://a.example"


# --- ConditionResult ----------------------------------------------------------


def test_condition_result_is_truthy_on_match():
    assert ConditionResult(matched=True)
    assert not ConditionResult(matched=False)


def test_condition_result_carries_reason_and_children():
    child = ConditionResult(matched=False, reason="field 'x' missing")
    parent = ConditionResult(matched=False, reason="all() failed", children=(child,))

    assert parent.children[0].reason == "field 'x' missing"


def test_condition_result_is_immutable():
    result = ConditionResult(matched=True)

    with pytest.raises(FrozenInstanceError):
        result.matched = False  # type: ignore[misc]


# --- Condition contract ---------------------------------------------------------


def test_condition_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Condition()  # type: ignore[abstract]


def test_condition_receives_state_and_shared_context():
    condition = StubCondition(matched=True, reason="ok")
    state = make_state(f1="x")
    context = EvaluationContext(now=datetime(2026, 7, 8, tzinfo=timezone.utc))

    result = condition.evaluate(state, context)

    assert result.matched and result.reason == "ok"
    assert condition.seen == [(state, context)]


def test_evaluation_context_defaults_to_utc_now():
    context = EvaluationContext()

    assert context.now.tzinfo is not None


# --- Rule -----------------------------------------------------------------------


def test_valid_rule_constructs_with_defaults():
    rule = Rule(id="r1", condition=StubCondition(True), actions=(click(),))

    assert rule.enabled
    assert rule.cooldown_ms == 0
    assert len(rule.actions) == 1


def test_rule_accepts_action_list_and_normalizes_to_tuple():
    rule = Rule(id="r1", condition=StubCondition(True), actions=[click(), click()])

    assert isinstance(rule.actions, tuple)
    assert len(rule.actions) == 2


def test_rule_requires_id():
    with pytest.raises(ValueError, match="id"):
        Rule(id="", condition=StubCondition(True), actions=(click(),))


def test_rule_requires_a_real_condition():
    with pytest.raises(ValueError, match="condition"):
        Rule(id="r1", condition="field == 1", actions=(click(),))  # type: ignore[arg-type]


def test_rule_requires_at_least_one_action():
    with pytest.raises(ValueError, match="at least one action"):
        Rule(id="r1", condition=StubCondition(True), actions=())


def test_rule_rejects_non_action_request_actions():
    with pytest.raises(ValueError, match="ActionRequest"):
        Rule(id="r1", condition=StubCondition(True), actions=("click",))  # type: ignore[arg-type]


def test_rule_rejects_negative_cooldown():
    with pytest.raises(ValueError, match="cooldown_ms"):
        Rule(id="r1", condition=StubCondition(True), actions=(click(),), cooldown_ms=-1)


def test_rule_is_immutable():
    rule = Rule(id="r1", condition=StubCondition(True), actions=(click(),))

    with pytest.raises(FrozenInstanceError):
        rule.enabled = False  # type: ignore[misc]
