"""
tests/integration/test_pgvector_filtered_recall.py

RED-state Wave 0 scaffold for META-02 (REQ A-4 / Phase 8 SC #2, #5).
Tests fail today; 08-04-PLAN.md (PgVectorStore filter WHERE + GUC) makes them green.

Skip-gated on PG_AVAILABLE — matches the existing pattern in test_pgvector_recall.py.
Run inside the dev environment with PostgreSQL + pgvector >= 0.8.0 reachable on
postgresql://rag:rag@localhost:5432/ragdb.
"""
from __future__ import annotations

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
        reason="PostgreSQL + pgvector not available — skipping filtered recall test",
    ),
]

# Override the production embedding_dim (1024) for fast isolated test tables.
# The fixtures below use [0.1 * (i + 1)] * DIM_TEST embeddings so the column
# vector type must match (otherwise upsert raises DataError before search runs).
# Pattern mirrors tests/integration/test_pgvector_recall.py:70 (`store._dim = DIM`).
DIM_TEST = 384


@pytest.mark.asyncio
async def test_filtered_recall_page(pg_store):
    """SC#2: filter {'page_number': 63} returns matching chunk in top-3."""
    from utils.models import ChunkMetadata, DocumentChunk
    store = pg_store
    store._dim = DIM_TEST
    store._table = "phase8_filtered_recall_test"
    await store.create_collection()
    try:
        # Seed: 5 chunks across two pages; only one is on page 63 with target content.
        chunks = [
            DocumentChunk(
                chunk_id=f"c{i}",
                doc_id="d1",
                content=content,
                content_with_header=content,
                metadata=ChunkMetadata(
                    doc_id="d1",
                    page_number=page,
                    section_id=sid,
                    section_title=stitle,
                    chunk_index=i,
                ),
                token_count=len(content),
                embedding=[0.1 * (i + 1)] * 384,
            )
            for i, (page, sid, stitle, content) in enumerate([
                (61, "3.8",  "其他术语",  "本节描述了无关定义"),
                (62, "3.9",  "通用要求",  "通用尺寸约束"),
                (63, "3.10", "定义的透光面", "灯具的发光面定义"),
                (64, "3.11", "性能",      "光强分布要求"),
                (65, "3.12", "测试",      "试验方法"),
            ])
        ]
        await store.upsert(chunks)
        # Query vector close to chunk index 2 (page 63)
        qv = [0.3] * 384
        results = await store.search(qv, top_k=3, filters={"page_number": 63})
        assert any(r.chunk_id == "c2" for r in results), \
            f"target c2 not in top-3 results: {[r.chunk_id for r in results]}"
        # All returned rows must have page_number == 63
        for r in results:
            assert r.metadata.get("page_number") == 63, \
                f"filter leaked: {r.metadata}"
    finally:
        pool = await store._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {store._table} CASCADE")
            await conn.execute(f"DROP TABLE IF EXISTS {store._table}_parent CASCADE")


@pytest.mark.asyncio
async def test_unfiltered_recall_unchanged(pg_store):
    """SC#2: unfiltered query continues to work; recall not lower than filtered case."""
    from utils.models import ChunkMetadata, DocumentChunk
    store = pg_store
    store._dim = DIM_TEST
    store._table = "phase8_unfiltered_recall_test"
    await store.create_collection()
    try:
        chunks = [
            DocumentChunk(
                chunk_id=f"u{i}",
                doc_id="d1",
                content=f"content {i}",
                content_with_header=f"content {i}",
                metadata=ChunkMetadata(doc_id="d1", page_number=63, chunk_index=i),
                token_count=4,
                embedding=[0.1 * (i + 1)] * 384,
            )
            for i in range(3)
        ]
        await store.upsert(chunks)
        results = await store.search([0.2] * 384, top_k=3, filters=None)
        assert len(results) == 3
    finally:
        pool = await store._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {store._table} CASCADE")
            await conn.execute(f"DROP TABLE IF EXISTS {store._table}_parent CASCADE")


