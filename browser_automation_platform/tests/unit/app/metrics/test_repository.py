from datetime import datetime, timedelta, timezone

import pytest

from bap.adapters.persistence.sqlite_store import SqliteStateStore
from bap.app.metrics.repository import MetricsRepository
from bap.core.ports.state_store_port import ActionRecord, HealthEventRecord, TickRecord

T0 = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def tick(profile_id, n, *, status="completed", duration=None, vision=None, actions=(), at=None):
    return TickRecord(
        timestamp=at or (T0 + timedelta(seconds=n)),
        profile_id=profile_id,
        tick_number=n,
        status=status,
        duration_ms=duration,
        vision_ms=vision,
        actions=actions,
    )


def seed(path, ticks=(), health=()):
    store = SqliteStateStore(path)
    for t in ticks:
        store.record_tick(t)
    for h in health:
        store.record_health(h)
    store.close()


def repo(path):
    return MetricsRepository(path)


# --- empty / missing ----------------------------------------------------------


def test_missing_database_returns_empty_metrics(tmp_path):
    r = repo(str(tmp_path / "does_not_exist.db"))

    assert r.overview().total_ticks == 0
    assert r.overview().error_rate == 0.0
    assert r.per_profile() == []
    assert r.recent_failures() == []
    assert r.actions().total == 0
    assert r.vision().vision_failure_rate == 0.0


def test_empty_database_with_schema_returns_zeroes(tmp_path):
    path = str(tmp_path / "h.db")
    seed(path)  # creates schema, no rows

    r = repo(path)
    assert r.overview().total_ticks == 0
    assert r.per_profile() == []


# --- overview aggregates ------------------------------------------------------


def test_overview_counts_and_error_rate(tmp_path):
    path = str(tmp_path / "h.db")
    seed(
        path,
        ticks=[
            tick("a", 1, duration=10),
            tick("a", 2, duration=20),
            tick("a", 3, status="capture_failed"),
            tick("a", 4, status="vision_failed"),
        ],
    )

    s = repo(path).overview()
    assert s.total_ticks == 4
    assert s.successful_ticks == 2
    assert s.failed_ticks == 2
    assert s.error_rate == 0.5
    assert s.avg_duration_ms == pytest.approx(15.0)


def test_percentiles_from_seeded_durations(tmp_path):
    path = str(tmp_path / "h.db")
    seed(path, ticks=[tick("a", i, duration=float(i * 10)) for i in range(1, 11)])  # 10..100

    s = repo(path).overview()
    assert s.p50_duration_ms is not None
    assert s.p95_duration_ms is not None
    assert s.p95_duration_ms >= s.p50_duration_ms


def test_recovery_events_counted(tmp_path):
    path = str(tmp_path / "h.db")
    seed(
        path,
        ticks=[tick("a", 1)],
        health=[
            HealthEventRecord(T0, "a", "degraded", "recovering", "attempt 1"),
            HealthEventRecord(T0, "a", "recovering", "healthy", "ok"),
            HealthEventRecord(T0, "a", "degraded", "recovering", "attempt 2"),
        ],
    )

    assert repo(path).overview().recovery_count == 2


# --- per profile --------------------------------------------------------------


def test_multiple_profiles_are_reported_separately(tmp_path):
    path = str(tmp_path / "h.db")
    seed(
        path,
        ticks=[
            tick("a", 1, at=T0),
            tick("a", 2, status="capture_failed", at=T0 + timedelta(seconds=60)),
            tick("b", 1, at=T0),
        ],
        health=[HealthEventRecord(T0, "a", None, "degraded", "one failure")],
    )

    profiles = {p.profile_id: p for p in repo(path).per_profile()}
    assert set(profiles) == {"a", "b"}
    assert profiles["a"].ticks == 2
    assert profiles["a"].failures == 1
    assert profiles["a"].health == "degraded"
    assert profiles["a"].last_seen is not None
    assert profiles["a"].ticks_per_min == pytest.approx(2.0)  # 2 ticks over 60s
    assert profiles["b"].failures == 0
    assert profiles["b"].health == "unknown"  # no health events for b


def test_action_success_rate_per_profile(tmp_path):
    path = str(tmp_path / "h.db")
    seed(
        path,
        ticks=[
            tick(
                "a",
                1,
                actions=(
                    ActionRecord("r1", "click", "succeeded"),
                    ActionRecord("r1", "wait", "failed", "boom"),
                ),
            )
        ],
    )

    p = repo(path).per_profile()[0]
    assert p.action_success_rate == pytest.approx(0.5)


# --- actions ------------------------------------------------------------------


def test_action_totals_and_top_failing(tmp_path):
    path = str(tmp_path / "h.db")
    seed(
        path,
        ticks=[
            tick(
                "a",
                1,
                actions=(
                    ActionRecord("r1", "click", "succeeded"),
                    ActionRecord("r1", "click", "failed", "x"),
                    ActionRecord("r1", "type", "failed", "y"),
                    ActionRecord("r1", "click", "failed", "z"),
                ),
            )
        ],
    )

    a = repo(path).actions()
    assert (a.total, a.successful, a.failed) == (4, 1, 3)
    assert a.top_failing[0] == ("click", 2)  # most common failing type


# --- vision -------------------------------------------------------------------


def test_vision_metrics(tmp_path):
    path = str(tmp_path / "h.db")
    seed(
        path,
        ticks=[
            tick("a", 1, vision=100.0),
            tick("a", 2, vision=200.0),
            tick("a", 3, status="vision_failed"),
        ],
    )

    v = repo(path).vision()
    assert v.avg_vision_ms == pytest.approx(150.0)
    assert v.vision_failure_rate == pytest.approx(1 / 3)


# --- recent failures ----------------------------------------------------------


def test_recent_failures_newest_first_with_reason(tmp_path):
    path = str(tmp_path / "h.db")
    seed(
        path,
        ticks=[
            tick("a", 1),
            tick("a", 2, status="capture_failed"),
            tick("b", 3, status="internal_error"),
        ],
    )
    # give the failed ticks explicit errors
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("UPDATE ticks SET error='page crashed' WHERE status='capture_failed'")
    conn.commit()
    conn.close()

    failures = repo(path).recent_failures(limit=10)
    assert [f.status for f in failures] == ["internal_error", "capture_failed"]
    assert failures[1].reason == "page crashed"


def test_repository_does_not_write(tmp_path):
    """A read-only repository must not create a DB file that isn't there."""
    path = tmp_path / "absent.db"
    repo(str(path))
    assert not path.exists()
