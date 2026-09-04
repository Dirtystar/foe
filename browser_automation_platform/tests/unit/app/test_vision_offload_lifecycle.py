"""Vision offload wiring + executor lifecycle through create_application."""

import threading

import pytest

from bap.app.composition import create_application
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor
from bap.core.rules.rule_engine import RuleStatus

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
"""


def _vision_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name.startswith("bap-vision"))


def test_no_executor_when_vision_workers_is_none():
    app = create_application(load_config_from_string(CONFIG))
    assert app.vision_executor is None


async def test_offloaded_vision_produces_same_result_and_cleans_up():
    reports = []
    supervisor = Supervisor(monitor=HealthMonitor(), sink=reports.append)
    app = create_application(
        load_config_from_string(CONFIG), on_report=supervisor.on_report, vision_workers=2
    )
    supervisor.session_manager = app.manager

    assert app.vision_executor is not None
    before = _vision_threads()

    await app.create_sessions()
    try:
        await app.scheduler.run_once()
    finally:
        await app.stop()

    # same functional result as inline: OCR emitted ready -> rule matched -> click
    report = reports[-1]
    assert report.completed
    assert report.evaluation.results[0].status is RuleStatus.MATCHED
    assert report.execution.fully_succeeded

    # executor was shut down; worker threads are gone
    assert app.vision_executor._shutdown is True  # noqa: SLF001
    assert _vision_threads() <= before


async def test_shutdown_waits_for_inflight_analyzers():
    supervisor = Supervisor(monitor=HealthMonitor(), sink=lambda r: None)
    app = create_application(
        load_config_from_string(CONFIG), on_report=supervisor.on_report, vision_workers=4
    )
    supervisor.session_manager = app.manager
    await app.create_sessions()
    await app.scheduler.run_once()

    await app.stop()  # shutdown(wait=True) -> no bap-vision threads survive

    assert _vision_threads() == 0
