# Phase 17: Tool Abstraction + RetrieveTool - Research

**Researched:** 2026-05-09
**Domain:** Python ABC / Pydantic V2 / provider-neutral tool registry / async dispatch
**Confidence:** HIGH

## Summary

Phase 17 is an internal refactor with all major architecture decisions locked in CONTEXT.md (D-01..D-12).
Research confirms the locked decisions are sound and surfaces three actionable answers for the open shape
decisions the planner must pick: (1) explicit-import side-effect strategy for tool registration wins,
(2) `provider_name: ClassVar[str]` on `BaseLLMClient` is cleaner than `type().__name__` mapping,
(3) module-level `AGENT_TOOL_ALLOWLIST` constant (not a class flag) is the right WebSearchTool exclusion
mechanism for testability and Phase 18 SSE filtering.

Key risk mitigated: `ToolResult.metadata` covers Phase 18 `tool.span` needs but the `latency_ms`
convention must be documented in the `ToolResult` docstring — otherwise Phase 18 gets `KeyError`.

**Primary recommendation:** Follow D-01..D-12 verbatim. Pick the three open shapes per this document
Section "Recommendations on 3 Open Shape Decisions." No new library dependencies needed.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: BaseTool ABC at `services/agent/tools/base.py`; ClassVar name/description/parameters_schema; @abstractmethod async def run(args, ctx)
- D-02: ToolResult Pydantic V2 frozen in utils/models.py; fields: content/chunks/metadata/is_error
- D-03: ToolContext Pydantic V2 frozen; fields: req/tf/retriever/llm
- D-04: RetrieveTool.run() body = verbatim execute_tool_call body adapted; tool_executor.py DELETED
- D-05: Two registered classes — RetrieveTool (search_knowledge_base) + RefinedRetrieveTool (refine_search) sharing _retrieve_impl
- D-06: _AGENT_TOOLS literal DELETED; AgentQueryPipeline uses registry.schemas_for(provider, names=AGENT_TOOL_ALLOWLIST)
- D-07: ToolRegistry class with register/get/list/schemas_for; @register decorator; get_tool_registry() singleton
- D-08: Provider-shape mapping (Anthropic input_schema vs OpenAI parameters) in registry adapter
- D-09: Executor._dispatch_one swaps to registry.get(name).run(args, ctx); no name-imports of tools in pipeline code
- D-10: WebSearchTool registered but excluded from AgentQueryPipeline.AGENT_TOOL_ALLOWLIST
- D-11: SwarmQueryPipeline scope-reduced (v1.5+ migration)
- D-12: No IntentRouter (carry-forward Phase 16 D-13)

### Claude's Discretion
- docs/agent-architecture.md#authoring-tools stub minimum content
- retrieve_multi_query not exposed as tool
- Provider name selection mechanism on BaseLLMClient (open — this research picks one)
- Module layout: services/agent/tools/ package structure
- WebSearchTool exclusion mechanism (open — this research picks one)
- __init__.py import strategy (open — this research picks one)

