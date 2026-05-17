"""tests/unit/test_memory_recall_semantic.py — Phase 24 / MEM-06 (Plan 24-02 RED).

Covers the semantic-recall rewrite of ``LongTermMemory.get_relevant_facts``:

  Test 1: returns bare strings sorted by cosine order (no prefix; ordered by
          embedding <=> vector, tie-break importance/created_at).
  Test 2: SET LOCAL hnsw.iterative_scan and hnsw.ef_search executed before fetch.
  Test 3: recall SELECT runs inside explicit conn.transaction() wrap.
  Test 4: embedder failure (parametrized RuntimeError / httpx.HTTPError / OSError)
          returns [] with zero DB hits.
  Test 5: asyncpg.PostgresError from SELECT returns [] without propagating.
  Test 6: limit parameter threaded to $4 positional in SQL.
  Test 7: signature unchanged (self, user_id, tenant_id, query, limit=5).
  Test 8: returned elements have no "- " or "* " bullet prefix (Pitfall 3 regression).
  Test 9: SQL tie-break contains importance DESC and created_at DESC.

ADDED tests (eng-review 2026-05-16 / T1 Decision-1):
  Test 10: load_context returns long_term_facts=[] after drop.
  Test 11: load_context does NOT await get_relevant_facts.

Dual-path patch convention:
  monkeypatch.setattr("services.memory.memory_service.get_embedder", ..., raising=False)
    — consumer-path (name bound after first lazy import)
  monkeypatch.setattr("services.vectorizer.embedder.get_embedder", ...)
    — source-path (intercepts `from services.vectorizer.embedder import get_embedder`)
"""
from __future__ import annotations

import os

# Env-var setdefault BEFORE any services.* import (Phase 23 shared pattern)
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import inspect
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import httpx
import pytest

from services.memory.memory_service import LongTermMemory, MemoryService


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    """Reset the _memory_service singleton between tests."""
    import services.memory.memory_service as mod

    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


class _AcquireCtx:
    """Async context manager that yields a pre-built conn object.

    Mirrors Phase 23 _AcquireCtx — redefined locally for test-file self-containment.
    """

    def __init__(self, conn: MagicMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> MagicMock:
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


def _make_fake_pool(
    conn: MagicMock,
) -> MagicMock:
    """Return a fake pool whose acquire() yields the given conn."""
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool


def _make_conn_with_txn() -> MagicMock:
    """Return a MagicMock conn with:
    - execute: AsyncMock (records SET LOCAL calls)
    - fetch: AsyncMock (returns [] by default)
    - transaction: MagicMock returning _AcquireCtx(self)  — Pitfall 2 mitigation

    The transaction CM yields the same conn so SET LOCAL calls see the same mock.
    """
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.transaction = MagicMock(return_value=_AcquireCtx(conn))
    return conn


def _make_long(pool: MagicMock) -> LongTermMemory:
    """Construct LongTermMemory with pool pre-injected (bypass _get_pool)."""
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool

    async def _get_pool():
        return pool

    lt._get_pool = _get_pool
    return lt


def _make_fake_embedder(vec: list[float] | None = None) -> MagicMock:
    """Return a fake embedder whose embed_one resolves to vec (default [0.1]*1024)."""
    if vec is None:
        vec = [0.1] * 1024
    fake = MagicMock()
    fake.embed_one = AsyncMock(return_value=vec)
    return fake


def _patch_embedder(monkeypatch, embedder: MagicMock) -> None:
    """Dual-path patch: source + consumer (raising=False for lazy import)."""
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder",
        lambda: embedder,
    )
    monkeypatch.setattr(
        "services.memory.memory_service.get_embedder",
        lambda: embedder,
        raising=False,
    )


# ---------------------------------------------------------------------------
# Test 1: returns bare strings sorted by cosine
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_returns_bare_strings_sorted_by_cosine(monkeypatch):
    """Stub fetch → 3 fake rows; result is bare strings in same order."""
    conn = _make_conn_with_txn()
    conn.fetch = AsyncMock(
        return_value=[{"fact": "f1"}, {"fact": "f2"}, {"fact": "f3"}]
    )
    pool = _make_fake_pool(conn)
    mem = _make_long(pool)

    _patch_embedder(monkeypatch, _make_fake_embedder())

    result = await mem.get_relevant_facts("u", "t", "q")
    assert result == ["f1", "f2", "f3"]


