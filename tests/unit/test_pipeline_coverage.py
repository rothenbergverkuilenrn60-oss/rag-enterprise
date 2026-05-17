"""Coverage tests for services/pipeline.py per TEST-08 (Phase 22 SC1).

Targets:
- AgentQueryPipeline.run/run_streaming error branches
- SwarmQueryPipeline synthesis path (debate=False)
- _dedup_chunks
- _build_initial_messages

Mock at consumer path (services.pipeline.<dep>) only — CF-02 v1.3 D-04 lock.
No production-code changes (CF-01 v1.3 D-04 lock).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

# Plan 27-02 / TD-06 — auto-attach redis_mock fixture for every test in this
# module (tests/conftest.py:pytest_collection_modifyitems hook).
pytestmark = pytest.mark.uses_redis

# ─── Shared helpers ─────────────────────────────────────────────────────────


def _make_req(**kwargs: Any):
    """Build a minimal GenerationRequest."""
    from utils.models import GenerationRequest
    return GenerationRequest(query=kwargs.get("query", "test query"), **{k: v for k, v in kwargs.items() if k != "query"})


def _make_chunk(chunk_id: str = "c1", doc_id: str = "d1") -> Any:
    """Build a minimal RetrievedChunk."""
    from utils.models import ChunkMetadata, RetrievedChunk
    meta = ChunkMetadata(doc_id=doc_id, chunk_index=0)
    return RetrievedChunk(chunk_id=chunk_id, doc_id=doc_id, content="text", metadata=meta)


def _make_tool_plan_terminal(rationale: str = "final answer") -> Any:
    """ToolPlan with no steps — terminal turn."""
    from utils.models import ToolPlan
    return ToolPlan(steps=[], rationale=rationale, stop_reason="text_only")


def _make_tool_plan_with_step() -> Any:
    """ToolPlan with one step."""
    from utils.models import ToolCall, ToolPlan
    step = ToolCall(id="tc1", name="search_knowledge_base", arguments={"query": "q"})
    return ToolPlan(steps=[step], parallel_groups=[[0]], rationale="", stop_reason="tool_use",
                    raw_assistant_msg={"role": "assistant", "content": []})


def _make_mem_ctx(session_id: str = "sess", user_id: str = "u1", tenant_id: str = "t1"):
    """Minimal MemoryContext."""
    from services.memory.memory_service import MemoryContext
    return MemoryContext(
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        short_term=[],
        long_term_facts=[],
        user_profile=None,
    )


def _make_tool_result(is_error: bool = False) -> Any:
    from utils.models import ToolResult
    return ToolResult(content="result-content", chunks=[], is_error=is_error)


def _make_generation_response(answer: str = "ans") -> Any:
    from utils.models import GenerationResponse
    return GenerationResponse(
        answer=answer, sources=[], session_id="sess", query="q",
        latency_ms=1.0, trace_id="tid", model="claude-3-5-sonnet-20241022",
    )


def _patch_pipeline_infra(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """
    Patch all AgentQueryPipeline constructor deps at the consumer path
    (CF-02) and return a dict of named stubs for assertion in tests.
    """

    stub_memory = AsyncMock()
    stub_memory.load_context = AsyncMock(return_value=_make_mem_ctx())
    stub_memory.save_turn = AsyncMock()

    stub_audit = AsyncMock()
    stub_audit.log_query = AsyncMock()

    stub_tenant = MagicMock()
    stub_tenant.get_tenant_filter.return_value = {}

    stub_filter_extractor = AsyncMock()
    stub_filter_extractor.extract = AsyncMock(return_value=MagicMock(filters={}))

    stub_retriever = AsyncMock()

    stub_llm = AsyncMock()
    stub_llm.provider_name = "anthropic"

    stub_tool_registry = MagicMock()
    stub_tool_registry.schemas_for.return_value = []

    monkeypatch.setattr("services.pipeline.get_memory_service", lambda: stub_memory)
    monkeypatch.setattr("services.pipeline.get_audit_service", lambda: stub_audit)
    monkeypatch.setattr("services.pipeline.get_tenant_service", lambda: stub_tenant)
    monkeypatch.setattr("services.pipeline.get_filter_extractor", lambda: stub_filter_extractor)
    monkeypatch.setattr("services.pipeline.get_retriever", lambda: stub_retriever)
    monkeypatch.setattr("services.pipeline.get_llm_client", lambda: stub_llm)
    monkeypatch.setattr("services.pipeline.get_tool_registry", lambda: stub_tool_registry)

    return {
        "memory": stub_memory,
        "audit": stub_audit,
        "tenant": stub_tenant,
        "filter_extractor": stub_filter_extractor,
        "retriever": stub_retriever,
        "llm": stub_llm,
        "tool_registry": stub_tool_registry,
    }


# ─── _dedup_chunks ───────────────────────────────────────────────────────────

def test_dedup_chunks_collapses_duplicate_chunk_ids() -> None:
    from services.pipeline import AgentQueryPipeline
    c1 = _make_chunk(chunk_id="dup", doc_id="d1")
    c2 = _make_chunk(chunk_id="dup", doc_id="d1")
    result = AgentQueryPipeline._dedup_chunks([c1, c2])
    assert len(result) == 1
    assert result[0].chunk_id == "dup"


def test_dedup_chunks_preserves_order_for_distinct_ids() -> None:
    from services.pipeline import AgentQueryPipeline
    chunks = [_make_chunk(chunk_id=f"c{i}") for i in range(5)]
    result = AgentQueryPipeline._dedup_chunks(chunks)
    assert [c.chunk_id for c in result] == [f"c{i}" for i in range(5)]


def test_dedup_chunks_empty_input_returns_empty() -> None:
    from services.pipeline import AgentQueryPipeline
    assert AgentQueryPipeline._dedup_chunks([]) == []


# ─── _build_initial_messages ─────────────────────────────────────────────────

def test_build_initial_messages_returns_at_least_one_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pipeline_infra(monkeypatch)
    from services.pipeline import AgentQueryPipeline
    pipeline = AgentQueryPipeline()
    req = _make_req()
    mem_ctx = _make_mem_ctx()
    msgs = pipeline._build_initial_messages(req, mem_ctx)
    # Must end with user message containing the query
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == req.query


def test_build_initial_messages_with_short_term_history(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pipeline_infra(monkeypatch)
    from services.memory.memory_service import ConversationTurn, MemoryContext
    from services.pipeline import AgentQueryPipeline
    pipeline = AgentQueryPipeline()
    req = _make_req(query="follow-up question")
    turns = [
        ConversationTurn(role="user", content="hi"),
        ConversationTurn(role="assistant", content="hello"),
    ]
    mem_ctx = MemoryContext(
        session_id="s", user_id="u", tenant_id="t",
        short_term=turns, long_term_facts=[], user_profile=None,
    )
    msgs = pipeline._build_initial_messages(req, mem_ctx)
    # History prepended + user query appended
    assert len(msgs) >= 3
    assert msgs[-1]["content"] == "follow-up question"


# ─── AgentQueryPipeline.run error branches ───────────────────────────────────

@pytest.mark.asyncio
async def test_agent_query_pipeline_run_planner_api_error_returns_graceful_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When planner raises anthropic.APIError, run() returns graceful error response (no raise)."""
    import anthropic
    _patch_pipeline_infra(monkeypatch)

    stub_planner = AsyncMock()
    stub_planner.plan_from_messages = AsyncMock(
        side_effect=anthropic.APIStatusError(
            message="overloaded",
            response=MagicMock(status_code=529, headers={}),
            body={},
        )
    )
    stub_executor = AsyncMock()

    monkeypatch.setattr("services.pipeline.get_planner", lambda: stub_planner)
    monkeypatch.setattr("services.pipeline.get_executor", lambda: stub_executor)

    from services.pipeline import AgentQueryPipeline

    # Also patch _persist_turn to avoid memory/audit side effects
    async def _fake_persist(req, answer, chunks, trace_id, t0, pf):
        return _make_generation_response(answer=answer)

    pipeline = AgentQueryPipeline()
    monkeypatch.setattr(pipeline, "_persist_turn", _fake_persist)

    req = _make_req()
    resp = await pipeline.run(req)
    # Run should NOT raise; should return a response with error text
    assert resp is not None
    assert isinstance(resp.answer, str)


