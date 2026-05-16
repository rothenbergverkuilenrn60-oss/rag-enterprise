"""Phase 23 / MEM-04 — AgentQueryPipeline end-to-end extractor integration.

Closes ROADMAP SC-4 + SC-5 at the integration layer:
  - SC-4: user-side fact persisted within 2s under real ``asyncio.create_task``.
  - SC-5: extractor exception isolated — pipeline returns normally.

Harness shape: AgentQueryPipeline.run is mocked at planner/executor consumer
paths to deterministically short-circuit (no real LLM, no real retrieval) but
the post-synthesis ``_persist_turn`` → ``dispatch_extraction`` path runs
end-to-end against the real pg pool fixture.

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
    ToolPlan,
)

pytestmark = [pytest.mark.integration, pytest.mark.pgvector]


# -----------------------------------------------------------------------------
# Minimal pipeline harness — short-circuits planner/executor/synth so only the
# post-synthesis _persist_turn → dispatch_extraction path runs end-to-end.
# -----------------------------------------------------------------------------


async def _build_minimal_agent_pipeline(
    pgvector_pool: asyncpg.Pool,
    monkeypatch: pytest.MonkeyPatch,
    final_answer: str = "Sure, React it is.",
):
    """Construct an AgentQueryPipeline whose Planner returns a terminal plan
    on the first iteration (so the executor never runs).

    Returns the live pipeline instance with all collaborators stubbed and
    its ``_long._pool`` set to the shared session pool.
    """
    # Patch the module-level helpers that depend on Redis (A/B + last-QA store)
    # to no-ops so the run path doesn't spend 10s timing out against
    # localhost:6379.
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

    # Planner returns terminal plan (no steps → AgentQueryPipeline.run breaks
    # out of the loop on iteration 1; plan.rationale becomes the final answer).
    terminal_plan = ToolPlan(
        steps=[],
        parallel_groups=[],
        rationale=final_answer,
        raw_assistant_msg={"role": "assistant", "content": final_answer},
        stop_reason="text_only",
    )
    mock_planner = MagicMock()
    mock_planner.plan_from_messages = AsyncMock(return_value=terminal_plan)
    monkeypatch.setattr(
        "services.pipeline.get_planner", lambda: mock_planner
    )

    # Executor never invoked (plan.steps == []) but patch defensively.
    mock_executor = MagicMock()
    mock_executor.execute_plan = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "services.pipeline.get_executor", lambda: mock_executor
    )

    # Reset memory service singleton so we get a fresh MemoryService whose
    # LongTermMemory we can pin to the shared pool below.
    import services.memory.memory_service as mem_mod
    monkeypatch.setattr(mem_mod, "_memory_service", None, raising=False)

    # Build a real AgentQueryPipeline now that get_planner/get_executor return
    # stubs — __init__ calls get_memory_service() / get_audit_service() /
    # get_tenant_service() / get_filter_extractor() / get_retriever() /
    # get_llm_client(). Wire mocks for the noisy ones (audit, tenant, filter).
    from services.pipeline import AgentQueryPipeline

    pipeline = AgentQueryPipeline()

    # Pin LongTermMemory's pool to the shared session pool so save_fact INSERTs
    # land in the live PG.
    pipeline._memory._long._pool = pgvector_pool

    # Stub audit so it doesn't hit real DB writes.
    pipeline._audit = MagicMock()
    pipeline._audit.log_query = AsyncMock(return_value=None)
    pipeline._audit.log = AsyncMock(return_value=None)

    # Stub tenant_svc + filter_extractor to be cheap.
    pipeline._tenant_svc = MagicMock()
    pipeline._tenant_svc.get_tenant_filter = MagicMock(return_value={})
    pipeline._filter_extractor = MagicMock()
    pipeline._filter_extractor.extract = AsyncMock(
        return_value=MagicMock(filters={}, semantic_query="")
    )

    return pipeline


# -----------------------------------------------------------------------------
# Test 1 — user turn writes a USER-SIDE fact within 2s (T1 strengthened)
# -----------------------------------------------------------------------------


async def test_user_turn_writes_user_side_fact_within_2s(
    pgvector_pool: asyncpg.Pool,
    extractor_llm_mock,
    embedder_or_mock,  # noqa: ARG001 — provides MagicMock embedder
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-4: row appears within 2s + persisted fact references USER's statement.

    T1 strengthening (eng-review 2026-05-16): asserts the persisted ``fact``
    column references the user's statement (regex ``React``), not just
    row-existence — closes the silent-success failure mode where the
    extractor extracts the assistant's reply paraphrase.
    """
    # Ensure schema exists.
    mem = LongTermMemory()
    mem._pool = pgvector_pool
    await mem._create_tables()

    # Wire the mocked extractor LLM to return a user-side preference fact.
    extractor_llm_mock.call_agentic_turn.return_value = AgenticTurn(
        text='{"facts":[{"fact":"user prefers React","category":"stable_preferences","importance":0.8}]}',
        tool_calls=[],
        stop_reason="text_only",
        raw_assistant_msg={"role": "assistant", "content": "..."},
        usage_input_tokens=0,
        usage_output_tokens=0,
    )

    pipeline = await _build_minimal_agent_pipeline(pgvector_pool, monkeypatch)

    req = GenerationRequest(
        query=(
            "what frontend framework do you recommend? "
            "I prefer React over Vue."
        ),
        user_id="u_e2e",
        tenant_id="t_e2e",
        session_id="s_e2e",
        agent_mode=True,
    )

    t_start = time.perf_counter()
    response = await pipeline.run(req)
    t_response = time.perf_counter()

    # User-facing turn returns normally + within 2s budget.
    assert isinstance(response, GenerationResponse)
    assert t_response - t_start < 2.0, (
        f"User-facing turn took {t_response - t_start:.2f}s > 2.0s budget"
    )

    # Wait for the background extraction task (SC-4 budget).
    await asyncio.sleep(2.0)

    # Verify the row appeared with the user-side fact content.
    async with pgvector_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT fact, importance FROM long_term_facts
               WHERE user_id='u_e2e' AND tenant_id='t_e2e' LIMIT 1"""
        )
    assert row is not None, (
        "Expected one long_term_facts row for u_e2e/t_e2e; got none. "
        "Either dispatch_extraction did not fire or the background task "
        "raised before save_fact."
    )
    # T1 strengthening — user-side fact assertion (case-insensitive regex).
    assert re.search(r"React", row["fact"], re.IGNORECASE), (
        f"Persisted fact does not reference the USER's stated preference "
        f"'React'; got fact={row['fact']!r}. Extractor may be misattributing "
        f"to the assistant's reply."
    )
    # Bucket-pinning: importance must land on one of the white-listed buckets,
    # and specifically the 0.8 'stable_preferences' bucket the LLM stub returned.
    assert row["importance"] in (0.2, 0.5, 0.8)
    assert row["importance"] == 0.8


# -----------------------------------------------------------------------------
# Test 2 — extractor exception isolated; pipeline returns normally
# -----------------------------------------------------------------------------


async def test_extractor_exception_isolated_pipeline_returns_normally(
    pgvector_pool: asyncpg.Pool,
    embedder_or_mock,  # noqa: ARG001 — fixture present for parity
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-5: extractor RuntimeError swallowed; pipeline.run returns normally.

    Patches ``services.agent.extractor.get_extractor`` to a mock whose
    ``run`` raises RuntimeError. Asserts:
      - pipeline.run returns a valid GenerationResponse (no propagation),
      - latency stays bounded (< 2.0s),
      - long_term_facts has zero rows for the user_id (extractor crashed
        before any save_fact).
    """
    # Ensure schema exists.
    mem = LongTermMemory()
    mem._pool = pgvector_pool
    await mem._create_tables()

    # Patch the extractor's run() to raise.
    failing_extractor = MagicMock()
    failing_extractor.run = AsyncMock(
        side_effect=RuntimeError("simulated extractor crash")
    )

    with patch(
        "services.agent.extractor.get_extractor",
        return_value=failing_extractor,
    ):
        pipeline = await _build_minimal_agent_pipeline(
            pgvector_pool, monkeypatch
        )

        req = GenerationRequest(
            query="hello world",
            user_id="u_e2e",
            tenant_id="t_e2e",
            session_id="s_e2e_iso",
            agent_mode=True,
        )

        t_start = time.perf_counter()
        response = await pipeline.run(req)
        t_response = time.perf_counter()

        # SC-5: pipeline returns normally despite extractor crash.
        assert isinstance(response, GenerationResponse)
        assert t_response - t_start < 2.0, (
            f"Pipeline latency {t_response - t_start:.2f}s > 2.0s (extractor "
            f"crash must not regress user-facing latency)"
        )

        # Let the failing background task complete + log_task_error fire.
        await asyncio.sleep(0.1)

    # No rows written — extractor crashed before save_fact ever ran.
    async with pgvector_pool.acquire() as conn:
        count = await conn.fetchval(
            """SELECT count(*) FROM long_term_facts
               WHERE user_id='u_e2e' AND tenant_id='t_e2e'"""
        )
    assert count == 0, (
        f"Expected 0 long_term_facts rows after extractor crash; got {count}. "
        f"The exception isolation contract may be leaking writes."
    )
