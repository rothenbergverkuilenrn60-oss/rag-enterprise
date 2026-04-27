from __future__ import annotations
import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import asyncio
import pytest


# ---------------------------------------------------------------------------
# Autouse fixture: reset event bus singleton between tests (T-06-06)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_event_bus_singleton(monkeypatch):
    import services.events.event_bus as mod
    yield
    monkeypatch.setattr(mod, "_event_bus", None, raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_event_bus_subscribe_and_dispatch():
    """Subscribe a handler, start, publish, assert handler receives event."""
    from services.events.event_bus import InMemoryEventBus, Event, EventType

    bus = InMemoryEventBus()
    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.DOC_INGESTED, handler)
    await bus.start()
    try:
        await bus.publish(Event(
            event_type=EventType.DOC_INGESTED,
            payload={"doc_id": "d1", "chunk_count": 5},
        ))
        await asyncio.sleep(0.05)
        assert len(received) == 1
        assert received[0].payload["doc_id"] == "d1"
    finally:
        bus.stop()


@pytest.mark.asyncio
async def test_event_bus_multiple_handlers():
    """Two handlers subscribed to the same event_type both receive the event."""
    from services.events.event_bus import InMemoryEventBus, Event, EventType

    bus = InMemoryEventBus()
    received_a = []
    received_b = []

    async def handler_a(event: Event) -> None:
        received_a.append(event)

    async def handler_b(event: Event) -> None:
        received_b.append(event)

    bus.subscribe(EventType.DOC_INGESTED, handler_a)
    bus.subscribe(EventType.DOC_INGESTED, handler_b)
    await bus.start()
    try:
        await bus.publish(Event(
            event_type=EventType.DOC_INGESTED,
            payload={"doc_id": "d2"},
        ))
        await asyncio.sleep(0.05)
        assert len(received_a) == 1
        assert len(received_b) == 1
    finally:
        bus.stop()


@pytest.mark.asyncio
async def test_event_bus_unsubscribed_event_type_skipped():
    """Handler subscribed to DOC_INGESTED does not receive a different event type."""
    from services.events.event_bus import InMemoryEventBus, Event, EventType

    bus = InMemoryEventBus()
    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.DOC_INGESTED, handler)
    await bus.start()
    try:
        await bus.publish(Event(
            event_type=EventType.QUERY_COMPLETED,
            payload={"query_preview": "test"},
        ))
        await asyncio.sleep(0.05)
        assert len(received) == 0
    finally:
        bus.stop()


@pytest.mark.asyncio
async def test_event_bus_stop_drains_loop():
    """After stop(), subsequent publish does not dispatch to handler."""
    from services.events.event_bus import InMemoryEventBus, Event, EventType

    bus = InMemoryEventBus()
    received = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(EventType.DOC_INGESTED, handler)
    await bus.start()
    bus.stop()
    # Give dispatch loop time to exit
    await asyncio.sleep(0.05)

    await bus.publish(Event(
        event_type=EventType.DOC_INGESTED,
        payload={"doc_id": "d3"},
    ))
    await asyncio.sleep(0.05)
    # Handler should NOT have been called after stop()
    assert len(received) == 0
