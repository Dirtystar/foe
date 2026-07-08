"""In-memory, in-process pub/sub for DomainEvents.

Deliberately small: no persistence, no networking, no thread-safety beyond
what a single asyncio event loop provides. Handlers may be plain functions
or coroutine functions; publish() awaits the async ones.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from bap.core.events.events import DomainEvent

EventHandler = Callable[[Any], Any]
"""Callable taking one event; may return an awaitable."""

ErrorCallback = Callable[[Exception, DomainEvent], None]


class EventBus:
    """Type-based pub/sub.

    Subscribing to a base class receives all its subclasses, so a subscriber
    to DomainEvent sees every event (the logging sink's use case).

    Handler errors: without an `on_error` callback, a raising handler
    propagates to the publisher immediately (fail fast). With one, the error
    is reported to the callback and dispatch continues to remaining handlers
    — this is what production wiring should use, so one broken subscriber
    cannot stall a tab's tick loop.
    """

    def __init__(self, on_error: ErrorCallback | None = None) -> None:
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = {}
        self._on_error = on_error

    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        """Remove a subscription. Raises ValueError if it does not exist."""
        try:
            self._handlers.get(event_type, []).remove(handler)
        except ValueError:
            raise ValueError(
                f"Handler is not subscribed to {event_type.__name__}."
            ) from None

    async def publish(self, event: DomainEvent) -> None:
        for handler in self._handlers_for(type(event)):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                if self._on_error is None:
                    raise
                self._on_error(exc, event)

    def _handlers_for(self, event_type: type) -> list[EventHandler]:
        """Handlers for the event's own type and every DomainEvent ancestor."""
        collected: list[EventHandler] = []
        for cls in event_type.__mro__:
            if issubclass(cls, DomainEvent):
                collected.extend(self._handlers.get(cls, []))
        return collected


__all__ = ["EventBus", "EventHandler", "ErrorCallback"]
