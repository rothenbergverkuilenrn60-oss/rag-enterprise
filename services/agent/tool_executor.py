"""Shared tool-execution helper extracted from v1.3 AgentQueryPipeline + SwarmQueryPipeline (AGENT-09).

The body is a verbatim extract of `_execute_tool_call` at the v1.3 baseline
(commit a3a95f8, lines 846-887 of services/pipeline.py — byte-identical to
the duplicate at lines 1107-1148). The only structural change is removing
the bound `self`: the previously-instance-attribute dependencies
(`retriever`, `llm`) are now explicit positional arguments so both
AgentQueryPipeline and SwarmQueryPipeline can share this single helper
without inheriting an empty base class.

Wave 1 of Phase 16 (Plan 16-01) introduces this helper and rewires both
v1.3 in-class methods to one-line delegates. Wave 3 (Plan 16-03) deletes
those delegates entirely; the new Executor in Plan 16-02 calls this helper
directly.
"""

from __future__ import annotations

from typing import Any

from utils.models import GenerationRequest, RetrievedChunk, ToolCall


async def execute_tool_call(
    tc: ToolCall,
    tf: dict[str, Any],
    req: GenerationRequest,
    retriever: Any,
    llm: Any,
) -> tuple[list[RetrievedChunk], str]:
    """Execute one tool call and return (chunks, ctx_text).

    Side-effect-free with respect to the calling pipeline state — this lets
    ``asyncio.gather(return_exceptions=True)`` collect results without
    mutating shared state during the parallel section. Caller merges
    ``chunks`` into ``all_chunks`` and runs dedup AFTER the gather.
    """
    args       = tc.arguments or {}
    query_str  = args.get("query") or args.get("refined_query", req.query)
    top_k      = min(int(args.get("top_k", 5)), 10)
    src_filter = args.get("source_filter")

    effective_filter = dict(tf or {})
    if src_filter:
        effective_filter["source"] = src_filter

    chunks, _ = await retriever.retrieve(
        query=query_str,
        top_k=top_k,
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
