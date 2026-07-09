"""Port for observing browser resource usage.

The snapshot is deliberately generic — plain numbers, no Playwright/Chromium
types — so core stays browser-agnostic. Adapters (e.g. the Playwright metrics
adapter) implement collection; unavailable measurements are None rather than
errors, so a missing process or an unsupported backend degrades gracefully.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class BrowserResourceSnapshot:
    browser_id: str
    pages: int = 0
    contexts: int = 0
    memory_mb: float | None = None
    cpu_percent: float | None = None
    collected_at: datetime = field(default_factory=_utc_now)


class BrowserMetricsPort(ABC):
    """Collects a resource snapshot for one browser. Observational only —
    collecting must never affect the runtime, and must not raise on a missing
    or unavailable process (return the snapshot with None measurements)."""

    @abstractmethod
    async def collect(self) -> BrowserResourceSnapshot: ...


__all__ = ["BrowserMetricsPort", "BrowserResourceSnapshot"]
