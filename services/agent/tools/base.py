"""BaseTool — provider-neutral Tool abstraction (Phase 17, AGENT-07).

All concrete tools must subclass ``BaseTool`` and declare three ClassVars:
``name``, ``description``, and ``parameters_schema``. The ``__init_subclass__``
guard enforces this at class-definition time, catching missing declarations
before any test or runtime dispatch attempts instantiation (RESEARCH Pitfall 2).

Wave 1 (17-01): ships this ABC in isolation.
Wave 2 (17-02): RetrieveTool + RefinedRetrieveTool + WebSearchTool register
                against ToolRegistry using this base.
Wave 3 (17-03): AgentQueryPipeline.run reads provider_name from the LLM client
                and calls ToolRegistry.schemas_for() instead of the inline
                _AGENT_TOOLS literal.
"""

from __future__ import annotations

import abc
from typing import Any, ClassVar

from utils.models import ToolContext, ToolResult


class BaseTool(abc.ABC):
    """Abstract base class for agent-runtime tools.

    Subclasses MUST declare:
      - ``name: ClassVar[str]``              — unique tool identifier
      - ``description: ClassVar[str]``       — human-readable description for LLM
      - ``parameters_schema: ClassVar[dict[str, Any]]`` — JSON Schema for tool input

    The ``__init_subclass__`` guard raises ``TypeError`` at class-body evaluation
    time if any of these are missing on a concrete (non-abstract) subclass.
    """

    name:              ClassVar[str]
    description:       ClassVar[str]
    parameters_schema: ClassVar[dict[str, Any]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Only enforce on concrete (non-abstract) subclasses — intermediate
        # abstract bases are allowed to omit ClassVars.
        if not getattr(cls, "__abstractmethods__", None):
            for attr in ("name", "description", "parameters_schema"):
                if not hasattr(cls, attr):
                    raise TypeError(
                        f"{cls.__name__} must define ClassVar {attr!r}"
                    )

    @abc.abstractmethod
    async def run(
        self,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        """Execute the tool. MUST be overridden by every concrete subclass."""

    def _build_error_result(
        self,
        exc: Exception,
        latency_ms: int = 0,
    ) -> ToolResult:
        """Construct an is_error=True ToolResult preserving Phase 18 SSE contract.

        ``content`` includes the tool name and exception message so the orchestrator
        can surface a meaningful error in the tool_result block without exposing
        internal tracebacks to the LLM.
        """
        return ToolResult(
            content=f"[{self.name}] error: {exc}",
            is_error=True,
            metadata={"latency_ms": latency_ms},
        )
