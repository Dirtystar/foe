"""Failure-injection reliability suite.

Drives the real runtime (create_application + Scheduler + SessionManager +
Supervisor) over stub adapters, injecting faults at each boundary the audit
cares about, and asserts the system stays intact: the tick loop survives, the
fault is reported meaningfully, and after shutdown there are no leaked asyncio
tasks, no leaked threads, and no orphan tabs.
"""

from __future__ import annotations

import asyncio
import signal
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from bap.adapters.persistence.sqlite_store import SqliteStateStore
from bap.app.composition import create_application
from bap.app.plugins import PluginError, apply_analyzer_plugins
from bap.app.registries import ActionHandlerRegistry, AnalyzerRegistry
from bap.app.stubs import StubActionHandler, StubAnalyzer, StubCapturePort
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor, SessionHealth
from bap.core.ports.action_handler_port import ActionContext, ActionHandlerPort, ActionResult
from bap.core.ports.capture_port import CaptureError
from bap.core.ports.state_store_port import StorageError, TickRecord
from bap.core.ports.vision_analyzer_port import AnalyzerContext, VisionAnalyzerPort
from tests.loadkit import (
    FlakyCapture,
    TrackingBrowser,
    live_task_count,
    make_config,
    thread_count,
)

_DEV = "config/development.example.yaml"


# --- local harness ------------------------------------------------------------


def _build(
    *,
    n: int = 1,
    browser=None,
    capture=None,
    analyzer_registry=None,
    action_registry=None,
    recreate_after: int = 2,
    max_recovery_attempts: int = 3,
):
    reports: list = []
    recovery: list = []
    monitor = HealthMonitor(
        recreate_after=recreate_after, max_recovery_attempts=max_recovery_attempts
    )
    supervisor = Supervisor(monitor=monitor, sink=reports.append, task_runner=recovery.append)
    browser = browser or TrackingBrowser()
    capture = capture or StubCapturePort()
    app = create_application(
        load_config_from_string(make_config(n, interval_ms=5)),
        on_report=supervisor.on_report,
        browser=browser,
        capture_port=capture,
        analyzer_registry=analyzer_registry,
        action_registry=action_registry,
    )
    supervisor.session_manager = app.manager
    return SimpleNamespace(
        app=app, supervisor=supervisor, monitor=monitor, browser=browser,
        capture=capture, reports=reports, recovery=recovery,
    )


async def _rounds(env, n: int) -> None:
    if not env.app.manager.profile_ids:
        await env.app.create_sessions()
    for _ in range(n):
        await env.app.scheduler.run_once()
        while env.recovery:
            await env.recovery.pop(0)


class _RaisingAnalyzer(VisionAnalyzerPort):
    def __init__(self, name: str, exc: Exception) -> None:
        self._name = name
        self._exc = exc

    @property
    def name(self) -> str:
        return self._name

    async def analyze(self, image, context: AnalyzerContext):
        raise self._exc


class _RaisingHandler(ActionHandlerPort):
    def __init__(self, action_type: str) -> None:
        self._action_type = action_type

    @property
    def action_type(self) -> str:
        return self._action_type

    async def execute(self, request, context: ActionContext) -> ActionResult:
        raise RuntimeError("handler boom")


# --- 1. browser/capture crash during a tick -----------------------------------


async def test_crash_during_tick_is_reported_and_survives():
    baseline_tasks, baseline_threads = live_task_count(), thread_count()
    env = _build(capture=FlakyCapture(fail_plan={"s0": 2}), recreate_after=2)

    await _rounds(env, 4)  # ticks 1-2 fail, recovery recreates, then it recovers

    failed = [r for r in env.reports if r.error is not None]
    assert failed, "a failed tick must surface an error in its report"
    assert isinstance(failed[0].error, CaptureError)
    assert env.browser.opens["s0"] >= 2, "session was recovered after the crash"

    errors = await env.app.stop()
    assert errors == ()
    assert env.browser.list_tabs() == []
    assert live_task_count() == baseline_tasks
    assert thread_count() == baseline_threads


# --- 2. browser crash during recovery -----------------------------------------


class _CrashOnReopenBrowser(TrackingBrowser):
    """Opens the first tab fine, then crashes on every reopen — i.e. the browser
    dies exactly when recovery tries to recreate the session."""

    async def open_tab(self, profile):
        if self.opens.get(profile.id, 0) >= 1:
            self.opens[profile.id] += 1
            raise RuntimeError(f"browser crashed reopening {profile.id}")
        return await super().open_tab(profile)


async def test_crash_during_recovery_is_contained():
    baseline_tasks, baseline_threads = live_task_count(), thread_count()
    env = _build(
        browser=_CrashOnReopenBrowser(),
        capture=FlakyCapture(fail_plan={"s0": 10_000}),  # forces recovery
        recreate_after=1,
        max_recovery_attempts=3,
    )

    await _rounds(env, 6)  # recovery attempts all hit the crashing reopen

    # The broken session is dropped rather than thrashing or crashing the loop.
    assert env.monitor.health_of("s0") in (SessionHealth.FAILED, SessionHealth.RECOVERING)
    assert "s0" not in env.app.manager.profile_ids

    errors = await env.app.stop()
    assert env.browser.list_tabs() == []
    assert live_task_count() == baseline_tasks
    assert thread_count() == baseline_threads


