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
    pytest.mark.skipif(
        not PG_AVAILABLE,
        reason="PostgreSQL + pgvector not available — skipping filtered recall test",
    ),
]


@pytest.mark.asyncio
async def test_filtered_recall_page(pg_store):
    """SC#2: filter {'page_number': 63} returns matching chunk in top-3."""
    from utils.models import DocumentChunk, ChunkMetadata
    store = pg_store
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
    from utils.models import DocumentChunk, ChunkMetadata
    store = pg_store
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
    from utils.models import DocumentChunk, ChunkMetadata
    store = pg_store
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
