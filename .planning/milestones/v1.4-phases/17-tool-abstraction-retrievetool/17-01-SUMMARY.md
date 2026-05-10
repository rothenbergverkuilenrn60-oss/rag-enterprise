---
phase: 17-tool-abstraction-retrievetool
plan: 01
subsystem: agent
tags: [pydantic-v2, abc, tool-registry, mypy-strict, tdd, ruff]

# Dependency graph
requires:
  - phase: 16-planner-executor-extraction
    provides: "ToolCall/ToolPlan models in utils/models.py, BaseLLMClient ABC, Planner/Executor pattern, TDD precedent"
provides:
  - "BaseTool ABC with __init_subclass__ ClassVar guard (services/agent/tools/base.py)"
  - "ToolRegistry with register/get/list/schemas_for + get_tool_registry() singleton (services/agent/tools/registry.py)"
  - "ToolResult + ToolContext Pydantic V2 frozen models (utils/models.py)"
  - "provider_name ClassVar on BaseLLMClient + OllamaLLMClient + OpenAILLMClient + AnthropicLLMClient"
  - "Parity test: schemas_for('anthropic') == _AGENT_TOOLS byte-identical (TestParity)"
affects: [17-02-PLAN, 17-03-PLAN, services/pipeline.py, services/agent/executor.py]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "BaseTool ABC with __init_subclass__ ClassVar guard — enforces name/description/parameters_schema at class-definition time"
    - "ToolRegistry decorator pattern — @get_tool_registry().register returns cls unchanged (Flask/Click idiom)"
    - "Provider-shape branching — anthropic={input_schema}; openai/ollama={type:function,function:{parameters}}"
    - "typing.List in class method signature to avoid method-name shadowing builtin list with from __future__ import annotations"

key-files:
  created:
    - services/agent/tools/__init__.py
    - services/agent/tools/base.py
    - services/agent/tools/registry.py
    - tests/unit/test_base_tool.py
    - tests/unit/test_tool_registry.py
  modified:
    - utils/models.py
    - services/generator/llm_client.py

key-decisions:
  - "ToolContext.model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True) — both flags required; arbitrary_types_allowed enables HybridRetrieverService + AnthropicLLMClient instances in ctx.retriever/ctx.llm"
  - "OllamaLLMClient.provider_name = 'openai' — Ollama uses OpenAI-compatible tool format (RESEARCH A3)"
  - "typing.List used in schemas_for() signature instead of builtin list to avoid mypy resolving ToolRegistry.list() method as type annotation (from __future__ import annotations PEP 563 class-scope shadowing)"
  - "asyncio.run() used in test_base_tool.py instead of deprecated asyncio.get_event_loop() (Python 3.12)"
  - "ToolResult.chunks: list[Any] — conservative Wave 1 choice; concrete RetrieveTool populates with RetrievedChunk instances in Wave 2"

patterns-established:
  - "BaseTool subclasses declare all 3 ClassVars explicitly (name/description/parameters_schema) — __init_subclass__ guard enforces at class-def time, not instantiation time"
  - "ToolRegistry tests: each test creates fresh ToolRegistry() instance for isolation; ONLY TestSingleton calls get_tool_registry()"
  - "Parity constant _EXPECTED_AGENT_TOOLS in test_tool_registry.py — byte-identical copy of services/pipeline.py:601-640 _AGENT_TOOLS; guards Wave 3 deletion"

requirements-completed: [AGENT-07]

# Metrics
duration: 10min
completed: 2026-05-09
---

# Phase 17 Plan 01: BaseTool ABC + ToolRegistry + ToolResult/ToolContext + provider_name (Wave 1, TDD) Summary

**Pydantic V2 frozen ToolResult/ToolContext + BaseTool ABC with __init_subclass__ ClassVar guard + ToolRegistry with provider-shape branching (anthropic/openai/ollama) + provider_name ClassVar on all LLM clients — 28 new tests, 0 regressions vs Phase 16 baseline (684 total)**

## Performance

- **Duration:** 10 min
- **Started:** 2026-05-09T05:54:03Z
- **Completed:** 2026-05-09T06:04:00Z
- **Tasks:** 7
- **Files modified:** 7

## Accomplishments

- RED gate: 11 + 17 failing tests written before any implementation (T1/T2); both files fail ImportError as expected
- GREEN gate: ToolResult/ToolContext in utils/models.py (T3), BaseTool ABC + __init_subclass__ guard (T4), ToolRegistry + singleton (T5), provider_name ClassVar (T6) — all tests go green in order
- REFACTOR: 684 passed, 72.4% coverage, ruff clean, 0 new mypy errors vs baseline; consumer files (pipeline.py/executor.py/tool_executor.py) untouched