# ---------------------------------------------------------------------------
# Test 2: SET LOCAL executed before fetch, strict_order + ef_search
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_local_executed_before_fetch(monkeypatch):
    """Two SET LOCAL calls must precede fetch; iterative_scan first, ef_search second."""
    conn = _make_conn_with_txn()
    conn.fetch = AsyncMock(return_value=[])
    pool = _make_fake_pool(conn)
    mem = _make_long(pool)

    _patch_embedder(monkeypatch, _make_fake_embedder())

    await mem.get_relevant_facts("u", "t", "q")

    # Two SET LOCAL execute calls must have happened.
    assert conn.execute.await_count == 2, (
        f"Expected 2 SET LOCAL execute calls, got {conn.execute.await_count}"
    )

    calls = conn.execute.call_args_list
    sql_0 = calls[0].args[0]
    sql_1 = calls[1].args[0]

    assert "SET LOCAL hnsw.iterative_scan" in sql_0, (
        f"First execute should set iterative_scan; got: {sql_0!r}"
    )
    assert "strict_order" in sql_0, (
        f"iterative_scan must be 'strict_order'; got: {sql_0!r}"
    )
    assert "SET LOCAL hnsw.ef_search" in sql_1, (
        f"Second execute should set ef_search; got: {sql_1!r}"
    )

    # fetch must have been called once (after the two SET LOCAL calls).
    assert conn.fetch.await_count == 1


# ---------------------------------------------------------------------------
# Test 3: recall uses explicit conn.transaction()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_relevant_facts_uses_transaction(monkeypatch):
    """conn.transaction() must be entered exactly once (Pitfall 2)."""
    conn = _make_conn_with_txn()
    pool = _make_fake_pool(conn)
    mem = _make_long(pool)

    _patch_embedder(monkeypatch, _make_fake_embedder())

    await mem.get_relevant_facts("u", "t", "q")

    assert conn.transaction.call_count == 1, (
        f"Expected transaction entered once, got {conn.transaction.call_count}"
    )


# ---------------------------------------------------------------------------
# Test 4: embedder failure → empty list, zero DB hits
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("ollama down"),
        httpx.HTTPError("transport error"),
        OSError("torch device error"),
    ],
)
async def test_embedder_failure_returns_empty(monkeypatch, exc):
    """Any of the three embedder failure types returns [] with no DB call."""
    conn = _make_conn_with_txn()
    pool = _make_fake_pool(conn)
    mem = _make_long(pool)

    failing_embedder = MagicMock()
    failing_embedder.embed_one = AsyncMock(side_effect=exc)
    _patch_embedder(monkeypatch, failing_embedder)

    result = await mem.get_relevant_facts("u", "t", "q")

    assert result == [], f"Expected [] on embedder failure, got {result!r}"
    assert conn.fetch.await_count == 0, (
        "DB fetch must not be called when embedder fails"
    )


# ---------------------------------------------------------------------------
# Test 5: asyncpg failure → empty list, no propagation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pg_failure_returns_empty(monkeypatch):
    """asyncpg.PostgresError from fetch returns [] without raising."""
    conn = _make_conn_with_txn()
    conn.fetch = AsyncMock(side_effect=asyncpg.PostgresError("syntax"))
    pool = _make_fake_pool(conn)
    mem = _make_long(pool)

    _patch_embedder(monkeypatch, _make_fake_embedder())

    result = await mem.get_relevant_facts("u", "t", "q")
    assert result == []


# ---------------------------------------------------------------------------
# Test 6: limit threaded to $4
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_limit_parameter_respected(monkeypatch):
    """limit=5 default and limit=3 override are passed as the last positional arg."""
    conn = _make_conn_with_txn()
    pool = _make_fake_pool(conn)
    mem = _make_long(pool)

    _patch_embedder(monkeypatch, _make_fake_embedder())

    # Default limit=5
    await mem.get_relevant_facts("u", "t", "q")
    positional = conn.fetch.call_args.args
    assert positional[-1] == 5, f"Expected limit=5 as last positional arg, got {positional[-1]!r}"

    conn.fetch.reset_mock()

    # Explicit limit=3
    await mem.get_relevant_facts("u", "t", "q", limit=3)
    positional = conn.fetch.call_args.args
    assert positional[-1] == 3, f"Expected limit=3 as last positional arg, got {positional[-1]!r}"


