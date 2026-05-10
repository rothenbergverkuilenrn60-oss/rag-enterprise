"""Unit tests for RetrieveTool + RefinedRetrieveTool (Phase 17-02, RED gate).

Tests are written BEFORE the implementation (TDD RED phase). All tests must
fail with ImportError or AttributeError until T3/T4 implement the classes.

Parity gate (Test 16 / TestSchemasForParity): registry.schemas_for('anthropic',
names=['search_knowledge_base', 'refine_search']) must be BYTE-IDENTICAL to the
_AGENT_TOOLS literal in services/pipeline.py:602-640. This is the Wave 3
deletion gate — when _AGENT_TOOLS is removed, schemas_for output must still
produce identical tool definitions for the planner LLM prompt.
"""
from __future__ import annotations

from typing import Any

import pytest

from services.agent.tools import (
    RefinedRetrieveTool,
    RetrieveTool,
    get_tool_registry,
)
from utils.models import GenerationRequest, ToolContext

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class _FakeChunkMeta:
    def __init__(self, title: str) -> None:
        self.title = title


class _FakeChunk:
    def __init__(self, content: str, doc_id: str, title: str | None = None) -> None:
        self.content = content
        self.doc_id = doc_id
        self.metadata = _FakeChunkMeta(title or "")
        self.chunk_id = f"chunk-{doc_id}"


