"""Off-loop vision execution.

AsyncVisionPipeline is a drop-in replacement for VisionPipeline (it subclasses
it, so CaptureBinding, TabSession, and VisionAnalyzerPort are all unchanged).
Instead of awaiting analyzers on the event loop, it runs each one in a shared
ThreadPoolExecutor via run_in_executor, so CPU-bound OCR/template matching no
longer blocks the scheduler loop or the other sessions' ticks.

Analyzers stay async (the port is unchanged). Each is driven to completion in
its worker thread with asyncio.run — for the CPU-bound analyzers this simply
runs their synchronous cv2/pytesseract work off the main loop; a genuinely
I/O-bound analyzer still works, it just gets its own short-lived loop.

The VisionResult contract is preserved exactly: same observations, same
failure isolation (VisionAnalyzerError and any exception become an
AnalyzerFailure), and deterministic binding-order results regardless of which
worker finishes first.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from bap.core.domain.models import ImageData, Observation
from bap.core.ports.vision_analyzer_port import VisionAnalyzerError
from bap.core.vision.pipeline import AnalyzerBinding, AnalyzerFailure, VisionPipeline, VisionResult


class AsyncVisionPipeline(VisionPipeline):
    def __init__(self, bindings: Sequence[AnalyzerBinding], *, executor: ThreadPoolExecutor) -> None:
        super().__init__(bindings)
        self._executor = executor

    async def run(self, image: ImageData) -> VisionResult:
        loop = asyncio.get_running_loop()
        futures = [
            loop.run_in_executor(self._executor, self._run_binding, binding, image)
            for binding in self._bindings
        ]
        outcomes = await asyncio.gather(*futures)

        observations: list[Observation] = []
        failures: list[AnalyzerFailure] = []
        for obs_list, failure in outcomes:  # binding order preserved by gather
            observations.extend(obs_list)
            if failure is not None:
                failures.append(failure)
        return VisionResult(observations=tuple(observations), failures=tuple(failures))

    @staticmethod
    def _run_binding(
        binding: AnalyzerBinding, image: ImageData
    ) -> tuple[list[Observation], AnalyzerFailure | None]:
        """Runs in a worker thread. Mirrors VisionPipeline._run_one's
        containment, but drives the analyzer coroutine off the main loop."""
        name = binding.analyzer.name
        try:
            observations = asyncio.run(binding.analyzer.analyze(image, binding.context))
            invalid = [o for o in observations if not isinstance(o, Observation)]
            if invalid:
                raise VisionAnalyzerError(
                    f"Analyzer '{name}' returned {len(invalid)} non-Observation item(s)."
                )
            return list(observations), None
        except Exception as exc:
            return [], AnalyzerFailure(analyzer=name, error=exc)


__all__ = ["AsyncVisionPipeline"]
