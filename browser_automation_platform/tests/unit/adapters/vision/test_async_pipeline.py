import threading
import time
from datetime import datetime, timezone

import pytest

from bap.adapters.vision.async_pipeline import AsyncVisionPipeline
from bap.core.domain.enums import ObservationKind
from bap.core.domain.models import ImageData, Observation
from bap.core.ports.vision_analyzer_port import (
    AnalyzerContext,
    VisionAnalyzerError,
    VisionAnalyzerPort,
)
from bap.core.vision.pipeline import AnalyzerBinding


def make_image() -> ImageData:
    return ImageData(
        data=b"\x89PNG\r\n\x1a\n", width=10, height=10, tab_id="t", captured_at=datetime.now(timezone.utc)
    )


CTX = AnalyzerContext(profile_id="p1", target_name="t")


class ListAnalyzer(VisionAnalyzerPort):
    def __init__(self, name, payload):
        self._name = name
        self.payload = payload

    @property
    def name(self):
        return self._name

    async def analyze(self, image, context):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def obs(name, analyzer):
    return Observation(name=name, kind=ObservationKind.TEXT, analyzer=analyzer, value="v")


def bind(analyzer):
    return AnalyzerBinding(analyzer=analyzer, context=CTX)


@pytest.fixture
def executor():
    from concurrent.futures import ThreadPoolExecutor

    ex = ThreadPoolExecutor(max_workers=4, thread_name_prefix="test-vision")
    yield ex
    ex.shutdown(wait=True)


async def test_observations_preserve_binding_order(executor):
    a = ListAnalyzer("a", [obs("f1", "a")])
    b = ListAnalyzer("b", [obs("f2", "b"), obs("f3", "b")])
    pipeline = AsyncVisionPipeline([bind(a), bind(b)], executor=executor)

    result = await pipeline.run(make_image())

    assert result.fully_succeeded
    assert [o.name for o in result.observations] == ["f1", "f2", "f3"]


async def test_ordering_preserved_despite_finish_order(executor):
    # 'slow' returns first-in-binding-order but finishes last
    class Slow(ListAnalyzer):
        async def analyze(self, image, context):
            time.sleep(0.05)
            return [obs("slow", "slow")]

    pipeline = AsyncVisionPipeline(
        [bind(Slow("slow", None)), bind(ListAnalyzer("fast", [obs("fast", "fast")]))],
        executor=executor,
    )

    result = await pipeline.run(make_image())

    assert [o.name for o in result.observations] == ["slow", "fast"]


async def test_failure_is_contained_as_analyzer_failure(executor):
    ok = ListAnalyzer("ok", [obs("f1", "ok")])
    boom = ListAnalyzer("boom", RuntimeError("cv2 exploded"))
    pipeline = AsyncVisionPipeline([bind(boom), bind(ok)], executor=executor)

    result = await pipeline.run(make_image())

    assert [o.name for o in result.observations] == ["f1"]
    assert len(result.failures) == 1
    assert result.failures[0].analyzer == "boom"
    assert isinstance(result.failures[0].error, RuntimeError)


async def test_non_observation_return_becomes_failure(executor):
    rogue = ListAnalyzer("rogue", ["not-an-observation"])
    pipeline = AsyncVisionPipeline([bind(rogue)], executor=executor)

    result = await pipeline.run(make_image())

    assert result.observations == ()
    assert isinstance(result.failures[0].error, VisionAnalyzerError)


async def test_analyzers_run_on_worker_threads_not_the_loop(executor):
    """The analyzer must execute off the main thread."""
    seen_threads = []

    class ThreadProbe(ListAnalyzer):
        async def analyze(self, image, context):
            seen_threads.append(threading.current_thread().name)
            return []

    pipeline = AsyncVisionPipeline([bind(ThreadProbe("probe", None))], executor=executor)
    await pipeline.run(make_image())

    assert seen_threads
    assert seen_threads[0].startswith("test-vision")  # ran in the pool


async def test_max_workers_limit_is_respected():
    from concurrent.futures import ThreadPoolExecutor

    concurrency = {"current": 0, "max": 0}
    lock = threading.Lock()

    class Tracked(ListAnalyzer):
        async def analyze(self, image, context):
            with lock:
                concurrency["current"] += 1
                concurrency["max"] = max(concurrency["max"], concurrency["current"])
            time.sleep(0.02)
            with lock:
                concurrency["current"] -= 1
            return []

    ex = ThreadPoolExecutor(max_workers=2)
    try:
        pipeline = AsyncVisionPipeline(
            [bind(Tracked(f"a{i}", None)) for i in range(6)], executor=ex
        )
        await pipeline.run(make_image())
    finally:
        ex.shutdown(wait=True)

    assert concurrency["max"] <= 2  # never exceeded the pool size


async def test_empty_pipeline_returns_empty_result(executor):
    result = await AsyncVisionPipeline([], executor=executor).run(make_image())

    assert result.fully_succeeded
    assert result.observations == ()
