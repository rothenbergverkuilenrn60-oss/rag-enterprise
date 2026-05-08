# =============================================================================
# tests/unit/test_agent_pipeline_refactor.py
# Phase 11-04 Task 1 — AgentQueryPipeline.run refactor onto call_agentic_turn
# Covers 10 behavior contracts:
#   1. NotImplementedError fallback to QueryPipeline (D-03)
#   2. Single-tool serial path (parallelism_factor=1, gather still called)
#   3. Two-tool parallel path via asyncio.gather
#   4. return_exceptions → tool_result is_error=True (LLM-resilient)
#   5. Chunk dedup runs ONCE per turn AFTER gather (gotcha #1)
#   6. Per-turn structured log records parallel_factor (W-1 — AC#4 audit trail)
#      AND AuditService.log_query stays backward-compat with intent="agent" (W-3)
#   7. stop_reason=max_tokens terminates loop gracefully
#   8. stop_reason=text_only extracts turn.text and breaks
#   9. MAX_ITERATIONS=5 honored (no infinite loop)
#  10. Narrow-except contract (B-1 / ERR-01):
#      10a httpx.HTTPError → graceful-degrade GenerationResponse
#      10b RuntimeError    → bubbles up (not caught)
# =============================================================================
from __future__ import annotations

import asyncio
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from loguru import logger as loguru_logger

from utils.models import (
    AgenticTurn,
    ChunkMetadata,
    GenerationRequest,
    GenerationResponse,
    RetrievedChunk,
    ToolCall,
)


# -----------------------------------------------------------------------------
# Fixtures
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


@pytest.fixture
def mock_pipeline():
    """Build an AgentQueryPipeline with all collaborators replaced by AsyncMock."""
    from services.pipeline import AgentQueryPipeline
    from services.memory.memory_service import MemoryContext

    pipe = AgentQueryPipeline.__new__(AgentQueryPipeline)
    pipe._llm = MagicMock()
    pipe._llm.call_agentic_turn = AsyncMock()
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
    pipe._tenant_svc = MagicMock()
    pipe._tenant_svc.get_tenant_filter = MagicMock(return_value={})
    return pipe


@pytest.fixture
def gen_req():
    return GenerationRequest(
        query="测试 多维度 查询",
        top_k=5,
        agent_mode=True,
        tenant_id="t1",
        user_id="u1",
    )


# -----------------------------------------------------------------------------
# Test 1 — NotImplementedError fallback
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_falls_back_when_call_agentic_turn_raises(mock_pipeline, gen_req):
    """D-03: provider raises NotImplementedError → fall back to QueryPipeline."""
    mock_pipeline._llm.call_agentic_turn.side_effect = NotImplementedError(
        "agent_mode not supported by OllamaLLMClient"
    )

    fallback_resp = GenerationResponse(
        answer="FALLBACK", session_id="s", query=gen_req.query, trace_id="tr"
    )
    fake_qp = MagicMock()
    fake_qp.run = AsyncMock(return_value=fallback_resp)

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda m: captured.append(str(m)), level="WARNING")
    try:
        with patch("services.pipeline.get_query_pipeline", return_value=fake_qp):
            resp = await mock_pipeline.run(gen_req)
    finally:
        loguru_logger.remove(sink_id)

    assert resp is fallback_resp
    fake_qp.run.assert_awaited_once_with(gen_req)
    assert any("falling back" in line for line in captured)


# -----------------------------------------------------------------------------
# Test 2 — Single tool: gather still called with 1 coro, parallelism_factor=1
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_single_tool_call_uses_gather(mock_pipeline, gen_req):
    tc1 = _tool_call("call_1", query="产假天数")
    mock_pipeline._llm.call_agentic_turn.side_effect = [
        _turn(tool_calls=[tc1], stop_reason="tool_use"),
        _turn(stop_reason="text_only", text="产假为158天"),
    ]
    mock_pipeline._retriever.retrieve.return_value = ([_chunk("c1")], {})

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda m: captured.append(str(m)), level="INFO")
    try:
        resp = await mock_pipeline.run(gen_req)
    finally:
        loguru_logger.remove(sink_id)

    assert resp.answer == "产假为158天"
    assert mock_pipeline._retriever.retrieve.await_count == 1
    # Per-turn log records parallel_factor=1
    assert any("parallel_factor=1" in line for line in captured)


