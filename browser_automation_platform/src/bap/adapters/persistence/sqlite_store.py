"""SQLite StateStorePort implementation.

All writes run on one dedicated background thread that owns the sole SQLite
connection. Runtime callbacks only enqueue records (non-blocking, thread-safe
via a queue), so a slow or failing write never blocks the event loop or the
scheduler. Writes are append-only INSERTs. Schema is created automatically on
open. Write failures on the background thread are surfaced through an optional
on_error callback rather than raised into the runtime.
"""

from __future__ import annotations

import queue
import sqlite3
import threading
from collections.abc import Callable

from bap.core.ports.state_store_port import (
    HealthEventRecord,
    StateStorePort,
    StorageError,
    TickRecord,
)

_SENTINEL = object()

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
"""


class SqliteStateStore(StateStorePort):
    def __init__(self, path: str, *, on_error: Callable[[Exception], None] | None = None) -> None:
        self._path = str(path)
        self._on_error = on_error
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._init_error: Exception | None = None
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="bap-store", daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._init_error is not None:
            raise StorageError(f"cannot open store '{self._path}': {self._init_error}")

    # --- port API (called from runtime threads; non-blocking) ---------------

    def record_tick(self, tick: TickRecord) -> None:
        self._enqueue(("tick", tick))

    def record_health(self, event: HealthEventRecord) -> None:
        self._enqueue(("health", event))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put(_SENTINEL)
        self._thread.join(timeout=5.0)

    def _enqueue(self, item) -> None:
        if self._closed:
            raise StorageError("store is closed")
        self._queue.put(item)

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
                item = self._queue.get()
                if item is _SENTINEL:
                    break
                kind, dto = item
                try:
                    if kind == "tick":
                        self._write_tick(conn, dto)
                    elif kind == "health":
                        self._write_health(conn, dto)
                    conn.commit()
                except Exception as exc:  # one bad write must not kill the writer
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


__all__ = ["SqliteStateStore"]