### Deferred Ideas (OUT OF SCOPE)
- Collapse search_knowledge_base + refine_search into single tool (v1.5+)
- MultiQueryRetrieveTool (v1.5+)
- SwarmQueryPipeline registry migration (v1.5+)
- Real WebSearchTool implementation (v1.5+)
- MCP plug-in discovery (10x roadmap #3)
- Per-tool retry/circuit-breaker policy
- Tool lifecycle hooks
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AGENT-07 | Provider-neutral Tool ABC; RetrieveTool wrapping retrieval; ≥1 skeletal placeholder; static class registry; MCP-replaceable abstraction | D-01..D-10 lock all structure; research confirms patterns are idiomatic and landmine-free |
</phase_requirements>

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tool protocol definition (BaseTool ABC) | services/agent/tools/ | — | Agent runtime owns tool abstraction; no pipeline tier involvement |
| Tool registry + singleton | services/agent/tools/registry.py | services/agent/__init__.py (re-export) | Matches get_planner/get_executor Phase 16 factory pattern |
| Provider-schema mapping | ToolRegistry.schemas_for() | — | D-08: mapping centralized in registry, NOT in LLM adapters |
| RetrieveTool dispatch | services/agent/tools/retrieve.py | services/retriever/ (untouched) | Tool wraps retriever; retriever internals unchanged |
| Executor dispatch seam | services/agent/executor.py | — | Single call-site surgery: _dispatch_one (≤5 lines) |
| ToolResult / ToolContext models | utils/models.py | — | D-02/D-03: matches ToolCall/ToolPlan placement (Phase 16 precedent) |
| Swarm compatibility shim | services/agent/tools/retrieve.py (retrieve_impl public) | services/pipeline.py (Swarm import) | D-11: Swarm switches import path only; no registry wiring |

---

## Anthropic vs OpenAI Tool Schema Canonical Mapping

### Anthropic tool shape [VERIFIED: Context7 / anthropics/anthropic-sdk-python]

Source: https://github.com/anthropics/anthropic-sdk-python/blob/main/tools.md

```python
# Anthropic wire shape (what call_agentic_turn / chat_with_tools consumes)
{
    "name": "search_knowledge_base",
    "description": "在企业知识库中搜索相关信息",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索查询词"},
            "top_k": {"type": "integer", "default": 5},
        },
        "required": ["query"],
        # Optional: "additionalProperties": false  (when using @beta_tool)
    }
}
```

`input_schema` is the full JSON Schema object. Anthropic's `@beta_tool` decorator adds
`"additionalProperties": false` automatically — the registry does NOT need to add it for
existing tools, but MAY add it for stricter validation. Current pipeline.py line 602-640 uses
`input_schema` WITHOUT `additionalProperties: false` — match this for parity.

### OpenAI tool shape [VERIFIED: Context7 / openai/openai-python]

Source: https://github.com/openai/openai-python/blob/main/src/openai/lib/_tools.py

```python
# OpenAI wire shape
{
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": "...",
        "parameters": {          # same JSON Schema body as Anthropic's input_schema
            "type": "object",
            "properties": {...},
            "required": [...],
        },
        # Optional: "strict": True  (only for OpenAI structured outputs / pydantic_function_tool)
    }
}
```

### Canonical mapping in `ToolRegistry.schemas_for`

```python
def schemas_for(self, provider: str, names: list[str] | None = None) -> list[dict[str, Any]]:
    tools = [t for t in self._tools.values() if names is None or t.name in names]
    if provider == "anthropic":
        return [{"name": t.name, "description": t.description, "input_schema": t.parameters_schema} for t in tools]
    elif provider in ("openai", "ollama"):
        return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters_schema}} for t in tools]
    raise ValueError(f"Unknown provider: {provider!r}")
```

**Subtle differences:**
- Anthropic: top-level `input_schema` key. OpenAI: nested under `"function"` with key `"parameters"`.
- OpenAI `strict: True` applies only when using `pydantic_function_tool` — NOT needed for Phase 17 manual schemas.
- Anthropic does NOT have a `type: "function"` wrapper at top level.
- Both providers accept identical JSON Schema body (`type/properties/required`) — `parameters_schema` declared once on BaseTool works for both.
- `additionalProperties: false` is optional on both sides for Phase 17 tools. Current pipeline does not set it; do not add to preserve parity.

**Existing pipeline uses Anthropic format verbatim** (lines 603-640). `schemas_for("anthropic", names=AGENT_TOOL_ALLOWLIST)` must produce output byte-identical to the deleted `_AGENT_TOOLS` list for the two retrieve tools.

---

## ABC + asyncio + Pydantic V2 Frozen Interactions

### BaseTool is a plain Python ABC — NOT a Pydantic BaseModel [VERIFIED: runtime]

`class BaseTool(abc.ABC)` with ClassVar attributes and `@abstractmethod async def run(...)`.
`ToolResult` and `ToolContext` are separate Pydantic V2 frozen models in `utils/models.py`.
There is no ABC+Pydantic inheritance — the two systems are separate. No interplay issues.

### Confirmed working pattern [VERIFIED: runtime in project venv, pydantic 2.13.4]

```python
import abc
from typing import Any, ClassVar
from pydantic import BaseModel, ConfigDict

# BaseTool — plain ABC
class BaseTool(abc.ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    parameters_schema: ClassVar[dict[str, Any]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Only check concrete subclasses (abstract intermediates are exempt)
        if not getattr(cls, "__abstractmethods__", None):
            for attr in ("name", "description", "parameters_schema"):
                if not hasattr(cls, attr):
                    raise TypeError(f"{cls.__name__} must define ClassVar {attr!r}")

    @abc.abstractmethod
    async def run(self, args: dict[str, Any], ctx: "ToolContext") -> "ToolResult": ...

    def _build_error_result(self, exc: Exception) -> "ToolResult":
        return ToolResult(content=f"[{self.name}] error: {exc}", is_error=True)

# ToolContext — Pydantic frozen, arbitrary_types_allowed=True for retriever/llm
class ToolContext(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    req: Any           # GenerationRequest
    tf: dict[str, Any]  # tenant filter; carries RLS
    retriever: Any
    llm: Any

# ToolResult — Pydantic frozen
class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    content: str
    chunks: list[Any] = []   # list[RetrievedChunk] in practice
    metadata: dict[str, Any] = {}
    is_error: bool = False
```

### Landmine: ClassVar annotations on ABC are NOT enforced at class definition [VERIFIED: runtime]

Without `__init_subclass__` guard: `ClassVar` annotations are purely type-checker hints; a concrete
subclass that forgets to set `name` will instantiate without error and raise `AttributeError` at
runtime when `name` is accessed (e.g., inside `schemas_for`). The `__init_subclass__` guard above
prevents this at class definition time — fires when the class body is evaluated, not at instantiation.

**Planner must include `__init_subclass__` guard on BaseTool.**

### Landmine: `arbitrary_types_allowed=True` required for ToolContext [VERIFIED: runtime]

`ToolContext.retriever` and `ToolContext.llm` are `Any`-typed (not Pydantic models). Without
`ConfigDict(arbitrary_types_allowed=True)`, Pydantic V2 raises `PydanticUserError` when
constructing `ToolContext` with live `HybridRetrieverService` / `AnthropicLLMClient` instances.
`ToolCall` and `ToolPlan` in `utils/models.py` do NOT have this problem (no unregistered types).

### Landmine: `frozen=True` + `ValidationError` (not `AttributeError`) [VERIFIED: runtime]

Attempts to mutate a frozen Pydantic V2 model raise `pydantic.ValidationError`, not
`AttributeError` or `TypeError`. Tests asserting on mutation prevention should catch
`pydantic.ValidationError` specifically if they test this behavior.

### async abstractmethod — no issues [VERIFIED: runtime]

`@abc.abstractmethod async def run(...)` works cleanly. Python's `ABCMeta` does not care
whether the abstract method is `async` — it only checks that the name is overridden.
`isinstance(tool, BaseTool)` works correctly on concrete subclasses.

---

## Tool Registry Decorator Patterns from Popular Python Frameworks

### Pattern: decorator returns the class unchanged [VERIFIED: Context7 + runtime]

Flask (blueprints), Click (commands), pytest (fixtures/marks), FastAPI (router inclusion)
all use variants of "decorator as registration with class/function returned unchanged."
The idiomatic Python form:

```python
# registry.py
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, type[BaseTool]] = {}

    def register(self, cls: type[BaseTool]) -> type[BaseTool]:
        """Register a Tool class. Returns cls unchanged so @registry.register works."""
        if cls.name in self._tools:
            raise ValueError(f"Tool {cls.name!r} already registered")
        self._tools[cls.name] = cls
        return cls  # <-- critical: return cls so decorator syntax works

    def get(self, name: str) -> BaseTool:
        """Instantiate a fresh tool per call (stateless dispatch)."""
        try:
            return self._tools[name]()
        except KeyError:
            raise KeyError(f"No tool registered as {name!r}") from None

    def list(self) -> list[str]:
        return sorted(self._tools.keys())

    def schemas_for(self, provider: str, names: list[str] | None = None) -> list[dict[str, Any]]:
        ...  # see Section above

# Module-level singleton
_registry: ToolRegistry | None = None

def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
```

```python
# retrieve.py — decorator usage
from services.agent.tools.registry import get_tool_registry

@get_tool_registry().register
class RetrieveTool(BaseTool):
    name = "search_knowledge_base"
    ...
```

### Test isolation [VERIFIED: runtime]

Tests instantiate `ToolRegistry()` directly (fresh, empty). Prod uses `get_tool_registry()`
singleton. Mock target for executor tests:

```python
# In test:
stub_registry = ToolRegistry()
stub_registry.register(FakeTool)
monkeypatch.setattr("services.agent.executor.get_tool_registry", lambda: stub_registry)
```

This follows the Phase 13/15 consumer-path mock convention already established. Mock at
`services.agent.executor.get_tool_registry`, NOT at `services.agent.tools.registry.get_tool_registry`.

### Duplicate registration guard [ASSUMED]

Flask and Click silently overwrite on duplicate; pytest raises. For tool registries,
raising on duplicate is safer (prevents silent config errors). Include the guard:
`if cls.name in self._tools: raise ValueError(...)`.

---

## Phase 18 SSE Forward-Compat — Does ToolResult.metadata Cover tool.span Needs?

Phase 18 needs per `tool.span.start/end/error` events:

| Field | Source | In D-02? | Gap? |
|-------|--------|----------|------|
| `tool_name` | `ToolCall.name` (Executor has it) | via ToolCall | None |
| `tool_args` | `ToolCall.arguments` (Executor has it) | via ToolCall | None |
| `result.content` | `ToolResult.content` | YES | None |
| `is_error` | `ToolResult.is_error` | YES | None |
| `latency_ms` | NOT in ToolResult fields | metadata["latency_ms"] | Convention only |
| `placeholder` | `metadata["placeholder"]` | via metadata | None |
| `query` (for retrieve tools) | `metadata["query"]` | via metadata | None |

**One gap: `latency_ms` is a metadata convention, not a typed field.** [VERIFIED: runtime]

Phase 18 will read `result.metadata.get("latency_ms")`. If a tool forgets to set it, Phase 18
gets `None` (using `.get()`) or `KeyError` (using `[]`). Mitigation:

1. `RetrieveTool._retrieve_impl` MUST populate `metadata["latency_ms"]` (document in ToolResult docstring).
2. `WebSearchTool` placeholder MUST set `metadata["latency_ms"] = 0`.
3. `BaseTool._build_error_result` MUST set `metadata["latency_ms"] = 0`.

**No structural change to D-02 fields is needed.** `metadata: dict[str, Any]` is the correct
extension point. D-02 is Phase 18 compatible as-is, subject to the convention documentation.

**Recommended metadata contract to document in `ToolResult` docstring:**

```
metadata keys (convention, not enforced):
  latency_ms: int       — wall-clock ms for the tool run (0 for errors/placeholders)
  query: str            — effective query string (RetrieveTool family)
  placeholder: bool     — True for skeletal/stub tools (WebSearchTool v1.4)
  chunk_count: int      — number of chunks returned (RetrieveTool family)
  provider: str         — tool-specific provider tag (future web search tools)
```

---

## WebSearchTool Placeholder Reference Shape

### What a well-formed placeholder looks like [VERIFIED: runtime + codebase patterns]

From D-10: `WebSearchTool.run()` returns a canned `ToolResult`. Pattern from the project's own
Phase 15 coverage stubs and standard "not-yet-implemented" conventions:

```python
# services/agent/tools/web_search.py
from __future__ import annotations
from typing import Any, ClassVar
import time
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from utils.models import ToolResult

@get_tool_registry().register
class WebSearchTool(BaseTool):
    """Placeholder — real web search deferred to v1.5+."""

    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = (
        "Search the public web for current information. "
        "(Placeholder: v1.5+ implementation pending.)"
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Web search query"},
        },
        "required": ["query"],
    }

    async def run(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        t0 = time.perf_counter()
        return ToolResult(
            content="[WebSearchTool placeholder — v1.5+]",
            metadata={
                "placeholder": True,
                "args": args,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            },
        )
```

Key properties of this shape:
- `description` includes "(Placeholder: v1.5+ pending)" — recognizable to reviewers [ASSUMED: LangChain placeholder convention]
- `parameters_schema` is a real JSON Schema (not empty) — proves schema machinery works
- `run()` returns quickly with `metadata["placeholder"] = True` — safe, no network, no secrets
- `metadata["latency_ms"]` populated (Phase 18 forward-compat)
- Excluded from `AGENT_TOOL_ALLOWLIST` so the LLM never sees it

---

## Recommendations on 3 Open Shape Decisions

### Decision 1: WebSearchTool exclusion mechanism

**Options:** `enabled_in_agent: ClassVar[bool] = False` flag vs explicit `AGENT_TOOL_ALLOWLIST` constant.

**Recommendation: explicit module-level `AGENT_TOOL_ALLOWLIST` constant.** [VERIFIED: runtime analysis]

Rationale:
- `AGENT_TOOL_ALLOWLIST = ["search_knowledge_base", "refine_search"]` in `services/pipeline.py` is
  already mentioned in D-06 as the mechanism. The constant IS the filtering — `schemas_for` receives
  `names=AGENT_TOOL_ALLOWLIST`, which performs list-membership filtering on tool names.
- A `ClassVar[bool]` flag on each tool would require `schemas_for` to inspect the flag AND be aware
  of the "agent" context — mixing registry concerns with pipeline concerns.
- For Phase 18 SSE filtering: the SSE emitter needs the same allowlist (it should emit `tool.span`
  events only for tools the agent actually called). The constant is importable; a class flag requires
  registry inspection.
- Testability: `schemas_for("anthropic", names=["search_knowledge_base"])` is a pure list-membership
  call that can be asserted on without any tool class inspection.
- The class-flag approach is better for large frameworks (LangChain, AutoGPT) where tools are
  third-party and cannot be modified. For a static internal registry with 3 tools, the explicit
  allowlist is cleaner.

**Concrete form:**

```python
# services/pipeline.py (module level, near AGENT_TOOL_ALLOWLIST)
AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search"]
```

WebSearchTool is registered (so `registry.list()` shows it, tests can call it) but simply absent
from `AGENT_TOOL_ALLOWLIST` — no per-tool flag needed.

---

### Decision 2: Provider-name detection on BaseLLMClient

**Options:** `type(self._llm).__name__`-based mapping dict vs `provider_name: ClassVar[str]` attribute.

**Recommendation: `provider_name: ClassVar[str]` on `BaseLLMClient`.** [VERIFIED: runtime analysis]

Rationale:
- The class-name mapping (`{"AnthropicLLMClient": "anthropic", "OpenAILLMClient": "openai", ...}`)
  is fragile: silently falls back to `"anthropic"` for any new provider (e.g., `GeminiLLMClient`)
  until the dict is updated. Silent mismatch = wrong tool-schema format sent to provider.
- Adding `provider_name: ClassVar[str] = "anthropic"` to `BaseLLMClient` is additive — no existing
  behavior changes, no existing tests break.
- Each existing subclass declares its own: `AnthropicLLMClient.provider_name = "anthropic"`,
  `OpenAILLMClient.provider_name = "openai"`, `OllamaLLMClient.provider_name = "openai"` (Ollama
  uses OpenAI-compatible format). Self-documenting at the provider definition site.
- Phase 11 abstraction stability: `call_agentic_turn` is unchanged. Adding a `ClassVar` attribute
  is additive and does not alter the method contract.
- Callsite in `AgentQueryPipeline.run`: `registry.schemas_for(self._llm.provider_name, names=AGENT_TOOL_ALLOWLIST)`.
  One clean attribute read, no dict lookup, no error cases.

**Concrete change to `BaseLLMClient`:**

```python
class BaseLLMClient(ABC):
    provider_name: ClassVar[str] = "anthropic"  # default; subclasses override
    ...

class AnthropicLLMClient(BaseLLMClient):
    provider_name: ClassVar[str] = "anthropic"

class OpenAILLMClient(BaseLLMClient):
    provider_name: ClassVar[str] = "openai"

class OllamaLLMClient(BaseLLMClient):
    provider_name: ClassVar[str] = "openai"  # Ollama uses OpenAI-compatible format
```

---

### Decision 3: `services/agent/tools/__init__.py` import side-effect strategy

**Options:** (A) explicit named imports, (B) `__all__` autodiscovery, (C) lazy at first-use.

**Recommendation: explicit named imports (Option A).** [VERIFIED: pattern analysis + runtime]

Rationale:
- Click (`app.register_blueprint`), Flask (`from . import views`), pytest (`conftest.py` imports)
  all use explicit imports to trigger registration side effects. This is the idiomatic Python pattern.
- `__all__` is for documenting public API surface, not for triggering side effects. Option B provides
  no mechanism to trigger `@registry.register` at module load time.
- Lazy registration (Option C) means tools are NOT registered until their module is first imported.
  If `services.agent.tools.retrieve` is never imported (e.g., in a test that imports `Executor`
  directly), `registry.get("search_knowledge_base")` raises `KeyError`. Non-obvious failure.
- With explicit imports in `__init__.py`, importing `services.agent.tools` (which happens when
  `services.agent.__init__` re-exports from it) guarantees all tools are registered.

**Concrete form:**

```python
# services/agent/tools/__init__.py
"""Tool registry and built-in tools for the agent runtime."""

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry, get_tool_registry

# Import tool modules to trigger @registry.register side effects at package load time
from services.agent.tools import retrieve as _retrieve_mod  # noqa: F401
from services.agent.tools import web_search as _web_search_mod  # noqa: F401

# Re-export concrete classes for type annotations and docs
from services.agent.tools.retrieve import RetrieveTool, RefinedRetrieveTool
from services.agent.tools.web_search import WebSearchTool

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "get_tool_registry",
    "RetrieveTool",
    "RefinedRetrieveTool",
    "WebSearchTool",
]
```

The `# noqa: F401` comments suppress ruff "imported but unused" warnings for the side-effect imports.
The explicit module-level aliases (`_retrieve_mod`, `_web_search_mod`) make the intent clear to readers
while keeping ruff clean. Alternatively, import the classes directly (they trigger module execution too):

```python
from services.agent.tools.retrieve import RetrieveTool, RefinedRetrieveTool, retrieve_impl
from services.agent.tools.web_search import WebSearchTool
```

This is simpler and achieves the same side-effect guarantee.

---

## Swarm Compatibility After tool_executor.py Deletion

D-04 deletes `tool_executor.py`. D-11 says SwarmQueryPipeline keeps direct retrieve calls.
After deletion, `SwarmQueryPipeline` cannot `from services.agent.tool_executor import execute_tool_call`.

**Recommended resolution:** Expose `_retrieve_impl` as a public `retrieve_impl` function in
`services/agent/tools/retrieve.py`. [VERIFIED: runtime analysis]

```python
# services/agent/tools/retrieve.py (exported public helper)
async def retrieve_impl(
    tc: ToolCall,
    tf: dict[str, Any],
    req: GenerationRequest,
    retriever: Any,
    llm: Any,
) -> tuple[list[RetrievedChunk], str]:
    """Shared retrieval helper — used by RetrieveTool, RefinedRetrieveTool, and SwarmQueryPipeline."""
    ...  # verbatim body from tool_executor.execute_tool_call
```

SwarmQueryPipeline changes one import line:
```python
# Before (deleted):
from services.agent.tool_executor import execute_tool_call
# After:
from services.agent.tools.retrieve import retrieve_impl as execute_tool_call
```

This:
- Honors D-04 (tool_executor.py deleted)
- Preserves D-11 (Swarm unchanged in behavior)
- Uses a public function (no cross-module private `_` imports)
- Keeps `services/agent/__init__.py` able to re-export `retrieve_impl` if needed

---

## Common Pitfalls

### Pitfall 1: `get_tool_registry().register` at module scope before singleton exists

**What goes wrong:** If `registry.py` defines `get_tool_registry()` with a lazy `_registry` global,
and `retrieve.py` calls `@get_tool_registry().register` at module scope, the singleton is created
the first time `retrieve.py` is imported. If tests import `ToolRegistry()` directly AND also import
`retrieve.py`, the test's fresh `ToolRegistry` does NOT contain `RetrieveTool` — only the singleton does.

**How to avoid:** Tests that test tool dispatch use the singleton (via `get_tool_registry()`) or
explicitly register test tools on a fresh `ToolRegistry()`. Never mix the two in a single test.
The established mock pattern: `monkeypatch.setattr("services.agent.executor.get_tool_registry", lambda: stub_registry)`.

**Warning signs:** `KeyError: 'search_knowledge_base'` in executor tests after Phase 17 lands.

### Pitfall 2: ClassVar annotations not enforced without `__init_subclass__`

**What goes wrong:** A future tool author forgets to set `name`; Python does not raise until
`registry.get(name).run(...)` is called and `t.name` is read — raising `AttributeError` at
dispatch time, not at class definition time.

**How to avoid:** Include `__init_subclass__` guard in `BaseTool` (see pattern above). This fires
at class body evaluation, giving an immediate `TypeError` with a clear message.

### Pitfall 3: `ToolContext(frozen=True)` without `arbitrary_types_allowed=True`

**What goes wrong:** Pydantic V2 raises `PydanticUserError: A non-annotated attribute was detected`
or `PydanticSchemaGenerationError` when `retriever` (a `HybridRetrieverService` instance, not a
Pydantic model) is assigned to a `frozen=True` model without `arbitrary_types_allowed=True`.

**How to avoid:** `ConfigDict(frozen=True, arbitrary_types_allowed=True)` on `ToolContext`.
Confirmed working in pydantic 2.13.4 (project venv). [VERIFIED: runtime]

### Pitfall 4: Swarm still importing `execute_tool_call` from deleted `tool_executor.py`

**What goes wrong:** `tool_executor.py` is deleted in D-04; `SwarmQueryPipeline` still imports
`execute_tool_call` from it. Import fails at startup; entire pipeline module crashes.

**How to avoid:** Phase 17 plan must include an explicit task to update `SwarmQueryPipeline`'s
import to `from services.agent.tools.retrieve import retrieve_impl as execute_tool_call` (see
Swarm Compatibility section). This is a 1-line change but easy to miss if the Swarm task is
not in the plan.

### Pitfall 5: `schemas_for` output not byte-identical to deleted `_AGENT_TOOLS` for the two retrieve tools

**What goes wrong:** The planner LLM sees different tool descriptions or property names; parity
tests fail or, worse, the LLM produces subtly different plans.

**How to avoid:** The `name`/`description`/`input_schema` content in `RetrieveTool.parameters_schema`
and `RefinedRetrieveTool.parameters_schema` must be character-identical to the deleted `_AGENT_TOOLS`
list (pipeline.py lines 603-640). Include a test that asserts
`registry.schemas_for("anthropic", names=AGENT_TOOL_ALLOWLIST) == [expected_search, expected_refine]`
with the exact strings from the old literal.

### Pitfall 6: mypy strict on `ClassVar[dict[str, Any]]` in ABC subclasses

**What goes wrong:** mypy `--strict` may warn about `ClassVar` assignments in subclasses
(`parameters_schema = {"type": "object", ...}` without explicit `ClassVar` annotation on the subclass).

**How to avoid:** In concrete subclasses, annotate explicitly:
```python
class RetrieveTool(BaseTool):
    name: ClassVar[str] = "search_knowledge_base"
    description: ClassVar[str] = "..."
    parameters_schema: ClassVar[dict[str, Any]] = {...}
```
Do not omit the `ClassVar[str]` annotation even though `BaseTool` already declares it — mypy strict
requires explicit annotation on the overriding class attribute.

---

## Code Examples

### BaseTool ABC with ClassVar guard and shared _build_error_result
```python
# Source: runtime-verified pattern (this research session)
import abc
from typing import Any, ClassVar
from utils.models import ToolResult, ToolContext  # noqa: TC001

class BaseTool(abc.ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    parameters_schema: ClassVar[dict[str, Any]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "__abstractmethods__", None):
            for attr in ("name", "description", "parameters_schema"):
                if not hasattr(cls, attr):
                    raise TypeError(f"{cls.__name__} must define ClassVar {attr!r}")

    @abc.abstractmethod
    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...

    def _build_error_result(self, exc: Exception, latency_ms: int = 0) -> ToolResult:
        return ToolResult(
            content=f"[{self.name}] error: {exc}",
            is_error=True,
            metadata={"latency_ms": latency_ms},
        )
```

### ToolRegistry with provider-shape mapping
```python
# Source: runtime-verified pattern (this research session)
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, type[BaseTool]] = {}

    def register(self, cls: type[BaseTool]) -> type[BaseTool]:
        if cls.name in self._tools:
            raise ValueError(f"Tool {cls.name!r} already registered")
        self._tools[cls.name] = cls
        return cls

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]()
        except KeyError:
            raise KeyError(f"No tool registered as {name!r}") from None

    def list(self) -> list[str]:
        return sorted(self._tools.keys())

    def schemas_for(self, provider: str, names: list[str] | None = None) -> list[dict[str, Any]]:
        tools = [t for t in self._tools.values() if names is None or t.name in names]
        if provider == "anthropic":
            return [
                {"name": t.name, "description": t.description, "input_schema": t.parameters_schema}
                for t in tools
            ]
        if provider in ("openai", "ollama"):
            return [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters_schema}}
                for t in tools
            ]
        raise ValueError(f"Unknown provider: {provider!r}")


_registry: ToolRegistry | None = None

def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
```

### Executor._dispatch_one after Phase 17 seam swap
```python
# Source: executor.py line 88 today; replace with:
async def _dispatch_one(
    self,
    tc: ToolCall,
    tf: dict[str, Any],
    req: GenerationRequest,
) -> ToolResult:
    ctx = ToolContext(req=req, tf=tf, retriever=self._retriever, llm=self._llm)
    return await get_tool_registry().get(tc.name).run(args=tc.arguments or {}, ctx=ctx)
```

Note: return type changes from `tuple[list[RetrievedChunk], str]` to `ToolResult`.
`execute_plan` and the orchestrator in `AgentQueryPipeline.run` must be updated to consume
`ToolResult` instead of the tuple. This is the primary callsite change in Phase 17.

### AgentQueryPipeline tool-schema injection point
```python
# Replace: tools=self._AGENT_TOOLS
# With:
tools=get_tool_registry().schemas_for(
    self._llm.provider_name,
    names=AGENT_TOOL_ALLOWLIST,
)
```

---

## Nyquist Validation Strategy for AGENT-07 Acceptance

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio |
| Config | `pytest.ini` (`asyncio_mode = auto`) |
| Quick run | `pytest tests/unit/test_tool_registry.py tests/unit/test_retrieve_tool.py -x -q` |
| Full suite | `pytest tests/unit/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Command | File |
|--------|----------|-----------|---------|------|
| AGENT-07 SC1 | BaseTool ABC has name/description/parameters_schema ClassVars + async run | unit | `pytest tests/unit/test_tool_registry.py::test_base_tool_abstract -x` | Wave 0 gap |
| AGENT-07 SC1 | Concrete subclass missing ClassVar raises TypeError at definition | unit | `pytest tests/unit/test_tool_registry.py::test_classvar_guard -x` | Wave 0 gap |
| AGENT-07 SC2 | RetrieveTool.run produces ToolResult; parity with old execute_tool_call | unit | `pytest tests/unit/test_retrieve_tool.py -x` | Wave 0 gap |
| AGENT-07 SC3 | WebSearchTool registered and returns placeholder ToolResult | unit | `pytest tests/unit/test_tool_registry.py::test_web_search_placeholder -x` | Wave 0 gap |
| AGENT-07 SC4 | Executor._dispatch_one calls registry.get(name).run() (no direct imports) | unit | `pytest tests/unit/test_executor.py -x` (UPDATE mock target) | Update existing |
| AGENT-07 SC4 | No direct tool imports in pipeline.py or executor.py | static | `grep -n "from services.agent.tools.retrieve import\|import RetrieveTool" services/pipeline.py services/agent/executor.py` → 0 matches | CI check |
| AGENT-07 SC5 | docs/agent-architecture.md#authoring-tools exists | smoke | `python3 -c "import pathlib; assert pathlib.Path('docs/agent-architecture.md').exists()"` | Wave 0 gap |
| Parity | schemas_for("anthropic", names=AGENT_TOOL_ALLOWLIST) == old _AGENT_TOOLS | unit | `pytest tests/unit/test_tool_registry.py::test_schemas_parity -x` | Wave 0 gap |
| Parity | 19 existing v1.3 unit tests still pass | regression | `pytest tests/unit/test_agent_pipeline_refactor.py tests/unit/test_agent_parity.py -x` | Existing |

### Wave 0 Gaps (new test files required before implementation)
- [ ] `tests/unit/test_tool_registry.py` — covers: BaseTool ABC enforcement, ToolRegistry register/get/list/schemas_for, provider mapping, duplicate registration guard, test isolation, schemas parity
- [ ] `tests/unit/test_retrieve_tool.py` — covers: RetrieveTool + RefinedRetrieveTool semantics; ToolResult shape assertions; WebSearchTool placeholder

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_tool_registry.py tests/unit/test_retrieve_tool.py -x -q`
- **Per wave merge:** `pytest tests/unit/ -q`
- **Phase gate:** Full unit suite green (currently 656 passed) + `grep` negative assertion on tool imports in pipeline.py/executor.py

---

## Environment Availability

Step 2.6: SKIPPED — Phase 17 is a pure code refactor. No external services, CLI tools, or databases
beyond the project's own venv (pydantic 2.13.4 confirmed present) are needed.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | LangChain placeholder convention: description includes "(Placeholder: ...)" | WebSearchTool Placeholder | Cosmetic only — reviewers may prefer different wording |
| A2 | Flask/Click/pytest decorator-returns-class is the idiomatic pattern for "register and return unchanged" | Tool Registry Decorator Patterns | Low — widely used; alternative is decorator returns wrapper, which would break `@registry.register class Foo` syntax |
| A3 | `OllamaLLMClient.provider_name = "openai"` (uses OpenAI-compatible format) | Open Shape Decision 2 | Medium — if Ollama adapter uses a different format, schemas_for("openai") schema breaks for Ollama. Verify in llm_client.py: OllamaLLMClient should already accept OpenAI-format tools in chat_with_tools(). |
| A4 | Duplicate registration guard (raise ValueError) is preferred over silent overwrite | ToolRegistry patterns | Low — raising is strictly safer; if tests accidentally register twice, the error is informative |
| A5 | `ClassVar[str]` on subclass is required for mypy --strict even when parent ABC declares it | Pitfall 6 | Medium — mypy behavior may vary by version; verify with `mypy services/agent/tools/ --strict` after Wave 1 |

---

## Open Questions

1. **`ToolContext.req` type annotation — `Any` or `GenerationRequest`**
   - What we know: `ToolContext` is in `utils/models.py`; `GenerationRequest` is also in `utils/models.py` (no circular import)
   - What's unclear: Whether `from __future__ import annotations` + direct import covers the type
   - Recommendation: Use `GenerationRequest` directly (same module). `Any` is unnecessary here — use concrete type for mypy --strict compliance.

2. **`Executor.execute_plan` return type after Phase 17**
   - What we know: Currently returns `list[tuple[list[RetrievedChunk], str] | BaseException]`. After Phase 17, `_dispatch_one` returns `ToolResult`.
   - What's unclear: Does `AgentQueryPipeline._build_tool_results` consume the old tuple or ToolResult? (Read `services/pipeline.py` around line 794-824 during planning.)
   - Recommendation: Change `execute_plan` return to `list[ToolResult | BaseException]`. Update `_build_tool_results` in the orchestrator to consume `ToolResult.content` and `ToolResult.chunks` instead of the tuple. This is a Wave 2/3 task.

---

## Sources

### Primary (HIGH confidence)
- Context7 `/anthropics/anthropic-sdk-python` — Anthropic tool use wire format, `input_schema` key, `additionalProperties` in `@beta_tool` output
  - Source URL: https://github.com/anthropics/anthropic-sdk-python/blob/main/tools.md
- Context7 `/openai/openai-python` — OpenAI function tool wire format (`type: "function"`, `function.parameters`), `strict` mode, `pydantic_function_tool`
  - Source URL: https://github.com/openai/openai-python/blob/main/src/openai/lib/_tools.py
- Context7 `/pydantic/pydantic` — `ClassVar` in BaseModel, ABC inheritance, `frozen=True`, `ConfigDict`
  - Source URL: https://github.com/pydantic/pydantic/blob/main/docs/concepts/models.md
- Runtime verification in project venv (pydantic 2.13.4): ToolContext/ToolResult frozen models, BaseTool ABC patterns, ToolRegistry decorator

### Secondary (MEDIUM confidence)
- `services/agent/executor.py` — current `_dispatch_one` call site (lines 88-94)
- `services/agent/tool_executor.py` — body to migrate verbatim into `retrieve_impl`
- `services/pipeline.py` lines 602-640 — `_AGENT_TOOLS` literal (parity target)
- `.planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md` — established patterns (consumer-path mock, thin orchestrator)

### Tertiary (LOW confidence — ASSUMED)
- A1: LangChain placeholder convention (description wording)
- A3: OllamaLLMClient uses OpenAI-compatible format

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all verified in project venv
- Architecture patterns: HIGH — verified via runtime + official docs
- Pitfalls: HIGH — most verified at runtime; A3 (Ollama format) is MEDIUM
- Phase 18 forward-compat: HIGH — gap identified and mitigation documented

**Research date:** 2026-05-09
**Valid until:** 2026-06-09 (stable — Pydantic V2/Python ABC patterns do not change rapidly)
