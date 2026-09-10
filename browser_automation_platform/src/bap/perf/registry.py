"""Thread-safe per-World and global performance registry (Milestone 4.9).

A passive sink: callers record one `TickRecord` per completed (or skipped) tick
and the registry aggregates per-World summaries (average / median / p95 / worst /
count / skipped / FPS-equivalent) plus per-stage breakdowns. It stores no
automation state and drives no behaviour — the runtime and benchmarks feed it,
and the Performance dashboard reads snapshots from it. A bounded ring of recent
ticks backs the live charts and the "recent slow ticks" view.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from bap.perf.stats import Summary, summarize
from bap.perf.timing import StageTimer


@dataclass
class TickRecord:
    world: str
    total: float                      # seconds; whole-tick wall time
    stages: dict[str, float] = field(default_factory=dict)
    skipped: bool = False
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def from_timer(cls, world: str, timer: StageTimer, *, skipped: bool = False) -> "TickRecord":
        return cls(world=world, total=timer.resolved_total(),
                   stages=dict(timer.stages), skipped=skipped)


class WorldMetrics:
    """Accumulated timing for a single World."""

    def __init__(self, name: str, *, ring: int = 240) -> None:
        self.name = name
        self._totals: list[float] = []
        self._stage_samples: dict[str, list[float]] = {}
        self._skipped = 0
        self._recent: deque[TickRecord] = deque(maxlen=ring)

    def add(self, rec: TickRecord) -> None:
        self._recent.append(rec)
        if rec.skipped:
            self._skipped += 1
            return
        self._totals.append(rec.total)
        for name, value in rec.stages.items():
            self._stage_samples.setdefault(name, []).append(value)

    @property
    def tick_count(self) -> int:
        return len(self._totals)

    @property
    def skipped(self) -> int:
        return self._skipped

    def summary(self) -> Summary:
        return summarize(self._totals)

    def stage_summaries(self) -> dict[str, Summary]:
        return {name: summarize(vals) for name, vals in self._stage_samples.items()}

    def worst_stage(self) -> tuple[str, float] | None:
        """The stage with the highest mean cost — the per-World bottleneck."""
        means = {n: (sum(v) / len(v)) for n, v in self._stage_samples.items() if v}
        if not means:
            return None
        name = max(means, key=means.get)
        return name, means[name]

    def recent(self, n: int = 20) -> list[TickRecord]:
        items = list(self._recent)
        return items[-n:]

    def slowest(self, n: int = 5) -> list[TickRecord]:
        done = [r for r in self._recent if not r.skipped]
        return sorted(done, key=lambda r: r.total, reverse=True)[:n]

    def to_dict(self) -> dict:
        s = self.summary()
        d = s.to_dict()
        d.update({
            "world": self.name,
            "skipped_ticks": self._skipped,
            "stages": {n: st.to_dict() for n, st in self.stage_summaries().items()},
        })
        ws = self.worst_stage()
        d["worst_stage"] = ws[0] if ws else None
        return d


class MetricsRegistry:
    """Live per-World + global metrics store. Safe to write from any thread."""

    def __init__(self, *, ring: int = 240) -> None:
        self._lock = threading.RLock()
        self._worlds: dict[str, WorldMetrics] = {}
        self._ring = ring
        self._start = time.monotonic()
        self._attached = 0
        self._running = 0

    # --- writes ------------------------------------------------------------

    def record(self, rec: TickRecord) -> None:
        with self._lock:
            wm = self._worlds.get(rec.world)
            if wm is None:
                wm = WorldMetrics(rec.world, ring=self._ring)
                self._worlds[rec.world] = wm
            wm.add(rec)

    def record_tick(self, world: str, timer: StageTimer, *, skipped: bool = False) -> None:
        self.record(TickRecord.from_timer(world, timer, skipped=skipped))

    def mark_skipped(self, world: str) -> None:
        self.record(TickRecord(world=world, total=0.0, skipped=True))

    def set_world_counts(self, *, attached: int | None = None, running: int | None = None) -> None:
        with self._lock:
            if attached is not None:
                self._attached = attached
            if running is not None:
                self._running = running

    def reset(self) -> None:
        with self._lock:
            self._worlds.clear()
            self._start = time.monotonic()
            self._attached = 0
            self._running = 0

    # --- reads -------------------------------------------------------------

    def world_names(self) -> list[str]:
        with self._lock:
            return sorted(self._worlds)

    def world(self, name: str) -> WorldMetrics | None:
        with self._lock:
            return self._worlds.get(name)

    def uptime_s(self) -> float:
        return time.monotonic() - self._start

    def global_summary(self) -> Summary:
        """Summary over every World's non-skipped ticks combined."""
        with self._lock:
            totals: list[float] = []
            for wm in self._worlds.values():
                totals.extend(wm._totals)
        return summarize(totals)

    def current_bottleneck(self) -> tuple[str, float] | None:
        """The stage with the highest mean cost across all Worlds."""
        with self._lock:
            agg: dict[str, list[float]] = {}
            for wm in self._worlds.values():
                for name, vals in wm._stage_samples.items():
                    agg.setdefault(name, []).extend(vals)
        means = {n: (sum(v) / len(v)) for n, v in agg.items() if v}
        if not means:
            return None
        name = max(means, key=means.get)
        return name, means[name]

    def snapshot(self, *, slow_n: int = 8) -> dict:
        """A plain-dict view for the dashboard / export (no live objects)."""
        with self._lock:
            worlds = {name: wm.to_dict() for name, wm in self._worlds.items()}
            total_ticks = sum(wm.tick_count for wm in self._worlds.values())
            total_skipped = sum(wm.skipped for wm in self._worlds.values())
            slow: list[dict] = []
            for wm in self._worlds.values():
                for rec in wm.slowest(slow_n):
                    slow.append({"world": wm.name, "total_ms": round(rec.total * 1000, 3),
                                 "stages": {k: round(v * 1000, 3) for k, v in rec.stages.items()}})
            attached, running = self._attached, self._running
        slow.sort(key=lambda r: r["total_ms"], reverse=True)
        bottleneck = self.current_bottleneck()
        gs = self.global_summary()
        return {
            "uptime_s": round(self.uptime_s(), 3),
            "attached_worlds": attached,
            "running_worlds": running,
            "world_count": len(worlds),
            "total_ticks": total_ticks,
            "total_skipped": total_skipped,
            "global": gs.to_dict(),
            "worlds": worlds,
            "recent_slow_ticks": slow[:slow_n],
            "current_bottleneck": ({"stage": bottleneck[0],
                                    "mean_ms": round(bottleneck[1] * 1000, 3)}
                                   if bottleneck else None),
        }


_DEFAULT: MetricsRegistry | None = None


def get_registry() -> MetricsRegistry:
    """The process-wide default registry (lazily created). The dashboard reads
    this; benchmarks may use it or their own instance."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = MetricsRegistry()
    return _DEFAULT


__all__ = ["TickRecord", "WorldMetrics", "MetricsRegistry", "get_registry"]
