"""Coverage tests for services/generator/llm_client.py per TEST-09 (Phase 22 SC2).

Targets:
- RateLimitError (429) / OverloadedError / RetryError / APIConnectionError branches
- across both AnthropicLLMClient.call_agentic_turn and OpenAILLMClient.call_agentic_turn
- AnthropicLLMClient._handle_error error-classification branches
- OpenAILLMClient.chat retry-then-success and raise-after-max-attempts (D-15)
- get_llm_client factory all provider branches

Happy-path reuses tests/unit/fixtures/agent_parity/{single_step,parallel_multi_step}.json (CF-03).
Failure paths use inline side_effect raising SDK exceptions (D-13).
Tenacity wait monkeypatched to wait_none() per retry test (D-15).
Mock at consumer path (services.generator.llm_client.<dep>) only — CF-02.
No production-code changes (CF-01).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import tenacity

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

import anthropic
import openai

from utils.models import AgenticTurn

# ---------------------------------------------------------------------------
# SDK exception factories (D-13 inline construction)
# ---------------------------------------------------------------------------
_TEST_REQUEST = httpx.Request("POST", "https://api.test")
_RESP_429 = httpx.Response(429, request=_TEST_REQUEST)
_RESP_529 = httpx.Response(529, request=_TEST_REQUEST)


def _make_anthropic_rate_limit() -> anthropic.RateLimitError:
    return anthropic.RateLimitError(message="429 rate limited", response=_RESP_429, body={})


def _make_anthropic_internal_server() -> anthropic.InternalServerError:
    """InternalServerError covers the OverloadedError (529) branch — no OverloadedError in this SDK version."""
    return anthropic.InternalServerError(message="overloaded 529", response=_RESP_529, body={})


def _make_anthropic_conn_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=_TEST_REQUEST)


def _make_openai_rate_limit() -> openai.RateLimitError:
    return openai.RateLimitError(message="429 rate limited", response=_RESP_429, body={})


def _make_openai_conn_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=_TEST_REQUEST)


# ---------------------------------------------------------------------------
# Parametrize tables (D-14)
# Columns: (provider, exc_name, exc_factory)
# ---------------------------------------------------------------------------
_RETRY_FAILURE_PARAMS = [
    pytest.param(
        "anthropic", "RateLimitError", _make_anthropic_rate_limit,
        id="anthropic-RateLimitError",
    ),
    pytest.param(
        "anthropic", "OverloadedError", _make_anthropic_internal_server,
        id="anthropic-OverloadedError",
    ),
    pytest.param(
        "anthropic", "APIConnectionError", _make_anthropic_conn_error,
        id="anthropic-APIConnectionError",
    ),
    pytest.param(
        "openai", "RateLimitError", _make_openai_rate_limit,
        id="openai-RateLimitError",
    ),
    pytest.param(
        "openai", "APIConnectionError", _make_openai_conn_error,
        id="openai-APIConnectionError",
    ),
]

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
_RAW_DICT_FIELDS = {"input"}


def _to_namespace(d: Any, _key: str | None = None) -> Any:
    """Recursively convert a JSON dict to nested SimpleNamespace for SDK-style attribute access."""
    if isinstance(d, dict):
        if _key in _RAW_DICT_FIELDS:
            return d
        return SimpleNamespace(**{k: _to_namespace(v, _key=k) for k, v in d.items()})
    if isinstance(d, list):
        return [_to_namespace(v, _key=_key) for v in d]
    return d


def _load_fixture(name: str) -> dict[str, Any]:
    fixture_dir = Path(__file__).parent / "fixtures" / "agentic_turn"
    return json.loads((fixture_dir / name).read_text(encoding="utf-8"))


def _load_parity_fixture(name: str) -> dict[str, Any]:
    """Load from agent_parity fixture dir (CF-03 happy-path reuse)."""
    fixture_dir = Path(__file__).parent / "fixtures" / "agent_parity"
    return json.loads((fixture_dir / name).read_text(encoding="utf-8"))


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


# ---------------------------------------------------------------------------
# --- AnthropicLLMClient.call_agentic_turn happy-path ---
# ---------------------------------------------------------------------------

@pytest.fixture
def anthropic_client() -> Any:
    """AnthropicLLMClient with anthropic.AsyncAnthropic patched at consumer-import site.

    CF-02: patch at 'anthropic.AsyncAnthropic' (the consumer-path binding used inside
    AnthropicLLMClient.__init__'s local `import anthropic` statement). This is
    equivalent to consumer-path patching because the local import resolves to
    sys.modules['anthropic'].AsyncAnthropic at call time.
    """
    from services.generator import llm_client as mod

    fake = MagicMock()
    fake.messages = MagicMock()
    fake.messages.create = AsyncMock()

    with patch("anthropic.AsyncAnthropic", return_value=fake):
        client = mod.AnthropicLLMClient()
    return client, fake


@pytest.fixture
def anthropic_fixture_single_step() -> dict[str, Any]:
    """CF-03: load agent_parity single_step fixture for Anthropic happy-path."""
    return _load_parity_fixture("single_step.json")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_call_agentic_turn_single_step_happy_path(
    anthropic_client: Any,
    anthropic_fixture_single_step: dict[str, Any],
) -> None:
    """Happy-path: single tool use turn using agentic_turn wire fixture (CF-03)."""
    client, fake = anthropic_client
    # Use agentic_turn wire fixture (has correct Anthropic SDK response shape)
    fake.messages.create.return_value = _to_namespace(_load_fixture("anthropic_single_tool_use.json"))

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": anthropic_fixture_single_step["input_messages"][-1]["content"]}],
        tools=[_TOOL],
        system=anthropic_fixture_single_step["input_messages"][0]["content"],
    )

    assert isinstance(turn, AgenticTurn)
    assert turn.stop_reason == "tool_use"
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "search_knowledge_base"
    assert turn.tool_calls[0].id == "toolu_01ABCsingle"
    assert turn.raw_assistant_msg["role"] == "assistant"
    assert turn.usage_input_tokens == 280
    assert turn.usage_output_tokens == 62


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_call_agentic_turn_text_only(anthropic_client: Any) -> None:
    """Anthropic text-only response: stop_reason text_only, no tool_calls."""
    client, fake = anthropic_client
    fake.messages.create.return_value = _to_namespace(_load_fixture("anthropic_text_only.json"))

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        system="sys",
    )
    assert isinstance(turn, AgenticTurn)
    assert turn.stop_reason == "text_only"
    assert len(turn.tool_calls) == 0
    assert len(turn.text) > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_call_agentic_turn_two_parallel_tools(anthropic_client: Any) -> None:
    """Anthropic parallel tool use: two ToolCall objects returned."""
    client, fake = anthropic_client
    fake.messages.create.return_value = _to_namespace(_load_fixture("anthropic_two_parallel_tool_use.json"))

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "parallel q"}],
        tools=[_TOOL],
        system="sys",
    )
    assert isinstance(turn, AgenticTurn)
    assert turn.stop_reason == "tool_use"
    assert len(turn.tool_calls) == 2
    tool_ids = {tc.id for tc in turn.tool_calls}
    assert "toolu_02parallelA" in tool_ids
    assert "toolu_02parallelB" in tool_ids


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_call_agentic_turn_max_tokens(anthropic_client: Any) -> None:
    """Anthropic max_tokens stop_reason maps to 'max_tokens'."""
    client, fake = anthropic_client
    fake.messages.create.return_value = _to_namespace(_load_fixture("anthropic_max_iterations.json"))

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "q"}],
        tools=[],
        system="sys",
    )
    assert turn.stop_reason == "max_tokens"


# ---------------------------------------------------------------------------
# --- OpenAILLMClient.call_agentic_turn happy-path ---
# ---------------------------------------------------------------------------

@pytest.fixture
def openai_client() -> Any:
    """OpenAILLMClient with openai.AsyncOpenAI patched at consumer-import site.

    CF-02: patch at 'openai.AsyncOpenAI' (the consumer-path binding used inside
    OpenAILLMClient.__init__'s `from openai import AsyncOpenAI` statement).
    """
    from services.generator import llm_client as mod

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock()

    with patch("openai.AsyncOpenAI", return_value=fake):
        client = mod.OpenAILLMClient()
    return client, fake


@pytest.fixture
def openai_fixture_parallel() -> dict[str, Any]:
    """CF-03: load agent_parity parallel_multi_step fixture for OpenAI happy-path."""
    return _load_parity_fixture("parallel_multi_step.json")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_call_agentic_turn_parallel_multi_step_happy_path(
    openai_client: Any,
    openai_fixture_parallel: dict[str, Any],
) -> None:
    """Happy-path: parallel multi-step tool calls (CF-03 fixture reuse)."""
    client, fake = openai_client
    fake.chat.completions.create.return_value = _to_namespace(
        _load_fixture("openai_two_parallel_tool_calls.json")
    )

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": openai_fixture_parallel["input_messages"][-1]["content"]}],
        tools=[_TOOL],
        system=openai_fixture_parallel["input_messages"][0]["content"],
    )

    assert isinstance(turn, AgenticTurn)
    assert turn.stop_reason == "tool_use"
    assert len(turn.tool_calls) == 2
    assert turn.tool_calls[0].id == "call_oai_parallel_A"
    assert turn.tool_calls[1].id == "call_oai_parallel_B"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_call_agentic_turn_text_only(openai_client: Any) -> None:
    """OpenAI text-only response: stop_reason text_only."""
    client, fake = openai_client
    fake.chat.completions.create.return_value = _to_namespace(_load_fixture("openai_text_only.json"))

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        system="sys",
    )
    assert isinstance(turn, AgenticTurn)
    assert turn.stop_reason == "text_only"
    assert len(turn.tool_calls) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_call_agentic_turn_single_tool(openai_client: Any) -> None:
    """OpenAI single tool call."""
    client, fake = openai_client
    fake.chat.completions.create.return_value = _to_namespace(_load_fixture("openai_single_tool_call.json"))

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "query"}],
        tools=[_TOOL],
        system="sys",
    )
    assert turn.stop_reason == "tool_use"
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "search_knowledge_base"
    assert turn.tool_calls[0].arguments == {"query": "产假天数规定", "top_k": 5}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_call_agentic_turn_finish_reason_length(openai_client: Any) -> None:
    """OpenAI finish_reason=length maps to stop_reason=max_tokens."""
    client, fake = openai_client
    resp = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="truncated", tool_calls=None),
            finish_reason="length",
        )],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=200),
    )
    fake.chat.completions.create.return_value = resp

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "q"}],
        tools=[],
        system="sys",
    )
    assert turn.stop_reason == "max_tokens"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_call_agentic_turn_finish_reason_unknown(openai_client: Any) -> None:
    """OpenAI finish_reason=content_filter maps to stop_reason=error."""
    client, fake = openai_client
    resp = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=None, tool_calls=None),
            finish_reason="content_filter",
        )],
        usage=None,
    )
    fake.chat.completions.create.return_value = resp

    turn = await client.call_agentic_turn(
        messages=[{"role": "user", "content": "q"}],
        tools=[],
        system="sys",
    )
    assert turn.stop_reason == "error"


# ---------------------------------------------------------------------------
# --- Failure paths: exception propagation from call_agentic_turn ---
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("provider,exc_name,exc_factory", _RETRY_FAILURE_PARAMS)
@pytest.mark.asyncio
async def test_call_agentic_turn_propagates_sdk_exception(
    provider: str,
    exc_name: str,
    exc_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """call_agentic_turn has no retry decorator: SDK exceptions propagate directly (D-13).

    Both AnthropicLLMClient and OpenAILLMClient propagate exceptions from their
    underlying SDK client. This exercises the exception branch in call_agentic_turn.
    """
    from services.generator import llm_client as mod

    exc = exc_factory()

    if provider == "anthropic":
        fake = MagicMock()
        fake.messages = MagicMock()
        fake.messages.create = AsyncMock(side_effect=exc)

        with patch("anthropic.AsyncAnthropic", return_value=fake):
            client = mod.AnthropicLLMClient()

        with pytest.raises(type(exc)):
            await client.call_agentic_turn(
                messages=[{"role": "user", "content": "q"}],
                tools=[_TOOL],
                system="sys",
            )
    else:
        fake = MagicMock()
        fake.chat = MagicMock()
        fake.chat.completions = MagicMock()
        fake.chat.completions.create = AsyncMock(side_effect=exc)

        with patch("openai.AsyncOpenAI", return_value=fake):
            client = mod.OpenAILLMClient()

        with pytest.raises(type(exc)):
            await client.call_agentic_turn(
                messages=[{"role": "user", "content": "q"}],
                tools=[_TOOL],
                system="sys",
            )


# ---------------------------------------------------------------------------
# --- Failure paths: retry-then-success on OpenAILLMClient.chat (has @retry) ---
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("exc_factory", [
    pytest.param(_make_openai_rate_limit, id="openai-RateLimitError"),
    pytest.param(_make_openai_conn_error, id="openai-APIConnectionError"),
])
@pytest.mark.asyncio
async def test_openai_chat_retries_then_succeeds(
    exc_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAILLMClient.chat @retry: first 2 attempts raise, 3rd succeeds (D-15 wait_none).

    Exercises: lines 349-364 (retry decorator + chat body + success path).
    """
    from services.generator import llm_client as mod

    exc = exc_factory()
    success_resp = SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="success answer"),
        )],
        usage=None,
    )
    create_mock = AsyncMock(side_effect=[exc, exc, success_resp])

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = create_mock

    with patch("openai.AsyncOpenAI", return_value=fake):
        client = mod.OpenAILLMClient()

    # D-15: monkeypatch tenacity wait to wait_none() so test runs in <1s
    monkeypatch.setattr(client.chat.retry, "wait", tenacity.wait_none())

    result = await client.chat(system="sys", user="user prompt")

    assert result == "success answer"
    assert create_mock.call_count == 3


