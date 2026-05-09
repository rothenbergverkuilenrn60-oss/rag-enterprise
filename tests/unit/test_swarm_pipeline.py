# =============================================================================
# tests/unit/test_swarm_pipeline.py
# Phase 12-03 Task 2 — SwarmQueryPipeline unit contracts (AGENT-03)
# Covers AGENT-03 acceptance criteria 1–7 + Pitfall 4 (coordinator main model).
# =============================================================================
"""Unit tests for SwarmQueryPipeline (AGENT-03)."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.audit.audit_service import AuditEvent
from services.memory.memory_service import MemoryContext
from services.pipeline import SwarmQueryPipeline
from utils.models import (
    AgenticTurn,
    ChunkMetadata,
    GenerationRequest,
    GenerationResponse,
    RetrievedChunk,
    ToolCall,
)


# -----------------------------------------------------------------------------
# Helpers (mirrors tests/unit/test_agent_pipeline_refactor.py:45–76)
# -----------------------------------------------------------------------------


def _chunk(chunk_id: str, doc_id: str = "d1", title: str = "t") -> RetrievedChunk:
    """Make a minimal RetrievedChunk with deterministic chunk_id."""
    md = ChunkMetadata(
        doc_id=doc_id,
        title=title,
    )
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        content=f"content-{chunk_id}",
        metadata=md,
    )


def _turn(
    *,
    tool_calls: list[ToolCall] | None = None,
    stop_reason: str = "text_only",
    text: str = "",
) -> AgenticTurn:
    return AgenticTurn(
        text=text,
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,  # type: ignore[arg-type]
        raw_assistant_msg={"role": "assistant", "content": text},
        usage_input_tokens=0,
        usage_output_tokens=0,
    )


def _tool_call(call_id: str, name: str = "search_knowledge_base", **args: Any) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args or {"query": "q"})


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_pipeline() -> SwarmQueryPipeline:
    """Build a SwarmQueryPipeline with all collaborators replaced by AsyncMock.

    Phase 16 Wave-3 update: ``_filter_extractor`` is now a stored instance
    attribute (same change applied to AgentQueryPipeline) so tests do not
    require a live LLM for filter extraction.
    """
    from services.nlu.filter_extractor import ExtractionResult

    pipe = SwarmQueryPipeline.__new__(SwarmQueryPipeline)
    pipe._llm = MagicMock()
    pipe._llm.provider_name = "anthropic"         # required for schemas_for() in _run_sub_agent
    pipe._llm.call_agentic_turn = AsyncMock()
    pipe._llm.chat = AsyncMock()                  # coordinator + synthesis
    pipe._retriever = MagicMock()
    pipe._retriever.retrieve = AsyncMock(return_value=([], {}))
    pipe._memory = MagicMock()
    pipe._memory.load_context = AsyncMock(
        return_value=MemoryContext(
            session_id="s",
            user_id="u",
            tenant_id="t",
            short_term=[],
            long_term_facts=[],
            user_profile=None,
        )
    )
    pipe._memory.save_turn = AsyncMock()
    pipe._audit = MagicMock()
    pipe._audit.log_query = AsyncMock()
    pipe._audit.log = AsyncMock()                 # swarm calls log() directly
    pipe._tenant_svc = MagicMock()
    pipe._tenant_svc.get_tenant_filter = MagicMock(return_value={})
    pipe._filter_extractor = MagicMock()
    pipe._filter_extractor.extract = AsyncMock(
        return_value=ExtractionResult(filters={}, semantic_query="")
    )
    return pipe


@pytest.fixture
def gen_req() -> GenerationRequest:
    return GenerationRequest(
        query="测试 多维度 查询",
        top_k=5,
        swarm_mode=True,
        tenant_id="t1",
        user_id="u1",
    )


# -----------------------------------------------------------------------------
# Test 1 — N=1 fallback delegates to AgentQueryPipeline (D-03 / AGENT-03 #1)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_n1_fallback_delegates_to_agent_pipeline(
    mock_pipeline: SwarmQueryPipeline, gen_req: GenerationRequest
) -> None:
    """Coordinator returns single-element array → delegate to AgentQueryPipeline."""
    mock_pipeline._llm.chat = AsyncMock(return_value='["only-q"]')
    expected_resp = GenerationResponse(
        answer="agent-answer",
        sources=[],
        session_id=gen_req.session_id,
        query=gen_req.query,
        latency_ms=1.0,
        trace_id="abcd1234",
        model="m",
    )
    with patch("services.pipeline.get_agent_pipeline") as mock_get_agent:
        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value=expected_resp)
        mock_get_agent.return_value = mock_agent
        resp = await mock_pipeline.run(gen_req)

    # Delegation happened with the original req.
    mock_get_agent.assert_called_once()
    mock_agent.run.assert_awaited_once_with(gen_req)
    assert resp is expected_resp
    # Sub-agent loop never invoked.
    mock_pipeline._llm.call_agentic_turn.assert_not_awaited()


# -----------------------------------------------------------------------------
# Test 2 — Sub-agents have isolated message histories (Pitfall 1 / AGENT-03 #3)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sub_agents_have_isolated_message_histories(
    mock_pipeline: SwarmQueryPipeline, gen_req: GenerationRequest
) -> None:
    """Each sub-agent must start with its own messages list (no shared reference)."""
    mock_pipeline._llm.chat = AsyncMock(side_effect=['["q-A","q-B"]', "synth"])

    captured_messages: list[list[dict[str, Any]]] = []

    async def fake_turn(*, messages: list[dict[str, Any]], **_: Any) -> AgenticTurn:
        # Capture by deep-shape, not by reference.
        captured_messages.append([dict(m) for m in messages])
        return _turn(stop_reason="text_only", text="ans")

    mock_pipeline._llm.call_agentic_turn = AsyncMock(side_effect=fake_turn)
    await mock_pipeline.run(gen_req)

    assert len(captured_messages) == 2, captured_messages
    assert all(len(m) == 1 for m in captured_messages), (
        "each sub-agent starts with exactly one message"
    )
    # Different content per sub-agent — proves no shared list.
    assert captured_messages[0][0]["content"] != captured_messages[1][0]["content"]


# -----------------------------------------------------------------------------
# Test 3 — Sub-agents run concurrently via asyncio.gather (D-05 / AGENT-03 #2)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sub_agents_run_concurrently(
    mock_pipeline: SwarmQueryPipeline, gen_req: GenerationRequest
) -> None:
    """If sub-agents ran serially this would deadlock waiting on the Event."""
    mock_pipeline._llm.chat = AsyncMock(side_effect=['["q-A","q-B"]', "synth"])

    started_event = asyncio.Event()
    pending = {"n": 0}

    async def slow_turn(**_: Any) -> AgenticTurn:
        pending["n"] += 1
        if pending["n"] >= 2:
            started_event.set()
        await asyncio.wait_for(started_event.wait(), timeout=2.0)
        return _turn(stop_reason="text_only", text="ans")

    mock_pipeline._llm.call_agentic_turn = AsyncMock(side_effect=slow_turn)

    resp = await asyncio.wait_for(mock_pipeline.run(gen_req), timeout=3.0)
    assert resp.answer == "synth"


# -----------------------------------------------------------------------------
# Test 4 — MAX_SWARM_AGENTS hard cap (D-09 / AGENT-03 #4)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_max_swarm_agents_cap(
    mock_pipeline: SwarmQueryPipeline, gen_req: GenerationRequest
) -> None:
    """Coordinator returns 8 items; cap enforces only MAX_SWARM_AGENTS dispatched."""
    too_many = '["q1","q2","q3","q4","q5","q6","q7","q8"]'
    mock_pipeline._llm.chat = AsyncMock(side_effect=[too_many, "synth"])
    captured: list[Any] = []

    async def fake_turn(*, messages: list[dict[str, Any]], **_: Any) -> AgenticTurn:
        captured.append(messages[0]["content"])
        return _turn(stop_reason="text_only", text="x")

    mock_pipeline._llm.call_agentic_turn = AsyncMock(side_effect=fake_turn)
    await mock_pipeline.run(gen_req)

    assert len(captured) == SwarmQueryPipeline.MAX_SWARM_AGENTS
    assert SwarmQueryPipeline.MAX_SWARM_AGENTS == 5  # default — sanity


# -----------------------------------------------------------------------------
# Test 5 — Partial failure returns synthesized response (Pitfall 2 / AGENT-03 #5)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_partial_failure_returns_response(
    mock_pipeline: SwarmQueryPipeline, gen_req: GenerationRequest
) -> None:
    """One sub-agent raises httpx.HTTPError → synthesis still runs with error marker."""
    mock_pipeline._llm.chat = AsyncMock(side_effect=['["q1","q2","q3"]', "synthesized"])
    call_count = {"n": 0}

    async def turn_with_failure(**_: Any) -> AgenticTurn:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise httpx.HTTPError("boom")
        return _turn(stop_reason="text_only", text=f"ans-{call_count['n']}")

    mock_pipeline._llm.call_agentic_turn = AsyncMock(side_effect=turn_with_failure)
    resp = await mock_pipeline.run(gen_req)

    assert isinstance(resp, GenerationResponse)
    assert resp.answer == "synthesized"
    # Synthesis call is the SECOND chat call (after coordinator).
    synth_call = mock_pipeline._llm.chat.await_args_list[1]
    synth_input = synth_call.kwargs["user"]
    assert "[Sub-agent 1 failed:" in synth_input


# -----------------------------------------------------------------------------
# Test 6 — Synthesis references all sub-questions and sub-answers (AGENT-03 #6)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_synthesis_references_all_sub_answers(
    mock_pipeline: SwarmQueryPipeline, gen_req: GenerationRequest
) -> None:
    """All sub-question texts and all sub-answer texts must appear in synthesis input."""
    mock_pipeline._llm.chat = AsyncMock(side_effect=['["dim-A","dim-B"]', "final"])
    texts = iter(["answer-alpha", "answer-beta"])

    async def fake_turn(**_: Any) -> AgenticTurn:
        return _turn(stop_reason="text_only", text=next(texts))

    mock_pipeline._llm.call_agentic_turn = AsyncMock(side_effect=fake_turn)
    await mock_pipeline.run(gen_req)

    synth_call = mock_pipeline._llm.chat.await_args_list[1]
    synth_input = synth_call.kwargs["user"]
    for needle in ("dim-A", "dim-B", "answer-alpha", "answer-beta"):
        assert needle in synth_input, f"{needle!r} missing from synth input"


# -----------------------------------------------------------------------------
# Test 7 — Audit log carries all 9 swarm fields via log() with AuditEvent (AGENT-03 #7)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_audit_log_swarm_fields(
    mock_pipeline: SwarmQueryPipeline, gen_req: GenerationRequest
) -> None:
    """Swarm path uses log(AuditEvent) — log_query has fixed signature."""
    mock_pipeline._llm.chat = AsyncMock(side_effect=['["q1","q2"]', "synth"])
    mock_pipeline._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(stop_reason="text_only", text="ans")
    )
    await mock_pipeline.run(gen_req)

    # Use log(AuditEvent) — NOT log_query — for swarm path.
    mock_pipeline._audit.log_query.assert_not_awaited()
    mock_pipeline._audit.log.assert_awaited_once()
    event = mock_pipeline._audit.log.await_args.args[0]
    assert isinstance(event, AuditEvent)
    assert event.detail["intent"] == "swarm"
    required = {
        "swarm_n", "per_agent_turns", "per_agent_tool_calls",
        "swarm_latency_ms", "synthesis_latency_ms",
        "latency_ms", "sources_count", "query_len",
    }
    missing = required - set(event.detail.keys())
    assert not missing, f"missing keys: {missing}"
    assert event.detail["swarm_n"] == 2
    assert len(event.detail["per_agent_turns"]) == 2
    assert len(event.detail["per_agent_tool_calls"]) == 2


# -----------------------------------------------------------------------------
# Test 8 — Coordinator + synthesis use main model, not haiku (Pitfall 4)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_coordinator_uses_main_model_not_haiku(
    mock_pipeline: SwarmQueryPipeline, gen_req: GenerationRequest
) -> None:
    """Coordinator decomposition + final synthesis must both hit the main model."""
    mock_pipeline._llm.chat = AsyncMock(side_effect=['["q1","q2"]', "synth"])
    mock_pipeline._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(stop_reason="text_only", text="ans")
    )
    await mock_pipeline.run(gen_req)

    coord_call = mock_pipeline._llm.chat.await_args_list[0]
    assert coord_call.kwargs.get("task_type") == "generate", (
        f"coordinator must use task_type='generate' (main model) per Pitfall 4; "
        f"got {coord_call.kwargs.get('task_type')!r}"
    )
    # Synthesis call should also use main model.
    synth_call = mock_pipeline._llm.chat.await_args_list[1]
    assert synth_call.kwargs.get("task_type") == "generate"
