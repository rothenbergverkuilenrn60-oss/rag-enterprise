"""Unit tests for memory_service prepare_dsn adoption + close() (Plan 26-03 / TD-03).

MemoryContext is a dataclass (not a pool-bearing class) — only LongTermMemory
has the asyncpg pool that needs the prepare_dsn migration + close().
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest


@pytest.mark.asyncio
async def test_long_term_memory_uses_prepare_dsn(monkeypatch) -> None:
    """LongTermMemory._get_pool must call prepare_dsn instead of inline strip."""
    from services.memory.memory_service import LongTermMemory

    spy = MagicMock(return_value=("postgresql://stubbed", {}))
    monkeypatch.setattr("services.memory.memory_service.prepare_dsn", spy)

    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock()
    create_pool_mock = AsyncMock(return_value=fake_pool)
    monkeypatch.setattr("services.memory.memory_service.asyncpg.create_pool", create_pool_mock)

    # Stub _create_tables so we don't hit PG
    ltm = LongTermMemory()
    monkeypatch.setattr(ltm, "_create_tables", AsyncMock())

    await ltm._get_pool()

    assert spy.called, "prepare_dsn should be called once by _get_pool"
    assert spy.call_count == 1


@pytest.mark.asyncio
async def test_long_term_memory_close_idempotent(monkeypatch) -> None:
    """close() called twice — second is no-op (pool already None)."""
    from services.memory.memory_service import LongTermMemory

    ltm = LongTermMemory()
    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()
    ltm._pool = fake_pool

    await ltm.close()
    await ltm.close()

    assert fake_pool.close.await_count == 1, "Pool close should only be awaited once"
    assert ltm._pool is None


@pytest.mark.asyncio
async def test_long_term_memory_close_when_pool_never_built() -> None:
    """close() must not raise when _pool is None (never accessed)."""
    from services.memory.memory_service import LongTermMemory

    ltm = LongTermMemory()
    assert ltm._pool is None
    await ltm.close()  # must not raise
    assert ltm._pool is None
