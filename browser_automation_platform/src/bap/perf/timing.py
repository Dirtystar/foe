"""Monotonic stage timing primitives (Milestone 4.9 — measurement only).

A tick is a single pass of the observe-only pipeline for one World. `StageTimer`
records the wall-clock cost of each named stage of that tick using
`time.perf_counter` (monotonic, high-resolution) — it never changes what the
pipeline computes, it only times it. Timings are held in insertion order so a
report can present stages in the order they run.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

# Canonical pipeline stage names, in execution order. Reports and the dashboard
# use this ordering; a timer may record a subset (e.g. weakening is skipped when
# a World has no calibrated region).
STAGES: tuple[str, ...] = (
    "capture",
    "weakening_ocr",
    "detection",
    "classification",
    "decision",
    "gui_update",
    "persistence",
)


def now() -> float:
    """Monotonic high-resolution clock, in seconds."""
    return time.perf_counter()


@dataclass
class StageTimer:
    """Accumulates per-stage durations (seconds) for a single tick.

    Use `with timer.stage("detection"): ...` around each stage; the elapsed time
    is added to that stage's total (repeated stages accumulate). `total` is the
    measured wall time of the whole tick when recorded via `tick()`, else the sum
    of the stages.
    """

    stages: dict[str, float] = field(default_factory=dict)
    total: float | None = None

    @contextmanager
    def stage(self, name: str):
        start = now()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0.0) + (now() - start)

    @contextmanager
    def tick(self):
        """Time the whole tick; sets `total` to the measured wall duration."""
        start = now()
        try:
            yield self
        finally:
            self.total = now() - start

    def record(self, name: str, seconds: float) -> None:
        self.stages[name] = self.stages.get(name, 0.0) + float(seconds)

    def stage_total(self) -> float:
        return sum(self.stages.values())

    def resolved_total(self) -> float:
        """The measured tick wall time if available, else the sum of stages."""
        return self.total if self.total is not None else self.stage_total()

    def ordered(self) -> list[tuple[str, float]]:
        """Stages in canonical execution order, then any extras in insertion order."""
        seen = set()
        out: list[tuple[str, float]] = []
        for name in STAGES:
            if name in self.stages:
                out.append((name, self.stages[name]))
                seen.add(name)
        for name, value in self.stages.items():
            if name not in seen:
                out.append((name, value))
        return out


__all__ = ["STAGES", "now", "StageTimer"]
