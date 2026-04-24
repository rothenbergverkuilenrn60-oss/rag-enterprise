# =============================================================================
# services/mcp_server.py
# MCP (Model Context Protocol) 服务器
#
# 作用：将 RAG 系统的核心能力通过 MCP 标准协议对外暴露，
#       让任何 MCP 客户端（Claude Desktop、Claude Code、自定义 Agent）
#       直接调用知识库搜索、文档摄取等功能，无需了解内部实现。
#
# 暴露的工具：
#   search_knowledge_base  — 向量混合检索（dense + sparse + rerank）
#   ingest_document        — 文档摄取（支持 PDF/DOCX/XLSX 等格式）
#   get_knowledge_stats    — 知识库统计（向量数量、集合信息）
#
# 启动方式：
#   python -m services.mcp_server
#   或配置到 Claude Desktop 的 mcpServers 中（stdio 模式）
#
# 安装依赖：
#   pip install mcp
# =============================================================================
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import asyncpg
import httpx
import openai
from loguru import logger


async def _run_server() -> None:
    """MCP Server 主函数（stdio 传输模式）。"""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp import types
    except ImportError:
        raise RuntimeError(
            "MCP 依赖未安装。请运行：pip install mcp\n"
            "详见：https://github.com/modelcontextprotocol/python-sdk"
        )

    server = Server("rag-enterprise")

    # ── 工具列表 ─────────────────────────────────────────────────────────────
    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="search_knowledge_base",
                description=(
                    "在企业知识库中进行混合语义检索（向量 + BM25 + Cross-Encoder 重排）。"
                    "返回最相关的文档片段，包含来源信息和相关性分数。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询，自然语言描述需要查找的信息",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回结果数量（1-20，默认 6）",
                            "default": 6,
                        },
                        "tenant_id": {
                            "type": "string",
                            "description": "租户 ID，用于多租户数据隔离（可选）",
                        },
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="ingest_document",
                description=(
                    "将文档摄取到知识库中。支持 PDF、DOCX、XLSX、CSV、HTML、TXT、MD 格式。"
                    "自动完成：预处理 → 提取 → 分块 → 向量化 → 存储。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "文档的绝对路径",
                        },
                        "title": {
                            "type": "string",
                            "description": "文档标题（可选，默认使用文件名）",
                        },
                        "tenant_id": {
                            "type": "string",
                            "description": "所属租户 ID（可选）",
                        },
                    },
                    "required": ["file_path"],
                },
            ),
            types.Tool(
                name="get_knowledge_stats",
                description="获取知识库统计信息：向量总数、集合名称、嵌入模型等。",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    # ── 工具实现 ──────────────────────────────────────────────────────────────
    @server.call_tool()
    async def call_tool(
        name: str,
        arguments: dict,
    ) -> list[types.TextContent]:

        if name == "search_knowledge_base":
            return await _tool_search(arguments)
        elif name == "ingest_document":
            return await _tool_ingest(arguments)
        elif name == "get_knowledge_stats":
            return await _tool_stats()
        else:
            return [types.TextContent(
                type="text",
                text=json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False),
            )]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


# ── 工具实现函数 ──────────────────────────────────────────────────────────────
async def _tool_search(args: dict):
    """search_knowledge_base 实现：调用 HybridRetrieverService。"""
    try:
        from mcp import types as mcp_types
        from services.retriever.retriever import get_retriever
        from services.generator.llm_client import get_llm_client

        query     = args.get("query", "")
        top_k     = min(int(args.get("top_k", 6)), 20)
        tenant_id = args.get("tenant_id", "")

        filters = {"tenant_id": tenant_id} if tenant_id else None
        retriever = get_retriever()
        llm_client = get_llm_client()

        chunks, timings = await retriever.retrieve(
            query=query,
            top_k=top_k,
            filters=filters,
            llm_client=llm_client,
        )

        results = []
        for i, chunk in enumerate(chunks):
            results.append({
                "rank":       i + 1,
                "doc_id":     chunk.doc_id,
                "title":      chunk.metadata.title or chunk.doc_id,
                "content":    chunk.content,
                "score":      round(chunk.final_score, 4),
                "source":     chunk.metadata.source,
                "page":       getattr(chunk.metadata, "page_number", None),
            })

        output = {
            "query":   query,
            "results": results,
            "total":   len(results),
            "timings": timings,
        }
        return [mcp_types.TextContent(
            type="text",
            text=json.dumps(output, ensure_ascii=False, indent=2),
        )]
    except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError) as exc:
        logger.error("MCP search_knowledge_base failed", exc_info=exc)
        from mcp import types as mcp_types
        return [mcp_types.TextContent(
            type="text",
            text=json.dumps({"error": "Knowledge base search failed"}, ensure_ascii=False),
        )]


async def _tool_ingest(args: dict):
    """ingest_document 实现：调用 IngestionPipeline。"""
    try:
        from mcp import types as mcp_types
        from services.pipeline import get_ingest_pipeline
        from utils.models import IngestionRequest

        file_path = args.get("file_path", "")
        title     = args.get("title", "")
        tenant_id = args.get("tenant_id", "")

        if not Path(file_path).exists():
            return [mcp_types.TextContent(
                type="text",
                text=json.dumps({"error": f"File not found: {file_path}"}, ensure_ascii=False),
            )]

        req = IngestionRequest(
            file_path=file_path,
            metadata={"title": title, "tenant_id": tenant_id} if title or tenant_id else {},
        )
        pipeline = get_ingest_pipeline()
        result   = await pipeline.run(req)

        return [mcp_types.TextContent(
            type="text",
            text=json.dumps({
                "success":      result.success,
                "doc_id":       result.doc_id,
                "total_chunks": result.total_chunks,
                "elapsed_ms":   result.elapsed_ms,
                "error":        result.error,
            }, ensure_ascii=False),
        )]
    except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError) as exc:
        logger.error("MCP ingest_document failed", exc_info=exc)
        from mcp import types as mcp_types
        return [mcp_types.TextContent(
            type="text",
            text=json.dumps({"error": "Document ingestion failed"}, ensure_ascii=False),
        )]


async def _tool_stats():
    """get_knowledge_stats 实现。"""
    try:
        from mcp import types as mcp_types
        from services.vectorizer.vector_store import get_vector_store
        from config.settings import settings

        store = get_vector_store()
        count = await store.count()
        return [mcp_types.TextContent(
            type="text",
            text=json.dumps({
                "vector_count":      count,
                "collection":        settings.qdrant_collection,
                "embedding_model":   settings.embedding_model,
                "embedding_dim":     settings.embedding_dim,
                "vector_store":      settings.vector_store,
            }, ensure_ascii=False),
        )]
    except asyncpg.PostgresError as exc:
        logger.error("MCP get_knowledge_stats failed", exc_info=exc)
        from mcp import types as mcp_types
        return [mcp_types.TextContent(
            type="text",
            text=json.dumps({"error": "Failed to retrieve knowledge stats"}, ensure_ascii=False),
        )]


if __name__ == "__main__":
    asyncio.run(_run_server())