# ---------------------------------------------------------------------------
# Test 7: signature unchanged
# ---------------------------------------------------------------------------
def test_signature_unchanged():
    """Pure-static gate: parameter names and defaults must not drift."""
    sig = inspect.signature(LongTermMemory.get_relevant_facts)
    params = list(sig.parameters.keys())
    assert params == ["self", "user_id", "tenant_id", "query", "limit"], (
        f"Signature drift detected: {params}"
    )
    assert sig.parameters["limit"].default == 5, (
        f"limit default must be 5, got {sig.parameters['limit'].default!r}"
    )


# ---------------------------------------------------------------------------
# Test 8: returned strings have no bullet prefix (Pitfall 3)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_returns_bare_strings_no_prefix(monkeypatch):
    """No element must start with '- ' or '* ' (bullets belong in RecallTool only)."""
    conn = _make_conn_with_txn()
    conn.fetch = AsyncMock(
        return_value=[{"fact": "bare fact"}, {"fact": "another bare fact"}]
    )
    pool = _make_fake_pool(conn)
    mem = _make_long(pool)

    _patch_embedder(monkeypatch, _make_fake_embedder())

    result = await mem.get_relevant_facts("u", "t", "q")
    for item in result:
        assert not item.startswith("- "), f"Item has bullet prefix: {item!r}"
        assert not item.startswith("* "), f"Item has bullet prefix: {item!r}"


# ---------------------------------------------------------------------------
# Test 9: SQL tie-break includes importance DESC, created_at DESC, LIMIT $4
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tie_break_sql_includes_importance_and_created_at(monkeypatch):
    """Substring check on the SQL passed to conn.fetch (not exact equality)."""
    conn = _make_conn_with_txn()
    pool = _make_fake_pool(conn)
    mem = _make_long(pool)

    _patch_embedder(monkeypatch, _make_fake_embedder())

    await mem.get_relevant_facts("u", "t", "q")

    assert conn.fetch.await_count == 1
    sql = conn.fetch.call_args.args[0]

    assert "WHERE user_id=$1 AND tenant_id=$2" in sql, f"Missing WHERE clause in SQL: {sql!r}"
    assert "ORDER BY embedding <=> $3::vector" in sql, f"Missing cosine ORDER BY in SQL: {sql!r}"
    assert "importance DESC" in sql, f"Missing importance DESC tie-break in SQL: {sql!r}"
    assert "created_at DESC" in sql, f"Missing created_at DESC tie-break in SQL: {sql!r}"
    assert "LIMIT $4" in sql, f"Missing LIMIT $4 in SQL: {sql!r}"


# ---------------------------------------------------------------------------
# Test 10 (ADDED — T1 / Decision-1): load_context returns long_term_facts=[]
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_load_context_drops_long_term_facts(monkeypatch):
    """After Decision-1, load_context must return long_term_facts=[]."""

    # Patch _short and _long on a fresh MemoryService
    svc = MemoryService.__new__(MemoryService)
    svc._short = MagicMock()
    svc._long = MagicMock()

    svc._short.get_history = AsyncMock(
        return_value=[{"role": "user", "content": "hi"}]
    )
    svc._long.get_user_profile = AsyncMock(return_value=None)
    # get_relevant_facts must NOT be awaited (T1)
    svc._long.get_relevant_facts = AsyncMock(return_value=["should not appear"])

    mem_ctx = await svc.load_context(
        session_id="s1",
        user_id="u1",
        tenant_id="t1",
        query="test query",
    )

    assert mem_ctx.long_term_facts == [], (
        f"load_context must return long_term_facts=[], got {mem_ctx.long_term_facts!r}"
    )


# ---------------------------------------------------------------------------
# Test 11 (ADDED — T1 / Decision-1): load_context must NOT await get_relevant_facts
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_load_context_does_not_call_get_relevant_facts(monkeypatch):
    """After Decision-1, load_context must never await _long.get_relevant_facts."""
    svc = MemoryService.__new__(MemoryService)
    svc._short = MagicMock()
    svc._long = MagicMock()

    svc._short.get_history = AsyncMock(return_value=[])
    svc._long.get_user_profile = AsyncMock(return_value=None)
    svc._long.get_relevant_facts = AsyncMock(return_value=["should not appear"])

    await svc.load_context(
        session_id="s1",
        user_id="u1",
        tenant_id="t1",
        query="test query",
    )

    svc._long.get_relevant_facts.assert_not_awaited()
    assert svc._long.get_relevant_facts.call_count == 0, (
        f"get_relevant_facts called {svc._long.get_relevant_facts.call_count} time(s); expected 0"
    )
