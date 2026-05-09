"""Unit tests for WebSearchTool placeholder (Phase 17-02, RED gate).

Tests are written BEFORE the implementation (TDD RED phase). All tests must
fail with ImportError until T5 implements WebSearchTool.

WebSearchTool is a skeletal placeholder that proves the tool-registry
pluggability pattern. It is REGISTERED but not in any consumer allowlist
(that is established in Wave 3 via Plan 17-03). The run() method returns
a canned ToolResult with metadata={'placeholder': True, ...}.
"""
from __future__ import annotations

from typing import Any

import pytest

from services.agent.tools import WebSearchTool, get_tool_registry
from utils.models import GenerationRequest, ToolContext


def _ctx() -> ToolContext:
    return ToolContext(
        req=GenerationRequest(query="q"),
        tf={},
        retriever=object(),
        llm=object(),
    )


class TestWebSearchToolRegistration:
    def test_web_search_tool_registered(self) -> None:
        """WebSearchTool is registered under name='web_search'."""
        assert "web_search" in get_tool_registry().list()

    def test_web_search_tool_name_classvar(self) -> None:
        """WebSearchTool.name == 'web_search'."""
        assert WebSearchTool.name == "web_search"

    def test_web_search_tool_description_has_placeholder(self) -> None:
        """WebSearchTool.description contains 'Placeholder' (recognizable to reviewers)."""
        assert "Placeholder" in WebSearchTool.description

    def test_web_search_tool_parameters_schema_nonempty(self) -> None:
        """WebSearchTool.parameters_schema is a non-empty JSON Schema with required=['query']."""
        schema = WebSearchTool.parameters_schema
        assert isinstance(schema, dict)
        assert len(schema) > 0
        assert schema.get("required") == ["query"]


class TestWebSearchToolRun:
    @pytest.mark.asyncio
    async def test_placeholder_content(self) -> None:
        """run() returns ToolResult with content='[WebSearchTool placeholder — v1.5+]'."""
        tool = WebSearchTool()
        result = await tool.run({"query": "hello"}, _ctx())
        assert result.content == "[WebSearchTool placeholder — v1.5+]"

    @pytest.mark.asyncio
    async def test_is_error_false(self) -> None:
        """run() returns is_error=False (placeholder is not an error)."""
        tool = WebSearchTool()
        result = await tool.run({"query": "hello"}, _ctx())
        assert result.is_error is False

    @pytest.mark.asyncio
    async def test_metadata_placeholder_true(self) -> None:
        """run() returns metadata['placeholder'] == True."""
        tool = WebSearchTool()
        result = await tool.run({"query": "hello"}, _ctx())
        assert result.metadata.get("placeholder") is True

    @pytest.mark.asyncio
    async def test_metadata_args_echo(self) -> None:
        """run() returns metadata['args'] == the input args dict."""
        tool = WebSearchTool()
        args: dict[str, Any] = {"query": "test search"}
        result = await tool.run(args, _ctx())
        assert result.metadata.get("args") == args

    @pytest.mark.asyncio
    async def test_metadata_latency_ms_nonneg(self) -> None:
        """run() returns metadata['latency_ms'] as int >= 0."""
        tool = WebSearchTool()
        result = await tool.run({"query": "q"}, _ctx())
        assert "latency_ms" in result.metadata
        assert isinstance(result.metadata["latency_ms"], int)
        assert result.metadata["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_no_network_call_with_none_deps(self) -> None:
        """run() succeeds with retriever=None, llm=None (no network calls)."""
        tool = WebSearchTool()
        ctx = ToolContext(
            req=GenerationRequest(query="q"),
            tf={},
            retriever=None,
            llm=None,
        )
        result = await tool.run({"query": "safe"}, ctx)
        assert result.content == "[WebSearchTool placeholder — v1.5+]"


class TestWebSearchToolExclusion:
    def test_web_search_in_registry_list(self) -> None:
        """web_search is in registry.list() — it IS registered."""
        assert "web_search" in get_tool_registry().list()

    def test_search_knowledge_base_in_registry_list(self) -> None:
        """search_knowledge_base is in registry.list()."""
        assert "search_knowledge_base" in get_tool_registry().list()

    def test_refine_search_in_registry_list(self) -> None:
        """refine_search is in registry.list()."""
        assert "refine_search" in get_tool_registry().list()

    def test_allowlist_excludes_web_search(self) -> None:
        """schemas_for with allowlist=['search_knowledge_base','refine_search'] returns 2 schemas (web_search excluded)."""
        schemas = get_tool_registry().schemas_for(
            "anthropic",
            names=["search_knowledge_base", "refine_search"],
        )
        assert len(schemas) == 2
        names = {s["name"] for s in schemas}
        assert "web_search" not in names

    def test_schemas_for_none_returns_3(self) -> None:
        """schemas_for('anthropic', names=None) returns all 3 registered tools."""
        schemas = get_tool_registry().schemas_for("anthropic", names=None)
        assert len(schemas) == 3
        names = {s["name"] for s in schemas}
        assert names == {"search_knowledge_base", "refine_search", "web_search"}
