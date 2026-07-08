"""Executes vision analyzers over a captured image.

The pipeline runs analyzers, it does not interpret them: observations come
out exactly as analyzers produced them (the Aggregator resolves conflicts),
and one analyzer failing never prevents the others from completing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from bap.core.domain.models import ImageData, Observation
from bap.core.ports.vision_analyzer_port import (
    AnalyzerContext,
    VisionAnalyzerError,
    VisionAnalyzerPort,
)


@dataclass(frozen=True)
class AnalyzerBinding:
    """One analyzer plus the context it runs with, fixed at configuration time."""

    analyzer: VisionAnalyzerPort
    context: AnalyzerContext


@dataclass(frozen=True)
class AnalyzerFailure:
    analyzer: str
    error: Exception


@dataclass(frozen=True)
class VisionResult:
    """Everything one pipeline run produced. Failures are data, not raises:
    the caller (TabSession) decides whether a partial result is usable."""

    observations: tuple[Observation, ...]
    failures: tuple[AnalyzerFailure, ...]

    @property
    def fully_succeeded(self) -> bool:
        return not self.failures


class VisionPipeline:
    """Runs a fixed set of analyzer bindings concurrently over one image.

    Bindings are set at construction: a pipeline instance represents "the
    analyzers configured for one capture target of one profile". Analyzers
    are independent — they share nothing, run via asyncio.gather, and their
    observation order in the result follows binding order, not finish order,
    so results are deterministic.
    """

    def __init__(self, bindings: Sequence[AnalyzerBinding]) -> None:
        self._bindings = tuple(bindings)

    @property
    def analyzer_names(self) -> tuple[str, ...]:
        return tuple(b.analyzer.name for b in self._bindings)

    async def run(self, image: ImageData) -> VisionResult:
        outcomes = await asyncio.gather(
            *(self._run_one(binding, image) for binding in self._bindings)
        )

        observations: list[Observation] = []
        failures: list[AnalyzerFailure] = []
        for obs_list, failure in outcomes:
            observations.extend(obs_list)
            if failure is not None:
                failures.append(failure)
        return VisionResult(observations=tuple(observations), failures=tuple(failures))

    @staticmethod
    async def _run_one(
        binding: AnalyzerBinding, image: ImageData
    ) -> tuple[list[Observation], AnalyzerFailure | None]:
        name = binding.analyzer.name
        try:
            observations = await binding.analyzer.analyze(image, binding.context)
            invalid = [o for o in observations if not isinstance(o, Observation)]
            if invalid:
                raise VisionAnalyzerError(
                    f"Analyzer '{name}' returned {len(invalid)} non-Observation item(s)."
                )
            return list(observations), None
        except Exception as exc:
            return [], AnalyzerFailure(analyzer=name, error=exc)


__all__ = ["AnalyzerBinding", "AnalyzerFailure", "VisionPipeline", "VisionResult"]
