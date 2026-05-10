# Phase 17: Tool Abstraction + RetrieveTool - Context

**Gathered:** 2026-05-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Define a provider-neutral `BaseTool` ABC; replace `AgentQueryPipeline._AGENT_TOOLS` literal with a static `ToolRegistry`; wrap retrieval as `RetrieveTool` + `RefinedRetrieveTool` (preserves v1.3 planner prompt names); register `WebSearchTool` placeholder to prove pluggability; route `Executor` dispatch through registry; stub `docs/agent-architecture.md#authoring-tools`. SwarmQueryPipeline scope-reduced to v1.5+. v1.3 retrieval behavior preserved on existing test fixtures.

</domain>

<decisions>
## Implementation Decisions

### Tool abstraction shape + result type

- **D-01:** `BaseTool` is an `ABC` (not Protocol). Lives at `services/agent/tools/base.py`. Three required `ClassVar` attributes: `name: str`, `description: str`, `parameters_schema: dict[str, Any]` (provider-neutral JSON Schema). One `@abstractmethod async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult`. Shared utilities (e.g., `_log_span`) live on the ABC to avoid duplication across ≥3 future tools. Phase 16 D-01 Pydantic style applies to ToolResult / ToolContext models.

- **D-02:** `ToolResult` is a Pydantic V2 frozen model in `utils/models.py` (matches `ToolCall` / `ToolPlan` placement). Fields: `content: str` (LLM-facing text), `chunks: list[RetrievedChunk] = []` (RAG-only, empty for non-RAG tools), `metadata: dict[str, Any] = {}` (free-form: URLs, query, latency, placeholder flag), `is_error: bool = False`. Orchestrator builds tool_results from `.content`; `chunks` consumed only on the RetrieveTool path; `metadata` surfaces to Phase 18 `tool.span` SSE event.

- **D-03:** `ToolContext` is a Pydantic V2 frozen model carrying `req: GenerationRequest`, `tf: dict[str, Any]` (tenant filter, RLS-bearing), `retriever: Any`, `llm: Any`. Mirrors the v1.3 `execute_tool_call(tc, tf, req, retriever, llm)` positional signature. Construction site: `Executor` builds ToolContext per dispatch. RLS guarantee preserved by carrying `tf` through unchanged.

### RetrieveTool boundary + _AGENT_TOOLS migration

- **D-04:** `RetrieveTool.run()` body is the verbatim `services/agent/tool_executor.py:execute_tool_call` body adapted to `BaseTool` signature. Hybrid retrieval + RRF + rerank stays inside `HybridRetrieverService.retrieve` (untouched). After Phase 17 lands, `services/agent/tool_executor.py` is DELETED — RetrieveTool subsumes it. Zero behavior change vs Phase 16 close.

- **D-05:** Two registered tool classes: `RetrieveTool` (name=`search_knowledge_base`) + `RefinedRetrieveTool` (name=`refine_search`). Both share a private `_retrieve_impl(query, top_k, filters, retriever, llm)` helper in the same module. Preserves v1.2/v1.3 planner prompt verbatim — zero parity risk against the 19 existing v1.3 unit tests + 2 parity fixtures from Phase 16. Collapsing to a single tool was rejected; deferred to v1.5+ if/when prompt-surface review happens.

- **D-06:** `_AGENT_TOOLS` literal at `services/pipeline.py:602-641` is DELETED. AgentQueryPipeline calls `get_tool_registry().schemas_for(provider, names=AGENT_TOOL_ALLOWLIST)` where `AGENT_TOOL_ALLOWLIST = ["search_knowledge_base", "refine_search"]` is a module-level constant. `_AGENT_SYSTEM` prompt at `services/pipeline.py:642-665` STAYS verbatim (D-13 carry-forward — planner prompt unchanged in Phase 17).

### Registry surface + provider-schema generation

