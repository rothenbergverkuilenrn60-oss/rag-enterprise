"""RecallTool — pgvector cosine-similarity recall via LongTermMemory (MEM-08).

Plan 01 stub; Plan 03 fills run() + registration decorator; Plan 04 wires import.
"""
from __future__ import annotations

import time
from typing import Any, ClassVar

import asyncpg  # type: ignore[import-untyped]  # why: asyncpg has no py.typed marker as of 2026-05
import httpx
from loguru import logger

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from services.memory.memory_service import get_memory_service
from utils.models import ToolContext, ToolResult

# JSON-Schema literal — MEM-08 verbatim
_RECALL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

# Single source of truth for the "no results" marker (D-C2).
_EMPTY_MARKER = "No matching facts found."

# Error marker shown to the planner LLM — stable string, never leaks exception
# text (D-C3 / Test 13 / T-24-03-I2).
_ERROR_MARKER = "Memory unavailable; proceed without recall."

# Narrow exception tuple for best-effort isolation (D-C3 / PATTERNS analog 3).
# Mirrors retrieve.py _RETRIEVE_RUNTIME_ERRORS convention.
_RECALL_RUNTIME_ERRORS = (asyncpg.PostgresError, httpx.HTTPError, RuntimeError, OSError)


# RecallTool — registers at import time (Plan 04 guards the import)
@get_tool_registry().register
class RecallTool(BaseTool):
    """recall_memory — pgvector cosine recall over long_term_facts (MEM-08)."""

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
        """recall_memory tool entry — 3-branch fan-out.

        ┌─────────────────────────────────────────────────────────────┐
        │ run(args, ctx)                                              │
        │   │                                                         │
        │   ├─ user_id="" OR tenant_id="" OR query=""                 │
        │   │    └─► ToolResult(_EMPTY_MARKER, is_error=False,        │
        │   │            metadata={reason:"missing_user_or_tenant_id"})│
        │   │                                                         │
        │   ├─ await public_passthrough(uid, tid, q, limit=5)          │
        │   │    │                                                    │
        │   │    ├─ raises (asyncpg/httpx/Runtime/OSError)             │
        │   │    │    └─► ToolResult(_ERROR_MARKER, is_error=True,    │
        │   │    │            metadata={latency_ms, error:True})      │
        │   │    │                                                    │
        │   │    ├─ returns []                                        │
        │   │    │    └─► ToolResult(_EMPTY_MARKER, is_error=False,   │
        │   │    │            metadata={latency_ms, fact_count:0})    │
        │   │    │                                                    │
        │   │    └─ returns [fact, ...]                               │
        │   │         └─► ToolResult("- " + "\\n- ".join(facts),     │
        │   │                 is_error=False,                        │
        │   │                 metadata={latency_ms, fact_count, q})  │
        └─────────────────────────────────────────────────────────────┘

        T3 (eng-review 2026-05-16): calls the PUBLIC passthrough method
        only; private _long attribute reach is banned by Test 14.
        """
        t0 = time.perf_counter()
        a = args or {}
        query_str = (a.get("query") or ctx.req.query or "").strip()
        user_id = getattr(ctx.req, "user_id", "")
        tenant_id = getattr(ctx.req, "tenant_id", "")

        # 1. Auth precondition — empty marker (NOT error). D-C2 / Pattern 3.
        if not user_id or not tenant_id or not query_str:
            return ToolResult(
                content=_EMPTY_MARKER,
                metadata={
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "reason": "missing_user_or_tenant_id",
                },
            )

        # 2. Best-effort recall. D-C3 isolation. T3: PUBLIC passthrough.
        try:
            mem = get_memory_service()
            facts = await mem.get_relevant_facts(
                user_id, tenant_id, query_str, limit=5,
            )
        except _RECALL_RUNTIME_ERRORS as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            logger.error(f"[RecallTool] failed: {exc!r}")
            return ToolResult(
                content=_ERROR_MARKER,
                metadata={"latency_ms": latency_ms, "error": True},
                is_error=True,
            )

        # 3. Shape result. D-C1 bullets + D-C2 empty marker.
        latency_ms = int((time.perf_counter() - t0) * 1000)
        if not facts:
            return ToolResult(
                content=_EMPTY_MARKER,
                metadata={
                    "latency_ms": latency_ms,
                    "fact_count": 0,
                    "query": query_str,
                },
            )

        return ToolResult(
            content="- " + "\n- ".join(facts),
            metadata={
                "latency_ms": latency_ms,
                "fact_count": len(facts),
                "query": query_str,
            },
        )
