"""Phase 23 / MEM-04 — `AgentQueryPipeline._persist_turn` wire-in test (Plan 23-05 Task 3).

Verifies the consumer-path wire-in: after `save_turn`, the pipeline calls
`dispatch_extraction(user_turn, ai_turn, user_id, tenant_id)` with the EXACT
``ConversationTurn`` instances passed to `save_turn` (eng-review A2 — no
parallel objects).

Mock-at-consumer-path discipline: patch ``services.pipeline.dispatch_extraction``
(the pipeline imports the symbol from there), NOT at the extractor module
where the symbol originally lives.

Also asserts `QueryPipeline.run` (legacy non-agentic) is INTENTIONALLY not
wired (per CONTEXT D / RESEARCH §Pattern 5).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault(
    "SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c"
)

import inspect
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.memory.memory_service import ConversationTurn


@pytest.mark.asyncio
async def test_persist_turn_dispatches_extractor(monkeypatch):
    """`AgentQueryPipeline._persist_turn` MUST call dispatch_extraction
    once post-`save_turn`, passing the SAME user_turn + ai_turn instances
    constructed for save_turn (eng-review A2 — no parallel objects)."""
    import services.pipeline as pipeline_mod
    from services.pipeline import AgentQueryPipeline

    mock_dispatch = MagicMock()
    monkeypatch.setattr(pipeline_mod, "dispatch_extraction", mock_dispatch)

    # __new__ bypass — sidestep heavy __init__ (LLM client, retriever, etc).
    pipeline = AgentQueryPipeline.__new__(AgentQueryPipeline)
    pipeline._memory = MagicMock(save_turn=AsyncMock())
    pipeline._audit = MagicMock(log_query=AsyncMock())

    req = MagicMock()
    req.session_id = "sess1"
    req.query = "I prefer React"
    req.user_id = "u1"
    req.tenant_id = "t1"
    req.top_k = 5
    req.filters = None

    chunk = MagicMock()
    chunk.doc_id = "d1"
    chunk2 = MagicMock(); chunk2.doc_id = "d2"
    chunk3 = MagicMock(); chunk3.doc_id = "d3"

    await pipeline._persist_turn(
        req=req,
        answer="The answer",
        all_chunks=[chunk, chunk2, chunk3],
        trace_id="tr1",
        t0=time.perf_counter(),
        parallelism_factors=[],
    )

    # dispatch_extraction called exactly once with kwargs form (A2 contract).
    assert mock_dispatch.call_count == 1
    kwargs = mock_dispatch.call_args.kwargs
    user_turn = kwargs["user_turn"]
    ai_turn = kwargs["ai_turn"]
    assert isinstance(user_turn, ConversationTurn)
    assert user_turn.role == "user"
    assert user_turn.content == "I prefer React"
    assert isinstance(ai_turn, ConversationTurn)
    assert ai_turn.role == "assistant"
    assert ai_turn.content == "The answer"
    assert ai_turn.sources == ["d1", "d2", "d3"]
    assert kwargs["user_id"] == "u1"
    assert kwargs["tenant_id"] == "t1"

    # Same-instance contract: dispatch receives the SAME objects save_turn got.
    save_turn_kwargs = pipeline._memory.save_turn.await_args.kwargs
    assert save_turn_kwargs["user_turn"] is user_turn
    assert save_turn_kwargs["ai_turn"] is ai_turn


def test_query_pipeline_NOT_wired():
    """`QueryPipeline.run` (legacy non-agentic path) MUST NOT call
    dispatch_extraction — CONTEXT D / RESEARCH §Pattern 5 explicit
    decision to keep extractor agent-tier only."""
    from services.pipeline import QueryPipeline

    src = inspect.getsource(QueryPipeline.run)
    assert "dispatch_extraction" not in src, (
        "QueryPipeline.run must not be wired — extractor is agent-tier only."
    )
