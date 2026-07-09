import sqlite3
import threading
import time
from datetime import datetime, timezone

import pytest

from bap.adapters.persistence.sqlite_store import (
    SqliteStateStore,
    WritePriority,
    _classify,
)
from bap.core.ports.state_store_port import ActionRecord, HealthEventRecord, TickRecord

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def low_tick(n):
    return TickRecord(timestamp=NOW, profile_id="p", tick_number=n, status="completed")


def normal_tick(n):
    return TickRecord(
        timestamp=NOW, profile_id="p", tick_number=n, status="completed",
        actions=(ActionRecord("r1", "click", "succeeded"),),
    )


def important_tick(n):
    return TickRecord(timestamp=NOW, profile_id="p", tick_number=n, status="capture_failed")


def health(n):
    return HealthEventRecord(NOW, "p", "healthy", "recovering", f"attempt {n}")


def read(path, query):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


class GatedStore(SqliteStateStore):
    """Writer blocks on a gate so the buffer can be filled deterministically."""

    def __init__(self, path, **kw):
        self.gate = threading.Event()
        super().__init__(path, **kw)

    def _write_tick(self, conn, tick):
        self.gate.wait()
        return SqliteStateStore._write_tick(conn, tick)

    def _write_health(self, conn, event):
        self.gate.wait()
        return SqliteStateStore._write_health(conn, event)


# --- classification -----------------------------------------------------------


def test_priority_classification():
    assert _classify("health", health(1)) is WritePriority.CRITICAL
    assert _classify("tick", important_tick(1)) is WritePriority.IMPORTANT
    assert _classify(
        "tick",
        TickRecord(timestamp=NOW, profile_id="p", tick_number=1, status="completed",
                   actions=(ActionRecord("r", "click", "failed", "x"),)),
    ) is WritePriority.IMPORTANT
    assert _classify("tick", normal_tick(1)) is WritePriority.NORMAL
    assert _classify("tick", low_tick(1)) is WritePriority.LOW


# --- normal drain -------------------------------------------------------------


def test_queue_drains_normally_without_drops(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path, max_queue_size=100)
    for i in range(50):
        store.record_tick(normal_tick(i))
    store.close()

    assert store.dropped_records == 0
    assert read(path, "SELECT COUNT(*) FROM ticks")[0][0] == 50


# --- overload / dropping ------------------------------------------------------


def test_overload_drops_low_priority_and_counts_them(tmp_path):
    path = str(tmp_path / "h.db")
    store = GatedStore(path, max_queue_size=5)
    try:
        for i in range(30):  # writer is gated -> buffer overflows
            store.record_tick(low_tick(i))
        assert store.overload_state == "overloaded"
        assert store.dropped_records >= 30 - 5 - 1  # bound + at most one in-flight
    finally:
        store.gate.set()
        store.close()

    stats = store.stats()
    assert stats.dropped == store.dropped_records
    written = read(path, "SELECT COUNT(*) FROM ticks")[0][0]
    assert written + store.dropped_records == 30  # every record accounted for
    assert written <= 6  # bound (5) + at most one in-flight


def test_important_records_preserved_over_low(tmp_path):
    path = str(tmp_path / "h.db")
    store = GatedStore(path, max_queue_size=5)
    try:
        for i in range(10):
            store.record_tick(low_tick(i))       # fill with LOW
        for i in range(3):
            store.record_tick(important_tick(100 + i))  # must displace LOW
    finally:
        store.gate.set()
        store.close()

    # all three IMPORTANT (failed) ticks survived
    failed = read(path, "SELECT COUNT(*) FROM ticks WHERE status='capture_failed'")[0][0]
    assert failed == 3
    assert store.dropped_records > 0


def test_critical_health_events_are_never_dropped(tmp_path):
    path = str(tmp_path / "h.db")
    store = GatedStore(path, max_queue_size=3)
    try:
        for i in range(50):
            store.record_tick(low_tick(i))   # flood LOW -> heavy dropping
        for i in range(10):
            store.record_health(health(i))   # CRITICAL bypasses the bound
    finally:
        store.gate.set()
        store.close()

    # every health event was persisted despite the tick flood
    assert read(path, "SELECT COUNT(*) FROM health_events")[0][0] == 10
    assert store.dropped_records > 0  # LOW ticks were dropped


def test_overload_with_genuinely_slow_writer(tmp_path):
    class SlowStore(SqliteStateStore):
        def _write_tick(self, conn, tick):
            time.sleep(0.002)
            return SqliteStateStore._write_tick(conn, tick)

    path = str(tmp_path / "slow.db")
    store = SlowStore(path, max_queue_size=20)
    try:
        for i in range(500):  # enqueue far faster than a 2ms/write drain
            store.record_tick(low_tick(i))
    finally:
        store.close()

    assert store.dropped_records > 0  # overload caused drops
    written = read(path, "SELECT COUNT(*) FROM ticks")[0][0]
    assert written + store.dropped_records == 500


# --- runtime never blocks -----------------------------------------------------


def test_enqueue_never_blocks_even_when_writer_is_stuck(tmp_path):
    path = str(tmp_path / "h.db")
    store = GatedStore(path, max_queue_size=5)
    try:
        start = time.perf_counter()
        for i in range(1000):
            store.record_tick(low_tick(i))  # writer fully blocked
        elapsed = time.perf_counter() - start
    finally:
        store.gate.set()
        store.close()

    assert elapsed < 0.5  # 1000 non-blocking enqueues are fast despite a stuck writer


# --- shutdown flush -----------------------------------------------------------


def test_close_flushes_remaining_records(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path, max_queue_size=10_000)
    for i in range(200):
        store.record_tick(normal_tick(i))
    # do not wait — close() must drain whatever is still queued
    store.close()

    assert store.pending_writes == 0
    assert read(path, "SELECT COUNT(*) FROM ticks")[0][0] == 200
    assert store.dropped_records == 0
