"""Phase 23 / MEM-05 — Extractor sub-agent adversarial-input proof set.

Eight+ attack vectors driving ``Extractor.run`` via mocked LLM responses. Every
fixture must produce ``[]`` regardless of which defense layer is the primary
catch:

  1. **Prompt layer** (fixtures 1–5, 9): mocked LLM obeys the refusal clause
     and emits ``{"facts": []}``. Verifies the integration path: a properly
     behaving LLM under attack-shaped input → empty extractor result.
  2. **Literal-category layer** (fixture 6): jailbroken LLM emits
     ``category="admin_policy"``. Pydantic ``Literal[...]`` rejects;
     ``_parse_and_truncate`` catches ``ValidationError`` and drops the row.
  3. **Cross-field validator** (fixture 7): jailbroken LLM emits valid
     category but wrong-bucket importance. ``@model_validator(mode="after")``
     rejects.
  4. **Defensive parse** (fixture 8): jailbroken LLM emits markdown-fenced
     truncated JSON. ``json.JSONDecodeError`` returns ``[]``.

Methodology: a real LLM cannot be exercised in unit tests. Fixtures #1–#5 + #9
verify the **compliant** integration path; #6–#8 verify the **jailbroken**
defense-in-depth (Pydantic + parse layers). Both shapes MUST yield ``[]`` for
the defense-in-depth claim to hold.

Mock-at-consumer-path discipline (CONTEXT §Established Patterns): all deps
patched as ``services.agent.extractor.<dep>``.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.memory.memory_service import ConversationTurn
from utils.models import AgenticTurn

# -----------------------------------------------------------------------------
# Fixture file load — at module scope so pytest.mark.parametrize can derive ids
# -----------------------------------------------------------------------------

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "extractor" / "adversarial.json"
FIXTURES: list[dict[str, Any]] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _agentic_turn(text: str) -> AgenticTurn:
    """Mirror tests/unit/test_extractor.py::_agentic_turn shape."""
    return AgenticTurn(
        text=text,
        tool_calls=[],
        stop_reason="text_only",
        raw_assistant_msg={"role": "assistant", "content": text},
        usage_input_tokens=0,
        usage_output_tokens=0,
    )


# -----------------------------------------------------------------------------
# Autouse — reset module-level singleton between tests (carry-forward from
# test_extractor.py so adversarial runs do not leak Extractor instances).
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_extractor_singleton(monkeypatch: pytest.MonkeyPatch) -> Any:
    import services.agent.extractor as emod

    monkeypatch.setattr(emod, "_extractor", None, raising=False)
    yield


# -----------------------------------------------------------------------------
# Parametrized driver — every fixture returns []
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture",
    FIXTURES,
    ids=[f["name"] for f in FIXTURES],
)
async def test_adversarial_returns_empty(
    monkeypatch: pytest.MonkeyPatch, fixture: dict[str, Any]
) -> None:
    """For each adversarial fixture, ``Extractor.run`` returns ``[]``.

    Defense layer the fixture exercises is documented in fixture['defense_layer'];
    the assertion message includes both ``name`` and ``defense_layer`` for
    diagnostic clarity (T-23-04-R1 mitigation — repudiation surface).
    """
    import services.agent.extractor as emod

    fake_llm = MagicMock()
    fake_llm.call_agentic_turn = AsyncMock(
        return_value=_agentic_turn(text=fixture["mocked_llm_output"])
    )
    monkeypatch.setattr("services.agent.extractor.get_llm_client", lambda: fake_llm)
    monkeypatch.setattr(emod.settings, "extractor_provider", None, raising=False)

    from services.agent.extractor import Extractor

    extractor = Extractor()
    extractor._llm = fake_llm  # defensive — _resolve_llm should have set this

    user_turn = ConversationTurn(role="user", content=fixture["turn_content"])
    ai_turn = ConversationTurn(role="assistant", content="OK.")

    result = await extractor.run(user_turn=user_turn, ai_turn=ai_turn)

    assert result == [], (
        f"fixture {fixture['name']!r} "
        f"(defense_layer={fixture['defense_layer']!r}, "
        f"threat_id={fixture['threat_id']!r}) leaked: {result!r}"
    )


# -----------------------------------------------------------------------------
# Defense-layer floor — fixture file structure invariants
# -----------------------------------------------------------------------------


def test_fixture_file_meets_floor() -> None:
    """Fixture file invariants (matches Plan 04 acceptance criteria):
      - ≥ 8 fixtures
      - 8 required attack-vector names present
      - all 4 defense layers represented (prompt, literal_category,
        cross_field_validator, defensive_parse)
    """
    assert len(FIXTURES) >= 8, f"expected ≥ 8 fixtures, got {len(FIXTURES)}"

    required_names = {
        "policy_injection_admin",
        "role_redefinition",
        "system_prompt_leak",
        "cross_user_injection",
        "cross_tenant_injection",
        "category_out_of_whitelist",
        "importance_out_of_bucket",
        "malformed_json",
    }
    names = {f["name"] for f in FIXTURES}
    assert required_names.issubset(names), (
        f"missing required fixtures: {required_names - names}"
    )

    required_layers = {
        "prompt",
        "literal_category",
        "cross_field_validator",
        "defensive_parse",
    }
    layers = {f["defense_layer"] for f in FIXTURES}
    assert required_layers.issubset(layers), (
        f"missing defense layers: {required_layers - layers}"
    )

    for f in FIXTURES:
        for key in ("name", "turn_content", "mocked_llm_output", "defense_layer"):
            assert key in f, f"fixture {f.get('name', '?')} missing key {key!r}"
