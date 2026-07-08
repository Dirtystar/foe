"""Read-only SQL over the persistence schema.

Each function takes a live sqlite3 connection and returns primitives; the
repository turns them into analytics models. Every read tolerates a missing
schema (fresh/empty database) by returning a safe default, so analytics never
crashes on an empty history. Nothing here writes — SELECT only.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = (), default: Any = 0) -> Any:
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError:  # no such table yet
        return default
    if row is None or row[0] is None:
        return default
    return row[0]


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


# --- overview -----------------------------------------------------------------


def total_ticks(conn) -> int:
    return int(_scalar(conn, "SELECT COUNT(*) FROM ticks"))


def successful_ticks(conn) -> int:
    return int(_scalar(conn, "SELECT COUNT(*) FROM ticks WHERE status = 'completed'"))


def avg_duration_ms(conn) -> float | None:
    value = _scalar(conn, "SELECT AVG(duration_ms) FROM ticks WHERE duration_ms IS NOT NULL", default=None)
    return float(value) if value is not None else None


def duration_percentile(conn, percentile: float) -> float | None:
    n = int(_scalar(conn, "SELECT COUNT(*) FROM ticks WHERE duration_ms IS NOT NULL"))
    if n == 0:
        return None
    offset = int(round((percentile / 100.0) * (n - 1)))
    rows = _rows(
        conn,
        "SELECT duration_ms FROM ticks WHERE duration_ms IS NOT NULL "
        "ORDER BY duration_ms LIMIT 1 OFFSET ?",
        (offset,),
    )
    return float(rows[0][0]) if rows else None


def recovery_count(conn, profile_id: str | None = None) -> int:
    if profile_id is None:
        return int(_scalar(conn, "SELECT COUNT(*) FROM health_events WHERE new_state = 'recovering'"))
    return int(
        _scalar(
            conn,
            "SELECT COUNT(*) FROM health_events WHERE new_state = 'recovering' AND profile_id = ?",
            (profile_id,),
        )
    )


# --- per profile --------------------------------------------------------------


def profile_tick_rows(conn) -> list[tuple]:
    """(profile_id, ticks, failures, min_ts, max_ts) per profile."""
    return _rows(
        conn,
        """
        SELECT profile_id,
               COUNT(*),
               SUM(CASE WHEN status != 'completed' THEN 1 ELSE 0 END),
               MIN(timestamp),
               MAX(timestamp)
        FROM ticks
        GROUP BY profile_id
        ORDER BY profile_id
        """,
    )


def profile_action_rows(conn) -> list[tuple]:
    """(profile_id, total_actions, successful_actions) per profile."""
    return _rows(
        conn,
        """
        SELECT t.profile_id,
               COUNT(*),
               SUM(CASE WHEN a.status = 'succeeded' THEN 1 ELSE 0 END)
        FROM actions a JOIN ticks t ON a.tick_id = t.id
        GROUP BY t.profile_id
        """,
    )


def recovery_rows(conn) -> list[tuple]:
    return _rows(
        conn,
        "SELECT profile_id, COUNT(*) FROM health_events "
        "WHERE new_state = 'recovering' GROUP BY profile_id",
    )


def latest_health_rows(conn) -> list[tuple]:
    return _rows(
        conn,
        "SELECT profile_id, new_state FROM health_events "
        "WHERE id IN (SELECT MAX(id) FROM health_events GROUP BY profile_id)",
    )


# --- vision -------------------------------------------------------------------


def avg_vision_ms(conn) -> float | None:
    value = _scalar(conn, "SELECT AVG(vision_ms) FROM ticks WHERE vision_ms IS NOT NULL", default=None)
    return float(value) if value is not None else None


def vision_failure_count(conn) -> int:
    return int(_scalar(conn, "SELECT COUNT(*) FROM ticks WHERE status = 'vision_failed'"))


# --- actions ------------------------------------------------------------------


def action_totals(conn) -> tuple[int, int, int]:
    total = int(_scalar(conn, "SELECT COUNT(*) FROM actions"))
    ok = int(_scalar(conn, "SELECT COUNT(*) FROM actions WHERE status = 'succeeded'"))
    return total, ok, total - ok


def top_failing_actions(conn, limit: int) -> list[tuple[str, int]]:
    rows = _rows(
        conn,
        "SELECT action_type, COUNT(*) c FROM actions WHERE status != 'succeeded' "
        "GROUP BY action_type ORDER BY c DESC, action_type LIMIT ?",
        (limit,),
    )
    return [(str(r[0]), int(r[1])) for r in rows]


# --- recent failures ----------------------------------------------------------


def recent_failure_rows(conn, limit: int) -> list[tuple]:
    return _rows(
        conn,
        "SELECT timestamp, profile_id, status, error FROM ticks "
        "WHERE status != 'completed' ORDER BY id DESC LIMIT ?",
        (limit,),
    )


__all__ = [
    "action_totals",
    "avg_duration_ms",
    "avg_vision_ms",
    "duration_percentile",
    "latest_health_rows",
    "profile_action_rows",
    "profile_tick_rows",
    "recent_failure_rows",
    "recovery_count",
    "recovery_rows",
    "successful_ticks",
    "top_failing_actions",
    "total_ticks",
    "vision_failure_count",
]
