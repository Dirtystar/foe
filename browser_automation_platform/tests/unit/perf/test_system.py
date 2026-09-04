"""Stdlib CPU + RAM sampling (Milestone 4.9)."""

from __future__ import annotations

from bap.perf.system import SystemSampler, current_rss_mb


def test_sampler_reports_expected_shape():
    s = SystemSampler()
    for _ in range(3):
        snap = s.sample()
        assert snap.timestamp > 0
    summary = s.summary()
    for key in ("uptime_s", "cpu_count", "avg_cpu_percent", "peak_cpu_percent",
                "avg_ram_mb", "peak_ram_mb", "current_ram_mb", "backend"):
        assert key in summary
    assert summary["uptime_s"] >= 0
    if summary["avg_cpu_percent"] is not None:
        assert summary["avg_cpu_percent"] >= 0


def test_current_rss_is_positive_or_none():
    rss = current_rss_mb()
    assert rss is None or rss > 0
