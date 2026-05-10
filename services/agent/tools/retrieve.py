"""RetrieveTool + RefinedRetrieveTool — wraps v1.3 retrieval as Phase 17 tools (AGENT-07).

The body of `_retrieve_impl` is a verbatim migration of
`services/agent/tool_executor.py:execute_tool_call:38-66` (the v1.3 baseline).
The XML doc-block format string (`<search_results><document index=...>`) is
consumed by the planner LLM prompt — any drift from the byte-exact format
invalidates the 19 v1.3 unit tests + 2 Phase 16 parity fixtures.

`retrieve_impl` is the public swarm-compatibility shim: same signature as
the soon-to-be-deleted `services.agent.tool_executor.execute_tool_call`,
so SwarmQueryPipeline can switch its import in Wave 3 with a single line.
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

import anthropic
import httpx
import openai
from loguru import logger

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from utils.models import (
    GenerationRequest,
    RetrievedChunk,
    ToolCall,
    ToolContext,
    ToolResult,
)


async def _retrieve_impl(
    *,
    query: str,
    top_k: int,
    source_filter: str | None,
    tf: dict[str, Any],
    retriever: Any,
    llm: Any,
) -> tuple[list[RetrievedChunk], str]:
    """Verbatim body migration from v1.3 services/agent/tool_executor.py:38-66.

    The XML doc-block format string is the planner-LLM-visible parity gate.
    """
    top_k_capped = min(int(top_k), 10)

    effective_filter = dict(tf or {})
    if source_filter:
        effective_filter["source"] = source_filter

    chunks, _ = await retriever.retrieve(
        query=query,
        top_k=top_k_capped,
        filters=effective_filter or None,
        llm_client=llm,
    )

    # Format chunks as XML document blocks (mirrors v1.1 shape).
    if chunks:
        doc_blocks = "\n\n".join(
            f'<document index="{i+1}" title="{c.metadata.title or c.doc_id}">\n'
            f"{c.content}\n"
            f"</document>"
            for i, c in enumerate(chunks)
        )
        ctx_text = f"<search_results>\n{doc_blocks}\n</search_results>"
    else:
        ctx_text = "未找到相关内容"

    return chunks, ctx_text


async def retrieve_impl(
    tc: ToolCall,
    tf: dict[str, Any],
    req: GenerationRequest,
    retriever: Any,
    llm: Any,
) -> tuple[list[RetrievedChunk], str]:
    """Shared retrieval helper. Same signature as the deleted-in-Wave-3
    services.agent.tool_executor.execute_tool_call. SwarmQueryPipeline
    switches its import to:
      `from services.agent.tools.retrieve import retrieve_impl as execute_tool_call`
    (Wave 3).
    """
    args = tc.arguments or {}
    query_str = args.get("query") or args.get("refined_query", req.query)
    top_k = int(args.get("top_k", 5))
    src_filter = args.get("source_filter")
    return await _retrieve_impl(
        query=query_str,
        top_k=top_k,
        source_filter=src_filter,
        tf=tf,
        retriever=retriever,
        llm=llm,
    )


_SEARCH_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索查询词，应精确描述需要找到的信息",
        },
        "top_k": {
            "type": "integer",
            "description": "返回结果数量（1-10）",
            "default": 5,
        },
    },
    "required": ["query"],
}

_REFINE_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "refined_query": {
            "type": "string",
            "description": "更精确的搜索词",
        },
        "source_filter": {
            "type": "string",
            "description": "限定搜索的文档来源（可选）",
        },
    },
    "required": ["refined_query"],
}


_RETRIEVE_RUNTIME_ERRORS = (
    RuntimeError,
    ValueError,
    anthropic.APIError,
    openai.APIError,
    httpx.HTTPError,
    TimeoutError,
)


@get_tool_registry().register
class RetrieveTool(BaseTool):
    """search_knowledge_base — primary RAG retrieval tool.

    Wraps the verbatim v1.3 retrieval body. Parity with the deleted
    _AGENT_TOOLS literal (services/pipeline.py:603-621) is the acceptance
    gate.
    """

    name: ClassVar[str] = "search_knowledge_base"
    description: ClassVar[str] = "在企业知识库中搜索相关信息"
    parameters_schema: ClassVar[dict[str, Any]] = _SEARCH_PARAMETERS_SCHEMA

    async def run(
        self,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        t0 = time.perf_counter()
        a = args or {}
        query_str = a.get("query") or ctx.req.query
        top_k = int(a.get("top_k", 5))
        try:
            chunks, ctx_text = await _retrieve_impl(
                query=query_str,
                top_k=top_k,
                source_filter=None,
                tf=ctx.tf,
                retriever=ctx.retriever,
                llm=ctx.llm,
            )
        except _RETRIEVE_RUNTIME_ERRORS as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            logger.error(f"[RetrieveTool] failed: {exc!r}")
            return self._build_error_result(exc, latency_ms=latency_ms)

        latency_ms = int((time.perf_counter() - t0) * 1000)
        return ToolResult(
            content=ctx_text,
            chunks=list(chunks),
            metadata={
                "latency_ms": latency_ms,
                "query": query_str,
                "chunk_count": len(chunks),
            },
        )


@get_tool_registry().register
class RefinedRetrieveTool(BaseTool):
    """refine_search — narrow-search variant; supports source_filter.

    Shares _retrieve_impl with RetrieveTool. Preserves v1.2/v1.3 planner
    prompt verbatim (CONTEXT D-05).
    """

    name: ClassVar[str] = "refine_search"
    description: ClassVar[str] = "用更精确的关键词细化搜索，适用于初次搜索结果不够具体时"
    parameters_schema: ClassVar[dict[str, Any]] = _REFINE_PARAMETERS_SCHEMA

    async def run(
        self,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        t0 = time.perf_counter()
        a = args or {}
        query_str = a.get("refined_query") or a.get("query") or ctx.req.query
        src_filter = a.get("source_filter")
        top_k = int(a.get("top_k", 5))
        try:
            chunks, ctx_text = await _retrieve_impl(
                query=query_str,
                top_k=top_k,
                source_filter=src_filter,
                tf=ctx.tf,
                retriever=ctx.retriever,
                llm=ctx.llm,
            )
        except _RETRIEVE_RUNTIME_ERRORS as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            logger.error(f"[RefinedRetrieveTool] failed: {exc!r}")
            return self._build_error_result(exc, latency_ms=latency_ms)

        latency_ms = int((time.perf_counter() - t0) * 1000)
        return ToolResult(
            content=ctx_text,
            chunks=list(chunks),
            metadata={
                "latency_ms": latency_ms,
                "query": query_str,
                "chunk_count": len(chunks),
            },
        )
