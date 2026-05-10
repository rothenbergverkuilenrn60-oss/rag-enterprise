"""Unit tests for Executor (Phase 16 Plan 16-02).

Phase 17 Wave-3 update: mocks `get_tool_registry` at consumer path
(services.agent.executor.get_tool_registry) per v1.3 Phase 13/15 convention.
Assertions updated from tuple-shape to ToolResult-shape.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from services.agent.executor import Executor
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry
from utils.models import GenerationRequest, ToolCall, ToolContext, ToolPlan, ToolResult


def _tc(call_id: str, name: str = "search_knowledge_base", **args: Any) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args)


def _req(query: str = "q") -> GenerationRequest:
    return GenerationRequest(query=query)


def _make_fake_tool(tool_name: str, content: str) -> type[BaseTool]:
    """Factory: returns a BaseTool subclass that returns a canned ToolResult."""

    class _FakeTool(BaseTool):
        name: ClassVar[str] = tool_name
        description: ClassVar[str] = "fake"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            return ToolResult(content=content, chunks=[], metadata={"latency_ms": 0})

    _FakeTool.__name__ = f"FakeTool_{tool_name}"
    _FakeTool.__qualname__ = f"FakeTool_{tool_name}"
    return _FakeTool


def _stub_registry(*tool_classes: type[BaseTool]) -> ToolRegistry:
    reg = ToolRegistry()
    for cls in tool_classes:
        reg.register(cls)
    return reg


@pytest.mark.asyncio
async def test_execute_plan_single_step(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeTool = _make_fake_tool("search_knowledge_base", "ctx_a")

    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(FakeTool),
    )

    plan = ToolPlan(
        steps=[_tc("a")],
        parallel_groups=[[0]],
    )
    executor = Executor(retriever=object(), llm=object())
    results = await executor.execute_plan(plan, {}, _req())

    assert len(results) == 1
    assert isinstance(results[0], ToolResult)
    assert results[0].content == "ctx_a"
    assert results[0].chunks == []


@pytest.mark.asyncio
async def test_execute_plan_parallel_dispatch_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asserts results returned in step-index order regardless of completion order."""
    started_event = asyncio.Event()
    barrier_count = 0

    class _BarrierTool(BaseTool):
        name: ClassVar[str] = "search_knowledge_base"
        description: ClassVar[str] = "barrier"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            nonlocal barrier_count
            barrier_count += 1
            if barrier_count >= 2:
                started_event.set()
            await started_event.wait()  # both must reach here before either returns
            return ToolResult(content=f"ctx_{ctx.req.query}", chunks=[], metadata={})

    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(_BarrierTool),
    )

    plan = ToolPlan(
        steps=[_tc("a", query="a"), _tc("b", query="b")],
        parallel_groups=[[0, 1]],
    )
    executor = Executor(retriever=object(), llm=object())
    results = await executor.execute_plan(plan, {}, _req())

    assert len(results) == 2
    assert isinstance(results[0], ToolResult)
    assert isinstance(results[1], ToolResult)


@pytest.mark.asyncio
async def test_execute_plan_two_waves_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wave 2 starts only after Wave 1 completes (sequential between waves)."""
    completion_order: list[str] = []

    class _OrderTool(BaseTool):
        name: ClassVar[str] = "search_knowledge_base"
        description: ClassVar[str] = "order"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            # args carries the call id via the ToolCall.arguments
            call_id = args.get("_id", "unknown")
            completion_order.append(str(call_id))
            return ToolResult(content=f"ctx_{call_id}", chunks=[], metadata={})

    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(_OrderTool),
    )

    plan = ToolPlan(
        steps=[_tc("a", _id="a"), _tc("b", _id="b"), _tc("c", _id="c")],
        parallel_groups=[[0, 1], [2]],
    )
    executor = Executor(retriever=object(), llm=object())
    results = await executor.execute_plan(plan, {}, _req())

    assert len(results) == 3
    assert "c" in completion_order
    # c must complete after both a and b
    assert completion_order.index("c") > completion_order.index("a")
    assert completion_order.index("c") > completion_order.index("b")


@pytest.mark.asyncio
async def test_execute_plan_returns_exception_as_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """return_exceptions=True: failed step returns BaseException, siblings unaffected.

    Phase 16 Wave-3 change: Executor uses asyncio.gather(return_exceptions=True)
    so individual step failures are returned as BaseException entries rather than
    raised. The orchestrator (AgentQueryPipeline.run) is responsible for building
    is_error=True tool_results from those entries (v1.3 Phase 12 D-01 isolation
    guarantee maintained end-to-end).
    """

    class _FlakyTool(BaseTool):
        name: ClassVar[str] = "search_knowledge_base"
        description: ClassVar[str] = "flaky"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            call_id = args.get("_id", "")
            if call_id == "bad":
                raise RuntimeError("tool failure")
            return ToolResult(content="ok", chunks=[], metadata={})

    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(_FlakyTool),
    )

    plan = ToolPlan(
        steps=[_tc("a", _id="a"), _tc("bad", _id="bad")],
        parallel_groups=[[0, 1]],
    )
    executor = Executor(retriever=object(), llm=object())

    results = await executor.execute_plan(plan, {}, _req())
    # step 0 ("a") succeeds; step 1 ("bad") fails → BaseException entry
    assert len(results) == 2
    assert isinstance(results[0], ToolResult)
    assert results[0].content == "ok"
    assert isinstance(results[1], RuntimeError)
    assert "tool failure" in str(results[1])


@pytest.mark.asyncio
async def test_execute_plan_preserves_tool_call_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller can re-correlate results via plan.steps[i].id."""

    class _IdTool(BaseTool):
        name: ClassVar[str] = "search_knowledge_base"
        description: ClassVar[str] = "id-echo"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            call_id = args.get("_id", "")
            return ToolResult(content=str(call_id), chunks=[], metadata={})

    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(_IdTool),
    )

    plan = ToolPlan(
        steps=[_tc("first", _id="first"), _tc("second", _id="second"), _tc("third", _id="third")],
        parallel_groups=[[0, 1, 2]],
    )
    executor = Executor(retriever=object(), llm=object())
    results = await executor.execute_plan(plan, {}, _req())

    # results[i] corresponds to plan.steps[i]
    for i, step in enumerate(plan.steps):
        assert isinstance(results[i], ToolResult)
        assert results[i].content == step.id


@pytest.mark.asyncio
async def test_execute_plan_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = ToolPlan(steps=[], parallel_groups=[])
    executor = Executor(retriever=object(), llm=object())
    results = await executor.execute_plan(plan, {}, _req())
    assert results == []
