---
status: complete
phase: 17-tool-abstraction-retrievetool
source:
  - 17-01-SUMMARY.md
  - 17-02-SUMMARY.md
  - 17-03-SUMMARY.md
started: 2026-05-09T20:35:00Z
updated: 2026-05-09T20:35:00Z
---

## Current Test

[testing complete — awaiting user confirmation of automated evidence]

## Tests

### 1. BaseTool ABC + ClassVar guard (ROADMAP SC1, AGENT-07, D-01)
expected: |
  - `services/agent/tools/base.py` defines `class BaseTool(abc.ABC)` with three required `ClassVar` attributes: `name: str`, `description: str`, `parameters_schema: dict[str, Any]`
  - `@abstractmethod async def run(args: dict, ctx: ToolContext) -> ToolResult` declared
  - `__init_subclass__` guard raises `TypeError` if a concrete subclass omits any required ClassVar (RESEARCH Pitfall 2 — silent AttributeError prevention)
  - 11 RED-then-GREEN tests in `tests/unit/test_base_tool.py` cover guard semantics
result: pass
evidence: |
  $ grep -nE 'class BaseTool|__init_subclass__|raise TypeError|abstractmethod' services/agent/tools/base.py
  → line 40: __init_subclass__ guard
  → line 47: raise TypeError on missing ClassVar
  → line 51: @abc.abstractmethod async def run
  Subagent verification: 11 test_base_tool.py tests GREEN.

### 2. ToolResult + ToolContext Pydantic V2 frozen (CONTEXT.md D-02, D-03; RESEARCH Pitfall 3)
expected: |
  - `utils/models.py::ToolResult` (line 359) Pydantic V2 frozen with `content: str`, `chunks: list[RetrievedChunk]=[]`, `metadata: dict=[{}]`, `is_error: bool=False`
  - `utils/models.py::ToolContext` (line 383) Pydantic V2 frozen with `req: GenerationRequest`, `tf: dict`, `retriever: Any`, `llm: Any`
  - ToolContext sets `arbitrary_types_allowed=True` (RESEARCH Pitfall 3 — without it, Pydantic refuses HybridRetrieverService/AnthropicLLMClient instances)
result: pass
evidence: |
  $ grep -nE 'class ToolResult|class ToolContext|ConfigDict' utils/models.py | tail -10
  → 359: class ToolResult(BaseModel)
  → 375: model_config = ConfigDict(frozen=True)
  → 383: class ToolContext(BaseModel)
  → 396: model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

### 3. ToolRegistry + provider-shape mapping (ROADMAP SC1, D-07, D-08)
expected: |
  - `services/agent/tools/registry.py::ToolRegistry` with `register/get/list/schemas_for(provider, names=None)` methods (lines 33, 44, 55, 59)
  - `get_tool_registry()` singleton (line 109)
  - `schemas_for("anthropic", names=["search_knowledge_base", "refine_search"])` produces output BYTE-IDENTICAL to deleted `_AGENT_TOOLS` literal (parity assertion in test)
  - `schemas_for("openai", ...)` produces correct `{type:"function", function:{name, description, parameters}}` shape per RESEARCH §"Anthropic vs OpenAI Tool Schema Canonical Mapping"
  - 17 RED-then-GREEN tests in `tests/unit/test_tool_registry.py` including byte-identical-to-_AGENT_TOOLS parity test
result: pass
evidence: |
  $ grep -nE 'class ToolRegistry|def register|def get|def list|def schemas_for|def get_tool_registry' services/agent/tools/registry.py
  → all 6 expected lines present
  Subagent verification: 17 test_tool_registry.py tests GREEN, including parity test against deleted _AGENT_TOOLS.

### 4. RetrieveTool + RefinedRetrieveTool wrap retrieval verbatim (ROADMAP SC2, D-04, D-05)
expected: |
  - `services/agent/tools/retrieve.py` defines `RetrieveTool` (name="search_knowledge_base") + `RefinedRetrieveTool` (name="refine_search")
  - Both subclass BaseTool; both registered via `@get_tool_registry().register` decorator at module top
  - Both delegate to private `_retrieve_impl(query, top_k, filters, retriever, llm)` helper — body BYTE-IDENTICAL to deleted `services/agent/tool_executor.py:execute_tool_call:38-66` (XML format string immutable, RESEARCH Pitfall 5)
  - Both `parameters_schema` ClassVars BYTE-IDENTICAL to deleted `_AGENT_TOOLS[0|1]["input_schema"]`
  - Public `retrieve_impl` shim alias preserved for swarm-compat path
  - 30 RED-then-GREEN tests in `tests/unit/test_retrieve_tool.py`
  - 19 v1.3 unit tests in test_agent_pipeline_refactor.py + test_swarm_pipeline.py + test_agent_parity.py STILL PASS (public assertions UNCHANGED)
result: pass
evidence: |
  Subagent verification: 30 test_retrieve_tool.py tests GREEN; parity tests preserved.
  Wave 3 deviation 3 (auto-fixed): test_agent_parity.py mock target updated from deleted execute_tool_call to registry — public assertions still UNCHANGED.

### 5. WebSearchTool placeholder + agent allowlist exclusion (ROADMAP SC3, D-10)
expected: |
  - `services/agent/tools/web_search.py::WebSearchTool` (name="web_search") subclasses BaseTool, returns `ToolResult(content="[WebSearchTool placeholder — v1.5+]", metadata={"placeholder": True, ...})`
  - Registered via `@get_tool_registry().register`; appears in `registry.list()` output
  - EXCLUDED from `services/pipeline.py::AGENT_TOOL_ALLOWLIST = ["search_knowledge_base", "refine_search"]` — planner LLM does NOT see `web_search` in its tool schemas
  - 15 RED-then-GREEN tests in `tests/unit/test_web_search_tool.py`
