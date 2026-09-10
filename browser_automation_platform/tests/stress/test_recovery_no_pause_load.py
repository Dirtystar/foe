"""16 sessions, live scheduler, continuous failures/recoveries: no pause, no
starvation. Recovery runs for real (replace_job) via the supervisor."""

import asyncio
from collections import Counter

import pytest

from bap.app.composition import create_application
from bap.app.stubs import StubCapturePort
from bap.app.supervisor import Supervisor
from bap.config.config_loader import load_config_from_string
from bap.core.engine.health import HealthMonitor
from bap.core.engine.scheduler import Scheduler
from bap.core.ports.capture_port import CaptureError

pytestmark = pytest.mark.stress

FLAKY = {"s0", "s3", "s7"}


def _config(n):
    profiles = "\n".join(
        f"""  - id: s{i}
    rule_pack: pack
    session: {{ interval_ms: 5 }}
    capture_bindings:
      - name: screen
        target: full_page
        analyzers:
          - type: ocr
            settings: {{ emit: {{ ready: true }} }}"""
        for i in range(n)
    )
    return f"""
settings: {{ max_sessions: {n} }}
rule_packs:
  pack:
    - id: click
      condition: {{ type: exists, field: screen.ready }}
      actions:
        - type: click
          params: {{ selector: "#x" }}
profiles:
{profiles}
"""


class RepeatingFlakyCapture(StubCapturePort):
    """Flaky profiles fail 2 consecutive captures every 10 -> periodic
    recovery; others always succeed."""

    def __init__(self):
        self.calls: Counter[str] = Counter()

    async def capture(self, tab, target=None):
        if tab.tab_id in FLAKY:
            phase = self.calls[tab.tab_id] % 10
            self.calls[tab.tab_id] += 1
            if phase < 2:
                raise CaptureError(f"periodic failure on {tab.tab_id}")
        return await super().capture(tab, target)


async def test_16_sessions_recover_continuously_without_pause_or_starvation(capsys):
    n = 16
    reports: Counter = Counter()
    recoveries: Counter = Counter()

    def sink(r):
        reports[r.profile_id] += 1

    def on_health(pid, health, reason):
        if health.value == "recovering":
            recoveries[pid] += 1

    monitor = HealthMonitor(recreate_after=2, max_recovery_attempts=10_000)  # keep recovering
    supervisor = Supervisor(
        monitor=monitor, sink=sink, on_health=on_health, task_runner=asyncio.ensure_future
    )
    scheduler = Scheduler(sleep=lambda s: asyncio.sleep(0), on_report=supervisor.on_report)

    from loadkit import TrackingBrowser

    browser = TrackingBrowser()
    app = create_application(
        load_config_from_string(_config(n)),
        browser=browser,
        capture_port=RepeatingFlakyCapture(),
        scheduler=scheduler,
    )
    supervisor.session_manager = app.manager

    paused = {"seen": False}

    async def watch_running():
        for _ in range(30_000):
            if not scheduler.running:
                paused["seen"] = True
            await asyncio.sleep(0)

    await app.start()
    watcher = asyncio.create_task(watch_running())
    try:
        # let the system run until every session has ticked a healthy amount
        await _wait_until(
            lambda: all(reports[f"s{i}"] >= 15 for i in range(n)), tries=200_000
        )
    finally:
        watcher.cancel()
        await app.stop()

    with capsys.disabled():
        least = min(reports[f"s{i}"] for i in range(n))
        most = max(reports[f"s{i}"] for i in range(n))
        print(
            f"\n[stress] 16 sessions | ticks per session: min={least} max={most} "
            f"| recoveries={sum(recoveries.values())} | scheduler paused={paused['seen']}"
        )

    assert not paused["seen"]  # scheduler never stopped during recovery
    assert all(reports[f"s{i}"] >= 15 for i in range(n))  # no starvation
    assert sum(recoveries.values()) > 0  # flaky sessions actually recovered
    assert all(recoveries[p] > 0 for p in FLAKY)  # each flaky one recovered
    # non-flaky sessions were never recreated
    assert all(browser.opens[f"s{i}"] == 1 for i in range(n) if f"s{i}" not in FLAKY)


async def _wait_until(predicate, *, tries=200_000):
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition never met")
