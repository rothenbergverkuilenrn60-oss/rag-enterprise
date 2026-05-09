"""Runtime stubs for `make demo-agent` (Phase 19, AGENT-08).

Promoted from ``tests/unit/test_agent_sse.py`` Phase 18 fixtures so the demo
runner and the demo integration test consume a single source of truth
(CONTEXT.md D-05 / D-06).
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Final

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry
from utils.models import ToolCall, ToolContext, ToolPlan, ToolResult

DEMO_QUERY: Final[str] = (
    "Across our compliance, finance, engineering, and HR knowledge bases, "
    "where do we mention 'data retention'?"
)

DEMO_KB_SHARDS: Final[tuple[str, ...]] = ("compliance", "finance", "engineering", "hr")

_DEMO_TERMINAL_ANSWER: Final[str] = (
    "Found references to 'data retention' across all 4 knowledge bases — "
    "see span results above."
)


class DemoStubPlanner:
    """First call returns the 4-tool fan-out, second call terminates (D-05)."""

    def __init__(self) -> None:
        self._call_count: int = 0

    async def plan_from_messages(
        self,
        messages: list[dict[str, Any]] | None = None,
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
    ) -> ToolPlan:
        self._call_count += 1
        if self._call_count == 1:
            steps = [
                ToolCall(
                    id=f"c{i}",
                    name="search_knowledge_base",
                    arguments={"query": DEMO_QUERY, "kb_shard": DEMO_KB_SHARDS[i]},
                )
                for i in range(4)
            ]
            return ToolPlan(
                steps=steps,
                parallel_groups=[[0, 1, 2, 3]],
                rationale="Fan out across 4 KBs in parallel",
                raw_assistant_msg={"role": "assistant", "content": "stub"},
                stop_reason="tool_use",
            )
        return ToolPlan(
            raw_assistant_msg={"role": "assistant", "content": _DEMO_TERMINAL_ANSWER},
            rationale=_DEMO_TERMINAL_ANSWER,
            stop_reason="text_only",
        )


def make_fake_retrieve_tool(
    name: str = "search_knowledge_base",
    sleep_s: float = 0.5,
    content: str = "[fixture chunk]",
) -> type[BaseTool]:
    """Build a fixture ``BaseTool`` subclass; ``chunk_count=3`` per D-06."""
    tool_name = name  # rebind so class body can reference (Python class-scope LEGB)

    class _Fake(BaseTool):
        name:              ClassVar[str]            = tool_name
        description:       ClassVar[str]            = "fake"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            return ToolResult(
                content=content,
                chunks=[],
                metadata={"latency_ms": int(sleep_s * 1000), "chunk_count": 3},
            )

    _Fake.__name__ = f"FakeTool_{tool_name}"
    return _Fake


def build_demo_registry(*tool_classes: type[BaseTool]) -> ToolRegistry:
    """Return a fresh ``ToolRegistry`` with each class registered (T-19-01-02)."""
    reg = ToolRegistry()
    for cls in tool_classes:
        reg.register(cls)
    return reg
