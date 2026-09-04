"""Performance Observatory (Milestone 4.9) — measurement only.

A self-contained measurement framework for the observe-only Forge pipeline. It
times the existing pipeline stage-by-stage, aggregates per-World and global
statistics, runs reproducible offline benchmarks over the reviewed frames, and
compares two runs for regressions. It changes **no** pipeline behaviour — no
detector, classifier, OCR, scheduler, World, or dataset logic is modified.

Public surface:
    timing.StageTimer / STAGES     — per-stage tick timing
    stats.summarize / Summary      — deterministic avg/median/p95/p99/max + FPS
    system.SystemSampler           — stdlib CPU + RAM sampling (no psutil dep)
    registry.MetricsRegistry       — thread-safe per-World + global store
    pipeline.run_tick              — timed harness over the real build_scan path
    benchmark.SyntheticBenchmark   — 1/2/4/8-World offline replay
    benchmark.StressBenchmark      — 100/1k/10k/100k-tick latency distribution
    export.to_json/to_csv/to_markdown, write_report
    compare.compare                — regression comparison of two runs
"""

from __future__ import annotations

from bap.perf.registry import MetricsRegistry, TickRecord, get_registry
from bap.perf.stats import Summary, summarize
from bap.perf.timing import STAGES, StageTimer

__all__ = [
    "STAGES", "StageTimer",
    "Summary", "summarize",
    "MetricsRegistry", "TickRecord", "get_registry",
]
