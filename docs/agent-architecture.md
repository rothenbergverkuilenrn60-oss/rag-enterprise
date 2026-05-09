# Agent Architecture

*Status: Phase 17 (v1.4) — Tool abstraction shipped. This document is the
tool-author quick-start. SSE event schemas (Phase 18) and historical intent
mapping (Phase 19) extend this file later.*

## Authoring Tools

The agent runtime dispatches tool calls through a static class registry
(`services/agent/tools/registry.py`). New tools subclass `BaseTool`,
declare three ClassVar attributes, implement an async `run` method, and
register themselves at module import time.

### Defining a Tool

1. Subclass `BaseTool` from `services.agent.tools.base`.
2. Declare three required ClassVar attributes:
   - `name: ClassVar[str]` — unique identifier used by the planner LLM.
   - `description: ClassVar[str]` — what the tool does, in the user's language.
   - `parameters_schema: ClassVar[dict[str, Any]]` — provider-neutral JSON Schema
     describing the tool's argument shape.
3. Implement `async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult`.
   `args` is the parsed argument dict from the LLM's tool call. `ctx` carries
   the request, tenant filter, retriever, and LLM client.

### Registering a Tool

Decorate the class with `@get_tool_registry().register` at module top.
Registration happens at module import time, not at runtime.

```python
from services.agent.tools.registry import get_tool_registry

@get_tool_registry().register
class MyTool(BaseTool):
    ...
```

`services/agent/tools/__init__.py` imports each tool module to trigger
the decorator at package load time. Add new tool modules there.

### parameters_schema Shape

`parameters_schema` is a provider-neutral JSON Schema dict. The
`ToolRegistry.schemas_for(provider)` method maps it to the wire format
each LLM provider expects:

- **Anthropic** — `{"name", "description", "input_schema": {...}}`.
- **OpenAI / Ollama** — `{"type": "function", "function": {"name", "description", "parameters": {...}}}`.

Tool authors write one schema; the registry handles provider mapping.

### Allowlisting

The planner sees only tools listed in `AGENT_TOOL_ALLOWLIST` in
`services/pipeline.py`. Tools registered but not in the allowlist (e.g.,
`WebSearchTool` placeholder) appear in `registry.list()` but are never
sent to the planner LLM.

### Runnable Example

`services/agent/tools/web_search.py` (the v1.4 placeholder) is the canonical
minimal example:

```python
from typing import Any, ClassVar
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from utils.models import ToolContext, ToolResult

@get_tool_registry().register
class WebSearchTool(BaseTool):
    name:              ClassVar[str]            = "web_search"
    description:       ClassVar[str]            = (
        "Search the public web for current information. "
        "(Placeholder: v1.5+ implementation pending.)"
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Web search query"}},
        "required": ["query"],
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(
            content="[WebSearchTool placeholder — v1.5+]",
            metadata={"placeholder": True, "args": args, "latency_ms": 0},
        )
```

This tool registers at import; appears in `registry.list()` as `"web_search"`;
is excluded from `AGENT_TOOL_ALLOWLIST` so the planner does not see it.

### ToolResult metadata convention

Phase 18 SSE event consumers read these keys from `ToolResult.metadata`:
`latency_ms: int`, `query: str`, `placeholder: bool`, `chunk_count: int`.
