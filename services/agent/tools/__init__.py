"""services.agent.tools — Tool abstraction layer (Phase 17, AGENT-07).

Wave 1 (Plan 17-01) ships BaseTool in isolation. ToolRegistry + get_tool_registry
are added in T5 once registry.py exists.
Wave 2 (Plan 17-02) registers RetrieveTool + RefinedRetrieveTool
+ WebSearchTool here via @get_tool_registry().register at module top.
Wave 3 (Plan 17-03) swaps Executor + AgentQueryPipeline callsites to read
from this registry.
"""

from services.agent.tools.base import BaseTool

__all__ = [
    "BaseTool",
]
