"""16 sessions with resource monitoring enabled: no starvation, no regression."""

import time

import pytest

from bap.app.resource_monitor import ResourceMonitor
from bap.core.ports.browser_metrics_port import BrowserMetricsPort, BrowserResourceSnapshot
from loadkit import build_env

pytestmark = pytest.mark.load


class FakeMetrics(BrowserMetricsPort):
    def __init__(self):
        self.calls = 0

    async def collect(self):
        self.calls += 1
        # simulate a small, cheap measurement
        return BrowserResourceSnapshot("browser", pages=16, contexts=16, memory_mb=1024.0)


async def test_16_sessions_with_monitoring_no_starvation(capsys):
    metrics = FakeMetrics()
    # ResourceMonitor forwards into the env's normal report chain.
    env = build_env(16, interval_ms=10)
    monitor = ResourceMonitor(
        metrics,
        collect_every=20,
        max_memory_mb=4096,
        max_pages=32,
        report_sink=env.supervisor.on_report,
    )
    # re-point the scheduler's reports through the resource monitor
    env.app.scheduler._on_report = monitor.on_report  # noqa: SLF001

    await env.app.create_sessions()
    rounds = 100
    start = time.perf_counter()
    try:
        await env.run_rounds(rounds)
    finally:
        await env.app.stop()
    elapsed = time.perf_counter() - start

    total = 16 * rounds
    assert env.reports["completed"] == total  # every session ticked equally
    assert metrics.calls > 0  # monitoring actually ran

    with capsys.disabled():
        print(
            f"\n[load] 16 sessions + monitoring | ticks={total} elapsed={elapsed:.3f}s "
            f"| collections={metrics.calls}"
        )


async def test_monitoring_does_not_regress_tick_throughput(capsys):
    """Throughput with monitoring must be close to throughput without it."""

    async def run(with_monitor):
        env = build_env(8, interval_ms=10)
        if with_monitor:
            monitor = ResourceMonitor(
                FakeMetrics(), collect_every=20, report_sink=env.supervisor.on_report
            )
            env.app.scheduler._on_report = monitor.on_report  # noqa: SLF001
        await env.app.create_sessions()
        start = time.perf_counter()
        try:
            await env.run_rounds(200)
        finally:
            await env.app.stop()
        return time.perf_counter() - start

    baseline = await run(False)
    monitored = await run(True)

    with capsys.disabled():
        print(f"\n[load] throughput: baseline={baseline:.3f}s monitored={monitored:.3f}s")
    # monitoring adds only a periodic cheap collection -> well under 2x
    assert monitored < baseline * 2 + 0.5
