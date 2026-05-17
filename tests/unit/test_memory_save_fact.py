"""tests/unit/test_memory_save_fact.py — Phase 23 / MEM-02 (Plan 23-02 RED).

Originally covered the embed-on-write rewrite of ``LongTermMemory.save_fact``
(Phase 23). Phase 27 / TD-05 (plan 27-04) converted ``save_fact`` into a
**D-12 thin wrapper** that delegates to ``LongTermMemory.save_facts``. The
outside contract preserved by this test file is still:

  Test 1: happy path — embedder is called exactly once, INSERT runs with
          ``$6::vector`` cast and a 1024-dim embedding parameter.
  Test 2: embedder failure (parametrized over RuntimeError / httpx.HTTPError /
          OSError) raises ``MemoryFactWriteError`` with ``__cause__`` chained
          and zero partial-write rows.
  Test 3: asyncpg.PostgresError on INSERT raises ``MemoryFactWriteError`` with
          ``__cause__`` chained.
  Test 4: signature gate — parameter names + defaults unchanged.

What changed in 27-04 internals (call shape):
  * save_fact wraps ``await self.save_facts([ExtractedFact(...)])``
  * save_facts calls ``embed_batch`` (NOT embed_one) on the embedder
  * Near-duplicate check uses ``conn.fetch`` (bulk SELECT) not ``conn.fetchrow``
  * Insert uses ``conn.executemany`` (single-row batch) not ``conn.execute``

Mocks at the source path (``services.vectorizer.embedder.get_embedder``)
because ``LongTermMemory.save_facts`` performs a lazy import of the symbol
inside the method body. Both call shapes covered via dual-path patch
(source + consumer).

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
    executemany_mock: AsyncMock | None = None,
    fetch_mock: AsyncMock | None = None,
    execute_mock: AsyncMock | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Return (pool, conn) for the 27-04 save_facts batch path.

    Defaults wire up a happy-path conn:
      * ``fetch``      → empty list (no near-duplicates).
      * ``execute``    → AsyncMock (SET LOCAL pair inside bulk dedupe).
      * ``executemany``→ AsyncMock (INSERT batch).
      * ``transaction``→ async-CM yielding the same conn so SET LOCAL execute
                         calls go through the same mock.
    """
    if fetch_mock is None:
        fetch_mock = AsyncMock(return_value=[])
    if execute_mock is None:
        execute_mock = AsyncMock()
    if executemany_mock is None:
        executemany_mock = AsyncMock()
    conn = MagicMock(
        execute=execute_mock,
        executemany=executemany_mock,
        fetch=fetch_mock,
    )
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


def _patch_embedder_batch(
    monkeypatch, batch_side_effect=None, batch_return=None,
) -> MagicMock:
    """27-04 dual-path patch — save_facts calls embed_batch (not embed_one)."""
    if batch_return is None:
        batch_return = [[0.1] * 1024]
    embed_batch = AsyncMock(side_effect=batch_side_effect, return_value=batch_return)
    embed_one = AsyncMock(return_value=[0.1] * 1024)
    fake = MagicMock(embed_batch=embed_batch, embed_one=embed_one)
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder", lambda: fake,
    )
    monkeypatch.setattr(
        "services.memory.memory_service.get_embedder", lambda: fake, raising=False,
    )
    return fake


# -----------------------------------------------------------------------------
# Test 1: happy path — embed-on-write, $6::vector cast, 1024-dim param
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_fact_embeds_one_row_with_1024_dim_embedding(monkeypatch):
    embedder = _patch_embedder_batch(monkeypatch)

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)

    await mem.save_fact(
        user_id="u1",
        tenant_id="t1",
        fact="user prefers React",
        importance=0.8,
    )

    # Embedder.embed_batch called exactly once with the single-fact list.
    embedder.embed_batch.assert_awaited_once_with(["user prefers React"])

    # 27-04: INSERT lands via executemany (single-element batch).
    assert conn.executemany.await_count == 1, (
        f"Expected 1 executemany call, got {conn.executemany.await_count}"
    )
    insert_call = conn.executemany.call_args
    sql = insert_call.args[0]
    assert "INSERT INTO long_term_facts" in sql
    assert "embedding" in sql
    assert "$6::vector" in sql

    # rows_to_insert is the second positional arg — list of tuples.
    rows = insert_call.args[1]
    assert len(rows) == 1
    assert rows[0] == ("u1", "t1", "user prefers React", "", 0.8, [0.1] * 1024)

    # Bulk dedupe SELECT was issued exactly once (empty-table mock → no audit).
    assert conn.fetch.await_count == 1


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
    monkeypatch, exc_cls, exc_msg,
):
    """Singular caller contract (D-12 wrapper preserves pre-27-03 behavior):
    when the ONLY fact in the batch fails to embed (both embed_batch and the
    per-item fallback embed_one raise), save_fact raises MemoryFactWriteError.
    """
    # Stub embed_batch AND embed_one fallback to raise — exhausts both paths.
    fake = MagicMock(
        embed_batch=AsyncMock(side_effect=exc_cls(exc_msg)),
        embed_one=AsyncMock(side_effect=exc_cls(exc_msg)),
    )
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder", lambda: fake,
    )
    monkeypatch.setattr(
        "services.memory.memory_service.get_embedder", lambda: fake, raising=False,
    )

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)

    with pytest.raises(MemoryFactWriteError):
        await mem.save_fact(
            user_id="u1",
            tenant_id="t1",
            fact="user prefers React",
        )

    # Zero partial-write rows — executemany never reached because the only
    # candidate had embed_failures==1, saved_count==0.
    assert conn.executemany.await_count == 0


# -----------------------------------------------------------------------------
# Test 3: asyncpg failure → MemoryFactWriteError with __cause__
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_fact_pg_failure_raises_typed_error(monkeypatch):
    _patch_embedder_batch(monkeypatch)

    # executemany raises — preserves the "INSERT failure → MemoryFactWriteError"
    # contract from pre-27-04 (it was conn.execute then; now it's executemany).
    executemany_mock = AsyncMock(side_effect=asyncpg.PostgresError("dim mismatch"))
    pool, _ = _make_fake_pool(executemany_mock=executemany_mock)
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
