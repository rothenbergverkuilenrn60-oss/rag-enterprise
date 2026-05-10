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
  * ``_ERROR_CONTENT`` — single source of truth for the three D-13
    user-facing error strings keyed by error kind.
  * ``_map_tavily_result`` — Tavily result dict → RetrievedChunk mapper
    (extracted for isolated coverage; wired to ``run()``'s happy path).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, ClassVar

import httpx
from loguru import logger
from tavily import (  # type: ignore[import-untyped]
    AsyncTavilyClient,
    UsageLimitExceededError,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

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
# D-13 user-facing error strings — single source of truth
# ---------------------------------------------------------------------------
#
# Centralized so the literal text appears once per kind across the module.
# Tests assert the dict's key set is exactly the three documented kinds;
# Plan 20-03 integration test reads these strings to verify the planner
# sees the correct re-plan guidance on each typed-error branch.

_ERROR_CONTENT: dict[str, str] = {
    "tavily_disabled": (
        "Web search not configured. Answer from the knowledge base only."
    ),
    "quota_exhausted": (
        "Web search quota exhausted today. Answer from the knowledge base only."
    ),
    "web_search_failed": (
        "Web search temporarily unavailable. Answer from the knowledge base only."
    ),
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
# Tavily-result → RetrievedChunk mapper (extracted for isolated coverage)
# ---------------------------------------------------------------------------

def _map_tavily_result(result: dict[str, Any]) -> RetrievedChunk:
    """Map one Tavily ``results[i]`` dict to a ``RetrievedChunk`` per D-09..D-12.

    chunk_id is a stable sha1[:16] hash of the URL so dedup across waves
    is straightforward. ``content`` is the Tavily snippet verbatim (no
    title prefix, no URL append) — D-12 contract; faithfulness-eval
    semantics preserved.
    """
    url = result.get("url", "")
    chunk_id = f"web:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}"
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="web",
        content=result.get("content", ""),
        metadata=ChunkMetadata(
            source=url,
            title=result.get("title", ""),
            chunk_type="web",
            page_number=None,
        ),
        final_score=float(result.get("score", 0.0)),
        retrieval_method="web",
    )


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
            return self._error_result(
                kind="tavily_disabled",
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

        # ── 2. Real call via tenacity-wrapped helper ───────────────────────
        try:
            resp = await _tavily_search(query_str)
        except UsageLimitExceededError as exc:
            # 429 — Tavily SDK's typed quota exception (NOT httpx.HTTPStatusError).
            # Log class name only; D-15 forbids serializing the message body
            # which may carry proxy-echoed Authorization header bytes.
            logger.error(
                f"[WebSearchTool] tavily {exc.__class__.__name__} (429 quota)"
            )
            return self._error_result(
                kind="quota_exhausted",
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        except httpx.HTTPStatusError as exc:
            # 5xx after 3 retries — retry boundary exhausted. Log status code
            # only; never the response headers or body (D-15 redaction).
            status = exc.response.status_code if exc.response is not None else 0
            logger.error(
                f"[WebSearchTool] tavily {exc.__class__.__name__} status={status}"
            )
            return self._error_result(
                kind="web_search_failed",
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            # Transport-layer failures (ConnectError, ReadTimeout, etc.) +
            # the SDK's tavily.errors.TimeoutError. Same kind/content as 5xx.
            logger.error(
                f"[WebSearchTool] tavily transport-error: {exc.__class__.__name__}"
            )
            return self._error_result(
                kind="web_search_failed",
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

        # ── 3. Happy-path mapping (D-09..D-12) ─────────────────────────────
        results = resp.get("results", []) if isinstance(resp, dict) else []
        chunks: list[RetrievedChunk] = [_map_tavily_result(r) for r in results]

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

    @staticmethod
    def _error_result(*, kind: str, latency_ms: int) -> ToolResult:
        """Construct a typed-error ToolResult (D-13/D-14/D-15 contract).

        ``kind`` is one of the three documented error kinds; the user-facing
        ``content`` text is looked up from ``_ERROR_CONTENT`` so the literal
        string appears once per kind in the module.
        """
        return ToolResult(
            content=_ERROR_CONTENT[kind],
            chunks=[],
            metadata={
                "error": True,
                "kind": kind,
                "latency_ms": latency_ms,
            },
            is_error=True,
        )