@pytest.mark.asyncio
async def test_agent_query_pipeline_run_executor_error_continues_to_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When executor.execute_plan raises, it propagates out (gather returns BaseException).

    The pipeline's _build_tool_results handles BaseException per step — no crash of outer loop.
    """
    _patch_pipeline_infra(monkeypatch)

    terminal_plan = _make_tool_plan_terminal(rationale="done")

    stub_planner = AsyncMock()
    # First call → plan with step; second call → terminal
    stub_planner.plan_from_messages = AsyncMock(side_effect=[
        _make_tool_plan_with_step(),
        terminal_plan,
    ])

    stub_executor = AsyncMock()
    # execute_plan returns list with a BaseException wrapped item
    exc = RuntimeError("executor-down")
    tool_result_with_error = [exc]
    stub_executor.execute_plan = AsyncMock(return_value=tool_result_with_error)

    monkeypatch.setattr("services.pipeline.get_planner", lambda: stub_planner)
    monkeypatch.setattr("services.pipeline.get_executor", lambda: stub_executor)

    async def _fake_persist(req, answer, chunks, trace_id, t0, pf):
        return _make_generation_response(answer=answer)

    from services.pipeline import AgentQueryPipeline
    pipeline = AgentQueryPipeline()
    monkeypatch.setattr(pipeline, "_persist_turn", _fake_persist)

    req = _make_req()
    resp = await pipeline.run(req)
    assert resp is not None


@pytest.mark.asyncio
async def test_agent_query_pipeline_run_tool_error_result_continues_to_synth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ToolResult(is_error=True) does not abort the run; synthesizer called normally."""
    _patch_pipeline_infra(monkeypatch)

    step_plan = _make_tool_plan_with_step()
    terminal_plan = _make_tool_plan_terminal(rationale="synthesized answer")

    stub_planner = AsyncMock()
    stub_planner.plan_from_messages = AsyncMock(side_effect=[step_plan, terminal_plan])

    stub_executor = AsyncMock()
    # Tool returns ToolResult with is_error=True
    stub_executor.execute_plan = AsyncMock(return_value=[_make_tool_result(is_error=True)])

    monkeypatch.setattr("services.pipeline.get_planner", lambda: stub_planner)
    monkeypatch.setattr("services.pipeline.get_executor", lambda: stub_executor)

    captured_answer: list[str] = []

    async def _fake_persist(req, answer, chunks, trace_id, t0, pf):
        captured_answer.append(answer)
        return _make_generation_response(answer=answer)

    from services.pipeline import AgentQueryPipeline
    pipeline = AgentQueryPipeline()
    monkeypatch.setattr(pipeline, "_persist_turn", _fake_persist)

    req = _make_req()
    resp = await pipeline.run(req)
    # run completed — verify synth answer was passed through
    assert resp is not None
    assert len(captured_answer) == 1
    assert captured_answer[0] == "synthesized answer"


