"""TDD RED tests for Executor.execute_plan_streaming (AGENT-04, plan 18-02).

Mirrors tests/unit/test_executor.py conventions: mock at consumer path
``services.agent.executor.get_tool_registry``; reuse ``_make_fake_tool`` and
``_stub_registry`` style fixtures inline (no shared conftest). Phase 13/15/17
mock-at-consumer-path convention preserved (D-16).

These tests verify Phase 18 D-05 + D-09 + D-12 contracts:
- ToolSpanStartEvent yielded BEFORE each dispatch awaits (per group).
- ToolSpanEndEvent OR ToolSpanErrorEvent yielded AS each future resolves.
- ExecutorParallelEvent yielded ONCE per group at group END with fan_out + group_latency_ms.
- BaseException isolation (v1.3 D-01) preserved — siblings keep running.
- seq counter monotonic across all yielded events (orchestrator threads itertools.count()).
"""
from __future__ import annotations

import itertools
from typing import Any, ClassVar

import pytest

from services.agent.executor import Executor
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry
from utils.models import (
    AgentEvent,
    ExecutorParallelEvent,
    GenerationRequest,
    ToolCall,
    ToolContext,
    ToolPlan,
    ToolResult,
    ToolSpanEndEvent,
    ToolSpanErrorEvent,
    ToolSpanStartEvent,
)


def _make_fake_tool(tool_name: str, content: str = "ctx") -> type[BaseTool]:
    class _Fake(BaseTool):
        name:              ClassVar[str]            = tool_name
        description:       ClassVar[str]            = "fake"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            return ToolResult(
                content=content,
                chunks=[],
                metadata={"latency_ms": 5, "chunk_count": 0},
            )

    _Fake.__name__ = f"FakeTool_{tool_name}"
    _Fake.__qualname__ = f"FakeTool_{tool_name}"
    return _Fake


def _stub_registry(*classes: type[BaseTool]) -> ToolRegistry:
    reg = ToolRegistry()
    for cls in classes:
        reg.register(cls)
    return reg


def _tc(idx: int, name: str = "search_knowledge_base") -> ToolCall:
    return ToolCall(id=f"call_{idx}", name=name, arguments={"q": f"x{idx}"})


def _req() -> GenerationRequest:
    return GenerationRequest(query="q", session_id="s", top_k=5)


def _split_yields(items: list[Any]) -> tuple[list[AgentEvent], list[Any]]:
    events  = [x for x in items if isinstance(x, AgentEvent)]
    results = [x for x in items if not isinstance(x, AgentEvent)]
    return events, results


@pytest.mark.asyncio
async def test_execute_plan_streaming_single_step(monkeypatch: pytest.MonkeyPatch) -> None:
    Tool = _make_fake_tool("search_knowledge_base", "out")
    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(Tool),
    )
    plan = ToolPlan(
        steps=[_tc(0)],
        parallel_groups=[[0]],
        rationale="r",
        raw_assistant_msg={"role": "assistant", "content": "x"},
        stop_reason="tool_use",
    )
    ex = Executor(retriever=object(), llm=object())
    items = [
        item async for item in ex.execute_plan_streaming(
            plan, tf={}, req=_req(),
            trace_id="abc12345",
            seq_counter=itertools.count(),
        )
    ]
    events, results = _split_yields(items)
    assert len(results) == 1 and isinstance(results[0], ToolResult)
    assert [type(e).__name__ for e in events] == [
        "ToolSpanStartEvent",
        "ToolSpanEndEvent",
        "ExecutorParallelEvent",
    ]
    assert isinstance(events[2], ExecutorParallelEvent)
    assert events[2].fan_out == 1


@pytest.mark.asyncio
async def test_execute_plan_streaming_two_groups_ordering(monkeypatch: pytest.MonkeyPatch) -> None:
    Tool = _make_fake_tool("search_knowledge_base", "out")
    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(Tool),
    )
    plan = ToolPlan(
        steps=[_tc(0), _tc(1), _tc(2)],
        parallel_groups=[[0], [1, 2]],
        rationale="r",
        raw_assistant_msg={"role": "assistant", "content": "x"},
        stop_reason="tool_use",
    )
    ex = Executor(retriever=object(), llm=object())
    items = [
        item async for item in ex.execute_plan_streaming(
            plan, tf={}, req=_req(),
            trace_id="abc12345",
            seq_counter=itertools.count(),
        )
    ]
    events, results = _split_yields(items)
    type_seq = [type(e).__name__ for e in events]

    # Group 1: 1 start, 1 end, 1 parallel (fan_out=1)
    # Group 2: 2 starts (both before any end), 2 ends, 1 parallel (fan_out=2)
    assert type_seq.count("ToolSpanStartEvent")    == 3
    assert type_seq.count("ToolSpanEndEvent")      == 3
    assert type_seq.count("ExecutorParallelEvent") == 2
    assert len(results) == 3
    parallel_events = [e for e in events if isinstance(e, ExecutorParallelEvent)]
    assert [p.fan_out for p in parallel_events] == [1, 2]

    # Group 1 invariants: first 3 events are start, end, parallel(fan_out=1)
    assert isinstance(events[0], ToolSpanStartEvent)
    assert isinstance(events[1], ToolSpanEndEvent)
    assert isinstance(events[2], ExecutorParallelEvent) and events[2].fan_out == 1

    # Group 2: starts of idx 1+2 must precede any end of idx 1+2, and parallel comes last
    g2_events = events[3:]
    starts = [i for i, e in enumerate(g2_events) if isinstance(e, ToolSpanStartEvent)]
    ends   = [i for i, e in enumerate(g2_events) if isinstance(e, ToolSpanEndEvent)]
    par    = [i for i, e in enumerate(g2_events) if isinstance(e, ExecutorParallelEvent)]
    assert starts == [0, 1]                    # both starts come first in group 2
    assert max(starts) < min(ends)             # all starts precede any end
    assert par == [len(g2_events) - 1]         # parallel is last in group 2


