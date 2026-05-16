"""Integration tests for Plan 24-04 / W3: RecallTool body against real PG.

W3 plan-checker fix (2026-05-16): this test was split out of
test_recall_tool_planner_pick.py to separate the real-LLM planner-pick gate
(T7 / Decision-7) from the RecallTool body end-to-end test.

This file carries NO real_llm marker — runs in default CI under
-m "not real_llm".  Requires PostgreSQL + pgvector (skip-gated on PG_AVAILABLE).

Phase 23 fixtures: pgvector_pool, clean_long_term_facts.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest

from tests.conftest import PG_AVAILABLE

# NOTE: NO pytest.mark.real_llm here — this file runs in default CI (W3 fix).
pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.skipif(
        not PG_AVAILABLE,
        reason="PostgreSQL + pgvector not available — skipping recall tool e2e test",
    ),
]

# Stable test-identity constants — scoped DELETE in teardown, never DROP TABLE.
_USER_ID = "test-plan04-e2e-u"
_TENANT_ID = "test-plan04-e2e-t"


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


@pytest.mark.asyncio
async def test_recall_tool_returns_seeded_fact(seeded_pool) -> None:
    """RecallTool body returns the seeded preference fact against real PG.

    Exercises the RecallTool.run() path end-to-end:
    - Real PG pool via pgvector_pool fixture
    - Real LongTermMemory.get_relevant_facts (cosine similarity)
    - Result content contains "React" substring
    - result.is_error is False

    Does NOT require a real LLM API key — tests the tool body only, not the
    planner decision (planner-pick coverage is in test_recall_tool_planner_pick.py).
    """
    from services.agent.tools.recall import RecallTool  # noqa: PLC0415
    from utils.models import GenerationRequest, ToolContext  # noqa: PLC0415

    req = GenerationRequest(
        query="frontend framework",
        user_id=_USER_ID,
        tenant_id=_TENANT_ID,
    )
    ctx = ToolContext(
        req=req,
        tf={},
        retriever=object(),
        llm=object(),
    )
    tool = RecallTool()
    result = await tool.run(args={"query": "frontend framework"}, ctx=ctx)

    assert result.is_error is False, (
        f"RecallTool.run returned is_error=True; content: {result.content!r}"
    )
    assert "React" in result.content, (
        f"Expected 'React' in RecallTool result, got: {result.content!r}"
    )
