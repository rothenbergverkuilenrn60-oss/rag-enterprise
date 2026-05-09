"""Unit tests for BaseTool ABC + ToolResult/ToolContext models (Phase 17-01, RED→GREEN).

RED gate: tests fail with ImportError until T3 (ToolResult/ToolContext) and
T4 (BaseTool) are implemented.

Test structure mirrors test_planner.py (class-grouped, pytest.raises pattern).
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest
import pydantic

from utils.models import GenerationRequest, ToolContext, ToolResult
from services.agent.tools.base import BaseTool


# ──────────────────────────────────────────────────────────────
# Module-level fixture: a well-formed concrete tool
# ──────────────────────────────────────────────────────────────

class _FakeTool(BaseTool):
    """Concrete test double: all three ClassVars set; run returns canned result."""

    name: ClassVar[str] = "fake"
    description: ClassVar[str] = "Fake tool for unit tests"
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(content="fake-result", metadata={"latency_ms": 0})


# ──────────────────────────────────────────────────────────────
# TestToolResultModel
# ──────────────────────────────────────────────────────────────

class TestToolResultModel:
    def test_default_construction(self) -> None:
        r = ToolResult(content="hi")
        assert r.content == "hi"
        assert r.chunks == []
        assert r.metadata == {}
        assert r.is_error is False

    def test_frozen_raises_validation_error(self) -> None:
        r = ToolResult(content="hi")
        with pytest.raises(pydantic.ValidationError):
            r.content = "x"  # type: ignore[misc]

    def test_round_trip_full(self) -> None:
        r = ToolResult(
            content="x",
            chunks=["chunk-a"],
            metadata={"latency_ms": 5},
            is_error=True,
        )
        d = r.model_dump()
        assert d["content"] == "x"
        assert d["chunks"] == ["chunk-a"]
        assert d["metadata"] == {"latency_ms": 5}
        assert d["is_error"] is True


# ──────────────────────────────────────────────────────────────
# TestToolContextModel
# ──────────────────────────────────────────────────────────────

class TestToolContextModel:
    def test_arbitrary_types_allowed(self) -> None:
        req = GenerationRequest(query="q")
        ctx = ToolContext(req=req, tf={}, retriever=object(), llm=object())
        assert ctx.req.query == "q"
        assert ctx.tf == {}

    def test_frozen_raises_validation_error(self) -> None:
        req = GenerationRequest(query="q")
        ctx = ToolContext(req=req, tf={}, retriever=object(), llm=object())
        with pytest.raises(pydantic.ValidationError):
            ctx.tf = {"x": 1}  # type: ignore[misc]


# ──────────────────────────────────────────────────────────────
# TestBaseToolABC
# ──────────────────────────────────────────────────────────────

class TestBaseToolABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError, match="Can't instantiate abstract"):
            BaseTool()  # type: ignore[abstract]

    def test_classvar_guard_missing_name(self) -> None:
        with pytest.raises(TypeError, match="must define ClassVar 'name'"):
            class _Broken(BaseTool):
                description: ClassVar[str] = "x"
                parameters_schema: ClassVar[dict[str, Any]] = {}

                async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
                    return ToolResult(content="")

    def test_classvar_guard_missing_description(self) -> None:
        with pytest.raises(TypeError, match="must define ClassVar 'description'"):
            class _Broken(BaseTool):
                name: ClassVar[str] = "broken"
                parameters_schema: ClassVar[dict[str, Any]] = {}

                async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
                    return ToolResult(content="")

    def test_classvar_guard_missing_parameters_schema(self) -> None:
        with pytest.raises(TypeError, match="must define ClassVar 'parameters_schema'"):
            class _Broken(BaseTool):
                name: ClassVar[str] = "broken"
                description: ClassVar[str] = "x"

                async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
                    return ToolResult(content="")

    def test_concrete_subclass_with_all_classvars_instantiates(self) -> None:
        tool = _FakeTool()
        assert isinstance(tool, BaseTool)
        req = GenerationRequest(query="q")
        ctx = ToolContext(req=req, tf={}, retriever=object(), llm=object())
        result = asyncio.get_event_loop().run_until_complete(tool.run({}, ctx))
        assert result.content == "fake-result"


# ──────────────────────────────────────────────────────────────
# TestBaseToolHelpers
# ──────────────────────────────────────────────────────────────

class TestBaseToolHelpers:
    def test_build_error_result(self) -> None:
        tool = _FakeTool()
        exc = ValueError("something went wrong")
        result = tool._build_error_result(exc, latency_ms=42)
        assert result.is_error is True
        assert "fake" in result.content
        assert "something went wrong" in result.content
        assert result.metadata["latency_ms"] == 42
