"""
tests/integration/test_recall_offline_eval.py

SC-1 offline eval gate — ROADMAP Phase 24 cosine quality contract.

Test 1 (positive): query "what frontend framework do I prefer?" against a seed
containing "user prefers React for frontend" returns React as top-1 result with
cosine similarity > 0.7 (measured offline, NOT enforced as a runtime threshold).

Test 2 (negative): query "what database do I use?" against the same seed
(which deliberately omits any database fact) returns no fact above cosine 0.5,
validating that semantic relevance — not popularity — drives ranking.

Skip-gated on PG_AVAILABLE. Both tests require real PG + real embedder.
CI hosts without PostgreSQL skip gracefully (Phase 23 precedent).
"""
from __future__ import annotations

import math
import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.skipif(
        not PG_AVAILABLE,
        reason="PostgreSQL + pgvector not available — skipping SC-1 offline eval",
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Cosine helper
# ──────────────────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    """Standard cosine similarity in [-1, 1]. Returns 0.0 for zero vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if (na and nb) else 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Seed fixture
# Seeds 5 facts WITHOUT any PostgreSQL / database fact — required for SC-1
# negative-case Option A: the seed must not contain a high-relevance database
# fact so the negative assertion (max_cos <= 0.5) is meaningful.
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
async def _react_seed():
    """Seed long_term_facts for SC-1; cleanup on teardown."""
    from services.memory.memory_service import LongTermMemory

    mem = LongTermMemory()
    await mem.save_fact(
        "test-sc1-u", "test-sc1-t",
        "user prefers React for frontend",
        source_doc="seed", importance=0.8,
    )
    await mem.save_fact(
        "test-sc1-u", "test-sc1-t",
        "user works in healthcare",
        source_doc="seed", importance=0.5,
    )
    await mem.save_fact(
        "test-sc1-u", "test-sc1-t",
        "user lives in Berlin",
        source_doc="seed", importance=0.2,
    )
    await mem.save_fact(
        "test-sc1-u", "test-sc1-t",
        "user enjoys hiking on weekends",
        source_doc="seed", importance=0.2,
    )
    await mem.save_fact(
        "test-sc1-u", "test-sc1-t",
        "user has a black cat named Pixel",
        source_doc="seed", importance=0.2,
    )
    yield mem
    # Scoped DELETE — never DROP TABLE (acceptance criteria requirement)
    pool = await mem._get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM long_term_facts WHERE user_id='test-sc1-u' AND tenant_id='test-sc1-t'"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — SC-1 positive case
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_react_preference_recalled_with_high_cosine(_react_seed):
    """SC-1 positive: React fact is top-1 result with cosine > 0.7.

    ROADMAP wording: "Query 'what frontend framework do I prefer?' recalls fact
    'user prefers React' with cosine similarity > 0.7"
    """
    from services.vectorizer.embedder import get_embedder

    mem = _react_seed
    query = "what frontend framework do I prefer?"
    facts = await mem.get_relevant_facts("test-sc1-u", "test-sc1-t", query, limit=5)

    assert len(facts) >= 1, "expected at least one fact returned"
    assert "React" in facts[0], f"top result was {facts[0]!r} — expected React"

    embedder = get_embedder()
    q_emb = await embedder.embed_one(query)
    f_emb = await embedder.embed_one(facts[0])
    cos = _cosine(q_emb, f_emb)
    assert cos > 0.7, f"cosine {cos:.4f} below 0.7 — semantic quality regression"


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 — SC-1 negative case
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_database_query_returns_no_relevant_fact(_react_seed):
    """SC-1 negative: query about databases returns no fact above cosine 0.5.

    ROADMAP wording: "Query 'what database do I use?' returns no fact above
    similarity 0.5 — query-relevance, not popularity, drives ranking"

    The seed deliberately omits any database-related fact so no returned result
    should have high cosine similarity with the database query.
    """
    from services.vectorizer.embedder import get_embedder

    mem = _react_seed
    query = "what database do I use?"
    facts = await mem.get_relevant_facts("test-sc1-u", "test-sc1-t", query, limit=5)

    embedder = get_embedder()
    q_emb = await embedder.embed_one(query)

    max_cos = 0.0
    for f in facts:
        f_emb = await embedder.embed_one(f)
        cos = _cosine(q_emb, f_emb)
        max_cos = max(max_cos, cos)

    assert max_cos <= 0.5, (
        f"unexpected high relevance ({max_cos:.4f}) for unrelated database query — "
        "check seed facts for accidental database-domain content"
    )
