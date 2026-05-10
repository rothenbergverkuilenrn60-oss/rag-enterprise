"""Phase 21 AGENT-05 — Verifier unit tests (RESEARCH §tdd-2; covers B-01..B-15).

RED gate per Plan 21-03 Task 1. Each test fails on first run with
``ImportError: cannot import name 'Verifier'`` (file doesn't exist yet).

Mocks at the consumer path (``services.agent.verifier.<dep>``) per CONTEXT
§"Established Patterns" — tests never touch underlying provider SDKs directly.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from services.pipeline import _SubAgentResult
from utils.models import (
    AgenticTurn,
    ChunkMetadata,
    RetrievedChunk,
    VerifierVerdict,  # noqa: F401  # plan acceptance ≥3 data-shape imports
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _chunk(chunk_id: str, content: str = "c") -> RetrievedChunk:
    md = ChunkMetadata(doc_id="d1", title="t")
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="d1",
        content=content,
        metadata=md,
    )


def _peer(answer: str = "a", chunks: list[RetrievedChunk] | None = None) -> _SubAgentResult:
    return _SubAgentResult(
        answer=answer,
        turns=1,
        tool_calls_count=0,
        chunks=chunks or [],
    )


def _turn(text: str = "") -> AgenticTurn:
    return AgenticTurn(
        text=text,
        tool_calls=[],
        stop_reason="text_only",
        raw_assistant_msg={"role": "assistant", "content": text},
        usage_input_tokens=0,
        usage_output_tokens=0,
    )


def _verdict_json(
    verdict: str = "agree",
    evidence_chunk_ids: list[str] | None = None,
    proposed_answer: str = "ans",
    reasoning: str = "r",
    latency_ms: int = 0,
) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "evidence_chunk_ids": evidence_chunk_ids if evidence_chunk_ids is not None else ["c1"],
            "reasoning": reasoning,
            "proposed_answer": proposed_answer,
            "latency_ms": latency_ms,
        }
    )


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_verifier(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a Verifier with the LLM dep replaced by AsyncMock at the consumer path."""
    from services.agent.verifier import Verifier
    import services.agent.verifier as vmod

    fake_llm = MagicMock()
    fake_llm.call_agentic_turn = AsyncMock()
    monkeypatch.setattr("services.agent.verifier.get_llm_client", lambda: fake_llm)
    # Force settings.verifier_provider to None so _resolve_llm takes the default branch.
    monkeypatch.setattr(vmod.settings, "verifier_provider", None, raising=False)
    v = Verifier()
    # Ensure the post-init mock is in place (defensive; _resolve_llm should have set it).
    v._llm = fake_llm
    return v


# -----------------------------------------------------------------------------
# Tests — RESEARCH §tdd-2 cases (B-01..B-15)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_happy_agree_path(mock_verifier: Any) -> None:
    """B-01 — agree verdict + non-empty evidence → returned as-is."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text=_verdict_json("agree", ["c1", "c2"]))
    )
    verdict = await mock_verifier.verify(
        peer_results=[_peer()],
        evidence=[_chunk("c1"), _chunk("c2")],
        user_query="q",
    )
    assert verdict.verdict == "agree"
    assert verdict.evidence_chunk_ids == ["c1", "c2"]
    assert verdict.proposed_answer == "ans"


@pytest.mark.asyncio
async def test_verify_forced_disagree_on_empty_evidence(mock_verifier: Any) -> None:
    """B-02 / CF-04 — agree with empty evidence_chunk_ids → forced to disagree INSIDE verify()."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text=_verdict_json("agree", []))
    )
    verdict = await mock_verifier.verify(
        peer_results=[_peer()],
        evidence=[_chunk("c1")],
        user_query="q",
    )
    assert verdict.verdict == "disagree"   # forced override per Pitfall P-02
    assert verdict.evidence_chunk_ids == []


@pytest.mark.asyncio
async def test_verify_honest_disagree_passes_through(mock_verifier: Any) -> None:
    """B-03 — disagree verdict from LLM passes through without modification."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text=_verdict_json("disagree", ["c1"]))
    )
    verdict = await mock_verifier.verify(
        peer_results=[_peer()],
        evidence=[_chunk("c1")],
        user_query="q",
    )
    assert verdict.verdict == "disagree"
    assert verdict.evidence_chunk_ids == ["c1"]


@pytest.mark.asyncio
async def test_verify_parses_markdown_fenced_json(mock_verifier: Any) -> None:
    """B-05 — markdown-fenced JSON: re.search greedy capture extracts the {...} block."""
    text = "Here is the verdict:\n```json\n" + _verdict_json("agree", ["c1"]) + "\n```\nDone."
    mock_verifier._llm.call_agentic_turn = AsyncMock(return_value=_turn(text=text))
    verdict = await mock_verifier.verify(
        peer_results=[_peer()],
        evidence=[_chunk("c1")],
        user_query="q",
    )
    assert verdict.verdict == "agree"


@pytest.mark.asyncio
async def test_verify_parses_prose_prefixed_json(mock_verifier: Any) -> None:
    """B-06 — prose-prefixed JSON: re.search picks up the {...} block from anywhere."""
    text = "Sure, here you go: " + _verdict_json("agree", ["c1"])
    mock_verifier._llm.call_agentic_turn = AsyncMock(return_value=_turn(text=text))
    verdict = await mock_verifier.verify(
        peer_results=[_peer()],
        evidence=[_chunk("c1")],
        user_query="q",
    )
    assert verdict.verdict == "agree"


@pytest.mark.asyncio
async def test_verify_raises_on_invalid_json(mock_verifier: Any) -> None:
    """B-07 — invalid JSON raises ValueError (caught at caller per D-06)."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text="{not really json}")
    )
    with pytest.raises((ValueError, ValidationError)):
        await mock_verifier.verify(
            peer_results=[_peer()],
            evidence=[_chunk("c1")],
            user_query="q",
        )


