"""Operational status: lifecycle transitions and health-derived degradation."""

from __future__ import annotations

from bap.core.engine.health import SessionHealth
from bap.ops.status import OperationalState, OperationalStatus


def _recorder():
    changes: list[tuple[OperationalStatus, str]] = []
    return changes, lambda status, reason: changes.append((status, reason))


def test_transition_notifies_on_change() -> None:
    changes, on_change = _recorder()
    state = OperationalState(on_change)
    state.transition(OperationalStatus.STARTING, "boot")
    state.transition(OperationalStatus.READY, "up")
    assert state.status is OperationalStatus.READY
    assert changes == [
        (OperationalStatus.STARTING, "boot"),
        (OperationalStatus.READY, "up"),
    ]


def test_transition_to_same_status_is_noop() -> None:
    changes, on_change = _recorder()
    state = OperationalState(on_change)
    state.transition(OperationalStatus.READY)
    changes.clear()
    state.transition(OperationalStatus.READY)
    assert changes == []


def test_health_derives_degraded_while_running() -> None:
    changes, on_change = _recorder()
    state = OperationalState(on_change)
    state.transition(OperationalStatus.READY)
    state.observe_health("p1", SessionHealth.DEGRADED, "flaky")
    assert state.status is OperationalStatus.DEGRADED
    # recovering back to healthy returns to ready
    state.observe_health("p1", SessionHealth.HEALTHY, "recovered")
    assert state.status is OperationalStatus.READY


def test_degraded_requires_all_sessions_healthy_to_recover() -> None:
    state = OperationalState()
    state.transition(OperationalStatus.READY)
    state.observe_health("p1", SessionHealth.FAILED, "dead")
    state.observe_health("p2", SessionHealth.HEALTHY, "ok")
    assert state.status is OperationalStatus.DEGRADED
    state.observe_health("p1", SessionHealth.HEALTHY, "back")
    assert state.status is OperationalStatus.READY


def test_health_ignored_when_not_running() -> None:
    changes, on_change = _recorder()
    state = OperationalState(on_change)
    state.transition(OperationalStatus.STARTING)
    changes.clear()
    state.observe_health("p1", SessionHealth.FAILED, "too early")
    assert state.status is OperationalStatus.STARTING
    assert changes == []


def test_stopping_clears_health_for_clean_restart() -> None:
    state = OperationalState()
    state.transition(OperationalStatus.READY)
    state.observe_health("p1", SessionHealth.FAILED, "dead")
    assert state.status is OperationalStatus.DEGRADED
    state.transition(OperationalStatus.STOPPING, "shutdown")
    state.transition(OperationalStatus.STOPPED, "stopped")
    # A fresh start must not inherit the old failed health.
    state.transition(OperationalStatus.READY, "restart")
    state.observe_health("p1", SessionHealth.HEALTHY, "ok")
    assert state.status is OperationalStatus.READY
