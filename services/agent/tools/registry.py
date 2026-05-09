"""ToolRegistry — static class registry for agent-runtime tools (Phase 17, AGENT-07).

Tools register via the ``@get_tool_registry().register`` decorator idiom
(Flask/Click/pytest pattern — returns cls unchanged so the class name is
unaffected). The registry is a singleton per process; the ``get_tool_registry()``
factory ensures all registration calls share the same instance.

Provider-shape mapping (D-07/D-08 from 17-CONTEXT):
  - ``"anthropic"`` → ``{"name", "description", "input_schema"}``
  - ``"openai"`` / ``"ollama"`` → ``{"type": "function", "function": {name, description, parameters}}``

Ollama uses the OpenAI-compatible tool format (RESEARCH Decision 2, Assumption A3).
"""

from __future__ import annotations

from typing import Any, List

from services.agent.tools.base import BaseTool


class ToolRegistry:
    """Static class registry for agent tools.

    Each tool class is stored by its ``name`` ClassVar. Instantiation is
    deferred to ``get()`` so the registry holds only classes, never instances
    (stateless dispatch — Wave 2 tools carry no per-call state).
    """

    def __init__(self) -> None:
        self._tools: dict[str, type[BaseTool]] = {}

    def register(self, cls: type[BaseTool]) -> type[BaseTool]:
        """Register a Tool class. Returns ``cls`` unchanged so @decorator syntax works.

        Raises:
            ValueError: if a tool with ``cls.name`` is already registered.
        """
        if cls.name in self._tools:
            raise ValueError(f"Tool {cls.name!r} already registered")
        self._tools[cls.name] = cls
        return cls

    def get(self, name: str) -> BaseTool:
        """Instantiate a fresh tool per call (stateless dispatch).

        Raises:
            KeyError: if no tool with ``name`` is registered.
        """
        try:
            return self._tools[name]()
        except KeyError:
            raise KeyError(f"No tool registered as {name!r}") from None

    def list(self) -> list[str]:
        """Sorted names of all registered tools."""
        return sorted(self._tools.keys())

    def schemas_for(
        self,
        provider: str,
        names: List[str] | None = None,
    ) -> List[dict[str, Any]]:
        """Return tool schemas shaped for the given LLM provider wire format.

        Args:
            provider: ``"anthropic"``, ``"openai"``, or ``"ollama"``.
            names:    If given, only return schemas for these tool names
                      (preserving list order). If ``None``, return all tools.

        Returns:
            List of provider-shaped tool schema dicts.

        Raises:
            ValueError: for unknown provider strings.
        """
        if names is not None:
            tools = [self._tools[n] for n in names if n in self._tools]
        else:
            tools = list(self._tools.values())

        if provider == "anthropic":
            return [
                {
                    "name":         t.name,
                    "description":  t.description,
                    "input_schema": t.parameters_schema,
                }
                for t in tools
            ]
        if provider in ("openai", "ollama"):
            return [
                {
                    "type": "function",
                    "function": {
                        "name":        t.name,
                        "description": t.description,
                        "parameters":  t.parameters_schema,
                    },
                }
                for t in tools
            ]
        raise ValueError(f"Unknown provider: {provider!r}")


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Return the process-wide ToolRegistry singleton.

    Mirrors the ``get_executor()`` / ``get_planner()`` singleton pattern from
    services/agent/executor.py:97-104 and services/agent/planner.py.
    """
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
