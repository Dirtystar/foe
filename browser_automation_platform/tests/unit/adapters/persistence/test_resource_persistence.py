import sqlite3
from datetime import datetime, timezone

from bap.adapters.persistence.sqlite_store import SqliteStateStore
from bap.app.metrics.repository import MetricsRepository
from bap.core.ports.state_store_port import BrowserResourceRecord

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def rec(n, memory=100.0, pages=4):
    return BrowserResourceRecord(
        timestamp=NOW, browser_id="b", memory_mb=memory, cpu_percent=10.0,
        pages=pages, contexts=2,
    )


def read(path, query):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def test_resource_snapshots_are_stored_append_only(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path)
    for i in range(3):
        store.record_resource(rec(i, memory=100.0 + i))
    store.close()

    rows = read(path, "SELECT memory_mb, pages, contexts FROM browser_metrics ORDER BY id")
    assert rows == [(100.0, 4, 2), (101.0, 4, 2), (102.0, 4, 2)]


def test_repository_reads_latest_snapshot_and_trend(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path)
    store.record_resource(rec(0, memory=100.0, pages=4))
    store.record_resource(rec(1, memory=150.0, pages=8))
    store.record_resource(rec(2, memory=200.0, pages=12))
    store.close()

    repo = MetricsRepository(path)
    try:
        r = repo.browser_resources()
        assert r.has_data
        assert r.memory_mb == 200.0  # latest
        assert r.pages == 12
        assert r.contexts == 2
        assert r.samples == 3
        assert r.memory_trend == (100.0, 150.0, 200.0)  # oldest -> newest
    finally:
        repo.close()


def test_repository_empty_when_no_resource_data(tmp_path):
    path = str(tmp_path / "h.db")
    store = SqliteStateStore(path)
    store.close()  # schema only, no rows

    repo = MetricsRepository(path)
    try:
        r = repo.browser_resources()
        assert not r.has_data
        assert r.memory_mb is None
        assert r.memory_trend == ()
    finally:
        repo.close()


def test_missing_database_returns_empty_resources(tmp_path):
    repo = MetricsRepository(str(tmp_path / "absent.db"))
    assert not repo.browser_resources().has_data
