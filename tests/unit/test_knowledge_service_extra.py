"""tests/unit/test_knowledge_service_extra.py — Phase 15 backfill.

Existing tests/unit/test_knowledge_service.py covers DocumentQualityChecker
basics; this file adds TransactionalIndexer.upsert_atomic happy + rollback,
KnowledgeUpdateService.incremental_update branches, and singleton accessor.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest


def _make_chunk(chunk_id: str, level: str = "child"):
    chunk = MagicMock()
    chunk.chunk_id = chunk_id
    chunk.content = f"text-{chunk_id}"
    chunk.content_with_header = f"hdr text-{chunk_id}"
    chunk.metadata = MagicMock()
    chunk.metadata.chunk_level = level
    chunk.embedding = None
    return chunk


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.knowledge.knowledge_service as mod
    yield
    monkeypatch.setattr(mod, "_knowledge_service", None, raising=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transactional_indexer_happy_path():
    from services.knowledge.knowledge_service import TransactionalIndexer
    txi = TransactionalIndexer()
    embedder = MagicMock()
    embedder.embed_batch = AsyncMock(return_value=[[0.1, 0.2]])
    bm25 = MagicMock()
    vstore = MagicMock()
    vstore.upsert = AsyncMock()
    vstore.upsert_parent_chunks = AsyncMock()
    chunks = [_make_chunk("c1"), _make_chunk("p1", "parent")]
    ok, err = await txi.upsert_atomic(chunks, "doc1", vstore, bm25, embedder)
    assert ok is True
    assert err == ""
    bm25.add.assert_called_once()
    vstore.upsert.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transactional_indexer_embedding_failure_returns_false():
    from services.knowledge.knowledge_service import TransactionalIndexer
    txi = TransactionalIndexer()
    embedder = MagicMock()
    embedder.embed_batch = AsyncMock(side_effect=RuntimeError("embed fail"))
    bm25 = MagicMock()
    vstore = MagicMock()
    chunks = [_make_chunk("c1")]
    ok, err = await txi.upsert_atomic(chunks, "doc1", vstore, bm25, embedder)
    assert ok is False
    assert "Embedding" in err


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transactional_indexer_bm25_failure_returns_false():
    from services.knowledge.knowledge_service import TransactionalIndexer
    txi = TransactionalIndexer()
    embedder = MagicMock()
    embedder.embed_batch = AsyncMock(return_value=[[0.0]])
    bm25 = MagicMock()
    bm25.add = MagicMock(side_effect=RuntimeError("bm25 corrupt"))
    vstore = MagicMock()
    chunks = [_make_chunk("c1")]
    ok, err = await txi.upsert_atomic(chunks, "doc1", vstore, bm25, embedder)
    assert ok is False
    assert "BM25" in err


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transactional_indexer_qdrant_failure_rolls_back_bm25():
    """Error path: Qdrant fails → BM25 rollback invoked."""
    from services.knowledge.knowledge_service import TransactionalIndexer
    txi = TransactionalIndexer()
    embedder = MagicMock()
    embedder.embed_batch = AsyncMock(return_value=[[0.0]])
    bm25 = MagicMock()
    bm25._corpus = ["text-c1"]
    bm25._ids = ["c1"]
    bm25._model = MagicMock()
    bm25.add = MagicMock()
    bm25.build = MagicMock()
    vstore = MagicMock()
    vstore.upsert = AsyncMock(side_effect=asyncpg.PostgresError("network down"))
    chunks = [_make_chunk("c1")]
    ok, err = await txi.upsert_atomic(chunks, "doc1", vstore, bm25, embedder)
    assert ok is False
    assert "rolled back" in err.lower()


@pytest.mark.unit
def test_rollback_bm25_clears_when_no_remaining():
    """Rollback path: removing all entries empties the index."""
    from services.knowledge.knowledge_service import TransactionalIndexer
    txi = TransactionalIndexer()
    bm25 = MagicMock()
    bm25._corpus = ["a"]
    bm25._ids = ["c1"]
    bm25._model = MagicMock()
    bm25.build = MagicMock()
    txi._rollback_bm25(bm25, ["c1"])
    assert bm25._corpus == []
    assert bm25._ids == []
    assert bm25._model is None


@pytest.mark.unit
def test_rollback_bm25_swallows_attribute_error():
    """Error path: missing attribute on bm25 → caught, no propagation."""
    from services.knowledge.knowledge_service import TransactionalIndexer
    txi = TransactionalIndexer()
    bm25 = object()
    txi._rollback_bm25(bm25, ["c1"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incremental_update_skips_unchanged_checksum(tmp_path):
    from services.knowledge.knowledge_service import (
        KnowledgeUpdateService,
        UpdateRecord,
        UpdateStatus,
    )
    p = tmp_path / "doc.txt"
    p.write_text("hello world", encoding="utf-8")

    svc = KnowledgeUpdateService()
    expected_checksum = svc._file_checksum(p)
    import hashlib
    doc_id = hashlib.md5(str(p).encode(), usedforsecurity=False).hexdigest()
    svc._records[doc_id] = UpdateRecord(
        record_id="prev", doc_id=doc_id, file_path=str(p),
        status=UpdateStatus.SUCCESS, checksum=expected_checksum,
    )
    record = await svc.incremental_update(p, MagicMock())
    assert record.status == UpdateStatus.SKIPPED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incremental_update_runs_pipeline_on_new_file(tmp_path):
    from services.knowledge.knowledge_service import KnowledgeUpdateService, UpdateStatus
    p = tmp_path / "doc.txt"
    p.write_text("hello", encoding="utf-8")
    svc = KnowledgeUpdateService()
    pipeline = MagicMock()
    fake_result = MagicMock(success=True, total_chunks=4, error="")
    pipeline.run = AsyncMock(return_value=fake_result)
    record = await svc.incremental_update(p, pipeline)
    assert record.status == UpdateStatus.SUCCESS
    assert record.chunk_count == 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incremental_update_handles_pipeline_failure(tmp_path):
    """Error path: pipeline.run reports failure → status FAILED."""
    from services.knowledge.knowledge_service import KnowledgeUpdateService, UpdateStatus
    p = tmp_path / "doc.txt"
    p.write_text("hello", encoding="utf-8")
    svc = KnowledgeUpdateService()
    pipeline = MagicMock()
    pipeline.run = AsyncMock(return_value=MagicMock(success=False, total_chunks=0, error="bad pdf"))
    record = await svc.incremental_update(p, pipeline)
    assert record.status == UpdateStatus.FAILED
    assert "bad pdf" in record.error


@pytest.mark.unit
@pytest.mark.asyncio
async def test_incremental_update_catches_runtime_error(tmp_path):
    """Error path: pipeline raises → status FAILED with sanitized error."""
    from services.knowledge.knowledge_service import KnowledgeUpdateService, UpdateStatus
    p = tmp_path / "doc.txt"
    p.write_text("hello", encoding="utf-8")
    svc = KnowledgeUpdateService()
    pipeline = MagicMock()
    pipeline.run = AsyncMock(side_effect=RuntimeError("boom"))
    record = await svc.incremental_update(p, pipeline)
    assert record.status == UpdateStatus.FAILED


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scan_and_update_dispatches_per_file(tmp_path):
    from services.knowledge.knowledge_service import KnowledgeUpdateService, UpdateStatus
    (tmp_path / "a.txt").write_text("hello a", encoding="utf-8")
    (tmp_path / "b.md").write_text("hello b", encoding="utf-8")
    svc = KnowledgeUpdateService()

    async def fake_inc(path, _pipeline, _tenant=""):
        rec = MagicMock()
        rec.status = UpdateStatus.SUCCESS
        return rec

    svc.incremental_update = fake_inc
    out = await svc.scan_and_update(Path(tmp_path), MagicMock())
    assert len(out) == 2


@pytest.mark.unit
def test_validate_document_passes_clean_text():
    from services.knowledge.knowledge_service import KnowledgeUpdateService
    svc = KnowledgeUpdateService()
    body = "这是一段测试中文内容。" * 30
    rep = svc.validate_document(body, "d1", "/p")
    assert rep.passed is True
    assert rep.quality_score > 0


@pytest.mark.unit
def test_validate_document_flags_too_short():
    """Error path: too-short body → errors and not-passed."""
    from services.knowledge.knowledge_service import KnowledgeUpdateService
    svc = KnowledgeUpdateService()
    rep = svc.validate_document("short", "d1", "/p")
    assert rep.passed is False
    assert any("过短" in e for e in rep.errors)


@pytest.mark.unit
def test_validate_document_flags_garbled_content():
    from services.knowledge.knowledge_service import KnowledgeUpdateService
    svc = KnowledgeUpdateService()
    body = "🎉🚀✨" * 200
    rep = svc.validate_document(body, "d1", "/p")
    assert rep.passed is False


@pytest.mark.unit
def test_get_knowledge_service_singleton():
    from services.knowledge.knowledge_service import get_knowledge_service
    a = get_knowledge_service()
    b = get_knowledge_service()
    assert a is b
