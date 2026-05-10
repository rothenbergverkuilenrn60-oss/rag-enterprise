"""tests/unit/test_event_bus_extra.py — Phase 15 backfill.

Existing tests/unit/test_event_bus.py covers basic Event + InMemoryEventBus
behavior. This file adds the EventBus facade (Kafka enabled vs disabled),
KafkaEventBackend.publish/start/stop fallbacks, the convenience emitters,
and the Event JSON round-trip.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.events.event_bus as mod
    yield
    monkeypatch.setattr(mod, "_event_bus", None, raising=False)


@pytest.mark.unit
def test_event_to_json_and_from_json_roundtrip():
    from services.events.event_bus import Event, EventType
    e = Event(
        event_type=EventType.DOC_INGESTED,
        payload={"doc_id": "d1"},
        tenant_id="t1",
    )
    raw = e.to_json()
    decoded = Event.from_json(raw)
    assert decoded.event_type == EventType.DOC_INGESTED
    assert decoded.payload["doc_id"] == "d1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kafka_backend_publish_no_op_when_no_producer():
    """No producer → publish silently exits."""
    from services.events.event_bus import Event, EventType, KafkaEventBackend
    backend = KafkaEventBackend("localhost:9092")
    backend._producer = None
    await backend.publish(Event(event_type=EventType.DOC_INGESTED, payload={}))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kafka_backend_publish_swallows_send_failure():
    """Error path: producer raises → warning logged, no propagation."""
    from services.events.event_bus import Event, EventType, KafkaEventBackend
    backend = KafkaEventBackend("localhost:9092")
    producer = MagicMock()
    producer.send_and_wait = AsyncMock(side_effect=RuntimeError("broker down"))
    backend._producer = producer
    await backend.publish(Event(event_type=EventType.DOC_INGESTED, payload={}))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kafka_backend_start_producer_falls_back_when_aiokafka_missing(monkeypatch):
    """ImportError on aiokafka → producer stays None, no exception."""
    import builtins
    real_import = builtins.__import__

    def fail_aiokafka(name, *a, **kw):
        if name == "aiokafka":
            raise ImportError("not installed")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fail_aiokafka)
    from services.events.event_bus import KafkaEventBackend
    backend = KafkaEventBackend("localhost:9092")
    await backend.start_producer()
    assert backend._producer is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_kafka_backend_stop_handles_no_producer():
    from services.events.event_bus import KafkaEventBackend
    backend = KafkaEventBackend("localhost:9092")
    backend._producer = None
    await backend.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_bus_kafka_disabled_uses_memory_only():
    """No kafka_bootstrap_servers → use_kafka=False, kafka backend None."""
    from services.events.event_bus import EventBus
    bus = EventBus.__new__(EventBus)
    bus._kafka = None
    bus._use_kafka = False
    from services.events.event_bus import InMemoryEventBus
    bus._memory = InMemoryEventBus()
    bus._memory.publish = AsyncMock()
    from services.events.event_bus import Event, EventType
    await bus.publish(Event(event_type=EventType.QUERY_COMPLETED, payload={}))
    bus._memory.publish.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_bus_kafka_enabled_publishes_to_both():
    """Kafka enabled → publish hits both backends."""
    from services.events.event_bus import (
        Event,
        EventBus,
        EventType,
        InMemoryEventBus,
    )
    bus = EventBus.__new__(EventBus)
    bus._kafka = MagicMock()
    bus._kafka.publish = AsyncMock()
    bus._use_kafka = True
    bus._memory = InMemoryEventBus()
    bus._memory.publish = AsyncMock()
    await bus.publish(Event(event_type=EventType.QUERY_COMPLETED, payload={}))
    bus._kafka.publish.assert_awaited_once()
    bus._memory.publish.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_bus_start_calls_kafka_then_memory():
    from services.events.event_bus import EventBus, InMemoryEventBus
    bus = EventBus.__new__(EventBus)
    bus._kafka = MagicMock()
    bus._kafka.start_producer = AsyncMock()
    bus._use_kafka = True
    bus._memory = InMemoryEventBus()
    bus._memory.start = AsyncMock()
    await bus.start()
    bus._kafka.start_producer.assert_awaited_once()
    bus._memory.start.assert_awaited_once()


@pytest.mark.unit
def test_event_bus_subscribe_routes_to_memory_bus():
    from services.events.event_bus import EventBus, InMemoryEventBus
    bus = EventBus.__new__(EventBus)
    bus._memory = InMemoryEventBus()
    handler = MagicMock()
    bus.subscribe("doc.ingested", handler)
    assert handler in bus._memory._handlers["doc.ingested"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_bus_subscribe_kafka_no_op_when_disabled():
    from services.events.event_bus import EventBus
    bus = EventBus.__new__(EventBus)
    bus._kafka = None
    bus._use_kafka = False
    await bus.subscribe_kafka("doc.ingested", AsyncMock())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_bus_stop_invokes_kafka_when_enabled():
    from services.events.event_bus import EventBus, InMemoryEventBus
    bus = EventBus.__new__(EventBus)
    bus._kafka = MagicMock()
    bus._kafka.stop = AsyncMock()
    bus._use_kafka = True
    bus._memory = InMemoryEventBus()
    bus._memory.stop = MagicMock()
    await bus.stop()
    bus._kafka.stop.assert_awaited_once()
    bus._memory.stop.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_emit_doc_ingested_publishes_correct_event():
    from services.events.event_bus import EventBus, EventType
    bus = EventBus.__new__(EventBus)
    bus.publish = AsyncMock()
    await bus.emit_doc_ingested("doc-1", chunk_count=3, tenant_id="t1")
    bus.publish.assert_awaited_once()
    event = bus.publish.call_args.args[0]
    assert event.event_type == EventType.DOC_INGESTED
    assert event.payload["chunk_count"] == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_emit_query_completed_truncates_query():
    from services.events.event_bus import EventBus, EventType
    bus = EventBus.__new__(EventBus)
    bus.publish = AsyncMock()
    long_query = "x" * 200
    await bus.emit_query_completed(long_query, 100, 50.0, 0.9)
    event = bus.publish.call_args.args[0]
    assert event.event_type == EventType.QUERY_COMPLETED
    assert len(event.payload["query_preview"]) == 80


@pytest.mark.unit
@pytest.mark.asyncio
async def test_emit_feedback_routes_positive_vs_negative():
    from services.events.event_bus import EventBus, EventType
    bus_pos = EventBus.__new__(EventBus)
    bus_pos.publish = AsyncMock()
    await bus_pos.emit_feedback(True, "s1")
    assert bus_pos.publish.call_args.args[0].event_type == EventType.FEEDBACK_POSITIVE

    bus_neg = EventBus.__new__(EventBus)
    bus_neg.publish = AsyncMock()
    await bus_neg.emit_feedback(False, "s1")
    assert bus_neg.publish.call_args.args[0].event_type == EventType.FEEDBACK_NEGATIVE


@pytest.mark.unit
def test_get_event_bus_singleton(monkeypatch):
    from services.events import event_bus as mod
    monkeypatch.setattr(mod, "_event_bus", None, raising=False)
    a = mod.get_event_bus()
    b = mod.get_event_bus()
    assert a is b
