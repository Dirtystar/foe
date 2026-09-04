import pytest

from bap.core.events.event_bus import EventBus
from bap.core.events.events import (
    ActionExecuted,
    DomainEvent,
    ErrorOccurred,
    SessionStarted,
    SessionStopped,
)


async def test_sync_handler_receives_published_event():
    bus = EventBus()
    received = []
    bus.subscribe(SessionStarted, received.append)

    event = SessionStarted(profile_id="tab1")
    await bus.publish(event)

    assert received == [event]


async def test_async_handler_is_awaited():
    bus = EventBus()
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe(ActionExecuted, handler)
    await bus.publish(ActionExecuted(profile_id="tab1", action_type="click", success=True))

    assert len(received) == 1


async def test_handlers_only_receive_their_event_type():
    bus = EventBus()
    started, stopped = [], []
    bus.subscribe(SessionStarted, started.append)
    bus.subscribe(SessionStopped, stopped.append)

    await bus.publish(SessionStarted(profile_id="tab1"))

    assert len(started) == 1
    assert stopped == []


async def test_multiple_handlers_run_in_subscription_order():
    bus = EventBus()
    calls = []
    bus.subscribe(SessionStarted, lambda e: calls.append("first"))
    bus.subscribe(SessionStarted, lambda e: calls.append("second"))

    await bus.publish(SessionStarted(profile_id="tab1"))

    assert calls == ["first", "second"]


async def test_subscribing_to_domain_event_receives_all_events():
    bus = EventBus()
    received = []
    bus.subscribe(DomainEvent, received.append)

    await bus.publish(SessionStarted(profile_id="tab1"))
    await bus.publish(ErrorOccurred(message="boom"))

    assert [type(e) for e in received] == [SessionStarted, ErrorOccurred]


async def test_unsubscribe_removes_handler():
    bus = EventBus()
    received = []
    handler = received.append
    bus.subscribe(SessionStarted, handler)
    bus.unsubscribe(SessionStarted, handler)

    await bus.publish(SessionStarted(profile_id="tab1"))

    assert received == []


async def test_unsubscribe_unknown_handler_raises():
    bus = EventBus()

    with pytest.raises(ValueError):
        bus.unsubscribe(SessionStarted, lambda e: None)


async def test_publish_with_no_subscribers_is_a_no_op():
    bus = EventBus()

    await bus.publish(SessionStarted(profile_id="tab1"))


async def test_handler_error_propagates_without_on_error_callback():
    bus = EventBus()

    def bad_handler(event):
        raise RuntimeError("subscriber bug")

    bus.subscribe(SessionStarted, bad_handler)

    with pytest.raises(RuntimeError):
        await bus.publish(SessionStarted(profile_id="tab1"))


async def test_on_error_callback_isolates_failures_and_dispatch_continues():
    errors = []
    bus = EventBus(on_error=lambda exc, event: errors.append((exc, event)))
    received = []

    def bad_handler(event):
        raise RuntimeError("subscriber bug")

    bus.subscribe(SessionStarted, bad_handler)
    bus.subscribe(SessionStarted, received.append)

    event = SessionStarted(profile_id="tab1")
    await bus.publish(event)

    assert len(received) == 1
    assert len(errors) == 1
    assert isinstance(errors[0][0], RuntimeError)
    assert errors[0][1] is event


def test_events_are_immutable_and_timestamped():
    event = SessionStopped(profile_id="tab1", reason="error")

    assert event.occurred_at.tzinfo is not None
    with pytest.raises(Exception):
        event.profile_id = "other"  # type: ignore[misc]
