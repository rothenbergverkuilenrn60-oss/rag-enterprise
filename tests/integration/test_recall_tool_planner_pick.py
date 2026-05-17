"""Integration tests for Plan 24-04 / SC-2: real-LLM planner picks recall_memory.

T7 (eng-review Decision-7): these tests use a REAL LLM to verify the planner
actually picks recall_memory for preference-referencing queries.  Mocked-planner
tests prove dispatch wiring, not real planner behavior — SC-2 requires the latter.

Marker: pytest.mark.real_llm — excluded from default CI via addopts -m "not integration".
Run nightly / pre-tag via: pytest -m real_llm

Skip-gated on PG_AVAILABLE so they skip gracefully on CI hosts without PostgreSQL.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.real_llm,
    pytest.mark.skipif(
        not PG_AVAILABLE,
        reason="PostgreSQL + pgvector not available — skipping planner-pick integration test",
    ),
]

# Stable test-identity constants — scoped DELETE in teardown, never DROP TABLE.
_USER_ID = "test-plan04-u"
_TENANT_ID = "test-plan04-t"

# Number of planner trials for the pick-rate gate (T7 / Decision-7).
_N_TRIALS = 5
_PICK_THRESHOLD = 4  # at least 4/5 must pick recall_memory for preference query


@pytest.fixture
async def seeded_pool(pgvector_pool):
    """Seed long_term_facts with a preference fact; delete after test."""
    from services.memory.memory_service import LongTermMemory  # noqa: PLC0415

    mem = LongTermMemory()
    await mem.save_fact(
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        fact="user prefers React for frontend development",
        source_doc="test",
        importance=0.9,
    )
    yield pgvector_pool
    # Scoped DELETE — never DROP TABLE (analog 13 anti-pattern).
    await pgvector_pool.execute(
        "DELETE FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        _USER_ID,
        _TENANT_ID,
    )


async def _run_planner_once(query: str) -> list[str]:
    """Run the real planner once and return the list of picked tool names.

    Uses AgentQueryPipeline's planner with AGENT_TOOL_ALLOWLIST including
    recall_memory (Plan 04 grows the list to length 4).

    Returns an empty list if the planner decides no tool call is needed.
    """
    from services.agent.planner import get_planner  # noqa: PLC0415
    from services.pipeline import AGENT_TOOL_ALLOWLIST  # noqa: PLC0415
    from utils.models import GenerationRequest  # noqa: PLC0415

    req = GenerationRequest(
        query=query,
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
        temperature=0.0,  # deterministic for pick-rate gate
        agent_mode=True,
    )
    planner = get_planner()
    messages = [{"role": "user", "content": query}]
    tool_plan = await planner.plan_from_messages(
        messages=messages,
        req=req,
        tool_names=AGENT_TOOL_ALLOWLIST,
    )
    if tool_plan is None:
        return []
    return [tc.name for tc in tool_plan.tool_calls]


@pytest.mark.asyncio
async def test_planner_picks_recall_for_preference_query(seeded_pool) -> None:
    """SC-2: real planner picks recall_memory ≥ 4/5 times for preference query.

    After seeding "user prefers React", a preference-referencing query must
    cause the planner LLM to include recall_memory in its ToolPlan at least
    _PICK_THRESHOLD / _N_TRIALS times (temperature=0.0 → near-deterministic).
    """
    query = "based on what you've learned about me, what frontend framework should I use?"
    picks = 0
    for _ in range(_N_TRIALS):
        tool_names = await _run_planner_once(query)
        if "recall_memory" in tool_names:
            picks += 1

    assert picks >= _PICK_THRESHOLD, (
        f"Expected planner to pick recall_memory ≥{_PICK_THRESHOLD}/{_N_TRIALS} times "
        f"for preference query, got {picks}/{_N_TRIALS}"
    )


@pytest.mark.asyncio
async def test_planner_skips_recall_for_unrelated_query(seeded_pool) -> None:
    """SC-2: real planner does NOT pick recall_memory for unrelated arithmetic query.

    A query that has no relationship to stored user preferences must cause the
    planner to skip recall_memory across all _N_TRIALS runs.
    """
    query = "what is 2+2?"
    picks = 0
    for _ in range(_N_TRIALS):
        tool_names = await _run_planner_once(query)
        if "recall_memory" in tool_names:
            picks += 1

    assert picks == 0, (
        f"Expected planner to skip recall_memory for unrelated query, "
        f"but it picked it {picks}/{_N_TRIALS} times"
    )
