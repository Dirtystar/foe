"""Export (JSON/CSV/Markdown) and regression comparison (Milestone 4.9)."""

from __future__ import annotations

import json

from bap.perf import compare as cmp_mod
from bap.perf import export


def _result(label: str, mean: float, p95: float, fps: float) -> dict:
    return {
        "kind": "stress", "label": label, "created_at": "2026-07-15T00:00:00+00:00",
        "git_ref": "abc1234", "machine": {"platform": "linux", "cpu_count": 4, "python": "3.11"},
        "frames_used": 6, "config": {"total_ticks": 50},
        "global": {"unit": "ms", "count": 50, "mean": mean, "median": mean, "p95": p95,
                   "p99": p95 + 1, "worst": p95 + 2, "min": mean - 1, "stdev": 1.0, "fps": fps},
        "stage_breakdown": {"detection": {"unit": "ms", "count": 50, "mean": mean * 0.9,
                                          "median": mean * 0.9, "p95": p95 * 0.9, "p99": p95,
                                          "worst": p95 + 1, "min": 1.0, "stdev": 1.0,
                                          "fps": 1000 / (mean * 0.9)}},
        "system": {"backend": "proc", "uptime_s": 1.0, "avg_cpu_percent": 90.0,
                   "peak_cpu_percent": 120.0, "avg_ram_mb": 100.0, "peak_ram_mb": 150.0,
                   "current_ram_mb": 100.0, "cpu_count": 4},
        "worlds": {}, "extra": {"throughput_fps": fps},
    }


def test_json_roundtrips():
    r = _result("base", 10.0, 15.0, 100.0)
    parsed = json.loads(export.to_json(r))
    assert parsed["global"]["mean"] == 10.0
    assert parsed["label"] == "base"


def test_csv_has_scopes():
    csv = export.to_csv(_result("base", 10.0, 15.0, 100.0))
    assert "scope" in csv.splitlines()[0]
    assert "global" in csv and "detection" in csv


def test_markdown_report_mentions_key_sections():
    md = export.to_markdown(_result("base", 10.0, 15.0, 100.0))
    assert "Performance report" in md
    assert "Global tick timing" in md
    assert "System" in md


def test_write_report(tmp_path):
    written = export.write_report(_result("base", 10.0, 15.0, 100.0), tmp_path, stem="r")
    assert set(written) == {"json", "csv", "md"}
    for path in written.values():
        assert path.endswith((".json", ".csv", ".md"))


def test_compare_flags_regression_and_improvement():
    base = _result("baseline", 10.0, 15.0, 100.0)
    slower = _result("current", 12.0, 20.0, 80.0)     # +20% mean, -20% fps
    cmp = cmp_mod.compare(base, slower, tolerance=5.0)
    metrics = {d.metric: d.verdict for d in cmp.global_deltas}
    assert metrics["mean"] == "regression"
    assert metrics["p95"] == "regression"
    assert metrics["fps"] == "regression"
    assert cmp.to_dict()["regression_count"] >= 3

    faster = _result("current", 8.0, 12.0, 125.0)     # improvements
    cmp2 = cmp_mod.compare(base, faster, tolerance=5.0)
    metrics2 = {d.metric: d.verdict for d in cmp2.global_deltas}
    assert metrics2["mean"] == "improvement"
    assert metrics2["fps"] == "improvement"


def test_compare_within_tolerance_is_unchanged():
    base = _result("baseline", 10.0, 15.0, 100.0)
    near = _result("current", 10.2, 15.3, 98.0)       # within 5%
    cmp = cmp_mod.compare(base, near, tolerance=5.0)
    assert all(d.verdict in ("unchanged", "n/a") for d in cmp.global_deltas)
    assert cmp.regressions == []


def test_compare_markdown_summarizes_counts():
    base = _result("baseline", 10.0, 15.0, 100.0)
    cur = _result("current", 13.0, 20.0, 70.0)
    md = cmp_mod.to_markdown(cmp_mod.compare(base, cur))
    assert "Regression comparison" in md
    assert "regression" in md
