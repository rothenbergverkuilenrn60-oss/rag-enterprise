"""Unit tests for BaseLLMClient.call_agentic_turn + Anthropic/OpenAI overrides.

D-04 strategy: pure mock against recorded wire-format JSON fixtures.
No live API calls. Deterministic. CI-friendly.

This file evolves across Plan 11-03 tasks:
  - Task 1: anthropic adapter parametrize + cross-cutting (disable_parallel_tool_use)
  - Task 2: openai adapter parametrize + cross-cutting (parallel_tool_calls,
            tools shape conversion, system prepending)
  - Task 3: Ollama regression test + final polish
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.models import AgenticTurn

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "agentic_turn"

# Anthropic block.input is a dict (the model's tool arguments). The adapter calls
# `dict(block.input)` on it, which requires the value to be a real mapping — NOT
# a SimpleNamespace. _to_namespace therefore preserves any field whose key is in
# this set as a raw dict instead of recursively converting it.
#
# OpenAI's `function.arguments` is a JSON-encoded STRING in the wire shape (the
# adapter does `json.loads` on it), so it does NOT need preservation here.
_RAW_DICT_FIELDS = {"input"}

# A minimal tool definition matching the project's _AGENT_TOOLS shape (Anthropic-style)
_TOOL: dict[str, Any] = {
    "name": "search_knowledge_base",
    "description": "Search the enterprise KB",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer", "default": 5},
        },
        "required": ["query"],
    },
}


def _to_namespace(d: Any, _key: str | None = None) -> Any:
    """Recursively convert a JSON dict to nested SimpleNamespace so
    SDK-style attribute access (resp.content[0].type, etc) works.

    Special-case: any field whose key is in `_RAW_DICT_FIELDS` is preserved as
    a raw dict (not converted to SimpleNamespace), because the adapter consumes
    it via `dict(block.input)` which requires a mapping, not an attribute
    namespace.
    """
    if isinstance(d, dict):
        if _key in _RAW_DICT_FIELDS:
            # Preserve as raw dict; do NOT recurse — Anthropic tool input is a
            # flat JSON-able mapping per the wire spec.
            return d
        return SimpleNamespace(**{k: _to_namespace(v, _key=k) for k, v in d.items()})
    if isinstance(d, list):
        return [_to_namespace(v, _key=_key) for v in d]
    return d


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


# ───── Anthropic adapter ─────────────────────────────────────────────────────

@pytest.fixture
def anthropic_client() -> Any:
    """Bypass the AsyncAnthropic constructor so we don't need an API key.
    Returns (AnthropicLLMClient, fake) where fake is the mocked SDK client.

    Note: we do NOT monkeypatch the model-name attribute. AnthropicLLMClient
    reads `settings.anthropic_model` (or its own `_default_model` instance attr)
    at call time; because the underlying `Anthropic` SDK class is fully replaced
    by `fake` (a MagicMock), the model string is irrelevant to the test path —
    `fake.messages.create(...)` returns the stubbed response regardless.
    """
    from services.generator import llm_client as mod
    fake = MagicMock()
    fake.messages = MagicMock()
    fake.messages.create = AsyncMock()
    with patch("anthropic.AsyncAnthropic", return_value=fake):
        client = mod.AnthropicLLMClient()
    return client, fake


@pytest.mark.unit
@pytest.mark.parametrize("fixture_name,expected", [
    ("anthropic_text_only.json",
        {"len_tool_calls": 0, "stop_reason": "text_only", "input_tokens": 320, "output_tokens": 48}),
    ("anthropic_single_tool_use.json",
        {"len_tool_calls": 1, "stop_reason": "tool_use", "input_tokens": 280, "output_tokens": 62,
         "first_tool_id": "toolu_01ABCsingle", "first_tool_name": "search_knowledge_base",
         "first_tool_args": {"query": "产假天数规定", "top_k": 5}}),
    ("anthropic_two_parallel_tool_use.json",
        {"len_tool_calls": 2, "stop_reason": "tool_use", "input_tokens": 305, "output_tokens": 98,
         "tool_ids_in_order": ["toolu_02parallelA", "toolu_02parallelB"]}),
    ("anthropic_max_iterations.json",
        {"len_tool_calls": 0, "stop_reason": "max_tokens", "input_tokens": 4096, "output_tokens": 1024}),
])
@pytest.mark.asyncio
async def test_anthropic_call_agentic_turn(
    anthropic_client: Any, fixture_name: str, expected: dict[str, Any],
) -> None:
    client, fake = anthropic_client
    fake.messages.create.return_value = _to_namespace(_load(fixture_name))

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "查询产假规定"}],
        tools=[_TOOL],
        system="你是助手",
    )

    assert isinstance(turn, AgenticTurn)
    assert len(turn.tool_calls) == expected["len_tool_calls"]
    assert turn.stop_reason == expected["stop_reason"]
    assert turn.usage_input_tokens == expected["input_tokens"]
    assert turn.usage_output_tokens == expected["output_tokens"]
    if "first_tool_id" in expected:
        assert turn.tool_calls[0].id == expected["first_tool_id"]
        assert turn.tool_calls[0].name == expected["first_tool_name"]
        assert turn.tool_calls[0].arguments == expected["first_tool_args"]
    if "tool_ids_in_order" in expected:
        assert [tc.id for tc in turn.tool_calls] == expected["tool_ids_in_order"]
    assert turn.raw_assistant_msg["role"] == "assistant"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_disable_parallel_tool_use_explicit(anthropic_client: Any) -> None:
    """parallel_tool_calls=True ↔ disable_parallel_tool_use=False (and vice versa).

    Verifies AGENT-02 acceptance #2: Anthropic adapter sets the explicit kwarg
    for auditability.
    """
    client, fake = anthropic_client
    fake.messages.create.return_value = _to_namespace(_load("anthropic_text_only.json"))

    await client.call_agentic_turn(
        messages=[{"role": "user", "content": "q"}], tools=[_TOOL], system="s",
        parallel_tool_calls=True,
    )
    kwargs = fake.messages.create.call_args.kwargs
    assert "disable_parallel_tool_use" in kwargs
    assert kwargs["disable_parallel_tool_use"] is False  # parallel=True ↔ disable=False

    fake.messages.create.reset_mock()
    fake.messages.create.return_value = _to_namespace(_load("anthropic_text_only.json"))
    await client.call_agentic_turn(
        messages=[{"role": "user", "content": "q"}], tools=[_TOOL], system="s",
        parallel_tool_calls=False,
    )
    assert fake.messages.create.call_args.kwargs["disable_parallel_tool_use"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_cached_system_used(anthropic_client: Any) -> None:
    """Prompt Caching preserved: messages.create is called with self._cached_system(system)."""
    client, fake = anthropic_client
    fake.messages.create.return_value = _to_namespace(_load("anthropic_text_only.json"))
    await client.call_agentic_turn(
        messages=[{"role": "user", "content": "q"}], tools=[_TOOL], system="SYS_PROMPT",
    )
    sent_system = fake.messages.create.call_args.kwargs["system"]
    # _cached_system returns a list with a cache_control-marked text block
    assert isinstance(sent_system, list)
    assert sent_system[0]["text"] == "SYS_PROMPT"
    assert sent_system[0].get("cache_control", {}).get("type") == "ephemeral"
