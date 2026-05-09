"""Planner — first LLM call returns a ToolPlan (AGENT-06, NLU-03).

Provider-neutral. Uses ``BaseLLMClient.call_agentic_turn`` from v1.2 Phase 11.
Single LLM call per ``Planner.plan_from_messages`` invocation — outer-loop
iteration is the orchestrator's responsibility (Phase 16 CONTEXT.md D-12).

The planner's ``rationale`` field is written in the same language as the
user query (CONTEXT.md D-03). The planner does NOT branch on provider type;
the adapter normalizes wire format inside ``call_agentic_turn``.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from services.generator.llm_client import get_llm_client
from utils.models import AgenticTurn, ToolCall, ToolPlan

_PLANNER_SYSTEM = (
    "You are the planner for an enterprise RAG agent. Given a user query, "
    "decide which tool calls to issue and how to group them for parallel "
    "execution. Emit your reasoning as `rationale` in the SAME LANGUAGE as "
    "the user query. Issue multiple tool calls concurrently when the query "
    "decomposes into independent sub-questions; issue them sequentially "
    "when later calls depend on earlier results. The available tools are "
    "registered with you at runtime."
)


class PlannerOutputError(ValueError):
    """Raised when the LLM response cannot be normalized into a ToolPlan."""


class Planner:
    """Wraps a single ``call_agentic_turn`` invocation, returns a ToolPlan."""

    def __init__(self, llm: Any | None = None) -> None:
        self._llm = llm if llm is not None else get_llm_client()

    async def plan_from_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> ToolPlan:
        """Issue one LLM call and normalize the assistant turn into a ToolPlan.

        ``messages`` is the conversation list (excluding system, which is
        passed separately to ``call_agentic_turn``). When ``system`` is
        None, the module-level ``_PLANNER_SYSTEM`` is used. ``tools`` may
        be None for the text-only path; the LLM-side raises if a tool call
        is required without tools registered.

        Phase 16 keeps the planner stateless — caching deferred to v1.5+
        per CONTEXT.md.
        """
        turn: AgenticTurn = await self._llm.call_agentic_turn(
            messages,
            tools=tools or [],
            system=system or _PLANNER_SYSTEM,
        )
        return self._turn_to_plan(turn)

    def _turn_to_plan(self, turn: AgenticTurn) -> ToolPlan:
        """Map AgenticTurn.tool_calls to a ToolPlan in single-wave shape.

        The default mapping puts every tool call in one parallel group —
        v1.2 ``parallel_tool_calls=True`` semantics. If the LLM returns text
        in addition to tool_calls and that text parses as a JSON ToolPlan
        with explicit ``parallel_groups``, that explicit shape wins.
        """
        if not turn.tool_calls:
            # No tool calls — empty plan with the LLM's text as rationale.
            return ToolPlan(steps=[], parallel_groups=[], rationale=turn.text or "")

        steps = list(turn.tool_calls)
        explicit = self._extract_explicit_plan(turn.text, steps)
        if explicit is not None:
            return explicit

        return ToolPlan(
            steps=steps,
            parallel_groups=[list(range(len(steps)))],
            rationale=turn.text or "",
        )

    def _extract_explicit_plan(
        self,
        text: str,
        steps: list[ToolCall],
    ) -> ToolPlan | None:
        """Best-effort: if assistant text is a ToolPlan-shaped JSON object,
        honor its parallel_groups. Otherwise return None.
        """
        if not text:
            return None
        candidate = text.strip()
        if not candidate.startswith("{"):
            return None
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        groups = data.get("parallel_groups")
        if not isinstance(groups, list):
            return None
        try:
            return ToolPlan(
                steps=steps,
                parallel_groups=groups,
                rationale=str(data.get("rationale", "")),
            )
        except ValueError as exc:
            logger.warning(f"[Planner] explicit parallel_groups invalid: {exc}")
            raise PlannerOutputError(
                f"explicit parallel_groups invalid: {exc}"
            ) from exc


_planner_instance: Planner | None = None


def get_planner() -> Planner:
    global _planner_instance
    if _planner_instance is None:
        _planner_instance = Planner()
    return _planner_instance
