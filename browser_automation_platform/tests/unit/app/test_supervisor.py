from datetime import datetime, timezone

import pytest

from bap.app.supervisor import Supervisor
from bap.core.engine.health import HealthMonitor, SessionHealth
from bap.core.engine.tab_session import TickReport, TickStatus


def report(profile_id="p1", status=TickStatus.COMPLETED) -> TickReport:
    now = datetime.now(timezone.utc)
    return TickReport(
        profile_id=profile_id, tick_number=1, status=status, started_at=now, finished_at=now
    )


class FakeManager:
    def __init__(self, *, recover_fails=False):
        self.recovered = []
        self.closed = []
        self._recover_fails = recover_fails

    async def recover_session(self, profile_id):
        self.recovered.append(profile_id)
        if self._recover_fails:
            raise RuntimeError("open_tab failed")
        return profile_id

    async def close_session(self, profile_id):
        self.closed.append(profile_id)


def make_supervisor(manager=None, *, health_log=None):
    tasks = []
    supervisor = Supervisor(
        monitor=HealthMonitor(recreate_after=2),
        session_manager=manager,
        sink=None,
        on_health=(lambda p, h, r: health_log.append((p, h))) if health_log is not None else None,
        task_runner=tasks.append,  # capture coroutines instead of scheduling them
    )
    return supervisor, tasks


async def _drain(tasks):
    while tasks:
        await tasks.pop(0)


# --- forwarding ---------------------------------------------------------------


def test_reports_are_forwarded_to_the_sink():
    seen = []
    supervisor = Supervisor(monitor=HealthMonitor(), sink=seen.append)

    r = report()
    supervisor.on_report(r)

    assert seen == [r]


# --- recovery triggering ------------------------------------------------------


async def test_two_transient_failures_trigger_recovery():
    manager = FakeManager()
    supervisor, tasks = make_supervisor(manager)

    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))
    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))
    await _drain(tasks)

    assert manager.recovered == ["p1"]


async def test_duplicate_recovery_is_suppressed_while_in_flight():
    manager = FakeManager()
    supervisor, tasks = make_supervisor(manager)

    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))
    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))  # triggers recovery
    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))  # in-flight -> suppressed

    assert len(tasks) == 1  # only one recovery scheduled
    await _drain(tasks)


async def test_recovery_failure_marks_failed_and_reports():
    manager = FakeManager(recover_fails=True)
    health_log = []
    supervisor, tasks = make_supervisor(manager, health_log=health_log)

    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))
    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))
    await _drain(tasks)

    assert ("p1", SessionHealth.FAILED) in health_log


async def test_permanent_failure_disables_the_session():
    manager = FakeManager()
    supervisor, tasks = make_supervisor(manager)

    supervisor.on_report(report(status=TickStatus.INTERNAL_ERROR))
    await _drain(tasks)

    assert manager.closed == ["p1"]


# --- health emission ----------------------------------------------------------


def test_health_is_emitted_only_on_change():
    health_log = []
    supervisor, _ = make_supervisor(FakeManager(), health_log=health_log)

    supervisor.on_report(report(status=TickStatus.COMPLETED))
    supervisor.on_report(report(status=TickStatus.COMPLETED))  # still healthy -> no repeat
    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))  # degraded -> change

    healths = [h for _, h in health_log]
    assert healths == [SessionHealth.HEALTHY, SessionHealth.DEGRADED]


def test_recovery_not_triggered_without_a_session_manager():
    supervisor, tasks = make_supervisor(manager=None)

    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))
    supervisor.on_report(report(status=TickStatus.CAPTURE_FAILED))

    assert tasks == []  # nothing to recover through


def test_two_supervisors_do_not_share_state():
    a, _ = make_supervisor(FakeManager())
    b, _ = make_supervisor(FakeManager())

    a.on_report(report(status=TickStatus.CAPTURE_FAILED))

    # b has seen nothing; its monitor is independent
    assert b._monitor.health_of("p1") is SessionHealth.HEALTHY  # noqa: SLF001