- **D-07:** `ToolRegistry` is a class with explicit methods: `register(tool_cls) -> type[BaseTool]` (returns class so `@registry.register` works as decorator), `get(name: str) -> BaseTool` (instantiates fresh per call), `list() -> list[str]` (sorted names), `schemas_for(provider: str, names: list[str] | None = None) -> list[dict]`. Module-level singleton via `get_tool_registry()` matches Phase 16 `get_planner` / `get_executor` factory pattern. Test isolation: tests can instantiate `ToolRegistry()` directly; prod uses singleton.

- **D-08:** Each Tool declares ONE provider-neutral `parameters_schema: dict[str, Any]` (JSON Schema shape — same as Anthropic's `input_schema` body). `ToolRegistry.schemas_for(provider)` performs the provider-shape mapping: `anthropic` → `{name, description, input_schema}`; `openai` → `{type: "function", function: {name, description, parameters}}`. Tools stay provider-agnostic; mapping logic centralized in registry. Adding a new provider = adding one method-internal branch.

- **D-09:** `Executor._dispatch_one` now calls `registry.get(tc.name).run(args=tc.arguments, ctx=tool_ctx)` instead of `execute_tool_call(...)`. Imports of specific tools by name are FORBIDDEN in `services/pipeline.py` and `services/agent/executor.py` (ROADMAP SC4) — only `get_tool_registry` import. Tools register themselves via `@registry.register` decorator at module-import time inside `services/agent/tools/__init__.py`.

### Skeletal placeholder tool + SwarmQueryPipeline scope

- **D-10:** `WebSearchTool` (name=`web_search`) is registered but EXCLUDED from `AgentQueryPipeline.AGENT_TOOL_ALLOWLIST` — preserves Phase 16 parity (planner LLM still sees only `search_knowledge_base` + `refine_search` in `schemas_for`). `WebSearchTool.run()` returns canned `ToolResult(content="[WebSearchTool placeholder — v1.5+]", metadata={"placeholder": True, "args": args})`. Filter mechanism (class-level `enabled_in_agent: ClassVar[bool] = False` flag vs explicit module-level allowlist) is a Phase 17 plan-level decision; CONTEXT.md is shape-agnostic on this.

- **D-11:** SwarmQueryPipeline is OUT OF SCOPE for Phase 17. Honors ROADMAP SC4 literal wording ("Executor dispatches strictly through the registry"). Swarm keeps its own `_SWARM_TOOLS` literal and direct `execute_tool_call` calls verbatim from Phase 16 close. After `tool_executor.py` deletion in D-04, SwarmQueryPipeline imports must switch to `from services.agent.tools.retrieve import _retrieve_impl` OR retain a thin `execute_tool_call` shim. Resolved at Phase 17 plan time. Swarm registry migration is a v1.5+ follow-up after AGENT-05 (multi-agent debate).

### NLU-03 carry-forward (no new decision)

- **D-12:** No `IntentRouter` class in Phase 17 either (carry-forward from Phase 16 D-13). Intent semantics still live in `ToolPlan` shape. Phase 17 only changes how tools are REGISTERED + DISPATCHED, not how the planner decides which tool to invoke.

### Claude's Discretion

- **`docs/agent-architecture.md#authoring-tools` stub content:** minimum content = (1) "How to define a Tool" — subclass BaseTool, set 3 ClassVars, implement `async def run`; (2) "How to register" — `@registry.register` decorator at module top; (3) "parameters_schema shape" — JSON Schema dict; (4) one runnable RetrieveTool-style example. The historical intent mapping table (Query/Agent/Swarm → ToolPlan shape) is DEFERRED to Phase 19 per Phase 16 D-13 — not in Phase 17 stub.
- **`retrieve_multi_query`** (already exists at `services/retriever/retriever.py:549`) is NOT exposed as a tool in Phase 17. Deferred to v1.5+ as a separate `MultiQueryRetrieveTool`. Current planner prompt does not reference it; adding now would expand prompt surface and risk parity break.
- **Planner schema injection point:** `Planner.plan_from_messages` already accepts `tools=...` kwarg (Phase 16). Phase 17 wiring: `AgentQueryPipeline.run` calls `registry.schemas_for("anthropic", names=AGENT_TOOL_ALLOWLIST)` and passes the result via `tools=...`. Provider name selection (which provider string to pass) is read from the LLM client class — `type(self._llm).__name__`-style mapping is acceptable; cleaner alternative is a `BaseLLMClient.provider_name: ClassVar[str]` attribute. Phase 17 plan picks one.
- **Module layout:** `services/agent/tools/__init__.py` + `base.py` (BaseTool ABC) + `registry.py` (ToolRegistry) + `retrieve.py` (RetrieveTool + RefinedRetrieveTool + `_retrieve_impl`) + `web_search.py` (placeholder). `services/agent/executor.py` updated to use registry; `services/agent/tool_executor.py` DELETED.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source design and milestone artifacts

- `/home/ubuntu/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` — v1.4 milestone design doc; Open Questions #2 (static class registry, MCP later) and #5 (Sub-agent reuse — confirms registry should support SwarmTool composition pathway later) bear on Phase 17.
- `.planning/PROJECT.md` — v1.4 Open Q#2 recommendation: static registry with abstraction clean enough that MCP plug-in discovery (10x roadmap #3) replaces it later without callsite changes.
- `.planning/ROADMAP.md` Phase 17 success criteria — the 5 SCs are the acceptance contract.
- `.planning/REQUIREMENTS.md` AGENT-07 acceptance — Tool Protocol/ABC, RetrieveTool wrapping QueryPipeline.run, ≥1 placeholder, static registry, MCP-replaceable.

### Code anchors

- `services/agent/__init__.py` — public surface re-exports (`Planner`, `Executor`, `get_planner`, `get_executor`); add `ToolRegistry`, `get_tool_registry`, `BaseTool` after Phase 17.
- `services/agent/executor.py:60` (`_dispatch_one`) — current call site `await execute_tool_call(tc, tf, req, self._retriever, self._llm)`; replaced with `await registry.get(tc.name).run(args=tc.arguments or {}, ctx=ToolContext(req=req, tf=tf, retriever=self._retriever, llm=self._llm))`.
- `services/agent/tool_executor.py:24-72` — `execute_tool_call` body; relocates verbatim into `services/agent/tools/retrieve.py::_retrieve_impl` (then both RetrieveTool + RefinedRetrieveTool delegate). File DELETED after migration.
- `services/pipeline.py:602-641` — `_AGENT_TOOLS` literal (DELETE in Phase 17).
- `services/pipeline.py:642-665` — `_AGENT_SYSTEM` prompt (STAYS verbatim — planner prompt unchanged).
- `services/pipeline.py:794-822` — `AgentQueryPipeline.run` outer loop; `tools=self._AGENT_TOOLS` arg replaced with `tools=registry.schemas_for(provider, names=AGENT_TOOL_ALLOWLIST)`.
- `services/pipeline.py:853+` — `SwarmQueryPipeline._SWARM_TOOLS` literal + tool dispatch; OUT OF SCOPE for Phase 17 (D-11). Only edit: switch import after `tool_executor.py` deletion (D-11 follow-up).
- `services/retriever/retriever.py:410-548` — `HybridRetrieverService.retrieve` (the body that RetrieveTool wraps); UNTOUCHED.
- `services/retriever/retriever.py:549` — `retrieve_multi_query` (NOT exposed as tool in Phase 17; deferred to v1.5+).
- `utils/models.py` — `ToolCall` (existing), `ToolPlan` (Phase 16); ADD `ToolResult` + `ToolContext` here in Phase 17.
- `services/generator/llm_client.py` — `BaseLLMClient.call_agentic_turn` (provider-neutral, untouched); consider adding `provider_name: ClassVar[str]` attribute (Claude's discretion D-?).

### Codebase maps (read once for orientation)

- `.planning/phases/16-planner-executor-extraction/16-CONTEXT.md` — Phase 16 decisions D-01 through D-14; particularly D-01/02/03 (ToolPlan schema), D-04/05 (shared helper placement), D-13/14 (NLU-03, agent_mode/swarm_mode preserved).
- `.planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md` — Wave 3 close-out; lists exact line numbers and helper extraction patterns Phase 17 builds on.

### Milestones archive (precedent decisions)

- `.planning/milestones/v1.3-phases/12-fork-agent-swarm/` — original SwarmQueryPipeline phase; informs D-11 scope-reduce decision.
- `.planning/milestones/v1.2-phases/11-provider-agnostic-agentic-layer-parallel-tool-call-burst/` — `BaseLLMClient.call_agentic_turn` abstraction; informs D-08 provider-mapping location.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`utils/models.py::ToolCall`** — Phase 16 reuse pattern. ADD `ToolResult` and `ToolContext` to the same module; same `ConfigDict(frozen=True)` style.
- **`services/agent/tool_executor.py:execute_tool_call`** — body relocates verbatim into `services/agent/tools/retrieve.py::_retrieve_impl`. Args (tc, tf, req, retriever, llm) → keyword args extracted into ToolContext.
- **`services/agent/executor.py::Executor`** — `_dispatch_one` is the only call site needing surgery. ToolContext construction is a 1-line addition; the import switch is a 1-line change.
- **Singleton factory pattern** — `get_planner` / `get_executor` (Phase 16). Add `get_tool_registry` next to them; same lazy-init pattern.
- **Pydantic V2 frozen with ConfigDict** — `ToolPlan` (utils/models.py:291) is the precedent shape for ToolResult / ToolContext.

### Established Patterns

- **Mock at consumer path** (Phase 13/15). Phase 17 unit tests will `monkeypatch.setattr("services.agent.executor.get_tool_registry", lambda: stub_registry)` — NOT `services.agent.tools.registry`.
- **mypy --strict + ruff clean** — Phase 17 must match Phase 16 close (296 errors = baseline; 0 new). New modules in `services/agent/tools/` must be strict-clean from day one.
- **`BaseException` (not `Exception`)** for `asyncio.gather` — Executor unchanged. Tools that may raise `CancelledError`/`TimeoutError` (e.g., future WebSearch with real network) inherit isolation from Executor's gather.
- **XML doc-block formatting in `_retrieve_impl`** — `<search_results><document index=...>` shape is consumed by the planner LLM prompt; do NOT change format string.
- **Provider-neutral schema → provider mapping in adapter** — Phase 11 establishes that provider specifics live BELOW `BaseLLMClient`. Phase 17 D-08 places the schemas-mapping in `ToolRegistry.schemas_for` instead, NOT inside the LLM adapters — keeps the v1.2 abstraction stable.
- **Decorator-as-registration** — `@registry.register` style mirrors `pytest.fixture` and `click.command` idioms; well-known to Python reviewers.

### Integration Points

- **`AgentQueryPipeline.run`** (services/pipeline.py:782-824) — replaces `tools=self._AGENT_TOOLS` arg with `tools=registry.schemas_for(provider_name, names=AGENT_TOOL_ALLOWLIST)`. Touch is ≤ 5 lines.
- **`Executor._dispatch_one`** (services/agent/executor.py:60) — replaces direct `execute_tool_call(...)` call with `registry.get(tc.name).run(args, ctx)`. Touch is ≤ 5 lines.
- **`utils/models.py`** — adds `ToolResult` + `ToolContext`. No changes to existing models.
- **`services/agent/__init__.py`** — re-exports `BaseTool`, `ToolRegistry`, `get_tool_registry`. Phase 18 will further re-export tool span event types.
- **`services/agent/tools/__init__.py`** — NEW module. Imports each tool module to trigger `@registry.register` side effects at package load time.
- **`tests/unit/test_tool_registry.py`** — NEW test module: register/get/list/schemas_for + provider mapping coverage.
- **`tests/unit/test_retrieve_tool.py`** — NEW test module: RetrieveTool + RefinedRetrieveTool semantics; assertions on ToolResult shape.
- **`tests/unit/test_agent_pipeline_refactor.py`** — UPDATE existing 11 tests to assert against registry-mediated dispatch (mock target stays at consumer path). Public assertions stay UNCHANGED (parity guarantee preserved).
- **`docs/agent-architecture.md`** — NEW file. Section `#authoring-tools` per ROADMAP SC5.

</code_context>

<specifics>
## Specific Ideas

- The user's emphasis throughout v1.4 has been **enterprise-grade preservation** (multi-tenancy, JWT, RLS, audit). Phase 17 must NOT regress these — `ToolContext.tf` carries the tenant filter through to retrieval; `audit_service.log()` call site in `AgentQueryPipeline._persist_turn` is unchanged. RLS isolation is preserved by construction (registry doesn't touch DB; `_retrieve_impl` calls `retriever.retrieve(filters=...)` exactly as v1.3 did).
- **Decorator registration over imperative `register()` calls** — Phase 17 adopts `@registry.register` because it co-locates the registration with the class definition. Future tool authors don't have to remember to register elsewhere.
- **Prompt parity is the acceptance gate.** v1.3 unit tests + Phase 16 parity fixtures + the `_AGENT_SYSTEM` prompt verbatim guarantee that the LLM sees the same world post-Phase-17. The only LLM-visible change is JSON-encoded — `tools=...` array still has same `name`, `description`, `input_schema` content for the two retrieve tools.

</specifics>

<deferred>
## Deferred Ideas

### To Phase 18 (SSE Planner Trace Event Stream)

- `tool.span.start` / `tool.span.end` / `tool.span.error` SSE events read tool name + ToolResult.metadata; Phase 17 ToolResult shape (D-02) is the contract Phase 18 consumes.
- `executor.parallel` SSE event reads `len(plan.parallel_groups[i])`; Phase 16 already in place.

### To Phase 19 (Agent-First Docs + Demo + Release)

- Historical intent mapping table (Query/Agent/Swarm → ToolPlan shape) — Phase 16 D-13 deferred to Phase 19. Phase 17 stub doc only covers Tool authoring, not intent migration.
- README rewrite leading with agent-first architecture; Phase 17 `docs/agent-architecture.md` becomes the canonical reference Phase 19 README links to.
- `make demo-agent` target — Phase 19. Phase 17 ensures registry surface is stable enough that demo can showcase tool plug-in.

### To v1.5+

- **Collapse `search_knowledge_base` + `refine_search` into single RetrieveTool.** Phase 17 keeps two names for prompt parity; collapsing requires regenerating parity fixtures + may invite subtle planner behavior changes. Worth a focused phase later.
- **`MultiQueryRetrieveTool`** wrapping `retrieve_multi_query` — separate tool class. Out of scope for Phase 17.
- **SwarmQueryPipeline migration to registry** — D-11 scope-reduce. Becomes a v1.5+ follow-up after AGENT-05 (multi-agent debate) lands.
- **Real `WebSearchTool` implementation** — Phase 17 ships placeholder. v1.5+ wires actual search provider with retry/timeout/cost guards.
- **`SQLTool`** for structured query with RLS-shaped tenant isolation — v1.5+. Was an option for Phase 17 placeholder but rejected as too heavy.
- **MCP plug-in discovery** — 10x roadmap #3. Replaces static registry with discovery protocol. D-07 keeps `ToolRegistry` API surface clean enough that swap is a single class replacement.
- **Per-tool retry / circuit-breaker policy** — uniform infrastructure on `BaseTool` (e.g., `retry: ClassVar[RetryPolicy]`). Defer until ≥3 real tools exist that need different policies.
- **`Tool` lifecycle hooks** — `before_run` / `after_run` for instrumentation. Defer until Phase 18 SSE work proves the need.
- **Tool authoring guide expansion** — Phase 17 stub is minimum. Phase 19 expands into user-facing tutorial with screenshots / asciinema if useful for the agent-first narrative.

</deferred>

---

*Phase: 17-tool-abstraction-retrievetool*
*Context gathered: 2026-05-09*
