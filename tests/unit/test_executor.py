"""Unit tests for Executor (Phase 16 Plan 16-02).

Mocks `execute_tool_call` and retriever/llm at consumer path
(services.agent.executor.<dep>) per v1.3 Phase 13/15 convention.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from services.agent.executor import Executor
from utils.models import GenerationRequest, RetrievedChunk, ToolCall, ToolPlan


def _tc(call_id: str, name: str = "search_knowledge_base", **args: Any) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args)


def _req(query: str = "q") -> GenerationRequest:
    return GenerationRequest(query=query)


@pytest.mark.asyncio
async def test_execute_plan_single_step(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake_exec(tc: ToolCall, tf: dict[str, Any], req: GenerationRequest,
                        retriever: Any, llm: Any) -> tuple[list[RetrievedChunk], str]:
        seen.append(tc.id)
        return ([], f"ctx_{tc.id}")

    monkeypatch.setattr("services.agent.executor.execute_tool_call", fake_exec)

    plan = ToolPlan(
        steps=[_tc("a")],
        parallel_groups=[[0]],
    )
    executor = Executor(retriever=object(), llm=object())
    results = await executor.execute_plan(plan, {}, _req())

    assert len(results) == 1
    assert results[0][1] == "ctx_a"
    assert seen == ["a"]


@pytest.mark.asyncio
async def test_execute_plan_parallel_dispatch_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asserts results returned in step-index order regardless of completion order."""
    started_event = asyncio.Event()
    barrier_count = 0

    async def fake_exec(tc: ToolCall, tf: dict[str, Any], req: GenerationRequest,
                        retriever: Any, llm: Any) -> tuple[list[RetrievedChunk], str]:
        nonlocal barrier_count
        barrier_count += 1
        if barrier_count >= 2:
            started_event.set()
        await started_event.wait()  # both must reach here before either returns
        return ([], f"ctx_{tc.id}")

    monkeypatch.setattr("services.agent.executor.execute_tool_call", fake_exec)

    plan = ToolPlan(
        steps=[_tc("a"), _tc("b")],
        parallel_groups=[[0, 1]],
    )
    executor = Executor(retriever=object(), llm=object())
    results = await executor.execute_plan(plan, {}, _req())

    assert len(results) == 2
    assert results[0][1] == "ctx_a"
    assert results[1][1] == "ctx_b"


@pytest.mark.asyncio
async def test_execute_plan_two_waves_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wave 2 starts only after Wave 1 completes (sequential between waves)."""
    completion_order: list[str] = []

    async def fake_exec(tc: ToolCall, tf: dict[str, Any], req: GenerationRequest,
                        retriever: Any, llm: Any) -> tuple[list[RetrievedChunk], str]:
        completion_order.append(tc.id)
        return ([], f"ctx_{tc.id}")

    monkeypatch.setattr("services.agent.executor.execute_tool_call", fake_exec)

    plan = ToolPlan(
        steps=[_tc("a"), _tc("b"), _tc("c")],
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
async def test_execute_plan_propagates_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """asyncio.gather BaseException scope: exception in one step propagates out."""

    async def fake_exec(tc: ToolCall, tf: dict[str, Any], req: GenerationRequest,
                        retriever: Any, llm: Any) -> tuple[list[RetrievedChunk], str]:
        if tc.id == "bad":
            raise RuntimeError("tool failure")
        return ([], "ok")

    monkeypatch.setattr("services.agent.executor.execute_tool_call", fake_exec)

    plan = ToolPlan(
        steps=[_tc("a"), _tc("bad")],
        parallel_groups=[[0, 1]],
    )
    executor = Executor(retriever=object(), llm=object())

    with pytest.raises(RuntimeError, match="tool failure"):
        await executor.execute_plan(plan, {}, _req())


@pytest.mark.asyncio
async def test_execute_plan_preserves_tool_call_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller can re-correlate results via plan.steps[i].id."""

    async def fake_exec(tc: ToolCall, tf: dict[str, Any], req: GenerationRequest,
                        retriever: Any, llm: Any) -> tuple[list[RetrievedChunk], str]:
        return ([], tc.id)

    monkeypatch.setattr("services.agent.executor.execute_tool_call", fake_exec)

    plan = ToolPlan(
        steps=[_tc("first"), _tc("second"), _tc("third")],
        parallel_groups=[[0, 1, 2]],
    )
    executor = Executor(retriever=object(), llm=object())
    results = await executor.execute_plan(plan, {}, _req())

    # results[i] corresponds to plan.steps[i]
    for i, step in enumerate(plan.steps):
        assert results[i][1] == step.id


@pytest.mark.asyncio
async def test_execute_plan_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = ToolPlan(steps=[], parallel_groups=[])
    executor = Executor(retriever=object(), llm=object())
    results = await executor.execute_plan(plan, {}, _req())
    assert results == []
