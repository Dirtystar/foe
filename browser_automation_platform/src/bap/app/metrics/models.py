"""Analytics models returned by the MetricsRepository.

These are the layer's public vocabulary — plain, immutable value objects, not
database rows. The repository translates SQL results into these so callers
(the GUI) never see cursors, tuples, or column order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class MetricSummary:
    total_ticks: int = 0
    successful_ticks: int = 0
    failed_ticks: int = 0
    avg_duration_ms: float | None = None
    p50_duration_ms: float | None = None
    p95_duration_ms: float | None = None
    recovery_count: int = 0

    @property
    def error_rate(self) -> float:
        return self.failed_ticks / self.total_ticks if self.total_ticks else 0.0

    @property
    def success_rate(self) -> float:
        return self.successful_ticks / self.total_ticks if self.total_ticks else 0.0


@dataclass(frozen=True)
class ProfileMetrics:
    profile_id: str
    ticks: int = 0
    failures: int = 0
    action_success_rate: float | None = None
    recovery_count: int = 0
    last_seen: datetime | None = None
    health: str = "unknown"
    ticks_per_min: float = 0.0


@dataclass(frozen=True)
class VisionMetrics:
    avg_vision_ms: float | None = None
    vision_failure_rate: float = 0.0


@dataclass(frozen=True)
class ActionMetrics:
    total: int = 0
    successful: int = 0
    failed: int = 0
    top_failing: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class RecentFailure:
    timestamp: datetime | None
    profile_id: str
    status: str
    reason: str


__all__ = [
    "ActionMetrics",
    "MetricSummary",
    "ProfileMetrics",
    "RecentFailure",
    "VisionMetrics",
]
