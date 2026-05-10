# Agent Architecture

*Status: Phase 19 (v1.4) — Concept + tool-authoring + SSE event-schema trilogy
complete. Read top-to-bottom: the Planner / Executor mental model, then how to
add a tool the planner can pick, then the wire format the executor emits.*

## Planner / Executor Model

The agent runtime is three explicit collaborators: a **Planner** that turns
a conversation into a `ToolPlan`, an **Executor** that dispatches the plan's
parallel groups concurrently, and a **Synthesizer** that composes the final
answer from the accumulated tool results. Each collaborator is a single-purpose
object behind a stable Pydantic V2 contract. The orchestrator (`AgentQueryPipeline`)
is a thin loop over these three.

The Planner is stateless: `(messages, tools) → ToolPlan`. It issues one LLM
call via the provider-neutral `BaseLLMClient.call_agentic_turn` (Phase 11) and
normalizes the assistant turn into a `ToolPlan`. The Executor consumes that
plan and walks `parallel_groups` — each inner list is a wave of step indices
dispatched concurrently via `asyncio.as_completed`, with v1.3 D-01
`BaseException` isolation so a failing sibling does not cancel the rest.
The Synthesizer is the LLM's terminal `call_agentic_turn` after results
return — it sees the tool-result messages and emits the final text-only
plan whose `rationale` IS the answer.

