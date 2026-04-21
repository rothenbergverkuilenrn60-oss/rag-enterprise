"""
Recall@10 quality gate for pgvector HNSW index (SC-2).

Replaces the original Qdrant-comparison baseline with an absolute quality gate:
recall@10 >= 0.95 against brute-force ground truth. This is appropriate because
D-05 removes QdrantVectorStore entirely, eliminating the Qdrant baseline.

Methodology:
1. Insert N random unit vectors as chunks
2. Compute brute-force top-10 neighbors for each query vector (ground truth)
3. Run HNSW search via PgVectorStore.search()
4. Compute recall@10 = (true neighbors found) / (total true neighbors)
5. Assert recall@10 >= 0.95
"""
from __future__ import annotations

import math
import random
import pytest
import asyncpg

from tests.conftest import PG_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="PostgreSQL + pgvector not available — skipping recall@10 test"
)

N_DOCS = 100          # vectors to insert
K = 10                # top-k for recall measurement
RECALL_THRESHOLD = 0.95
DIM = 64              # smaller dim for fast test (overrides settings.embedding_dim)
SEED = 42


def _random_unit_vector(dim: int, rng: random.Random) -> list[float]:
    v = [rng.gauss(0, 1) for _ in range(dim)]
    mag = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / mag for x in v]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    return dot / (mag_a * mag_b + 1e-12)


def _brute_force_top_k(
    query: list[float], corpus: list[list[float]], k: int
) -> list[int]:
    sims = [(_cosine_similarity(query, v), i) for i, v in enumerate(corpus)]
    sims.sort(reverse=True)
    return [i for _, i in sims[:k]]


async def test_recall_at_10(pg_pool: asyncpg.Pool):
    """HNSW recall@10 against brute-force ground truth must be >= 0.95 (SC-2).

    Uses a small dim=64 corpus for speed. The HNSW index parameters (m=16,
    ef_construction=64) from Plan 02 are tested at their actual query quality.
    """
    import services.vectorizer.vector_store as vs_module
    from services.vectorizer.vector_store import PgVectorStore
    from utils.models import DocumentChunk, ChunkMetadata, DocType

    vs_module._store_instance = None
    store = PgVectorStore()
    # Override dim and table name for this isolated test
    store._dim = DIM
    store._table = "recall_test_table"

    await store.create_collection()

    rng = random.Random(SEED)
    vectors = [_random_unit_vector(DIM, rng) for _ in range(N_DOCS)]

    # Insert all vectors
    chunks = []
    for i, vec in enumerate(vectors):
        meta = ChunkMetadata(
            source="recall_test",
            doc_type=DocType.PDF,
            chunk_index=i,
            total_chunks=N_DOCS,
            title=f"Doc {i}",
        )
        chunks.append(DocumentChunk(
            chunk_id=f"recall-{i}",
            doc_id=f"doc-{i}",
            content=f"content {i}",
            content_with_header=f"[Doc {i}] content {i}",
            metadata=meta,
            embedding=vec,
        ))

    await store.upsert(chunks, tenant_id="recall-tenant")

    # Select 20 random query vectors from the corpus
    query_indices = rng.sample(range(N_DOCS), 20)
    total_hits = 0
    total_expected = len(query_indices) * K

    for qi in query_indices:
        query_vec = vectors[qi]
        true_top_k = set(_brute_force_top_k(query_vec, vectors, K))

        results = await store.search(
            query_vector=query_vec,
            top_k=K,
            tenant_id="recall-tenant",
            filters={"tenant_id": "recall-tenant"},
        )
        result_ids = {r.chunk_id.replace("recall-", "") for r in results}
        found_indices = {int(rid) for rid in result_ids if rid.isdigit()}
        total_hits += len(true_top_k & found_indices)

    recall = total_hits / total_expected
    assert recall >= RECALL_THRESHOLD, (
        f"HNSW recall@10={recall:.3f} is below threshold {RECALL_THRESHOLD}. "
        f"Check HNSW parameters (m=16, ef_construction=64) in create_collection()."
    )

    # Cleanup
    async with pg_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS recall_test_table CASCADE;")
        await conn.execute("DROP TABLE IF EXISTS recall_test_table_parent CASCADE;")

    vs_module._store_instance = None
