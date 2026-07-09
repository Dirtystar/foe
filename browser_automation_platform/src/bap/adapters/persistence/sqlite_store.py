"""SQLite StateStorePort implementation.

All writes run on one dedicated background thread that owns the sole SQLite
connection. Runtime callbacks only enqueue records (non-blocking, thread-safe),
so a slow or failing write never blocks the event loop or the scheduler. Writes
are append-only INSERTs. Schema is created automatically on open. Write failures
on the background thread are surfaced through an optional on_error callback
rather than raised into the runtime.

Overload policy (see docs/PRODUCTION_RISK_REPORT.md): the write buffer is
bounded (`max_queue_size`). Enqueue is always non-blocking — the runtime never
waits on storage. When the buffer is full, records are dropped by priority
(lowest first), and `dropped_records` counts them. CRITICAL records
(health/recovery/disabled-session events) bypass the bound and are never
dropped, because losing them would corrupt the diagnostic picture of what the
runtime did; the tradeoff is that a sustained flood of CRITICAL records could
grow memory (bounded in practice by how often health transitions occur).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

from bap.core.ports.state_store_port import (
    BrowserResourceRecord,
    HealthEventRecord,
    StateStorePort,
    StorageError,
    TickRecord,
)


class WritePriority(IntEnum):
    """Higher value = more important. Dropping starts from the lowest."""

    LOW = 0        # successful tick history (completed, no actions)
    NORMAL = 1     # completed tick carrying action successes
    IMPORTANT = 2  # failed ticks and ticks containing action failures
    CRITICAL = 3   # health/recovery/disabled-session events — never dropped


def _classify(kind: str, dto) -> WritePriority:
    if kind == "health":
        return WritePriority.CRITICAL
    if kind == "resource":
        return WritePriority.NORMAL  # diagnostic; below failures, above pure history
    # tick
    if dto.status != "completed":
        return WritePriority.IMPORTANT
    if any(a.status != "succeeded" for a in dto.actions):
        return WritePriority.IMPORTANT
    if dto.actions:
        return WritePriority.NORMAL
    return WritePriority.LOW


@dataclass(frozen=True)
class StoreStats:
    """Observability snapshot for the writer. Latencies are milliseconds."""

    pending: int
    completed: int
    failed: int
    dropped: int
    total_write_ms: float
    max_write_ms: float
    overloaded: bool

    @property
    def avg_write_ms(self) -> float:
        return self.total_write_ms / self.completed if self.completed else 0.0


class _WriteBuffer:
    """Bounded, priority-aware, thread-safe hand-off to the writer thread.

    Non-critical records are capped at `max_size`; CRITICAL records bypass the
    cap. put() never blocks: on a full buffer it evicts the lowest-priority
    queued record that ranks below the incoming one (dropping LOW before
    NORMAL before IMPORTANT), or drops the incoming record if nothing ranks
    lower. Items are drained FIFO so history stays roughly chronological.
    """

    def __init__(self, max_size: int) -> None:
        self._max = max_size
        self._items: deque = deque()  # (priority, kind, dto)
        self._noncritical = 0
        self._dropped = 0
        self._closed = False
        self._cond = threading.Condition()

    def put(self, priority: WritePriority, kind: str, dto) -> None:
        with self._cond:
            if priority is WritePriority.CRITICAL:
                self._items.append((priority, kind, dto))
                self._cond.notify()
                return
            if self._noncritical < self._max:
                self._items.append((priority, kind, dto))
                self._noncritical += 1
                self._cond.notify()
                return
            # Full: evict the lowest-priority item ranking below the incoming.
            victim = self._lowest_index_below(priority)
            if victim is not None:
                del self._items[victim]  # evicted item is non-critical
                self._items.append((priority, kind, dto))
                self._dropped += 1
                self._cond.notify()
            else:
                self._dropped += 1  # incoming is the least important — drop it

    def _lowest_index_below(self, priority: WritePriority) -> int | None:
        best_idx: int | None = None
        best_pri: WritePriority = priority
        for i, (p, _, _) in enumerate(self._items):
            if p < best_pri:
                best_pri = p
                best_idx = i
        return best_idx

    def get(self):
        """Block until an item is available; return None once closed+drained."""
        with self._cond:
            while not self._items and not self._closed:
                self._cond.wait()
            if not self._items:
                return None
            priority, kind, dto = self._items.popleft()
            if priority is not WritePriority.CRITICAL:
                self._noncritical -= 1
            return priority, kind, dto

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    @property
    def pending(self) -> int:
        with self._cond:
            return len(self._items)

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def overloaded(self) -> bool:
        with self._cond:
            return self._noncritical >= self._max

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    tick_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    duration_ms REAL,
    capture_ms REAL,
    vision_ms REAL,
    rules_ms REAL,
    actions_ms REAL,
    rules_matched INTEGER,
    rules_total INTEGER,
    error TEXT
);
CREATE TABLE IF NOT EXISTS health_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT NOT NULL,
    reason TEXT
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick_id INTEGER NOT NULL,
    rule_id TEXT,
    action_type TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    FOREIGN KEY (tick_id) REFERENCES ticks (id)
);
CREATE TABLE IF NOT EXISTS browser_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    browser_id TEXT NOT NULL,
    memory_mb REAL,
    cpu_percent REAL,
    pages INTEGER NOT NULL,
    contexts INTEGER NOT NULL
);
"""