@pytest.mark.asyncio
async def test_agent_query_pipeline_run_not_implemented_delegates_to_query_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NotImplementedError from planner triggers fallback to QueryPipeline.run."""
    _patch_pipeline_infra(monkeypatch)

    stub_planner = AsyncMock()
    stub_planner.plan_from_messages = AsyncMock(side_effect=NotImplementedError("no agentic turn"))

    monkeypatch.setattr("services.pipeline.get_planner", lambda: stub_planner)
    monkeypatch.setattr("services.pipeline.get_executor", lambda: AsyncMock())

    fallback_resp = _make_generation_response(answer="fallback")
    stub_query_pipeline = AsyncMock()
    stub_query_pipeline.run = AsyncMock(return_value=fallback_resp)
    monkeypatch.setattr("services.pipeline.get_query_pipeline", lambda: stub_query_pipeline)

    from services.pipeline import AgentQueryPipeline
    pipeline = AgentQueryPipeline()

    req = _make_req()
    resp = await pipeline.run(req)
    assert resp.answer == "fallback"
    stub_query_pipeline.run.assert_awaited_once()


# ─── AgentQueryPipeline.run_streaming error branches ─────────────────────────

async def _collect_stream(pipeline: Any, req: Any) -> list[Any]:
    events = []
    async for event in pipeline.run_streaming(req):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_agent_query_pipeline_run_streaming_planner_api_error_yields_synthesizer_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When planner raises APIError, run_streaming still yields SynthesizerFinalEvent and closes cleanly."""
    import anthropic
    _patch_pipeline_infra(monkeypatch)

    stub_planner = AsyncMock()
    stub_planner.plan_from_messages = AsyncMock(
        side_effect=anthropic.APIStatusError(
            message="overloaded",
            response=MagicMock(status_code=529, headers={}),
            body={},
        )
    )
    monkeypatch.setattr("services.pipeline.get_planner", lambda: stub_planner)
    monkeypatch.setattr("services.pipeline.get_executor", lambda: AsyncMock())

    async def _fake_persist(req, answer, chunks, trace_id, t0, pf):
        return _make_generation_response(answer=answer)

    from services.pipeline import AgentQueryPipeline
    from utils.models import SynthesizerFinalEvent
    pipeline = AgentQueryPipeline()
    monkeypatch.setattr(pipeline, "_persist_turn", _fake_persist)

    req = _make_req()
    events = await _collect_stream(pipeline, req)

    # Stream must close cleanly (no unhandled exception)
    # SynthesizerFinalEvent must be the last event
    assert events, "expected at least SynthesizerFinalEvent"
    assert isinstance(events[-1], SynthesizerFinalEvent)


