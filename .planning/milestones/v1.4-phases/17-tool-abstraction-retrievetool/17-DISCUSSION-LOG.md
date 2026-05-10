# Phase 17: Tool Abstraction + RetrieveTool - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-09
**Phase:** 17-tool-abstraction-retrievetool
**Areas discussed:** Tool abstraction shape + result type, RetrieveTool boundary + _AGENT_TOOLS migration, Registry surface + provider-schema generation, Skeletal placeholder tool + SwarmQueryPipeline scope

---

## Tool abstraction shape + result type (GA1)

### GA1-A — Abstraction primitive

| Option | Description | Selected |
|--------|-------------|----------|
| typing.Protocol (structural, no inheritance) | Zero inheritance burden. MCP-style 3rd-party tools just need to match shape. mypy-checked. No isinstance() unless `@runtime_checkable`. | |
| ABC (BaseTool with shared utilities) | `class BaseTool(ABC)` with `@abstractmethod async def run(...)`. Allows shared helpers (`_log_span`, `_build_error_result`). Runtime `isinstance` works. | ✓ |
| @runtime_checkable Protocol (hybrid) | Structural typing + runtime checks. Slight cost on isinstance speed; only checks attribute presence. | |

**User's choice:** ABC (BaseTool with shared utilities) — recommended option.
**Notes:** Anticipates ≥3 tools sharing boilerplate (logging, retry, schema-from-pydantic conversion).

### GA1-B — Tool result shape

| Option | Description | Selected |
|--------|-------------|----------|
| ToolResult Pydantic V2 frozen model | Uniform shape: `content` / `chunks` / `metadata` / `is_error`. Matches Phase 16 ToolPlan/ToolCall style. | ✓ |
| Keep `tuple[list[RetrievedChunk], str]` | Zero migration cost. Awkward for non-RAG tools. No place for tool-specific metadata. | |
| TypedDict (lighter than Pydantic) | Less validation overhead. Breaks Phase 16 D-01 Pydantic V2 frozen consistency. | |

**User's choice:** ToolResult Pydantic V2 frozen model — recommended option.
**Notes:** Provides uniform shape across RAG and non-RAG tools; metadata field surfaces to Phase 18 SSE event.

---

## RetrieveTool boundary + _AGENT_TOOLS migration (GA2)

### GA2-A — Wrap target

| Option | Description | Selected |
|--------|-------------|----------|
| Wrap execute_tool_call body verbatim | Body of `services/agent/tool_executor.py:execute_tool_call` adapted to BaseTool signature. tool_executor.py DELETED after migration. Zero behavior change. | ✓ |
| Wrap QueryPipeline.run() literally (per ROADMAP wording) | QueryPipeline.run does retrieve + LLM generation + audit + persist; doubles LLM cost; conflicts with planner outer loop. | |
| Wrap HybridRetrieverService.retrieve directly | Loses XML `<search_results><document>` formatting v1.3 prompts depend on. Net same as option 1 but loses reuse signal. | |

**User's choice:** Wrap execute_tool_call body verbatim — recommended option.
**Notes:** ROADMAP "wrap QueryPipeline.run()" wording is loose; the actually-correct wrap target is the existing helper.

### GA2-B — Tool name strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Keep two names: RetrieveTool + RefinedRetrieveTool | Two registered Tool classes; both share private `_retrieve_impl`. Preserves v1.2/v1.3 planner prompt verbatim — zero parity risk. | ✓ |
| Collapse to single RetrieveTool with optional source_filter | Cleaner architecturally. Changes prompt surface; risks parity break on 19 v1.3 tests + 2 fixtures. | |
| Keep two names but unified internally via helper | Tightened version of option 1 — same behavior. | |

**User's choice:** Keep two names — recommended option.
**Notes:** Collapsing deferred to v1.5+ if/when prompt-surface review happens.

---

## Registry surface + provider-schema generation (GA3)

### GA3-A — Registry shape

| Option | Description | Selected |
|--------|-------------|----------|
| ToolRegistry class with explicit register/get/schemas_for | Singleton via `get_tool_registry()` matches Phase 16 pattern. Test isolation: tests instantiate fresh; prod uses singleton. MCP later: subclass or replace singleton. | ✓ |
| Module-level dict + @register_tool decorator | Idiomatic Python. Less ceremony. Harder to isolate in tests; conflicts with Phase 13/15 mock-at-consumer-path pattern. | |
| Class with class-level dict + @classmethod decorators | Hybrid. Looks like a class but state is global. Worst of both. | |

**User's choice:** ToolRegistry class — recommended option.
**Notes:** Decorator usage preserved (`registry.register` returns class for `@registry.register` syntax).

### GA3-B — Provider-schema mapping location

