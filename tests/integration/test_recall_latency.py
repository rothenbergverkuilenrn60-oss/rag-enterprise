"""
tests/integration/test_recall_latency.py

T9 / Decision-6 SC-3 SQL-only HNSW latency benchmark @ 10k rows.

Seeds 10,000 long_term_facts rows for a dedicated (user_id, tenant_id) pair
using bulk INSERT with pre-computed random unit vectors (numpy seed=42) —
avoids 10,000 embed_one calls.

Query is embedded ONCE outside the timed loop (embedder excluded from SC-3 SLA).
50 timed trials of the txn-wrapped SELECT (replicating get_relevant_facts SQL body).
Asserts p95 < 50ms per ROADMAP SC-3.

Skip-gated on PG_AVAILABLE. No real_llm marker — SQL-only scope (Decision-6).
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import numpy as np
import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.skipif(
        not PG_AVAILABLE,
        reason="PostgreSQL + pgvector not available — skipping SC-3 latency benchmark",
    ),
]

_USER_ID = "test-sc3-u"
_TENANT_ID = "test-sc3-t"
_SEED_ROWS = 10_000
_TRIALS = 50
_LIMIT = 5


# ──────────────────────────────────────────────────────────────────────────────
# Test: SC-3 HNSW latency p95 < 50ms @ 10k rows (SQL-only, embed excluded)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recall_sql_p95_under_50ms_at_10k_rows():
    """SC-3: SQL-only HNSW filtered recall p95 < 50ms @ 10k rows.

    T9 / Decision-6 scope: embed query ONCE outside the timed loop.
    Only pool-acquire + SET LOCAL GUCs + pgvector ORDER BY SELECT are timed.
    """
    from config.settings import settings
    from services.memory.memory_service import LongTermMemory
    from services.vectorizer.embedder import get_embedder

    mem = LongTermMemory()
    pool = await mem._get_pool()

    # ── Step 1: ensure table exists ───────────────────────────────────────────
    await mem._create_tables()

    # ── Step 2: bulk-seed 10k rows with pre-computed random unit vectors ──────
    # numpy seed=42 for reproducibility. Normalise each vector to unit length
    # so cosine distance semantics hold (distance ∈ [0, 2]).
    rng = np.random.default_rng(seed=42)
    dim = 1024
    raw = rng.standard_normal((_SEED_ROWS, dim)).astype("float32")
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    unit_vecs = (raw / norms).tolist()  # list of list[float]

    rows = [
        (_USER_ID, _TENANT_ID, f"benchmark fact {i}", "bench", 0.5, unit_vecs[i])
        for i in range(_SEED_ROWS)
    ]

    async with pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO long_term_facts
               (user_id, tenant_id, fact, source_doc, importance, embedding)
               VALUES ($1, $2, $3, $4, $5, $6::vector)""",
            rows,
        )

    # ── Step 3: embed query ONCE outside the timed loop (Decision-6 scope) ────
    embedder = get_embedder()
    q_vec = await embedder.embed_one("what frontend do I prefer?")

    ef = int(getattr(settings, "pgvector_ef_search_filtered", 200))

    # ── Step 4: 50 timed trials — SQL-only (pool-acquire + txn + SELECT) ─────
    timings_ms: list[float] = []
    for _ in range(_TRIALS):
        t0 = time.perf_counter()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
                await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")
                await conn.fetch(
                    """SELECT fact FROM long_term_facts
                       WHERE user_id=$1 AND tenant_id=$2
                       ORDER BY embedding <=> $3::vector,
                                importance DESC,
                                created_at DESC
                       LIMIT $4""",
                    _USER_ID, _TENANT_ID, q_vec, _LIMIT,
                )
        timings_ms.append((time.perf_counter() - t0) * 1000)

    # ── Step 5: compute p95 and assert SC-3 SLA ───────────────────────────────
    sorted_ms = sorted(timings_ms)
    p95_idx = int(0.95 * len(sorted_ms)) - 1
    p95 = sorted_ms[max(p95_idx, 0)]

    # Optional p99 for ops visibility
    p99_idx = int(0.99 * len(sorted_ms)) - 1
    p99 = sorted_ms[max(p99_idx, 0)]

    print(
        f"\nSC-3 latency @ {_SEED_ROWS} rows / {_TRIALS} trials: "
        f"p50={sorted_ms[len(sorted_ms) // 2]:.1f}ms  "
        f"p95={p95:.1f}ms  p99={p99:.1f}ms"
    )

    assert p95 < 50, (
        f"SQL p95 {p95:.1f}ms exceeds ROADMAP SC-3 50ms target "
        f"(p99={p99:.1f}ms, min={sorted_ms[0]:.1f}ms, max={sorted_ms[-1]:.1f}ms)"
    )

    # ── Step 6: cleanup (scoped DELETE — never DROP TABLE) ────────────────────
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
            _USER_ID, _TENANT_ID,
        )
