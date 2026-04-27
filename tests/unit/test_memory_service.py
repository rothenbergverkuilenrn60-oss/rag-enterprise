"""
tests/unit/test_memory_service.py
Unit tests for ShortTermMemory using fakeredis (no real Redis required).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
import pytest_asyncio
import fakeredis
from unittest.mock import AsyncMock, MagicMock


@pytest_asyncio.fixture
async def fake_redis():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


@pytest.mark.asyncio
async def test_short_term_memory_append_and_get(fake_redis, monkeypatch):
    from services.memory.memory_service import ShortTermMemory, ConversationTurn

    mem = ShortTermMemory()
    monkeypatch.setattr(mem, "_client", fake_redis)

    turn = ConversationTurn(role="user", content="hello")
    await mem.append("sess1", turn)

    history = await mem.get_history("sess1")
    assert len(history) == 1
    assert history[0].content == "hello"


@pytest.mark.asyncio
async def test_short_term_memory_window_truncation(fake_redis, monkeypatch):
    """get_history with max_turns=3 only returns the last 6 items (3 turns * 2)."""
    from services.memory.memory_service import ShortTermMemory, ConversationTurn

    mem = ShortTermMemory()
    monkeypatch.setattr(mem, "_client", fake_redis)

    # Append 10 turns
    for i in range(10):
        turn = ConversationTurn(role="user", content=f"turn-{i}")
        await mem.append("sess2", turn)

    # Request only 3 turns (max_turns=3 → lrange fetches last 6 entries)
    history = await mem.get_history("sess2", max_turns=3)
    assert len(history) <= 6
    # The last turn should be the most recent
    assert history[-1].content == "turn-9"


@pytest.mark.asyncio
async def test_short_term_memory_empty_history(fake_redis, monkeypatch):
    from services.memory.memory_service import ShortTermMemory

    mem = ShortTermMemory()
    monkeypatch.setattr(mem, "_client", fake_redis)

    history = await mem.get_history("nonexistent-session")
    assert history == []


@pytest.mark.asyncio
async def test_get_memory_service_singleton():
    from services.memory.memory_service import get_memory_service

    svc1 = get_memory_service()
    svc2 = get_memory_service()
    assert svc1 is svc2
