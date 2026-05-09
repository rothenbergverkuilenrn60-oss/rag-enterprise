"""services.agent.tools — Tool abstraction layer (Phase 17, AGENT-07).

Wave 1 (Plan 17-01) ships BaseTool + ToolRegistry + ToolResult/ToolContext
in isolation. Wave 2 (Plan 17-02) registers RetrieveTool + RefinedRetrieveTool
+ WebSearchTool here via @get_tool_registry().register at module top.
Wave 3 (Plan 17-03) swaps Executor + AgentQueryPipeline callsites to read
from this registry.
"""

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry, get_tool_registry

# Side-effect imports trigger @get_tool_registry().register decorators at
# package load time (RESEARCH §Decision 3 — explicit named imports).
from services.agent.tools.retrieve import (  # noqa: F401
    RefinedRetrieveTool,
    RetrieveTool,
    retrieve_impl,
)

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "get_tool_registry",
    "RetrieveTool",
    "RefinedRetrieveTool",
    "retrieve_impl",
]
