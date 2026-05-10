"""Unit tests for ToolRegistry + get_tool_registry singleton (Phase 17-01, RED→GREEN).

RED gate: tests fail with ImportError until T5 (ToolRegistry) is implemented.

Structure mirrors test_planner.py (class-grouped, fresh-registry-per-test isolation).
ONLY TestSingleton calls get_tool_registry() — all other tests use ToolRegistry()
directly to avoid singleton state cross-contamination.

_EXPECTED_AGENT_TOOLS is the byte-identical parity copy of services/pipeline.py
AgentQueryPipeline._AGENT_TOOLS. Wave 3 will delete that literal; TestParity
guards against drift in RetrieveTool.parameters_schema (Wave 2).
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry, get_tool_registry
from utils.models import ToolContext, ToolResult

# ──────────────────────────────────────────────────────────────
# Parity constant — BYTE-IDENTICAL to services/pipeline.py
# AgentQueryPipeline._AGENT_TOOLS (lines 602-640 at Phase 17 baseline).
# When Wave 3 deletes _AGENT_TOOLS, this constant becomes the parity contract.
# ──────────────────────────────────────────────────────────────

_EXPECTED_AGENT_TOOLS = [
    {
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
    },
    {
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
    },
]


# ──────────────────────────────────────────────────────────────
# Module-level fixtures
# ──────────────────────────────────────────────────────────────

class _FakeTool(BaseTool):
    """Minimal concrete tool for registry tests."""

    name: ClassVar[str] = "fake"
    description: ClassVar[str] = "A fake tool for registry unit tests"
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(content="fake")


class _FakeRetrieveTool(BaseTool):
    """Parity-test tool whose schema matches _AGENT_TOOLS[0] exactly."""

    name: ClassVar[str] = "search_knowledge_base"
    description: ClassVar[str] = "在企业知识库中搜索相关信息"
    parameters_schema: ClassVar[dict[str, Any]] = {
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

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(content="retrieved")


class _FakeRefineTool(BaseTool):
    """Parity-test tool whose schema matches _AGENT_TOOLS[1] exactly."""

    name: ClassVar[str] = "refine_search"
    description: ClassVar[str] = "用更精确的关键词细化搜索，适用于初次搜索结果不够具体时"
    parameters_schema: ClassVar[dict[str, Any]] = {
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

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(content="refined")


# ──────────────────────────────────────────────────────────────
# TestToolRegistryRegister
# ──────────────────────────────────────────────────────────────

class TestToolRegistryRegister:
    def test_register_returns_cls_unchanged(self) -> None:
        registry = ToolRegistry()
        result = registry.register(_FakeTool)
        assert result is _FakeTool
        assert registry.list() == ["fake"]

    def test_duplicate_registration_raises_value_error(self) -> None:
        registry = ToolRegistry()
        registry.register(_FakeTool)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_FakeTool)

    def test_decorator_syntax_returns_original_class(self) -> None:
        registry = ToolRegistry()

        @registry.register
        class _MyTool(BaseTool):
            name: ClassVar[str] = "my_tool"
            description: ClassVar[str] = "A tool"
            parameters_schema: ClassVar[dict[str, Any]] = {}

            async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
                return ToolResult(content="")

        assert _MyTool.name == "my_tool"
        assert "my_tool" in registry.list()


# ──────────────────────────────────────────────────────────────
# TestToolRegistryGet
# ──────────────────────────────────────────────────────────────

class TestToolRegistryGet:
    def test_get_returns_fresh_instance(self) -> None:
        registry = ToolRegistry()
        registry.register(_FakeTool)
        a = registry.get("fake")
        b = registry.get("fake")
        assert isinstance(a, _FakeTool)
        assert a is not b  # stateless dispatch — fresh per call

    def test_get_unknown_raises_key_error(self) -> None:
        registry = ToolRegistry()
        with pytest.raises(KeyError, match="No tool registered as 'nonexistent'"):
            registry.get("nonexistent")


# ──────────────────────────────────────────────────────────────
# TestToolRegistryList
# ──────────────────────────────────────────────────────────────

class TestToolRegistryList:
    def test_list_returns_sorted_names(self) -> None:
        registry = ToolRegistry()

        class _ZTool(BaseTool):
            name: ClassVar[str] = "fake_z"
            description: ClassVar[str] = "z"
            parameters_schema: ClassVar[dict[str, Any]] = {}

            async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
                return ToolResult(content="")

        class _ATool(BaseTool):
            name: ClassVar[str] = "fake_a"
            description: ClassVar[str] = "a"
            parameters_schema: ClassVar[dict[str, Any]] = {}

            async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
                return ToolResult(content="")

        registry.register(_ZTool)
        registry.register(_ATool)
        assert registry.list() == ["fake_a", "fake_z"]


# ──────────────────────────────────────────────────────────────
# TestProviderMapping
# ──────────────────────────────────────────────────────────────

class TestProviderMapping:
    def _registry_with_fake(self) -> ToolRegistry:
        registry = ToolRegistry()
        registry.register(_FakeTool)
        return registry

    def test_schemas_for_anthropic(self) -> None:
        registry = self._registry_with_fake()
        result = registry.schemas_for("anthropic", names=["fake"])
        assert len(result) == 1
        item = result[0]
        assert set(item.keys()) == {"name", "description", "input_schema"}
        assert item["name"] == "fake"
        assert item["description"] == "A fake tool for registry unit tests"
        assert item["input_schema"] == {"type": "object", "properties": {}}

    def test_schemas_for_openai(self) -> None:
        registry = self._registry_with_fake()
        result = registry.schemas_for("openai", names=["fake"])
        assert len(result) == 1
        item = result[0]
        assert set(item.keys()) == {"type", "function"}
        assert item["type"] == "function"
        fn = item["function"]
        assert set(fn.keys()) == {"name", "description", "parameters"}
        assert fn["name"] == "fake"
        assert fn["description"] == "A fake tool for registry unit tests"
        assert fn["parameters"] == {"type": "object", "properties": {}}

    def test_schemas_for_ollama_same_as_openai(self) -> None:
        registry = self._registry_with_fake()
        openai_result = registry.schemas_for("openai", names=["fake"])
        ollama_result = registry.schemas_for("ollama", names=["fake"])
        assert ollama_result == openai_result

    def test_schemas_for_unknown_provider_raises(self) -> None:
        registry = self._registry_with_fake()
        with pytest.raises(ValueError, match="Unknown provider"):
            registry.schemas_for("gemini", names=["fake"])

    def test_schemas_for_none_names_returns_all(self) -> None:
        registry = ToolRegistry()
        registry.register(_FakeTool)

        class _AnotherTool(BaseTool):
            name: ClassVar[str] = "another"
            description: ClassVar[str] = "another tool"
            parameters_schema: ClassVar[dict[str, Any]] = {}

            async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
                return ToolResult(content="")

        registry.register(_AnotherTool)
        result = registry.schemas_for("anthropic", names=None)
        names_returned = {item["name"] for item in result}
        assert names_returned == {"fake", "another"}


# ──────────────────────────────────────────────────────────────
# TestSingleton
# ──────────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_tool_registry_singleton(self) -> None:
        r1 = get_tool_registry()
        r2 = get_tool_registry()
        assert r1 is r2


# ──────────────────────────────────────────────────────────────
# TestParity — byte-identical to _AGENT_TOOLS from services/pipeline.py
# ──────────────────────────────────────────────────────────────

class TestParity:
    def test_schemas_for_anthropic_matches_agent_tools_literal(self) -> None:
        """Parity gate: ToolRegistry output must be byte-identical to the
        _AGENT_TOOLS literal in services/pipeline.py (lines 602-640 at
        Phase 17 baseline). Wave 3 will delete that literal; this test
        prevents silent drift in tool schemas.
        """
        registry = ToolRegistry()
        registry.register(_FakeRetrieveTool)
        registry.register(_FakeRefineTool)
        result = registry.schemas_for(
            "anthropic",
            names=["search_knowledge_base", "refine_search"],
        )
        assert result == _EXPECTED_AGENT_TOOLS


# ──────────────────────────────────────────────────────────────
# TestProviderNameClassVar  (added in T6 — provider_name on LLM clients)
# ──────────────────────────────────────────────────────────────

class TestProviderNameClassVar:
    def test_base_default(self) -> None:
        from services.generator.llm_client import BaseLLMClient
        assert BaseLLMClient.provider_name == "anthropic"

    def test_anthropic(self) -> None:
        from services.generator.llm_client import AnthropicLLMClient
        assert AnthropicLLMClient.provider_name == "anthropic"

    def test_openai(self) -> None:
        from services.generator.llm_client import OpenAILLMClient
        assert OpenAILLMClient.provider_name == "openai"

    def test_ollama_uses_openai_format(self) -> None:
        from services.generator.llm_client import OllamaLLMClient
        assert OllamaLLMClient.provider_name == "openai"
