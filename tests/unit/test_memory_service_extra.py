"""tests/unit/test_memory_service_extra.py — Phase 15 backfill.

Existing tests/unit/test_memory_service.py covers a small subset; this
file adds ShortTermMemory + LongTermMemory + MemoryService coverage with
mocked Redis / asyncpg / pool acquire.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import json
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
import redis.asyncio as redis_async


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


def _make_short(redis_mock):
    from services.memory.memory_service import ShortTermMemory
    s = ShortTermMemory.__new__(ShortTermMemory)
    s._ttl = 3600
    s._client = redis_mock
    return s


def _make_long(pool_mock):
    from services.memory.memory_service import LongTermMemory
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool_mock

    async def _get_pool():
        return pool_mock

    lt._get_pool = _get_pool
    return lt


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool


@pytest.mark.unit
@pytest.mark.asyncio
async def test_short_term_append_writes_redis_list():
    from services.memory.memory_service import ConversationTurn
    r = MagicMock()
    r.rpush = AsyncMock()
    r.expire = AsyncMock()
    s = _make_short(r)
    await s.append("sess-1", ConversationTurn(role="user", content="hi"))
    r.rpush.assert_awaited_once()
    r.expire.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_short_term_get_history_parses_json():
    from services.memory.memory_service import ConversationTurn
    turn = ConversationTurn(role="assistant", content="answer")
    r = MagicMock()
    r.lrange = AsyncMock(return_value=[json.dumps(turn.__dict__)])
    s = _make_short(r)
    out = await s.get_history("sess-1")
    assert len(out) == 1
    assert out[0].content == "answer"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_short_term_get_history_redis_error_returns_empty():
    """Error path: RedisError → []."""
    r = MagicMock()
    r.lrange = AsyncMock(side_effect=redis_async.RedisError("boom"))
    s = _make_short(r)
    out = await s.get_history("sess-1")
    assert out == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_short_term_clear_deletes_key():
    r = MagicMock()
    r.delete = AsyncMock()
    s = _make_short(r)
    await s.clear("sess-1")
    r.delete.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_short_term_get_formatted_history_returns_role_content_dicts():
    from services.memory.memory_service import ConversationTurn
    t1 = ConversationTurn(role="user", content="q1")
    t2 = ConversationTurn(role="assistant", content="a1")
    r = MagicMock()
    r.lrange = AsyncMock(return_value=[json.dumps(t1.__dict__), json.dumps(t2.__dict__)])
    s = _make_short(r)
    out = await s.get_formatted_history("sess-1")
    assert out == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_get_user_profile_returns_default_when_missing():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    lt = _make_long(_make_pool(conn))
    profile = await lt.get_user_profile("u1", "t1")
    assert profile.user_id == "u1"
    assert profile.query_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_get_user_profile_parses_row():
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={
        "user_id": "u1", "tenant_id": "t1",
        "frequent_topics": json.dumps(["python", "rag"]),
        "preferred_detail": "brief",
        "query_count": 7, "positive_count": 3, "negative_count": 1,
        "last_active": 0.0, "metadata": "{}",
    })
    lt = _make_long(_make_pool(conn))
    profile = await lt.get_user_profile("u1", "t1")
    assert profile.frequent_topics == ["python", "rag"]
    assert profile.preferred_detail == "brief"
    assert profile.query_count == 7


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_get_user_profile_pg_error_returns_default():
    """Error path: PostgresError → default UserProfile."""
    conn = MagicMock()
    conn.fetchrow = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
    lt = _make_long(_make_pool(conn))
    profile = await lt.get_user_profile("u1", "t1")
    assert profile.query_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_upsert_user_profile_executes_insert():
    from services.memory.memory_service import UserProfile
    conn = MagicMock()
    conn.execute = AsyncMock()
    lt = _make_long(_make_pool(conn))
    await lt.upsert_user_profile(UserProfile(user_id="u1"))
    conn.execute.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_get_relevant_facts_returns_strings():
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=[{"fact": "f1"}, {"fact": "f2"}])
    lt = _make_long(_make_pool(conn))
    out = await lt.get_relevant_facts("u1", "t1", "query")
    assert out == ["f1", "f2"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_get_relevant_facts_pg_error_returns_empty():
    conn = MagicMock()
    conn.fetch = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
    lt = _make_long(_make_pool(conn))
    out = await lt.get_relevant_facts("u1", "t1", "query")
    assert out == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_save_fact_calls_insert():
    conn = MagicMock()
    conn.execute = AsyncMock()
    lt = _make_long(_make_pool(conn))
    await lt.save_fact("u1", "t1", fact="xyz")
    conn.execute.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_save_query_truncates_answer():
    conn = MagicMock()
    conn.execute = AsyncMock()
    lt = _make_long(_make_pool(conn))
    await lt.save_query("u1", "t1", "s1", "Q?", "ASK", answer_short="x" * 1000)
    args = conn.execute.call_args.args
    assert len(args[-1]) == 500


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_update_feedback_runs_query():
    conn = MagicMock()
    conn.execute = AsyncMock()
    lt = _make_long(_make_pool(conn))
    await lt.update_feedback("u1", "s1", 1)
    conn.execute.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_long_term_update_profile_appends_topic():
    """Happy path: new topic prepended; positive feedback increments."""
    from services.memory.memory_service import UserProfile
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.execute = AsyncMock()
    lt = _make_long(_make_pool(conn))

    captured: list = []

    async def capture(profile: UserProfile):
        captured.append(profile)

    lt.upsert_user_profile = capture
    await lt.update_profile_from_query("u1", "t1", "rag", feedback=1)
    assert captured[0].positive_count == 1
    assert "rag" in captured[0].frequent_topics


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_service_load_context_aggregates(monkeypatch):
    from services.memory.memory_service import (
        ConversationTurn,
        MemoryService,
        UserProfile,
    )
    svc = MemoryService.__new__(MemoryService)
    svc._short = MagicMock()
    svc._short.get_history = AsyncMock(return_value=[ConversationTurn(role="user", content="q")])
    svc._long = MagicMock()
    svc._long.get_relevant_facts = AsyncMock(return_value=["fact-1"])
    svc._long.get_user_profile = AsyncMock(return_value=UserProfile(user_id="u1"))
    ctx = await svc.load_context("s1", "u1", "t1", "query")
    assert ctx.short_term[0].content == "q"
    assert ctx.long_term_facts == ["fact-1"]
    assert ctx.user_profile.user_id == "u1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_service_save_turn_dispatches_short_and_long():
    from services.memory.memory_service import ConversationTurn, MemoryService
    svc = MemoryService.__new__(MemoryService)
    svc._short = MagicMock()
    svc._short.append = AsyncMock()
    svc._long = MagicMock()
    svc._long.save_query = AsyncMock()
    svc._long.update_profile_from_query = AsyncMock()
    await svc.save_turn(
        "s1", "u1", "t1",
        user_turn=ConversationTurn(role="user", content="q"),
        ai_turn=ConversationTurn(role="assistant", content="a"),
        intent="ASK",
    )
    assert svc._short.append.await_count == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_service_save_feedback_routes_to_long():
    from services.memory.memory_service import MemoryService
    svc = MemoryService.__new__(MemoryService)
    svc._long = MagicMock()
    svc._long.update_feedback = AsyncMock()
    await svc.save_feedback("u1", "s1", 1)
    svc._long.update_feedback.assert_awaited_once()


@pytest.mark.unit
def test_user_profile_satisfaction_rate_no_feedback_defaults_half():
    from services.memory.memory_service import UserProfile
    p = UserProfile(user_id="u1")
    assert p.satisfaction_rate == 0.5
    p.positive_count = 3
    p.negative_count = 1
    assert abs(p.satisfaction_rate - 0.75) < 1e-6


@pytest.mark.unit
def test_get_memory_service_singleton(monkeypatch):
    import services.memory.memory_service as mod
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)
    a = mod.get_memory_service()
    b = mod.get_memory_service()
    assert a is b
