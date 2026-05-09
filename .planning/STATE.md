---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: Agent-First Architecture Inversion
status: executing
stopped_at: Plan 19-02 complete (RED+GREEN, 6 integration tests, runner module)
last_updated: "2026-05-09T15:33:21.346Z"
last_activity: 2026-05-09
progress:
  total_phases: 4
  completed_phases: 2
  total_plans: 19
  completed_plans: 12
  percent: 63
---

# STATE — EnterpriseRAG (v1.4 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-09 after v1.4 open)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** Phase 19 — Agent-First Docs + Demo + Release (Phase 18 complete; AGENT-04 closed; awaiting Phase 19 docs+demo to lock v1.4 milestone PR)

## Current Position

Phase: 18 (sse-planner-trace-event-stream) — EXECUTING
Plan: 2 of 5
Status: Ready to execute
Last activity: 2026-05-09

| Field | Value |
|-------|-------|
| Milestone | v1.4 Agent-First Architecture Inversion |
| Current phase | 17 — Tool Abstraction + RetrieveTool (3/3 plans executed) |
| Current plan | 17-03 (complete) |
| Phase status | 2/4 phases implementation-complete (verify pending on both 16 + 17) |
| Overall progress | Phase 17 = 100% plans executed; v1.4 = 50% phases at impl-complete |

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 16 | Planner + Executor Extraction | AGENT-06, AGENT-09, NLU-03 | All 3 waves executed; awaiting /gsd-verify-work 16 |
| 17 | Tool Abstraction + RetrieveTool | AGENT-07 | All 3 waves executed; awaiting /gsd-verify-work 17 |
| 18 | SSE Planner Trace Event Stream | AGENT-04 | Context gathered (D-01..D-18); ready for /gsd-plan-phase 18 |
| 19 | Agent-First Docs + Demo + Release | AGENT-08 | Not started |

## Accumulated Context

### Carry-Forward from v1.3 (key decisions still in force)

| Decision | Source | Why it matters in v1.4 |
|----------|--------|------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All v1.4 work runs on this stack; multi-tenancy preserved by construction |
| Section heading text in embedded content; numeric IDs in metadata only | v1.1 Phase 8 D-02 | Any new chunker / retrieval work must preserve this rule |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 | Pattern reused for any new filtered queries inside `RetrieveTool` |
| Regex-first filter extractor in `services/nlu/filter_extractor.py` | v1.1 Phase 8 QUERY-01 | NLU-03 (intent classification by planner) must NOT regress regex-first behavior — regex stays the cheap first branch inside `RetrieveTool`'s filter handling |
| FastAPI StaticFiles mount at `/ui/`; `static/index.html → ui.html` symlink | v1.1 Phase 9 | UI demo for agent-first must preserve this; only update content, not mount |
| `diff-cover ≥ 80%` gate on touched files | v1.1 Phase 10 TEST-03 | All v1.4 PRs MUST pass this gate |
| Combined coverage `--fail-under=70` global floor | v1.3 Phase 15 | New v1.4 modules included from day one — no exemption |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | New `Planner` and `Executor` reuse this provider-neutral interface — don't add `@abstractmethod` |
| `parallel_tool_calls=True` explicit in OpenAI; `disable_parallel_tool_use=False` explicit in Anthropic | v1.2 Phase 11 | New `Executor` inherits this pattern for tool dispatch |
| `asyncio.gather` for concurrent tool execution | v1.2 Phase 11 | New `Executor` runs `ToolPlan.steps` via `asyncio.gather` (parallelism factor logged) |
| `AgentQueryPipeline` body byte-identical baseline (v1.2 close → v1.3 D-01) | v1.3 Phase 12 | v1.4 Phase 16 explicitly modifies this — refactor MUST keep behavioral parity via tests against v1.3 baseline before any new behavior lands |
| `_execute_tool_call` duplicated verbatim across `SwarmQueryPipeline` + `AgentQueryPipeline` | v1.3 Phase 12 + 15 audit | v1.4 Phase 16 extracts the shared helper (AGENT-09); both pipelines must call the helper after extraction |
| Sub-agents do NOT inherit chat history | v1.3 D-06 | True context isolation; preserved if Phase 16 planner ever fans into swarm-style sub-agents (deferred to v1.5+ AGENT-05 but design hooks must not block) |
| `BaseException` (not `Exception`) for `asyncio.gather` isolation | v1.3 Phase 12 | New `Executor` uses the same exception scope to avoid `CancelledError` / `TimeoutError` propagation |
| Mock at consumer path (`services.<mod>.<dep>`) not source | v1.3 Phase 13 + 15 | All v1.4 unit tests follow this pattern |
| Phase 15 D-08 `parallel = false` in `[tool.coverage.run]` | v1.3 Phase 15 | Combine job topology preserved verbatim across v1.4 |

### Source Design Document

`/home/ubuntu/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` — Approach A (incremental refactor, no framework lock-in). Read at the start of `/gsd-plan-phase 16`.

### Open Questions Carried into Planning

(From the source design doc — to be resolved during phase discussions, not blockers for opening v1.4.)

