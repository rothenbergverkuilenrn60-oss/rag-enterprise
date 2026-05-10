"""tests/unit/test_indexer_service.py — Phase 15 backfill.

Covers services/vectorizer/indexer.py: BM25Index search/build paths and
VectorizerService.vectorize_and_store success + parent-upsert error path.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest


def _make_chunk(chunk_id: str, *, level: str = "child", content: str = "hello"):
    from utils.models import ChunkMetadata, DocumentChunk
    return DocumentChunk(
        chunk_id=chunk_id,
        doc_id="doc-1",
        content=content,
        content_with_header=f"[h] {content}",
        metadata=ChunkMetadata(chunk_level=level),
    )


@pytest.mark.unit
def test_bm25_search_returns_empty_when_model_unbuilt():
    from services.vectorizer.indexer import BM25Index
    idx = BM25Index()
    assert idx.search("anything", top_k=5) == []


@pytest.mark.unit
def test_bm25_build_and_search_roundtrip():
    from services.vectorizer.indexer import BM25Index
    idx = BM25Index()
    idx.build(
        texts=["alpha beta gamma", "beta delta", "gamma epsilon"],
        ids=["a", "b", "c"],
    )
    results = idx.search("alpha", top_k=2)
    assert len(results) >= 1
    assert results[0][0] == "a"


@pytest.mark.unit
def test_bm25_add_appends_to_corpus():
    from services.vectorizer.indexer import BM25Index
    idx = BM25Index()
    idx.build(["alpha"], ["a"])
    idx.add(["beta"], ["b"])
    assert "a" in idx._ids and "b" in idx._ids


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vectorize_and_store_empty_chunks_short_circuits(monkeypatch):
    from services.vectorizer import indexer

    svc = indexer.VectorizerService.__new__(indexer.VectorizerService)
    svc._embedder = MagicMock()
    svc._store = MagicMock()
    svc._bm25 = MagicMock()

    result = await svc.vectorize_and_store([], doc_id="doc-empty")
    assert result.doc_id == "doc-empty"
    assert result.total_chunks == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vectorize_and_store_happy_path(monkeypatch):
    from services.vectorizer import indexer

    monkeypatch.setattr(indexer.settings, "sparse_enabled", True, raising=False)
    monkeypatch.setattr(indexer.settings, "vector_store", "pgvector", raising=False)
    monkeypatch.setattr(indexer.settings, "qdrant_collection", "rag_v1", raising=False)

    svc = indexer.VectorizerService.__new__(indexer.VectorizerService)
    svc._embedder = MagicMock()
    svc._embedder.embed_batch = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    svc._store = MagicMock()
    svc._store.upsert = AsyncMock()
    svc._store.upsert_parent_chunks = AsyncMock()
    svc._bm25 = MagicMock()

    chunks = [_make_chunk("c1"), _make_chunk("c2"), _make_chunk("p1", level="parent")]
    result = await svc.vectorize_and_store(chunks, doc_id="doc-1")

    assert result.doc_id == "doc-1"
    assert result.total_chunks == 2
    assert result.embedded_chunks == 2
    svc._embedder.embed_batch.assert_awaited_once()
    svc._store.upsert.assert_awaited_once()
    svc._store.upsert_parent_chunks.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vectorize_and_store_parent_upsert_postgres_error_swallowed(monkeypatch):
    """Error path: parent-collection upsert raises PostgresError → non-fatal."""
    from services.vectorizer import indexer

    monkeypatch.setattr(indexer.settings, "sparse_enabled", False, raising=False)
    monkeypatch.setattr(indexer.settings, "vector_store", "pgvector", raising=False)
    monkeypatch.setattr(indexer.settings, "qdrant_collection", "rag_v1", raising=False)

    svc = indexer.VectorizerService.__new__(indexer.VectorizerService)
    svc._embedder = MagicMock()
    svc._embedder.embed_batch = AsyncMock(return_value=[[0.0, 0.0]])
    svc._store = MagicMock()
    svc._store.upsert = AsyncMock()
    svc._store.upsert_parent_chunks = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
    svc._bm25 = MagicMock()

    chunks = [_make_chunk("c1"), _make_chunk("p1", level="parent")]
    result = await svc.vectorize_and_store(chunks, doc_id="doc-2")
    assert result.doc_id == "doc-2"


@pytest.mark.unit
def test_get_bm25_index_returns_module_singleton():
    from services.vectorizer.indexer import _bm25_index, get_bm25_index
    assert get_bm25_index() is _bm25_index


@pytest.mark.unit
def test_get_vectorizer_returns_singleton(monkeypatch):
    from services.vectorizer import indexer

    monkeypatch.setattr(indexer, "_vectorizer", None)
    fake_embedder = MagicMock()
    fake_store = MagicMock()
    fake_bm25 = MagicMock()
    monkeypatch.setattr(indexer, "get_embedder", lambda: fake_embedder)
    monkeypatch.setattr(indexer, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(indexer, "get_bm25_index", lambda: fake_bm25)

    v1 = indexer.get_vectorizer()
    v2 = indexer.get_vectorizer()
    assert v1 is v2
    monkeypatch.setattr(indexer, "_vectorizer", None)