## Task Commits

1. **T1: RED gate — test_base_tool.py** — `60742c4` (test)
2. **T2: RED gate — test_tool_registry.py** — `7f919e6` (test)
3. **T3: GREEN ToolResult + ToolContext** — `06c0fc3` (feat)
4. **T4: GREEN BaseTool ABC** — `42118fe` (feat)
5. **T5: GREEN ToolRegistry + get_tool_registry** — `897a3fc` (feat)
6. **T6: GREEN provider_name ClassVar** — `ce4c549` (feat)
7. **T7: REFACTOR sweep** — `ce4c549` (no new files; all gates already passing)

## Files Created/Modified

- `services/agent/tools/__init__.py` — package init; re-exports BaseTool, ToolRegistry, get_tool_registry
- `services/agent/tools/base.py` — BaseTool ABC: __init_subclass__ guard, abstractmethod run, _build_error_result helper
- `services/agent/tools/registry.py` — ToolRegistry: register/get/list/schemas_for + get_tool_registry() singleton
- `utils/models.py` — added ToolResult + ToolContext (frozen Pydantic V2 models) after ToolPlan
- `services/generator/llm_client.py` — ClassVar import + provider_name on BaseLLMClient + 3 subclasses
- `tests/unit/test_base_tool.py` — 11 tests (RED→GREEN): ToolResult/ToolContext models + BaseTool ABC guards
- `tests/unit/test_tool_registry.py` — 17 tests (RED→GREEN): registry CRUD + provider mapping + parity + provider_name

## Decisions Made

- `arbitrary_types_allowed=True` required on ToolContext — without it, Pydantic V2 raises PydanticUserError when constructing with HybridRetrieverService/AnthropicLLMClient instances (RESEARCH Pitfall 3)
- `OllamaLLMClient.provider_name = "openai"` — Ollama is OpenAI-API-compatible; same tool wire format (RESEARCH Decision 2, A3)
- `typing.List` in `schemas_for()` signature to avoid `from __future__ import annotations` resolving `list[str]` as `ToolRegistry.list` method in class scope (PEP 563 class-scope shadowing issue caught by mypy-strict — Rule 1 fix)
- `asyncio.run()` instead of `asyncio.get_event_loop().run_until_complete()` — the latter raises RuntimeError on Python 3.12 when no event loop is active (Rule 1 fix)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] asyncio.run() instead of deprecated get_event_loop()**
- **Found during:** T4 (test_base_tool.py GREEN run)
- **Issue:** `asyncio.get_event_loop().run_until_complete(tool.run({}, ctx))` raises `RuntimeError: There is no current event loop in thread 'MainThread'` on Python 3.12
- **Fix:** Changed to `asyncio.run(tool.run({}, ctx))` in test_base_tool.py
- **Files modified:** tests/unit/test_base_tool.py
- **Verification:** test_concrete_subclass_with_all_classvars_instantiates PASSED
- **Committed in:** 42118fe (T4 commit)

**2. [Rule 1 - Bug] typing.List in schemas_for() to avoid method-name/annotation shadow**
- **Found during:** T5 (mypy --strict on services/agent/tools/registry.py)
- **Issue:** `names: list[str] | None = None` annotation in `schemas_for()` — with `from __future__ import annotations`, mypy resolves `list` in the class-scope and finds the `list()` method instead of the builtin, emitting 2 new [valid-type] errors
- **Fix:** Changed parameter/return type annotations to use `typing.List[str]` / `typing.List[dict[str, Any]]` for `schemas_for()` only
- **Files modified:** services/agent/tools/registry.py
- **Verification:** mypy --strict shows 0 errors on services/agent/tools/; total error count unchanged vs baseline (121)
- **Committed in:** 897a3fc (T5 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both fixes required for correctness. No scope creep; no Wave 2/3 files touched.

## Issues Encountered

- mypy --strict traverses all transitively imported files (config, retriever, vectorizer) when called on any services/ file; "0 new errors" was confirmed by comparing total count before/after our changes (123 → 121, and 0 errors on services/agent/tools/ specifically)

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Wave 1 infrastructure complete; Wave 2 (17-02) can register RetrieveTool + RefinedRetrieveTool + WebSearchTool via `@get_tool_registry().register`
- Wave 3 (17-03): AgentQueryPipeline.run reads `self._llm.provider_name` and calls `registry.schemas_for(...)` to replace the inline `_AGENT_TOOLS` literal
- Parity test in TestParity::test_schemas_for_anthropic_matches_agent_tools_literal guards against schema drift during Wave 2 tool implementation

---
*Phase: 17-tool-abstraction-retrievetool*
*Completed: 2026-05-09*
