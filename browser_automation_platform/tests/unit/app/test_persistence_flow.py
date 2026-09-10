"""End-to-end: real SQLite store persists a real (stub-runtime) tick round."""

import sqlite3

import pytest

from bap.adapters.persistence.sqlite_store import SqliteStateStore
from bap.app.composition import create_application
from bap.app.persistence_sink import PersistenceSink
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor

CONFIG = """
rule_packs:
  pack:
    - id: click_ready
      condition: { type: exists, field: screen.ready }
      actions:
        - type: click
          params: { selector: "#x" }
profiles:
  - id: a
    rule_pack: pack
    session: { interval_ms: 10 }
    capture_bindings:
      - name: screen
        target: full_page
        analyzers:
          - type: ocr
            settings: { emit: { ready: true } }
  - id: b
    rule_pack: pack
    session: { interval_ms: 10 }
"""


def read(path, query):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


async def test_full_stack_persists_ticks_actions_and_health(tmp_path):
    db = str(tmp_path / "history.db")
    store = SqliteStateStore(db)
    persistence = PersistenceSink(store)
    supervisor = Supervisor(
        monitor=HealthMonitor(), sink=persistence.on_report, on_health=persistence.on_health
    )

    app = create_application(load_config_from_string(CONFIG), on_report=supervisor.on_report)
    supervisor.session_manager = app.manager

    await app.create_sessions()
    try:
        await app.scheduler.run_once()
    finally:
        await app.stop()
    store.close()  # flush the writer thread before reading

    ticks = read(db, "SELECT profile_id, status FROM ticks ORDER BY profile_id")
    assert ticks == [("a", "completed"), ("b", "completed")]

    # profile 'a' matched the rule and clicked; the action was persisted
    actions = read(
        db,
        "SELECT t.profile_id, a.action_type, a.status FROM actions a "
        "JOIN ticks t ON a.tick_id = t.id",
    )
    assert actions == [("a", "click", "succeeded")]

    # both sessions reported an initial healthy transition
    health = read(db, "SELECT profile_id, new_state FROM health_events ORDER BY profile_id")
    assert health == [("a", "healthy"), ("b", "healthy")]

    # metrics were captured
    durations = read(db, "SELECT duration_ms FROM ticks")
    assert all(d[0] is not None for d in durations)


async def test_runtime_continues_when_storage_fails(tmp_path):
    """A store that raises on every write must not stop the scheduler."""

    class BrokenStore(SqliteStateStore):
        def record_tick(self, tick):
            raise RuntimeError("disk gone")

    db = str(tmp_path / "h.db")
    store = BrokenStore(db)
    errors = []
    persistence = PersistenceSink(store, on_error=errors.append)
    supervisor = Supervisor(monitor=HealthMonitor(), sink=persistence.on_report)

    app = create_application(load_config_from_string(CONFIG), on_report=supervisor.on_report)
    supervisor.session_manager = app.manager

    await app.create_sessions()
    try:
        runs = await app.scheduler.run_once()  # must complete despite storage errors
    finally:
        await app.stop()
    store.close()

    assert len(runs) == 2  # both sessions ticked
    assert all(r.report is not None for r in runs)
    assert errors  # failures surfaced as observable errors