| Option | Description | Selected |
|--------|-------------|----------|
| Registry-level adapter via schemas_for(provider) | Tools declare ONE neutral parameters_schema; registry maps to provider shapes. Tools stay provider-agnostic. | ✓ |
| Tool-level: each Tool declares both anthropic_schema + openai_schema | Verbose; boilerplate compounds at 5+ tools. | |
| Provider mapping in BaseLLMClient adapter | Pushes into Phase 11 abstraction; rejected by carry-forward. | |

**User's choice:** Registry-level adapter — recommended option.

---

## Skeletal placeholder tool + SwarmQueryPipeline scope (GA4)

### GA4-A — Placeholder tool choice

| Option | Description | Selected |
|--------|-------------|----------|
| WebSearchTool placeholder | Network-I/O-shaped tool with timeout/retry pattern in design. Aligns with v1.5+ roadmap (10x #3 MCP web tools). Easier to test (no DB dependency). | ✓ |
| SQLTool placeholder | Fits enterprise-grade story but non-trivial to design as placeholder (schema, allowed tables, injection guards). Risks scope creep. | |
| EchoTool (trivial test placeholder) | Cheapest registry test. Doesn't signal v1.5+ direction; reads as throwaway in PR review. | |

**User's choice:** WebSearchTool placeholder — recommended option.
**Notes:** Returns canned `ToolResult(content="[WebSearchTool placeholder — v1.5+]", metadata={"placeholder": True, ...})`. Excluded from `AgentQueryPipeline.AGENT_TOOL_ALLOWLIST` so planner LLM doesn't see it (preserves Phase 16 parity).

### GA4-B — SwarmQueryPipeline scope

| Option | Description | Selected |
|--------|-------------|----------|
| Scope-reduce: Agent-only in Phase 17 | Honors ROADMAP SC4 literal wording. Swarm migration becomes v1.5+ follow-up after AGENT-05. Smaller PR; no parity risk on 8 swarm tests. | ✓ |
| Wire SwarmQueryPipeline through registry too | Eliminates duplication. Phase 17 becomes 30%+ larger. | |
| Hybrid: Swarm imports registry but bypasses dispatch | Half-measure; worst of both. | |

**User's choice:** Scope-reduce to Agent-only — recommended option.
**Notes:** Swarm keeps own `_SWARM_TOOLS` literal + direct retrieve calls. After `tool_executor.py` deletion (D-04), SwarmQueryPipeline switches import to `services/agent/tools/retrieve.py` shared helper OR retains a thin shim — Phase 17 plan decides exact mechanism.

---

## Claude's Discretion

- **Module layout:** `services/agent/tools/` package with `base.py` (BaseTool ABC), `registry.py` (ToolRegistry), `retrieve.py` (RetrieveTool + RefinedRetrieveTool + `_retrieve_impl`), `web_search.py` (WebSearchTool placeholder). `services/agent/tool_executor.py` DELETED.
- **`docs/agent-architecture.md#authoring-tools` stub:** minimum content covers (1) subclass BaseTool, (2) `@registry.register` decorator, (3) parameters_schema as JSON Schema dict, (4) one runnable RetrieveTool-style example. Historical intent mapping table deferred to Phase 19.
- **`retrieve_multi_query` not exposed:** Existing helper at `services/retriever/retriever.py:549` not registered as a Phase 17 tool. Deferred as `MultiQueryRetrieveTool` to v1.5+.
- **WebSearchTool exclusion mechanism:** Class-level `enabled_in_agent: ClassVar[bool] = False` flag vs explicit module-level allowlist constant — Phase 17 plan picks one.
- **Provider-name selection on `BaseLLMClient`:** `type(self._llm).__name__`-based mapping vs adding a `provider_name: ClassVar[str]` attribute on `BaseLLMClient`. Phase 17 plan picks one.

## Deferred Ideas

- Collapse `search_knowledge_base` + `refine_search` into single RetrieveTool — v1.5+.
- `MultiQueryRetrieveTool` wrapping `retrieve_multi_query` — v1.5+.
- SwarmQueryPipeline registry migration — v1.5+ after AGENT-05.
- Real `WebSearchTool` implementation with retry/timeout/cost guards — v1.5+.
- `SQLTool` for RLS-shaped structured query — v1.5+.
- MCP plug-in discovery replacing static registry — 10x roadmap #3.
- Per-tool retry / circuit-breaker policy — defer until ≥3 real tools.
- Tool lifecycle hooks (`before_run` / `after_run`) — defer until Phase 18 proves need.
- Tool authoring guide expansion (tutorial with asciinema) — Phase 19.
- Historical intent mapping table (Query/Agent/Swarm → ToolPlan shape) — Phase 19 per Phase 16 D-13.