@pytest.mark.unit
@pytest.mark.parametrize("exc_factory", [
    pytest.param(_make_openai_rate_limit, id="openai-RateLimitError"),
    pytest.param(_make_openai_conn_error, id="openai-APIConnectionError"),
])
@pytest.mark.asyncio
async def test_openai_chat_raises_after_max_attempts(
    exc_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAILLMClient.chat @retry: all 3 attempts raise → tenacity.RetryError (D-15).

    Exercises: retry exhaustion path in stop_after_attempt(3) decorator.
    """
    from services.generator import llm_client as mod

    exc = exc_factory()
    create_mock = AsyncMock(side_effect=[exc, exc, exc])

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = create_mock

    with patch("openai.AsyncOpenAI", return_value=fake):
        client = mod.OpenAILLMClient()

    # D-15: monkeypatch tenacity wait to wait_none() so test runs in <1s
    monkeypatch.setattr(client.chat.retry, "wait", tenacity.wait_none())

    with pytest.raises((tenacity.RetryError, type(exc))):
        await client.chat(system="sys", user="user prompt")

    assert create_mock.call_count == 3


# ---------------------------------------------------------------------------
# --- Anthropic RetryError direct propagation test ---
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_agentic_turn_propagates_retry_error_after_exhaustion(
    anthropic_client: Any,
) -> None:
    """AnthropicLLMClient.call_agentic_turn propagates tenacity.RetryError when injected directly."""
    client, fake = anthropic_client

    # Build a minimal Future-like to satisfy tenacity.RetryError.__init__
    class _FakeFuture:
        def result(self) -> None:
            raise anthropic.RateLimitError(message="429", response=_RESP_429, body={})

    retry_error = tenacity.RetryError(last_attempt=_FakeFuture())  # type: ignore[arg-type]
    fake.messages.create = AsyncMock(side_effect=retry_error)

    with pytest.raises(tenacity.RetryError):
        await client.call_agentic_turn(
            messages=[{"role": "user", "content": "q"}],
            tools=[_TOOL],
            system="sys",
        )


# ---------------------------------------------------------------------------
# --- Anthropic _handle_error branches ---
# ---------------------------------------------------------------------------
# NOTE: In this version of the anthropic SDK, `OverloadedError` does not exist
# as a top-level export. The `_handle_error` method tries to import it:
#   `from anthropic import OverloadedError`
# This raises ImportError, which is caught by `except ImportError: pass`,
# and ALL error-handling branches are then skipped — the function always falls
# through to `raise exc` at L1008. These tests verify that _handle_error
# exercises L940-1008 and re-raises the exception correctly.

@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_handle_error_reraises_rate_limit(
    anthropic_client: Any,
) -> None:
    """_handle_error: RateLimitError is re-raised (exercises lines 940-1008).

    In this SDK version, OverloadedError import fails so all branches are skipped
    and the original exception propagates via `raise exc` at L1008.
    """
    client, _ = anthropic_client

    rate_limit_exc = _make_anthropic_rate_limit()
    with pytest.raises(anthropic.RateLimitError):
        await client._handle_error(
            rate_limit_exc,
            system="sys",
            user="user",
            temperature=0.1,
            task_type="generate",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_handle_error_reraises_internal_server(
    anthropic_client: Any,
) -> None:
    """_handle_error: InternalServerError (529 overloaded) is re-raised.

    Exercises L940-1008 on the overload exception path.
    """
    client, _ = anthropic_client

    overloaded_exc = _make_anthropic_internal_server()
    with pytest.raises(anthropic.InternalServerError):
        await client._handle_error(
            overloaded_exc,
            system="sys",
            user="user",
            temperature=0.1,
            task_type="generate",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_handle_error_reraises_connection_error(
    anthropic_client: Any,
) -> None:
    """_handle_error: APIConnectionError is re-raised.

    Exercises L940-1008 on the connection error path.
    """
    client, _ = anthropic_client

    conn_exc = _make_anthropic_conn_error()
    with pytest.raises(anthropic.APIConnectionError):
        await client._handle_error(
            conn_exc,
            system="sys",
            user="user",
            temperature=0.1,
            task_type="generate",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_handle_error_reraises_bad_request(
    anthropic_client: Any,
) -> None:
    """_handle_error: BadRequestError (e.g. context overflow) is re-raised.

    Exercises L940-1008; BadRequestError branch code is also present but
    only reachable if OverloadedError import succeeds (not in this SDK version).
    """
    client, _ = anthropic_client

    resp_400 = httpx.Response(400, request=_TEST_REQUEST)
    exc_400 = anthropic.BadRequestError(
        message="input length and `max_tokens` exceed context limit: 90000 + 4096 > 90000",
        response=resp_400,
        body={},
    )
    with pytest.raises(anthropic.BadRequestError):
        await client._handle_error(
            exc_400,
            system="sys",
            user="user",
            temperature=0.1,
            task_type="generate",
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_handle_error_reraises_unknown_exception(
    anthropic_client: Any,
) -> None:
    """_handle_error: unknown exception type is re-raised (L1008 raise exc path)."""
    client, _ = anthropic_client

    unknown_exc = ValueError("unexpected error")
    with pytest.raises(ValueError, match="unexpected error"):
        await client._handle_error(
            unknown_exc,
            system="sys",
            user="user",
            temperature=0.1,
            task_type="generate",
        )


# ---------------------------------------------------------------------------
# --- get_llm_client factory branches ---
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_llm_client_returns_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory: llm_provider=anthropic returns AnthropicLLMClient (L1033-1034)."""
    from services.generator import llm_client as mod

    # Reset singleton
    mod._llm_instance = None
    monkeypatch.setattr("services.generator.llm_client.settings.llm_provider", "anthropic")

    fake = MagicMock()
    fake.messages = MagicMock()
    with patch("anthropic.AsyncAnthropic", return_value=fake):
        client = mod.get_llm_client()

    assert isinstance(client, mod.AnthropicLLMClient)
    mod._llm_instance = None  # cleanup


@pytest.mark.unit
def test_get_llm_client_returns_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory: llm_provider=openai returns OpenAILLMClient (L1031-1032)."""
    from services.generator import llm_client as mod

    mod._llm_instance = None
    monkeypatch.setattr("services.generator.llm_client.settings.llm_provider", "openai")

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    with patch("openai.AsyncOpenAI", return_value=fake):
        client = mod.get_llm_client()

    assert isinstance(client, mod.OpenAILLMClient)
    mod._llm_instance = None  # cleanup


@pytest.mark.unit
def test_get_llm_client_returns_cached_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory: singleton pattern — second call returns same instance (L1026-1027)."""
    from services.generator import llm_client as mod

    mod._llm_instance = None
    monkeypatch.setattr("services.generator.llm_client.settings.llm_provider", "openai")

    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    with patch("openai.AsyncOpenAI", return_value=fake):
        c1 = mod.get_llm_client()
        c2 = mod.get_llm_client()

    assert c1 is c2
    mod._llm_instance = None  # cleanup


@pytest.mark.unit
def test_get_llm_client_unsupported_provider_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory: unknown provider raises ValueError (L1046-1047)."""
    from services.generator import llm_client as mod

    mod._llm_instance = None
    monkeypatch.setattr("services.generator.llm_client.settings.llm_provider", "unsupported_xyz")

    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        mod.get_llm_client()

    mod._llm_instance = None  # cleanup


@pytest.mark.unit
def test_get_llm_client_azure_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Factory: llm_provider=azure creates OpenAILLMClient with AsyncAzureOpenAI (L1035-1045)."""
    from services.generator import llm_client as mod

    mod._llm_instance = None
    monkeypatch.setattr("services.generator.llm_client.settings.llm_provider", "azure")
    monkeypatch.setattr("services.generator.llm_client.settings.openai_api_key", "test-azure-key")

    fake_azure = MagicMock()
    fake_azure.chat = MagicMock()
    fake_azure.chat.completions = MagicMock()

    with patch("openai.AsyncAzureOpenAI", return_value=fake_azure):
        client = mod.get_llm_client()

    assert isinstance(client, mod.OpenAILLMClient)
    mod._llm_instance = None  # cleanup


# ---------------------------------------------------------------------------
# --- OpenAI call_agentic_turn: tool result message translation ---
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_openai_call_agentic_turn_translates_tool_result_messages(
    openai_client: Any,
) -> None:
    """OpenAILLMClient.call_agentic_turn translates Anthropic-shape tool_result messages to OpenAI tool messages.

    Exercises lines 493-498 (_translate_tool_result_message logic in call_agentic_turn).
    """
    client, fake = openai_client
    fake.chat.completions.create.return_value = _to_namespace(_load_fixture("openai_text_only.json"))

    # Anthropic-shape tool_result message
    tool_result_msg: dict[str, Any] = {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "call_123",
                "content": "The answer is 42",
            }
        ],
    }

    await client.call_agentic_turn(
        messages=[tool_result_msg],
        tools=[_TOOL],
        system="sys",
    )

    sent_messages = fake.chat.completions.create.call_args.kwargs["messages"]
    # Should include translated tool message
    tool_msgs = [m for m in sent_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "call_123"
    assert tool_msgs[0]["content"] == "The answer is 42"


# ---------------------------------------------------------------------------
# --- Wave-2 backfill: AnthropicLLMClient.chat (L618-637) ---
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_chat_returns_text(anthropic_client):
    client, fake = anthropic_client
    fake.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(type='text', text='Hello '),
            SimpleNamespace(type='text', text='world'),
        ],
        stop_reason='end_turn',
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    result = await client.chat(system='sys', user='hi', task_type='generate')
    assert result == 'Hello \nworld'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_chat_max_tokens_warning(anthropic_client):
    client, fake = anthropic_client
    fake.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type='text', text='partial')],
        stop_reason='max_tokens',
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )
    result = await client.chat(system='sys', user='hi')
    assert result == 'partial'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_chat_empty_content(anthropic_client):
    client, fake = anthropic_client
    fake.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type='tool_use', name='fn', id='x', input={})],
        stop_reason='tool_use',
        usage=SimpleNamespace(input_tokens=5, output_tokens=2),
    )
    result = await client.chat(system='sys', user='hi')
    assert result == ''


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_chat_light_task_uses_haiku(anthropic_client):
    client, fake = anthropic_client
    fake.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type='text', text='result')],
        stop_reason='end_turn',
        usage=SimpleNamespace(input_tokens=5, output_tokens=2),
    )
    await client.chat(system='sys', user='hi', task_type='nlu')
    sent_model = fake.messages.create.call_args.kwargs['model']
    assert 'haiku' in sent_model.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_call_agentic_turn_error_stop_reason(anthropic_client):
    client, fake = anthropic_client
    fake.messages.create.return_value = SimpleNamespace(
        content=[],
        stop_reason='cancelled',
        usage=SimpleNamespace(input_tokens=5, output_tokens=1),
    )
    turn = await client.call_agentic_turn(
        messages=[{'role': 'user', 'content': 'q'}],
        tools=[],
        system='sys',
    )
    assert turn.stop_reason == 'error'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_chat_with_tools_returns_tool_input(anthropic_client):
    client, fake = anthropic_client
    fake.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type='tool_use', input={'key': 'value'}, name='fn', id='x')],
        stop_reason='tool_use',
        usage=SimpleNamespace(input_tokens=5, output_tokens=2),
    )
    result = await client.chat_with_tools(system='sys', user='hi', tools=[_TOOL], task_type='nlu')
    assert result == {'key': 'value'}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_chat_with_tools_returns_empty_on_no_tool_use(anthropic_client):
    client, fake = anthropic_client
    fake.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type='text', text='text reply')],
        stop_reason='end_turn',
        usage=SimpleNamespace(input_tokens=5, output_tokens=2),
    )
    result = await client.chat_with_tools(system='sys', user='hi', tools=[_TOOL])
    assert result == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_chat_with_tools_handles_exception(anthropic_client):
    client, fake = anthropic_client
    fake.messages.create.side_effect = anthropic.APIConnectionError(request=_TEST_REQUEST)
    result = await client.chat_with_tools(system='sys', user='hi', tools=[_TOOL])
    assert result == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_chat_thinking_returns_text(anthropic_client):
    client, fake = anthropic_client
    fake.messages.create.return_value = SimpleNamespace(
        content=[
            SimpleNamespace(type='thinking', thinking='internal reasoning'),
            SimpleNamespace(type='text', text='final answer'),
        ],
        stop_reason='end_turn',
        usage=SimpleNamespace(input_tokens=20, output_tokens=10),
    )
    result = await client.chat_thinking(system='sys', user='complex question')
    assert result == 'final answer'


