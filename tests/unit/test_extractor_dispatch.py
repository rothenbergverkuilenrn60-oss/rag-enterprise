"""Phase 23 / MEM-04 — `dispatch_extraction` wrapper unit tests (Plan 23-05 Task 1).

RED gates for the `services.agent.extractor.dispatch_extraction` body. The
stub (Plan 23-03) returns ``None`` unconditionally; this test file MUST fail
RED on the post-Plan-04 tree and turn GREEN once Plan 23-05 Task 2 fills the
body per RESEARCH §Pattern 4.

Mock-at-consumer-path discipline (CONTEXT §Established Patterns): all
patches target ``services.agent.extractor.<dep>``.

Signature under test (eng-review A2):
    dispatch_extraction(
        user_turn: ConversationTurn,
        ai_turn:   ConversationTurn,
        user_id:   str | None,
        tenant_id: str | None,
    ) -> None
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault(
    "SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c"
)

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.agent.extractor as extractor_mod
from services.agent.extractor import dispatch_extraction
from services.memory.memory_service import ConversationTurn
from utils.models import ExtractedFact

# -----------------------------------------------------------------------------
# Helpers + autouse reset
# -----------------------------------------------------------------------------


def _user_turn(content: str = "I prefer React") -> ConversationTurn:
    return ConversationTurn(role="user", content=content)


def _ai_turn(content: str = "Got it.") -> ConversationTurn:
    return ConversationTurn(role="assistant", content=content)


@pytest.fixture(autouse=True)
def _reset_extractor_singletons(monkeypatch):
    """Clear the extractor singleton + force `extractor_enabled=True` per test."""
    monkeypatch.setattr(extractor_mod, "_extractor", None, raising=False)
    monkeypatch.setattr(
        extractor_mod.settings, "extractor_enabled", True, raising=False
    )
    yield


# -----------------------------------------------------------------------------
# Skip-path tests (kill-switch + missing auth)
# -----------------------------------------------------------------------------


def test_dispatch_skips_on_missing_user_id(monkeypatch):
    """Empty / None user_id → log-then-skip; create_task never fires.

    Verifies the missing-user-id check fires REGARDLESS of tenant_id state
    (early-return ordering: user_id first for diagnostic clarity).
    """
    mock_create_task = MagicMock()
    mock_logger = MagicMock()
    monkeypatch.setattr(
        extractor_mod.asyncio, "create_task", mock_create_task
    )
    monkeypatch.setattr(extractor_mod, "logger", mock_logger)

    # Both empty-string and None must skip with "missing_user_id"
    for bad in ("", None):
        mock_create_task.reset_mock()
        mock_logger.reset_mock()
        dispatch_extraction(
            user_turn=_user_turn(),
            ai_turn=_ai_turn(),
            user_id=bad,
            tenant_id="t1",
        )
        assert mock_create_task.call_count == 0, (
            f"create_task fired with user_id={bad!r}"
        )
        assert mock_logger.info.call_count == 1
        kwargs = mock_logger.info.call_args.kwargs
        assert kwargs.get("operation") == "extractor_skipped"
        assert kwargs.get("reason") == "missing_user_id"


def test_dispatch_skips_on_missing_tenant_id(monkeypatch):
    """Empty / None tenant_id (with valid user_id) → log-then-skip."""
    mock_create_task = MagicMock()
    mock_logger = MagicMock()
    monkeypatch.setattr(
        extractor_mod.asyncio, "create_task", mock_create_task
    )
    monkeypatch.setattr(extractor_mod, "logger", mock_logger)

    for bad in ("", None):
        mock_create_task.reset_mock()
        mock_logger.reset_mock()
        dispatch_extraction(
            user_turn=_user_turn(),
            ai_turn=_ai_turn(),
            user_id="u1",
            tenant_id=bad,
        )
        assert mock_create_task.call_count == 0, (
            f"create_task fired with tenant_id={bad!r}"
        )
        assert mock_logger.info.call_count == 1
        kwargs = mock_logger.info.call_args.kwargs
        assert kwargs.get("operation") == "extractor_skipped"
        assert kwargs.get("reason") == "missing_tenant_id"

    # Ordering: when BOTH missing, user_id reason wins (checked first).
    mock_create_task.reset_mock()
    mock_logger.reset_mock()
    dispatch_extraction(
        user_turn=_user_turn(), ai_turn=_ai_turn(),
        user_id="", tenant_id="",
    )
    assert mock_create_task.call_count == 0
    assert mock_logger.info.call_args.kwargs.get("reason") == "missing_user_id"


def test_dispatch_skips_when_disabled(monkeypatch):
    """Kill-switch FIRST (cheapest skip). settings.extractor_enabled=False."""
    mock_create_task = MagicMock()
    mock_logger = MagicMock()
    monkeypatch.setattr(
        extractor_mod.settings, "extractor_enabled", False, raising=False
    )
    monkeypatch.setattr(
        extractor_mod.asyncio, "create_task", mock_create_task
    )
    monkeypatch.setattr(extractor_mod, "logger", mock_logger)

    dispatch_extraction(
        user_turn=_user_turn(),
        ai_turn=_ai_turn(),
        user_id="u1",
        tenant_id="t1",
    )
    assert mock_create_task.call_count == 0
    assert mock_logger.info.call_count == 1
    kwargs = mock_logger.info.call_args.kwargs
    assert kwargs.get("operation") == "extractor_skipped"
    assert kwargs.get("reason") == "disabled"


# -----------------------------------------------------------------------------
# Happy-path: create_task fires + log_task_error attached
# -----------------------------------------------------------------------------


def test_dispatch_fires_create_task(monkeypatch):
    """Happy path: create_task('extractor') + add_done_callback(log_task_error)."""
    from utils.tasks import log_task_error

    mock_task = MagicMock()
    mock_create_task = MagicMock(return_value=mock_task)
    monkeypatch.setattr(
        extractor_mod.asyncio, "create_task", mock_create_task
    )
    # Avoid actually constructing an Extractor (real LLM client init).
    fake_extractor = MagicMock(run=AsyncMock(return_value=[]))
    monkeypatch.setattr(
        extractor_mod, "get_extractor", lambda: fake_extractor
    )

    dispatch_extraction(
        user_turn=_user_turn(),
        ai_turn=_ai_turn(),
        user_id="u1",
        tenant_id="t1",
    )

    assert mock_create_task.call_count == 1
    # Coroutine is positional arg 0; name kwarg present.
    assert mock_create_task.call_args.kwargs.get("name") == "extractor"
    # Done-callback wired to log_task_error.
    assert mock_task.add_done_callback.call_count == 1
    assert mock_task.add_done_callback.call_args.args[0] is log_task_error

    # Clean up the un-awaited coroutine we just leaked into create_task's mock.
    coro = mock_create_task.call_args.args[0]
    coro.close()


# -----------------------------------------------------------------------------
# End-to-end isolation: real asyncio.create_task + raising extractor
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_extraction_failure_isolated(monkeypatch):
    """A raising extractor MUST NOT propagate into the dispatch caller.

    Uses REAL asyncio.create_task; log_task_error swallows the failure.
    """
    fake_extractor = MagicMock(
        run=AsyncMock(side_effect=RuntimeError("extractor down"))
    )
    monkeypatch.setattr(
        extractor_mod, "get_extractor", lambda: fake_extractor
    )

    # Dispatch is synchronous; returns None even when the background task
    # will raise. The raise surfaces via log_task_error (utils/tasks.py),
    # not into the caller.
    result = dispatch_extraction(
        user_turn=_user_turn(),
        ai_turn=_ai_turn(),
        user_id="u1",
        tenant_id="t1",
    )
    assert result is None

    # Let the background task complete + the done-callback fire.
    await asyncio.sleep(0.05)

    # Verify extractor.run was indeed awaited (background task ran).
    fake_extractor.run.assert_awaited_once()


# -----------------------------------------------------------------------------
# _run_and_persist body: save_fact called per extracted fact
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_run_and_persist_calls_save_fact(monkeypatch):
    """Two extracted facts → save_fact awaited twice with correct kwargs."""
    facts = [
        ExtractedFact(
            fact="user prefers React",
            category="stable_preferences",
            importance=0.8,
        ),
        ExtractedFact(
            fact="user works in healthcare",
            category="stable_preferences",
            importance=0.8,
        ),
    ]
    fake_extractor = MagicMock(run=AsyncMock(return_value=facts))
    monkeypatch.setattr(
        extractor_mod, "get_extractor", lambda: fake_extractor
    )

    mock_save_fact = AsyncMock()
    fake_mem = MagicMock()
    fake_mem._long = MagicMock(save_fact=mock_save_fact)
    # Patch the lazy `from services.memory.memory_service import get_memory_service`
    # by intercepting the module-level symbol on the source module — the
    # `from ... import` inside `_run_and_persist` resolves through
    # `services.memory.memory_service.get_memory_service`.
    import services.memory.memory_service as mem_mod
    monkeypatch.setattr(mem_mod, "get_memory_service", lambda: fake_mem)

    dispatch_extraction(
        user_turn=_user_turn(),
        ai_turn=_ai_turn(),
        user_id="u1",
        tenant_id="t1",
    )
    await asyncio.sleep(0.05)

    assert mock_save_fact.await_count == 2
    seen_facts = {
        c.kwargs["fact"] for c in mock_save_fact.await_args_list
    }
    assert seen_facts == {"user prefers React", "user works in healthcare"}
    # All calls scoped to the correct tenant + user.
    for c in mock_save_fact.await_args_list:
        assert c.kwargs["user_id"] == "u1"
        assert c.kwargs["tenant_id"] == "t1"
        assert c.kwargs["importance"] == 0.8


@pytest.mark.asyncio
async def test_dispatch_zero_facts_skips_save_fact(monkeypatch):
    """Empty extractor result → save_fact never awaited."""
    fake_extractor = MagicMock(run=AsyncMock(return_value=[]))
    monkeypatch.setattr(
        extractor_mod, "get_extractor", lambda: fake_extractor
    )

    mock_save_fact = AsyncMock()
    fake_mem = MagicMock()
    fake_mem._long = MagicMock(save_fact=mock_save_fact)
    import services.memory.memory_service as mem_mod
    monkeypatch.setattr(mem_mod, "get_memory_service", lambda: fake_mem)

    dispatch_extraction(
        user_turn=_user_turn(),
        ai_turn=_ai_turn(),
        user_id="u1",
        tenant_id="t1",
    )
    await asyncio.sleep(0.05)

    assert mock_save_fact.await_count == 0