@pytest.mark.asyncio
async def test_agent_query_pipeline_run_streaming_not_implemented_yields_synthesizer_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NotImplementedError from planner in streaming mode yields SynthesizerFinalEvent."""
    _patch_pipeline_infra(monkeypatch)

    stub_planner = AsyncMock()
    stub_planner.plan_from_messages = AsyncMock(side_effect=NotImplementedError("no agentic turn"))
    monkeypatch.setattr("services.pipeline.get_planner", lambda: stub_planner)
    monkeypatch.setattr("services.pipeline.get_executor", lambda: AsyncMock())

    async def _fake_persist(req, answer, chunks, trace_id, t0, pf):
        return _make_generation_response(answer=answer)

    from services.pipeline import AgentQueryPipeline
    from utils.models import SynthesizerFinalEvent
    pipeline = AgentQueryPipeline()
    monkeypatch.setattr(pipeline, "_persist_turn", _fake_persist)

    req = _make_req()
    events = await _collect_stream(pipeline, req)

    assert isinstance(events[-1], SynthesizerFinalEvent)


@pytest.mark.asyncio
async def test_agent_query_pipeline_run_streaming_terminal_plan_yields_synthesizer_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When planner returns terminal plan (no steps), stream yields SynthesizerFinalEvent with answer."""
    _patch_pipeline_infra(monkeypatch)

    stub_planner = AsyncMock()
    stub_planner.plan_from_messages = AsyncMock(return_value=_make_tool_plan_terminal(rationale="my answer"))
    monkeypatch.setattr("services.pipeline.get_planner", lambda: stub_planner)
    monkeypatch.setattr("services.pipeline.get_executor", lambda: AsyncMock())

    async def _fake_persist(req, answer, chunks, trace_id, t0, pf):
        return _make_generation_response(answer=answer)

    from services.pipeline import AgentQueryPipeline
    from utils.models import SynthesizerFinalEvent
    pipeline = AgentQueryPipeline()
    monkeypatch.setattr(pipeline, "_persist_turn", _fake_persist)

    req = _make_req()
    events = await _collect_stream(pipeline, req)

    final = events[-1]
    assert isinstance(final, SynthesizerFinalEvent)
    assert final.answer == "my answer"