@pytest.mark.asyncio
async def test_legacy_chunks_searchable(pg_store):
    """SC#5 / T-08-03: chunks without section_id/section_title load and search without error."""
    from utils.models import ChunkMetadata, DocumentChunk
    store = pg_store
    store._dim = DIM_TEST
    store._table = "phase8_legacy_search_test"
    await store.create_collection()
    try:
        # Legacy chunk: section_id and section_title left at default ""
        chunks = [
            DocumentChunk(
                chunk_id="legacy1",
                doc_id="dlegacy",
                content="legacy content",
                content_with_header="legacy content",
                metadata=ChunkMetadata(doc_id="dlegacy", page_number=10),
                token_count=2,
                embedding=[0.1] * 384,
            ),
        ]
        await store.upsert(chunks)
        # Unfiltered search must still return it
        unfiltered = await store.search([0.1] * 384, top_k=1, filters=None)
        assert any(r.chunk_id == "legacy1" for r in unfiltered)
        # Section-filtered search must NOT match (NULL semantics — legacy excluded silently)
        filtered = await store.search([0.1] * 384, top_k=1, filters={"section_id": "3.10"})
        assert all(r.chunk_id != "legacy1" for r in filtered)
    finally:
        pool = await store._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {store._table} CASCADE")
            await conn.execute(f"DROP TABLE IF EXISTS {store._table}_parent CASCADE")


@pytest.mark.asyncio
async def test_pipeline_e2e_filter_propagation(pg_store):
    """SC#3: end-to-end demonstration that the filter-extraction → tf-merge →
    vector_store.search chain returns the right chunk for a real Chinese query.

    This test does not boot the full QueryPipeline (which has many heavy
    dependencies — embedder, NLU, generator, etc.); instead, it calls
    extract_filters directly and then store.search directly, replicating the
    extract → merge → search portion of QueryPipeline._run_query. The pipeline
    edit in 08-05 task 1 is verified by static greps + pipeline unit tests;
    this test verifies the contract held by both ends.
    """
    from services.nlu.filter_extractor import extract_filters
    from utils.models import ChunkMetadata, DocumentChunk

    store = pg_store
    store._dim = DIM_TEST
    store._table = "phase8_e2e_filter_propagation"
    await store.create_collection()
    try:
        # Seed: GB4785-2019-style chunks across pages 61-65, target on page 63.
        chunks = [
            DocumentChunk(
                chunk_id=f"e{i}",
                doc_id="d1",
                content=content,
                content_with_header=content,
                metadata=ChunkMetadata(
                    doc_id="d1",
                    page_number=page,
                    section_id=sid,
                    section_title=stitle,
                    chunk_index=i,
                ),
                token_count=len(content),
                embedding=[0.1 * (i + 1)] * DIM_TEST,
            )
            for i, (page, sid, stitle, content) in enumerate([
                (61, "3.8",  "其他术语",      "前言部分定义"),
                (62, "3.9",  "通用要求",      "通用尺寸约束"),
                (63, "3.10", "定义的透光面",  "灯具的发光面定义为投影"),
                (64, "3.11", "性能",          "光强分布要求"),
                (65, "3.12", "测试",          "试验方法描述"),
            ])
        ]
        await store.upsert(chunks)

        # 1. Mirror the pipeline edit: extract filters from the user query.
        user_query = "第63页灯具的发光面"
        extraction = extract_filters(user_query)
        assert extraction.filters == {"page_number": 63}, extraction.filters
        assert extraction.semantic_query.strip() == "灯具的发光面", \
            f"semantic_query should be stripped: {extraction.semantic_query!r}"
        # The literal "第63页" MUST NOT remain in the text that goes to the embedder.
        assert "第63页" not in extraction.semantic_query
        assert "页" not in extraction.semantic_query.strip()  # whole token gone

        # 2. Mirror the pipeline edit: merge into tf and call vector_store.search.
        tf: dict = {}
        tf = {**tf, **extraction.filters}
        # Use a query vector that's reasonably close to chunk e2 (index 2 → 0.3).
        qv = [0.3] * DIM_TEST
        results = await store.search(qv, top_k=3, filters=tf)

        # 3. Verify: target chunk on page 63 is in top-3, no off-page leakage.
        assert results, "expected at least one result for filtered e2e query"
        assert any(r.chunk_id == "e2" for r in results), \
            f"target e2 not in top-3: {[r.chunk_id for r in results]}"
        for r in results:
            assert r.metadata.get("page_number") == 63, \
                f"filter leaked: page_number={r.metadata.get('page_number')!r}"

        # 4. Sanity: unfiltered query returns more variety (regression contract).
        unfiltered = await store.search(qv, top_k=5, filters=None)
        unfiltered_pages = {r.metadata.get("page_number") for r in unfiltered}
        assert len(unfiltered_pages) > 1, \
            f"unfiltered should span multiple pages, got: {unfiltered_pages}"
    finally:
        pool = await store._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP TABLE IF EXISTS {store._table} CASCADE")
            await conn.execute(f"DROP TABLE IF EXISTS {store._table}_parent CASCADE")