# -----------------------------------------------------------------------------
# Test 3 — Two parallel tool calls: gather schedules both concurrently
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_tool_calls_run_concurrently(mock_pipeline, gen_req):
    """Use two events to verify gather actually runs them in parallel.

    If retrieves were serial, the second event would never get set (the first
    coroutine would block on its own event forever — test would deadlock /
    timeout). With gather, BOTH coroutines start simultaneously and we set the
    events from outside.
    """
    started_event = asyncio.Event()
    pending_count = {"n": 0}

    async def slow_retrieve(**kwargs):
        pending_count["n"] += 1
        if pending_count["n"] >= 2:
            started_event.set()
        # Wait until BOTH have started — proves parallelism.
        await asyncio.wait_for(started_event.wait(), timeout=2.0)
        return ([_chunk(f"c-{pending_count['n']}")], {})

    mock_pipeline._retriever.retrieve = AsyncMock(side_effect=slow_retrieve)

    tc1 = _tool_call("call_1", query="产假")
    tc2 = _tool_call("call_2", query="病假")
    mock_pipeline._llm.call_agentic_turn.side_effect = [
        _turn(tool_calls=[tc1, tc2], stop_reason="tool_use"),
        _turn(stop_reason="text_only", text="answer"),
    ]

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda m: captured.append(str(m)), level="INFO")
    try:
        resp = await asyncio.wait_for(mock_pipeline.run(gen_req), timeout=5.0)
    finally:
        loguru_logger.remove(sink_id)

    assert resp.answer == "answer"
    assert mock_pipeline._retriever.retrieve.await_count == 2
    assert any("parallel_factor=2" in line for line in captured)


