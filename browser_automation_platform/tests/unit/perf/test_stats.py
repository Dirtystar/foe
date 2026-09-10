"""Deterministic summary statistics (Milestone 4.9)."""

from __future__ import annotations

from bap.perf.stats import Summary, fps_equiv, percentile, summarize


def test_percentile_linear_interpolation():
    xs = [0.010, 0.020, 0.030, 0.040, 0.050]
    assert percentile(xs, 0) == 0.010
    assert percentile(xs, 50) == 0.030
    assert abs(percentile(xs, 95) - 0.048) < 1e-12   # rank 3.8 -> 0.04 + 0.8*0.01
    assert percentile(xs, 100) == 0.050


def test_percentile_edge_cases():
    assert percentile([], 95) == 0.0
    assert percentile([0.7], 95) == 0.7


def test_summarize_is_deterministic_and_correct():
    xs = [0.01, 0.02, 0.03, 0.04, 0.05]
    a = summarize(xs)
    b = summarize(list(reversed(xs)))
    assert a == b                              # order-independent
    assert a.count == 5
    assert abs(a.mean - 0.03) < 1e-12
    assert a.worst == 0.05
    assert a.minimum == 0.01
    assert abs(a.fps - (1 / 0.03)) < 1e-9


def test_summarize_empty():
    s = summarize([])
    assert s == Summary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    assert s.fps == 0.0


def test_to_dict_ms_scaling_and_fps():
    d = summarize([0.01, 0.02, 0.03]).to_dict(ms=True)
    assert d["unit"] == "ms"
    assert abs(d["mean"] - 20.0) < 1e-6        # 0.02 s -> 20 ms
    assert d["count"] == 3
    assert fps_equiv(0.02) == 50.0
