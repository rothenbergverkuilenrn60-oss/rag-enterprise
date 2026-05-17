"""
tests/unit/test_memory_schema.py
Phase 23 / MEM-01 — DDL idempotency + HNSW index presence + typed-exception import.

RED gates per Plan 23-01 Task 1. Each test fails on the unmodified tree with
``AttributeError`` / ``AssertionError`` / ``ImportError`` until Task 2 lands
the schema migration in ``services/memory/memory_service.py``.

Mocks at the consumer path (``services.memory.memory_service.<dep>``) per
v1.3 D-08 — tests never touch asyncpg / pgvector directly.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    """Mirror tests/unit/test_memory_service.py: clear the module-level singleton between tests."""
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


def _build_fake_pool() -> tuple[MagicMock, MagicMock]:
    """Build an async-context-manager fake pool whose acquire() yields a MagicMock conn."""
    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock()

    fake_pool = MagicMock()
    fake_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return fake_pool, fake_conn


def _concat_sql(fake_conn: MagicMock) -> str:
    """Concatenate all SQL strings issued via conn.execute(...) for substring assertions."""
    return "\n".join(call.args[0] for call in fake_conn.execute.call_args_list)


@pytest.mark.asyncio
async def test_create_tables_idempotent() -> None:
    """Test 1 — running _create_tables twice does not raise; new DDL strings present."""
    from services.memory.memory_service import LongTermMemory

    mem = LongTermMemory()
    fake_pool, fake_conn = _build_fake_pool()
    mem._pool = fake_pool  # bypass _get_pool

    await mem._create_tables()
    await mem._create_tables()  # second call must be a no-op (IF NOT EXISTS)

    sql = _concat_sql(fake_conn)
    assert "ALTER TABLE long_term_facts ADD COLUMN IF NOT EXISTS embedding vector(1024)" in sql, (
        "missing ALTER TABLE ADD COLUMN IF NOT EXISTS embedding vector(1024) — "
        f"observed SQL:\n{sql}"
    )
    assert "CREATE INDEX IF NOT EXISTS ltf_emb_hnsw_idx" in sql, (
        "missing CREATE INDEX IF NOT EXISTS ltf_emb_hnsw_idx"
    )
    assert "USING hnsw" in sql, "HNSW index DDL missing USING hnsw clause"
    assert "vector_cosine_ops" in sql, "HNSW index DDL missing vector_cosine_ops opclass"
    assert "m = 16" in sql, "HNSW index DDL missing m = 16 parameter"
    assert "ef_construction = 64" in sql, "HNSW index DDL missing ef_construction = 64 parameter"


@pytest.mark.asyncio
async def test_hnsw_index_uses_settings_embedding_dim(monkeypatch) -> None:
    """Test 2 — embedding column dim tracks settings.embedding_dim (monkeypatched to 2048)."""
    import services.memory.memory_service as mod
    from services.memory.memory_service import LongTermMemory

    # Patch at consumer path. settings module is lazy-imported inside _create_tables;
    # patch the underlying settings instance so the lazy import sees 2048.
    from config.settings import settings as real_settings
    monkeypatch.setattr(real_settings, "embedding_dim", 2048, raising=False)
    # Also patch at consumer path in case the module hoists the import in the future.
    monkeypatch.setattr(mod, "settings", real_settings, raising=False)

    mem = LongTermMemory()
    fake_pool, fake_conn = _build_fake_pool()
    mem._pool = fake_pool

    await mem._create_tables()

    sql = _concat_sql(fake_conn)
    assert "vector(2048)" in sql, (
        f"ALTER TABLE did not interpolate settings.embedding_dim=2048; observed SQL:\n{sql}"
    )


def test_memory_fact_write_error_importable() -> None:
    """Test 4 — MemoryFactWriteError is importable + subclass of Exception + has docstring."""
    from services.memory.memory_service import MemoryFactWriteError

    assert issubclass(MemoryFactWriteError, Exception)
    assert MemoryFactWriteError.__doc__, "MemoryFactWriteError must carry a docstring"