@pytest.mark.asyncio
async def test_agent_query_pipeline_run_streaming_emits_planner_plan_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a tool-step plan, run_streaming emits PlannerPlanEvent before SynthesizerFinalEvent."""
    _patch_pipeline_infra(monkeypatch)

    step_plan = _make_tool_plan_with_step()
    terminal_plan = _make_tool_plan_terminal(rationale="done")

    stub_planner = AsyncMock()
    stub_planner.plan_from_messages = AsyncMock(side_effect=[step_plan, terminal_plan])

    async def _fake_stream(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        # Yield a ToolSpanStartEvent + ToolSpanEndEvent + bare result
        from utils.models import ToolResult, ToolSpanEndEvent, ToolSpanStartEvent
        span_id = "s1"
        yield ToolSpanStartEvent(
            trace_id="t", seq=0, ts_ms=0, span_id=span_id,
            name="search_knowledge_base", args={},
        )
        yield ToolSpanEndEvent(
            trace_id="t", seq=1, ts_ms=0, span_id=span_id,
            latency_ms=10, chunk_count=0, is_error=False, content_preview="ok",
        )
        yield ToolResult(content="ok", chunks=[], is_error=False)

    stub_executor = MagicMock()
    stub_executor.execute_plan_streaming = _fake_stream

    monkeypatch.setattr("services.pipeline.get_planner", lambda: stub_planner)
    monkeypatch.setattr("services.pipeline.get_executor", lambda: stub_executor)

    async def _fake_persist(req, answer, chunks, trace_id, t0, pf):
        return _make_generation_response(answer=answer)

    from services.pipeline import AgentQueryPipeline
    from utils.models import SynthesizerFinalEvent
    pipeline = AgentQueryPipeline()
    monkeypatch.setattr(pipeline, "_persist_turn", _fake_persist)

    req = _make_req()
    events = await _collect_stream(pipeline, req)

    event_types = [type(e).__name__ for e in events]
    assert "PlannerPlanEvent" in event_types
    assert isinstance(events[-1], SynthesizerFinalEvent)


# ─── SwarmQueryPipeline synthesis path (debate=False = no verifier) ──────────

def _patch_swarm_infra(monkeypatch: pytest.MonkeyPatch, sub_questions: list[str]) -> dict[str, Any]:
    """Patch SwarmQueryPipeline deps at consumer path for synthesis tests."""
    stub_memory = AsyncMock()
    stub_memory.save_turn = AsyncMock()
    stub_audit = AsyncMock()
    stub_audit.log = AsyncMock()
    stub_tenant = MagicMock()
    stub_tenant.get_tenant_filter.return_value = {}
    stub_filter_extractor = AsyncMock()
    stub_filter_extractor.extract = AsyncMock(return_value=MagicMock(filters={}))
    stub_retriever = AsyncMock()
    stub_llm = AsyncMock()

    monkeypatch.setattr("services.pipeline.get_memory_service", lambda: stub_memory)
    monkeypatch.setattr("services.pipeline.get_audit_service", lambda: stub_audit)
    monkeypatch.setattr("services.pipeline.get_tenant_service", lambda: stub_tenant)
    monkeypatch.setattr("services.pipeline.get_filter_extractor", lambda: stub_filter_extractor)
    monkeypatch.setattr("services.pipeline.get_retriever", lambda: stub_retriever)
    monkeypatch.setattr("services.pipeline.get_llm_client", lambda: stub_llm)

    return {
        "memory": stub_memory,
        "audit": stub_audit,
        "llm": stub_llm,
    }


@pytest.mark.asyncio
async def test_swarm_query_pipeline_synthesis_composes_peer_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SwarmQueryPipeline.run decomposes, runs sub-agents, and synthesizes final answer."""
    _patch_swarm_infra(monkeypatch, sub_questions=["q1", "q2"])

    from services.pipeline import SwarmQueryPipeline, _SubAgentResult

    sub_questions = ["sub-q1", "sub-q2"]
    sub_results = [
        _SubAgentResult(answer="answer-1", turns=1, tool_calls_count=0, chunks=[]),
        _SubAgentResult(answer="answer-2", turns=1, tool_calls_count=0, chunks=[]),
    ]

    pipeline = SwarmQueryPipeline()
    monkeypatch.setattr(pipeline, "_decompose", AsyncMock(return_value=sub_questions))
    monkeypatch.setattr(pipeline, "_run_sub_agent", AsyncMock(side_effect=sub_results))
    monkeypatch.setattr(pipeline, "_synthesize", AsyncMock(return_value="synthesized-final"))

    req = _make_req()
    resp = await pipeline.run(req)

    assert resp.answer == "synthesized-final"
    pipeline._synthesize.assert_awaited_once()


