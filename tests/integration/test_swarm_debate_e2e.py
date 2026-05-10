# =============================================================================
# tests/integration/test_swarm_debate_e2e.py
# Phase 21 / Plan 21-05 — SC2 / CF-06 latency-contract integration test.
#
# Marked `pytest.mark.integration` (excluded from default pytest run via
# pytest.ini `addopts = -m "not integration"`) to keep wall-clock-sensitive
# assertions out of the per-task fast path. This file does NOT require
# OPENAI_API_KEY — it uses synthetic asyncio.sleep mocks at the
# _llm.chat / _run_sub_agent / _verifier.verify seams (per
# 21-VALIDATION.md Wave-0 latency-contract idiom mirrored from
# tests/unit/test_agent_sse.py:247-250). Run explicitly:
#
#   pytest tests/integration/test_swarm_debate_e2e.py -m integration
#
# Latency contract (CF-06 / SC2):
#   total ≤ max(peer_latency) + verifier_latency + small_overhead
# I.e. peers fan out concurrently → max(peer); verifier runs sequentially
# AFTER peers → +verifier; if peers ran serially, total would be sum(peer).
# =============================================================================
"""SC2 / CF-06 latency-contract integration test for SwarmQueryPipeline debate hop."""
from __future__ import annotations

import asyncio
import json as _json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.pipeline import SwarmQueryPipeline, _SubAgentResult
from utils.models import (
    AgentEvent,
    ChunkMetadata,
    GenerationRequest,
    RetrievedChunk,
    VerifierVerdict,
)

# Module-level marker: integration tier only.
pytestmark = [pytest.mark.integration]


def _chunk(chunk_id: str, doc_id: str = "d1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        content=f"content-{chunk_id}",
        metadata=ChunkMetadata(doc_id=doc_id, title="t"),
    )


def _build_swarm() -> SwarmQueryPipeline:
    """Construct SwarmQueryPipeline bypassing __init__ collaborators —
    matches mock_pipeline fixture from tests/unit/test_swarm_pipeline.py."""
    from services.memory.memory_service import MemoryContext
    from services.nlu.filter_extractor import ExtractionResult

    pipe = SwarmQueryPipeline.__new__(SwarmQueryPipeline)
    pipe._llm = MagicMock()
    pipe._llm.provider_name = "anthropic"
    pipe._llm.call_agentic_turn = AsyncMock()
    pipe._llm.chat = AsyncMock()
    pipe._retriever = MagicMock()
    pipe._retriever.retrieve = AsyncMock(return_value=([], {}))
    pipe._memory = MagicMock()
    pipe._memory.load_context = AsyncMock(
        return_value=MemoryContext(
            session_id="s", user_id="u", tenant_id="t",
            short_term=[], long_term_facts=[], user_profile=None,
        ),
    )
    pipe._memory.save_turn = AsyncMock()
    pipe._audit = MagicMock()
    pipe._audit.log_query = AsyncMock()
    pipe._audit.log = AsyncMock()
    pipe._tenant_svc = MagicMock()
    pipe._tenant_svc.get_tenant_filter = MagicMock(return_value={})
    pipe._filter_extractor = MagicMock()
    pipe._filter_extractor.extract = AsyncMock(
        return_value=ExtractionResult(filters={}, semantic_query=""),
    )
    pipe._verifier = MagicMock()
    pipe._verifier.verify = AsyncMock()
    return pipe


@pytest.mark.asyncio
async def test_swarm_debate_latency_bounded_by_max_peer_plus_verifier() -> None:
    """SC2 / CF-06 — verifier runs sequentially AFTER peers, peers run
    concurrently. With 3 peers x 0.3s + verifier 0.2s, total elapsed must be
    bounded by max(peer)=0.3 + verifier=0.2 = 0.5s + overhead, NOT
    sum(peer)+verifier=1.1s.

    The assertion `450 < elapsed_ms < 700` mirrors the latency-bound idiom
    at tests/unit/test_agent_sse.py:247-250.
    """
    pipe = _build_swarm()

    # Coordinator returns 3 sub-questions; synthesis returns instantly.
    pipe._llm.chat = AsyncMock(
        side_effect=[_json.dumps(["q1", "q2", "q3"]), "synth"],
    )

    # Each sub-agent sleeps 0.3s then returns a result with one chunk.
    async def _slow_sub_agent(idx: int, q: str, tf: dict, req: GenerationRequest) -> _SubAgentResult:
        await asyncio.sleep(0.3)
        return _SubAgentResult(
            answer=f"peer-{idx}", turns=1, tool_calls_count=0,
            chunks=[_chunk(f"c{idx}")],
        )

    pipe._run_sub_agent = _slow_sub_agent  # type: ignore[method-assign]

    # Verifier sleeps 0.2s then returns an `agree` verdict.
    async def _slow_verify(*, peer_results: Any, evidence: Any, user_query: str) -> VerifierVerdict:
        await asyncio.sleep(0.2)
        return VerifierVerdict(
            verdict="agree",
            evidence_chunk_ids=["c0"],
            reasoning="r",
            proposed_answer="ans",
            latency_ms=200,
        )

    pipe._verifier.verify = AsyncMock(side_effect=_slow_verify)

    req = GenerationRequest(
        query="多维度查询测试",
        top_k=5,
        swarm_mode=True,
        debate=True,
        tenant_id="t1",
        user_id="u1",
    )

    t0 = time.perf_counter()
    events: list[AgentEvent] = [evt async for evt in pipe.run_streaming(req)]
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # Latency bound: max(peer)=300 + verifier=200 = 500ms + overhead.
    # Sum bound (failure mode) would be 3*300 + 200 = 1100ms.
    assert 450 < elapsed_ms < 700, (
        f"max(peer)+verifier=500ms expected; got {elapsed_ms}ms "
        f"(sum-of-peers would be 1100ms — concurrency regression)"
    )

    # Sanity: SSE event sequence contains the verifier events + terminal.
    type_names = [type(e).__name__ for e in events]
    assert "VerifierStartEvent" in type_names
    assert "VerifierCompleteEvent" in type_names
    assert type_names[-1] == "SynthesizerFinalEvent"
