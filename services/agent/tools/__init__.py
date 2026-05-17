"""services.agent.tools — Tool abstraction layer (Phase 17, AGENT-07).

Wave 1 (Plan 17-01) ships BaseTool + ToolRegistry + ToolResult/ToolContext
in isolation. Wave 2 (Plan 17-02) registers RetrieveTool + RefinedRetrieveTool
+ WebSearchTool here via @get_tool_registry().register at module top.
Wave 3 (Plan 17-03) swaps Executor + AgentQueryPipeline callsites to read
from this registry.
Phase 24 (Plan 24-04) adds RecallTool via conditional import (D-B4 / Pattern 3).
"""

from config.settings import settings
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry, get_tool_registry

# Side-effect imports trigger @get_tool_registry().register decorators at
# package load time (RESEARCH §Decision 3 — explicit named imports).
from services.agent.tools.retrieve import (  # noqa: F401
    RefinedRetrieveTool,
    RetrieveTool,
    retrieve_impl,
)
from services.agent.tools.web_search import WebSearchTool  # noqa: F401

# Phase 24 / D-B4 / Pattern 3 — kill-switch via conditional registration.
# When False, the decorator never runs → registry.get("recall_memory")
# raises KeyError → planner-LLM never sees the tool schema.
# __all__ intentionally excludes RecallTool — consumers go through
# get_tool_registry().get("recall_memory") to avoid surprising ImportError
# when the toggle is False (analog-4 swap-list row 3).
if settings.recall_tool_enabled:
    from services.agent.tools.recall import RecallTool  # noqa: F401

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "get_tool_registry",
    "RetrieveTool",
    "RefinedRetrieveTool",
    "WebSearchTool",
    "retrieve_impl",
]