@pytest.mark.asyncio
async def test_verify_raises_on_shape_mismatch(mock_verifier: Any) -> None:
    """B-08 — JSON parses but missing required fields → pydantic.ValidationError."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text='{"verdict":"agree"}')
    )
    with pytest.raises(ValidationError):
        await mock_verifier.verify(
            peer_results=[_peer()],
            evidence=[_chunk("c1")],
            user_query="q",
        )


@pytest.mark.asyncio
async def test_verify_propagates_llm_exception(mock_verifier: Any) -> None:
    """B-13 — LLM raises → Verifier propagates (no internal except per D-06)."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(side_effect=RuntimeError("boom"))
    with pytest.raises(RuntimeError) as exc_info:
        await mock_verifier.verify(
            peer_results=[_peer()],
            evidence=[_chunk("c1")],
            user_query="q",
        )
    assert "boom" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verdict_value,evidence_ids",
    [("agree", ["c1"]), ("disagree", ["c1"])],
)
async def test_verify_proposed_answer_always_populated(
    mock_verifier: Any, verdict_value: str, evidence_ids: list[str]
) -> None:
    """B-01..B-03 / D-02 — proposed_answer non-empty for both verdicts."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text=_verdict_json(verdict_value, evidence_ids, proposed_answer="non-empty"))
    )
    verdict = await mock_verifier.verify(
        peer_results=[_peer()],
        evidence=[_chunk("c1")],
        user_query="q",
    )
    assert verdict.proposed_answer != ""


@pytest.mark.asyncio
async def test_verify_defensive_chunk_id_filter(mock_verifier: Any) -> None:
    """B-09 — chunk_ids not in supplied evidence are dropped (Claude's-discretion bullet)."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text=_verdict_json("disagree", ["c1", "c99", "c2"]))
    )
    verdict = await mock_verifier.verify(
        peer_results=[_peer()],
        evidence=[_chunk("c1"), _chunk("c2")],
        user_query="q",
    )
    assert verdict.evidence_chunk_ids == ["c1", "c2"]   # c99 dropped (not in evidence)


@pytest.mark.asyncio
async def test_verify_latency_ms_is_wallclock(mock_verifier: Any) -> None:
    """B-14 — wall-clock measurement overrides any LLM-emitted latency_ms."""

    async def slow_call(**_: Any) -> AgenticTurn:
        await asyncio.sleep(0.01)
        return _turn(text=_verdict_json("agree", ["c1"], latency_ms=999))

    mock_verifier._llm.call_agentic_turn = AsyncMock(side_effect=slow_call)
    verdict = await mock_verifier.verify(
        peer_results=[_peer()],
        evidence=[_chunk("c1")],
        user_query="q",
    )
    assert verdict.latency_ms < 999   # wall-clock value is small (~10ms), not 999


# -----------------------------------------------------------------------------
# Structural tests (SC1 sampling rows + AGENT-14 sub-claim + _resolve_llm branches)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_calls_text_only_with_tools_empty(mock_verifier: Any) -> None:
    """SC1 sampling — verifier invokes call_agentic_turn with tools=[] (CF-03 enforcement)."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text=_verdict_json("agree", ["c1"]))
    )
    await mock_verifier.verify(
        peer_results=[_peer()],
        evidence=[_chunk("c1")],
        user_query="q",
    )
    kwargs = mock_verifier._llm.call_agentic_turn.call_args.kwargs
    assert kwargs["tools"] == []
    assert kwargs.get("parallel_tool_calls") is False


def test_system_prompt_forbids_invention() -> None:
    """SC1 sampling — _VERIFIER_SYSTEM forbids inventing facts (Candidate A or B)."""
    from services.agent.verifier import _VERIFIER_SYSTEM

    candidate_a_match = "不得编造" in _VERIFIER_SYSTEM
    candidate_b_match = ("forbid" in _VERIFIER_SYSTEM.lower()) and ("invent" in _VERIFIER_SYSTEM.lower())
    assert candidate_a_match or candidate_b_match


@pytest.mark.asyncio
async def test_verify_makes_single_llm_call(mock_verifier: Any) -> None:
    """AGENT-14 sub-claim — verifier issues exactly one LLM call regardless of peer count."""
    mock_verifier._llm.call_agentic_turn = AsyncMock(
        return_value=_turn(text=_verdict_json("agree", ["c1"]))
    )
    await mock_verifier.verify(
        peer_results=[_peer(), _peer(), _peer()],
        evidence=[_chunk("c1")],
        user_query="q",
    )
    assert mock_verifier._llm.call_agentic_turn.await_count == 1


def test_resolve_llm_anthropic_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """B-11 — verifier_provider="anthropic" → AnthropicLLMClient instantiated."""
    from services.agent.verifier import Verifier
    import services.agent.verifier as vmod

    fake_anthropic_cls = MagicMock()
    monkeypatch.setattr("services.agent.verifier.AnthropicLLMClient", fake_anthropic_cls)
    monkeypatch.setattr(vmod.settings, "verifier_provider", "anthropic", raising=False)

    Verifier()
    fake_anthropic_cls.assert_called_once()


def test_resolve_llm_openai_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """B-12 — verifier_provider="openai" → OpenAILLMClient instantiated."""
    from services.agent.verifier import Verifier
    import services.agent.verifier as vmod

    fake_openai_cls = MagicMock()
    monkeypatch.setattr("services.agent.verifier.OpenAILLMClient", fake_openai_cls)
    monkeypatch.setattr(vmod.settings, "verifier_provider", "openai", raising=False)

    Verifier()
    fake_openai_cls.assert_called_once()