@pytest.mark.asyncio
async def test_execute_plan_streaming_baseexception_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    long_msg = "boom-" + "x" * 300

    class _Flaky(BaseTool):
        name:              ClassVar[str]            = "flaky"
        description:       ClassVar[str]            = "raises"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            raise RuntimeError(long_msg)

    Good = _make_fake_tool("search_knowledge_base", "out")
    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(Good, _Flaky),
    )
    plan = ToolPlan(
        steps=[_tc(0, name="search_knowledge_base"), _tc(1, name="flaky")],
        parallel_groups=[[0, 1]],
        rationale="r",
        raw_assistant_msg={"role": "assistant", "content": "x"},
        stop_reason="tool_use",
    )
    ex = Executor(retriever=object(), llm=object())
    items = [
        item async for item in ex.execute_plan_streaming(
            plan, tf={}, req=_req(),
            trace_id="abc12345",
            seq_counter=itertools.count(),
        )
    ]
    events, results = _split_yields(items)
    err_events = [e for e in events if isinstance(e, ToolSpanErrorEvent)]
    end_events = [e for e in events if isinstance(e, ToolSpanEndEvent)]
    assert len(err_events) == 1 and len(end_events) == 1
    assert err_events[0].error_type == "RuntimeError"
    assert len(err_events[0].error_message) == 200
    assert err_events[0].error_message == long_msg[:200]
    # results carry one BaseException (the flaky tool) and one ToolResult (the good one)
    assert any(isinstance(r, BaseException) for r in results)
    assert any(isinstance(r, ToolResult) for r in results)
    # exactly one ExecutorParallelEvent per group, fan_out=2
    par_events = [e for e in events if isinstance(e, ExecutorParallelEvent)]
    assert len(par_events) == 1 and par_events[0].fan_out == 2


@pytest.mark.asyncio
async def test_execute_plan_streaming_span_id_match(monkeypatch: pytest.MonkeyPatch) -> None:
    Tool = _make_fake_tool("search_knowledge_base", "out")
    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(Tool),
    )
    plan = ToolPlan(
        steps=[_tc(0), _tc(1), _tc(2)],
        parallel_groups=[[0, 1, 2]],
        rationale="r",
        raw_assistant_msg={"role": "assistant", "content": "x"},
        stop_reason="tool_use",
    )
    ex = Executor(retriever=object(), llm=object())
    items = [
        item async for item in ex.execute_plan_streaming(
            plan, tf={}, req=_req(),
            trace_id="abc12345",
            seq_counter=itertools.count(),
        )
    ]
    events, _ = _split_yields(items)
    starts = {e.span_id for e in events if isinstance(e, ToolSpanStartEvent)}
    ends   = {e.span_id for e in events if isinstance(e, (ToolSpanEndEvent, ToolSpanErrorEvent))}
    assert starts == ends
    assert len(starts) == 3


@pytest.mark.asyncio
async def test_execute_plan_streaming_seq_monotonic(monkeypatch: pytest.MonkeyPatch) -> None:
    Tool = _make_fake_tool("search_knowledge_base", "out")
    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(Tool),
    )
    plan = ToolPlan(
        steps=[_tc(0), _tc(1)],
        parallel_groups=[[0, 1]],
        rationale="r",
        raw_assistant_msg={"role": "assistant", "content": "x"},
        stop_reason="tool_use",
    )
    ex = Executor(retriever=object(), llm=object())
    counter = itertools.count(start=10)
    items = [
        item async for item in ex.execute_plan_streaming(
            plan, tf={}, req=_req(),
            trace_id="abc12345",
            seq_counter=counter,
        )
    ]
    events, _ = _split_yields(items)
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)
    assert seqs[0] == 10


@pytest.mark.asyncio
async def test_execute_plan_streaming_empty_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    Tool = _make_fake_tool("search_knowledge_base", "out")
    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(Tool),
    )
    plan = ToolPlan(
        steps=[],
        parallel_groups=[],
        rationale="terminal",
        raw_assistant_msg={"role": "assistant", "content": "x"},
        stop_reason="text_only",
    )
    ex = Executor(retriever=object(), llm=object())
    items = [
        item async for item in ex.execute_plan_streaming(
            plan, tf={}, req=_req(),
            trace_id="abc12345",
            seq_counter=itertools.count(),
        )
    ]
    assert items == []


@pytest.mark.asyncio
async def test_execute_plan_streaming_does_not_break_execute_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parity gate — adding execute_plan_streaming must not regress execute_plan."""
    Tool = _make_fake_tool("search_knowledge_base", "out")
    monkeypatch.setattr(
        "services.agent.executor.get_tool_registry",
        lambda: _stub_registry(Tool),
    )
    plan = ToolPlan(
        steps=[_tc(0)],
        parallel_groups=[[0]],
        rationale="r",
        raw_assistant_msg={"role": "assistant", "content": "x"},
        stop_reason="tool_use",
    )
    ex = Executor(retriever=object(), llm=object())
    out = await ex.execute_plan(plan, tf={}, req=_req())
    assert len(out) == 1 and isinstance(out[0], ToolResult)
