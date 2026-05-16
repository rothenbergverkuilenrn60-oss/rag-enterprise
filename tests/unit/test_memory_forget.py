"""tests/unit/test_memory_forget.py — Phase 25 / GDPR-01 + T7.

Covers LongTermMemory.forget_user (chunked at 1000/txn per T7):
  Test 1: class MemoryForgetError exists and is Exception subclass.
  Test 2: happy path — chunk returns "DELETE 3" + "DELETE 0"; method returns int 3.
  Test 3: idempotent — first chunk "DELETE 0"; method returns int 0; execute called once.
  Test 4: asyncpg.PostgresError -> MemoryForgetError raised.
  Test 5: __cause__ chained (raise MemoryForgetError from exc).
  Test 6: SQL args — "WHERE user_id=$1 AND tenant_id=$2" + "LIMIT 1000" present; args match.
  Test 7 (T7): large bucket — 4 chunks "DELETE 1000" x 2 + "DELETE 500" + "DELETE 0";
               total == 2500; execute.await_count == 4.

Imports of services.memory.memory_service symbols live inside test bodies so that
collection succeeds even before GREEN production code lands (Task 2 of Plan 25-02).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest


# -----------------------------------------------------------------------------
# Fake-pool harness — copied verbatim from tests/unit/test_memory_save_fact.py:50-80
# (Analog 7 in 25-PATTERNS.md). forget_user only uses pool.acquire() + conn.execute(),
# so no fetchrow extension is needed.
# -----------------------------------------------------------------------------
class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool(execute_mock: AsyncMock) -> tuple[MagicMock, MagicMock]:
    """Return (pool, conn) where pool.acquire() yields a conn with the given
    execute mock. conn is returned for awaited-count assertions.
    """
    conn = MagicMock(execute=execute_mock)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool, conn


def _make_long(pool: MagicMock):
    """Construct LongTermMemory with pool pre-injected (bypass _get_pool)."""
    from services.memory.memory_service import LongTermMemory

    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool

    async def _get_pool():
        return pool

    lt._get_pool = _get_pool
    return lt


# -----------------------------------------------------------------------------
# Test 1: MemoryForgetError class exists and subclasses Exception
# -----------------------------------------------------------------------------
def test_memory_forget_error_class_exists():
    from services.memory.memory_service import MemoryForgetError

    assert issubclass(MemoryForgetError, Exception)


# -----------------------------------------------------------------------------
# Test 2: happy path — two chunks ("DELETE 3" + "DELETE 0") return int 3
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forget_user_returns_row_count():
    execute = AsyncMock(side_effect=["DELETE 3", "DELETE 0"])
    pool, _conn = _make_fake_pool(execute)
    lt = _make_long(pool)

    result = await lt.forget_user("alice", "acme")

    assert result == 3
    assert execute.await_count == 2


# -----------------------------------------------------------------------------
# Test 3: idempotent — empty bucket returns 0 with a single execute call
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forget_user_idempotent_zero():
    execute = AsyncMock(return_value="DELETE 0")
    pool, _conn = _make_fake_pool(execute)
    lt = _make_long(pool)

    result = await lt.forget_user("ghost", "acme")

    assert result == 0
    assert execute.await_count == 1


# -----------------------------------------------------------------------------
# Test 4: asyncpg.PostgresError -> MemoryForgetError raised
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forget_user_raises_memory_forget_error_on_pg_error():
    from services.memory.memory_service import MemoryForgetError

    execute = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
    pool, _conn = _make_fake_pool(execute)
    lt = _make_long(pool)

    with pytest.raises(MemoryForgetError):
        await lt.forget_user("alice", "acme")


# -----------------------------------------------------------------------------
# Test 5: __cause__ chained (raise ... from exc)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forget_user_error_chains_cause():
    from services.memory.memory_service import MemoryForgetError

    pg_error = asyncpg.PostgresError("boom")
    execute = AsyncMock(side_effect=pg_error)
    pool, _conn = _make_fake_pool(execute)
    lt = _make_long(pool)

    with pytest.raises(MemoryForgetError) as exc_info:
        await lt.forget_user("alice", "acme")

    assert exc_info.value.__cause__ is pg_error
    assert isinstance(exc_info.value.__cause__, asyncpg.PostgresError)


# -----------------------------------------------------------------------------
# Test 6: SQL args — parameterized WHERE + LIMIT 1000 (subquery form);
#         first call passes ("alice", "acme") as positional args
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forget_user_sql_args():
    execute = AsyncMock(side_effect=["DELETE 0"])
    pool, _conn = _make_fake_pool(execute)
    lt = _make_long(pool)

    await lt.forget_user("alice", "acme")

    assert execute.await_count == 1
    first_call = execute.call_args_list[0]
    sql = first_call.args[0]
    assert "WHERE user_id=$1 AND tenant_id=$2" in sql
    assert "LIMIT" in sql  # chunked subquery form (LIMIT 1000 or LIMIT $3)
    # Positional args after the SQL string must include both ids in order.
    rest = first_call.args[1:]
    assert "alice" in rest
    assert "acme" in rest


# -----------------------------------------------------------------------------
# Test 7 (T7 — outside voice F1): large bucket chunks at 1000/txn,
#         terminates on "DELETE 0", sums total deletions across chunks
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forget_user_chunks_large_bucket():
    execute = AsyncMock(
        side_effect=["DELETE 1000", "DELETE 1000", "DELETE 500", "DELETE 0"]
    )
    pool, _conn = _make_fake_pool(execute)
    lt = _make_long(pool)

    result = await lt.forget_user("alice", "acme")

    assert result == 2500
    assert execute.await_count == 4
