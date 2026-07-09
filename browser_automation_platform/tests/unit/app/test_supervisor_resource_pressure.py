import pytest

from bap.app.supervisor import BROWSER_HEALTH_ID, Supervisor
from bap.core.engine.health import (
    HealthMonitor,
    ResourceAction,
    ResourcePressurePolicy,
    ResourcePressureState,
    SessionHealth,
)
from bap.core.ports.browser_metrics_port import BrowserResourceSnapshot


# --- policy classification ----------------------------------------------------


def test_policy_normal_when_no_breaches():
    policy = ResourcePressurePolicy()
    d = policy.observe(())
    assert d.state is ResourcePressureState.NORMAL
    assert d.action is ResourceAction.NONE


def test_policy_degrades_then_recovers_then_disables():
    policy = ResourcePressurePolicy(recover_after=2, disable_after=4)
    breach = ("memory 5000MB > 4096MB",)

    states = [policy.observe(breach) for _ in range(5)]

    assert states[0].state is ResourcePressureState.DEGRADED
    assert states[0].action is ResourceAction.NONE
    assert states[1].action is ResourceAction.RECOVER  # at recover_after
    assert states[1].state is ResourcePressureState.CRITICAL
    assert states[2].action is ResourceAction.NONE  # holding critical
    assert states[3].action is ResourceAction.DISABLE  # at disable_after
    assert states[4].action is ResourceAction.NONE  # already disabled


def test_policy_resets_on_recovery():
    policy = ResourcePressurePolicy(recover_after=2, disable_after=4)
    policy.observe(("x",))
    policy.observe(("x",))  # RECOVER
    d = policy.observe(())  # back within limits
    assert d.state is ResourcePressureState.NORMAL
    # counter reset: two more breaches needed to recover again
    assert policy.observe(("x",)).action is ResourceAction.NONE
    assert policy.observe(("x",)).action is ResourceAction.RECOVER


def test_policy_rejects_bad_thresholds():
    with pytest.raises(ValueError):
        ResourcePressurePolicy(recover_after=5, disable_after=3)


# --- supervisor integration ---------------------------------------------------


class FakeManager:
    def __init__(self, profile_ids=("a", "b")):
        self._profile_ids = tuple(profile_ids)
        self.recovered = []
        self.closed = []

    @property
    def profile_ids(self):
        return self._profile_ids

    async def recover_session(self, pid):
        self.recovered.append(pid)

    async def close_session(self, pid):
        self.closed.append(pid)


def snap():
    return BrowserResourceSnapshot("browser", pages=20, memory_mb=5000.0)


def make_supervisor(manager, health_log):
    tasks = []
    sup = Supervisor(
        monitor=HealthMonitor(),
        session_manager=manager,
        on_health=lambda p, h, r: health_log.append((p, h)),
        task_runner=tasks.append,
        resource_policy=ResourcePressurePolicy(recover_after=2, disable_after=4),
    )
    return sup, tasks


async def _drain(tasks):
    while tasks:
        await tasks.pop(0)


async def test_brief_pressure_emits_browser_health_only():
    manager = FakeManager()
    health = []
    sup, tasks = make_supervisor(manager, health)

    sup.note_resource_pressure(snap(), ("memory 5000MB > 4096MB",))
    await _drain(tasks)

    assert (BROWSER_HEALTH_ID, SessionHealth.DEGRADED) in health
    assert manager.recovered == []  # no action yet


async def test_sustained_pressure_recovers_all_sessions():
    manager = FakeManager(("a", "b", "c"))
    health = []
    sup, tasks = make_supervisor(manager, health)

    sup.note_resource_pressure(snap(), ("memory 5000MB > 4096MB",))
    sup.note_resource_pressure(snap(), ("memory 5000MB > 4096MB",))  # recover_after=2
    await _drain(tasks)

    assert sorted(manager.recovered) == ["a", "b", "c"]  # all reclaimed


async def test_persistent_pressure_disables_all_sessions():
    manager = FakeManager(("a", "b"))
    health = []
    sup, tasks = make_supervisor(manager, health)

    for _ in range(4):  # disable_after=4
        sup.note_resource_pressure(snap(), ("memory 5000MB > 4096MB",))
        await _drain(tasks)

    assert sorted(manager.closed) == ["a", "b"]


async def test_recovery_from_pressure_clears_browser_health():
    manager = FakeManager()
    health = []
    sup, tasks = make_supervisor(manager, health)

    sup.note_resource_pressure(snap(), ("memory 5000MB > 4096MB",))  # degraded
    sup.note_resource_pressure(snap(), ())  # back to normal
    await _drain(tasks)

    healths = [h for p, h in health if p == BROWSER_HEALTH_ID]
    assert SessionHealth.HEALTHY in healths