result: pass
evidence: |
  $ grep -nE 'class WebSearchTool|placeholder|name.*web_search' services/agent/tools/web_search.py
  → line 35: class WebSearchTool(BaseTool)
  → line 38: name: ClassVar[str] = "web_search"
  → line 53: content="[WebSearchTool placeholder — v1.5+]"
  → line 55: "placeholder": True
  $ grep -n 'AGENT_TOOL_ALLOWLIST' services/pipeline.py
  → 590: AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search"]  (web_search NOT in list)

### 6. Executor dispatches strictly through registry; no name-imports (ROADMAP SC4, D-09; AGENT-09 carry-forward)
expected: |
  - `services/agent/executor.py::Executor._dispatch_one` body: builds `ToolContext`, calls `get_tool_registry().get(tc.name).run(args, ctx)` — returns `ToolResult`
  - `services/agent/executor.py` imports `get_tool_registry` from `services.agent.tools` ONLY; NO name-imports of RetrieveTool/RefinedRetrieveTool/WebSearchTool
  - `services/pipeline.py` has NO name-imports of specific tool classes
  - `services/agent/tool_executor.py` is DELETED
  - `grep -rnE 'def _execute_tool_call' services/` returns 0 (AGENT-09 NOT regressed)
  - `_AGENT_TOOLS` literal removed from `services/pipeline.py` (was at lines 602-641)
  - `AGENT_TOOL_ALLOWLIST` constant defined; used at AgentQueryPipeline.run + SwarmQueryPipeline.run callsites
result: pass
evidence: |
  $ ls services/agent/tool_executor.py
  → DELETED (cannot access)
  $ grep -rnE 'def _execute_tool_call' services/
  → 0 matches
  $ grep -nE '_AGENT_TOOLS' services/pipeline.py
  → 0 matches
  $ grep -n 'AGENT_TOOL_ALLOWLIST' services/pipeline.py
  → 590 (def) + 781 (Agent callsite) + 933 (Swarm callsite — Rule 3 deviation; switched to registry instead of shim alias)

### 7. Tool authoring guide stub + integration sweep (ROADMAP SC5; final acceptance)
expected: |
  - `docs/agent-architecture.md` exists with `#authoring-tools` section containing:
    1. "How to define a Tool" (subclass BaseTool, set 3 ClassVars, implement async run)
    2. "How to register" (`@get_tool_registry().register` decorator)
    3. "parameters_schema shape" (JSON Schema dict)
    4. One runnable RetrieveTool-style example
  - Phase 19 historical intent mapping deferred (per Phase 16 D-13)
  - Full unit suite: `pytest tests/unit -q` → 729 passed (656 baseline + 73 new TDD tests, 0 regressions)
  - `coverage report --fail-under=70` → 72.6%
  - `ruff check services/ tests/` clean
  - `mypy --strict services/agent/ services/pipeline.py utils/models.py services/generator/llm_client.py` → 0 NEW errors vs Phase 16 baseline (296)
  - Multi-tenancy / RLS / JWT / audit untouched (services/auth/, services/audit/ 0 changes in Phase 17 delta)
result: pass
evidence: |
  $ wc -l docs/agent-architecture.md
  → 98 lines
  $ grep -n '^##' docs/agent-architecture.md
  → ## Authoring Tools, ### Defining a Tool, ### Registering a Tool, ### parameters_schema Shape, ### Allowlisting, ### Runnable Example, ### ToolResult metadata convention
  Subagent verification (Wave 3 T7): 729 passed, coverage 72.6%, ruff clean, mypy 0 new errors.
  $ git diff --stat c896b4b..HEAD services/auth/ services/audit/
  → 0 files changed (RLS/JWT/audit infrastructure untouched in Phase 17)

## Summary

total: 7
passed: 7
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

<!-- No gaps. All ROADMAP SC1-5 + AGENT-07 + CONTEXT.md decisions D-01..D-12 + RESEARCH.md pitfalls 1-6 verified. -->

## Notes

- note: "Wave 3 deviation 1: SwarmQueryPipeline switched to registry instead of the planned shim alias path."
  status: by-design
  reason: |
    Plan 17-03 directed SwarmQueryPipeline import switch to `from services.agent.tools.retrieve import retrieve_impl as execute_tool_call` (the public swarm-compat shim alias). Subagent (Rule 3 deviation) switched it to `registry.schemas_for(...)` callsite directly — same architectural intent but cleaner. Result: SwarmQueryPipeline now also benefits from the registry surface; net move is in the direction of the v1.5+ Swarm migration deferred per D-11. No regression on 8 swarm tests.
  impact: positive — small unplanned step toward D-11 (Swarm registry migration) without breaking scope.

- note: "Live integration test (real PG + RLS + LLM) NOT run in this verify pass."
  status: deferred
  reason: |
    `tests/integration/test_agent_pipeline_parallel.py` requires `OPENAI_API_KEY` + running pgvector. Same constraint as Phase 16 verify. Unit-level audit field shape preserved (verified by passing parity tests).
  impact: low — recommend manual smoke before `/gsd-ship` to master, OR bundled with Phase 16 integration smoke at v1.4 milestone close.