class _FakeRetriever:
    def __init__(
        self,
        chunks_to_return: list[Any] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.chunks = chunks_to_return or []
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def retrieve(
        self,
        *,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None,
        llm_client: Any,
    ) -> tuple[list[Any], dict[str, Any]]:
        self.calls.append(
            {"query": query, "top_k": top_k, "filters": filters, "llm_client": llm_client}
        )
        if self.raise_exc:
            raise self.raise_exc
        return list(self.chunks), {}


def _ctx(
    retriever: Any,
    query: str = "default-query",
    tf: dict[str, Any] | None = None,
) -> ToolContext:
    return ToolContext(
        req=GenerationRequest(query=query),
        tf=tf or {},
        retriever=retriever,
        llm=object(),
    )


# ---------------------------------------------------------------------------
# Parity constants — byte-identical copy of services/pipeline.py:602-640
# These are the DELETION GATE for Wave 3.
# ---------------------------------------------------------------------------

_EXPECTED_SEARCH_TOOL = {
    "name": "search_knowledge_base",
    "description": "在企业知识库中搜索相关信息",
    "input_schema": {
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
    },
}

_EXPECTED_REFINE_TOOL = {
    "name": "refine_search",
    "description": "用更精确的关键词细化搜索，适用于初次搜索结果不够具体时",
    "input_schema": {
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
    },
}


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestRetrieveToolRegistration:
    def test_retrieve_tool_registered(self) -> None:
        """RetrieveTool is registered under name='search_knowledge_base'."""
        assert "search_knowledge_base" in get_tool_registry().list()

    def test_refine_tool_registered(self) -> None:
        """RefinedRetrieveTool is registered under name='refine_search'."""
        assert "refine_search" in get_tool_registry().list()

    def test_retrieve_tool_name_classvar(self) -> None:
        """RetrieveTool.name matches the parity constant."""
        assert RetrieveTool.name == _EXPECTED_SEARCH_TOOL["name"]

    def test_retrieve_tool_description_classvar(self) -> None:
        """RetrieveTool.description is byte-identical to pipeline.py:605."""
        assert RetrieveTool.description == _EXPECTED_SEARCH_TOOL["description"]

    def test_retrieve_tool_parameters_schema(self) -> None:
        """RetrieveTool.parameters_schema is byte-identical to pipeline.py:606-620."""
        assert RetrieveTool.parameters_schema == _EXPECTED_SEARCH_TOOL["input_schema"]

    def test_refine_tool_name_classvar(self) -> None:
        """RefinedRetrieveTool.name matches the parity constant."""
        assert RefinedRetrieveTool.name == _EXPECTED_REFINE_TOOL["name"]

    def test_refine_tool_description_classvar(self) -> None:
        """RefinedRetrieveTool.description is byte-identical to pipeline.py:624."""
        assert RefinedRetrieveTool.description == _EXPECTED_REFINE_TOOL["description"]

    def test_refine_tool_parameters_schema(self) -> None:
        """RefinedRetrieveTool.parameters_schema is byte-identical to pipeline.py:625-639."""
        assert RefinedRetrieveTool.parameters_schema == _EXPECTED_REFINE_TOOL["input_schema"]


class TestRetrieveToolRun:
    @pytest.mark.asyncio
    async def test_calls_retriever_with_query_and_top_k(self) -> None:
        """RetrieveTool.run passes query and top_k to retriever.retrieve."""
        ret = _FakeRetriever()
        tool = RetrieveTool()
        await tool.run({"query": "hello", "top_k": 3}, _ctx(ret))
        assert len(ret.calls) == 1
        assert ret.calls[0]["query"] == "hello"
        assert ret.calls[0]["top_k"] == 3

    @pytest.mark.asyncio
    async def test_top_k_capped_at_10(self) -> None:
        """top_k=15 → retriever called with top_k=10 (v1.3 line 40 cap)."""
        ret = _FakeRetriever()
        tool = RetrieveTool()
        await tool.run({"query": "q", "top_k": 15}, _ctx(ret))
        assert ret.calls[0]["top_k"] == 10

    @pytest.mark.asyncio
    async def test_top_k_default_is_5(self) -> None:
        """top_k missing → retriever called with top_k=5 (v1.3 default)."""
        ret = _FakeRetriever()
        tool = RetrieveTool()
        await tool.run({"query": "q"}, _ctx(ret))
        assert ret.calls[0]["top_k"] == 5

    @pytest.mark.asyncio
    async def test_tf_passed_as_filters(self) -> None:
        """tf={'tenant_id':'t1'} passed as filters to retriever."""
        ret = _FakeRetriever()
        tool = RetrieveTool()
        await tool.run({"query": "q"}, _ctx(ret, tf={"tenant_id": "t1"}))
        assert ret.calls[0]["filters"] == {"tenant_id": "t1"}

    @pytest.mark.asyncio
    async def test_empty_tf_yields_none_filters(self) -> None:
        """Empty tf={} → filters=None (effective_filter or None; v1.3 line 43-44)."""
        ret = _FakeRetriever()
        tool = RetrieveTool()
        await tool.run({"query": "q"}, _ctx(ret, tf={}))
        assert ret.calls[0]["filters"] is None


class TestRefinedRetrieveTool:
    @pytest.mark.asyncio
    async def test_refined_query_used_as_query(self) -> None:
        """RefinedRetrieveTool with args={'refined_query':'q2'} → retriever query='q2'."""
        ret = _FakeRetriever()
        tool = RefinedRetrieveTool()
        await tool.run({"refined_query": "q2"}, _ctx(ret))
        assert ret.calls[0]["query"] == "q2"

    @pytest.mark.asyncio
    async def test_source_filter_merges_into_filters(self) -> None:
        """source_filter in args is merged into effective_filter."""
        ret = _FakeRetriever()
        tool = RefinedRetrieveTool()
        await tool.run(
            {"refined_query": "q2", "source_filter": "docs"},
            _ctx(ret),
        )
        assert ret.calls[0]["filters"] == {"source": "docs"}

    @pytest.mark.asyncio
    async def test_source_filter_merges_with_tf(self) -> None:
        """source_filter + tf both appear in filters."""
        ret = _FakeRetriever()
        tool = RefinedRetrieveTool()
        await tool.run(
            {"refined_query": "q2", "source_filter": "docs"},
            _ctx(ret, tf={"tenant_id": "t1"}),
        )
        assert ret.calls[0]["filters"] == {"tenant_id": "t1", "source": "docs"}

    @pytest.mark.asyncio
    async def test_tf_preserved_when_no_source_filter(self) -> None:
        """tf preserved when no source_filter provided."""
        ret = _FakeRetriever()
        tool = RefinedRetrieveTool()
        await tool.run(
            {"refined_query": "q2"},
            _ctx(ret, tf={"tenant_id": "t1"}),
        )
        assert ret.calls[0]["filters"] == {"tenant_id": "t1"}

    @pytest.mark.asyncio
    async def test_fallback_to_req_query_when_no_refined_query(self) -> None:
        """No refined_query in args → falls back to req.query (v1.3 line 39 fallback)."""
        ret = _FakeRetriever()
        tool = RefinedRetrieveTool()
        await tool.run({}, _ctx(ret, query="req-query"))
        assert ret.calls[0]["query"] == "req-query"


class TestXMLFormat:
    @pytest.mark.asyncio
    async def test_xml_format_byte_identical(self) -> None:
        """XML doc-block format is byte-identical to tool_executor.py:54-63."""
        chunks = [
            _FakeChunk("body1", "d1", "T1"),
            _FakeChunk("body2", "d2", "T2"),
        ]
        ret = _FakeRetriever(chunks_to_return=chunks)
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        expected = (
            '<search_results>\n'
            '<document index="1" title="T1">\n'
            'body1\n'
            '</document>\n\n'
            '<document index="2" title="T2">\n'
            'body2\n'
            '</document>\n'
            '</search_results>'
        )
        assert result.content == expected

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_sentinel(self) -> None:
        """Empty chunks → content == '未找到相关内容' (UTF-8 sentinel, NOT XML wrapper)."""
        ret = _FakeRetriever(chunks_to_return=[])
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        assert result.content == "未找到相关内容"

    @pytest.mark.asyncio
    async def test_doc_id_used_as_title_when_title_empty(self) -> None:
        """When chunk metadata.title is empty, doc_id is used as title."""
        chunks = [_FakeChunk("content", "doc-abc", title="")]
        ret = _FakeRetriever(chunks_to_return=chunks)
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        assert 'title="doc-abc"' in result.content


class TestToolResultMetadata:
    @pytest.mark.asyncio
    async def test_metadata_contains_latency_ms(self) -> None:
        """ToolResult.metadata contains latency_ms (int >= 0)."""
        ret = _FakeRetriever()
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        assert "latency_ms" in result.metadata
        assert isinstance(result.metadata["latency_ms"], int)
        assert result.metadata["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_metadata_contains_query(self) -> None:
        """ToolResult.metadata contains query (str)."""
        ret = _FakeRetriever()
        tool = RetrieveTool()
        result = await tool.run({"query": "my-query"}, _ctx(ret))
        assert result.metadata["query"] == "my-query"

    @pytest.mark.asyncio
    async def test_metadata_contains_chunk_count(self) -> None:
        """ToolResult.metadata contains chunk_count (int)."""
        chunks = [_FakeChunk("c", "d1", "T"), _FakeChunk("c2", "d2", "T2")]
        ret = _FakeRetriever(chunks_to_return=chunks)
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        assert result.metadata["chunk_count"] == 2

    @pytest.mark.asyncio
    async def test_toolresult_is_not_error_on_success(self) -> None:
        """Successful run returns is_error=False."""
        ret = _FakeRetriever()
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        assert result.is_error is False


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_runtime_error_returns_is_error_true(self) -> None:
        """Retriever RuntimeError → ToolResult(is_error=True)."""
        exc = RuntimeError("retriever exploded")
        ret = _FakeRetriever(raise_exc=exc)
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_error_result_content_includes_tool_name(self) -> None:
        """Error ToolResult.content includes 'search_knowledge_base'."""
        exc = RuntimeError("boom")
        ret = _FakeRetriever(raise_exc=exc)
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        assert "search_knowledge_base" in result.content

    @pytest.mark.asyncio
    async def test_error_result_content_includes_exc_message(self) -> None:
        """Error ToolResult.content includes the exception message."""
        exc = RuntimeError("boom boom")
        ret = _FakeRetriever(raise_exc=exc)
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        assert "boom boom" in result.content

    @pytest.mark.asyncio
    async def test_error_result_metadata_has_latency_ms(self) -> None:
        """Error ToolResult.metadata contains latency_ms >= 0."""
        exc = RuntimeError("err")
        ret = _FakeRetriever(raise_exc=exc)
        tool = RetrieveTool()
        result = await tool.run({"query": "q"}, _ctx(ret))
        assert "latency_ms" in result.metadata
        assert result.metadata["latency_ms"] >= 0


class TestSchemasForParity:
    def test_retrieve_tool_xml_format_parity(self) -> None:
        """schemas_for('anthropic', names=[...]) BYTE-IDENTICAL to _AGENT_TOOLS literal.

        This is the WAVE 3 DELETION GATE. When _AGENT_TOOLS is removed from
        services/pipeline.py, the planner LLM must still receive identical
        tool schemas. If this test fails, the XML format / tool description
        has drifted from v1.3 baseline.
        """
        registry = get_tool_registry()
        schemas = registry.schemas_for(
            "anthropic",
            names=["search_knowledge_base", "refine_search"],
        )
        assert len(schemas) == 2
        assert schemas[0] == _EXPECTED_SEARCH_TOOL
        assert schemas[1] == _EXPECTED_REFINE_TOOL
