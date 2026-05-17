"""TDD RED tests for AgentQueryPipeline.run_streaming (AGENT-04, plan 18-03).

Mock-at-consumer-path discipline (D-16): every patch targets
``services.pipeline.<name>`` so the orchestrator picks up stubs without
the real Planner/Executor wiring.

Covers ROADMAP Phase 18 SC1 (event types fire), SC3 (smoke count),
SC4 (latency bound). D-11 redaction + D-12 error path also tested.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, ClassVar

import pytest

from services.agent.executor import Executor
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry
from services.pipeline import AgentQueryPipeline
from utils.models import (
    AgentEvent,
    ExecutorParallelEvent,
    GenerationRequest,
    GenerationResponse,
    PlannerPlanEvent,
    SynthesizerFinalEvent,
    ToolCall,
    ToolContext,
    ToolPlan,
    ToolResult,
    ToolSpanEndEvent,
    ToolSpanErrorEvent,
    ToolSpanStartEvent,
)

# Plan 27-02 / TD-06 — auto-attach redis_mock fixture for every test in this
# module (tests/conftest.py:pytest_collection_modifyitems hook).
pytestmark = pytest.mark.uses_redis

# ── helpers ────────────────────────────────────────────────────────────

def _req(query: str = "q") -> GenerationRequest:
    return GenerationRequest(
        query=query, session_id="s", top_k=5,
        tenant_id="tenant-A", user_id="user-A",
    )


def _plan(
    steps: list[ToolCall],
    groups: list[list[int]],
    rationale: str = "r",
    stop_reason: str = "tool_use",
) -> ToolPlan:
    return ToolPlan(
        steps=steps, parallel_groups=groups, rationale=rationale,
        raw_assistant_msg={"role": "assistant", "content": "stub"},
        stop_reason=stop_reason,
    )


def _terminal_plan(rationale: str) -> ToolPlan:
    return ToolPlan(
        steps=[], parallel_groups=[], rationale=rationale,
        raw_assistant_msg={"role": "assistant", "content": rationale},
        stop_reason="text_only",
    )


def _make_fake_tool(
    tool_name: str,
    content: str = "ctx",
    sleep_s: float = 0.0,
) -> type[BaseTool]:
    class _Fake(BaseTool):
        name:              ClassVar[str]            = tool_name
        description:       ClassVar[str]            = "fake"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            return ToolResult(
                content=content,
                chunks=[],
                metadata={"latency_ms": int(sleep_s * 1000), "chunk_count": 0},
            )

    _Fake.__name__ = f"FakeTool_{tool_name}"
    return _Fake


def _stub_registry(*classes: type[BaseTool]) -> ToolRegistry:
    reg = ToolRegistry()
    for cls in classes:
        reg.register(cls)
    return reg


class _StubPlanner:
    """Returns a queue of pre-canned ToolPlans, one per call."""

    def __init__(self, plans: list[ToolPlan]) -> None:
        self._plans = list(plans)

    async def plan_from_messages(self, *args: Any, **kwargs: Any) -> ToolPlan:
        return self._plans.pop(0)


@pytest.fixture
def patch_pipeline_singletons(monkeypatch: pytest.MonkeyPatch):
    """Patch all singleton accessors AgentQueryPipeline.__init__ touches.

    Returns a callable that the test passes the planner + tool classes to.
    """
    def _do(planner: _StubPlanner, *tool_classes: type[BaseTool]) -> AgentQueryPipeline:
        # Memory / audit / tenant / filter — all no-op stubs.
        class _NoMem:
            async def load_context(self, *a: Any, **kw: Any) -> Any:
                class _C:
                    short_term: list[Any] = []
                return _C()

            async def save_turn(self, *a: Any, **kw: Any) -> None:
                return None

        class _NoAudit:
            async def log_query(self, *a: Any, **kw: Any) -> None:
                return None

        class _NoTenant:
            def get_tenant_filter(self, tenant_id: str) -> dict[str, Any]:
                return {}

        class _NoFilter:
            async def extract(self, q: str) -> Any:
                class _E:
                    filters: dict[str, Any] = {}
                    semantic_query: str = q
                return _E()

        monkeypatch.setattr("services.pipeline.get_memory_service",   lambda: _NoMem())
        monkeypatch.setattr("services.pipeline.get_audit_service",    lambda: _NoAudit())
        monkeypatch.setattr("services.pipeline.get_tenant_service",   lambda: _NoTenant())
        monkeypatch.setattr("services.pipeline.get_filter_extractor", lambda: _NoFilter())
        monkeypatch.setattr("services.pipeline.get_planner",          lambda: planner)

        # Real Executor over stub registry — patched at consumer path.
        monkeypatch.setattr(
            "services.agent.executor.get_tool_registry",
            lambda: _stub_registry(*tool_classes),
        )
        executor = Executor(
            retriever=object(),
            llm=type("LLM", (), {"provider_name": "openai"})(),
        )
        monkeypatch.setattr("services.pipeline.get_executor", lambda: executor)
        # Belt-and-braces: pipeline-path get_tool_registry is invoked when
        # pipeline computes the planner-tools schema list. Patch both per D-16.
        monkeypatch.setattr(
            "services.pipeline.get_tool_registry",
            lambda: _stub_registry(*tool_classes),
        )

        # LLM client stub — only provider_name read by AgentQueryPipeline.
        class _LLM:
            provider_name: ClassVar[str] = "openai"

        monkeypatch.setattr("services.pipeline.get_llm_client", lambda: _LLM())
        monkeypatch.setattr("services.pipeline.get_retriever",  lambda: object())

        return AgentQueryPipeline()

    return _do


# ── tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_streaming_emits_planner_plan_first(patch_pipeline_singletons) -> None:
    Tool = _make_fake_tool("search_knowledge_base")
    plans = [
        _plan(
            steps=[ToolCall(id="c0", name="search_knowledge_base", arguments={"q": "x"})],
            groups=[[0]],
        ),
        _terminal_plan("done"),
    ]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Tool)
    events: list[AgentEvent] = [evt async for evt in pipeline.run_streaming(_req())]
    assert isinstance(events[0], PlannerPlanEvent)
    assert events[0].plan.steps[0].name == "search_knowledge_base"


@pytest.mark.asyncio
async def test_run_streaming_smoke_sequence_d15(patch_pipeline_singletons) -> None:
    """ROADMAP SC3 — exact event counts for a known multi-hop plan.

    Reconciled per plan 18-01 planner_decision: ExecutorParallelEvent emitted
    at group END (not start). Single planner.plan event because the second
    iteration's terminal plan short-circuits without a separate planner.plan
    emission (D-06 — planner_event mirrors planner-call boundary, not loop
    iteration).

    Expected counts:
      planner.plan      x 1
      tool.span.start   x 4   (1 + 3)
      tool.span.end     x 4
      executor.parallel x 2   (fan_out=1, fan_out=3)
      synthesizer.final x 1
      TOTAL = 12 events
    """
    Tool = _make_fake_tool("search_knowledge_base")
    steps = [
        ToolCall(id=f"c{i}", name="search_knowledge_base", arguments={"i": i})
        for i in range(4)
    ]
    plans = [
        _plan(steps=steps, groups=[[0], [1, 2, 3]]),
        _terminal_plan("final-answer"),
    ]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Tool)
    events = [evt async for evt in pipeline.run_streaming(_req())]
    types = [type(e).__name__ for e in events]
    assert types.count("PlannerPlanEvent")      == 1
    assert types.count("ToolSpanStartEvent")    == 4
    assert types.count("ToolSpanEndEvent")      == 4
    assert types.count("ExecutorParallelEvent") == 2
    assert types.count("SynthesizerFinalEvent") == 1
    assert len(events) == 12
    parallel_events = [e for e in events if isinstance(e, ExecutorParallelEvent)]
    assert [p.fan_out for p in parallel_events] == [1, 3]


@pytest.mark.asyncio
async def test_run_streaming_latency_bounded_by_max_not_sum_d14_sc4(patch_pipeline_singletons) -> None:
    """ROADMAP SC4 — 4 tools x 0.5s each finish in max(0.5)+overhead, not 4x0.5."""
    Tool = _make_fake_tool("search_knowledge_base", sleep_s=0.5)
    steps = [
        ToolCall(id=f"c{i}", name="search_knowledge_base", arguments={"i": i})
        for i in range(4)
    ]
    plans = [
        _plan(steps=steps, groups=[[0, 1, 2, 3]]),
        _terminal_plan("done"),
    ]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Tool)
    t0 = time.perf_counter()
    events = [evt async for evt in pipeline.run_streaming(_req())]
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    assert 450 < elapsed_ms < 700, f"expected 450 < elapsed_ms < 700, got {elapsed_ms}"
    types = [type(e).__name__ for e in events]
    assert types.count("ToolSpanStartEvent") == 4
    assert types.count("ToolSpanEndEvent")   == 4
    parallel = [e for e in events if isinstance(e, ExecutorParallelEvent)]
    assert parallel[0].fan_out == 4


@pytest.mark.asyncio
async def test_run_streaming_redaction_args_verbatim_content_truncated_d11(patch_pipeline_singletons) -> None:
    """D-11 — args verbatim in tool.span.start; content > 200 chars truncated."""
    big_content = "x" * 500
    Tool = _make_fake_tool("search_knowledge_base", content=big_content)
    args = {"password": "secret-x", "k": 1}
    plans = [
        _plan(
            steps=[ToolCall(id="c0", name="search_knowledge_base", arguments=args)],
            groups=[[0]],
        ),
        _terminal_plan("done"),
    ]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Tool)
    events = [evt async for evt in pipeline.run_streaming(_req())]
    starts = [e for e in events if isinstance(e, ToolSpanStartEvent)]
    ends   = [e for e in events if isinstance(e, ToolSpanEndEvent)]
    assert starts[0].args == args, "args must be verbatim per D-11"
    assert len(ends[0].content_preview) == 200
    assert ends[0].content_preview == "x" * 200


@pytest.mark.asyncio
async def test_run_streaming_error_event_replaces_end_d12(patch_pipeline_singletons) -> None:
    long_msg = "kaboom-" + "x" * 250

    class _Flaky(BaseTool):
        name:              ClassVar[str]            = "flaky"
        description:       ClassVar[str]            = "fail"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            raise RuntimeError(long_msg)

    Good = _make_fake_tool("search_knowledge_base")
    plans = [
        _plan(
            steps=[
                ToolCall(id="c0", name="search_knowledge_base", arguments={}),
                ToolCall(id="c1", name="flaky", arguments={}),
            ],
            groups=[[0, 1]],
        ),
        _terminal_plan("done"),
    ]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Good, _Flaky)
    events = [evt async for evt in pipeline.run_streaming(_req())]
    err = [e for e in events if isinstance(e, ToolSpanErrorEvent)]
    end = [e for e in events if isinstance(e, ToolSpanEndEvent)]
    assert len(err) == 1
    assert err[0].error_type == "RuntimeError"
    assert len(err[0].error_message) == 200
    assert err[0].span_id not in {e.span_id for e in end}, \
        "tool.span.error replaces tool.span.end for that span_id"


@pytest.mark.asyncio
async def test_run_streaming_synthesizer_final_terminal(patch_pipeline_singletons) -> None:
    Tool = _make_fake_tool("search_knowledge_base")
    plans = [
        _plan(
            steps=[ToolCall(id="c0", name="search_knowledge_base", arguments={})],
            groups=[[0]],
        ),
        _terminal_plan("the-final-answer"),
    ]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Tool)
    events = [evt async for evt in pipeline.run_streaming(_req())]
    assert isinstance(events[-1], SynthesizerFinalEvent)
    assert events[-1].answer == "the-final-answer"


@pytest.mark.asyncio
async def test_run_streaming_seq_monotonic_across_planner_and_executor(patch_pipeline_singletons) -> None:
    Tool = _make_fake_tool("search_knowledge_base")
    plans = [
        _plan(
            steps=[ToolCall(id="c0", name="search_knowledge_base", arguments={})],
            groups=[[0]],
        ),
        _terminal_plan("done"),
    ]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Tool)
    events = [evt async for evt in pipeline.run_streaming(_req())]
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


@pytest.mark.asyncio
async def test_run_streaming_persist_turn_called_once(
    patch_pipeline_singletons,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """security_gate — audit log on every agent turn must still fire."""
    Tool = _make_fake_tool("search_knowledge_base")
    plans = [
        _plan(
            steps=[ToolCall(id="c0", name="search_knowledge_base", arguments={})],
            groups=[[0]],
        ),
        _terminal_plan("done"),
    ]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Tool)

    call_count = {"n": 0}

    async def _mock_persist(*a: Any, **kw: Any) -> GenerationResponse:
        call_count["n"] += 1
        return GenerationResponse(
            answer="done", sources=[], session_id="s", query="q",
            latency_ms=0.0, trace_id="abc12345", model="m",
        )

    monkeypatch.setattr(AgentQueryPipeline, "_persist_turn", _mock_persist)

    _ = [evt async for evt in pipeline.run_streaming(_req())]
    assert call_count["n"] == 1, "_persist_turn must be called exactly once per stream"


@pytest.mark.asyncio
async def test_run_streaming_does_not_break_run(patch_pipeline_singletons) -> None:
    Tool = _make_fake_tool("search_knowledge_base")
    plans = [_terminal_plan("done")]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Tool)
    resp = await pipeline.run(_req())
    assert isinstance(resp, GenerationResponse)
    assert resp.answer == "done"
