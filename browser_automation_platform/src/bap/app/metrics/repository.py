"""MetricsRepository: read-only analytics over the persisted history.

Independent of StateStorePort — it never writes and shares no state with the
writer. It opens its own read-only SQLite connection (URI mode=ro), so it
cannot block or corrupt runtime writes; with the store's WAL journal, reads
and writes proceed concurrently. A missing or empty database yields empty
metrics rather than an error.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from bap.app.metrics import queries as q
from bap.app.metrics.models import (
    ActionMetrics,
    BrowserResourceMetrics,
    MetricSummary,
    ProfileMetrics,
    RecentFailure,
    VisionMetrics,
)


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _ticks_per_min(count: int, min_ts, max_ts) -> float:
    start, end = _parse_ts(min_ts), _parse_ts(max_ts)
    if start is None or end is None:
        return 0.0
    span_s = (end - start).total_seconds()
    if span_s <= 0:
        return 0.0
    return count / (span_s / 60.0)


class MetricsRepository:
    def __init__(self, path: str) -> None:
        self._path = str(path)
        self._conn: sqlite3.Connection | None = self._open()

    def _open(self) -> sqlite3.Connection | None:
        if not Path(self._path).exists():
            return None  # nothing persisted yet -> empty metrics
        try:
            return sqlite3.connect(
                f"file:{self._path}?mode=ro", uri=True, check_same_thread=False
            )
        except sqlite3.OperationalError:
            return None

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # --- overview -----------------------------------------------------------

    def overview(self) -> MetricSummary:
        if self._conn is None:
            return MetricSummary()
        total = q.total_ticks(self._conn)
        success = q.successful_ticks(self._conn)
        return MetricSummary(
            total_ticks=total,
            successful_ticks=success,
            failed_ticks=total - success,
            avg_duration_ms=q.avg_duration_ms(self._conn),
            p50_duration_ms=q.duration_percentile(self._conn, 50),
            p95_duration_ms=q.duration_percentile(self._conn, 95),
            recovery_count=q.recovery_count(self._conn),
        )

    # --- per profile --------------------------------------------------------

    def per_profile(self) -> list[ProfileMetrics]:
        if self._conn is None:
            return []
        actions = {r[0]: (r[1], r[2]) for r in q.profile_action_rows(self._conn)}
        recoveries = {r[0]: r[1] for r in q.recovery_rows(self._conn)}
        health = {r[0]: r[1] for r in q.latest_health_rows(self._conn)}

        result: list[ProfileMetrics] = []
        for profile_id, ticks, failures, min_ts, max_ts in q.profile_tick_rows(self._conn):
            total_actions, ok_actions = actions.get(profile_id, (0, 0))
            success_rate = (ok_actions / total_actions) if total_actions else None
            result.append(
                ProfileMetrics(
                    profile_id=profile_id,
                    ticks=int(ticks),
                    failures=int(failures or 0),
                    action_success_rate=success_rate,
                    recovery_count=int(recoveries.get(profile_id, 0)),
                    last_seen=_parse_ts(max_ts),
                    health=health.get(profile_id, "unknown"),
                    ticks_per_min=_ticks_per_min(int(ticks), min_ts, max_ts),
                )
            )
        return result

    # --- vision -------------------------------------------------------------

    def vision(self) -> VisionMetrics:
        if self._conn is None:
            return VisionMetrics()
        total = q.total_ticks(self._conn)
        failures = q.vision_failure_count(self._conn)
        return VisionMetrics(
            avg_vision_ms=q.avg_vision_ms(self._conn),
            vision_failure_rate=(failures / total) if total else 0.0,
        )

    # --- actions ------------------------------------------------------------

    def actions(self, *, top: int = 5) -> ActionMetrics:
        if self._conn is None:
            return ActionMetrics()
        total, ok, failed = q.action_totals(self._conn)
        return ActionMetrics(
            total=total,
            successful=ok,
            failed=failed,
            top_failing=tuple(q.top_failing_actions(self._conn, top)),
        )

    # --- browser resources --------------------------------------------------

    def browser_resources(self, *, trend: int = 30) -> BrowserResourceMetrics:
        if self._conn is None:
            return BrowserResourceMetrics()
        samples = q.resource_sample_count(self._conn)
        if samples == 0:
            return BrowserResourceMetrics()
        latest = q.latest_resource_row(self._conn)
        browser_id, memory_mb, cpu_percent, pages, contexts, ts = latest
        return BrowserResourceMetrics(
            browser_id=browser_id,
            memory_mb=float(memory_mb) if memory_mb is not None else None,
            cpu_percent=float(cpu_percent) if cpu_percent is not None else None,
            pages=int(pages),
            contexts=int(contexts),
            last_seen=_parse_ts(ts),
            samples=samples,
            memory_trend=tuple(q.resource_memory_trend(self._conn, trend)),
        )

    # --- recent failures ----------------------------------------------------

    def recent_failures(self, *, limit: int = 20) -> list[RecentFailure]:
        if self._conn is None:
            return []
        return [
            RecentFailure(
                timestamp=_parse_ts(ts),
                profile_id=profile_id,
                status=status,
                reason=error or status,
            )
            for ts, profile_id, status, error in q.recent_failure_rows(self._conn, limit)
        ]


__all__ = ["MetricsRepository"]
