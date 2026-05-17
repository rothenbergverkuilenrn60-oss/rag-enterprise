"""Phase 23 / MEM-03 — Extractor sub-agent unit tests.

Mock-at-consumer-path discipline (CONTEXT §Established Patterns):
all dependencies are patched as ``services.agent.extractor.<dep>``.

RED gate per Plan 23-03 Task 2 — six tests fail until Task 3 lands the
``services/agent/extractor.py`` production module. ``test_settings_extractor_fields_present``
turns GREEN immediately because the settings change is in this task.

Per eng-review A2 (2026-05-16): ``Extractor.run`` takes BOTH the user_turn
and the ai_turn of the just-finished exchange; the prompt is formatted as
``"USER: {user_content[:2000]}\nASSISTANT: {ai_content[:2000]}"``. Two tests
exercise the both-turn signature explicitly.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.memory.memory_service import ConversationTurn
from utils.models import AgenticTurn, ExtractedFact   # noqa: F401  # plan acceptance shape import


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _agentic_turn(text: str) -> AgenticTurn:
    """Mirror tests/unit/test_verifier.py::_turn shape."""
    return AgenticTurn(
        text=text,
        tool_calls=[],
        stop_reason="text_only",
        raw_assistant_msg={"role": "assistant", "content": text},
        usage_input_tokens=0,
        usage_output_tokens=0,
    )


def _user(content: str = "I prefer React") -> ConversationTurn:
    return ConversationTurn(role="user", content=content)


def _ai(content: str = "OK, noted.") -> ConversationTurn:
    return ConversationTurn(role="assistant", content=content)


# -----------------------------------------------------------------------------
# Autouse — reset module-level singleton between tests
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_extractor_singleton(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The ``_extractor`` module-level singleton leaks state across tests.
    Reset to None before each test (the import is best-effort — if the module
    doesn't exist yet, this no-ops, which is fine for the RED-gate phase).
    """
    try:
        import services.agent.extractor as emod   # noqa: F401
        monkeypatch.setattr(emod, "_extractor", None, raising=False)
    except ImportError:
        pass
    yield


