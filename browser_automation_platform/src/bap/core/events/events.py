"""Domain events published on the EventBus.

Events are immutable facts about something that already happened. They carry
data only — no behavior, no references to live objects (no TabHandle, no
Page) so any subscriber (logging, future GUI) can hold them freely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base type for all events. Subscribe to this to receive everything."""

    occurred_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, kw_only=True)
class SessionStarted(DomainEvent):
    profile_id: str


@dataclass(frozen=True, kw_only=True)
class SessionStopped(DomainEvent):
    profile_id: str
    reason: str = "requested"


@dataclass(frozen=True, kw_only=True)
class ErrorOccurred(DomainEvent):
    message: str
    profile_id: str | None = None
    error_type: str | None = None


@dataclass(frozen=True, kw_only=True)
class ActionExecuted(DomainEvent):
    profile_id: str
    action_type: str
    success: bool
    detail: str | None = None
