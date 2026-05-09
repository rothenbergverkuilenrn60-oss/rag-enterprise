"""WebSearchTool — skeletal placeholder to prove tool-registry pluggability.

Phase 17 (AGENT-07) requires >= 1 additional skeletal tool registered to
demonstrate non-RAG dispatch. Real implementation deferred to v1.5+.

This tool is REGISTERED but NOT in `AGENT_TOOL_ALLOWLIST` (added to
services/pipeline.py in Wave 3 — Plan 17-03), so the planner LLM never
sees its schema. `registry.list()` does include it — so future agents
that pass `names=None` to `schemas_for` get all three tools.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from utils.models import ToolContext, ToolResult


_WEB_SEARCH_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Web search query",
        },
    },
    "required": ["query"],
}


@get_tool_registry().register
class WebSearchTool(BaseTool):
    """Placeholder — real web search deferred to v1.5+."""

    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = (
        "Search the public web for current information. "
        "(Placeholder: v1.5+ implementation pending.)"
    )
    parameters_schema: ClassVar[dict[str, Any]] = _WEB_SEARCH_PARAMETERS_SCHEMA

    async def run(
        self,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        t0 = time.perf_counter()
        latency_ms = int((time.perf_counter() - t0) * 1000)
        return ToolResult(
            content="[WebSearchTool placeholder — v1.5+]",
            metadata={
                "placeholder": True,
                "args": dict(args or {}),
                "latency_ms": latency_ms,
            },
        )