# -----------------------------------------------------------------------------
# Fixture — Extractor instance with mocked LLM (consumer-path patches)
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_extractor(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build an Extractor with the LLM dep replaced by AsyncMock at the
    consumer path (``services.agent.extractor.get_llm_client``).
    """
    import services.agent.extractor as emod
    from services.agent.extractor import Extractor

    fake_llm = MagicMock()
    fake_llm.call_agentic_turn = AsyncMock()
    monkeypatch.setattr("services.agent.extractor.get_llm_client", lambda: fake_llm)
    # Force settings.extractor_provider to None so _resolve_llm hits default branch.
    monkeypatch.setattr(emod.settings, "extractor_provider", None, raising=False)
    ex = Extractor()
    ex._llm = fake_llm   # defensive — _resolve_llm should have set this already
    return ex


# -----------------------------------------------------------------------------
# Test 1 — settings fields present (GREEN immediately in this task)
# -----------------------------------------------------------------------------


def test_settings_extractor_fields_present() -> None:
    """RESEARCH §Open Question Q1 — extractor_enabled / extractor_model /
    extractor_provider added to config/settings.py with the documented defaults.
    """
    from config.settings import settings

    assert settings.extractor_enabled is True
    assert settings.extractor_model is None
    assert settings.extractor_provider is None


# -----------------------------------------------------------------------------
# Test 2 — _resolve_llm provider bypass (P-09 verifier precedent)
# -----------------------------------------------------------------------------


def test_resolve_llm_provider_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pitfall P-09 (verifier carry-forward) — settings.extractor_provider
    bypasses get_llm_client() singleton and instantiates a fresh provider.
    """
    import services.agent.extractor as emod
    from services.agent.extractor import Extractor

    # Patch provider client constructors so instantiation doesn't need API keys.
    fake_anthropic_instance = MagicMock(name="AnthropicLLMClient_instance")
    fake_openai_instance = MagicMock(name="OpenAILLMClient_instance")
    monkeypatch.setattr(
        "services.agent.extractor.AnthropicLLMClient",
        MagicMock(return_value=fake_anthropic_instance),
    )
    monkeypatch.setattr(
        "services.agent.extractor.OpenAILLMClient",
        MagicMock(return_value=fake_openai_instance),
    )

    # Branch 1: extractor_provider="anthropic" → AnthropicLLMClient.
    monkeypatch.setattr(emod.settings, "extractor_provider", "anthropic", raising=False)
    ex = Extractor()
    assert ex._llm is fake_anthropic_instance

    # Branch 2: extractor_provider="openai" → OpenAILLMClient.
    monkeypatch.setattr(emod.settings, "extractor_provider", "openai", raising=False)
    ex = Extractor()
    assert ex._llm is fake_openai_instance

    # Branch 3: extractor_provider=None → get_llm_client() default singleton.
    sentinel = MagicMock(name="default_singleton")
    monkeypatch.setattr("services.agent.extractor.get_llm_client", lambda: sentinel)
    monkeypatch.setattr(emod.settings, "extractor_provider", None, raising=False)
    ex = Extractor()
    assert ex._llm is sentinel


# -----------------------------------------------------------------------------
# Test 3 — truncation: top-3 by importance, stable sort tie-break
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_truncates_top3_by_importance(mock_extractor: Any) -> None:
    """5 facts returned by LLM (2 stable=0.8, 2 recurring=0.5, 1 transient=0.2)
    → only the top 3 by importance survive; stable sort preserves declaration
    order among ties.
    """
    payload = {
        "facts": [
            {"fact": "user prefers React",       "category": "stable_preferences", "importance": 0.8},
            {"fact": "user works in healthcare", "category": "stable_preferences", "importance": 0.8},
            {"fact": "user asks Postgres often", "category": "recurring_topics",   "importance": 0.5},
            {"fact": "user explores agentic",    "category": "recurring_topics",   "importance": 0.5},
            {"fact": "user debugging HNSW",      "category": "transient_context",  "importance": 0.2},
        ]
    }
    mock_extractor._llm.call_agentic_turn = AsyncMock(
        return_value=_agentic_turn(text=json.dumps(payload))
    )

    result = await mock_extractor.run(user_turn=_user("I prefer React"), ai_turn=_ai("OK."))

    assert len(result) == 3
    assert [r.importance for r in result] == [0.8, 0.8, 0.5]
    # Stable sort tie-break — first declared 0.8 fact preserved in position 0.
    assert result[0].fact == "user prefers React"
    # Transient (0.2) dropped entirely.
    assert all(r.category != "transient_context" for r in result)


# -----------------------------------------------------------------------------
# Test 4 — BaseException swallow (Phase 12 isolation contract / D-06)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_returns_empty_on_llm_exception(mock_extractor: Any) -> None:
    """LLM call raises → ``except BaseException`` swallows; result == []."""
    # Sub-case A — plain Exception subclass (most common path).
    mock_extractor._llm.call_agentic_turn = AsyncMock(side_effect=Exception("provider down"))
    result = await mock_extractor.run(user_turn=_user(), ai_turn=_ai())
    assert result == []

    # Sub-case B — non-Exception BaseException subclass (verifies the
    # ``except BaseException`` clause without conflating CancelledError
    # cancellation semantics).
    class _Boom(BaseException):
        pass

    mock_extractor._llm.call_agentic_turn = AsyncMock(side_effect=_Boom("synthetic boom"))
    result = await mock_extractor.run(user_turn=_user(), ai_turn=_ai())
    assert result == []


# -----------------------------------------------------------------------------
# Test 5 — malformed JSON / wrong shape → []
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_text,desc",
    [
        ("",                                                              "empty text"),
        ("not JSON",                                                      "plain text"),
        ("```json\n{not valid",                                            "markdown-wrapped malformed"),
        ('{"facts": "not a list"}',                                        "wrong-shape facts field (string)"),
        ('{"facts": [{"fact": "x", "category": "stable_preferences", "importance": 0.5}]}',
         "category/importance mismatch — Pydantic drops the row"),
    ],
)
async def test_run_returns_empty_on_malformed_json(
    mock_extractor: Any, raw_text: str, desc: str
) -> None:
    """All 5 malformed-shape sub-cases → []."""
    mock_extractor._llm.call_agentic_turn = AsyncMock(
        return_value=_agentic_turn(text=raw_text)
    )
    result = await mock_extractor.run(user_turn=_user(), ai_turn=_ai())
    assert result == [], f"expected [] for {desc!r}; got {result!r}"


# -----------------------------------------------------------------------------
# Test 6 — get_extractor singleton
# -----------------------------------------------------------------------------


def test_get_extractor_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_extractor() returns the same instance across calls; resetting
    ``_extractor`` to None forces a fresh instance.
    """
    import services.agent.extractor as emod
    from services.agent.extractor import get_extractor

    # Patch provider construction so the singleton can initialize without API keys.
    monkeypatch.setattr(
        "services.agent.extractor.get_llm_client",
        lambda: MagicMock(name="default_singleton"),
    )
    monkeypatch.setattr(emod.settings, "extractor_provider", None, raising=False)

    a = get_extractor()
    b = get_extractor()
    assert a is b

    monkeypatch.setattr(emod, "_extractor", None, raising=False)
    c = get_extractor()
    assert c is not a


# -----------------------------------------------------------------------------
# Test 7 — A2 amendment: BOTH turns truncated to 2000 chars each
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_passes_user_and_ai_turn_truncated_to_2000_each(mock_extractor: Any) -> None:
    """Per eng-review A2: prompt body is
    ``"USER: {user[:2000]}\nASSISTANT: {ai[:2000]}"`` — both 3000-char inputs
    are clipped to 2000 chars each (combined ~4000-char body).
    """
    long_u = "u" * 3000
    long_a = "a" * 3000
    mock_extractor._llm.call_agentic_turn = AsyncMock(
        return_value=_agentic_turn(text='{"facts": []}')
    )
    await mock_extractor.run(
        user_turn=ConversationTurn(role="user", content=long_u),
        ai_turn=ConversationTurn(role="assistant", content=long_a),
    )

    # Inspect the messages kwarg passed to call_agentic_turn.
    kwargs = mock_extractor._llm.call_agentic_turn.await_args.kwargs
    expected_content = "USER: " + ("u" * 2000) + "\nASSISTANT: " + ("a" * 2000)
    assert kwargs["messages"] == [{"role": "user", "content": expected_content}]
