import asyncio

import pytest

from bap.app.composition import Application, create_application
from bap.app.errors import CompositionError
from bap.app.registries import ActionHandlerRegistry, AnalyzerRegistry
from bap.app.stubs import StubActionHandler, StubAnalyzer, StubBrowser, StubCapturePort
from bap.config.config_loader import load_config_from_string
from bap.core.engine.scheduler import Scheduler
from bap.core.ports.action_handler_port import ActionResult, ActionStatus
from bap.core.rules.rule_engine import RuleStatus

CONFIG = """
settings:
  max_sessions: 5
rule_packs:
  default:
    - id: click_when_low
      condition:
        type: compare
        field: header.count
        op: less_than
        value: 100
      actions:
        - type: click
          params: { target: main }
profiles:
  - id: profile_01
    rule_pack: default
    session: { interval_ms: 10 }
    capture_bindings:
      - name: header
        target: full_page
        analyzers:
          - type: ocr
            settings: { emit: { count: 42 } }
  - id: profile_02
    rule_pack: default
    session: { interval_ms: 10 }
"""


def load(text: str = CONFIG):
    return load_config_from_string(text)


async def _instant_sleep(seconds: float) -> None:
    await asyncio.sleep(0)


# --- construction -------------------------------------------------------------


def test_create_application_returns_wired_application():
    app = create_application(load())

    assert isinstance(app, Application)
    assert app.manager is not None
    assert app.scheduler is not None
    assert [s.profile_id for s in app.session_specs] == ["profile_01", "profile_02"]


def test_construction_does_not_start_anything():
    browser = StubBrowser()
    app = create_application(load(), browser=browser)

    assert browser.started is False  # building never starts the browser
    assert not app.scheduler.running
    assert app.manager.session_count == 0


async def test_profiles_create_expected_sessions():
    app = create_application(load(), scheduler=Scheduler(sleep=_instant_sleep))

    await app.create_sessions()
    try:
        assert app.manager.profile_ids == ("profile_01", "profile_02")
        assert app.browser.started is True
    finally:
        await app.stop()


# --- translation reaches runtime behaviour ------------------------------------


async def test_rules_and_actions_wired_so_matching_rule_fires_handler():
    calls: list = []

    class Recorder(StubActionHandler):
        async def execute(self, request, context):
            calls.append(request)
            return ActionResult(request=request, status=ActionStatus.SUCCEEDED)

    analyzers = AnalyzerRegistry()
    analyzers.register("ocr", lambda: StubAnalyzer("ocr"))
    actions = ActionHandlerRegistry()
    actions.register("click", lambda: Recorder("click"))

    scheduler = Scheduler()
    app = create_application(
        load(), analyzer_registry=analyzers, action_registry=actions, scheduler=scheduler
    )
    await app.create_sessions()

    runs = await scheduler.run_once()

    # profile_01's stub OCR emits header.count=42; rule fires -> click recorded.
    p1_run = next(r for r in runs if r.profile_id == "profile_01")
    assert p1_run.report.status.name == "COMPLETED"
    assert p1_run.report.page_state.value_of("header.count") == 42
    assert p1_run.report.evaluation.results[0].status is RuleStatus.MATCHED
    assert [r.action_type for r in calls] == ["click"]
    assert calls[0].rule_id == "click_when_low"  # provenance survived translation + engine
    await app.stop()


async def test_profile_without_matching_observation_takes_no_action():
    scheduler = Scheduler()
    app = create_application(load(), scheduler=scheduler)
    await app.create_sessions()

    runs = await scheduler.run_once()

    p2_run = next(r for r in runs if r.profile_id == "profile_02")  # no analyzers
    assert p2_run.report.status.name == "COMPLETED"
    assert p2_run.report.evaluation.results[0].status is RuleStatus.NOT_MATCHED
    await app.stop()


# --- dependency injection -----------------------------------------------------


def test_injected_dependencies_are_used_by_identity():
    browser = StubBrowser()
    capture = StubCapturePort()
    scheduler = Scheduler()
    app = create_application(load(), browser=browser, capture_port=capture, scheduler=scheduler)

    assert app.browser is browser
    assert app.scheduler is scheduler
    # capture_port is wired into sessions, not held on the app; identity is
    # exercised through the running-tick tests above.


def test_max_sessions_flows_from_config_settings():
    app = create_application(load())
    # SessionManager enforces it; the value came from settings.max_sessions=5.
    assert app.manager._max_sessions == 5  # noqa: SLF001 - asserting wiring


# --- fail before runtime ------------------------------------------------------


def test_unknown_action_type_fails_before_runtime_creation():
    text = CONFIG.replace("type: click", "type: teleport")
    browser = StubBrowser()

    with pytest.raises(CompositionError, match="no handler registered"):
        create_application(load(text), browser=browser)

    assert browser.started is False  # nothing ran


def test_unknown_analyzer_type_fails_before_runtime_creation():
    text = CONFIG.replace("type: ocr", "type: telepathy")

    with pytest.raises(CompositionError, match="no analyzer registered"):
        create_application(load(text))


def test_unknown_comparison_op_fails_during_construction():
    text = CONFIG.replace("op: less_than", "op: approximately")

    with pytest.raises(CompositionError, match="unknown comparison op"):
        create_application(load(text))


# --- independence / no global state -------------------------------------------


def test_two_applications_from_same_config_are_independent():
    config = load()
    app_a = create_application(config)
    app_b = create_application(config)

    assert app_a is not app_b
    assert app_a.manager is not app_b.manager
    assert app_a.scheduler is not app_b.scheduler
    assert app_a.browser is not app_b.browser


async def test_running_one_application_does_not_affect_another():
    app_a = create_application(load(), scheduler=Scheduler(sleep=_instant_sleep))
    app_b = create_application(load(), scheduler=Scheduler(sleep=_instant_sleep))

    await app_a.create_sessions()
    try:
        assert app_b.manager.session_count == 0  # b untouched by a
        assert app_b.browser.started is False
    finally:
        await app_a.stop()


async def test_application_restartable_after_stop():
    app = create_application(load(), scheduler=Scheduler(sleep=_instant_sleep))

    await app.create_sessions()
    await app.stop()
    await app.create_sessions()  # same specs, fresh run
    try:
        assert app.manager.profile_ids == ("profile_01", "profile_02")
    finally:
        await app.stop()
