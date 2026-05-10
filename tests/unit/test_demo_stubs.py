"""TDD RED tests for services.agent._demo_stubs (Phase 19, AGENT-08).

These tests pin the runtime contract for the demo-agent primitives promoted
from ``tests/unit/test_agent_sse.py`` Phase 18 fixtures (``_StubPlanner``,
``_make_fake_tool``, ``_stub_registry``) into a single source of truth shared
between ``make demo-agent`` and the Phase 19 demo integration test.

Plan spec: ``.planning/phases/19-agent-first-docs-demo-release/19-01-PLAN.md``.
Decisions: CONTEXT.md D-05 (4-tool fan-out demo query), D-06 (chunk_count=3
on demo tool metadata so SSE events carry visible chunk counts).

RED state: ALL imports from ``services.agent._demo_stubs`` fail with
``ModuleNotFoundError`` until Task 2 ships the module.
"""
from __future__ import annotations

import time
from typing import Any, ClassVar

import pytest

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry
from services.agent._demo_stubs import (  # noqa: E402  (RED — module does not exist yet)
    DEMO_QUERY,
    DemoStubPlanner,
    build_demo_registry,
    make_fake_retrieve_tool,
)
from utils.models import (
    GenerationRequest,
    ToolCall,  # noqa: F401  — required import per plan 19-01 Task 1 acceptance criteria
    ToolContext,
    ToolPlan,
    ToolResult,
)


# ── helpers ────────────────────────────────────────────────────────────


def _ctx() -> ToolContext:
    """Construct a ToolContext with stubs sufficient for ``run`` invocation.

    The fake tool's ``run`` body never touches retriever/llm — it just
    sleeps and returns a fixture ToolResult — so ``object()`` satisfies
    the ``arbitrary_types_allowed=True`` ToolContext fields.
    """
    return ToolContext(
        req=GenerationRequest(
            query="x",
            session_id="s",
            top_k=5,
            tenant_id="t",
            user_id="u",
        ),
        tf={},
        retriever=object(),
        llm=type("LLM", (), {"provider_name": "openai"})(),
    )


# ── tests ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_demo_stub_planner_returns_four_step_plan() -> None:
    """First call returns the 4-tool parallel plan per CONTEXT.md D-05."""
    planner = DemoStubPlanner()
    plan = await planner.plan_from_messages([], None, None)

    assert isinstance(plan, ToolPlan)
    assert len(plan.steps) == 4
    assert all(step.name == "search_knowledge_base" for step in plan.steps)
    assert plan.parallel_groups == [[0, 1, 2, 3]]
    assert plan.stop_reason == "tool_use"
    assert plan.rationale != ""


@pytest.mark.asyncio
async def test_demo_stub_planner_second_call_returns_terminal_plan() -> None:
    """Second call returns the terminal text-only plan with composed answer."""
    planner = DemoStubPlanner()
    await planner.plan_from_messages([], None, None)
    plan = await planner.plan_from_messages([], None, None)

    assert isinstance(plan, ToolPlan)
    assert plan.steps == []
    assert plan.parallel_groups == []
    assert plan.stop_reason == "text_only"
    assert plan.rationale != ""


def test_make_fake_retrieve_tool_returns_basetool_subclass() -> None:
    """Factory returns a class (not an instance) subclassing BaseTool."""
    cls = make_fake_retrieve_tool(
        name="search_knowledge_base", sleep_s=0.0, content="ctx"
    )

    assert isinstance(cls, type)
    assert issubclass(cls, BaseTool)
    assert cls.name == "search_knowledge_base"
    assert isinstance(cls.parameters_schema, dict)
    assert cls.parameters_schema["type"] == "object"


@pytest.mark.asyncio
async def test_make_fake_retrieve_tool_run_returns_toolresult_with_metadata() -> None:
    """run() yields ToolResult with content + chunk_count=3 + latency_ms=0 for sleep_s=0."""
    cls = make_fake_retrieve_tool(
        name="search_knowledge_base", sleep_s=0.0, content="ctx"
    )
    instance = cls()
    result = await instance.run({"q": "x"}, _ctx())

    assert isinstance(result, ToolResult)
    assert result.content == "ctx"
    assert result.metadata["latency_ms"] == 0
    assert result.metadata["chunk_count"] == 3


@pytest.mark.asyncio
async def test_make_fake_retrieve_tool_respects_sleep_s() -> None:
    """sleep_s=0.05 produces wall-clock ∈ (0.04s, 0.2s) and latency_ms=50."""
    cls = make_fake_retrieve_tool(
        name="search_knowledge_base", sleep_s=0.05, content="ctx"
    )
    instance = cls()

    t0 = time.perf_counter()
    result = await instance.run({"q": "x"}, _ctx())
    elapsed = time.perf_counter() - t0

    assert 0.04 < elapsed < 0.2, f"expected 0.04 < elapsed < 0.2, got {elapsed}"
    assert result.metadata["latency_ms"] == 50


def test_build_demo_registry_registers_all_tools() -> None:
    """build_demo_registry returns a fresh ToolRegistry with passed classes registered."""

    class _FakeRegistered(BaseTool):
        name:              ClassVar[str]            = "search_knowledge_base"
        description:       ClassVar[str]            = "fake"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            return ToolResult(content="x", chunks=[], metadata={})

    reg = build_demo_registry(_FakeRegistered)

    assert isinstance(reg, ToolRegistry)
    assert "search_knowledge_base" in reg.list()
    instance = reg.get("search_knowledge_base")
    assert isinstance(instance, _FakeRegistered)


def test_demo_query_constant_matches_context_d05() -> None:
    """DEMO_QUERY is byte-identical to CONTEXT.md <specifics> verbatim string."""
    assert DEMO_QUERY == (
        "Across our compliance, finance, engineering, and HR knowledge bases, "
        "where do we mention 'data retention'?"
    )
