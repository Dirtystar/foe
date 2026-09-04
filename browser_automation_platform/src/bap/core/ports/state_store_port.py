"""Persistence port and its DTOs.

The port defines *what* runtime history can be stored; adapters decide *how*
(SQLite, etc.). The DTOs here are deliberately plain persistence records, not
runtime objects — no TickReport, no Observation, no exceptions — so the core
never leaks live objects into storage and storage never depends on runtime
internals. No database logic lives in core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


class StorageError(Exception):
    """Raised when a store cannot be opened or a write fails irrecoverably."""


@dataclass(frozen=True)
class ActionRecord:
    rule_id: str | None
    action_type: str
    status: str
    error: str | None = None


@dataclass(frozen=True)
class TickRecord:
    timestamp: datetime
    profile_id: str
    tick_number: int
    status: str
    duration_ms: float | None = None
    capture_ms: float | None = None
    vision_ms: float | None = None
    rules_ms: float | None = None
    actions_ms: float | None = None
    rules_matched: int | None = None
    rules_total: int | None = None
    error: str | None = None
    actions: tuple[ActionRecord, ...] = ()


@dataclass(frozen=True)
class HealthEventRecord:
    timestamp: datetime
    profile_id: str
    previous_state: str | None
    new_state: str
    reason: str


@dataclass(frozen=True)
class BrowserResourceRecord:
    timestamp: datetime
    browser_id: str
    memory_mb: float | None
    cpu_percent: float | None
    pages: int
    contexts: int


class StateStorePort(ABC):
    """Append-only history store for runtime diagnostics.

    Implementations must be safe to call from runtime callbacks and must not
    require the caller to be on any particular thread. Writes may be
    asynchronous; close() flushes and releases resources.
    """

    @abstractmethod
    def record_tick(self, tick: TickRecord) -> None: ...

    @abstractmethod
    def record_health(self, event: HealthEventRecord) -> None: ...

    def record_resource(self, snapshot: BrowserResourceRecord) -> None:
        """Persist a browser resource snapshot. Non-abstract with a no-op
        default so existing stores keep working unchanged; backends that
        support it (SQLite) override this."""

    @abstractmethod
    def close(self) -> None: ...


__all__ = [
    "ActionRecord",
    "BrowserResourceRecord",
    "HealthEventRecord",
    "StateStorePort",
    "StorageError",
    "TickRecord",
]
