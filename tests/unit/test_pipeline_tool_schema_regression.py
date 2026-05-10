"""Regression tests for v1.4.1: tool schema double-conversion bug.

Bug (caught at v1.4.0 + 1 day, by docker-prod smoke):
    services/pipeline.py used `schemas_for(self._llm.provider_name)` at three
    callsites. For an OpenAI client this returns OpenAI-shape tool dicts
    `{"type": "function", "function": {"name": ..., ...}}`.

    But every `LLMClient.call_agentic_turn` implementation EXPECTS Anthropic-
    shape input — `{"name": ..., "description": ..., "input_schema": ...}` —
    and converts to wire format internally (see llm_client.py:411-418).

    Result: `KeyError: 'name'` on every real LLM agent call (SSE + non-SSE).

    Phase 18 SSE tests used class-level stub LLMs that bypass `call_agentic_turn`
    entirely, so the bug never surfaced in CI. Live OpenAI integration test
    `test_agent_pipeline_runs_real_tool_use_loop_on_openai` is gated by
    `pytest.mark.integration` and was skipped during the v1.4.0 regression run.

Two regression vectors:
  1. Source invariant: assert pipeline.py uses literal "anthropic" string at
     all schemas_for callsites — not provider_name.
  2. Behavior: drive Planner.plan_from_messages with a real OpenAILLMClient
     (HTTP mocked) and registry-shaped Anthropic tools; assert no KeyError.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ─── Vector 1: source invariant ────────────────────────────────────────────────


def test_pipeline_schemas_for_uses_anthropic_literal() -> None:
    """All `schemas_for(...)` callsites in services/pipeline.py must pass the
    literal string "anthropic" — never `self._llm.provider_name` or any other
    dynamic value — because `call_agentic_turn` expects Anthropic-shape input
    regardless of the underlying LLM provider.
    """
    src = (PROJECT_ROOT / "services" / "pipeline.py").read_text()
    pattern = re.compile(r"schemas_for\(\s*([^,\)]+?),\s*names=", re.MULTILINE)
    args = pattern.findall(src)

    assert args, "no schemas_for(...) callsites found in services/pipeline.py"
    for arg in args:
        arg_clean = arg.strip()
        assert arg_clean == '"anthropic"', (
            f"schemas_for() called with {arg_clean!r}; must be the literal "
            f'"anthropic". call_agentic_turn always expects Anthropic-shape '
            f"tools and converts to wire format internally — passing the LLM "
            f"provider name causes KeyError on real LLM calls."
        )


def test_pipeline_does_not_pass_provider_name_to_schemas_for() -> None:
    """Inverse of the above: assert the broken pattern is gone."""
    src = (PROJECT_ROOT / "services" / "pipeline.py").read_text()
    assert "self._llm.provider_name" not in src, (
        "services/pipeline.py still references self._llm.provider_name. "
        "This was the v1.4.0 bug source — call_agentic_turn expects Anthropic "
        "shape, not the provider's wire shape."
    )


# ─── Vector 2: behavior — real OpenAI client with HTTP-layer mock ─────────────


@pytest.fixture
def openai_client_with_mock_http() -> tuple[Any, MagicMock]:
    """Real OpenAILLMClient with a mocked AsyncOpenAI underneath. The mock
    intercepts `chat.completions.create` so no network call is made and we
    avoid needing an API key."""
    from services.generator import llm_client as mod

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    # Default: text-only response (no tool_calls) so the agent loop exits
    # cleanly and the test doesn't have to mock retrievers.
    fake_msg = SimpleNamespace(
        content="ok",
        tool_calls=None,
        role="assistant",
    )
    fake_choice = SimpleNamespace(message=fake_msg, finish_reason="stop")
    fake_response = SimpleNamespace(
        choices=[fake_choice],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    fake.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("openai.AsyncOpenAI", return_value=fake):
        client = mod.OpenAILLMClient()
    return client, fake


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_agentic_turn_with_anthropic_shape_tools_does_not_raise(
    openai_client_with_mock_http: tuple[Any, MagicMock],
) -> None:
    """call_agentic_turn must accept Anthropic-shape tools (`{name, description,
    input_schema}`) without raising KeyError. This is the contract that
    pipeline.py:858 (and 787, 1087) violated by passing OpenAI-shape input."""
    client, fake = openai_client_with_mock_http

    # Anthropic-shape tools — the contract call_agentic_turn was designed for.
    tools = [
        {
            "name": "search_knowledge_base",
            "description": "Search the enterprise KB",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]

    # Should not raise KeyError — converts internally to OpenAI shape.
    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        system="be terse",
    )
    assert turn is not None

    # Verify chat.completions.create was called with OpenAI-shape tools
    # produced by the internal conversion.
    fake.chat.completions.create.assert_called_once()
    kwargs = fake.chat.completions.create.call_args.kwargs
    assert "tools" in kwargs
    openai_tools = kwargs["tools"]
    assert openai_tools[0]["type"] == "function"
    assert openai_tools[0]["function"]["name"] == "search_knowledge_base"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_agentic_turn_with_openai_shape_tools_raises_keyerror(
    openai_client_with_mock_http: tuple[Any, MagicMock],
) -> None:
    """Documents the input-shape contract: OpenAI-shape input is REJECTED.
    If pipeline.py ever regresses to passing `provider_name` again, the
    OpenAI-shape tools that schemas_for("openai") returns will trigger this
    same KeyError. This test fails closed if the contract changes silently.
    """
    client, _ = openai_client_with_mock_http

    # OpenAI-shape tools — the wrong shape, what the bug produced.
    bad_tools = [
        {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": "Search the enterprise KB",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]

    with pytest.raises(KeyError, match="name"):
        await client.call_agentic_turn(
            messages=[{"role": "user", "content": "hello"}],
            tools=bad_tools,
            system="be terse",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_registry_anthropic_shape_satisfies_call_agentic_turn(
    openai_client_with_mock_http: tuple[Any, MagicMock],
) -> None:
    """The full chain: ToolRegistry.schemas_for("anthropic") output must be
    consumable by call_agentic_turn without conversion. This is what
    pipeline.py now does (post v1.4.1 fix)."""
    # Force-load the registry so RetrieveTool etc. are registered.
    import services.agent.tools  # noqa: F401
    from services.agent.tools.registry import get_tool_registry

    client, fake = openai_client_with_mock_http
    tools = get_tool_registry().schemas_for("anthropic", names=None)
    assert tools, "registry returned no tools — fixture problem, not regression"

    # Each schema must have the Anthropic-shape keys call_agentic_turn reads.
    for t in tools:
        assert "name" in t, f"registry schema missing 'name' key: {t}"
        assert "description" in t, f"registry schema missing 'description' key: {t}"
        # call_agentic_turn falls back to "parameters" if "input_schema" absent.
        assert "input_schema" in t or "parameters" in t

    # End-to-end: feed registry output directly to call_agentic_turn.
    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "hello"}],
        tools=tools,
        system="be terse",
    )
    assert turn is not None
