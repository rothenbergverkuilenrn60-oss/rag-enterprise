"""Unit tests for ToolPlan validators + Planner (Phase 16 Plan 16-02 RED→GREEN).

Mocks `call_agentic_turn` at consumer path (services.agent.planner.get_llm_client
or the Planner's own _llm) per v1.3 Phase 13/15 mock-at-consumer convention.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from services.agent.planner import Planner, PlannerOutputError
from utils.models import AgenticTurn, ToolCall, ToolPlan


class _StubLLM:
    """Minimal LLM stub: returns canned AgenticTurns in sequence."""

    def __init__(self, turns: list[AgenticTurn]) -> None:
        self._turns = list(turns)
        self.calls: list[tuple[Any, Any]] = []

    async def call_agentic_turn(
        self,
        messages: list[dict[str, Any]],
        tools: Any | None = None,
        system: str | None = None,
        **_: Any,
    ) -> AgenticTurn:
        self.calls.append((messages, tools))
        return self._turns.pop(0)


def _tc(call_id: str, name: str = "search_knowledge_base", **args: Any) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args)


def _turn(*, text: str = "", tool_calls: list[ToolCall] | None = None,
          stop_reason: str = "tool_use") -> AgenticTurn:
    return AgenticTurn(
        text=text,
        tool_calls=tool_calls or [],
        stop_reason=stop_reason,  # type: ignore[arg-type]
        raw_assistant_msg={},
    )


# ───────── ToolPlan validator tests ─────────

class TestToolPlanValidators:
    def test_valid_single_step(self) -> None:
        plan = ToolPlan(
            steps=[_tc("a")],
            parallel_groups=[[0]],
            rationale="single",
        )
        assert plan.steps[0].id == "a"
        assert plan.parallel_groups == [[0]]

    def test_valid_multi_step_one_wave(self) -> None:
        plan = ToolPlan(
            steps=[_tc("a"), _tc("b")],
            parallel_groups=[[0, 1]],
            rationale="parallel",
        )
        assert plan.parallel_groups == [[0, 1]]

    def test_valid_two_waves(self) -> None:
        plan = ToolPlan(
            steps=[_tc("a"), _tc("b"), _tc("c")],
            parallel_groups=[[0, 1], [2]],
            rationale="seq after parallel",
        )
        assert plan.parallel_groups == [[0, 1], [2]]

    def test_valid_empty_plan(self) -> None:
        plan = ToolPlan(steps=[], parallel_groups=[], rationale="")
        assert plan.steps == []

    def test_reject_empty_groups_when_steps_present(self) -> None:
        with pytest.raises(ValidationError, match="must not be empty"):
            ToolPlan(steps=[_tc("a")], parallel_groups=[])

    def test_reject_groups_when_no_steps(self) -> None:
        with pytest.raises(ValidationError, match="must be empty when steps is empty"):
            ToolPlan(steps=[], parallel_groups=[[0]])

    def test_reject_index_out_of_range(self) -> None:
        with pytest.raises(ValidationError, match="out of range"):
            ToolPlan(steps=[_tc("a")], parallel_groups=[[0, 5]])

    def test_reject_negative_index(self) -> None:
        with pytest.raises(ValidationError, match="out of range"):
            ToolPlan(steps=[_tc("a")], parallel_groups=[[-1]])

    def test_reject_duplicate_index(self) -> None:
        with pytest.raises(ValidationError, match="multiple groups"):
            ToolPlan(
                steps=[_tc("a"), _tc("b")],
                parallel_groups=[[0, 1], [0]],
            )

    def test_reject_missing_index(self) -> None:
        with pytest.raises(ValidationError, match="missing step indices"):
            ToolPlan(
                steps=[_tc("a"), _tc("b")],
                parallel_groups=[[0]],
            )

    def test_reject_empty_inner_group(self) -> None:
        with pytest.raises(ValidationError, match="empty groups"):
            ToolPlan(
                steps=[_tc("a")],
                parallel_groups=[[]],
            )

    def test_frozen(self) -> None:
        plan = ToolPlan(steps=[_tc("a")], parallel_groups=[[0]])
        with pytest.raises(ValidationError):
            plan.rationale = "mutated"  # type: ignore[misc]


# ───────── Planner tests ─────────

class TestPlanner:
    @pytest.mark.asyncio
    async def test_plan_from_messages_single_tool(self) -> None:
        turn = _turn(tool_calls=[_tc("c1", query="hello")])
        llm = _StubLLM([turn])
        planner = Planner(llm=llm)

        plan = await planner.plan_from_messages([{"role": "user", "content": "hi"}])

        assert isinstance(plan, ToolPlan)
        assert len(plan.steps) == 1
        assert plan.steps[0].id == "c1"
        assert plan.parallel_groups == [[0]]
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_plan_from_messages_two_parallel(self) -> None:
        turn = _turn(tool_calls=[_tc("a"), _tc("b")])
        llm = _StubLLM([turn])
        planner = Planner(llm=llm)

        plan = await planner.plan_from_messages([{"role": "user", "content": "hi"}])

        assert len(plan.steps) == 2
        # Default mapping: all parallel
        assert plan.parallel_groups == [[0, 1]]

    @pytest.mark.asyncio
    async def test_plan_from_messages_no_tools_text_only(self) -> None:
        turn = _turn(text="direct answer", stop_reason="text_only")
        llm = _StubLLM([turn])
        planner = Planner(llm=llm)

        plan = await planner.plan_from_messages([{"role": "user", "content": "hi"}])

        assert plan.steps == []
        assert plan.parallel_groups == []
        assert plan.rationale == "direct answer"

    @pytest.mark.asyncio
    async def test_plan_respects_explicit_parallel_groups(self) -> None:
        # LLM returns two tool calls AND text containing an explicit ToolPlan JSON
        explicit_text = json.dumps({
            "parallel_groups": [[0], [1]],
            "rationale": "must be sequential",
        })
        turn = _turn(text=explicit_text, tool_calls=[_tc("a"), _tc("b")])
        llm = _StubLLM([turn])
        planner = Planner(llm=llm)

        plan = await planner.plan_from_messages([])

        assert plan.parallel_groups == [[0], [1]]
        assert plan.rationale == "must be sequential"

    @pytest.mark.asyncio
    async def test_plan_rejects_explicit_invalid_groups(self) -> None:
        explicit_text = json.dumps({
            "parallel_groups": [[0, 5]],  # out of range
            "rationale": "broken",
        })
        turn = _turn(text=explicit_text, tool_calls=[_tc("a")])
        llm = _StubLLM([turn])
        planner = Planner(llm=llm)

        with pytest.raises(PlannerOutputError):
            await planner.plan_from_messages([])

    @pytest.mark.asyncio
    async def test_plan_single_call_only(self) -> None:
        # Planner does NOT loop — exactly one call_agentic_turn per plan call
        turn = _turn(tool_calls=[_tc("c1")])
        llm = _StubLLM([turn])
        planner = Planner(llm=llm)

        await planner.plan_from_messages([])
        assert len(llm.calls) == 1

    @pytest.mark.asyncio
    async def test_plan_ignores_text_when_not_json(self) -> None:
        turn = _turn(text="just thinking out loud", tool_calls=[_tc("a")])
        llm = _StubLLM([turn])
        planner = Planner(llm=llm)

        plan = await planner.plan_from_messages([])

        # Text is non-JSON narrative, not an explicit ToolPlan — fall through to default mapping
        assert plan.parallel_groups == [[0]]
        assert plan.rationale == "just thinking out loud"
