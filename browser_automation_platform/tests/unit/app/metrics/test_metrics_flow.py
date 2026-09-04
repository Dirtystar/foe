"""Integration: real SQLite history produced by a run, read back as metrics."""

import pytest

from bap.adapters.persistence.sqlite_store import SqliteStateStore
from bap.app.composition import create_application
from bap.app.metrics.repository import MetricsRepository
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


async def test_metrics_reflect_a_real_persisted_run(tmp_path):
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
        for _ in range(3):
            await app.scheduler.run_once()  # 3 ticks per profile
    finally:
        await app.stop()
    store.close()

    repo = MetricsRepository(db)
    try:
        overview = repo.overview()
        assert overview.total_ticks == 6  # 2 profiles x 3 ticks
        assert overview.successful_ticks == 6
        assert overview.error_rate == 0.0
        assert overview.avg_duration_ms is not None

        profiles = {p.profile_id: p for p in repo.per_profile()}
        assert profiles["a"].ticks == 3
        assert profiles["b"].ticks == 3
        assert profiles["a"].health == "healthy"

        actions = repo.actions()
        assert actions.total == 3  # profile a clicked each of its 3 ticks
        assert actions.successful == 3
    finally:
        repo.close()
