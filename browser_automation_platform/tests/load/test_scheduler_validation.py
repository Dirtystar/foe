"""Scheduler validation: interval accuracy, jitter, and no head-of-line block."""

import asyncio

import pytest

from bap.app.composition import create_application
from bap.app.stubs import StubBrowser, StubCapturePort
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor
from bap.core.engine.scheduler import Scheduler
from loadkit import make_config

pytestmark = pytest.mark.load


class RecordingSleep:
    def __init__(self):
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        await asyncio.sleep(0)


async def _wait_until(predicate, *, tries=5000):
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never met")


async def test_interval_accuracy_at_scale():
    sleep = RecordingSleep()
    counts = {}

    def sink(r):
        counts[r.profile_id] = counts.get(r.profile_id, 0) + 1

    supervisor = Supervisor(monitor=HealthMonitor(), sink=sink)
    # An injected scheduler carries its own on_report; wire the supervisor here.
    scheduler = Scheduler(sleep=sleep, on_report=supervisor.on_report)
    app = create_application(
        load_config_from_string(make_config(8, interval_ms=250)),
        browser=StubBrowser(),
        capture_port=StubCapturePort(),
        scheduler=scheduler,
    )
    supervisor.session_manager = app.manager

    await app.start()
    try:
        await _wait_until(lambda: all(counts.get(f"s{i}", 0) >= 3 for i in range(8)))
    finally:
        await app.stop()

    # every recorded inter-tick delay equals the configured interval (250ms),
    # with zero jitter -> no drift introduced by the scheduler itself
    assert sleep.delays, "no sleeps recorded"
    assert all(abs(d - 0.25) < 1e-9 for d in sleep.delays)


async def test_jitter_is_bounded_and_applied():
    sleep = RecordingSleep()
    supervisor = Supervisor(monitor=HealthMonitor(), sink=lambda r: None)
    scheduler = Scheduler(sleep=sleep, rng=lambda: 0.5, on_report=supervisor.on_report)
    app = create_application(
        load_config_from_string(make_config(4, interval_ms=100, jitter_ms=100)),
        browser=StubBrowser(),
        capture_port=StubCapturePort(),
        scheduler=scheduler,
    )
    supervisor.session_manager = app.manager
    await app.start()
    try:
        await _wait_until(lambda: len(sleep.delays) >= 8)
    finally:
        await app.stop()

    # interval 100ms + rng(0.5)*100ms jitter = 150ms exactly
    assert all(abs(d - 0.15) < 1e-9 for d in sleep.delays)


async def test_slow_session_does_not_block_others(capsys):
    """One session with a slow (awaited) capture must not starve the others —
    the cooperative event loop keeps the fast sessions ticking."""
    fast_ticks = {"count": 0}
    slow_release = asyncio.Event()

    class MixedCapture(StubCapturePort):
        async def capture(self, tab, target=None):
            if tab.tab_id == "s0":
                await slow_release.wait()  # s0 hangs until released
            return await super().capture(tab, target)

    def sink(r):
        if r.profile_id != "s0":
            fast_ticks["count"] += 1

    supervisor = Supervisor(monitor=HealthMonitor(), sink=sink)
    scheduler = Scheduler(sleep=lambda s: asyncio.sleep(0), on_report=supervisor.on_report)
    app = create_application(
        load_config_from_string(make_config(4, interval_ms=10)),
        browser=StubBrowser(),
        capture_port=MixedCapture(),
        scheduler=scheduler,
    )
    supervisor.session_manager = app.manager

    await app.start()
    try:
        # fast sessions keep ticking while s0 is stuck in capture
        await _wait_until(lambda: fast_ticks["count"] >= 30)
    finally:
        slow_release.set()
        await app.stop()

    with capsys.disabled():
        print(f"\n[load] fast-session ticks while one session hung: {fast_ticks['count']}")
