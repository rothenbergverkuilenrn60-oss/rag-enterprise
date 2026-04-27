from __future__ import annotations
import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Autouse fixture: reset feedback singleton between tests (T-06-06)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_feedback_singleton(monkeypatch):
    import services.feedback.feedback_service as mod
    yield
    monkeypatch.setattr(mod, "_feedback_service", None, raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def _patch_bus_and_memory(monkeypatch):
    """Helper: patch get_event_bus (local import) and get_memory_service."""
    import services.events.event_bus as bus_mod
    import services.memory.memory_service as mem_mod

    mock_bus = AsyncMock()
    mock_memory = AsyncMock()
    monkeypatch.setattr(bus_mod, "get_event_bus", lambda: mock_bus)
    monkeypatch.setattr(mem_mod, "get_memory_service", lambda: mock_memory)
    return mock_bus, mock_memory


@pytest.mark.asyncio
async def test_submit_feedback_publishes_event(monkeypatch):
    """submit() calls emit_feedback on the event bus."""
    mock_bus, _ = _patch_bus_and_memory(monkeypatch)

    from services.feedback.feedback_service import FeedbackService, FeedbackRecord
    svc = FeedbackService()
    record = FeedbackRecord(
        session_id="sess1",
        query="What is the policy?",
        answer="The policy is...",
        feedback=1,
        user_id="u1",
        tenant_id="t1",
    )
    await svc.submit(record)

    mock_bus.emit_feedback.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_includes_user_id_in_event(monkeypatch):
    """submit() passes user_id and session_id to emit_feedback."""
    mock_bus, _ = _patch_bus_and_memory(monkeypatch)

    from services.feedback.feedback_service import FeedbackService, FeedbackRecord
    svc = FeedbackService()
    record = FeedbackRecord(
        session_id="sess2",
        query="What is the rule?",
        answer="The rule is...",
        feedback=1,
        user_id="user_abc",
        tenant_id="tenant_xyz",
    )
    await svc.submit(record)

    call_kwargs = mock_bus.emit_feedback.call_args
    assert call_kwargs.kwargs.get("user_id") == "user_abc" or (
        "user_abc" in str(call_kwargs)
    )


@pytest.mark.asyncio
async def test_submit_negative_feedback_increments_count(monkeypatch):
    """Negative feedback increments the internal negative count for doc_ids."""
    _patch_bus_and_memory(monkeypatch)

    from services.feedback.feedback_service import FeedbackService, FeedbackRecord
    svc = FeedbackService()
    record = FeedbackRecord(
        session_id="sess3",
        query="question",
        answer="answer",
        feedback=-1,
        user_id="u1",
        doc_ids=["doc1"],
    )
    await svc.submit(record)
    assert svc._negative_counts.get("doc1", 0) == 1


@pytest.mark.asyncio
async def test_submit_positive_feedback_does_not_increment_negative_count(monkeypatch):
    """Positive feedback does not increment negative_counts."""
    _patch_bus_and_memory(monkeypatch)

    from services.feedback.feedback_service import FeedbackService, FeedbackRecord
    svc = FeedbackService()
    record = FeedbackRecord(
        session_id="sess4",
        query="question",
        answer="answer",
        feedback=1,
        user_id="u1",
        doc_ids=["doc2"],
    )
    await svc.submit(record)
    assert svc._negative_counts.get("doc2", 0) == 0


def test_get_stats_empty():
    """get_stats() returns sensible defaults when no records have been submitted."""
    from services.feedback.feedback_service import FeedbackService
    svc = FeedbackService()
    stats = svc.get_stats()
    assert stats["total"] == 0
    assert stats["satisfaction_rate"] is None