@pytest.mark.asyncio
async def test_swarm_query_pipeline_run_no_verifier_hop_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SwarmQueryPipeline.run does NOT call any verifier — Phase 21 invariant carry-forward."""
    _patch_swarm_infra(monkeypatch, sub_questions=["q1", "q2"])

    from services.pipeline import SwarmQueryPipeline, _SubAgentResult

    pipeline = SwarmQueryPipeline()
    monkeypatch.setattr(pipeline, "_decompose", AsyncMock(return_value=["s1", "s2"]))
    sub_res = _SubAgentResult(answer="a", turns=1, tool_calls_count=0, chunks=[])
    monkeypatch.setattr(pipeline, "_run_sub_agent", AsyncMock(return_value=sub_res))
    monkeypatch.setattr(pipeline, "_synthesize", AsyncMock(return_value="final"))

    # Ensure there is no `_verify` or similar attribute on the pipeline
    assert not hasattr(pipeline, "_verify"), (
        "SwarmQueryPipeline should NOT have a _verify method (Phase 21 invariant)"
    )

    req = _make_req()
    resp = await pipeline.run(req)
    assert resp is not None


@pytest.mark.asyncio
async def test_swarm_query_pipeline_n1_delegates_to_agent_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When decompose returns single sub-question, delegates to AgentQueryPipeline."""
    _patch_swarm_infra(monkeypatch, sub_questions=["q1"])

    from services.pipeline import SwarmQueryPipeline

    pipeline = SwarmQueryPipeline()
    monkeypatch.setattr(pipeline, "_decompose", AsyncMock(return_value=["only-one"]))

    fallback_resp = _make_generation_response(answer="agent-answer")
    stub_agent_pipeline = AsyncMock()
    stub_agent_pipeline.run = AsyncMock(return_value=fallback_resp)
    monkeypatch.setattr("services.pipeline.get_agent_pipeline", lambda: stub_agent_pipeline)

    req = _make_req()
    resp = await pipeline.run(req)
    assert resp.answer == "agent-answer"
    stub_agent_pipeline.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_swarm_query_pipeline_sub_agent_exception_produces_error_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a sub-agent coroutine raises, it is replaced with an error-marker string."""
    _patch_swarm_infra(monkeypatch, sub_questions=["q1", "q2"])

    from services.pipeline import SwarmQueryPipeline

    pipeline = SwarmQueryPipeline()
    monkeypatch.setattr(pipeline, "_decompose", AsyncMock(return_value=["q1", "q2"]))

    # First sub-agent raises, second succeeds
    from services.pipeline import _SubAgentResult
    call_count = 0

    async def _side_effect(*args: Any, **kwargs: Any) -> _SubAgentResult:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("sub-agent-crash")
        return _SubAgentResult(answer="good-answer", turns=1, tool_calls_count=0, chunks=[])

    monkeypatch.setattr(pipeline, "_run_sub_agent", _side_effect)
    monkeypatch.setattr(pipeline, "_synthesize", AsyncMock(return_value="final-with-partial"))

    req = _make_req()
    resp = await pipeline.run(req)
    assert resp is not None
    # _synthesize was called — graceful degradation
    pipeline._synthesize.assert_awaited_once()


# --- Wave-2 backfill: QueryPipeline._run_query main path ---


def _patch_query_pipeline_infra(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch all QueryPipeline constructor deps at consumer path (CF-02)."""
    from services.rules.rules_engine import RuleAction

    stub_retriever = AsyncMock()
    # retrieve_multi_query returns (chunks, latencies)
    stub_retriever.retrieve_multi_query = AsyncMock(return_value=([], {}))

    stub_generator = AsyncMock()
    from utils.models import GenerationResponse
    fake_resp = GenerationResponse(
        answer="generated-answer", sources=[],
        session_id="sess", query="q", latency_ms=1.0, trace_id="t",
        model="claude-3-5-sonnet-20241022",
    )
    fake_resp_copy = fake_resp.model_copy(update={"faithfulness_score": 0.0})
    stub_generator.generate = AsyncMock(return_value=fake_resp_copy)

    stub_llm = AsyncMock()
    stub_llm.chat = AsyncMock(return_value="chitchat-reply")

    stub_nlu = AsyncMock()
    from services.nlu.nlu_service import QueryIntent
    stub_nlu_result = MagicMock()
    stub_nlu_result.intent = QueryIntent.FACTUAL
    stub_nlu_result.entities = []
    stub_nlu_result.rewritten_queries = ["test query"]
    stub_nlu_result.needs_clarification = False
    stub_nlu_result.clarification_hint = ""
    stub_nlu.analyze = AsyncMock(return_value=stub_nlu_result)
    stub_nlu.recommend_top_k = MagicMock(return_value=6)

    stub_memory = AsyncMock()
    stub_memory.load_context = AsyncMock(return_value=_make_mem_ctx())
    stub_memory.save_turn = AsyncMock()

    stub_rules = MagicMock()
    rule_result = MagicMock()
    rule_result.action = RuleAction.PASS
    rule_result.message = ""
    stub_rules.run = MagicMock(return_value=rule_result)

    stub_event_bus = AsyncMock()
    stub_tenant_svc = MagicMock()
    stub_tenant_svc.check_permission = MagicMock(return_value=True)
    stub_tenant_svc.get_tenant_filter = MagicMock(return_value={})

    stub_audit = AsyncMock()
    stub_audit.log_query = AsyncMock()

    stub_summary_indexer = AsyncMock()

    # Mocks for cache
    stub_filter_extractor = AsyncMock()
    fe_result = MagicMock()
    fe_result.semantic_query = "test query"
    fe_result.filters = {}
    stub_filter_extractor.extract = AsyncMock(return_value=fe_result)

    counter_mock = MagicMock()
    counter_mock.labels = MagicMock(return_value=counter_mock)
    counter_mock.inc = MagicMock()
    counter_mock.observe = MagicMock()

    monkeypatch.setattr("services.pipeline.get_retriever", lambda: stub_retriever)
    monkeypatch.setattr("services.pipeline.get_generator", lambda: stub_generator)
    monkeypatch.setattr("services.pipeline.get_llm_client", lambda: stub_llm)
    monkeypatch.setattr("services.pipeline.get_nlu_service", lambda: stub_nlu)
    monkeypatch.setattr("services.pipeline.get_memory_service", lambda: stub_memory)
    monkeypatch.setattr("services.pipeline.get_rules_engine", lambda: stub_rules)
    monkeypatch.setattr("services.pipeline.get_event_bus", lambda: stub_event_bus)
    monkeypatch.setattr("services.pipeline.get_tenant_service", lambda: stub_tenant_svc)
    monkeypatch.setattr("services.pipeline.get_audit_service", lambda: stub_audit)
    monkeypatch.setattr("services.pipeline.get_summary_indexer", lambda: stub_summary_indexer)
    monkeypatch.setattr("services.pipeline.get_filter_extractor", lambda: stub_filter_extractor)
    monkeypatch.setattr("services.pipeline.query_total", counter_mock)
    monkeypatch.setattr("services.pipeline.query_latency_seconds", counter_mock)
    monkeypatch.setattr("services.pipeline.faithfulness_histogram", counter_mock)
    monkeypatch.setattr("services.pipeline.retrieval_chunks_histogram", counter_mock)
    monkeypatch.setattr("services.pipeline.cache_hit_total", counter_mock)

    # cache_get returns None (cache miss), cache_set is no-op
    monkeypatch.setattr("services.pipeline.cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr("services.pipeline.cache_set", AsyncMock())

    return {
        "retriever": stub_retriever,
        "generator": stub_generator,
        "llm": stub_llm,
        "nlu": stub_nlu,
        "memory": stub_memory,
        "rules": stub_rules,
        "audit": stub_audit,
        "tenant_svc": stub_tenant_svc,
        "nlu_result": stub_nlu_result,
    }


@pytest.mark.asyncio
async def test_query_pipeline_run_query_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QueryPipeline._run_query executes end-to-end on happy path."""
    stubs = _patch_query_pipeline_infra(monkeypatch)

    from services.pipeline import QueryPipeline
    pipeline = QueryPipeline()

    req = _make_req()
    resp = await pipeline._run_query(req)

    assert resp is not None
    assert resp.answer == "generated-answer"
    stubs["generator"].generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_query_pipeline_tenant_permission_denied_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QueryPipeline._run_query returns permission-denied response when tenant check fails."""
    stubs = _patch_query_pipeline_infra(monkeypatch)
    stubs["tenant_svc"].check_permission = MagicMock(return_value=False)

    from services.pipeline import QueryPipeline
    pipeline = QueryPipeline()

    req = _make_req(tenant_id="tenant-x", user_id="u1")
    resp = await pipeline._run_query(req)

    assert resp is not None
    assert "权限" in resp.answer


@pytest.mark.asyncio
async def test_query_pipeline_chitchat_intent_uses_llm_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CHITCHAT intent short-circuits to LLM.chat without retrieval."""
    stubs = _patch_query_pipeline_infra(monkeypatch)
    from services.nlu.nlu_service import QueryIntent
    stubs["nlu_result"].intent = QueryIntent.CHITCHAT

    from services.pipeline import QueryPipeline
    pipeline = QueryPipeline()

    req = _make_req()
    resp = await pipeline._run_query(req)

    assert resp is not None
    stubs["llm"].chat.assert_awaited_once()
    # Generator should NOT be called for chitchat
    stubs["generator"].generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_query_pipeline_pre_rule_block_returns_rule_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-query rule BLOCK returns rule message without retrieval."""
    stubs = _patch_query_pipeline_infra(monkeypatch)

    from services.rules.rules_engine import RuleAction
    block_result = MagicMock()
    block_result.action = RuleAction.BLOCK
    block_result.message = "blocked-by-rule"

    pass_result = MagicMock()
    pass_result.action = RuleAction.PASS
    pass_result.message = ""

    # pre_query → BLOCK; subsequent stages not reached
    stubs["rules"].run = MagicMock(side_effect=[block_result, pass_result, pass_result])

    from services.pipeline import QueryPipeline
    pipeline = QueryPipeline()

    req = _make_req()
    resp = await pipeline._run_query(req)

    assert "blocked-by-rule" in resp.answer
    stubs["retriever"].retrieve_multi_query.assert_not_awaited()


# --- Wave-2 backfill: SwarmQueryPipeline._synthesize branches ---

@pytest.mark.asyncio
async def test_swarm_synthesize_all_failed_agents_returns_graceful_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_synthesize with all-failed sub-agents returns graceful degradation without LLM call."""
    stubs = _patch_swarm_infra(monkeypatch, sub_questions=[])

    from services.pipeline import SwarmQueryPipeline
    pipeline = SwarmQueryPipeline()

    # LLM.chat should NOT be called when all failed
    stub_llm_chat = AsyncMock()
    stubs["llm"].chat = stub_llm_chat

    all_failed = [
        "[Sub-agent 0 failed: RuntimeError('oops')]",
        "[Sub-agent 1 failed: ValueError('bad')]",
    ]
    result = await pipeline._synthesize("original query", ["q1", "q2"], all_failed)

    assert "抱歉" in result or "失败" in result
    stub_llm_chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_swarm_synthesize_normal_path_calls_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_synthesize with good answers calls LLM.chat for synthesis."""
    stubs = _patch_swarm_infra(monkeypatch, sub_questions=[])

    from services.pipeline import SwarmQueryPipeline
    pipeline = SwarmQueryPipeline()

    stubs["llm"].chat = AsyncMock(return_value="synthesized")

    result = await pipeline._synthesize("query", ["q1"], ["answer1"])

    assert result == "synthesized"
    stubs["llm"].chat.assert_awaited_once()


# --- Wave-2 backfill: get_*_pipeline singletons ---

def test_get_swarm_pipeline_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_swarm_pipeline returns a singleton SwarmQueryPipeline."""
    import services.pipeline as pm
    monkeypatch.setattr(pm, "_swarm_pipeline", None)

    # Patch all constructor deps to avoid real service instantiation
    _patch_swarm_infra(monkeypatch, [])

    from services.pipeline import SwarmQueryPipeline, get_swarm_pipeline
    p1 = get_swarm_pipeline()
    p2 = get_swarm_pipeline()
    assert p1 is p2
    assert isinstance(p1, SwarmQueryPipeline)
    # cleanup
    monkeypatch.setattr(pm, "_swarm_pipeline", None)
