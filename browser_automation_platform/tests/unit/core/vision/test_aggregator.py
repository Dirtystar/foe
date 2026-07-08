from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import Observation, PageState
from bap.core.vision.aggregator import Aggregator

T0 = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def obs(name: str, value, *, confidence=0.5, analyzer="a", at=T0) -> Observation:
    return Observation(
        name=name,
        kind=ObservationKind.TEXT,
        analyzer=analyzer,
        value=value,
        confidence=confidence,
        observed_at=at,
    )


def test_each_field_name_becomes_one_page_state_field():
    state = Aggregator().build_page_state("p1", [obs("f1", "x"), obs("f2", "y")])

    assert state.profile_id == "p1"
    assert state.has("f1") and state.has("f2")
    assert state.value_of("f1") == "x"
    assert state.value_of("f2") == "y"


def test_higher_confidence_wins_conflicts():
    low = obs("f1", "low", confidence=0.4, analyzer="ocr")
    high = obs("f1", "high", confidence=0.9, analyzer="ai")

    state = Aggregator().build_page_state("p1", [low, high])

    assert state.value_of("f1") == "high"
    assert state.get("f1").analyzer == "ai"


def test_order_of_input_does_not_change_the_winner():
    low = obs("f1", "low", confidence=0.4)
    high = obs("f1", "high", confidence=0.9)

    forward = Aggregator().build_page_state("p1", [low, high])
    backward = Aggregator().build_page_state("p1", [high, low])

    assert forward.value_of("f1") == backward.value_of("f1") == "high"


def test_equal_confidence_newest_observation_wins():
    older = obs("f1", "older", at=T0)
    newer = obs("f1", "newer", at=T0 + timedelta(seconds=1))

    state = Aggregator().build_page_state("p1", [newer, older])

    assert state.value_of("f1") == "newer"


def test_no_observations_builds_empty_page_state():
    state = Aggregator().build_page_state("p1", [])

    assert dict(state.fields) == {}
    assert not state.has("anything")
    assert state.value_of("anything") is None


def test_page_state_is_immutable():
    state = Aggregator().build_page_state("p1", [obs("f1", "x")])

    with pytest.raises(FrozenInstanceError):
        state.profile_id = "other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        state.fields["f1"] = None  # type: ignore[index]


def test_page_state_requires_profile_id():
    with pytest.raises(ValueError, match="profile_id"):
        PageState(profile_id="")


def test_page_state_timestamps_are_utc():
    state = Aggregator().build_page_state("p1", [])

    assert state.created_at.tzinfo is not None
