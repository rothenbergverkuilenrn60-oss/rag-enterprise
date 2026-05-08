# =============================================================================
# tests/unit/test_agentic_turn_models.py
# Phase 11-01 Task 1 — provider-neutral agentic dataclasses (AGENT-01)
# Covers behavior tests 1–6 from the plan.
# =============================================================================
from __future__ import annotations

import pytest
from pydantic import ValidationError

from utils.models import AgenticTurn, ToolCall


@pytest.mark.unit
class TestToolCall:
    def test_constructs_with_required_and_optional_fields(self) -> None:
        # Behavior Test 1
        call = ToolCall(
            id="call_x",
            name="search_knowledge_base",
            arguments={"query": "q"},
        )
        assert call.id == "call_x"
        assert call.name == "search_knowledge_base"
        assert call.arguments == {"query": "q"}

    def test_arguments_default_to_empty_dict(self) -> None:
        call = ToolCall(id="call_y", name="noop")
        assert call.arguments == {}

    def test_frozen_assignment_is_rejected(self) -> None:
        # Behavior Test 2 — frozen via Pydantic V2 ConfigDict.
        # Pydantic V2 raises ValidationError on frozen mutation.
        call = ToolCall(id="call_z", name="x", arguments={})
        with pytest.raises(ValidationError):
            call.id = "mutated"  # type: ignore[misc]


@pytest.mark.unit
class TestAgenticTurn:
    def test_constructs_with_full_fields(self) -> None:
        # Behavior Test 3
        turn = AgenticTurn(
            text="hi",
            tool_calls=[],
            stop_reason="text_only",
            raw_assistant_msg={"role": "assistant", "content": "hi"},
            usage_input_tokens=10,
            usage_output_tokens=20,
        )
        assert turn.text == "hi"
        assert turn.tool_calls == []
        assert turn.stop_reason == "text_only"
        assert turn.raw_assistant_msg == {"role": "assistant", "content": "hi"}
        assert turn.usage_input_tokens == 10
        assert turn.usage_output_tokens == 20

    def test_invalid_stop_reason_raises(self) -> None:
        # Behavior Test 4 — Literal-typed stop_reason rejects unknown value
        with pytest.raises(ValidationError):
            AgenticTurn(
                text="",
                tool_calls=[],
                stop_reason="invalid_value",  # type: ignore[arg-type]
                raw_assistant_msg={},
            )

    def test_model_dump_round_trips(self) -> None:
        # Behavior Test 5
        original = AgenticTurn(
            text="answer",
            tool_calls=[ToolCall(id="c1", name="t1", arguments={"k": 1})],
            stop_reason="tool_use",
            raw_assistant_msg={"role": "assistant", "content": [{"type": "text", "text": "answer"}]},
            usage_input_tokens=42,
            usage_output_tokens=7,
        )
        dumped = original.model_dump()
        roundtripped = AgenticTurn.model_validate(dumped)
        assert roundtripped == original

    def test_tool_calls_preserve_order(self) -> None:
        # Behavior Test 6
        turn = AgenticTurn(
            text="",
            tool_calls=[
                ToolCall(id="call_a", name="t_a", arguments={}),
                ToolCall(id="call_b", name="t_b", arguments={}),
            ],
            stop_reason="tool_use",
            raw_assistant_msg={},
        )
        assert turn.tool_calls[0].id == "call_a"
        assert turn.tool_calls[1].id == "call_b"

    def test_all_valid_stop_reasons_accepted(self) -> None:
        # Defensive: all four locked literals must be acceptable
        for reason in ("text_only", "tool_use", "max_tokens", "error"):
            t = AgenticTurn(
                text="",
                tool_calls=[],
                stop_reason=reason,  # type: ignore[arg-type]
                raw_assistant_msg={},
            )
            assert t.stop_reason == reason

    def test_frozen_assignment_is_rejected(self) -> None:
        turn = AgenticTurn(
            text="",
            tool_calls=[],
            stop_reason="text_only",
            raw_assistant_msg={},
        )
        with pytest.raises(ValidationError):
            turn.text = "mutated"  # type: ignore[misc]
