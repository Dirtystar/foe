import asyncio
from datetime import datetime, timezone

import pytest

from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import ImageData, Observation
from bap.core.ports.vision_analyzer_port import (
    AnalyzerContext,
    VisionAnalyzerError,
    VisionAnalyzerPort,
)
from bap.core.vision.pipeline import AnalyzerBinding, VisionPipeline


def make_image() -> ImageData:
    return ImageData(
        data=b"\x89PNG\r\n\x1a\n",
        width=100,
        height=20,
        tab_id="tab1",
        captured_at=datetime.now(timezone.utc),
    )


CTX = AnalyzerContext(profile_id="p1", target_name="header")


class ListAnalyzer(VisionAnalyzerPort):
    """Returns a fixed payload; records that it was called."""

    def __init__(self, name: str, payload):
        self._name = name
        self.payload = payload
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def analyze(self, image, context):
        self.calls += 1
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def obs(name: str, analyzer: str, **overrides) -> Observation:
    defaults = dict(kind=ObservationKind.TEXT, value="v", confidence=0.5)
    defaults.update(overrides)
    return Observation(name=name, analyzer=analyzer, **defaults)


def bind(analyzer) -> AnalyzerBinding:
    return AnalyzerBinding(analyzer=analyzer, context=CTX)


async def test_multiple_analyzers_contribute_observations_in_binding_order():
    a = ListAnalyzer("a", [obs("f1", "a")])
    b = ListAnalyzer("b", [obs("f2", "b"), obs("f3", "b")])
    pipeline = VisionPipeline([bind(a), bind(b)])

    result = await pipeline.run(make_image())

    assert result.fully_succeeded
    assert [o.name for o in result.observations] == ["f1", "f2", "f3"]
    assert a.calls == 1 and b.calls == 1


async def test_analyzers_run_concurrently():
    """First analyzer only finishes once the second has started — deadlocks
    (and times out) if the pipeline ran them sequentially."""
    second_started = asyncio.Event()

    class Waits(ListAnalyzer):
        async def analyze(self, image, context):
            await second_started.wait()
            return []

    class Signals(ListAnalyzer):
        async def analyze(self, image, context):
            second_started.set()
            return []

    pipeline = VisionPipeline([bind(Waits("w", [])), bind(Signals("s", []))])

    result = await asyncio.wait_for(pipeline.run(make_image()), timeout=2.0)

    assert result.fully_succeeded


async def test_one_failing_analyzer_does_not_stop_the_others():
    ok = ListAnalyzer("ok", [obs("f1", "ok")])
    boom = ListAnalyzer("boom", RuntimeError("lens cap on"))
    pipeline = VisionPipeline([bind(boom), bind(ok)])

    result = await pipeline.run(make_image())

    assert not result.fully_succeeded
    assert [o.name for o in result.observations] == ["f1"]
    assert len(result.failures) == 1
    assert result.failures[0].analyzer == "boom"
    assert isinstance(result.failures[0].error, RuntimeError)


async def test_analyzer_returning_non_observations_is_recorded_as_failure():
    rogue = ListAnalyzer("rogue", ["not-an-observation"])
    pipeline = VisionPipeline([bind(rogue)])

    result = await pipeline.run(make_image())

    assert result.observations == ()
    assert len(result.failures) == 1
    assert isinstance(result.failures[0].error, VisionAnalyzerError)


async def test_empty_analyzer_results_are_valid():
    quiet = ListAnalyzer("quiet", [])
    pipeline = VisionPipeline([bind(quiet)])

    result = await pipeline.run(make_image())

    assert result.fully_succeeded
    assert result.observations == ()


async def test_pipeline_with_no_bindings_returns_empty_result():
    pipeline = VisionPipeline([])

    result = await pipeline.run(make_image())

    assert result.fully_succeeded
    assert result.observations == ()
    assert pipeline.analyzer_names == ()
