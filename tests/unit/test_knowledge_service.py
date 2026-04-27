from __future__ import annotations
import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Autouse fixture: reset knowledge singleton between tests (T-06-06)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_knowledge_singleton(monkeypatch):
    import services.knowledge.knowledge_service as mod
    yield
    monkeypatch.setattr(mod, "_knowledge_service", None, raising=False)


# ---------------------------------------------------------------------------
# DocumentQualityChecker — pure logic tests (no mock needed)
# ---------------------------------------------------------------------------
def test_document_quality_checker_valid_content():
    """Well-formed document with enough content passes quality check."""
    from services.knowledge.knowledge_service import DocumentQualityChecker
    checker = DocumentQualityChecker()
    result = checker.check(
        "This is a valid document with enough content to pass quality checks. "
        "It has more than one hundred characters and no garbled text whatsoever.",
        doc_id="d1",
        file_path="/tmp/doc.txt",
    )
    assert result.passed is True
    assert result.char_count >= 100
    assert len(result.errors) == 0


def test_document_quality_checker_too_short():
    """Document below MIN_CHARS threshold fails quality check."""
    from services.knowledge.knowledge_service import DocumentQualityChecker
    checker = DocumentQualityChecker()
    result = checker.check("hi", doc_id="d2", file_path="/tmp/short.txt")
    assert result.passed is False
    assert len(result.errors) > 0


def test_document_quality_checker_empty_string():
    """Empty document fails quality check."""
    from services.knowledge.knowledge_service import DocumentQualityChecker
    checker = DocumentQualityChecker()
    result = checker.check("", doc_id="d3", file_path="/tmp/empty.txt")
    assert result.passed is False


def test_document_quality_checker_near_empty_whitespace():
    """Document that is only whitespace (< 50 non-whitespace chars) fails."""
    from services.knowledge.knowledge_service import DocumentQualityChecker
    checker = DocumentQualityChecker()
    result = checker.check("   \n\n\t   ", doc_id="d4", file_path="/tmp/ws.txt")
    assert result.passed is False


def test_document_quality_checker_returns_report_with_metadata():
    """DocumentQualityReport includes doc_id and file_path from input."""
    from services.knowledge.knowledge_service import DocumentQualityChecker
    checker = DocumentQualityChecker()
    result = checker.check(
        "A" * 200,
        doc_id="doc_abc",
        file_path="/data/file.pdf",
    )
    assert result.doc_id == "doc_abc"
    assert result.file_path == "/data/file.pdf"
    assert result.char_count == 200


# ---------------------------------------------------------------------------
# KnowledgeUpdateService — singleton test
# ---------------------------------------------------------------------------
def test_knowledge_service_singleton():
    """get_knowledge_service() returns the same instance on repeated calls."""
    from services.knowledge.knowledge_service import get_knowledge_service
    svc1 = get_knowledge_service()
    svc2 = get_knowledge_service()
    assert svc1 is svc2


# ---------------------------------------------------------------------------
# TransactionalIndexer asyncpg mock test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_transactional_indexer_embedding_failure_returns_false(monkeypatch):
    """If embedding fails, upsert_atomic returns (False, 'Embedding failed')."""
    from services.knowledge.knowledge_service import TransactionalIndexer

    indexer = TransactionalIndexer()

    # Minimal stub chunk
    mock_chunk = MagicMock()
    mock_chunk.metadata.chunk_level = "child"
    mock_chunk.content_with_header = "some text"
    mock_chunk.content = "some text"

    mock_embedder = AsyncMock()
    mock_embedder.embed_batch = AsyncMock(side_effect=RuntimeError("embed fail"))

    mock_vector_store = MagicMock()
    mock_bm25 = MagicMock()

    success, msg = await indexer.upsert_atomic(
        chunks=[mock_chunk],
        doc_id="d1",
        vector_store=mock_vector_store,
        bm25_index=mock_bm25,
        embedder=mock_embedder,
    )
    assert success is False
    assert "Embedding failed" in msg


@pytest.mark.asyncio
async def test_transactional_indexer_no_chunks_succeeds():
    """An empty chunk list completes successfully (nothing to index)."""
    from services.knowledge.knowledge_service import TransactionalIndexer

    indexer = TransactionalIndexer()

    mock_embedder = AsyncMock()
    mock_embedder.embed_batch = AsyncMock(return_value=[])
    mock_vector_store = AsyncMock()
    mock_bm25 = MagicMock()

    success, msg = await indexer.upsert_atomic(
        chunks=[],
        doc_id="d_empty",
        vector_store=mock_vector_store,
        bm25_index=mock_bm25,
        embedder=mock_embedder,
    )
    assert success is True
    assert msg == ""
