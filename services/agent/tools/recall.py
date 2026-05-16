"""RecallTool — pgvector cosine-similarity recall via LongTermMemory (Phase 24, MEM-08).

Plan 01 stub: ships the class definition + three required ClassVars + a
placeholder run() body returning the empty marker. The real implementation
lands in Plan 03 (which replaces the run body and adds the registration
decorator). Plan 04 wires the conditional import in
services/agent/tools/__init__.py.

Registration is deferred to Plan 03 — that decorator must land AFTER the
real run body so the registry schema reflects a functional tool.
"""
from __future__ import annotations

from typing import Any, ClassVar

from services.agent.tools.base import BaseTool
from utils.models import ToolContext, ToolResult

# ---------------------------------------------------------------------------
# JSON-Schema literal — MEM-08 verbatim
# ---------------------------------------------------------------------------
_RECALL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

# Single source of truth for the "no results" marker (D-C2).
# Plan 03 will reference this constant from its run body.
_EMPTY_MARKER = "No matching facts found."


# ---------------------------------------------------------------------------
# RecallTool stub — registration decorator deferred to Plan 03
# ---------------------------------------------------------------------------
class RecallTool(BaseTool):
    """recall_memory — pgvector cosine recall over long_term_facts.

    Plan 01 stub: ClassVars only. Plan 03 fills the run body.
    Plan 04 wires registration via conditional import in
    services/agent/tools/__init__.py.
    """

    name: ClassVar[str] = "recall_memory"
    description: ClassVar[str] = (
        "Recall durable facts the agent has previously learned about this user. "
        "Call when the query references prior context, preferences, or recurring "
        "topics. Skip when conversation pivots to a new topic."
    )
    parameters_schema: ClassVar[dict[str, Any]] = _RECALL_PARAMETERS_SCHEMA

    async def run(
        self,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        # Plan 01 stub — Plan 03 replaces this body with the real recall
        # path. Returning the empty marker (NOT is_error) means the type
        # surface is exercised end-to-end without depending on Plan 02's
        # get_relevant_facts rewrite.
        return ToolResult(content=_EMPTY_MARKER, metadata={"stub": True})
