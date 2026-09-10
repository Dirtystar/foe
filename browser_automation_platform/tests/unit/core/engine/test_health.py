from datetime import datetime, timezone

import pytest

from bap.core.engine.health import (
    FailureClass,
    HealthMonitor,
    RecoveryAction,
    SessionHealth,
    classify,
)
from bap.core.engine.tab_session import TickReport, TickStatus


def report(profile_id="p1", status=TickStatus.COMPLETED, error=None) -> TickReport:
    now = datetime.now(timezone.utc)
    return TickReport(
        profile_id=profile_id,
        tick_number=1,
        status=status,
        started_at=now,
        finished_at=now,
        error=error,
    )


# --- classification -----------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        (TickStatus.COMPLETED, FailureClass.NONE),
        (TickStatus.CAPTURE_FAILED, FailureClass.TRANSIENT),
        (TickStatus.VISION_FAILED, FailureClass.TRANSIENT),
        (TickStatus.INTERNAL_ERROR, FailureClass.PERMANENT),
    ],
)
def test_classify_maps_status_to_failure_class(status, expected):
    assert classify(report(status=status)) is expected


# --- monitor policy -----------------------------------------------------------


def test_healthy_tick_is_healthy_with_no_action():
    monitor = HealthMonitor()

    decision = monitor.observe(report(status=TickStatus.COMPLETED))

    assert decision.health is SessionHealth.HEALTHY
    assert decision.action is RecoveryAction.NONE
    assert not decision.should_recover


def test_first_transient_failure_degrades_but_keeps_ticking():
    monitor = HealthMonitor(recreate_after=2)

    decision = monitor.observe(report(status=TickStatus.CAPTURE_FAILED))

    assert decision.health is SessionHealth.DEGRADED
    assert decision.action is RecoveryAction.SKIP_TEMPORARILY


def test_consecutive_transient_failures_trigger_recreate():
    monitor = HealthMonitor(recreate_after=2)

    monitor.observe(report(status=TickStatus.CAPTURE_FAILED))
    decision = monitor.observe(report(status=TickStatus.CAPTURE_FAILED))

    assert decision.health is SessionHealth.RECOVERING
    assert decision.action is RecoveryAction.RECREATE_SESSION
    assert decision.should_recover


def test_permanent_failure_disables_immediately():
    monitor = HealthMonitor()

    decision = monitor.observe(report(status=TickStatus.INTERNAL_ERROR))

    assert decision.health is SessionHealth.FAILED
    assert decision.action is RecoveryAction.MARK_DISABLED
    assert decision.should_disable


def test_healthy_tick_resets_counters():
    monitor = HealthMonitor(recreate_after=2)
    monitor.observe(report(status=TickStatus.CAPTURE_FAILED))
    monitor.observe(report(status=TickStatus.COMPLETED))  # recovered

    # counter was reset, so a single failure degrades again (not recreate)
    decision = monitor.observe(report(status=TickStatus.CAPTURE_FAILED))

    assert decision.action is RecoveryAction.SKIP_TEMPORARILY


def test_recovery_attempts_are_bounded_then_disabled():
    monitor = HealthMonitor(recreate_after=1, max_recovery_attempts=2)

    actions = [monitor.observe(report(status=TickStatus.CAPTURE_FAILED)).action for _ in range(5)]

    # recreate, recreate, then give up (disable) and stay disabled — never loops
    assert actions[0] is RecoveryAction.RECREATE_SESSION
    assert actions[1] is RecoveryAction.RECREATE_SESSION
    assert actions[2] is RecoveryAction.MARK_DISABLED
    assert all(a is RecoveryAction.MARK_DISABLED for a in actions[2:])


def test_sessions_are_tracked_independently_no_shared_state():
    monitor = HealthMonitor(recreate_after=2)

    monitor.observe(report(profile_id="a", status=TickStatus.CAPTURE_FAILED))
    monitor.observe(report(profile_id="a", status=TickStatus.CAPTURE_FAILED))
    b_decision = monitor.observe(report(profile_id="b", status=TickStatus.CAPTURE_FAILED))

    assert monitor.health_of("a") is SessionHealth.RECOVERING
    assert b_decision.health is SessionHealth.DEGRADED  # b unaffected by a


def test_mark_failed_forces_failed_state():
    monitor = HealthMonitor()

    monitor.mark_failed("p1")

    assert monitor.health_of("p1") is SessionHealth.FAILED


def test_unknown_profile_defaults_to_healthy():
    assert HealthMonitor().health_of("never-seen") is SessionHealth.HEALTHY
