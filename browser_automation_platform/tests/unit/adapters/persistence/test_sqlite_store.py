import sqlite3
from datetime import datetime, timezone

import pytest

from bap.adapters.persistence.sqlite_store import SqliteStateStore
from bap.core.ports.state_store_port import (
    ActionRecord,
    HealthEventRecord,
    StorageError,
    TickRecord,
)

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def tick(**over) -> TickRecord:
    defaults = dict(
        timestamp=NOW,
        profile_id="p1",
        tick_number=1,
        status="completed",
        duration_ms=42.0,
        capture_ms=5.0,
        vision_ms=30.0,
        rules_ms=1.0,
        actions_ms=6.0,
        rules_matched=1,
        rules_total=2,
        error=None,
        actions=(),
    )
    defaults.update(over)
    return TickRecord(**defaults)


def read(path, query):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def test_schema_is_created_automatically(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path)
    store.close()

    tables = {r[0] for r in read(path, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ticks", "health_events", "actions"} <= tables


def test_completed_tick_and_metrics_are_persisted(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path)
    store.record_tick(tick())
    store.close()

    rows = read(
        path,
        "SELECT profile_id, status, duration_ms, capture_ms, vision_ms, rules_ms, "
        "actions_ms, rules_matched, rules_total FROM ticks",
    )
    assert rows == [("p1", "completed", 42.0, 5.0, 30.0, 1.0, 6.0, 1, 2)]


def test_failed_tick_is_persisted_with_error(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path)
    store.record_tick(tick(status="capture_failed", error="page crashed", duration_ms=None))
    store.close()

    rows = read(path, "SELECT status, error FROM ticks")
    assert rows == [("capture_failed", "page crashed")]


def test_action_results_are_preserved_and_linked_to_tick(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path)
    store.record_tick(
        tick(
            actions=(
                ActionRecord(rule_id="r1", action_type="click", status="succeeded"),
                ActionRecord(rule_id="r1", action_type="wait", status="failed", error="boom"),
            )
        )
    )
    store.close()

    rows = read(
        path,
        "SELECT a.rule_id, a.action_type, a.status, a.error FROM actions a "
        "JOIN ticks t ON a.tick_id = t.id ORDER BY a.id",
    )
    assert rows == [
        ("r1", "click", "succeeded", None),
        ("r1", "wait", "failed", "boom"),
    ]


def test_health_transitions_are_stored(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path)
    store.record_health(
        HealthEventRecord(
            timestamp=NOW,
            profile_id="p1",
            previous_state="healthy",
            new_state="recovering",
            reason="recovery attempt 1",
        )
    )
    store.close()

    rows = read(path, "SELECT profile_id, previous_state, new_state, reason FROM health_events")
    assert rows == [("p1", "healthy", "recovering", "recovery attempt 1")]


def test_history_is_append_only(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path)
    for i in range(1, 4):
        store.record_tick(tick(tick_number=i))
    store.close()

    rows = read(path, "SELECT tick_number FROM ticks ORDER BY id")
    assert [r[0] for r in rows] == [1, 2, 3]


def test_opening_a_corrupted_database_raises_storage_error(tmp_path):
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"this is definitely not a sqlite database file")

    with pytest.raises(StorageError):
        SqliteStateStore(str(path))


def test_recording_after_close_raises_storage_error(tmp_path):
    store = SqliteStateStore(str(tmp_path / "h.db"))
    store.close()

    with pytest.raises(StorageError):
        store.record_tick(tick())


def test_close_is_idempotent(tmp_path):
    store = SqliteStateStore(str(tmp_path / "h.db"))
    store.close()
    store.close()  # must not raise


def test_two_stores_do_not_share_state(tmp_path):
    a = SqliteStateStore(str(tmp_path / "a.db"))
    b = SqliteStateStore(str(tmp_path / "b.db"))
    a.record_tick(tick(profile_id="only-a"))
    a.close()
    b.close()

    assert read(str(tmp_path / "a.db"), "SELECT COUNT(*) FROM ticks")[0][0] == 1
    assert read(str(tmp_path / "b.db"), "SELECT COUNT(*) FROM ticks")[0][0] == 0
