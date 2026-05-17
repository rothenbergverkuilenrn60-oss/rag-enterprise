"""TOC-01 integration test — TOCTOU race closure for save_facts.

Requirement: TOC-01 (Phase 29 / Plan 29-00)
Context: .planning/phases/29-toctou-silent-skip-enforcement/29-CONTEXT.md D-TOC-01

Two parallel ``save_facts`` writers with the same (user_id, tenant_id) and
identical fact text MUST produce exactly 1 row in ``long_term_facts`` once the
``pg_advisory_xact_lock(hashtext($1 || '|' || $2))`` advisory lock wraps the
precheck SELECT + executemany INSERT (GREEN phase — Plan 29-00 Task 1).

RED phase (Plan 29-00 Task 0): without the lock, concurrent writers both pass
the bulk-dedupe SELECT at timestamp T0 before either has INSERTed, and both
proceed to INSERT — producing COUNT(*) == 2. This test asserts COUNT(*) == 1
and therefore FAILS red until the lock is in place.

Skip-gated on PG_AVAILABLE (Pattern E — mirrors test_memory_suite_factory_migrated.py).
Embedder is monkeypatched to return a fixed [0.1]*1024 vector (no network).
Each writer uses an INDEPENDENT asyncpg pool (single-pool variant may serialize
and not surface the race — Open Risk #2, 29-CONTEXT.md).
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from tests.conftest import PG_AVAILABLE

# Shared DSN — same as conftest.PG_DSN
_PG_DSN = "postgresql://rag:rag@localhost:5432/ragdb"

# Marker applied at module level (skip-if-no-PG + uses_postgres gate)
pytestmark = [
    pytest.mark.uses_postgres,
    pytest.mark.skipif(not PG_AVAILABLE, reason="needs live PostgreSQL"),
]

# ---------------------------------------------------------------------------
# Capture list for A1-A GUC integration assertion
# ---------------------------------------------------------------------------
_guc_capture: list[dict[str, str]] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _make_pool() -> asyncpg.Pool:
    """Create an independent asyncpg pool with pgvector codec registered."""
    from pgvector.asyncpg import register_vector

    async def _init(conn: asyncpg.Connection) -> None:
        await register_vector(conn)

    pool: asyncpg.Pool = await asyncpg.create_pool(
        _PG_DSN,
        min_size=1,
        max_size=3,
        init=_init,
    )
    return pool


def _patch_embedder_fixed(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Monkeypatch embedder to return fixed [0.1]*1024 for all calls.

    Both concurrent writers receive identical vectors so the bulk-dedupe
    SELECT finds distance == 0 < threshold — only the advisory lock prevents
    both from proceeding past the precheck.
    """
    fake = MagicMock(
        embed_batch=AsyncMock(return_value=[[0.1] * 1024]),
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
    return fake


# ---------------------------------------------------------------------------
# Pre/post-test cleanup fixture
# ---------------------------------------------------------------------------
@pytest.fixture
async def clean_toctou_rows() -> Any:
    """Delete test rows before and after each test (idempotent)."""
    if not PG_AVAILABLE:
        yield
        return

    pool = await _make_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM long_term_facts "
                "WHERE user_id = $1 AND tenant_id = $2",
                "toctou-u1", "toctou-t1",
            )
        yield
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM long_term_facts "
                "WHERE user_id = $1 AND tenant_id = $2",
                "toctou-u1", "toctou-t1",
            )
    finally:
        await pool.close()


