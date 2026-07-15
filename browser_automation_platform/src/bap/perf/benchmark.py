"""Offline, reproducible performance benchmarks (Milestone 4.9).

Two browser-free benchmarks that replay the **reviewed** frame set through the
real observe-only pipeline:

  * `SyntheticBenchmark` — models 1 / 2 / 4 / 8 Worlds and reports frames/sec,
    tick latency, the per-stage breakdown, CPU and RAM.
  * `StressBenchmark` — runs a fixed tick budget (100 / 1k / 10k / 100k) and
    reports average / median / p95 / p99 / max.

Determinism: frames are loaded once and replayed from memory in a fixed, sorted
order with a fixed World assignment and no randomness, so re-running on the same
machine yields results comparable within normal system variance. Nothing here
changes detector, classifier, OCR, scheduler, or World behaviour — it only times
the existing pipeline.
"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bap.perf.pipeline import run_tick
from bap.perf.registry import MetricsRegistry
from bap.perf.stats import summarize
from bap.perf.system import SystemSampler
from bap.perf.timing import StageTimer

_ASSETS_ROOT = Path(__file__).resolve().parents[2] / "tests" / "forge_assets"


@dataclass
class Frame:
    """One preloaded reviewed frame, ready to replay with no disk access."""

    key: str
    image: object          # decoded BGR ndarray
    rois: object           # ScanRois (includes the calibrated weakening region)
    world_hint: str | None


def load_frames(assets_root: Path | str = _ASSETS_ROOT) -> list[Frame]:
    """Load and decode every reviewed frame once, in a deterministic order."""
    import cv2

    from bap.forge.detection.dataset import load_all

    samples = sorted(load_all(), key=lambda s: s.key)
    frames: list[Frame] = []
    for s in samples:
        img = cv2.imread(str(s.path))
        if img is None:
            continue
        frames.append(Frame(key=s.key, image=img, rois=s.rois, world_hint=s.world))
    if not frames:
        raise RuntimeError("no reviewed frames available to benchmark")
    return frames


def build_classifier(assets_root: Path | str = _ASSETS_ROOT):
    """The bundled classifier (reviewed exemplars). None if nothing is reviewed."""
    from bap.forge.detection.classify import default_label_sources, train_from_sources

    sources = default_label_sources(Path(assets_root))
    return train_from_sources(sources) if sources else None


def _make_world(index: int):
    from bap.forge.worlds import World

    return World(alias=f"W{index}", hostname=f"cz{index}.forgeofempires.com")


def _machine() -> dict:
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu_count": __import__("os").cpu_count(),
        "processor": platform.processor() or platform.machine(),
    }


def _git_ref() -> str | None:
    try:
        import subprocess

        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


@dataclass
class BenchmarkResult:
    kind: str                      # "synthetic" | "stress"
    label: str
    config: dict
    created_at: str
    git_ref: str | None
    machine: dict
    frames_used: int
    global_summary: dict
    stage_breakdown: dict          # stage -> Summary.to_dict()
    system: dict
    worlds: dict = field(default_factory=dict)   # per-World summary dicts
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "label": self.label,
            "config": self.config,
            "created_at": self.created_at,
            "git_ref": self.git_ref,
            "machine": self.machine,
            "frames_used": self.frames_used,
            "global": self.global_summary,
            "stage_breakdown": self.stage_breakdown,
            "system": self.system,
            "worlds": self.worlds,
            "extra": self.extra,
        }


class _BenchBase:
    def __init__(self, frames=None, classifier=None, detector=None,
                 *, persist: bool = False, warmup: int = 3) -> None:
        self._frames = frames if frames is not None else load_frames()
        self._classifier = classifier if classifier is not None else build_classifier()
        if detector is None:
            from bap.forge.detection.detector import BadgeDetector

            detector = BadgeDetector()
        self._detector = detector
        self._persist = persist
        self._warmup = max(0, warmup)

    def _tick(self, frame: Frame, world) -> StageTimer:
        _, timer = run_tick(frame.image, world=world, detector=self._detector,
                            classifier=self._classifier, rois=frame.rois,
                            persist=self._persist)
        return timer

    def _do_warmup(self, world) -> None:
        # Warm code paths / caches so steady-state numbers are not skewed by the
        # first few JIT-free-but-cold-cache ticks. Not recorded.
        for i in range(self._warmup):
            self._tick(self._frames[i % len(self._frames)], world)


class SyntheticBenchmark(_BenchBase):
    """Replay the reviewed frames across N Worlds and report scaling behaviour."""

    def run(self, world_count: int, *, ticks_per_world: int = 100,
            sample_every: int = 10) -> BenchmarkResult:
        if world_count < 1:
            raise ValueError("world_count must be >= 1")
        registry = MetricsRegistry(ring=max(240, ticks_per_world))
        worlds = [_make_world(i + 1) for i in range(world_count)]
        registry.set_world_counts(attached=world_count, running=world_count)
        self._do_warmup(worlds[0])

        sampler = SystemSampler()
        stage_acc: dict[str, list[float]] = {}
        totals: list[float] = []
        n = len(self._frames)
        wall0 = time.monotonic()
        tick_i = 0
        # Round-robin across Worlds so the interleaving matches a single-process
        # scheduler servicing N Worlds in turn (the real runtime is one loop).
        for step in range(ticks_per_world):
            for w_idx, world in enumerate(worlds):
                frame = self._frames[(step + w_idx) % n]  # deterministic rotation
                timer = self._tick(frame, world)
                registry.record_tick(world.alias, timer)
                totals.append(timer.resolved_total())
                for name, value in timer.stages.items():
                    stage_acc.setdefault(name, []).append(value)
                tick_i += 1
                if tick_i % sample_every == 0:
                    sampler.sample()
        wall = time.monotonic() - wall0
        sampler.sample()

        total_ticks = len(totals)
        gsum = summarize(totals)
        result = BenchmarkResult(
            kind="synthetic",
            label=f"{world_count}-world",
            config={"world_count": world_count, "ticks_per_world": ticks_per_world,
                    "total_ticks": total_ticks, "persist": self._persist},
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            git_ref=_git_ref(),
            machine=_machine(),
            frames_used=n,
            global_summary=gsum.to_dict(),
            stage_breakdown={k: summarize(v).to_dict() for k, v in stage_acc.items()},
            system=sampler.summary(),
            worlds={name: registry.world(name).to_dict() for name in registry.world_names()},
            extra={
                "wall_seconds": round(wall, 4),
                "throughput_fps": round(total_ticks / wall, 3) if wall > 0 else 0.0,
                "per_world_fps": round(gsum.fps, 3),
            },
        )
        return result


class StressBenchmark(_BenchBase):
    """Run a fixed tick budget over the reviewed frames and report the latency
    distribution (average / median / p95 / p99 / max)."""

    def run(self, total_ticks: int, *, sample_every: int = 50) -> BenchmarkResult:
        if total_ticks < 1:
            raise ValueError("total_ticks must be >= 1")
        world = _make_world(1)
        self._do_warmup(world)
        sampler = SystemSampler()
        totals: list[float] = []
        stage_acc: dict[str, list[float]] = {}
        n = len(self._frames)
        wall0 = time.monotonic()
        for i in range(total_ticks):
            timer = self._tick(self._frames[i % n], world)
            totals.append(timer.resolved_total())
            for name, value in timer.stages.items():
                stage_acc.setdefault(name, []).append(value)
            if (i + 1) % sample_every == 0:
                sampler.sample()
        wall = time.monotonic() - wall0
        sampler.sample()

        gsum = summarize(totals)
        return BenchmarkResult(
            kind="stress",
            label=f"{total_ticks}-ticks",
            config={"total_ticks": total_ticks, "persist": self._persist},
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            git_ref=_git_ref(),
            machine=_machine(),
            frames_used=n,
            global_summary=gsum.to_dict(),
            stage_breakdown={k: summarize(v).to_dict() for k, v in stage_acc.items()},
            system=sampler.summary(),
            extra={
                "wall_seconds": round(wall, 4),
                "throughput_fps": round(total_ticks / wall, 3) if wall > 0 else 0.0,
            },
        )


def run_synthetic_suite(world_counts=(1, 2, 4, 8), *, ticks_per_world: int = 100,
                        frames=None, classifier=None, detector=None) -> list[BenchmarkResult]:
    """Run the standard 1/2/4/8-World synthetic sweep sharing one loaded fixture."""
    bench = SyntheticBenchmark(frames=frames, classifier=classifier, detector=detector)
    return [bench.run(c, ticks_per_world=ticks_per_world) for c in world_counts]


def run_stress_suite(budgets=(100, 1000, 10000, 100000), *,
                     frames=None, classifier=None, detector=None) -> list[BenchmarkResult]:
    """Run the standard stress ladder sharing one loaded fixture."""
    bench = StressBenchmark(frames=frames, classifier=classifier, detector=detector)
    return [bench.run(b) for b in budgets]


__all__ = [
    "Frame", "BenchmarkResult", "SyntheticBenchmark", "StressBenchmark",
    "load_frames", "build_classifier", "run_synthetic_suite", "run_stress_suite",
]
