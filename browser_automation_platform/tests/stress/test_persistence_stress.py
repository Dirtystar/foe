"""Persistence stress: high write volume, bounded queue, clean flush."""

import sqlite3
import time

import pytest

from bap.adapters.persistence.sqlite_store import SqliteStateStore
from bap.app.persistence_sink import PersistenceSink
from loadkit import build_env

pytestmark = pytest.mark.stress


def _row_count(path, table):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


async def test_high_volume_writes_flush_completely_on_close(tmp_path, capsys):
    path = str(tmp_path / "stress.db")
    store = SqliteStateStore(path)
    persistence = PersistenceSink(store)
    env = build_env(16, interval_ms=10, downstream_sink=persistence.on_report)
    await env.app.create_sessions()

    rounds = 300  # 16 * 300 = 4800 ticks (+ one action each) enqueued fast
    try:
        await env.run_rounds(rounds)
        peak_pending = store.pending_writes  # depth right after the burst
    finally:
        await env.app.stop()

    store.close()  # must flush every queued write
    stats = store.stats()

    expected = 16 * rounds
    assert _row_count(path, "ticks") == expected
    assert _row_count(path, "actions") == expected  # one click per tick
    assert stats.pending == 0  # queue fully drained
    assert stats.failed == 0
    assert stats.completed >= expected

    with capsys.disabled():
        print(
            f"\n[stress] persisted {expected} ticks | peak pending={peak_pending} "
            f"| avg write={stats.avg_write_ms:.3f}ms max={stats.max_write_ms:.2f}ms"
        )


async def test_writer_queue_drains_between_bursts(tmp_path):
    path = str(tmp_path / "drain.db")
    store = SqliteStateStore(path)
    persistence = PersistenceSink(store)
    env = build_env(8, interval_ms=10, downstream_sink=persistence.on_report)
    await env.app.create_sessions()
    try:
        await env.run_rounds(100)
        # give the writer a moment to catch up, then confirm it drained
        deadline = time.monotonic() + 5.0
        while store.pending_writes > 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert store.pending_writes == 0  # no unbounded growth
    finally:
        await env.app.stop()
        store.close()


async def test_wal_mode_is_enabled(tmp_path):
    path = str(tmp_path / "wal.db")
    store = SqliteStateStore(path)
    store.close()

    conn = sqlite3.connect(path)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"  # concurrent reader-friendly journal


async def test_runtime_unaffected_when_writes_are_slow(tmp_path):
    """A deliberately slow writer must not slow the tick loop: enqueue is
    non-blocking, so the runtime completes all rounds regardless."""

    class SlowStore(SqliteStateStore):
        def _write_tick(self, conn, tick):  # type: ignore[override]
            time.sleep(0.001)  # simulate slow disk
            return SqliteStateStore._write_tick(conn, tick)

    path = str(tmp_path / "slow.db")
    store = SlowStore(path)
    persistence = PersistenceSink(store)
    env = build_env(4, interval_ms=10, downstream_sink=persistence.on_report)
    await env.app.create_sessions()
    try:
        start = time.perf_counter()
        await env.run_rounds(50)  # 200 ticks
        loop_elapsed = time.perf_counter() - start
    finally:
        await env.app.stop()
        store.close()

    assert env.reports["completed"] == 200
    # the tick loop finished long before the writer could (200 * ~1ms serial)
    assert loop_elapsed < 0.2
