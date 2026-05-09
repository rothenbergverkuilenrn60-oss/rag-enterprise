"""Parity tests: replay v1.3 baseline fixtures through new Planner+Executor.

Phase 16 Plan 16-02. Fixtures live at tests/unit/fixtures/agent_parity/.
Each fixture provides a sequence of canned LLM AgenticTurns; the test
mocks `call_agentic_turn` at the consumer path, runs Planner.plan_from_messages
+ Executor.execute_plan, and asserts the resulting ToolCall sequence
matches the fixture's expected sequence byte-for-byte.

The full outer-loop / synthesizer behavior is exercised in Plan 16-03
(Wave 3) — this file only covers Planner + Executor in isolation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from services.agent.executor import Executor
from services.agent.planner import Planner
from utils.models import AgenticTurn, GenerationRequest, RetrievedChunk, ToolCall

FIXTURES = Path(__file__).parent / "fixtures" / "agent_parity"


def _agentic_turn_from_canned(canned: dict[str, Any]) -> AgenticTurn:
    """Convert fixture canned-turn dict to AgenticTurn."""
    raw_tool_calls = canned.get("tool_calls", []) or []
    tool_calls = [
        ToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("arguments", {}))
        for tc in raw_tool_calls
    ]
    stop = canned.get("stop_reason") or "tool_use"
    # Normalize provider stop reasons to AgenticTurn literals
    if stop == "end_turn":
        stop = "text_only"
    return AgenticTurn(
        text=canned.get("text") or "",
        tool_calls=tool_calls,
        stop_reason=stop,  # type: ignore[arg-type]
        raw_assistant_msg={},
    )


class _ReplayLLM:
    """LLM stub that yields canned turns in sequence."""

    def __init__(self, turns: list[AgenticTurn]) -> None:
        self._turns = list(turns)

    async def call_agentic_turn(
        self,
        messages: list[dict[str, Any]],
        tools: Any | None = None,
        system: str | None = None,
        **_: Any,
    ) -> AgenticTurn:
        return self._turns.pop(0)


@pytest.mark.parametrize("fixture_name", ["single_step.json", "parallel_multi_step.json"])
@pytest.mark.asyncio
async def test_agent_parity(
    fixture_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fix = json.loads((FIXTURES / fixture_name).read_text())
    canned_turns = [_agentic_turn_from_canned(t) for t in fix["llm_canned_turns"]]
    expected_seq: list[dict[str, Any]] = fix["expected_tool_call_sequence"]

    # Build Planner with replay LLM
    llm = _ReplayLLM(canned_turns)
    planner = Planner(llm=llm)
    plan = await planner.plan_from_messages(fix["input_messages"])

    # Verify ToolCall extraction
    actual_seq = [
        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
        for tc in plan.steps
    ]
    assert actual_seq == expected_seq, (
        f"ToolCall sequence mismatch for {fixture_name}\n"
        f"  expected: {expected_seq}\n"
        f"  actual:   {actual_seq}"
    )

    # Now Executor must dispatch them in the right shape
    dispatched: list[str] = []

    async def fake_exec(
        tc: ToolCall,
        tf: dict[str, Any],
        req: GenerationRequest,
        retriever: Any,
        llm_arg: Any,
    ) -> tuple[list[RetrievedChunk], str]:
        dispatched.append(tc.id)
        return ([], f"result_{tc.id}")

    monkeypatch.setattr("services.agent.executor.execute_tool_call", fake_exec)

    executor = Executor(retriever=object(), llm=object())
    req = GenerationRequest(query="parity-test")
    results = await executor.execute_plan(plan, {}, req)

    assert len(results) == len(plan.steps)
    # All expected tool call IDs were dispatched (order may vary within waves
    # due to asyncio.gather scheduling, but set membership is byte-stable)
    assert set(dispatched) == {tc["id"] for tc in expected_seq}