1. **Planner output schema.** Pydantic model fields for `ToolPlan` (`steps: list[ToolCall]`, `parallel_groups: list[list[int]]`, `rationale: str`). Decide in Phase 16 plan.
2. **Tool registration mechanism.** Static class registry vs plugin discovery. Recommend static registry for v1.4 with abstraction clean enough that MCP can replace it without callsite changes.
3. **Iteration cap policy.** v1.3's hardcoded `max_iterations=5` vs adaptive cap. Recommend keep static for v1.4 to constrain blast radius.
4. **Backwards compatibility.** Keep `/query?agent_mode=true` working as a thin alias for `/agent/v1/run`? Recommend alias.
5. **Sub-agent reuse.** `SwarmQueryPipeline` as a tool (composes naturally) vs separate execution mode. Recommend tool — confirm in Phase 16 discussion.
6. **Cross-model second opinion.** Skipped during /office-hours. Worth running `codex review` on the design doc before locking Phase 16 plan.

### Blockers

None.

### Todos (carry-forward, not v1.4-scoped but tracked)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9/14 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10/15 live PR through CI confirms `coverage-combine` job + HTML artifact (natural confirmation on first PR)
- [ ] Push tags `v1.1`, `v1.2`, `v1.3` to origin (currently local-only)
- [ ] PR #1 + PR #2 + PR #3 (v1.3) review + merge
- [ ] v1.5+ follow-up: lift 5 large modules above per-module 70% (pipeline, llm_client, vector_store, retriever, extractor)
- [ ] v1.5+ follow-up: AGENT-05 multi-agent debate / sub-agent verify (10x roadmap #2)
- [ ] v1.5+ follow-up: UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke test

## Session Continuity

**Last updated:** 2026-05-09 — Phase 17 implementation complete (3 waves, 22 commits)
**Stopped at:** Plan 19-02 complete (RED+GREEN, 6 integration tests, runner module)
**Next action:** Run `/gsd-verify-work 17` to confirm AGENT-07 acceptance against codebase. Then advance to `/gsd-discuss-phase 18` (SSE Planner Trace Event Stream, AGENT-04). Phase 18 consumes Phase 17's `ToolResult.metadata` shape for `tool.span` events — forward-compat verified during Phase 17 research (RESEARCH §"Phase 18 SSE Forward-Compat").

### Phase 17 Wave 1 Execution Notes

- **Wave 1 (commits 60742c4 → 2fdb765, feat(17-01-T1..T6) + summary):** Built BaseTool ABC at `services/agent/tools/base.py` with `__init_subclass__` ClassVar guard (RESEARCH Pitfall 2 — silent AttributeError prevention). Built ToolRegistry class at `services/agent/tools/registry.py` with `register/get/list/schemas_for(provider, names=None)` + `get_tool_registry()` singleton. Added ToolResult + ToolContext Pydantic V2 frozen models to `utils/models.py` (ToolContext sets `arbitrary_types_allowed=True` per Pitfall 3). Added `provider_name: ClassVar[str]` to BaseLLMClient + 3 subclasses (Anthropic="anthropic", OpenAI="openai", Ollama="openai"). 28 new TDD tests (11 base + 17 registry incl. byte-identical-to-_AGENT_TOOLS parity test). Verification: 684 passed (was 656); coverage 72.4%; ruff clean; mypy 0 new errors.

### Phase 17 Wave 2 Execution Notes

- **Wave 2 (commits d9d3fc3 → c07a526, feat(17-02-T1..T6) + summary):** Built `_retrieve_impl` (private) + `retrieve_impl` (public swarm-compat shim alias) at `services/agent/tools/retrieve.py` — body verbatim from `services/agent/tool_executor.py::execute_tool_call:38-66` with XML format string immutable (Pitfall 5). Built RetrieveTool (search_knowledge_base) + RefinedRetrieveTool (refine_search) — both subclass BaseTool, share `_retrieve_impl`, parameters_schema byte-identical to deleted `_AGENT_TOOLS` entries. Built WebSearchTool placeholder at `services/agent/tools/web_search.py` returning canned `ToolResult(content="[WebSearchTool placeholder — v1.5+]", metadata={"placeholder": True, ...})`. Tools registered via `@get_tool_registry().register` decorator at module top + explicit imports in `services/agent/tools/__init__.py` (RESEARCH Decision 3). 45 new TDD tests (30 retrieve + 15 web_search). Verification: 729 passed; coverage 93% on services/agent/tools/; ruff clean; mypy 0 new errors.

### Phase 17 Wave 3 Execution Notes

- **Wave 3 (commits ac23340 → f19e8d5, feat(17-03-T1..T7) + T5b + summary):** Swapped `Executor._dispatch_one` to call `get_tool_registry().get(tc.name).run(args=tc.arguments or {}, ctx=ToolContext(req=req, tf=tf, retriever=self._retriever, llm=self._llm))`. Deleted `services/agent/tool_executor.py` entirely. Deleted `_AGENT_TOOLS` literal at services/pipeline.py:602-641; added `AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search"]` module constant; replaced `tools=self._AGENT_TOOLS` callsites with `tools=get_tool_registry().schemas_for(self._llm.provider_name, names=AGENT_TOOL_ALLOWLIST)`. Extended `services/agent/__init__.py` to re-export BaseTool/ToolRegistry/get_tool_registry. Created `docs/agent-architecture.md#authoring-tools` stub (97 lines, ROADMAP SC5). Three deviations auto-fixed (Rules 1+3): (1) SwarmQueryPipeline _AGENT_TOOLS reference also switched to registry instead of shim alias — cleaner; (2) 2 test fixtures missing `_llm.provider_name` — added; (3) test_agent_parity.py patched deleted `execute_tool_call` — updated to registry mock. Verification: 729 passed; coverage 72.6%; ruff clean; mypy 0 new errors. AGENT-07 closed.

### Phase 16 Wave 3 Execution Notes

- **Wave 3 (commits f69a4b0 → c896b4b, feat(16-03-T1..T4) + summary commit):** AgentQueryPipeline.run rewritten as thin orchestrator over `get_planner()` + `get_executor()`; final body 43 lines (≤50 gate). Module-level `MAX_ITERATIONS = 5` constant absorbs v1.3 outer-loop cap (CONTEXT.md D-12). Both `_execute_tool_call` one-line delegates deleted from `services/pipeline.py` — `grep -rnE "def _execute_tool_call" services/` returns 0; only `async def execute_tool_call` in `services/agent/tool_executor.py:24` remains (AGENT-09 acceptance). `tests/unit/test_agent_pipeline_refactor.py` mock targets switched to `services.pipeline.get_planner` / `services.pipeline.get_executor` (consumer-path pattern); 11 public assertions unchanged. Verification: `pytest tests/unit -q` → 656 passed / 1 skipped / 0 failures; `coverage report --fail-under=70` → 72.1%; `ruff check services/ tests/` clean; `mypy --strict` 296 errors (= v1.3 baseline, 0 new).
- **Three deviations (auto-fixed, Rule 1/2):** (1) `Executor.execute_plan` lacked `return_exceptions=True` on `asyncio.gather` — broke error-isolation test; fixed. (2) `SwarmQueryPipeline` filter extractor not injectable — added DI param to keep 8 swarm tests green. (3) `test_execute_plan_propagates_exceptions` updated to assert post-fix isolation behavior. All in scope for `services/agent/executor.py`, `services/pipeline.py`, `tests/unit/test_executor.py`, `tests/unit/test_swarm_pipeline.py` — no architectural drift from PLAN.md must-haves.
- **Phase 16 close-out:** AGENT-06 (planner + executor extraction), AGENT-09 (single shared `execute_tool_call`), NLU-03 (intent classification by planner — preserves regex-first filter extractor) all implementation-complete. `/gsd-verify-work 16` is the next gate.

### Phase 16 Wave 1 + 2 Execution Notes

- **Wave 1 (commit 635790d, feat(16-01)):** services/agent/ package created. tool_executor.py contains the shared async free function (body verbatim from v1.3 services/pipeline.py:846-887). AgentQueryPipeline._execute_tool_call (line 847) and SwarmQueryPipeline._execute_tool_call (line 1078) replaced with one-line delegates. Two synthesized parity fixtures written under tests/unit/fixtures/agent_parity/ (single_step + parallel_multi_step) — synthesized from v1.3 fixture shape rather than captured from a real LLM run because PG was empty in the dev environment; downstream Wave 3 verification still relies on the existing 19 tests in test_agent_pipeline_refactor.py + test_swarm_pipeline.py for parity. Verification: 19/19 critical tests pass; ruff clean.
- **Wave 2 (TDD on Plan 16-02):** Added ToolPlan to utils/models.py with 5 validators (empty groups, out-of-range index, duplicate index, missing index, empty inner group). New services/agent/planner.py with Planner + PlannerOutputError + get_planner singleton. New services/agent/executor.py with Executor + get_executor singleton; walks parallel_groups via asyncio.gather; preserves results in step-index order; BaseException scope per v1.3 D-01. services/agent/__init__.py re-exports the public surface. Three new test files: test_planner.py (19 tests: 12 ToolPlan validators + 7 Planner), test_executor.py (6 tests: dispatch order, two-wave ordering, exception propagation, id round-trip, empty plan, parallel coverage), test_agent_parity.py (2 parametrized tests over the fixtures). Verification: 55/55 critical tests pass (28 v1.3 baseline + 27 Wave 2 new); mypy --strict on services/agent/ clean; ruff clean.
- **Planner API alignment fix:** initial Planner.plan_from_messages signature did not match BaseLLMClient.call_agentic_turn (which requires `system: str` and `tools: list[dict[str, Any]]` positional/keyword). Fixed by adding `system: str | None = None` parameter and defaulting to module-level `_PLANNER_SYSTEM` constant. Stub LLMs in tests accept `**_: Any` to absorb the kwarg.
- **No new behavior in v1.3 surface:** AgentQueryPipeline.run body is BYTE-IDENTICAL to its state at the start of Phase 16 (modulo Wave 1's one-line _execute_tool_call delegate). Phase 16 Wave 3 is the seam swap.