# -----------------------------------------------------------------------------
# Test 4 — return_exceptions: failed tool → is_error=True
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_exception_becomes_is_error_tool_result(mock_pipeline, gen_req):
    """One failed tool → tool_result with is_error=True, not raised to caller."""
    call_count = {"n": 0}

    async def flaky_retrieve(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("retriever-boom")
        return ([_chunk("c-ok")], {})

    mock_pipeline._retriever.retrieve = AsyncMock(side_effect=flaky_retrieve)

    tc1 = _tool_call("call_1", query="bad")
    tc2 = _tool_call("call_2", query="good")
    mock_pipeline._llm.call_agentic_turn.side_effect = [
        _turn(tool_calls=[tc1, tc2], stop_reason="tool_use"),
        _turn(stop_reason="text_only", text="recovered"),
    ]

    resp = await mock_pipeline.run(gen_req)

    # Pipeline did NOT crash; both tools were attempted; the LLM was sent both
    # tool_results, with is_error=True for the failed one.
    assert resp.answer == "recovered"

    # Inspect the messages passed to the SECOND call_agentic_turn — that turn's
    # input contains the tool_result block we built.
    second_call = mock_pipeline._llm.call_agentic_turn.await_args_list[1]
    second_messages = second_call.kwargs["messages"]
    last_user_msg = second_messages[-1]
    assert last_user_msg["role"] == "user"
    tool_results_block = last_user_msg["content"]
    assert isinstance(tool_results_block, list)
    assert any(
        tr.get("type") == "tool_result"
        and tr.get("tool_use_id") == "call_1"
        and tr.get("is_error") is True
        for tr in tool_results_block
    )
    # Successful one has no is_error key (or False)
    assert any(
        tr.get("type") == "tool_result"
        and tr.get("tool_use_id") == "call_2"
        and not tr.get("is_error")
        for tr in tool_results_block
    )


# -----------------------------------------------------------------------------
# Test 5 — Dedup runs OUT of the gather, AFTER all results return (gotcha #1)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chunk_dedup_runs_after_gather_not_inside(mock_pipeline, gen_req):
    """Two parallel tools return overlapping chunk_ids; dedup happens AFTER
    both results return (one pass, not interleaved with retrieval)."""
    duplicate_chunk = _chunk("shared-id", doc_id="d-shared")
    unique_chunk_1 = _chunk("uniq-1")
    unique_chunk_2 = _chunk("uniq-2")

    # Each tool returns a chunk-set that overlaps on "shared-id"
    call_count = {"n": 0}

    async def overlap_retrieve(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ([duplicate_chunk, unique_chunk_1], {})
        return ([duplicate_chunk, unique_chunk_2], {})

    mock_pipeline._retriever.retrieve = AsyncMock(side_effect=overlap_retrieve)

    tc1 = _tool_call("call_a", query="a")
    tc2 = _tool_call("call_b", query="b")
    mock_pipeline._llm.call_agentic_turn.side_effect = [
        _turn(tool_calls=[tc1, tc2], stop_reason="tool_use"),
        _turn(stop_reason="text_only", text="done"),
    ]

    resp = await mock_pipeline.run(gen_req)

    # Final sources should have ONE shared-id and both uniques (dedup worked
    # exactly once, post-gather).
    chunk_ids = [c.chunk_id for c in resp.sources]
    assert chunk_ids.count("shared-id") == 1
    assert "uniq-1" in chunk_ids
    assert "uniq-2" in chunk_ids


# -----------------------------------------------------------------------------
# Test 6 — Per-turn structured-log audit + AuditService backward compat
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_per_turn_structured_log_records_parallel_factor(mock_pipeline, gen_req):
    """W-1: structured-log line is the per-turn audit trail (AC#4).
    W-3: AuditService.log_query stays backward-compat with intent='agent'."""
    tc1 = _tool_call("c1", query="q1")
    tc2 = _tool_call("c2", query="q2")
    mock_pipeline._llm.call_agentic_turn.side_effect = [
        _turn(tool_calls=[tc1, tc2], stop_reason="tool_use"),
        _turn(stop_reason="text_only", text="ok"),
    ]
    mock_pipeline._retriever.retrieve.return_value = ([_chunk("c1")], {})

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda m: captured.append(str(m)), level="INFO")
    try:
        await mock_pipeline.run(gen_req)
    finally:
        loguru_logger.remove(sink_id)

    # W-1: at least one line matches the per-turn audit pattern
    pattern = re.compile(r"\[Agent\] iter=\d+ parallel_factor=\d+ tools=\[")
    assert any(pattern.search(line) for line in captured), (
        f"No per-turn parallel_factor log line found. captured={captured!r}"
    )

    # W-3: AuditService.log_query called with literal intent="agent"
    mock_pipeline._audit.log_query.assert_awaited_once()
    assert mock_pipeline._audit.log_query.await_args.kwargs["intent"] == "agent"


# -----------------------------------------------------------------------------
# Test 7 — stop_reason=max_tokens terminates loop gracefully
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_max_tokens_stop_reason_terminates_gracefully(mock_pipeline, gen_req):
    mock_pipeline._llm.call_agentic_turn.side_effect = [
        _turn(stop_reason="max_tokens", text="partial answer (truncated)"),
    ]
    resp = await mock_pipeline.run(gen_req)
    assert resp.answer == "partial answer (truncated)"
    # No crash; loop terminated after 1 call.
    assert mock_pipeline._llm.call_agentic_turn.await_count == 1


# -----------------------------------------------------------------------------
# Test 8 — stop_reason=text_only extracts turn.text
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_text_only_stop_reason_extracts_text(mock_pipeline, gen_req):
    mock_pipeline._llm.call_agentic_turn.side_effect = [
        _turn(stop_reason="text_only", text="hello world"),
    ]
    resp = await mock_pipeline.run(gen_req)
    assert resp.answer == "hello world"


# -----------------------------------------------------------------------------
# Test 9 — MAX_ITERATIONS=5 honored (no infinite loop)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_max_iterations_is_5(mock_pipeline, gen_req):
    """LLM returns tool_use 5 times in a row → loop terminates after 5; no exception."""
    tc = _tool_call("c", query="q")
    mock_pipeline._llm.call_agentic_turn.side_effect = [
        _turn(tool_calls=[tc], stop_reason="tool_use"),
    ] * 10  # provide more than enough so we don't StopIteration

    mock_pipeline._retriever.retrieve.return_value = ([_chunk("c1")], {})

    resp = await mock_pipeline.run(gen_req)
    assert mock_pipeline._llm.call_agentic_turn.await_count == 5
    assert isinstance(resp, GenerationResponse)


# -----------------------------------------------------------------------------
# Test 10 — Narrow-except contract (B-1 / ERR-01)
# -----------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narrow_except_catches_httpx_error(mock_pipeline, gen_req):
    """10a — httpx.HTTPError is in the narrow except tuple → graceful degrade."""
    mock_pipeline._llm.call_agentic_turn.side_effect = httpx.HTTPError("boom")

    resp = await mock_pipeline.run(gen_req)
    assert isinstance(resp, GenerationResponse)
    assert resp.answer.startswith("抱歉")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_narrow_except_does_not_catch_runtime_error(mock_pipeline, gen_req):
    """10b — RuntimeError is NOT in the narrow tuple → bubbles up."""
    mock_pipeline._llm.call_agentic_turn.side_effect = RuntimeError("internal bug")

    with pytest.raises(RuntimeError, match="internal bug"):
        await mock_pipeline.run(gen_req)
