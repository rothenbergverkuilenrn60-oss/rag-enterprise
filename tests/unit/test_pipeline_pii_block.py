"""
tests/unit/test_pipeline_pii_block.py
TDD RED: PII block enforcement in IngestionPipeline Stage 3

Tests verify that:
  - Pipeline returns error when detected PII type is in pii_block_entities (SEC-03)
  - Pipeline continues (masks and proceeds) when PII type is NOT in pii_block_entities
  - audit.log_pii_detected is called whenever PII is detected
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


def _fake_pii_result(pii_types: list[str]) -> MagicMock:
    r = MagicMock()
    r.has_pii = bool(pii_types)
    r.pii_types = list(pii_types)
    r.findings = [MagicMock() for _ in pii_types]
    r.masked_text = "[MASKED]"
    return r


def _fake_settings(
    *,
    pii_block_on_detect: bool = True,
    pii_block_entities: list[str] | None = None,
    pii_detection_enabled: bool = True,
) -> MagicMock:
    s = MagicMock()
    s.pii_block_on_detect = pii_block_on_detect
    s.pii_block_entities = pii_block_entities or [
        "US_SSN", "CREDIT_CARD", "US_BANK_NUMBER", "US_DRIVER_LICENSE", "US_PASSPORT"
    ]
    s.pii_detection_enabled = pii_detection_enabled
    s.contextual_retrieval_enabled = False
    s.summary_index_enabled = False
    return s


def _setup_pipeline_mocks(monkeypatch: pytest.MonkeyPatch, pii_types: list[str], settings: MagicMock):
    """Patch all IngestionPipeline dependencies, return audit mock."""
    import services.pipeline as pm

    monkeypatch.setattr(pm, "settings", settings)

    pre = AsyncMock()
    pre.process.return_value = MagicMock(is_duplicate=False)
    monkeypatch.setattr(pm, "get_preprocessor", lambda: pre)

    extracted = MagicMock()
    extracted.extraction_errors = []
    extracted.body_text = "Document containing sensitive data."
    extracted.title = None
    ext = AsyncMock()
    ext.extract.return_value = extracted
    monkeypatch.setattr(pm, "get_extractor", lambda: ext)

    detector = MagicMock()
    detector.detect.return_value = _fake_pii_result(pii_types)
    monkeypatch.setattr(pm, "get_pii_detector", lambda: detector)

    audit = AsyncMock()
    monkeypatch.setattr(pm, "get_audit_service", lambda: audit)

    quality = MagicMock(passed=True, errors=[])
    knowledge = MagicMock()
    knowledge.validate_document.return_value = quality
    monkeypatch.setattr(pm, "get_knowledge_service", lambda: knowledge)

    vr = MagicMock(total_chunks=1, failed_chunks=0, errors=[])
    vectorizer = AsyncMock()
    vectorizer.vectorize_and_store.return_value = vr
    monkeypatch.setattr(pm, "get_vectorizer", lambda: vectorizer)

    doc_processor = AsyncMock()
    doc_processor.process.return_value = [MagicMock()]
    monkeypatch.setattr(pm, "get_doc_processor", lambda: doc_processor)

    event_bus = AsyncMock()
    monkeypatch.setattr(pm, "get_event_bus", lambda: event_bus)

    summary_indexer = AsyncMock()
    monkeypatch.setattr(pm, "get_summary_indexer", lambda: summary_indexer)

    counter = MagicMock()
    counter.labels.return_value = counter
    monkeypatch.setattr(pm, "pii_detected_total", counter)
    monkeypatch.setattr(pm, "ingest_total", counter)
    monkeypatch.setattr(pm, "ingest_chunks_histogram", counter)
    monkeypatch.setattr(pm, "retrieval_chunks_histogram", counter)
    monkeypatch.setattr(pm, "cache_hit_total", counter)
    monkeypatch.setattr(pm, "rule_trigger_total", counter)

    return audit


class TestPipelinePIIBlock:
    @pytest.mark.asyncio
    async def test_blocked_entity_type_returns_error_response(self, monkeypatch):
        """Pipeline returns error when detected type is in pii_block_entities."""
        s = _fake_settings(pii_block_on_detect=True, pii_block_entities=["US_SSN", "CREDIT_CARD"])
        _setup_pipeline_mocks(monkeypatch, pii_types=["US_SSN"], settings=s)

        from services.pipeline import IngestionPipeline, IngestionRequest
        pipeline = IngestionPipeline()
        req = IngestionRequest(
            file_path="/tmp/test.txt",
            metadata={"tenant_id": "t1", "user_id": "u1"},
        )
        response = await pipeline._run_ingest(req)

        assert response.success is False
        assert response.error is not None
        assert "PII" in response.error or "blocked" in response.error.lower()

    @pytest.mark.asyncio
    async def test_non_blocked_entity_type_continues_pipeline(self, monkeypatch):
        """Pipeline does not block when detected type is NOT in pii_block_entities."""
        s = _fake_settings(pii_block_on_detect=True, pii_block_entities=["US_SSN", "CREDIT_CARD"])
        _setup_pipeline_mocks(monkeypatch, pii_types=["phone"], settings=s)

        from services.pipeline import IngestionPipeline, IngestionRequest
        pipeline = IngestionPipeline()
        req = IngestionRequest(
            file_path="/tmp/test.txt",
            metadata={"tenant_id": "t1", "user_id": "u1"},
        )
        response = await pipeline._run_ingest(req)

        pii_blocked = (
            not response.success
            and response.error is not None
            and ("PII" in response.error or "blocked" in response.error.lower())
        )
        assert not pii_blocked, (
            f"Pipeline should not have blocked on 'phone' type, but got: {response.error}"
        )

    @pytest.mark.asyncio
    async def test_audit_log_pii_detected_called_when_pii_found(self, monkeypatch):
        """audit.log_pii_detected is called whenever PII is detected."""
        s = _fake_settings(pii_block_on_detect=True, pii_block_entities=["US_SSN"])
        audit = _setup_pipeline_mocks(monkeypatch, pii_types=["US_SSN"], settings=s)

        from services.pipeline import IngestionPipeline, IngestionRequest
        pipeline = IngestionPipeline()
        req = IngestionRequest(
            file_path="/tmp/test.txt",
            metadata={"tenant_id": "t1", "user_id": "u1"},
        )
        await pipeline._run_ingest(req)

        audit.log_pii_detected.assert_awaited()