Add tools the planner can pick: see [Authoring Tools](#authoring-tools).

### Flow

```
Request ──▶ AgentQueryPipeline ──▶ Planner.plan_from_messages
                                      │
                                      ▼
                                   ToolPlan ──▶ Executor.execute_plan_streaming
                                                    │
                                                    ▼
                                              parallel groups
                                              (asyncio.as_completed,
                                               BaseException isolation)
                                                    │
                                                    ▼
                                               ToolResult[]
                                                    │
                                                    ▼
                                          Synthesizer (call_agentic_turn) ──▶ Response
```

Each arrow is a single function call. The pipeline issues at most
`MAX_ITERATIONS = 5` planner turns (Phase 16 D-12); each turn either yields
a non-terminal `ToolPlan` (with steps to dispatch) or a terminal one (no
steps, `rationale` is the answer).

### Pydantic V2 Signatures

Planner output is a frozen `ToolPlan`:

```python
class ToolCall(BaseModel):
    """A single tool invocation requested by the LLM in one assistant turn."""
    model_config = ConfigDict(frozen=True)

    id:        str
    name:      str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolPlan(BaseModel):
    """Planner output: an ordered list of ToolCalls plus their parallel-group assignment."""
    model_config = ConfigDict(frozen=True)

    steps:             list[ToolCall]  = Field(default_factory=list)
    parallel_groups:   list[list[int]] = Field(default_factory=list)
    rationale:         str             = ""
    raw_assistant_msg: dict[str, Any]  = Field(default_factory=dict)
    stop_reason:       str             = "text_only"
```

`parallel_groups` is the canonical execution shape: every step index in
`range(len(steps))` MUST appear in exactly one group. A non-empty plan
always has a non-empty `parallel_groups`. `stop_reason` mirrors the upstream
LLM stop reason (`text_only` / `tool_use` / `max_tokens` / `error`).

### Method Signatures

The Planner exposes one async method:

```python
async def plan_from_messages(
    self,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    system: str | None = None,
) -> ToolPlan: ...
```

The Executor exposes the streaming dispatcher consumed by `AgentQueryPipeline.run_streaming`:

```python
async def execute_plan_streaming(
    self,
    plan: ToolPlan,
    tf: dict[str, Any],
    req: GenerationRequest,
    *,
    trace_id: str,
    seq_counter: Iterator[int],
) -> AsyncIterator[AgentEvent | ToolResult | BaseException]: ...
```

The streaming variant yields events at lifecycle boundaries (`tool.span.start`,
`tool.span.end` / `tool.span.error`, `executor.parallel`) interleaved with
the bare results — see [Event Schema Reference](#event-schema-reference)
for the wire format.

### Runnable Example

Drive the full Planner → Executor → Synthesizer loop and print every event:

```python
import asyncio
from services.pipeline import AgentQueryPipeline
from utils.models import GenerationRequest

async def main() -> None:
    pipeline = AgentQueryPipeline()
    req = GenerationRequest(
        query=(
            "Across our compliance, finance, engineering, and HR knowledge "
            "bases, where do we mention 'data retention'?"
        ),
        session_id="demo-session",
        tenant_id="demo-tenant",
        user_id="demo-user",
        top_k=5,
    )
    async for evt in pipeline.run_streaming(req):
        print(
            f"{evt.event_type:>22}  seq={evt.seq:>3}  "
            f"ts={evt.ts_ms}  payload={evt.model_dump_json()}"
        )

asyncio.run(main())
```

This is the same query `make demo-agent` runs; the only difference is that
`make demo-agent` (Phase 19) wires stub Planner + stub `RetrieveTool` so the
snippet is offline-runnable from a clean checkout. To run it against real
LLM + real retrieval, point `LLM_PROVIDER` and `PG_DSN` at live services
and remove the stubs (see `services/agent/_demo_runner.py` for the patch list).

Decode the events on the wire: see [Event Schema Reference](#event-schema-reference).

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

## Event Schema Reference

The agent runtime emits a structured SSE stream on
`POST /api/v1/agent/v1/run/stream` (AGENT-04, Phase 18). Each event is one
SSE frame: `event: <event_type>\ndata: <json>\n\n`. The terminal event is
`synthesizer.final` — no `[DONE]` sentinel. Payloads are Pydantic V2 frozen
models in `utils/models.py` (`AgentEvent` base + 6 concrete subclasses);
every event carries three common fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `trace_id` | string (8-hex) | yes | Per-stream identifier; matches the orchestrator's `trace_id`. |
| `seq` | integer | yes | Monotonic counter; starts at 0; strictly increasing across all event types. |
| `ts_ms` | integer | yes | Unix epoch milliseconds at emit time. |

`event_type` is a `ClassVar[str]` discriminator carried on the SSE `event:`
line — NOT a JSON field. Per-event tables and JSON examples below show
event-specific fields only; `trace_id`/`seq`/`ts_ms` are present on every
payload.

**Redaction policy (D-11):** `tool.span.start.args` is verbatim from the LLM
tool-call. `tool.span.end.content_preview` and `tool.span.error.error_message`
each truncate to 200 chars (full tracebacks log server-side only). Multi-tenant
isolation is preserved by JWT + Postgres RLS at the route layer.

### planner.plan

Emitted once per planner turn after a non-terminal `ToolPlan`. Terminal
plans (no steps; rationale IS the answer) skip this and go straight to
`synthesizer.final`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `plan` | object (`ToolPlan`) | yes | Full planner output: `steps` (list of `ToolCall`), `parallel_groups` (list of int lists), `rationale` (string), `raw_assistant_msg` (provider-shaped dict), `stop_reason` (`text_only`/`tool_use`/`max_tokens`/`error`). |

Example payload:

```json
{"plan": {
   "steps": [{"id": "call_1", "name": "search_knowledge_base", "arguments": {"query": "leave policy"}}],
   "parallel_groups": [[0]],
   "rationale": "single-hop retrieve",
   "raw_assistant_msg": {"role": "assistant", "content": "..."},
   "stop_reason": "tool_use"
}}
```

### tool.span.start

Emitted once per tool dispatch BEFORE the dispatch awaits. Within a parallel
group, all starts fire before any task resolves.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `span_id` | string (8-hex) | yes | Per-dispatch identifier; matches the corresponding end-or-error event. |
| `name` | string | yes | Registered tool name (e.g. `search_knowledge_base`). |
| `args` | object | yes | LLM-provided arguments verbatim. **Not redacted** — see policy above. |

Example payload:

```json
{"span_id": "9f3c1e2a", "name": "search_knowledge_base", "args": {"query": "leave policy"}}
```

### tool.span.end

Emitted when a tool dispatch resolves to `ToolResult`; replaced by
`tool.span.error` when the dispatch raises `BaseException`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `span_id` | string (8-hex) | yes | Matches the prior `tool.span.start`. |
| `latency_ms` | integer | yes | Wall-clock ms for this single dispatch (per-tool, not per-group). |
| `chunk_count` | integer | yes | From `ToolResult.metadata["chunk_count"]` with `len(ToolResult.chunks)` fallback (Phase 17 D-02). |
| `is_error` | boolean | yes | `True` if the tool returned a controlled error result (e.g. RetrieveTool fallback). |
| `content_preview` | string | yes | First 200 characters of `ToolResult.content`. |

Example payload:

```json
{"span_id": "9f3c1e2a", "latency_ms": 412, "chunk_count": 3, "is_error": false,
 "content_preview": "<context>\n[来源1] 员工产假为98天..."}
```

### tool.span.error

Emitted INSTEAD OF `tool.span.end` when a dispatch raises `BaseException`
(incl. `CancelledError`, `TimeoutError`). v1.3 D-01 isolation preserved —
siblings in the parallel group continue running.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `span_id` | string (8-hex) | yes | Matches the prior `tool.span.start`. |
| `latency_ms` | integer | yes | Wall-clock ms before the exception was raised. |
| `error_type` | string | yes | `type(exc).__name__` (e.g. `RuntimeError`, `TimeoutError`). |
| `error_message` | string | yes | First 200 characters of `str(exc)`. Full traceback logged server-side only. |

Example payload:

```json
{"span_id": "9f3c1e2a", "latency_ms": 5, "error_type": "RuntimeError",
 "error_message": "vector store connection refused"}
```

### executor.parallel

Emitted once per parallel group at group END (D-09 / D-15 option c — fires
after all child `tool.span.end` / `tool.span.error` events so
`group_latency_ms` is always populated; bounded by the slowest tool).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `fan_out` | integer | yes | Number of tools dispatched in this group. |
| `group_latency_ms` | integer | yes | Wall-clock ms for the entire group (bounded by `max(tool_latency)`, not sum). |

Example payload: `{"fan_out": 3, "group_latency_ms": 510}`

### synthesizer.final

Terminal event. Emitted exactly once per stream (terminal plan, max-
iterations cap, or error fallback). No `[DONE]` sentinel — this IS the
terminal frame; `seq` is the highest in the stream.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `answer` | string | yes | Composed final answer text. Empty string if all iterations errored. |
| `sources_count` | integer | yes | Total deduplicated chunks accumulated across all tool dispatches. |

Example payload: `{"answer": "员工产假为 98 天 [来源1]...", "sources_count": 5}`

### Consuming the Stream

Minimal browser consumer (one `addEventListener` per event type):

```javascript
const es = new EventSource('/api/v1/agent/v1/run/stream'), J = (e) => JSON.parse(e.data);
es.addEventListener('planner.plan',      (e) => { const v = J(e); console.log('plan:', v.plan.parallel_groups, v.plan.rationale); });
es.addEventListener('tool.span.start',   (e) => { const v = J(e); console.log(`start ${v.name} span=${v.span_id}`, v.args); });
es.addEventListener('tool.span.end',     (e) => { const v = J(e); console.log(`end ${v.span_id} ${v.latency_ms}ms ${v.chunk_count} chunks`); });
es.addEventListener('tool.span.error',   (e) => { const v = J(e); console.warn(`err ${v.span_id} ${v.error_type}: ${v.error_message}`); });
es.addEventListener('executor.parallel', (e) => { const v = J(e); console.log(`group fan_out=${v.fan_out} ${v.group_latency_ms}ms`); });
es.addEventListener('synthesizer.final', (e) => { const v = J(e); console.log('final:', v.answer); es.close(); });
```

`EventSource` issues GET; this route accepts POST. For POST-SSE use `fetch`
with a streaming reader (Phase 19's `make demo-agent` ships a runnable example).
