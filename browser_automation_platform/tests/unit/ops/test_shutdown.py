"""Graceful shutdown hardening: idempotent, no leaked tasks/threads/tabs,
and persistence is flushed on close. Exercised over the real runtime with
stub adapters (no production hooks added)."""

from __future__ import annotations

import asyncio
import sqlite3

from bap.app.composition import create_application
from bap.app.persistence_sink import PersistenceSink
from bap.app.stubs import StubCapturePort
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor
from bap.ops.lifecycle import IdempotentShutdown
from tests.loadkit import (
    FlakyCapture,
    TrackingBrowser,
    build_env,
    live_task_count,
    make_config,
    thread_count,
)


async def test_clean_start_stop_leaves_no_tasks_or_open_tabs() -> None:
    env = build_env(4, interval_ms=5)
    baseline_tasks = live_task_count()
    baseline_threads = thread_count()

    await env.app.start()
    await asyncio.sleep(0.05)  # let several ticks run
    errors = await env.app.stop()

    assert errors == ()
    assert live_task_count() == baseline_tasks
    assert thread_count() == baseline_threads
    # every tab that opened was closed
    assert env.browser.opens == env.browser.closes
    assert sum(env.browser.opens.values()) == 4


async def test_shutdown_is_idempotent_under_concurrent_triggers() -> None:
    env = build_env(3, interval_ms=5)
    await env.app.start()
    await asyncio.sleep(0.03)

    shutdown = IdempotentShutdown(lambda: _stop_and_record(env, results))
    results: list = []
    await asyncio.gather(*(shutdown() for _ in range(4)))

    assert len(results) == 1  # underlying stop ran exactly once
    assert results[0] == ()
    assert env.browser.opens == env.browser.closes


async def _stop_and_record(env, results) -> None:
    results.append(await env.app.stop())


async def test_shutdown_during_active_tick_completes_cleanly() -> None:
    # A capture that blocks briefly guarantees stop() lands mid-tick.
    class SlowCapture(StubCapturePort):
        async def capture(self, tab, target=None):
            await asyncio.sleep(0.02)
            return await super().capture(tab, target)

    env = build_env(2, interval_ms=1, capture=SlowCapture())
    baseline_tasks = live_task_count()
    await env.app.start()
    await asyncio.sleep(0.01)  # a tick is in-flight inside SlowCapture
    errors = await env.app.stop()

    assert errors == ()
    assert live_task_count() == baseline_tasks
    assert env.browser.opens == env.browser.closes


async def test_shutdown_during_recovery_completes_cleanly() -> None:
    # Real recovery tasks (default task_runner) in flight when we stop.
    browser = TrackingBrowser()
    capture = FlakyCapture(fail_plan={"s0-tab": 10_000})  # permanently broken tab
    monitor = HealthMonitor(recreate_after=1, max_recovery_attempts=100)
    supervisor = Supervisor(monitor=monitor)
    app = create_application(
        load_config_from_string(make_config(2, interval_ms=1)),
        on_report=supervisor.on_report,
        browser=browser,
        capture_port=capture,
    )
    supervisor.session_manager = app.manager

    baseline_tasks = live_task_count()
    await app.start()
    await asyncio.sleep(0.05)  # failures + recovery churning
    errors = await app.stop()
    await asyncio.sleep(0)  # let any just-scheduled recovery settle

    assert errors == ()
    assert live_task_count() == baseline_tasks
    assert browser.opens == browser.closes


async def test_persistence_is_flushed_on_close(tmp_path) -> None:
    from bap.adapters.persistence.sqlite_store import SqliteStateStore

    db = tmp_path / "history.db"
    store = SqliteStateStore(str(db))
    sink = PersistenceSink(store)
    env = build_env(2, interval_ms=5, downstream_sink=sink.on_report)

    await env.app.start()
    await asyncio.sleep(0.05)
    await env.app.stop()
    store.close()  # must drain the write buffer before returning

    conn = sqlite3.connect(str(db))
    try:
        (count,) = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()
    finally:
        conn.close()
    assert count > 0
