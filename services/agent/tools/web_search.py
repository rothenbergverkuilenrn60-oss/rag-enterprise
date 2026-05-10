"""WebSearchTool — Tavily-backed real implementation (Phase 20, AGENT-10/11/12).

Async-throughout via ``AsyncTavilyClient``. Tenacity 3-attempt exponential
backoff scoped to a single private helper ``_tavily_search``. Three typed
error kinds (``tavily_disabled``, ``quota_exhausted``, ``web_search_failed``)
are constructed inline in ``run()`` — the base helper that echoes the raw
exception into ``ToolResult.content`` is deliberately NOT used here
(CONTEXT D-15 source-side redaction: it could leak Tavily auth-header or
response-body bytes through the planner-visible content string).

Redaction contract (D-15): on every error path, ``ToolResult.metadata``
carries ONLY ``{error: True, kind: <kind>, latency_ms: <int>}``. Raw
exception text, response headers, response bodies, and tracebacks are
never serialized. ``logger.error`` logs the exception class name plus
the HTTP status code only.

Module-public symbols:
  * ``WebSearchTool`` — registered tool, BaseTool subclass.
  * ``_tavily_search`` — tenacity-wrapped private helper; the SOLE retry
    boundary in this module. Imported by tests as the verifiable
    decorator-marker target.
  * ``get_tavily_client`` — process-wide ``AsyncTavilyClient`` singleton
    factory (lazy-init, mirrors ``get_tool_registry`` shape).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, ClassVar

import httpx
from loguru import logger
from tavily import AsyncTavilyClient, UsageLimitExceededError  # type: ignore[import-untyped]
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from config.settings import settings
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from utils.models import (
    ChunkMetadata,
    RetrievedChunk,
    ToolContext,
    ToolResult,
)

# ---------------------------------------------------------------------------
# JSON-Schema for the planner LLM (one required string field: query)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# AsyncTavilyClient lifecycle (CONTEXT D-05 — module-level lazy singleton)
# ---------------------------------------------------------------------------

_tavily_client: AsyncTavilyClient | None = None


def get_tavily_client() -> AsyncTavilyClient:
    """Process-wide AsyncTavilyClient singleton — keeps httpx pool warm.

    First call constructs the client with the current ``settings.tavily_api_key``;
    subsequent calls reuse the instance. Tests reset by monkeypatching
    ``services.agent.tools.web_search._tavily_client`` to ``None``.
    """
    global _tavily_client
    if _tavily_client is None:
        _tavily_client = AsyncTavilyClient(api_key=settings.tavily_api_key)
    return _tavily_client


# ---------------------------------------------------------------------------
# Tenacity-wrapped inner helper (CONTEXT D-08 — narrow retry boundary)
# ---------------------------------------------------------------------------
#
# Retry only on transient transport-layer / 5xx failures: httpx.HTTPStatusError
# (raised by Tavily SDK via response.raise_for_status() on >=500), httpx
# transport errors (ConnectError, ReadTimeout, etc.), and the SDK's own
# tavily.errors.TimeoutError. UsageLimitExceededError (429) is NOT retried —
# the planner LLM should re-plan immediately on quota exhaustion rather than
# burn three more API quota points trying.

@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=10),
    reraise=True,
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.HTTPError)),
)
async def _tavily_search(query: str) -> dict[str, Any]:
    """Single-purpose Tavily call surface; the only thing tenacity wraps."""
    client = get_tavily_client()
    resp: dict[str, Any] = await client.search(
        query=query,
        search_depth=settings.tavily_search_depth,
        max_results=settings.tavily_max_results,
    )
    return resp


# ---------------------------------------------------------------------------
# Tool class — replaces the Phase 17 placeholder body
# ---------------------------------------------------------------------------

@get_tool_registry().register
class WebSearchTool(BaseTool):
    """web_search — real-time/external retrieval via Tavily."""

    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = (
        "Search the public web for current/real-time information, news, "
        "recent events, or topics not covered by the internal knowledge "
        "base. Prefer search_knowledge_base for indexed corpus questions."
    )
    parameters_schema: ClassVar[dict[str, Any]] = _WEB_SEARCH_PARAMETERS_SCHEMA

    async def run(
        self,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        t0 = time.perf_counter()
        a = args or {}
        query_str = (a.get("query") or ctx.req.query or "").strip()

        # ── 1. tavily_disabled short-circuit (D-03 / D-13) ──────────────────
        # Empty key → typed-error ToolResult BEFORE retry boundary, BEFORE
        # any network call, BEFORE get_tavily_client invocation. Spy in
        # tests verifies the factory is NEVER called on this path.
        if not settings.tavily_api_key:
            return ToolResult(
                content=(
                    "Web search not configured. "
                    "Answer from the knowledge base only."
                ),
                chunks=[],
                metadata={
                    "error": True,
                    "kind": "tavily_disabled",
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                },
                is_error=True,
            )

        # ── 2. Real call via tenacity-wrapped helper ───────────────────────
        try:
            resp = await _tavily_search(query_str)
        except UsageLimitExceededError as exc:
            # 429 — Tavily SDK's typed quota exception (NOT httpx.HTTPStatusError).
            # Log class name only — D-15 forbids serializing exc message which
            # may contain proxy-echoed Authorization header bytes.
            latency_ms = int((time.perf_counter() - t0) * 1000)
            logger.error(
                f"[WebSearchTool] tavily {exc.__class__.__name__} (429 quota)"
            )
            return ToolResult(
                content=(
                    "Web search quota exhausted today. "
                    "Answer from the knowledge base only."
                ),
                chunks=[],
                metadata={
                    "error": True,
                    "kind": "quota_exhausted",
                    "latency_ms": latency_ms,
                },
                is_error=True,
            )
        except httpx.HTTPStatusError as exc:
            # 5xx after 3 retries — exhausted retry boundary. Log status code
            # only; never the response headers or body (D-15 redaction).
            latency_ms = int((time.perf_counter() - t0) * 1000)
            status = exc.response.status_code if exc.response is not None else 0
            logger.error(
                f"[WebSearchTool] tavily {exc.__class__.__name__} status={status}"
            )
            return ToolResult(
                content=(
                    "Web search temporarily unavailable. "
                    "Answer from the knowledge base only."
                ),
                chunks=[],
                metadata={
                    "error": True,
                    "kind": "web_search_failed",
                    "latency_ms": latency_ms,
                },
                is_error=True,
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            # Transport-layer failures (ConnectError, ReadTimeout, etc.) +
            # the SDK's tavily.errors.TimeoutError (subclass of builtin
            # Exception, NOT TimeoutError). Same kind/content as 5xx —
            # opaque to the planner, retried by tenacity, then surfaced.
            latency_ms = int((time.perf_counter() - t0) * 1000)
            logger.error(
                f"[WebSearchTool] tavily transport-error: {exc.__class__.__name__}"
            )
            return ToolResult(
                content=(
                    "Web search temporarily unavailable. "
                    "Answer from the knowledge base only."
                ),
                chunks=[],
                metadata={
                    "error": True,
                    "kind": "web_search_failed",
                    "latency_ms": latency_ms,
                },
                is_error=True,
            )

        # ── 3. Happy-path mapping (D-09..D-12) ─────────────────────────────
        results = resp.get("results", []) if isinstance(resp, dict) else []
        chunks: list[RetrievedChunk] = []
        for r in results:
            url = r.get("url", "")
            chunk_id = (
                f"web:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}"
            )
            chunks.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    doc_id="web",
                    content=r.get("content", ""),
                    metadata=ChunkMetadata(
                        source=url,
                        title=r.get("title", ""),
                        chunk_type="web",
                        page_number=None,
                    ),
                    final_score=float(r.get("score", 0.0)),
                    retrieval_method="web",
                )
            )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        return ToolResult(
            content=f"Web search returned {len(chunks)} result(s).",
            chunks=chunks,
            metadata={
                "latency_ms": latency_ms,
                "query": query_str,
                "chunk_count": len(chunks),
            },
        )
