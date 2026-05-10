"""Regression tests for v1.4.2: Anthropic→OpenAI tool_result message translation.

Bug (caught at v1.4.1+1day, by docker-prod smoke vs Groq):
    pipeline.py:816 emits Anthropic-shape tool result wrapper
        {"role":"user", "content":[{"type":"tool_result", "tool_use_id":..., "content":...}]}
    per project convention.

    OpenAILLMClient.call_agentic_turn passed messages through unchanged to
    chat.completions.create. Strict OpenAI-compat servers (Groq, DeepSeek,
    Qwen via DashScope) reject this with HTTP 400::

        "messages.N.content.0.type": value is not one of the allowed values
                                     ['text', 'image_url', 'document']

    Net effect: every iter≥2 of the agent tool-use loop crashes after the
    first tool round-trip; final answer becomes the v1.3 graceful-degrade
    fallback ("抱歉，智能助手在处理您的请求时遇到了错误").

Fix (this patch):
    `_translate_tool_result_message` helper translates each Anthropic tool_result
    wrapper into one OpenAI ``{role:"tool", tool_call_id, content:str}`` per
    tool_result block, before submitting to the OpenAI SDK.

    Anthropic adapter is unchanged — Anthropic API natively accepts the wrapper.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── _translate_tool_result_message helper unit tests ─────────────────────────


def test_translate_passthrough_for_non_user_role() -> None:
    """System/assistant/tool messages are passed through unchanged."""
    from services.generator.llm_client import _translate_tool_result_message

    for role in ("system", "assistant", "tool"):
        msg = {"role": role, "content": "anything"}
        assert _translate_tool_result_message(msg) is None


def test_translate_passthrough_for_user_string_content() -> None:
    """Plain user text messages are passed through unchanged."""
    from services.generator.llm_client import _translate_tool_result_message

    msg = {"role": "user", "content": "hello"}
    assert _translate_tool_result_message(msg) is None


def test_translate_passthrough_for_mixed_content_blocks() -> None:
    """User messages whose content list does NOT consist solely of tool_result
    blocks (e.g., text + image) must pass through unchanged — translation is
    only valid when the entire wrapper is a tool_result batch."""
    from services.generator.llm_client import _translate_tool_result_message

    msg = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
            {"type": "text", "text": "follow-up question"},
        ],
    }
    assert _translate_tool_result_message(msg) is None


def test_translate_single_tool_result_string_content() -> None:
    """Single tool_result with string content → single OpenAI tool message."""
    from services.generator.llm_client import _translate_tool_result_message

    msg = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "call_abc", "content": "found 3 chunks"},
        ],
    }
    out = _translate_tool_result_message(msg)
    assert out == [
        {"role": "tool", "tool_call_id": "call_abc", "content": "found 3 chunks"},
    ]


def test_translate_multiple_tool_results_fan_in() -> None:
    """Parallel tool_call burst → one OpenAI tool message per result, ordered."""
    from services.generator.llm_client import _translate_tool_result_message

    msg = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "c0", "content": "result0"},
            {"type": "tool_result", "tool_use_id": "c1", "content": "result1"},
            {"type": "tool_result", "tool_use_id": "c2", "content": "result2"},
            {"type": "tool_result", "tool_use_id": "c3", "content": "result3"},
        ],
    }
    out = _translate_tool_result_message(msg)
    assert len(out) == 4
    for i, m in enumerate(out):
        assert m["role"] == "tool"
        assert m["tool_call_id"] == f"c{i}"
        assert m["content"] == f"result{i}"


def test_translate_tool_result_with_anthropic_content_blocks() -> None:
    """Some callers pass content as Anthropic-style block list (text-blocks +
    other types). Translator must flatten into a single string per OpenAI spec.
    """
    from services.generator.llm_client import _translate_tool_result_message

    msg = {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "c0",
                "content": [
                    {"type": "text", "text": "chunk 1: ..."},
                    {"type": "text", "text": "chunk 2: ..."},
                ],
            },
        ],
    }
    out = _translate_tool_result_message(msg)
    assert len(out) == 1
    assert out[0]["role"] == "tool"
    assert out[0]["tool_call_id"] == "c0"
    # Content must be a string, parts joined by newline.
    assert isinstance(out[0]["content"], str)
    assert "chunk 1" in out[0]["content"]
    assert "chunk 2" in out[0]["content"]


def test_translate_handles_empty_tool_use_id_safely() -> None:
    """Defensive: missing tool_use_id should not crash; empty string is sent.
    OpenAI will reject empty tool_call_id at API layer, but we surface that
    clearly rather than crashing here."""
    from services.generator.llm_client import _translate_tool_result_message

    msg = {
        "role": "user",
        "content": [
            {"type": "tool_result", "content": "orphaned"},
        ],
    }
    out = _translate_tool_result_message(msg)
    assert out == [
        {"role": "tool", "tool_call_id": "", "content": "orphaned"},
    ]


# ─── End-to-end behavior — call_agentic_turn integrates the translation ──────


@pytest.fixture
def openai_client_with_mock_http() -> tuple[Any, MagicMock]:
    """Real OpenAILLMClient with mocked AsyncOpenAI underneath."""
    from services.generator import llm_client as mod

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake_msg = SimpleNamespace(content="ok", tool_calls=None, role="assistant")
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
async def test_call_agentic_turn_translates_tool_result_messages(
    openai_client_with_mock_http: tuple[Any, MagicMock],
) -> None:
    """When the caller passes an Anthropic-shape tool_result wrapper in
    `messages`, OpenAILLMClient.call_agentic_turn must translate it before
    sending to chat.completions.create. Otherwise Groq/DeepSeek/Qwen reject."""
    client, fake = openai_client_with_mock_http

    tools = [
        {
            "name": "search_knowledge_base",
            "description": "Search the KB",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    messages = [
        {"role": "user", "content": "What is X?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_oai_0",
                    "type": "function",
                    "function": {
                        "name": "search_knowledge_base",
                        "arguments": json.dumps({"query": "X"}),
                    },
                }
            ],
        },
        # ↓ The breaking message — Anthropic wrapper shape from pipeline.py:816
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_oai_0",
                    "content": "found chunk: X is ...",
                }
            ],
        },
    ]

    await client.call_agentic_turn(
        messages=messages, tools=tools, system="be terse"
    )

    # Inspect what was actually sent to the OpenAI SDK.
    fake.chat.completions.create.assert_called_once()
    sent_messages = fake.chat.completions.create.call_args.kwargs["messages"]

    # Expected shape: [system, user, assistant(tool_calls), tool(translated)]
    # — 4 messages, NOT 4 with the broken Anthropic wrapper still inside.
    assert sent_messages[0]["role"] == "system"
    assert sent_messages[1]["role"] == "user"
    assert sent_messages[2]["role"] == "assistant"
    # The critical assertion — the Anthropic wrapper is GONE; replaced by
    # role:"tool" with tool_call_id and string content.
    assert sent_messages[3]["role"] == "tool", (
        f"v1.4.2 regression: tool_result wrapper not translated to role:tool. "
        f"Got: {sent_messages[3]!r}"
    )
    assert sent_messages[3]["tool_call_id"] == "call_oai_0"
    assert sent_messages[3]["content"] == "found chunk: X is ..."

    # Also verify NO message in the sent list has content with type="tool_result"
    # (the exact pattern Groq rejects).
    for m in sent_messages:
        c = m.get("content")
        if isinstance(c, list):
            for block in c:
                if isinstance(block, dict):
                    assert block.get("type") != "tool_result", (
                        f"v1.4.2 regression: content block with type=tool_result "
                        f"reached the OpenAI SDK call. This is the exact shape "
                        f"Groq/DeepSeek/Qwen reject with HTTP 400. msg={m!r}"
                    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_agentic_turn_translates_parallel_tool_result_burst(
    openai_client_with_mock_http: tuple[Any, MagicMock],
) -> None:
    """Multi-tool parallel burst: one Anthropic wrapper with N tool_result
    blocks must explode into N OpenAI tool messages."""
    client, fake = openai_client_with_mock_http

    tools = [
        {
            "name": "search_knowledge_base",
            "description": "Search KB",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    messages = [
        {"role": "user", "content": "fan-out query"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": "search_knowledge_base",
                              "arguments": json.dumps({"q": f"shard{i}"})}}
                for i in range(4)
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": f"c{i}",
                 "content": f"shard{i} result"}
                for i in range(4)
            ],
        },
    ]

    await client.call_agentic_turn(
        messages=messages, tools=tools, system="x"
    )

    sent = fake.chat.completions.create.call_args.kwargs["messages"]
    # 1 system + 1 user + 1 assistant + 4 tool = 7
    assert len(sent) == 7, f"expected 7 messages after fan-in translation, got {len(sent)}"
    tool_msgs = [m for m in sent if m["role"] == "tool"]
    assert len(tool_msgs) == 4
    for i, tm in enumerate(tool_msgs):
        assert tm["tool_call_id"] == f"c{i}"
        assert tm["content"] == f"shard{i} result"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_agentic_turn_does_not_translate_plain_user_text(
    openai_client_with_mock_http: tuple[Any, MagicMock],
) -> None:
    """First-turn case (no tool round-trip yet): user message is plain text.
    Must pass through verbatim."""
    client, fake = openai_client_with_mock_http

    await client.call_agentic_turn(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        system="x",
    )

    sent = fake.chat.completions.create.call_args.kwargs["messages"]
    assert sent == [
        {"role": "system", "content": "x"},
        {"role": "user", "content": "hello"},
    ]
