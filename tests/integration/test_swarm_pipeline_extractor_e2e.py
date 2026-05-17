"""Phase 23 / MEM-04 — SwarmQueryPipeline end-to-end extractor integration.

T2 per eng-review 2026-05-16: closes the ``inspect.getsource`` structural-check
fallback used in Plan 05 unit test ``test_swarm_run_dispatches_extractor``.
That unit test only proved the literal string ``dispatch_extraction(`` appears
in the source — it did NOT prove the call actually fires at runtime with the
correct kwargs. This integration test closes the gap with real PG + real
``asyncio.create_task`` + behavioral fact-persistence assertions.

Markers: ``integration`` + ``pgvector``. SKIPs gracefully when PG unavailable.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import asyncio
import re
import time
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from services.memory.memory_service import LongTermMemory
from utils.models import (
    AgenticTurn,
    GenerationRequest,
    GenerationResponse,
)

pytestmark = [pytest.mark.integration, pytest.mark.pgvector]


# -----------------------------------------------------------------------------
# Minimal swarm pipeline harness.
#
# SwarmQueryPipeline.run delegates to _run_with_state when N>1 (which is where
# the Plan 23-05 dispatch_extraction wire-in lives). To force the N>1 path:
#   1. patch _decompose → ["q1", "q2"] (2 sub-questions, not 1, so no N=1
#      short-circuit to AgentQueryPipeline)
#   2. patch _run_sub_agent → return canned _SubAgentResult
#   3. patch _synthesize → return deterministic final answer
#
# This keeps the run-loop body itself intact (save_turn + dispatch_extraction
# both still execute via the real call sites — we are NOT mocking those).
# -----------------------------------------------------------------------------


async def _build_minimal_swarm_pipeline(
    pgvector_pool: asyncpg.Pool,
    monkeypatch: pytest.MonkeyPatch,
    final_answer: str = "Sure, React it is.",
):
    """Return a SwarmQueryPipeline whose collaborators are stubbed but whose
    _run_with_state body (and therefore dispatch_extraction call) is untouched.
    """
    # Redis-dependent helpers → no-op (no localhost:6379 timeout).
    monkeypatch.setattr(
        "services.pipeline._ab_assign_and_map",
        AsyncMock(return_value=(None, None)),
    )
    monkeypatch.setattr(
        "services.pipeline._store_last_qa", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "services.pipeline._ab_record", AsyncMock(return_value=None)
    )

    # Reset memory service singleton so we get a fresh MemoryService whose
    # LongTermMemory we can pin to the shared pool below.
    import services.memory.memory_service as mem_mod
    monkeypatch.setattr(mem_mod, "_memory_service", None, raising=False)

    from services.pipeline import SwarmQueryPipeline, _SubAgentResult

    pipeline = SwarmQueryPipeline()

    # Pin LongTermMemory's pool to the shared session pool.
    pipeline._memory._long._pool = pgvector_pool

    # Stub the noisy collaborators.
    pipeline._audit = MagicMock()
    pipeline._audit.log_query = AsyncMock(return_value=None)
    pipeline._audit.log = AsyncMock(return_value=None)
    pipeline._tenant_svc = MagicMock()
    pipeline._tenant_svc.get_tenant_filter = MagicMock(return_value={})
    pipeline._filter_extractor = MagicMock()
    pipeline._filter_extractor.extract = AsyncMock(
        return_value=MagicMock(filters={}, semantic_query="")
    )

    # Decompose: return 2 sub-questions so N>1 path is taken.
    pipeline._decompose = AsyncMock(return_value=["q1", "q2"])

    # Sub-agent: return a deterministic, successful result (no LLM, no retrieval).
    async def _stub_sub_agent(agent_index, sub_question, tf, req):  # noqa: ARG001
        return _SubAgentResult(
            answer=f"answer for {sub_question}",
            turns=1,
            tool_calls_count=0,
            chunks=[],
        )

    pipeline._run_sub_agent = _stub_sub_agent

    # Synthesizer: deterministic final answer (no LLM).
    pipeline._synthesize = AsyncMock(return_value=final_answer)

    return pipeline


# -----------------------------------------------------------------------------
# Test 1 — swarm run writes a USER-SIDE fact within 2s (closes T2 fallback)
# -----------------------------------------------------------------------------


async def test_swarm_run_writes_user_side_fact_within_2s(
    pgvector_pool: asyncpg.Pool,
    extractor_llm_mock,
    embedder_or_mock,  # noqa: ARG001 — provides MagicMock embedder
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SwarmQueryPipeline.run end-to-end: dispatch_extraction fires + user-side
    fact persists to long_term_facts within 2s budget. Closes Plan 05 unit
    test's inspect.getsource structural-fallback gap.
    """
    # Ensure schema exists.
    mem = LongTermMemory()
    mem._pool = pgvector_pool
    await mem._create_tables()

    # Wire the extractor LLM stub to return a user-side preference fact.
    extractor_llm_mock.call_agentic_turn.return_value = AgenticTurn(
        text='{"facts":[{"fact":"user prefers React","category":"stable_preferences","importance":0.8}]}',
        tool_calls=[],
        stop_reason="text_only",
        raw_assistant_msg={"role": "assistant", "content": "..."},
        usage_input_tokens=0,
        usage_output_tokens=0,
    )

    pipeline = await _build_minimal_swarm_pipeline(pgvector_pool, monkeypatch)

    req = GenerationRequest(
        query="I prefer React over Vue. What do you recommend?",
        user_id="u_swarm_e2e",
        tenant_id="t_swarm_e2e",
        session_id="s_swarm_e2e",
        swarm_mode=True,
    )

    t0 = time.perf_counter()
    response = await pipeline.run(req)
    t1 = time.perf_counter()

    # Swarm path has higher latency budget than agent due to fan-out.
    assert isinstance(response, GenerationResponse)
    assert t1 - t0 < 5.0, (
        f"Swarm pipeline.run took {t1 - t0:.2f}s > 5.0s budget"
    )

    # Wait for the background extractor.
    await asyncio.sleep(2.0)

    async with pgvector_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT fact, importance FROM long_term_facts
               WHERE user_id='u_swarm_e2e' AND tenant_id='t_swarm_e2e' LIMIT 1"""
        )
    assert row is not None, (
        "SwarmQueryPipeline.run did not persist a long_term_facts row for "
        "u_swarm_e2e. dispatch_extraction may not have fired in the swarm "
        "path — closes Plan 05 inspect.getsource fallback gap."
    )
    assert re.search(r"React", row["fact"], re.IGNORECASE), (
        f"Persisted fact does not reference USER's stated 'React' preference; "
        f"got fact={row['fact']!r}"
    )
    assert row["importance"] == 0.8


# -----------------------------------------------------------------------------
# Test 2 — swarm extractor exception isolated
# -----------------------------------------------------------------------------


async def test_swarm_extractor_exception_isolated(
    pgvector_pool: asyncpg.Pool,
    embedder_or_mock,  # noqa: ARG001 — fixture present for parity
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Swarm path mirror of test_extractor_exception_isolated_pipeline_returns_normally:
    extractor.run raises RuntimeError; SwarmQueryPipeline.run still returns a
    valid GenerationResponse + zero rows written.
    """
    mem = LongTermMemory()
    mem._pool = pgvector_pool
    await mem._create_tables()

    failing_extractor = MagicMock()
    failing_extractor.run = AsyncMock(
        side_effect=RuntimeError("simulated swarm extractor crash")
    )

    with patch(
        "services.agent.extractor.get_extractor",
        return_value=failing_extractor,
    ):
        pipeline = await _build_minimal_swarm_pipeline(
            pgvector_pool, monkeypatch
        )

        req = GenerationRequest(
            query="hello swarm world",
            user_id="u_swarm_e2e",
            tenant_id="t_swarm_e2e",
            session_id="s_swarm_e2e_iso",
            swarm_mode=True,
        )

        t0 = time.perf_counter()
        response = await pipeline.run(req)
        t1 = time.perf_counter()

        assert isinstance(response, GenerationResponse)
        assert t1 - t0 < 5.0, (
            f"Swarm pipeline latency {t1 - t0:.2f}s > 5.0s (extractor crash "
            f"must not regress)"
        )

        # Let the failing background task complete + log_task_error fire.
        await asyncio.sleep(0.1)

    async with pgvector_pool.acquire() as conn:
        count = await conn.fetchval(
            """SELECT count(*) FROM long_term_facts
               WHERE user_id='u_swarm_e2e' AND tenant_id='t_swarm_e2e'"""
        )
    assert count == 0, (
        f"Expected 0 long_term_facts rows after swarm extractor crash; "
        f"got {count}."
    )
