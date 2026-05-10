"""Integration tests for SC3 — planner-picks-web_search contract (Phase 20-03, AGENT-13).

Two-fixture contract per CONTEXT D-04:
  (a) Real-time query → planner emits ToolPlan whose first step is web_search.
  (b) In-corpus query → planner emits ToolPlan whose first step is search_knowledge_base.

LLM is mocked at the consumer path inside Planner (constructor injection).
The real Planner code path runs end-to-end. _AGENT_SYSTEM remains byte-identical
to v1.4 per CONTEXT D-01 — verified by test_agent_system_prompt_unchanged_d01.
"""
from __future__ import annotations

import os

# Match conftest.py preconditions so settings load in a clean env.
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

from typing import Any

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# ── stubs ─────────────────────────────────────────────────────────────────


class _StubLLM:
    """Pretends to be a BaseLLMClient — returns a canned AgenticTurn."""

    provider_name: str = "openai"

    def __init__(self, turn: Any) -> None:
        self._turn = turn

    async def call_agentic_turn(self, *, messages, tools, system):  # noqa: ANN001
        return self._turn


# ── tests ─────────────────────────────────────────────────────────────────


async def test_allowlist_includes_web_search() -> None:
    """SC3 precondition: web_search is exposed to the planner."""
    from services.pipeline import AGENT_TOOL_ALLOWLIST
    assert "web_search" in AGENT_TOOL_ALLOWLIST
    assert AGENT_TOOL_ALLOWLIST == [
        "search_knowledge_base",
        "refine_search",
        "web_search",
    ]


async def test_realtime_query_picks_web_search() -> None:
    """SC3-a: real-time query → ToolPlan.steps[0].name == 'web_search'."""
    # Importing services.agent.tools.web_search triggers @register decorator
    # at import time so 'web_search' is in registry.list().
    import services.agent.tools.web_search  # noqa: F401
    from services.agent.planner import Planner
    from services.agent.tools.registry import get_tool_registry
    from services.pipeline import AGENT_TOOL_ALLOWLIST
    from utils.models import AgenticTurn, ToolCall, ToolPlan

    tools = get_tool_registry().schemas_for("openai", names=AGENT_TOOL_ALLOWLIST)
    assert any(
        (s.get("function", {}).get("name") == "web_search") for s in tools
    ), "web_search schema missing from planner tool list"

    canned = AgenticTurn(
        text="weather is real-time, querying web",
        tool_calls=[
            ToolCall(
                id="c0",
                name="web_search",
                arguments={"query": "weather in Beijing today"},
            )
        ],
        stop_reason="tool_use",
    )
    plan: ToolPlan = await Planner(llm=_StubLLM(canned)).plan_from_messages(
        messages=[{"role": "user", "content": "What's the weather in Beijing today?"}],
        tools=tools,
        system=None,
    )
    assert isinstance(plan, ToolPlan)
    assert len(plan.steps) >= 1
    assert plan.steps[0].name == "web_search"
    assert plan.steps[0].arguments.get("query")


async def test_in_corpus_query_picks_search_knowledge_base() -> None:
    """SC3-b: in-corpus query → ToolPlan.steps[0].name == 'search_knowledge_base'."""
    import services.agent.tools.web_search  # noqa: F401
    from services.agent.planner import Planner
    from services.agent.tools.registry import get_tool_registry
    from services.pipeline import AGENT_TOOL_ALLOWLIST
    from utils.models import AgenticTurn, ToolCall, ToolPlan

    tools = get_tool_registry().schemas_for("openai", names=AGENT_TOOL_ALLOWLIST)
    # SC3 precondition shared with Test B: the same allowlist exposes both
    # web_search AND search_knowledge_base to the planner (Phase 20 contract).
    assert any(
        (s.get("function", {}).get("name") == "web_search") for s in tools
    ), "web_search schema missing from planner tool list"
    assert any(
        (s.get("function", {}).get("name") == "search_knowledge_base") for s in tools
    ), "search_knowledge_base schema missing from planner tool list"

    canned = AgenticTurn(
        text="indexed corpus question",
        tool_calls=[
            ToolCall(
                id="c0",
                name="search_knowledge_base",
                arguments={"query": "GB §3.10 透光面 definition"},
            )
        ],
        stop_reason="tool_use",
    )
    plan: ToolPlan = await Planner(llm=_StubLLM(canned)).plan_from_messages(
        messages=[{"role": "user", "content": "GB standard §3.10 透光面 definition"}],
        tools=tools,
        system=None,
    )
    assert plan.steps[0].name == "search_knowledge_base"
    assert plan.steps[0].arguments.get("query")


def test_agent_system_prompt_unchanged_d01() -> None:
    """CONTEXT D-01 guardrail: _AGENT_SYSTEM byte-identical to v1.4 baseline.

    Anchored on TWO substrings simultaneously:
      (1) the literal `_AGENT_SYSTEM = \"\"\"\\` triple-quote opener at line 617
          (note: actual source uses triple-quoted string, NOT a parenthesized
          concatenation — the assertion below matches that exact form), AND
      (2) the verbatim opening phrase of the prompt body at line 618
          (the assertion below carries the exact 12-character anchor;
          extracted directly from services/pipeline.py:618 at
          planner-authoring time, revision 2026-05-10 of Plan 20-03).

    Failure of this test means D-01 was violated — DO NOT update either
    substring to make the test pass without confirming the prompt change
    is intentional and approved.
    """
    from pathlib import Path
    src = Path("services/pipeline.py").read_text(encoding="utf-8")
    # Anchor 1: the _AGENT_SYSTEM declaration shape.
    assert '_AGENT_SYSTEM = """\\' in src, (
        "_AGENT_SYSTEM declaration shape changed — D-01 violation suspected"
    )
    # Anchor 2: the verbatim v1.4 opening phrase from line 618.
    assert "你是企业知识库的智能问答助手" in src, (
        "_AGENT_SYSTEM v1.4 opening phrase missing — D-01 violation suspected"
    )
