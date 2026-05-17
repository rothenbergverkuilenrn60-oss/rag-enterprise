"""tests/unit/test_memory_save_fact.py — Phase 23 / MEM-02 (Plan 23-02 RED).

Covers the embed-on-write rewrite of ``LongTermMemory.save_fact``:

  Test 1: happy path — embedder called once, INSERT awaited once with
          `$6::vector` cast and 1024-dim embedding parameter.
  Test 2: embedder failure (parametrized over RuntimeError / httpx.HTTPError /
          OSError) raises ``MemoryFactWriteError`` with ``__cause__`` chained
          and zero partial-write rows (conn.execute never awaited).
  Test 3: asyncpg.PostgresError on INSERT raises ``MemoryFactWriteError`` with
          ``__cause__`` chained.
  Test 4: signature gate — parameter names + defaults unchanged.

Mocks at the source path (``services.vectorizer.embedder.get_embedder``)
because ``LongTermMemory.save_fact`` performs a lazy import of the symbol
inside the method body (circular-import resilience per repo convention) —
patching the consumer-module attr would not intercept a fresh ``from … import``.
Also patches the consumer-module attr (``services.memory.memory_service.
get_embedder``, ``raising=False``) so both call shapes are covered.

Env-var setdefault block at module top mirrors ``tests/unit/test_memory_service.py``.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import inspect
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import httpx
import pytest

from services.memory.memory_service import LongTermMemory, MemoryFactWriteError


# -----------------------------------------------------------------------------
# Fixtures / helpers
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool(
    execute_mock: AsyncMock,
    fetchrow_mock: AsyncMock | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Return (pool, conn) where pool.acquire() yields a conn with the given
    execute mock. conn is returned for awaited-count assertions.

    Plan 27-03 / TD-04 — save_fact now runs a cosine precheck before INSERT,
    so the conn mock needs ``fetchrow`` (the precheck SELECT) and
    ``transaction()`` (an async-CM wrapper around the SET LOCAL pair). Default
    fetchrow → ``None`` (empty table = no near-dup), transaction → re-yields
    the same conn so SET LOCAL execute calls hit the same mock.
    """
    if fetchrow_mock is None:
        fetchrow_mock = AsyncMock(return_value=None)
    conn = MagicMock(execute=execute_mock, fetchrow=fetchrow_mock)
    conn.transaction = MagicMock(return_value=_AcquireCtx(conn))
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool, conn


def _make_long(pool: MagicMock) -> LongTermMemory:
    """Construct LongTermMemory with pool pre-injected (bypass _get_pool)."""
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool

    async def _get_pool():
        return pool

    lt._get_pool = _get_pool
    return lt


# -----------------------------------------------------------------------------
# Test 1: happy path — embed-on-write, $6::vector cast, 1024-dim param
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_fact_embeds_one_row_with_1024_dim_embedding(monkeypatch):
    embed_one = AsyncMock(return_value=[0.1] * 1024)
    fake_embedder = MagicMock(embed_one=embed_one)
    # Source-path patch (intercepts the lazy `from … import get_embedder`).
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder",
        lambda: fake_embedder,
    )
    # Consumer-path patch (raising=False — name not bound at module top).
    monkeypatch.setattr("services.memory.memory_service.get_embedder", lambda: fake_embedder, raising=False)

    execute = AsyncMock()
    pool, conn = _make_fake_pool(execute)
    mem = _make_long(pool)

    await mem.save_fact(
        user_id="u1",
        tenant_id="t1",
        fact="user prefers React",
        importance=0.8,
    )

    # Embedder called exactly once with the fact text.
    embed_one.assert_awaited_once_with("user prefers React")

    # Plan 27-03 / TD-04: save_fact now runs 2 SET LOCAL execute calls (inside
    # the precheck transaction) + 1 INSERT execute. The INSERT is the LAST
    # execute call. Precheck SELECT goes through fetchrow (counted separately).
    assert conn.execute.await_count == 3, (
        f"Expected 2 SET LOCAL + 1 INSERT execute calls, got {conn.execute.await_count}"
    )
    insert_call = conn.execute.call_args_list[-1]
    sql = insert_call.args[0]
    assert "INSERT INTO long_term_facts" in sql
    assert "embedding" in sql
    assert "$6::vector" in sql

    # Positional params: user_id, tenant_id, fact, source_doc, importance, embedding
    positional = insert_call.args[1:]
    assert positional == ("u1", "t1", "user prefers React", "", 0.8, [0.1] * 1024)

    # Precheck SELECT was issued exactly once (empty-table mock → no audit row).
    assert conn.fetchrow.await_count == 1


# -----------------------------------------------------------------------------
# Test 2: embedder failure → MemoryFactWriteError, zero partial-write rows
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exc_cls,exc_msg",
    [
        (RuntimeError, "ollama down"),
        (httpx.HTTPError, "transport"),
        (OSError, "torch device"),
    ],
)
@pytest.mark.asyncio
async def test_save_fact_embedder_failure_raises_typed_error_no_partial_write(
    monkeypatch, exc_cls, exc_msg
):
    embed_one = AsyncMock(side_effect=exc_cls(exc_msg))
    fake_embedder = MagicMock(embed_one=embed_one)
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder",
        lambda: fake_embedder,
    )
    monkeypatch.setattr("services.memory.memory_service.get_embedder", lambda: fake_embedder, raising=False)

    execute = AsyncMock()
    pool, conn = _make_fake_pool(execute)
    mem = _make_long(pool)

    with pytest.raises(MemoryFactWriteError) as exc_info:
        await mem.save_fact(
            user_id="u1",
            tenant_id="t1",
            fact="user prefers React",
        )

    # Zero partial-write rows — INSERT never reached.
    assert conn.execute.await_count == 0
    # __cause__ preserved for debuggability.
    assert isinstance(exc_info.value.__cause__, exc_cls)


# -----------------------------------------------------------------------------
# Test 3: asyncpg failure → MemoryFactWriteError with __cause__
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_fact_pg_failure_raises_typed_error(monkeypatch):
    embed_one = AsyncMock(return_value=[0.1] * 1024)
    fake_embedder = MagicMock(embed_one=embed_one)
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder",
        lambda: fake_embedder,
    )
    monkeypatch.setattr("services.memory.memory_service.get_embedder", lambda: fake_embedder, raising=False)

    execute = AsyncMock(side_effect=asyncpg.PostgresError("dim mismatch"))
    pool, _ = _make_fake_pool(execute)
    mem = _make_long(pool)

    with pytest.raises(MemoryFactWriteError) as exc_info:
        await mem.save_fact(
            user_id="u1",
            tenant_id="t1",
            fact="user prefers React",
        )
    assert isinstance(exc_info.value.__cause__, asyncpg.PostgresError)


# -----------------------------------------------------------------------------
# Test 4: signature unchanged
# -----------------------------------------------------------------------------
def test_save_fact_signature_unchanged():
    sig = inspect.signature(LongTermMemory.save_fact)
    params = list(sig.parameters.keys())
    assert params == ["self", "user_id", "tenant_id", "fact", "source_doc", "importance"]
    assert sig.parameters["source_doc"].default == ""
    assert sig.parameters["importance"].default == 0.5
