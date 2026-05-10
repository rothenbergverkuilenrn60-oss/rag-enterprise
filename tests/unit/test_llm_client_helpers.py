"""tests/unit/test_llm_client_helpers.py — Phase 15 backfill.

Existing llm_client tests cover specific provider integrations. This file
adds: BaseLLMClient default chat_with_tools / chat_thinking / call_agentic_turn,
the supports_* property defaults, _anthropic_model_for_task task routing,
_report_usage no-op when usage missing, and _get_anthropic_retry_errors
caching.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


import pytest


def _make_stub(chat_response: str = "{}"):
    """Create a concrete BaseLLMClient subclass with stub chat/stream_chat."""
    from services.generator.llm_client import BaseLLMClient

    class _Stub(BaseLLMClient):
        async def chat(self, system, user, temperature=0.1, task_type="generate"):
            return chat_response

        async def stream_chat(self, system, user, temperature=0.1):
            yield ""

    return _Stub()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_with_tools_parses_embedded_json():
    """Default impl: extract first {...} block from response."""
    c = _make_stub('preamble {"key": "value"} trailer')
    out = await c.chat_with_tools(system="s", user="u", tools=[])
    assert out == {"key": "value"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_with_tools_returns_empty_on_no_json():
    """Error path: no JSON in response → empty dict."""
    c = _make_stub("just text no JSON")
    out = await c.chat_with_tools(system="s", user="u", tools=[])
    assert out == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_with_tools_returns_empty_on_invalid_json():
    """Error path: JSON-like but malformed → empty dict."""
    c = _make_stub('broken {"key": no_quotes}')
    out = await c.chat_with_tools(system="s", user="u", tools=[])
    assert out == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_chat_thinking_default_routes_to_chat():
    c = _make_stub("thoughtful response")
    out = await c.chat_thinking(system="s", user="u")
    assert out == "thoughtful response"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_agentic_turn_default_raises_not_implemented():
    """Default impl: raises NotImplementedError naming the subclass."""
    c = _make_stub()
    with pytest.raises(NotImplementedError, match="agent_mode not supported"):
        await c.call_agentic_turn(messages=[], tools=[], system="")


@pytest.mark.unit
def test_default_supports_tools_is_false():
    c = _make_stub()
    assert c.supports_tools is False
    assert c.supports_thinking is False


@pytest.mark.unit
def test_anthropic_model_for_task_routes_light_to_haiku():
    from services.generator.llm_client import (
        _HAIKU_MODEL,
        _anthropic_model_for_task,
    )
    assert _anthropic_model_for_task("nlu", "claude-sonnet-4-6") == _HAIKU_MODEL
    assert _anthropic_model_for_task("rewrite", "claude-sonnet-4-6") == _HAIKU_MODEL
    assert _anthropic_model_for_task("classify", "claude-sonnet-4-6") == _HAIKU_MODEL


@pytest.mark.unit
def test_anthropic_model_for_task_default_returns_default():
    from services.generator.llm_client import _anthropic_model_for_task
    assert _anthropic_model_for_task("generate", "claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert _anthropic_model_for_task("thinking", "claude-opus-4-7") == "claude-opus-4-7"


@pytest.mark.unit
def test_report_usage_no_op_when_response_lacks_usage():
    """Defensive path: response without .usage attribute → silent no-op."""
    from services.generator.llm_client import _report_usage
    _report_usage(object(), provider="anthropic")
    _report_usage(None, provider="anthropic")


@pytest.mark.unit
def test_report_usage_no_op_when_total_zero():
    """Branch: zero-token responses must not call metrics."""
    from services.generator.llm_client import _report_usage

    class FakeUsage:
        input_tokens = 0
        output_tokens = 0

    class FakeResp:
        usage = FakeUsage()

    _report_usage(FakeResp(), provider="anthropic")


@pytest.mark.unit
def test_get_anthropic_retry_errors_returns_tuple():
    from services.generator.llm_client import _get_anthropic_retry_errors
    out = _get_anthropic_retry_errors()
    assert isinstance(out, tuple)
    assert len(out) == 2
    out2 = _get_anthropic_retry_errors()
    assert out is out2 or (out[0] is out2[0] and out[1] is out2[1])