# --- 3. analyzer timeout / exception (isolated as a vision failure) -----------


async def test_analyzer_timeout_is_isolated():
    registry = AnalyzerRegistry()
    registry.register("ocr", lambda: _RaisingAnalyzer("ocr", TimeoutError("analyzer timed out")))
    env = _build(analyzer_registry=registry)

    await _rounds(env, 1)

    report = env.reports[-1]
    assert report.vision is not None and report.vision.failures, "analyzer failure recorded"
    failure = report.vision.failures[0]
    assert failure.analyzer == "ocr"
    assert isinstance(failure.error, TimeoutError)
    # A failing analyzer is isolated into a well-formed VISION_FAILED report
    # (rules are conservatively skipped) — not a crash.
    assert report.status.value == "vision_failed"

    await env.app.stop()


# --- 4. action handler exception (isolated as a FAILED action) ----------------


async def test_action_handler_exception_is_isolated():
    actions = ActionHandlerRegistry()
    actions.register("click", lambda: _RaisingHandler("click"))
    # Stub analyzers still emit `ready`, so the rule matches and click fires.
    analyzers = AnalyzerRegistry()
    analyzers.register("ocr", lambda: StubAnalyzer("ocr"))
    env = _build(analyzer_registry=analyzers, action_registry=actions)

    await _rounds(env, 1)

    report = env.reports[-1]
    assert report.execution is not None and report.execution.failures, "action failure recorded"
    assert not any(r.succeeded for r in report.execution.results)
    assert report.status.value == "completed"  # a failing handler is not a crash

    await env.app.stop()


# --- 5. persistence failure during shutdown -----------------------------------


def _a_tick() -> TickRecord:
    from datetime import datetime, timezone

    return TickRecord(
        timestamp=datetime.now(timezone.utc), profile_id="s0", tick_number=1, status="completed"
    )


def test_persistence_failure_during_shutdown_is_isolated(tmp_path):
    seen: list[Exception] = []
    store = SqliteStateStore(str(tmp_path / "h.db"), on_error=seen.append)

    def boom(conn, dto):
        raise RuntimeError("disk gone")

    store._write_tick = boom  # type: ignore[assignment]
    store.record_tick(_a_tick())
    store.close()  # draining a failing write must not raise out of shutdown

    assert store.stats().failed >= 1
    assert seen, "the write failure was reported via on_error"
    store.close()  # idempotent


# --- 6. corrupted SQLite database ---------------------------------------------


def test_corrupted_database_fails_fast_with_a_clear_error(tmp_path):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not a sqlite database at all" * 10)

    with pytest.raises(StorageError) as exc:
        SqliteStateStore(str(corrupt))
    assert "cannot open store" in str(exc.value)


# --- 7. invalid plugin package ------------------------------------------------


class _BadEntryPoint:
    name = "explodes"

    def load(self):
        raise ImportError("no module named 'ghost'")


class _NonCallableEntryPoint:
    name = "not_callable"

    def load(self):
        return "i am a string, not a factory"


def test_invalid_plugin_import_fails_during_composition():
    registry = AnalyzerRegistry()
    with pytest.raises(PluginError) as exc:
        apply_analyzer_plugins(registry, entry_points=[_BadEntryPoint()])
    assert "failed to load" in str(exc.value)


def test_non_callable_plugin_is_rejected():
    registry = AnalyzerRegistry()
    with pytest.raises(PluginError, match="not callable"):
        apply_analyzer_plugins(registry, entry_points=[_NonCallableEntryPoint()])


# --- 8. SIGTERM during startup ------------------------------------------------


async def test_sigterm_during_startup_shuts_down_cleanly(monkeypatch):
    # Make the browser's start() slow so a signal can land mid-startup, before
    # the run loop reaches its wait.
    import bap.app.stubs as stubs

    original_start = stubs.StubBrowser.start

    async def slow_start(self):
        await asyncio.sleep(0.15)
        await original_start(self)

    monkeypatch.setattr(stubs.StubBrowser, "start", slow_start)

    from bap.main import run

    loop = asyncio.get_running_loop()
    previous = signal.getsignal(signal.SIGTERM)
    baseline_tasks, baseline_threads = live_task_count(), thread_count()

    task = asyncio.create_task(
        run(Path(_DEV), seconds=None, real=False, real_vision=False)
    )
    try:
        await asyncio.sleep(0.03)  # we are now inside the slow startup
        assert not task.done()
        signal.raise_signal(signal.SIGTERM)  # SIGTERM during startup
        await asyncio.wait_for(task, timeout=5.0)
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.remove_signal_handler(sig)
            except (ValueError, RuntimeError):
                pass
        signal.signal(signal.SIGTERM, previous)

    assert task.done() and task.exception() is None
    assert live_task_count() == baseline_tasks, "no leaked tasks after startup-time SIGTERM"
    assert thread_count() == baseline_threads
