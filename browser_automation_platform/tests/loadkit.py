"""Shared harness for load/stress scenarios.

Everything is built from the real runtime (create_application, Scheduler,
SessionManager, Supervisor, persistence) wired to stub adapters — no
architecture is bypassed and no test-only hooks are added to production code.
Drivers are deterministic (run_once + drained recovery) unless a scenario
explicitly needs real-time scheduling.
"""

from __future__ import annotations

import asyncio
import gc
import threading
from collections import Counter
from dataclasses import dataclass, field

from bap.app.composition import create_application
from bap.app.stubs import StubBrowser, StubCapturePort
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor
from bap.core.ports.capture_port import CaptureError

# --- configuration builders ---------------------------------------------------


def make_config(n_sessions: int, *, interval_ms: int = 10, jitter_ms: int = 0) -> str:
    """N profiles, each with a stub OCR that emits `ready`, so every tick
    matches one rule and performs one (stub) click — the heaviest steady
    state for rules/actions/persistence."""
    profiles = "\n".join(
        f"""  - id: s{i}
    rule_pack: pack
    session: {{ interval_ms: {interval_ms}, jitter_ms: {jitter_ms} }}
    capture_bindings:
      - name: screen
        target: full_page
        analyzers:
          - type: ocr
            settings: {{ emit: {{ ready: true }} }}"""
        for i in range(n_sessions)
    )
    return f"""
settings:
  max_sessions: {max(n_sessions, 1)}
rule_packs:
  pack:
    - id: click_ready
      condition: {{ type: exists, field: screen.ready }}
      actions:
        - type: click
          params: {{ selector: "#x" }}
profiles:
{profiles}
"""


class FlakyCapture(StubCapturePort):
    """Fails a chosen profile's captures per a schedule, else succeeds.

    `fail_plan` maps tab_id -> number of leading captures to fail. Use a huge
    number to simulate a permanently broken tab.
    """

    def __init__(self, fail_plan: dict[str, int] | None = None):
        self.fail_plan = dict(fail_plan or {})
        self.calls: Counter[str] = Counter()

    async def capture(self, tab, target=None):
        limit = self.fail_plan.get(tab.tab_id, 0)
        if self.calls[tab.tab_id] < limit:
            self.calls[tab.tab_id] += 1
            raise CaptureError(f"simulated capture failure on {tab.tab_id}")
        return await super().capture(tab, target)


class TrackingBrowser(StubBrowser):
    """Counts tab opens/closes per profile for lifecycle assertions."""

    def __init__(self):
        super().__init__()
        self.opens: Counter[str] = Counter()
        self.closes: Counter[str] = Counter()

    async def open_tab(self, profile):
        self.opens[profile.id] += 1
        return await super().open_tab(profile)

    async def close_tab(self, tab):
        self.closes[tab.tab_id] += 1
        return await super().close_tab(tab)


# --- environment --------------------------------------------------------------


@dataclass
class LoadEnv:
    app: object
    supervisor: Supervisor
    monitor: HealthMonitor
    browser: TrackingBrowser
    capture: StubCapturePort
    reports: Counter = field(default_factory=Counter)
    recovery_tasks: list = field(default_factory=list)

    async def run_rounds(self, rounds: int) -> None:
        """Deterministic driver: tick every session once per round, then run
        any recovery the supervisor scheduled."""
        for _ in range(rounds):
            await self.app.scheduler.run_once()
            while self.recovery_tasks:
                await self.recovery_tasks.pop(0)


def build_env(
    n_sessions: int,
    *,
    interval_ms: int = 10,
    capture: StubCapturePort | None = None,
    downstream_sink=None,
    recreate_after: int = 2,
    max_recovery_attempts: int = 3,
) -> LoadEnv:
    """Build a runtime over stub adapters. `downstream_sink` (e.g. a
    persistence sink's on_report) is chained after the report counter."""
    reports: Counter = Counter()
    recovery_tasks: list = []

    def counting_sink(report):
        reports[report.status.value] += 1
        if downstream_sink is not None:
            downstream_sink(report)

    monitor = HealthMonitor(
        recreate_after=recreate_after, max_recovery_attempts=max_recovery_attempts
    )
    supervisor = Supervisor(
        monitor=monitor, sink=counting_sink, task_runner=recovery_tasks.append
    )

    browser = TrackingBrowser()
    capture = capture or StubCapturePort()
    app = create_application(
        load_config_from_string(make_config(n_sessions, interval_ms=interval_ms)),
        on_report=supervisor.on_report,
        browser=browser,
        capture_port=capture,
    )
    supervisor.session_manager = app.manager

    return LoadEnv(
        app=app,
        supervisor=supervisor,
        monitor=monitor,
        browser=browser,
        capture=capture,
        reports=reports,
        recovery_tasks=recovery_tasks,
    )


# --- measurement --------------------------------------------------------------


def live_task_count() -> int:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return 0
    return len([t for t in asyncio.all_tasks(loop) if not t.done()])


def thread_count() -> int:
    return threading.active_count()


def object_count() -> int:
    gc.collect()
    return len(gc.get_objects())
