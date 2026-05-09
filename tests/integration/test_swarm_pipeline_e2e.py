# =============================================================================
# tests/integration/test_swarm_pipeline_e2e.py
# Phase 12-03 Task 3 — End-to-end live LLM smoke for SwarmQueryPipeline (AGENT-03).
#
# Excluded from default pytest run by pytest.ini `addopts = -m "not integration"`.
# Run explicitly:
#   pytest tests/integration/test_swarm_pipeline_e2e.py -m integration
#
# Per CONTEXT.md D-05 (mirrors test_agent_pipeline_parallel.py): the live OpenAI
# test runs UNCONDITIONALLY via the OneAPI gateway — missing OPENAI_API_KEY is a
# CONFIGURATION ERROR and surfaces as a hard test failure, NOT a `pytest.skip`.
# =============================================================================
"""End-to-end integration test for SwarmQueryPipeline (AGENT-03)."""
from __future__ import annotations

import pytest

from services.pipeline import SwarmQueryPipeline
from utils.models import GenerationRequest, GenerationResponse

# Module-level marker: integration tier only.
pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_swarm_e2e_multi_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live multi-dimension query through SwarmQueryPipeline → real LLM.

    Asserts:
      - resp.answer is non-empty string
      - resp.sources is a list
      - resp.latency_ms > 0
      - resp.trace_id present
    Best-effort logs keyword hits across the three sub-question domains; the
    keyword check is informational (corpus dependency makes a hard assertion
    flaky).
    """
    # Force OpenAI provider (project default; assert explicitly to mirror analog).
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    # Reset both singletons so the env override takes effect against a fresh client.
    import services.generator.llm_client as llm_mod
    import services.pipeline as pipe_mod
    llm_mod._llm_instance = None
    pipe_mod._swarm_pipeline = None

    pipeline = SwarmQueryPipeline()

    # Production canary query — three independent dimensions.
    req = GenerationRequest(
        query="审计上月所有未结案件的产假天数、病假规定、加班补偿政策",
        top_k=5,
        swarm_mode=True,
        tenant_id="integration-test",
        user_id="integration-test-user",
    )

    resp: GenerationResponse = await pipeline.run(req)

    assert isinstance(resp, GenerationResponse)
    assert isinstance(resp.answer, str) and len(resp.answer) > 0, "swarm produced empty answer"
    assert isinstance(resp.sources, list)
    assert resp.latency_ms > 0, f"latency_ms must be positive; got {resp.latency_ms}"
    assert resp.trace_id and len(resp.trace_id) > 0

    # Best-effort: synthesis output references at least one sub-question domain.
    # If the corpus is empty for the test tenant, sub-agents may all degrade —
    # in that case the answer will contain the graceful-degradation marker; we
    # accept either outcome and only assert non-empty above. The keyword check
    # below is informational logging, not a hard assertion.
    keywords = ("产假", "病假", "加班")
    hits = [k for k in keywords if k in resp.answer]
    print(f"[swarm-e2e] keyword hits: {hits} / 3; answer length: {len(resp.answer)}")
