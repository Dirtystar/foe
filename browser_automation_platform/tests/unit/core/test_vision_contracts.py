from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import ImageData, Observation, Rect
from bap.core.ports.vision_analyzer_port import AnalyzerContext, VisionAnalyzerPort


def make_observation(**overrides):
    defaults = dict(
        name="header_region.text",
        kind=ObservationKind.TEXT,
        analyzer="stub_ocr",
        value="Count: 42",
        confidence=0.9,
        region=Rect(x=5, y=10, w=100, h=20),
    )
    defaults.update(overrides)
    return Observation(**defaults)


def make_image() -> ImageData:
    return ImageData(
        data=b"\x89PNG\r\n\x1a\n",
        width=100,
        height=20,
        tab_id="tab1",
        captured_at=datetime.now(timezone.utc),
    )


# --- Observation validation -------------------------------------------------


def test_valid_observation_constructs():
    obs = make_observation()

    assert obs.kind is ObservationKind.TEXT
    assert obs.value == "Count: 42"
    assert obs.confidence == 0.9
    assert obs.region == Rect(x=5, y=10, w=100, h=20)
    assert obs.analyzer == "stub_ocr"
    assert obs.observed_at.tzinfo is not None


def test_observation_defaults_are_minimal():
    obs = Observation(name="x", kind=ObservationKind.CUSTOM, analyzer="plugin")

    assert obs.value is None
    assert obs.confidence == 1.0
    assert obs.region is None
    assert dict(obs.attributes) == {}


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 5.0])
def test_confidence_outside_unit_interval_is_rejected(confidence):
    with pytest.raises(ValueError, match="confidence"):
        make_observation(confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_confidence_boundaries_are_accepted(confidence):
    assert make_observation(confidence=confidence).confidence == confidence


def test_empty_name_is_rejected():
    with pytest.raises(ValueError, match="name"):
        make_observation(name="")


def test_empty_analyzer_is_rejected():
    with pytest.raises(ValueError, match="analyzer"):
        make_observation(analyzer="")


def test_kind_must_be_observation_kind_enum():
    with pytest.raises(ValueError, match="kind"):
        make_observation(kind="text")


# --- Immutability -----------------------------------------------------------


def test_observation_fields_cannot_be_reassigned():
    obs = make_observation()

    with pytest.raises(FrozenInstanceError):
        obs.value = "tampered"  # type: ignore[misc]


def test_observation_attributes_mapping_is_read_only():
    obs = make_observation(attributes={"lang": "eng"})

    assert obs.attributes["lang"] == "eng"
    with pytest.raises(TypeError):
        obs.attributes["lang"] = "ces"  # type: ignore[index]


def test_attributes_are_copied_from_the_caller_dict():
    source = {"threshold": 0.8}
    obs = make_observation(attributes=source)
    source["threshold"] = 0.1

    assert obs.attributes["threshold"] == 0.8


# --- AnalyzerContext ---------------------------------------------------------


def test_analyzer_context_defaults():
    ctx = AnalyzerContext(profile_id="profile_01")

    assert ctx.target_name is None
    assert dict(ctx.settings) == {}


def test_analyzer_context_requires_profile_id():
    with pytest.raises(ValueError, match="profile_id"):
        AnalyzerContext(profile_id="")


def test_analyzer_context_settings_are_read_only():
    ctx = AnalyzerContext(profile_id="p1", settings={"lang": "eng"})

    with pytest.raises(TypeError):
        ctx.settings["lang"] = "ces"  # type: ignore[index]


# --- Analyzer contract --------------------------------------------------------


class StubAnalyzer(VisionAnalyzerPort):
    """Minimal conforming implementation used to exercise the contract."""

    @property
    def name(self) -> str:
        return "stub"

    async def analyze(self, image, context):
        return [
            Observation(
                name=f"{context.target_name}.stubbed",
                kind=ObservationKind.CUSTOM,
                analyzer=self.name,
                value=True,
            )
        ]


def test_port_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        VisionAnalyzerPort()  # type: ignore[abstract]


def test_incomplete_implementation_cannot_be_instantiated():
    class MissingAnalyze(VisionAnalyzerPort):
        @property
        def name(self) -> str:
            return "broken"

    with pytest.raises(TypeError):
        MissingAnalyze()  # type: ignore[abstract]


async def test_conforming_analyzer_produces_valid_observations():
    analyzer = StubAnalyzer()
    ctx = AnalyzerContext(profile_id="p1", target_name="header_region")

    observations = await analyzer.analyze(make_image(), ctx)

    assert len(observations) == 1
    obs = observations[0]
    assert obs.name == "header_region.stubbed"
    assert obs.analyzer == "stub"
    assert obs.kind is ObservationKind.CUSTOM
