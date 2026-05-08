# =============================================================================
# tests/integration/test_agent_pipeline_parallel.py
#
# Live OpenAI integration test for AGENT-02 parallel tool-call burst.
#
# Per CONTEXT.md D-05 (W-6 fix): the live OpenAI test runs UNCONDITIONALLY
# via the OneAPI gateway. The CI/dev environment is configured to provide
# `OPENAI_API_KEY`; absence is a CONFIGURATION ERROR and surfaces as a hard
# test failure, NOT a `pytest.skip`. Skipping silently would let a broken
# config land unnoticed.
#
# (The Anthropic-side live test, defined elsewhere, KEEPS its skipif on
#  ANTHROPIC_API_KEY per D-05.)
#
# This test verifies that a multi-dimension query produces ≥2 tool calls
# executed concurrently through `AgentQueryPipeline`, and that the final
# answer references results from ≥2 of the 3 sub-queries (multi-result
# synthesis — AGENT-02 AC#5(c) per W-2 fix).
# =============================================================================
from __future__ import annotations

import time

import pytest

# Module-level marker: integration tier only. NO pytest.mark.skipif on
# OPENAI_API_KEY — D-05 says runs unconditionally; missing key fails loudly
# at the OpenAI client construction step inside the pipeline.
pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_agent_pipeline_runs_real_tool_use_loop_on_openai(monkeypatch):
    """AGENT-01 acceptance #5 + AGENT-02 acceptance #5 combined.

    Submits a multi-dimension agent_mode=True query through the live OneAPI
    gateway, then asserts:
      (a) the pipeline ran the real tool-use loop (no fallback to QueryPipeline)
      (b) at least one turn produced ≥2 parallel tool calls (AGENT-02 #5(a))
      (c) the final answer references ≥2 of the 3 keyword classes
          (AGENT-02 #5(c) — W-2 fix)

    Test requires `OPENAI_API_KEY` in env per D-05; missing key surfaces as
    a hard test failure, not a skip.
    """
    # Force OpenAI provider for this test (project default but assert explicitly).
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    # Lazy-import after env override.
    from services.pipeline import AgentQueryPipeline
    from utils.models import GenerationRequest

    # Reset any cached singleton so the env override takes effect.
    import services.generator.llm_client as llm_mod
    llm_mod._llm_instance = None

    pipeline = AgentQueryPipeline()

    multi_dimension_query = (
        "请同时查询三项规定:(1)产假天数 (2)病假规定 (3)加班补偿政策。"
        "三项相互独立,可以并行检索。"
    )
    req = GenerationRequest(
        query=multi_dimension_query,
        top_k=6,
        agent_mode=True,
        tenant_id="",
        user_id="",
    )

    # Capture log output to assert parallelism_factor ≥ 2 in at least one turn.
    from loguru import logger as loguru_logger
    captured: list[str] = []
    sink_id = loguru_logger.add(lambda msg: captured.append(str(msg)), level="INFO")

    try:
        t0 = time.perf_counter()
        resp = await pipeline.run(req)
        elapsed = time.perf_counter() - t0
    finally:
        loguru_logger.remove(sink_id)

    # AGENT-01 acceptance: ran the real tool-use loop (not QueryPipeline fallback).
    # The fallback path emits "falling back" in logs; absence is positive evidence.
    assert not any("falling back" in line for line in captured), (
        "AgentQueryPipeline fell back to QueryPipeline — call_agentic_turn likely raised. "
        "AGENT-01 acceptance #5 NOT satisfied."
    )

    # AGENT-02 acceptance #5(a): at least one turn had parallel_factor ≥ 2.
    parallel_lines = [line for line in captured if "parallel_factor=" in line]
    assert parallel_lines, "No [Agent] iter=... parallel_factor=... lines emitted"
    factors: list[int] = []
    for line in parallel_lines:
        idx = line.find("parallel_factor=")
        if idx >= 0:
            tail = line[idx + len("parallel_factor="):]
            num_str = tail.split(maxsplit=1)[0].rstrip("\n,)] ")
            try:
                factors.append(int(num_str))
            except ValueError:
                pass
    assert any(f >= 2 for f in factors), (
        f"No turn had >=2 parallel tool calls; observed factors={factors}. "
        f"Either the LLM didn't emit parallel tool calls (model-dependent — try "
        f"prompting more explicitly) or asyncio.gather is not actually being "
        f"called with >=2 coros. AGENT-02 acceptance #5(a) NOT satisfied."
    )

    # Sanity: response has an answer + trace_id.
    assert resp.answer, "Empty answer despite successful loop"
    assert resp.trace_id

    # AGENT-02 AC#5(c) — W-2 fix: final answer references results from ≥2 of
    # the 3 sub-queries (multi-result synthesis). LLM nondeterminism is
    # accommodated by requiring ≥2 of 3 keyword classes, not all 3.
    keyword_classes = ('产假', '病假', '加班')
    matches = sum(kw in resp.answer for kw in keyword_classes)
    assert matches >= 2, (
        f"Expected resp.answer to reference >=2 of {keyword_classes} "
        f"(multi-result synthesis); got {matches}. "
        f"answer (first 200 chars): {resp.answer[:200]}"
    )

    # Time budget: with 2-3 parallel tool calls + ~1s retrieve each, total
    # should finish well under MAX_ITERATIONS * tool_timeout. Generous bound
    # to avoid flake on slow gateways.
    assert elapsed < 60.0, f"Integration ran too long ({elapsed:.1f}s); investigate"