@pytest.mark.unit
@pytest.mark.asyncio
async def test_anthropic_chat_thinking_falls_back_on_error(anthropic_client):
    client, fake = anthropic_client
    fallback_msg = SimpleNamespace(
        content=[SimpleNamespace(type='text', text='fallback text')],
        stop_reason='end_turn',
        usage=SimpleNamespace(input_tokens=5, output_tokens=3),
    )
    fake.messages.create.side_effect = [
        anthropic.APIConnectionError(request=_TEST_REQUEST),
        fallback_msg,
    ]
    result = await client.chat_thinking(system='sys', user='complex question')
    assert result == 'fallback text'


@pytest.mark.unit
def test_get_llm_client_returns_ollama(monkeypatch):
    from services.generator import llm_client as mod
    mod._llm_instance = None
    monkeypatch.setattr('services.generator.llm_client.settings.llm_provider', 'ollama')
    client = mod.get_llm_client()
    assert isinstance(client, mod.OllamaLLMClient)
    mod._llm_instance = None


@pytest.mark.unit
def test_anthropic_client_supports_tools_and_thinking(anthropic_client):
    client, _ = anthropic_client
    assert client.supports_tools is True
    assert client.supports_thinking is True


@pytest.mark.unit
def test_get_anthropic_retry_errors_resets_cache():
    from services.generator import llm_client as mod
    original_rate = mod._anthropic_rate_limit_cls
    original_overload = mod._anthropic_overload_cls
    mod._anthropic_rate_limit_cls = None
    mod._anthropic_overload_cls = None
    try:
        result = mod._get_anthropic_retry_errors()
        assert isinstance(result, tuple)
        assert len(result) == 2
    finally:
        mod._anthropic_rate_limit_cls = original_rate
        mod._anthropic_overload_cls = original_overload
