"""Synthetic + stress benchmark plumbing (Milestone 4.9).

Uses a lightweight fake detector/classifier so the benchmark *framework* (world
scaling, per-World aggregation, stage breakdown, reproducible structure) is tested
in milliseconds. The drift test separately proves the timed harness matches the
real pipeline; here we only exercise the benchmark orchestration.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from bap.forge.detection.geometry import CaptureGeometry, derive_rois
from bap.perf.benchmark import Frame, StressBenchmark, SyntheticBenchmark


class _FakeDetector:
    _offset = (16, 0)

    def scan(self, image, region=None):
        return SimpleNamespace(detections=[], candidates=[])

    def score_at(self, image, x, y):
        return 0.0


class _FakeClassifier:
    def __len__(self):
        return 3

    def predict(self, patch):
        return (50, 0.9)


def _frames(n: int = 4):
    rois = derive_rois(CaptureGeometry(raw_w=160, raw_h=100), None)
    out = []
    for i in range(n):
        img = np.zeros((100, 160, 3), dtype=np.uint8)
        out.append(Frame(key=f"fake:{i}", image=img, rois=rois, world_hint=None))
    return out


def _bench(cls):
    return cls(frames=_frames(), classifier=_FakeClassifier(), detector=_FakeDetector(), warmup=1)


def test_synthetic_scales_worlds_and_aggregates():
    bench = _bench(SyntheticBenchmark)
    for count in (1, 2, 4):
        res = bench.run(count, ticks_per_world=3, sample_every=2)
        assert res.kind == "synthetic"
        assert res.config["world_count"] == count
        assert len(res.worlds) == count
        # Every World recorded exactly ticks_per_world ticks.
        for w in res.worlds.values():
            assert w["count"] == 3
        assert res.global_summary["count"] == count * 3
        assert "detection" in res.stage_breakdown
        assert res.extra["throughput_fps"] > 0
        assert res.system["backend"] in ("proc", "psutil")


def test_synthetic_structure_is_reproducible():
    bench = _bench(SyntheticBenchmark)
    a = bench.run(2, ticks_per_world=3)
    b = bench.run(2, ticks_per_world=3)
    # Structural determinism: same Worlds, same counts, same config (timings vary).
    assert set(a.worlds) == set(b.worlds)
    assert {k: v["count"] for k, v in a.worlds.items()} == {k: v["count"] for k, v in b.worlds.items()}
    assert a.config == b.config
    assert a.frames_used == b.frames_used


def test_stress_reports_distribution():
    bench = _bench(StressBenchmark)
    res = bench.run(20, sample_every=5)
    assert res.kind == "stress"
    g = res.global_summary
    assert g["count"] == 20
    # avg / median / p95 / p99 / max are all present and ordered.
    assert g["median"] <= g["p95"] <= g["p99"] <= g["worst"]
    assert res.config["total_ticks"] == 20
