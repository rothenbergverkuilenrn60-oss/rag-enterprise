"""services.agent — agent runtime: planner, executor, shared tool helper.

Phase 16 (v1.4 Agent-First Architecture Inversion) introduced this package
as the umbrella for the new collaborator boundary. ``AgentQueryPipeline``
in services/pipeline.py becomes a thin orchestrator over these primitives
in Wave 3 (Plan 16-03).
"""

from services.agent.executor import Executor, get_executor
from services.agent.planner import Planner, PlannerOutputError, get_planner
from services.agent.tool_executor import execute_tool_call

__all__ = [
    "Executor",
    "Planner",
    "PlannerOutputError",
    "execute_tool_call",
    "get_executor",
    "get_planner",
]
