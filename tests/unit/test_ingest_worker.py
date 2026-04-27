"""Failing test stubs for services.ingest_worker (Plan 05-01, RED phase).

Covers ASYNC-01 and ASYNC-02 acceptance behaviors for the ARQ task function
and WorkerSettings class. These tests MUST FAIL until Plan 05-03 creates
services/ingest_worker.py — that's intentional TDD scaffolding.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock


# ---------------------------------------------------------------------------
# Test 1 — success path: ingest_task returns structured result dict
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_task_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given pipeline.run() returns success, ingest_task returns dict with success=True."""
    # Arrange
    mock_result = MagicMock()
    mock_result.doc_id = "doc-001"
    mock_result.success = True
    mock_result.error = None
    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("services.pipeline.get_ingest_pipeline", lambda: mock_pipeline)

    # Act
    from services.ingest_worker import ingest_task
    result = await ingest_task({}, {"doc_id": "doc-001", "content": "hello", "tenant_id": "t1"})

    # Assert
    assert result["success"] is True
    assert result["doc_id"] == "doc-001"
    assert result["tenant_id"] == "t1"
    assert result["error"] is None


# ---------------------------------------------------------------------------
# Test 2 — failure path: pipeline returns success=False with error detail
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_task_failure_error_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given pipeline.run() returns success=False, ingest_task returns dict with success=False and error detail."""
    # Arrange
    mock_result = MagicMock()
    mock_result.doc_id = "doc-002"
    mock_result.success = False
    mock_result.error = "boom"
    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("services.pipeline.get_ingest_pipeline", lambda: mock_pipeline)

    # Act
    from services.ingest_worker import ingest_task
    result = await ingest_task({}, {"doc_id": "doc-002", "content": "bad", "tenant_id": "t1"})

    # Assert
    assert result["success"] is False
    assert result["error"] == "boom"


# ---------------------------------------------------------------------------
# Test 3 — exception propagation: ValueError from pipeline must not be swallowed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_task_propagates_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given pipeline.run() raises ValueError, ingest_task re-raises it (ARQ catches at queue layer)."""
    # Arrange
    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(side_effect=ValueError("bad doc"))
    monkeypatch.setattr("services.pipeline.get_ingest_pipeline", lambda: mock_pipeline)

    # Act + Assert
    from services.ingest_worker import ingest_task
    with pytest.raises(ValueError, match="bad doc"):
        await ingest_task({}, {"doc_id": "doc-003", "content": "x", "tenant_id": "t1"})


# ---------------------------------------------------------------------------
# Test 4 — tenant ID passthrough: result includes tenant_id from request
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ingest_task_passes_tenant_id_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given req_data has tenant_id='tenant-A', result['tenant_id'] must equal 'tenant-A'."""
    # Arrange
    mock_result = MagicMock()
    mock_result.doc_id = "doc-004"
    mock_result.success = True
    mock_result.error = None
    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("services.pipeline.get_ingest_pipeline", lambda: mock_pipeline)

    # Act
    from services.ingest_worker import ingest_task
    result = await ingest_task({}, {"doc_id": "doc-004", "content": "test", "tenant_id": "tenant-A"})

    # Assert
    assert result["tenant_id"] == "tenant-A"


# ---------------------------------------------------------------------------
# Test 5 — WorkerSettings TTL: keep_result must equal 86400 (ASYNC-02 24h)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_keep_result_ttl_is_24h() -> None:
    """WorkerSettings.keep_result must be 86400 (24h) per ASYNC-02."""
    from services.ingest_worker import WorkerSettings
    assert WorkerSettings.keep_result == 86400, (
        f"Expected keep_result=86400, got {WorkerSettings.keep_result}"
    )


# ---------------------------------------------------------------------------
# Test 6 — WorkerSettings functions: ingest_task must be registered
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_worker_settings_includes_ingest_task() -> None:
    """WorkerSettings.functions must include ingest_task so ARQ can dispatch it."""
    from services.ingest_worker import ingest_task, WorkerSettings
    assert ingest_task in WorkerSettings.functions, (
        "ingest_task must be in WorkerSettings.functions"
    )


# ---------------------------------------------------------------------------
# Test 7 — WorkerSettings timeout: job_timeout must be 300 seconds
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_worker_settings_job_timeout_is_300s() -> None:
    """WorkerSettings.job_timeout must be 300 per ASYNC-01/02 spec."""
    from services.ingest_worker import WorkerSettings
    assert WorkerSettings.job_timeout == 300, (
        f"Expected job_timeout=300, got {WorkerSettings.job_timeout}"
    )
