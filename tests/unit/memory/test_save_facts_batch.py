"""tests/unit/memory/test_save_facts_batch.py — Phase 27 / TD-05 / SC-4.

Mock-counting tests pinning the "1× embed_batch + 1× bulk dedupe + 1× executemany"
contract for ``LongTermMemory.save_facts`` (plan 27-04 Task 2).

What SC-4 actually asserts (RESEARCH §"Mock-counting test for 1-RTT contract"):
  * embedder.embed_batch is awaited EXACTLY ONCE for the whole batch.
  * conn.fetch is awaited EXACTLY ONCE (the bulk dedupe SELECT — C1 SQL).
  * conn.executemany is awaited EXACTLY ONCE (the batch INSERT).
  * The strict "1 PG RTT" budget allows piggybacked SET LOCAL execute calls
    (they share the precheck transaction's connection) — what matters is the
    DATA queries (fetch + executemany).

Also pins the C1 corrected SQL shape so any future regression that flips back
to ``unnest($1::vector[])`` (which the pgvector.asyncpg codec hijacks per
D-13) will fail this file before reaching live PG.

Patterns A+B+C from PATTERNS.md §"Shared Patterns".
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.memory.memory_service import LongTermMemory, SaveFactsResult
from utils.models import ExtractedFact


# -----------------------------------------------------------------------------
# Pattern B — autouse singleton reset
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool(
    *,
    fetch_mock: AsyncMock | None = None,
    execute_mock: AsyncMock | None = None,
    executemany_mock: AsyncMock | None = None,
) -> tuple[MagicMock, MagicMock]:
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
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool

    async def _get_pool():
        return pool

    lt._get_pool = _get_pool
    return lt


def _patch_embedder_batch(monkeypatch, n: int = 5) -> tuple[MagicMock, AsyncMock]:
    """Dual-path patch on get_embedder; return (fake_embedder, embed_batch_spy)."""
    embed_batch_spy = AsyncMock(return_value=[[0.1] * 1024 for _ in range(n)])
    fake = MagicMock(
        embed_batch=embed_batch_spy,
        embed_one=AsyncMock(return_value=[0.1] * 1024),
    )
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder", lambda: fake,
    )
    monkeypatch.setattr(
        "services.memory.memory_service.get_embedder",
        lambda: fake,
        raising=False,
    )
    return fake, embed_batch_spy


def _patch_audit(monkeypatch) -> MagicMock:
    mock_audit = MagicMock(log=AsyncMock())
    monkeypatch.setattr(
        "services.audit.audit_service.get_audit_service",
        lambda: mock_audit,
    )
    return mock_audit


def _make_facts(n: int) -> list[ExtractedFact]:
    return [
        ExtractedFact(
            fact=f"fact number {i}",
            category="recurring_topics",
            importance=0.5,
        )
        for i in range(n)
    ]


# -----------------------------------------------------------------------------
# Test 1 — SC-4 mock counting (1 embed_batch + 1 executemany)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_facts_5_emits_exactly_1_embed_batch_and_1_executemany(monkeypatch):
    """5-fact turn → exactly 1× embed_batch + 1× bulk dedupe + 1× executemany.

    This is THE SC-4 mock-count test for plan 27-04. Watch for any future
    change that loops over facts inside save_facts — embed_batch.call_count
    or executemany.await_count != 1 would catch the regression.
    """
    _, embed_batch_spy = _patch_embedder_batch(monkeypatch, n=5)
    _patch_audit(monkeypatch)

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)
    facts = _make_facts(5)

    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # 1× embed_batch call with all 5 strings.
    assert embed_batch_spy.call_count == 1, (
        f"Expected 1 embed_batch call, got {embed_batch_spy.call_count}"
    )
    assert embed_batch_spy.call_args.args[0] == [f.fact for f in facts]

    # 1× executemany INSERT.
    assert conn.executemany.call_count == 1, (
        f"Expected 1 executemany call, got {conn.executemany.call_count}"
    )
    insert_sql = conn.executemany.call_args.args[0]
    assert "INSERT INTO long_term_facts" in insert_sql
    assert "$6::vector" in insert_sql
    # All 5 rows passed in a single executemany batch.
    assert len(conn.executemany.call_args.args[1]) == 5

    # 1× bulk dedupe SELECT.
    assert conn.fetch.call_count == 1, (
        f"Expected 1 bulk dedupe SELECT, got {conn.fetch.call_count}"
    )

    # Result counts match.
    assert result == SaveFactsResult(
        saved_count=5, skipped_near_duplicates=0, skipped_embed_failures=0,
    )


# -----------------------------------------------------------------------------
# Test 2 — empty list short-circuits
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_facts_empty_list_returns_zeros(monkeypatch):
    _, embed_batch_spy = _patch_embedder_batch(monkeypatch, n=0)
    _patch_audit(monkeypatch)

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)

    result = await mem.save_facts([], user_id="u1", tenant_id="t1")

    assert result == SaveFactsResult(0, 0, 0)
    # Embedder NOT called for empty input.
    assert embed_batch_spy.call_count == 0
    # PG NOT touched for empty input.
    assert conn.fetch.call_count == 0
    assert conn.executemany.call_count == 0


# -----------------------------------------------------------------------------
# Test 3 — C1 SQL pattern: unnest($1::text[]) WITH ORDINALITY + vec_txt::vector
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_facts_bulk_dedupe_sql_uses_text_array_pattern_c1(monkeypatch):
    """The bulk dedupe SQL MUST use C1's text[] cast pattern.

    Regression bar: pgvector.asyncpg.register_vector (called in _get_pool's
    init hook) hijacks $1::vector[] parameter binding. The C1 pattern
    sidesteps the codec by passing $1 as text[] of vector literals, with
    the cast applied per-row via vec_txt::vector inside EXISTS. RESEARCH §10
    has the empirical validation against live PG.

    This test pins both the SQL shape AND the parameter type.
    """
    _, _ = _patch_embedder_batch(monkeypatch, n=3)
    _patch_audit(monkeypatch)

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)
    facts = _make_facts(3)

    await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # Capture the bulk dedupe SQL + first positional bind.
    fetch_call = conn.fetch.call_args
    sql = fetch_call.args[0]
    vec_literals_arg = fetch_call.args[1]

    # SQL shape — C1 corrected pattern.
    assert "unnest($1::text[]) WITH ORDINALITY" in sql, (
        f"Bulk dedupe SQL must use unnest($1::text[]) WITH ORDINALITY. SQL: {sql!r}"
    )
    assert "vec_txt::vector" in sql, (
        f"Bulk dedupe must cast per-row via vec_txt::vector. SQL: {sql!r}"
    )
    # NOT the broken pattern.
    assert "unnest($1::vector[])" not in sql, (
        "Bulk dedupe must NOT use $1::vector[] (the pgvector codec hijacks it)."
    )

    # First bind is a list of strings (pgvector text literals — C1).
    assert isinstance(vec_literals_arg, list)
    assert len(vec_literals_arg) == 3
    assert all(isinstance(lit, str) for lit in vec_literals_arg)
    # Each literal is pgvector text form: '[x,y,z,...]'
    for lit in vec_literals_arg:
        assert lit.startswith("[") and lit.endswith("]")
