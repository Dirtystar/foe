"""Health classification and recovery policy — pure decision logic.

Lives above TabSession and knows nothing about browsers: it reads the tick
outcomes TabSession already reports and decides what should happen. It holds
no I/O and performs no recovery itself; SessionManager owns the actual
lifecycle actions. Keeping this a pure state machine makes the policy fully
unit-testable and keeps retry/restart logic out of the RuleEngine,
ActionExecutor, and Conditions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from bap.core.engine.tab_session import TickReport, TickStatus


class SessionHealth(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    FAILED = "failed"


class RecoveryAction(Enum):
    NONE = "none"
    SKIP_TEMPORARILY = "skip_temporarily"
    RESTART_TAB = "restart_tab"          # reserved lighter variant of recreate
    RECREATE_SESSION = "recreate_session"
    MARK_DISABLED = "mark_disabled"


class FailureClass(Enum):
    NONE = "none"
    TRANSIENT = "transient"
    PERMANENT = "permanent"


# Only transient failures are recovered automatically. Capture and vision
# failures are treated as transient (timeouts, temporary browser/vision
# hiccups). An INTERNAL_ERROR is an unexpected pipeline/wiring fault that
# recreating the tab will not fix, so it is permanent. Genuinely permanent
# config faults (invalid config, missing analyzer/handler) are caught earlier,
# at composition time, and never reach a tick.
_TRANSIENT_STATUSES = {TickStatus.CAPTURE_FAILED, TickStatus.VISION_FAILED}
_PERMANENT_STATUSES = {TickStatus.INTERNAL_ERROR}


def classify(report: TickReport) -> FailureClass:
    if report.status is TickStatus.COMPLETED:
        return FailureClass.NONE
    if report.status in _PERMANENT_STATUSES:
        return FailureClass.PERMANENT
    if report.status in _TRANSIENT_STATUSES:
        return FailureClass.TRANSIENT
    return FailureClass.PERMANENT  # unknown status: do not auto-recover blindly


@dataclass(frozen=True)
class RecoveryDecision:
    profile_id: str
    health: SessionHealth
    action: RecoveryAction
    failure_class: FailureClass
    reason: str

    @property
    def should_recover(self) -> bool:
        return self.action in (RecoveryAction.RESTART_TAB, RecoveryAction.RECREATE_SESSION)

    @property
    def should_disable(self) -> bool:
        return self.action is RecoveryAction.MARK_DISABLED


@dataclass
class _State:
    health: SessionHealth = SessionHealth.HEALTHY
    consecutive_transient: int = 0
    recovery_attempts: int = 0


class HealthMonitor:
    """Per-session health state machine driven by TickReports.

    Policy: the first transient failures degrade the session (keep ticking);
    after `recreate_after` consecutive transient failures it asks for a
    recreate and counts the attempt; after `max_recovery_attempts` recreates
    without a healthy tick it gives up and asks to disable the session, so a
    persistently failing session cannot loop forever. Any healthy tick clears
    the counters. State is per profile — there is no shared/global state.
    """

    def __init__(self, *, recreate_after: int = 2, max_recovery_attempts: int = 3) -> None:
        if recreate_after < 1:
            raise ValueError("recreate_after must be >= 1")
        if max_recovery_attempts < 1:
            raise ValueError("max_recovery_attempts must be >= 1")
        self._recreate_after = recreate_after
        self._max_recovery_attempts = max_recovery_attempts
        self._states: dict[str, _State] = {}

    def health_of(self, profile_id: str) -> SessionHealth:
        state = self._states.get(profile_id)
        return state.health if state else SessionHealth.HEALTHY

    def mark_failed(self, profile_id: str) -> None:
        """Force a session to FAILED — used when a recovery attempt itself
        failed, so the state reflects reality."""
        self._states.setdefault(profile_id, _State()).health = SessionHealth.FAILED

    def observe(self, report: TickReport) -> RecoveryDecision:
        profile_id = report.profile_id
        state = self._states.setdefault(profile_id, _State())
        failure = classify(report)

        if failure is FailureClass.NONE:
            state.consecutive_transient = 0
            state.recovery_attempts = 0
            state.health = SessionHealth.HEALTHY
            return self._decision(profile_id, state, RecoveryAction.NONE, failure, "tick completed")

        if failure is FailureClass.PERMANENT:
            state.health = SessionHealth.FAILED
            return self._decision(
                profile_id, state, RecoveryAction.MARK_DISABLED, failure,
                f"permanent failure ({report.status.value})",
            )

        # transient
        state.consecutive_transient += 1
        if state.consecutive_transient < self._recreate_after:
            state.health = SessionHealth.DEGRADED
            return self._decision(
                profile_id, state, RecoveryAction.SKIP_TEMPORARILY, failure,
                f"transient failure ({report.status.value}), "
                f"{state.consecutive_transient} in a row",
            )

        if state.recovery_attempts >= self._max_recovery_attempts:
            state.health = SessionHealth.FAILED
            return self._decision(
                profile_id, state, RecoveryAction.MARK_DISABLED, failure,
                f"exceeded {self._max_recovery_attempts} recovery attempts",
            )

        state.recovery_attempts += 1
        state.consecutive_transient = 0
        state.health = SessionHealth.RECOVERING
        return self._decision(
            profile_id, state, RecoveryAction.RECREATE_SESSION, failure,
            f"recovery attempt {state.recovery_attempts} "
            f"after {report.status.value}",
        )

    @staticmethod
    def _decision(profile_id, state, action, failure, reason) -> RecoveryDecision:
        return RecoveryDecision(
            profile_id=profile_id,
            health=state.health,
            action=action,
            failure_class=failure,
            reason=reason,
        )


class ResourcePressureState(Enum):
    NORMAL = "normal"
    DEGRADED = "degraded"
    CRITICAL = "critical"


class ResourceAction(Enum):
    NONE = "none"
    RECOVER = "recover"    # reclaim resources by recreating sessions
    DISABLE = "disable"    # persistent pressure: stop the sessions


@dataclass(frozen=True)
class ResourcePressureDecision:
    state: ResourcePressureState
    action: ResourceAction
    reason: str
    changed: bool


class ResourcePressurePolicy:
    """Escalates browser resource pressure over time, mirroring HealthMonitor.

    Observational first: brief pressure only degrades (a health signal). Only
    sustained pressure escalates — one RECOVER at `recover_after` consecutive
    breaches, then DISABLE at `disable_after`. Actions fire once at their
    threshold (not every sample), and any within-limits sample resets.
    """

    def __init__(self, *, recover_after: int = 3, disable_after: int = 6) -> None:
        if not 1 <= recover_after < disable_after:
            raise ValueError("require 1 <= recover_after < disable_after")
        self._recover_after = recover_after
        self._disable_after = disable_after
        self._consecutive = 0
        self._state = ResourcePressureState.NORMAL

    @property
    def state(self) -> ResourcePressureState:
        return self._state

    def observe(self, breaches: tuple[str, ...]) -> ResourcePressureDecision:
        prev = self._state
        if not breaches:
            self._consecutive = 0
            self._state = ResourcePressureState.NORMAL
            return ResourcePressureDecision(
                ResourcePressureState.NORMAL, ResourceAction.NONE,
                "resources within limits", prev is not ResourcePressureState.NORMAL,
            )

        self._consecutive += 1
        reason = "resource pressure: " + "; ".join(breaches)
        action = ResourceAction.NONE
        if self._consecutive == self._disable_after:
            action = ResourceAction.DISABLE
        elif self._consecutive == self._recover_after:
            action = ResourceAction.RECOVER
        self._state = (
            ResourcePressureState.CRITICAL
            if self._consecutive >= self._recover_after
            else ResourcePressureState.DEGRADED
        )
        return ResourcePressureDecision(self._state, action, reason, prev is not self._state)


__all__ = [
    "FailureClass",
    "HealthMonitor",
    "RecoveryAction",
    "RecoveryDecision",
    "ResourceAction",
    "ResourcePressureDecision",
    "ResourcePressurePolicy",
    "ResourcePressureState",
    "SessionHealth",
    "classify",
]