class SqliteStateStore(StateStorePort):
    def __init__(
        self,
        path: str,
        *,
        max_queue_size: int = 10_000,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        if max_queue_size <= 0:
            raise ValueError("max_queue_size must be > 0")
        self._path = str(path)
        self._on_error = on_error
        self._buffer = _WriteBuffer(max_queue_size)
        self._ready = threading.Event()
        self._init_error: Exception | None = None
        self._closed = False
        # Observability (written only by the writer thread; read after work
        # settles or post-close).
        self._completed = 0
        self._failed = 0
        self._total_write_ms = 0.0
        self._max_write_ms = 0.0
        self._thread = threading.Thread(target=self._run, name="bap-store", daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._init_error is not None:
            raise StorageError(f"cannot open store '{self._path}': {self._init_error}")

    # --- port API (called from runtime threads; non-blocking) ---------------

    def record_tick(self, tick: TickRecord) -> None:
        self._enqueue("tick", tick)

    def record_health(self, event: HealthEventRecord) -> None:
        self._enqueue("health", event)

    def record_resource(self, snapshot: BrowserResourceRecord) -> None:
        self._enqueue("resource", snapshot)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._buffer.close()  # writer drains remaining items, then exits
        self._thread.join(timeout=10.0)

    def _enqueue(self, kind: str, dto) -> None:
        if self._closed:
            raise StorageError("store is closed")
        # Non-blocking, priority-aware. Never raises on overload; drops instead.
        self._buffer.put(_classify(kind, dto), kind, dto)

    @property
    def pending_writes(self) -> int:
        return self._buffer.pending

    @property
    def dropped_records(self) -> int:
        return self._buffer.dropped

    @property
    def overload_state(self) -> str:
        return "overloaded" if self._buffer.overloaded else "normal"

    def stats(self) -> StoreStats:
        return StoreStats(
            pending=self._buffer.pending,
            completed=self._completed,
            failed=self._failed,
            dropped=self._buffer.dropped,
            total_write_ms=self._total_write_ms,
            max_write_ms=self._max_write_ms,
            overloaded=self._buffer.overloaded,
        )

    # --- writer thread ------------------------------------------------------

    def _run(self) -> None:
        try:
            conn = sqlite3.connect(self._path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
        except Exception as exc:  # corrupted/unopenable db: report at construction
            self._init_error = exc
            self._ready.set()
            return
        self._ready.set()

        try:
            while True:
                item = self._buffer.get()
                if item is None:  # closed and drained
                    break
                _priority, kind, dto = item
                started = time.perf_counter()
                try:
                    if kind == "tick":
                        self._write_tick(conn, dto)
                    elif kind == "health":
                        self._write_health(conn, dto)
                    elif kind == "resource":
                        self._write_resource(conn, dto)
                    conn.commit()
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    self._completed += 1
                    self._total_write_ms += elapsed_ms
                    self._max_write_ms = max(self._max_write_ms, elapsed_ms)
                except Exception as exc:  # one bad write must not kill the writer
                    self._failed += 1
                    if self._on_error is not None:
                        self._on_error(exc)
        finally:
            conn.close()

    @staticmethod
    def _write_tick(conn: sqlite3.Connection, tick: TickRecord) -> None:
        cursor = conn.execute(
            """
            INSERT INTO ticks (
                timestamp, profile_id, tick_number, status, duration_ms,
                capture_ms, vision_ms, rules_ms, actions_ms, rules_matched,
                rules_total, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tick.timestamp.isoformat(),
                tick.profile_id,
                tick.tick_number,
                tick.status,
                tick.duration_ms,
                tick.capture_ms,
                tick.vision_ms,
                tick.rules_ms,
                tick.actions_ms,
                tick.rules_matched,
                tick.rules_total,
                tick.error,
            ),
        )
        tick_id = cursor.lastrowid
        for action in tick.actions:
            conn.execute(
                "INSERT INTO actions (tick_id, rule_id, action_type, status, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (tick_id, action.rule_id, action.action_type, action.status, action.error),
            )

    @staticmethod
    def _write_resource(conn: sqlite3.Connection, snap: BrowserResourceRecord) -> None:
        conn.execute(
            "INSERT INTO browser_metrics (timestamp, browser_id, memory_mb, cpu_percent, "
            "pages, contexts) VALUES (?, ?, ?, ?, ?, ?)",
            (
                snap.timestamp.isoformat(),
                snap.browser_id,
                snap.memory_mb,
                snap.cpu_percent,
                snap.pages,
                snap.contexts,
            ),
        )

    @staticmethod
    def _write_health(conn: sqlite3.Connection, event: HealthEventRecord) -> None:
        conn.execute(
            "INSERT INTO health_events (timestamp, profile_id, previous_state, new_state, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                event.timestamp.isoformat(),
                event.profile_id,
                event.previous_state,
                event.new_state,
                event.reason,
            ),
        )


__all__ = ["SqliteStateStore", "StoreStats", "WritePriority"]
