"""Deterministic summary statistics for timing samples (Milestone 4.9).

Pure Python, no numpy — the same inputs always produce the same summary, so two
benchmark runs are comparable and regression comparison is stable. Percentiles
use linear interpolation between closest ranks (numpy's default "linear" method).
Durations are handled in seconds; helpers convert to milliseconds and FPS for
presentation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def percentile(values: list[float], q: float) -> float:
    """The q-th percentile (0..100) via linear interpolation, deterministic."""
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    rank = (q / 100.0) * (len(xs) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return xs[int(rank)]
    frac = rank - lo
    return xs[lo] + (xs[hi] - xs[lo]) * frac


@dataclass(frozen=True)
class Summary:
    """Aggregate timing summary. All durations are seconds."""

    count: int
    mean: float
    median: float
    p95: float
    p99: float
    worst: float
    minimum: float
    stdev: float
    total: float

    @property
    def fps(self) -> float:
        """Average frames-per-second equivalent (1 / mean tick)."""
        return (1.0 / self.mean) if self.mean > 0 else 0.0

    def to_dict(self, *, ms: bool = True) -> dict:
        scale = 1000.0 if ms else 1.0
        unit = "ms" if ms else "s"
        return {
            "count": self.count,
            "unit": unit,
            "mean": round(self.mean * scale, 4),
            "median": round(self.median * scale, 4),
            "p95": round(self.p95 * scale, 4),
            "p99": round(self.p99 * scale, 4),
            "worst": round(self.worst * scale, 4),
            "min": round(self.minimum * scale, 4),
            "stdev": round(self.stdev * scale, 4),
            "total": round(self.total * scale, 4),
            "fps": round(self.fps, 3),
        }


def summarize(values: list[float]) -> Summary:
    """Summarize a list of durations (seconds). Empty input yields zeros."""
    if not values:
        return Summary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    n = len(values)
    total = math.fsum(values)
    mean = total / n
    stdev = 0.0
    if n > 1:
        var = math.fsum((v - mean) ** 2 for v in values) / (n - 1)
        stdev = math.sqrt(var)
    return Summary(
        count=n,
        mean=mean,
        median=percentile(values, 50),
        p95=percentile(values, 95),
        p99=percentile(values, 99),
        worst=max(values),
        minimum=min(values),
        stdev=stdev,
        total=total,
    )


def fps_equiv(mean_seconds: float) -> float:
    return (1.0 / mean_seconds) if mean_seconds > 0 else 0.0


__all__ = ["percentile", "Summary", "summarize", "fps_equiv"]
