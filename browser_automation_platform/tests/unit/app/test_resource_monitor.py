from datetime import datetime, timezone

import pytest

from bap.app.resource_monitor import ResourceMonitor, snapshot_to_record
from bap.core.engine.tab_session import TickReport, TickStatus
from bap.core.ports.browser_metrics_port import BrowserMetricsPort, BrowserResourceSnapshot


def report(profile_id="p1"):
    now = datetime.now(timezone.utc)
    return TickReport(
        profile_id=profile_id, tick_number=1, status=TickStatus.COMPLETED,
        started_at=now, finished_at=now,
    )


class FakeMetrics(BrowserMetricsPort):
    def __init__(self, snapshot=None, *, error=None):
        self._snapshot = snapshot or BrowserResourceSnapshot("b", pages=3, contexts=2, memory_mb=100.0)
        self._error = error
        self.calls = 0

    async def collect(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._snapshot


class RecordingStore:
    def __init__(self):
        self.resources = []

    def record_resource(self, rec):
        self.resources.append(rec)


async def test_reports_are_forwarded_downstream():
    forwarded = []
    monitor = ResourceMonitor(FakeMetrics(), collect_every=1000, report_sink=forwarded.append)

    r = report()
    monitor.on_report(r)

    assert forwarded == [r]


async def test_collection_triggered_on_cadence():
    metrics = FakeMetrics()
    scheduled = []
    monitor = ResourceMonitor(metrics, collect_every=3, task_runner=scheduled.append)

    for _ in range(7):
        monitor.on_report(report())

    # collection scheduled once per `collect_every` reports (at 3 and 6)
    assert len(scheduled) == 2
    for coro in scheduled:
        await coro  # run the scheduled collections
    assert metrics.calls == 2


async def test_snapshot_is_persisted_and_observed():
    store = RecordingStore()
    observed = []
    monitor = ResourceMonitor(FakeMetrics(), store=store, on_resource=observed.append)

    snap = await monitor.collect_now()

    assert snap is not None
    assert len(store.resources) == 1
    assert store.resources[0].pages == 3
    assert observed[0].memory_mb == 100.0


async def test_limits_are_evaluated_and_breaches_reported():
    pressure = []
    monitor = ResourceMonitor(
        FakeMetrics(BrowserResourceSnapshot("b", pages=20, contexts=2, memory_mb=5000.0)),
        max_memory_mb=4096,
        max_pages=16,
        on_pressure=lambda s, b: pressure.append(b),
    )

    await monitor.collect_now()

    assert len(pressure) == 1
    breaches = pressure[0]
    assert any("memory" in b for b in breaches)
    assert any("pages" in b for b in breaches)


async def test_within_limits_reports_empty_breaches():
    pressure = []
    monitor = ResourceMonitor(
        FakeMetrics(BrowserResourceSnapshot("b", pages=2, contexts=1, memory_mb=100.0)),
        max_memory_mb=4096,
        max_pages=16,
        on_pressure=lambda s, b: pressure.append(b),
    )

    await monitor.collect_now()

    assert pressure == [()]  # called with empty breaches so the policy can reset


async def test_collection_failure_is_contained():
    monitor = ResourceMonitor(FakeMetrics(error=RuntimeError("psutil blew up")))

    result = await monitor.collect_now()  # must not raise

    assert result is None


def test_snapshot_to_record_maps_fields():
    snap = BrowserResourceSnapshot("b7", pages=4, contexts=2, memory_mb=42.0, cpu_percent=9.0)
    rec = snapshot_to_record(snap)
    assert (rec.browser_id, rec.pages, rec.contexts) == ("b7", 4, 2)
    assert rec.memory_mb == 42.0 and rec.cpu_percent == 9.0
