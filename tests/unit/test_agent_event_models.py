"""TDD RED tests for Phase 18 SSE AgentEvent classes (AGENT-04, plan 18-01).

These tests MUST fail before implementation lands. After plan 18-01 Task 2,
they MUST all pass with no edits to test logic.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from utils.models import (
    AgentEvent,
    ExecutorParallelEvent,
    PlannerPlanEvent,
    SynthesizerFinalEvent,
    ToolCall,
    ToolPlan,
    ToolSpanEndEvent,
    ToolSpanErrorEvent,
    ToolSpanStartEvent,
)


def _sample_plan() -> ToolPlan:
    tc = ToolCall(id="call_1", name="search_knowledge_base", arguments={"query": "x"})
    return ToolPlan(
        steps=[tc],
        parallel_groups=[[0]],
        rationale="single hop",
        raw_assistant_msg={"role": "assistant", "content": "stub"},
        stop_reason="tool_use",
    )


# 1. event_type ClassVar values (D-09)
def test_event_type_class_vars_match_d09() -> None:
    assert PlannerPlanEvent.event_type      == "planner.plan"
    assert ToolSpanStartEvent.event_type    == "tool.span.start"
    assert ToolSpanEndEvent.event_type      == "tool.span.end"
    assert ToolSpanErrorEvent.event_type    == "tool.span.error"
    assert ExecutorParallelEvent.event_type == "executor.parallel"
    assert SynthesizerFinalEvent.event_type == "synthesizer.final"


# 2. Frozen — assignment raises
def test_planner_plan_event_is_frozen() -> None:
    evt = PlannerPlanEvent(trace_id="t1", seq=0, ts_ms=1, plan=_sample_plan())
    with pytest.raises(ValidationError):
        evt.seq = 99  # type: ignore[misc]


def test_tool_span_start_event_is_frozen() -> None:
    evt = ToolSpanStartEvent(
        trace_id="t1", seq=0, ts_ms=1,
        span_id="s1", name="search_knowledge_base", args={"q": "x"},
    )
    with pytest.raises(ValidationError):
        evt.span_id = "s2"  # type: ignore[misc]


def test_tool_span_end_event_is_frozen() -> None:
    evt = ToolSpanEndEvent(
        trace_id="t1", seq=0, ts_ms=1,
        span_id="s1", latency_ms=120, chunk_count=3,
        is_error=False, content_preview="hello",
    )
    with pytest.raises(ValidationError):
        evt.latency_ms = 0  # type: ignore[misc]


def test_tool_span_error_event_is_frozen() -> None:
    evt = ToolSpanErrorEvent(
        trace_id="t1", seq=0, ts_ms=1,
        span_id="s1", latency_ms=10,
        error_type="RuntimeError", error_message="boom",
    )
    with pytest.raises(ValidationError):
        evt.error_message = "tampered"  # type: ignore[misc]


def test_executor_parallel_event_is_frozen() -> None:
    evt = ExecutorParallelEvent(
        trace_id="t1", seq=0, ts_ms=1, fan_out=3, group_latency_ms=500,
    )
    with pytest.raises(ValidationError):
        evt.fan_out = 1  # type: ignore[misc]


def test_synthesizer_final_event_is_frozen() -> None:
    evt = SynthesizerFinalEvent(
        trace_id="t1", seq=0, ts_ms=1, answer="hi", sources_count=0,
    )
    with pytest.raises(ValidationError):
        evt.answer = "tampered"  # type: ignore[misc]


# 3. JSON round-trip (D-10)
def test_planner_plan_event_round_trip() -> None:
    evt = PlannerPlanEvent(trace_id="t1", seq=0, ts_ms=1, plan=_sample_plan())
    blob = evt.model_dump_json()
    again = PlannerPlanEvent.model_validate_json(blob)
    assert again.plan.rationale == "single hop"
    assert again.plan.steps[0].name == "search_knowledge_base"


def test_tool_span_start_round_trip() -> None:
    evt = ToolSpanStartEvent(
        trace_id="t1", seq=1, ts_ms=2,
        span_id="s1", name="search_knowledge_base", args={"query": "x"},
    )
    again = ToolSpanStartEvent.model_validate_json(evt.model_dump_json())
    assert again.args == {"query": "x"}
    assert again.span_id == "s1"


def test_tool_span_end_round_trip() -> None:
    evt = ToolSpanEndEvent(
        trace_id="t1", seq=2, ts_ms=3,
        span_id="s1", latency_ms=120, chunk_count=3,
        is_error=False, content_preview="hello",
    )
    again = ToolSpanEndEvent.model_validate_json(evt.model_dump_json())
    assert again.latency_ms == 120 and again.chunk_count == 3 and again.content_preview == "hello"


def test_tool_span_error_round_trip() -> None:
    evt = ToolSpanErrorEvent(
        trace_id="t1", seq=2, ts_ms=3,
        span_id="s1", latency_ms=10,
        error_type="RuntimeError", error_message="boom",
    )
    again = ToolSpanErrorEvent.model_validate_json(evt.model_dump_json())
    assert again.error_type == "RuntimeError" and again.error_message == "boom"


def test_executor_parallel_round_trip() -> None:
    evt = ExecutorParallelEvent(trace_id="t1", seq=3, ts_ms=4, fan_out=4, group_latency_ms=510)
    again = ExecutorParallelEvent.model_validate_json(evt.model_dump_json())
    assert again.fan_out == 4 and again.group_latency_ms == 510


def test_synthesizer_final_round_trip() -> None:
    evt = SynthesizerFinalEvent(trace_id="t1", seq=4, ts_ms=5, answer="ok", sources_count=2)
    again = SynthesizerFinalEvent.model_validate_json(evt.model_dump_json())
    assert again.answer == "ok" and again.sources_count == 2


# 4. ClassVar event_type excluded from model_dump
def test_event_type_excluded_from_model_dump() -> None:
    evt = ExecutorParallelEvent(trace_id="t1", seq=0, ts_ms=1, fan_out=1, group_latency_ms=0)
    dumped = evt.model_dump()
    assert "event_type" not in dumped, "event_type is a ClassVar; Pydantic V2 must NOT include it in model_dump()"


# 5. Verbatim args (D-11 — emitter is responsible; model holds verbatim)
def test_tool_span_start_args_are_verbatim() -> None:
    args = {"password": "secret-x", "nested": {"a": 1}}
    evt = ToolSpanStartEvent(
        trace_id="t1", seq=0, ts_ms=1,
        span_id="s1", name="x", args=args,
    )
    assert evt.args == args  # NO scrubbing inside the model


# 6. AgentEvent base does NOT have event_type ClassVar (subclasses do)
def test_agent_event_base_has_no_event_type() -> None:
    """Base class is abstract-by-convention — only concrete subclasses declare event_type."""
    assert not hasattr(AgentEvent, "event_type"), (
        "AgentEvent base must not declare event_type; concrete subclasses each set their own."
    )
