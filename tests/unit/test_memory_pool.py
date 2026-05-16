"""
tests/unit/test_memory_pool.py
Phase 23 / MEM-01 — LongTermMemory._get_pool registers the pgvector codec.

RED gate per Plan 23-01 Task 1. Fails on unmodified tree because current
_get_pool does NOT pass init=<callable> to asyncpg.create_pool, and the
register_vector symbol is not imported in services.memory.memory_service.

Mocks at consumer path per v1.3 D-08.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


@pytest.mark.asyncio
async def test_register_vector_init(monkeypatch) -> None:
    """_get_pool must call asyncpg.create_pool with an init= callable that
    awaits pgvector.asyncpg.register_vector on every acquired connection."""
    from services.memory.memory_service import LongTermMemory

    # Sentinel pool returned by the patched create_pool. _get_pool then awaits
    # self._create_tables(), which itself re-enters _get_pool — short-circuit
    # that by stubbing _create_tables on the instance.
    sentinel_pool = MagicMock(name="sentinel_pool")
    create_pool_mock = AsyncMock(return_value=sentinel_pool)
    register_vector_mock = AsyncMock()

    monkeypatch.setattr(
        "services.memory.memory_service.asyncpg.create_pool",
        create_pool_mock,
        raising=True,
    )
    # raising=False because Plan 01 introduces this symbol; pre-Task-2 the
    # attribute does not exist and the test must still drive the GREEN target.
    monkeypatch.setattr(
        "services.memory.memory_service.register_vector",
        register_vector_mock,
        raising=False,
    )

    mem = LongTermMemory()
    mem._pool = None

    # Stub _create_tables to keep the test focused on pool-init wiring.
    async def _noop() -> None:
        return None
    mem._create_tables = _noop  # type: ignore[method-assign]

    pool = await mem._get_pool()
    assert pool is sentinel_pool

    # Assert create_pool was called once with init= as a kwarg.
    assert create_pool_mock.await_count == 1
    _, kwargs = create_pool_mock.call_args
    assert "init" in kwargs, (
        f"asyncpg.create_pool not called with init= kwarg; kwargs={list(kwargs)}"
    )
    init_cb = kwargs["init"]
    assert callable(init_cb), "init kwarg must be an async callable"

    # Invoke the init callback with a dummy conn; assert register_vector awaited.
    dummy_conn = MagicMock(name="dummy_conn")
    await init_cb(dummy_conn)
    register_vector_mock.assert_awaited_once_with(dummy_conn)
