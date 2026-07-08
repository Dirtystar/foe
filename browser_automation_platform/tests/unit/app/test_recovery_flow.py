"""End-to-end recovery with a simulated browser failure.

Uses the real Scheduler, SessionManager, and Supervisor with stub adapters —
one capture port that fails a session's first few ticks, then succeeds — and
verifies the failing session recovers while the other keeps ticking. Fully
deterministic (driven by run_once + draining recovery tasks; no timers).
"""

from collections import Counter

import pytest

from bap.app.composition import create_application
from bap.app.stubs import StubBrowser, StubCapturePort
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor, SessionHealth
from bap.core.engine.tab_session import TickStatus
from bap.core.ports.capture_port import CaptureError

CONFIG = """
rule_packs:
  noop: []
profiles:
  - id: a
    rule_pack: noop
    session: { interval_ms: 10 }
    capture_bindings:
      - name: screen
        target: full_page
        analyzers:
          - type: ocr
  - id: b
    rule_pack: noop
    session: { interval_ms: 10 }
    capture_bindings:
      - name: screen
        target: full_page
        analyzers:
          - type: ocr
"""


class FlakyCapture(StubCapturePort):
    """Fails the first `fail_times` captures for one profile, then succeeds."""

    def __init__(self, fail_for: str, fail_times: int):
        self._fail_for = fail_for
        self._fail_times = fail_times
        self.calls: Counter[str] = Counter()

    async def capture(self, tab, target=None):
        if tab.tab_id == self._fail_for and self.calls[tab.tab_id] < self._fail_times:
            self.calls[tab.tab_id] += 1
            raise CaptureError("simulated transient capture failure")
        return await super().capture(tab, target)


class TrackingBrowser(StubBrowser):
    def __init__(self):
        super().__init__()
        self.opens: Counter[str] = Counter()

    async def open_tab(self, profile):
        self.opens[profile.id] += 1
        return await super().open_tab(profile)


async def test_failing_session_recovers_while_other_keeps_ticking():
    reports = []
    health = []
    pending = []

    monitor = HealthMonitor(recreate_after=2, max_recovery_attempts=3)
    supervisor = Supervisor(
        monitor=monitor,
        sink=reports.append,
        on_health=lambda p, h, r: health.append((p, h)),
        task_runner=pending.append,  # capture recovery coroutines for deterministic draining
    )

    browser = TrackingBrowser()
    app = create_application(
        load_config_from_string(CONFIG),
        on_report=supervisor.on_report,
        browser=browser,
        capture_port=FlakyCapture(fail_for="a", fail_times=2),
    )
    supervisor.session_manager = app.manager

    await app.create_sessions()
    try:
        for _ in range(4):
            await app.scheduler.run_once()
            while pending:
                await pending.pop(0)  # perform any scheduled recovery now
    finally:
        await app.stop()

    a_reports = [r.status for r in reports if r.profile_id == "a"]
    b_reports = [r.status for r in reports if r.profile_id == "b"]

    # 'a' failed transiently, was recovered, and resumed completing
    assert TickStatus.CAPTURE_FAILED in a_reports
    assert a_reports[-1] is TickStatus.COMPLETED
    assert monitor.health_of("a") is SessionHealth.HEALTHY
    assert ("a", SessionHealth.RECOVERING) in health

    # the tab was actually recreated (opened once at start, once on recovery)
    assert browser.opens["a"] == 2

    # 'b' was never affected — it completed every tick and was opened once
    assert b_reports and all(s is TickStatus.COMPLETED for s in b_reports)
    assert browser.opens["b"] == 1


async def test_persistently_failing_session_is_disabled_not_looped():
    reports = []
    pending = []
    monitor = HealthMonitor(recreate_after=1, max_recovery_attempts=2)
    supervisor = Supervisor(monitor=monitor, sink=reports.append, task_runner=pending.append)

    app = create_application(
        load_config_from_string(CONFIG),
        on_report=supervisor.on_report,
        browser=StubBrowser(),
        capture_port=FlakyCapture(fail_for="a", fail_times=10_000),  # never recovers
    )
    supervisor.session_manager = app.manager

    await app.create_sessions()
    try:
        for _ in range(8):
            await app.scheduler.run_once()
            while pending:
                await pending.pop(0)
        active = tuple(app.manager.profile_ids)  # capture before shutdown clears it
    finally:
        await app.stop()

    # 'a' gave up and was disabled (removed), so it stops ticking; 'b' remains
    assert monitor.health_of("a") is SessionHealth.FAILED
    assert "b" in active
    assert "a" not in active
