"""Per-World + global metrics registry and stage timing (Milestone 4.9)."""

from __future__ import annotations

from bap.perf.registry import MetricsRegistry, TickRecord
from bap.perf.timing import StageTimer


def _timer(detection: float, total: float | None = None) -> StageTimer:
    t = StageTimer()
    t.record("capture", 0.0)
    t.record("detection", detection)
    t.record("classification", 0.001)
    t.total = total if total is not None else t.stage_total()
    return t


def test_stage_timer_orders_and_totals():
    t = StageTimer()
    with t.tick():
        with t.stage("detection"):
            _ = sum(range(100))
        t.record("capture", 0.002)
    names = [n for n, _ in t.ordered()]
    assert names == ["capture", "detection"]      # canonical order, not insertion
    assert t.resolved_total() == t.total


def test_registry_aggregates_and_counts_skips():
    reg = MetricsRegistry()
    for i in range(4):
        reg.record_tick("W1", _timer(0.01 * (i + 1)))
    reg.mark_skipped("W1")
    wm = reg.world("W1")
    assert wm.tick_count == 4
    assert wm.skipped == 1
    summ = wm.summary()
    assert summ.count == 4
    assert summ.worst == wm.summary().worst


def test_bottleneck_and_snapshot():
    reg = MetricsRegistry()
    reg.record_tick("W1", _timer(0.05))     # detection dominates
    reg.record_tick("W2", _timer(0.05))
    reg.set_world_counts(attached=2, running=1)
    bn = reg.current_bottleneck()
    assert bn is not None and bn[0] == "detection"

    snap = reg.snapshot()
    assert snap["world_count"] == 2
    assert snap["attached_worlds"] == 2
    assert snap["running_worlds"] == 1
    assert snap["total_ticks"] == 2
    assert snap["current_bottleneck"]["stage"] == "detection"
    assert set(snap["worlds"]) == {"W1", "W2"}
    assert snap["worlds"]["W1"]["worst_stage"] == "detection"


def test_recent_and_slowest_ring():
    reg = MetricsRegistry(ring=8)
    for i in range(12):
        reg.record_tick("W1", _timer(0.001 * (i + 1), total=0.001 * (i + 1)))
    wm = reg.world("W1")
    assert len(wm.recent(100)) == 8              # bounded ring
    slow = wm.slowest(3)
    assert slow[0].total >= slow[1].total >= slow[2].total


def test_tickrecord_from_timer_marks_skipped():
    rec = TickRecord.from_timer("W1", _timer(0.01), skipped=True)
    assert rec.skipped is True and rec.world == "W1"
    reg = MetricsRegistry()
    reg.record(rec)
    assert reg.world("W1").skipped == 1
    assert reg.world("W1").tick_count == 0
