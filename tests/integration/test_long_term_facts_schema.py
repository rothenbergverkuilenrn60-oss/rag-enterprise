"""Phase 23 / MEM-01 — integration test for ``LongTermMemory`` DDL on real pgvector.

ROADMAP SC-1: column exists with correct dim; HNSW index exists; cosine query
uses the HNSW index (proven via EXPLAIN).

When PG is unavailable, the ``pgvector_pool`` fixture (declared in
``tests/conftest.py``) raises ``pytest.skip`` so the file is collected but the
tests SKIP — keeping CI green on hosts without PostgreSQL.

Markers: ``integration`` + ``pgvector`` so the default ``-m "not integration"``
in pytest.ini deselects them.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import json

import asyncpg
import pytest

from config.settings import settings
from services.memory.memory_service import LongTermMemory

pytestmark = [pytest.mark.integration, pytest.mark.pgvector]


# -----------------------------------------------------------------------------
# Test 1 — DDL idempotency on real PG
# -----------------------------------------------------------------------------


async def test_create_tables_idempotent_real_pg(
    pgvector_pool: asyncpg.Pool, clean_long_term_facts: None
) -> None:
    """``_create_tables`` runs twice without raising; embedding column persists.

    Closes ROADMAP SC-1 idempotency contract at the real-PG layer (unit-level
    coverage in ``tests/unit/test_memory_schema.py`` exists but mocks asyncpg).
    """
    mem = LongTermMemory()
    # Inject the shared session pool so _create_tables uses it instead of
    # spinning up a per-test pool (which would re-run pgvector codec init).
    mem._pool = pgvector_pool

    # First call: should succeed.
    await mem._create_tables()
    # Second call: must be idempotent (no IF NOT EXISTS race; no duplicate
    # CREATE INDEX error; no ALTER TABLE re-add error).
    await mem._create_tables()

    # Verify embedding column exists.
    async with pgvector_pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT column_name, data_type, udt_name
               FROM information_schema.columns
               WHERE table_name='long_term_facts' AND column_name='embedding'"""
        )
        assert len(rows) == 1, (
            f"embedding column missing or duplicated; got {len(rows)} rows"
        )
        # pgvector encodes vector type as USER-DEFINED in information_schema;
        # the underlying udt_name is 'vector'.
        assert rows[0]["data_type"] == "USER-DEFINED"
        assert rows[0]["udt_name"] == "vector"

        # Verify HNSW index exists.
        idx_count = await conn.fetchval(
            """SELECT count(*) FROM pg_indexes
               WHERE tablename='long_term_facts' AND indexname='ltf_emb_hnsw_idx'"""
        )
        assert idx_count == 1, f"ltf_emb_hnsw_idx missing; got {idx_count}"


# -----------------------------------------------------------------------------
# Test 2 — HNSW EXPLAIN confirms cosine query uses the HNSW index
# -----------------------------------------------------------------------------


def _walk_plan(node: dict) -> list[dict]:
    """Yield every plan node in the EXPLAIN JSON tree (depth-first)."""
    out: list[dict] = [node]
    for child in node.get("Plans", []) or []:
        out.extend(_walk_plan(child))
    return out


async def test_hnsw_index_used_on_cosine_query(
    pgvector_pool: asyncpg.Pool,
    embedder_or_mock,  # noqa: ARG001 — fixture present for side-effect parity
    clean_long_term_facts: None,
) -> None:
    """EXPLAIN (FORMAT JSON) on a ``<=>`` cosine query references ``ltf_emb_hnsw_idx``.

    Closes ROADMAP SC-1's HNSW-is-actually-queryable half. With only 10 rows
    the PG planner may prefer a seq scan; ``SET LOCAL enable_seqscan = off``
    forces the index path deterministically (T-23-06-D1 mitigation per plan
    threat register).
    """
    # Ensure tables exist.
    mem = LongTermMemory()
    mem._pool = pgvector_pool
    await mem._create_tables()

    dim = settings.embedding_dim

    async with pgvector_pool.acquire() as conn:
        # Seed 10 rows with random vectors. Use $5::vector cast so pgvector
        # codec parses the Python list correctly.
        import random

        rng = random.Random(42)
        for i in range(10):
            vec = [rng.gauss(0.0, 1.0) for _ in range(dim)]
            await conn.execute(
                """INSERT INTO long_term_facts
                   (user_id, tenant_id, fact, importance, embedding)
                   VALUES ($1, $2, $3, $4, $5::vector)""",
                "u_explain",
                "t_explain",
                f"seed fact {i}",
                0.5,
                vec,
            )

        # Force HNSW index path (T-23-06-D1: 10 rows below planner's
        # seq-scan threshold).
        async with conn.transaction():
            await conn.execute("SET LOCAL enable_seqscan = off;")
            query_vec = [rng.gauss(0.0, 1.0) for _ in range(dim)]
            raw = await conn.fetchval(
                """EXPLAIN (FORMAT JSON)
                   SELECT id FROM long_term_facts
                   ORDER BY embedding <=> $1::vector
                   LIMIT 5""",
                query_vec,
            )

    # asyncpg returns the EXPLAIN payload as a JSON-encoded text;
    # parse defensively (some versions return list-of-dict directly).
    plan_json = json.loads(raw) if isinstance(raw, str) else raw
    root_plan = plan_json[0]["Plan"]
    nodes = _walk_plan(root_plan)

    matching = [
        n
        for n in nodes
        if n.get("Index Name") == "ltf_emb_hnsw_idx"
        and "Index Scan" in n.get("Node Type", "")
    ]
    assert matching, (
        "EXPLAIN did not reference ltf_emb_hnsw_idx in any Index Scan node; "
        f"nodes={[n.get('Node Type') for n in nodes]}"
    )


# -----------------------------------------------------------------------------
# Test 3 — embedding column dim matches settings.embedding_dim
# -----------------------------------------------------------------------------


async def test_embedding_column_dim_matches_settings(
    pgvector_pool: asyncpg.Pool, clean_long_term_facts: None
) -> None:
    """Inserting a vector of correct dim succeeds; wrong dim raises PG error.

    Closes the settings.embedding_dim ↔ VECTOR(N) coupling contract.
    """
    mem = LongTermMemory()
    mem._pool = pgvector_pool
    await mem._create_tables()

    dim = settings.embedding_dim

    async with pgvector_pool.acquire() as conn:
        # Correct dim → succeeds.
        await conn.execute(
            """INSERT INTO long_term_facts
               (user_id, tenant_id, fact, importance, embedding)
               VALUES ($1, $2, $3, $4, $5::vector)""",
            "u_dim",
            "t_dim",
            "correct-dim fact",
            0.5,
            [0.1] * dim,
        )
        count = await conn.fetchval(
            "SELECT count(*) FROM long_term_facts WHERE user_id='u_dim'"
        )
        assert count == 1

        # Wrong dim → pgvector raises DataError (or similar PostgresError).
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                """INSERT INTO long_term_facts
                   (user_id, tenant_id, fact, importance, embedding)
                   VALUES ($1, $2, $3, $4, $5::vector)""",
                "u_dim_bad",
                "t_dim",
                "wrong-dim fact",
                0.5,
                [0.1] * (dim + 1),
            )