# ---------------------------------------------------------------------------
# Test 1 — TOC-01 concurrent-writer race
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_facts_toctou_concurrent_writers_produce_one_row(
    clean_toctou_rows: Any,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TOC-01: two parallel writers with same (user_id, tenant_id, fact) → exactly 1 row.

    RED contract: without advisory lock, COUNT(*) lands at 2 because both
    writers pass the bulk-dedupe SELECT (empty table at both T0 queries) and
    both INSERT. Assert COUNT(*) == 1 so this test FAILS RED until Task 1 locks.

    Two independent asyncpg pools (one per writer) are required — a shared pool
    may serialize requests internally and mask the race (29-CONTEXT Open Risk #2).
    """
    _patch_embedder_fixed(monkeypatch)

    from services.memory.memory_service import LongTermMemory
    from utils.models import ExtractedFact

    # Build two independent LongTermMemory instances, each with its own pool.
    pool_a = await _make_pool()
    pool_b = await _make_pool()

    try:
        ltm_a = LongTermMemory.__new__(LongTermMemory)
        ltm_b = LongTermMemory.__new__(LongTermMemory)

        # Ensure schema exists (idempotent CREATE IF NOT EXISTS).
        ltm_a._pool = pool_a

        async def _get_pool_a() -> asyncpg.Pool:
            return pool_a

        async def _get_pool_b() -> asyncpg.Pool:
            return pool_b

        ltm_a._get_pool = _get_pool_a  # type: ignore[method-assign]
        ltm_b._get_pool = _get_pool_b  # type: ignore[method-assign]
        ltm_b._pool = pool_b

        await ltm_a._create_tables()  # idempotent — sets up long_term_facts schema

        fact = ExtractedFact(
            fact="toctou-test-fact-XYZ",
            category="recurring_topics",
            importance=0.5,
        )

        async def writer_a() -> None:
            await asyncio.sleep(0)  # encourage interleaving
            await ltm_a.save_facts(
                [fact],
                user_id="toctou-u1",
                tenant_id="toctou-t1",
            )

        async def writer_b() -> None:
            await asyncio.sleep(0)  # encourage interleaving
            await ltm_b.save_facts(
                [fact],
                user_id="toctou-u1",
                tenant_id="toctou-t1",
            )

        # Run both writers concurrently.
        await asyncio.gather(writer_a(), writer_b())

    finally:
        await pool_a.close()
        await pool_b.close()

    # Verify via a third independent pool (avoid writer pool quirks).
    verify_pool = await _make_pool()
    try:
        async with verify_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM long_term_facts "
                "WHERE user_id = $1 AND tenant_id = $2 AND fact = $3",
                "toctou-u1", "toctou-t1", "toctou-test-fact-XYZ",
            )
        count = row["n"] if row else 0
        assert count == 1, (
            f"TOC-01 FAILED: expected exactly 1 row after concurrent writers, "
            f"got COUNT(*) = {count}. Race window not closed (advisory lock missing)."
        )
    finally:
        await verify_pool.close()


# ---------------------------------------------------------------------------
# Test 2 — A1-A GUC integration assertion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_facts_guc_preserved_inside_outer_txn(
    clean_toctou_rows: Any,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1-A: SET LOCAL GUCs (hnsw.iterative_scan + ef_search) are still in
    effect when the bulk-dedupe SELECT runs inside the outer advisory-lock txn.

    Monkeypatches ``_bulk_near_duplicate_check_raw`` (the no-txn/no-GUC raw
    helper extracted during GREEN) to additionally capture the current GUC
    values via ``SHOW hnsw.iterative_scan`` and ``SHOW hnsw.ef_search``.

    After ``save_facts`` returns, asserts:
    - ``iterative_scan == "strict_order"``
    - ``ef_search`` is a numeric string (not the PG default "40") — i.e., the
      SET LOCAL from save_facts took effect and was still visible inside the
      outer txn when the bulk SELECT ran.

    This proves the A1-A inlining works: GUCs are NOT reverted by a SAVEPOINT
    release (because the _raw helper no longer opens an inner SAVEPOINT).
    """
    _patch_embedder_fixed(monkeypatch)

    _guc_capture.clear()

    from services.memory.memory_service import LongTermMemory
    from utils.models import ExtractedFact

    pool = await _make_pool()
    try:
        ltm = LongTermMemory.__new__(LongTermMemory)
        ltm._pool = pool

        async def _get_pool_single() -> asyncpg.Pool:
            return pool

        ltm._get_pool = _get_pool_single  # type: ignore[method-assign]
        await ltm._create_tables()

        # Capture the original _bulk_near_duplicate_check_raw method.
        original_raw = LongTermMemory._bulk_near_duplicate_check_raw  # type: ignore[attr-defined]

        async def _capturing_raw(
            conn: asyncpg.Connection,
            *,
            user_id: str,
            tenant_id: str,
            embeddings: list[list[float]],
            threshold: float,
        ) -> set[int]:
            """Wrap the real _raw helper; capture GUC state before running."""
            iterative_scan = await conn.fetchval("SHOW hnsw.iterative_scan")
            ef_search = await conn.fetchval("SHOW hnsw.ef_search")
            _guc_capture.append({
                "iterative_scan": str(iterative_scan),
                "ef_search": str(ef_search),
            })
            result: set[int] = await original_raw(
                ltm, conn,
                user_id=user_id,
                tenant_id=tenant_id,
                embeddings=embeddings,
                threshold=threshold,
            )
            return result

        monkeypatch.setattr(
            ltm,
            "_bulk_near_duplicate_check_raw",
            _capturing_raw,
        )

        fact = ExtractedFact(
            fact="toctou-test-fact-XYZ",
            category="recurring_topics",
            importance=0.5,
        )
        await ltm.save_facts(
            [fact],
            user_id="toctou-u1",
            tenant_id="toctou-t1",
        )
    finally:
        await pool.close()

    # Assert GUC capture happened.
    assert len(_guc_capture) >= 1, (
        "A1-A FAILED: _bulk_near_duplicate_check_raw was never called — "
        "save_facts body does not call the _raw helper."
    )
    capture = _guc_capture[0]

    # hnsw.iterative_scan must be strict_order (SET LOCAL in save_facts still in effect).
    assert capture["iterative_scan"] == "strict_order", (
        f"A1-A FAILED: hnsw.iterative_scan = {capture['iterative_scan']!r} "
        f"(expected 'strict_order'). SET LOCAL was reverted — SAVEPOINT leak?"
    )

    # ef_search must be numeric and not the PG default (40).
    try:
        ef_val = int(capture["ef_search"])
    except ValueError:
        pytest.fail(
            f"A1-A FAILED: hnsw.ef_search = {capture['ef_search']!r} — not numeric."
        )
        return  # unreachable; for type checker

    # The settings default is 200 (pgvector_ef_search_filtered default).
    # We accept any value != PG's built-in default of 40 as evidence the SET LOCAL fired.
    assert ef_val != 40, (  # noqa: PLR2004
        "A1-A FAILED: hnsw.ef_search == 40 (PG default) — SET LOCAL hnsw.ef_search "
        "was not applied or was reverted before the bulk SELECT ran."
    )
