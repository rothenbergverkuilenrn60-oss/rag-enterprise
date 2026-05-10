# =============================================================================
# tests/unit/test_swarm_pipeline.py
# Phase 12-03 Task 2 — SwarmQueryPipeline unit contracts (AGENT-03)
# Covers AGENT-03 acceptance criteria 1–7 + Pitfall 4 (coordinator main model).
# =============================================================================
"""Unit tests for SwarmQueryPipeline (AGENT-03)."""
from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.audit.audit_service import AuditEvent
from services.memory.memory_service import MemoryContext
from services.pipeline import SwarmQueryPipeline, _SubAgentResult
from utils.models import (
    AgenticTurn,
    ChunkMetadata,
    GenerationRequest,
    GenerationResponse,
    RetrievedChunk,
    ToolCall,
    VerifierVerdict,
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


# ─── Phase 21 — _synthesize divergence branch ─────────────────────────────
#
# Plan 21-04 (TDD): _synthesize gains an optional `verifier_verdict` kwarg
# (D-04). When verdict == "disagree", route through `_format_disagree` which
# emits the locked D-03 Chinese banner using `_DISAGREE_BANNER_TEMPLATE`
# (Pitfall P-08 single-symbol-edit). Default / agree paths stay BYTE-IDENTICAL
# to v1.4 swarm (SC5/CF-08). Disagree branch makes ZERO additional LLM calls.

# Verbatim D-03 banner (locked-string contract; the test below proves
# byte-identity against this string).
_DISAGREE_BANNER_LOCKED: str = (
    "⚠️ 子代理间存在分歧（{N} 个同伴中的 {M} 个提出差异回答）。"
    "以上回答基于验证者引用的证据（{chunk_count} 个块）。"
)


def _verdict(
    verdict: str = "disagree",
    proposed_answer: str = "verifier ans",
    evidence_chunk_ids: list[str] | None = None,
    reasoning: str = "r",
) -> VerifierVerdict:
    return VerifierVerdict(
        verdict=verdict,  # type: ignore[arg-type]
        evidence_chunk_ids=evidence_chunk_ids if evidence_chunk_ids is not None else ["c1", "c2"],
        reasoning=reasoning,
        proposed_answer=proposed_answer,
        latency_ms=100,
    )


def _peer(answer: str = "a", chunks: list[RetrievedChunk] | None = None) -> _SubAgentResult:
    return _SubAgentResult(answer=answer, turns=1, tool_calls_count=0, chunks=chunks or [])


# Case 1 (B-24, SC5) — default kwarg = byte-identity with v1.4 swarm.
@pytest.mark.unit
@pytest.mark.asyncio
async def test_synthesize_default_kwarg_byte_identical(
    mock_pipeline: SwarmQueryPipeline,
) -> None:
    """`verifier_verdict=None` (default) MUST hit the existing synthesis body
    byte-identically: exactly one `_llm.chat` await, returns its output."""
    # Inspect-guard: if the kwarg is absent from the signature, the test fails
    # loudly even if the behavioural path would pass vacuously.
    assert "verifier_verdict" in inspect.signature(SwarmQueryPipeline._synthesize).parameters

    mock_pipeline._llm.chat = AsyncMock(return_value="synthesized output")
    result = await mock_pipeline._synthesize("q", ["sq1"], ["a1"])

    assert mock_pipeline._llm.chat.await_count == 1
    assert result == "synthesized output"


# Case 2 (B-25) — agree-with-evidence falls through to standard synthesis.
@pytest.mark.unit
@pytest.mark.asyncio
async def test_synthesize_agree_kwarg_byte_identical(
    mock_pipeline: SwarmQueryPipeline,
) -> None:
    """`verifier_verdict.verdict == "agree"` MUST behave exactly like the
    default-kwarg path (consensus answer comes from `_llm.chat`)."""
    mock_pipeline._llm.chat = AsyncMock(return_value="synthesized output")
    result = await mock_pipeline._synthesize(
        "q", ["sq1"], ["a1"], verifier_verdict=_verdict(verdict="agree"),
    )

    assert mock_pipeline._llm.chat.await_count == 1
    assert result == "synthesized output"


# Case 3 (B-26) — disagree path: ZERO LLM calls, returns `_format_disagree(...)`.
@pytest.mark.unit
@pytest.mark.asyncio
async def test_synthesize_disagree_uses_proposed_answer_no_llm(
    mock_pipeline: SwarmQueryPipeline,
) -> None:
    """Disagree dispatch MUST NOT touch `_llm.chat` and MUST surface the
    verifier's proposed_answer + the locked banner with N=M=len(answers)."""
    # AsyncMock side_effect raises if `_llm.chat` is awaited — proves zero calls.
    mock_pipeline._llm.chat = AsyncMock(
        side_effect=AssertionError("must NOT call _llm.chat on disagree"),
    )
    result = await mock_pipeline._synthesize(
        "q",
        ["sq1", "sq2"],
        ["a1", "a2"],
        verifier_verdict=_verdict(
            verdict="disagree",
            proposed_answer="evidence-led answer",
            evidence_chunk_ids=["c1", "c2", "c3"],
        ),
    )

    # `proposed_answer` is the user-visible answer, prefix.
    assert result.startswith("evidence-led answer")
    # Locked Chinese banner present.
    assert "⚠️ 子代理间存在分歧" in result
    # chunk_count substitution from len(verdict.evidence_chunk_ids).
    assert "3 个块" in result
    # peer_count == len(answers) → N=M=2.
    assert "2 个同伴中的 2 个提出差异回答" in result


# Case 4 (B-27) — exact-template substitution; LOCKED-string contract.
@pytest.mark.unit
def test_format_disagree_exact_template_substitution() -> None:
    """`_format_disagree` returns EXACT byte-identical output against the locked
    D-03 string. Failing test surfaces any future template drift."""
    out = SwarmQueryPipeline._format_disagree(
        _verdict(verdict="disagree", proposed_answer="ans", evidence_chunk_ids=["c1"]),
        sub_results=[_peer(), _peer(), _peer()],
    )
    assert out == (
        "ans\n\n"
        "⚠️ 子代理间存在分歧（3 个同伴中的 3 个提出差异回答）。"
        "以上回答基于验证者引用的证据（1 个块）。"
    )


# Case 5 (Pitfall P-08) — module-level constant exists with expected placeholders.
@pytest.mark.unit
def test_format_disagree_module_constant_present() -> None:
    """`_DISAGREE_BANNER_TEMPLATE` MUST live at module level so any future
    v1.6+ i18n routing change is a single-symbol edit (Pitfall P-08)."""
    from services.pipeline import _DISAGREE_BANNER_TEMPLATE

    assert isinstance(_DISAGREE_BANNER_TEMPLATE, str)
    assert "{N}" in _DISAGREE_BANNER_TEMPLATE
    assert "{M}" in _DISAGREE_BANNER_TEMPLATE
    assert "{chunk_count}" in _DISAGREE_BANNER_TEMPLATE
    # Cross-check: byte-identity against the locked D-03 reference string.
    assert _DISAGREE_BANNER_TEMPLATE == _DISAGREE_BANNER_LOCKED


# ─── Phase 21 — debate hop + run_streaming + audit + latency ──────────────
#
# Plan 21-05 (TDD): SwarmQueryPipeline gains
#   - self._verifier = Verifier() (in __init__)
#   - run_streaming(req) AS PRIMARY async generator (W5/W8 fix —
#     trace_id + seq_counter LOCAL per call, no instance buffer state)
#   - thin run(req) wrapper that drains run_streaming and returns
#     GenerationResponse (backward-compat)
#   - audit detail extension with conditional `agent_05` namespace (D-11)
# 8 unit cases below; 1 route test in tests/unit/test_agent_stream_route.py;
# 1 latency-contract integration case in tests/integration/test_swarm_debate_e2e.py.

import json as _json  # noqa: E402

from utils.models import (  # noqa: E402
    AgentEvent,
    SynthesizerFinalEvent,
    VerifierCompleteEvent,
    VerifierDisagreementEvent,
)


def _wire_swarm_for_debate(
    pipe: SwarmQueryPipeline,
    *,
    sub_questions: tuple[str, ...] = ("q1", "q2"),
    peer_chunks: list[list[RetrievedChunk]] | None = None,
    synthesis_text: str = "synth",
) -> None:
    """Wire mock pipeline so SwarmQueryPipeline.run_streaming() reaches the verifier hop.

    - Patches `_llm.chat` to (decompose-payload, synthesis-text) side-effect.
    - Replaces `_run_sub_agent` on the instance with a stub that returns
      pre-canned `_SubAgentResult` values per sub-question.
    """
    if peer_chunks is None:
        peer_chunks = [
            [_chunk("c1"), _chunk("c2")],
            [_chunk("c2"), _chunk("c3")],
        ]
    decompose_payload = _json.dumps(list(sub_questions))
    pipe._llm.chat = AsyncMock(side_effect=[decompose_payload, synthesis_text])

    async def _fake_sub_agent(idx: int, q: str, tf: dict, req: GenerationRequest) -> _SubAgentResult:
        return _SubAgentResult(
            answer=f"peer-{idx}-answer",
            turns=1,
            tool_calls_count=0,
            chunks=peer_chunks[idx % len(peer_chunks)],
        )

    pipe._run_sub_agent = _fake_sub_agent  # type: ignore[method-assign]


@pytest.fixture
def mock_swarm_with_verifier(mock_pipeline: SwarmQueryPipeline) -> SwarmQueryPipeline:
    """mock_pipeline + a mock _verifier (set on instance because __init__ is bypassed)."""
    mock_pipeline._verifier = MagicMock()  # type: ignore[attr-defined]
    mock_pipeline._verifier.verify = AsyncMock()  # type: ignore[attr-defined]
    return mock_pipeline


# Case 1 (B-16 / SC5 / Pitfall P-04) — debate=False is byte-identical to v1.4.
@pytest.mark.unit
@pytest.mark.asyncio
async def test_debate_false_byte_identical_to_v13_swarm(
    mock_swarm_with_verifier: SwarmQueryPipeline, gen_req: GenerationRequest,
) -> None:
    """`req.debate=False` MUST NOT invoke the verifier, MUST NOT add `agent_05`
    to audit detail, and MUST NOT call `_dedup_chunks` against swarm chunks
    (proxied via _llm.chat call_count == 2 — decompose + synth only)."""
    req = gen_req.model_copy(update={"debate": False})
    _wire_swarm_for_debate(mock_swarm_with_verifier)

    await mock_swarm_with_verifier.run(req)

    # Verifier never invoked.
    assert mock_swarm_with_verifier._verifier.verify.await_count == 0
    # Decompose + synth = 2 chat calls; no extra calls (e.g. for verifier path).
    assert mock_swarm_with_verifier._llm.chat.await_count == 2
    # Audit detail has NO `agent_05` key.
    audit_event = mock_swarm_with_verifier._audit.log.await_args.args[0]
    assert "agent_05" not in audit_event.detail


# Case 2 (B-17 / tdd-4 case 2) — debate=True happy agree path.
@pytest.mark.unit
@pytest.mark.asyncio
async def test_debate_true_happy_agree_emits_start_and_complete(
    mock_swarm_with_verifier: SwarmQueryPipeline, gen_req: GenerationRequest,
) -> None:
    """`agree` verdict → VerifierStartEvent + VerifierCompleteEvent + terminal
    SynthesizerFinalEvent. NO disagreement event. Single verifier call."""
    req = gen_req.model_copy(update={"debate": True})
    _wire_swarm_for_debate(mock_swarm_with_verifier)
    mock_swarm_with_verifier._verifier.verify = AsyncMock(
        return_value=_verdict(verdict="agree", evidence_chunk_ids=["c1", "c2"]),
    )

    events: list[AgentEvent] = [
        evt async for evt in mock_swarm_with_verifier.run_streaming(req)
    ]

    type_names = [type(e).__name__ for e in events]
    assert "VerifierStartEvent" in type_names
    assert "VerifierCompleteEvent" in type_names
    assert "VerifierDisagreementEvent" not in type_names
    # Terminal event invariant (CF-07).
    assert isinstance(events[-1], SynthesizerFinalEvent)
    # Verifier called exactly once (CF-06 — single sequential call).
    assert mock_swarm_with_verifier._verifier.verify.await_count == 1
    # Decompose + synth — verifier hop did NOT trigger an extra _llm.chat call.
    assert mock_swarm_with_verifier._llm.chat.await_count == 2
    # Audit detail has the agent_05 namespace.
    audit_event = mock_swarm_with_verifier._audit.log.await_args.args[0]
    assert audit_event.detail["agent_05"]["verifier_used"] is True
    assert audit_event.detail["agent_05"]["forced_disagree"] is False
    assert audit_event.detail["agent_05"]["verifier_failed"] is False
    # W5/W8 assertion: every event shares one trace_id local per call.
    trace_ids = {e.trace_id for e in events}
    assert len(trace_ids) == 1
    assert next(iter(trace_ids))  # non-empty


# Case 3 (B-18 / tdd-4 case 3) — disagree with non-empty evidence → peers_diverge.
@pytest.mark.unit
@pytest.mark.asyncio
async def test_debate_true_disagree_emits_peers_diverge(
    mock_swarm_with_verifier: SwarmQueryPipeline, gen_req: GenerationRequest,
) -> None:
    """`disagree` + non-empty evidence_chunk_ids → reason='peers_diverge'.
    `_synthesize` short-circuits via D-04 _format_disagree (zero synth chat call)."""
    req = gen_req.model_copy(update={"debate": True})
    _wire_swarm_for_debate(mock_swarm_with_verifier)
    mock_swarm_with_verifier._verifier.verify = AsyncMock(
        return_value=_verdict(
            verdict="disagree",
            evidence_chunk_ids=["c1", "c2"],
            proposed_answer="ans",
        ),
    )

    events: list[AgentEvent] = [
        evt async for evt in mock_swarm_with_verifier.run_streaming(req)
    ]

    disagreement_events = [e for e in events if isinstance(e, VerifierDisagreementEvent)]
    assert len(disagreement_events) == 1
    assert disagreement_events[0].reason == "peers_diverge"
    assert list(disagreement_events[0].evidence_chunk_ids) == ["c1", "c2"]

    complete_events = [e for e in events if isinstance(e, VerifierCompleteEvent)]
    assert len(complete_events) == 1
    assert complete_events[0].verdict == "disagree"

    assert isinstance(events[-1], SynthesizerFinalEvent)
    assert events[-1].answer.startswith("ans")
    # _synthesize short-circuits (no synth chat call); only decompose chat call.
    assert mock_swarm_with_verifier._llm.chat.await_count == 1


# Case 4 (B-19 / tdd-4 case 4 / D-11) — empty-evidence forced-disagree.
@pytest.mark.unit
@pytest.mark.asyncio
async def test_debate_true_forced_disagree_emits_forced_no_evidence(
    mock_swarm_with_verifier: SwarmQueryPipeline, gen_req: GenerationRequest,
) -> None:
    """`disagree` + empty evidence_chunk_ids → reason='forced_no_evidence'
    (CF-04 forced-disagree was applied INSIDE Verifier.verify per Plan 03)."""
    req = gen_req.model_copy(update={"debate": True})
    _wire_swarm_for_debate(mock_swarm_with_verifier)
    mock_swarm_with_verifier._verifier.verify = AsyncMock(
        return_value=_verdict(
            verdict="disagree",
            evidence_chunk_ids=[],
            proposed_answer="ans",
        ),
    )

    events: list[AgentEvent] = [
        evt async for evt in mock_swarm_with_verifier.run_streaming(req)
    ]

    disagreement_events = [e for e in events if isinstance(e, VerifierDisagreementEvent)]
    assert len(disagreement_events) == 1
    assert disagreement_events[0].reason == "forced_no_evidence"

    audit_event = mock_swarm_with_verifier._audit.log.await_args.args[0]
    assert audit_event.detail["agent_05"]["forced_disagree"] is True

    # Final answer banner uses chunk_count=0 substitution.
    assert isinstance(events[-1], SynthesizerFinalEvent)
    assert "0 个块" in events[-1].answer


# Case 5 (B-20 / tdd-4 case 5 / CF-09 / D-06) — verifier raises → graceful degrade.
@pytest.mark.unit
@pytest.mark.asyncio
async def test_debate_true_verifier_raises_emits_verifier_failed_and_degrades(
    mock_swarm_with_verifier: SwarmQueryPipeline, gen_req: GenerationRequest,
) -> None:
    """`BaseException` from verify() → VerifierDisagreementEvent
    (reason='verifier_failed', error_type='RuntimeError') + terminal
    SynthesizerFinalEvent + fall-through to non-debate _synthesize path."""
    req = gen_req.model_copy(update={"debate": True})
    _wire_swarm_for_debate(mock_swarm_with_verifier)
    mock_swarm_with_verifier._verifier.verify = AsyncMock(
        side_effect=RuntimeError("boom"),
    )

    events: list[AgentEvent] = [
        evt async for evt in mock_swarm_with_verifier.run_streaming(req)
    ]

    type_names = [type(e).__name__ for e in events]
    # VerifierStartEvent emitted before the failed verify call.
    assert type_names.count("VerifierStartEvent") == 1
    # VerifierDisagreementEvent with reason='verifier_failed' + error_type.
    failed_events = [
        e for e in events
        if isinstance(e, VerifierDisagreementEvent) and e.reason == "verifier_failed"
    ]
    assert len(failed_events) == 1
    assert failed_events[0].error_type == "RuntimeError"
    assert failed_events[0].summary == "boom"
    # NO VerifierCompleteEvent on failure path.
    assert "VerifierCompleteEvent" not in type_names
    # Terminal event present (CF-07 — graceful degrade still emits terminal).
    assert isinstance(events[-1], SynthesizerFinalEvent)

    audit_event = mock_swarm_with_verifier._audit.log.await_args.args[0]
    assert audit_event.detail["agent_05"]["verifier_failed"] is True

    # _synthesize fell through to standard consensus path (decompose + synth).
    assert mock_swarm_with_verifier._llm.chat.await_count == 2


# Case 6 (B-22 / tdd-4 case 7) — audit detail superset + JSON-native (P-07).
@pytest.mark.unit
@pytest.mark.asyncio
async def test_debate_true_audit_detail_superset_with_agent_05(
    mock_swarm_with_verifier: SwarmQueryPipeline, gen_req: GenerationRequest,
) -> None:
    """Happy `agree` path: audit detail keys include all v1.4 swarm keys
    PLUS `agent_05` namespace; all values JSON-native (P-07 round-trip)."""
    req = gen_req.model_copy(update={"debate": True})
    _wire_swarm_for_debate(mock_swarm_with_verifier)
    mock_swarm_with_verifier._verifier.verify = AsyncMock(
        return_value=_verdict(verdict="agree", evidence_chunk_ids=["c1"]),
    )

    await mock_swarm_with_verifier.run(req)

    audit_event = mock_swarm_with_verifier._audit.log.await_args.args[0]
    detail = audit_event.detail

    # v1.4 swarm keys still present.
    base_keys = {
        "latency_ms", "sources_count", "query_len", "intent",
        "swarm_n", "per_agent_turns", "per_agent_tool_calls",
        "swarm_latency_ms", "synthesis_latency_ms",
    }
    assert base_keys.issubset(set(detail.keys()))
    assert "agent_05" in detail

    # agent_05 sub-keys.
    agent_05 = detail["agent_05"]
    sub_keys = {
        "verifier_used", "verifier_failed", "forced_disagree",
        "verifier_latency_ms", "verifier_model", "evidence_chunk_count",
    }
    assert sub_keys.issubset(set(agent_05.keys()))

    # JSON-native round-trip (P-07 — a stray Pydantic model would crash here).
    _json.dumps(detail)


# Case 7 (B-23 / tdd-4 case 8 / Pitfall P-03) — verifier sees deduped evidence.
@pytest.mark.unit
@pytest.mark.asyncio
async def test_verifier_sees_deduped_evidence(
    mock_swarm_with_verifier: SwarmQueryPipeline, gen_req: GenerationRequest,
) -> None:
    """Peer chunks overlap (peer 0 → [c1,c2], peer 1 → [c2,c3]).
    Verifier `evidence` MUST be deduped: 3 chunks, first-occurrence order."""
    req = gen_req.model_copy(update={"debate": True})
    _wire_swarm_for_debate(
        mock_swarm_with_verifier,
        peer_chunks=[
            [_chunk("c1"), _chunk("c2")],
            [_chunk("c2"), _chunk("c3")],
        ],
    )
    mock_swarm_with_verifier._verifier.verify = AsyncMock(
        return_value=_verdict(verdict="agree", evidence_chunk_ids=["c1"]),
    )

    await mock_swarm_with_verifier.run(req)

    call_kwargs = mock_swarm_with_verifier._verifier.verify.call_args.kwargs
    evidence = call_kwargs["evidence"]
    assert len(evidence) == 3
    assert [c.chunk_id for c in evidence] == ["c1", "c2", "c3"]


# Case 8 (CF-07 / SC3) — synthesizer.final terminal in all 4 debate paths.
@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verdict_kind",
    ["agree", "disagree_evidence", "disagree_forced", "raises"],
)
async def test_synthesizer_final_terminal_in_all_debate_paths(
    mock_swarm_with_verifier: SwarmQueryPipeline,
    gen_req: GenerationRequest,
    verdict_kind: str,
) -> None:
    """SynthesizerFinalEvent is the terminal event AND has the maximum seq
    in every one of the 4 debate paths (agree, disagree-with-evidence,
    forced-disagree, verifier-raises)."""
    req = gen_req.model_copy(update={"debate": True})
    _wire_swarm_for_debate(mock_swarm_with_verifier)

    if verdict_kind == "agree":
        mock_swarm_with_verifier._verifier.verify = AsyncMock(
            return_value=_verdict(verdict="agree", evidence_chunk_ids=["c1"]),
        )
    elif verdict_kind == "disagree_evidence":
        mock_swarm_with_verifier._verifier.verify = AsyncMock(
            return_value=_verdict(verdict="disagree", evidence_chunk_ids=["c1", "c2"]),
        )
    elif verdict_kind == "disagree_forced":
        mock_swarm_with_verifier._verifier.verify = AsyncMock(
            return_value=_verdict(verdict="disagree", evidence_chunk_ids=[]),
        )
    elif verdict_kind == "raises":
        mock_swarm_with_verifier._verifier.verify = AsyncMock(
            side_effect=RuntimeError("boom"),
        )
    else:
        raise AssertionError(f"unknown verdict_kind={verdict_kind!r}")

    events: list[AgentEvent] = [
        evt async for evt in mock_swarm_with_verifier.run_streaming(req)
    ]

    assert isinstance(events[-1], SynthesizerFinalEvent)
    # Terminal-by-seq: max seq value belongs to the terminal event.
    max_seq = max(e.seq for e in events)
    assert events[-1].seq == max_seq
