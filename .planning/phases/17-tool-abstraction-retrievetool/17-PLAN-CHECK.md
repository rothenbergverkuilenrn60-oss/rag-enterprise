# Phase 17 Plan Check

**Phase:** 17-tool-abstraction-retrievetool
**Plans checked:** 17-01 (Wave 1, TDD, 7 tasks), 17-02 (Wave 2, TDD, 6 tasks), 17-03 (Wave 3, execute, 7 tasks)
**Total tasks:** 20
**Requirement:** AGENT-07
**Baseline:** Phase 16 close — 656 unit tests, mypy 296 errors, coverage ≥70%
**Check date:** 2026-05-09
**Result:** PASS — 0 blockers, 3 warnings

---

## Coverage Summary

| Requirement | Plans | Status |
|-------------|-------|--------|
| AGENT-07 | 17-01, 17-02, 17-03 | Covered |

| ROADMAP SC | Description | Covering Tasks |
|------------|-------------|----------------|
| SC1 | BaseTool ABC with name/description/parameters_schema/async run | 17-01-T4 (impl), 17-01-T1 (tests) |
| SC2 | RetrieveTool wraps v1.3 retrieval; existing fixtures pass | 17-02-T3, T4 (impl), 17-02-T1 (tests) |
| SC3 | WebSearchTool placeholder registered | 17-02-T5 (impl), 17-02-T2 (tests) |
| SC4 | Executor + pipeline tool-class-import-free | 17-03-T1 (executor), 17-03-T3 (pipeline) |
| SC5 | docs/agent-architecture.md#authoring-tools with runnable example | 17-03-T6 |

| Plan | Tasks | Files | Wave | Type | Status |
|------|-------|-------|------|------|--------|
| 17-01 | 7 | 7 | 1 | tdd | Valid |
| 17-02 | 6 | 5 | 2 | tdd | Valid |
| 17-03 | 7 | 8 | 3 | execute | Valid |

---

## Dimension 1: Requirement Coverage — PASS

AGENT-07 is the only requirement for Phase 17. All three plan frontmatter blocks carry `requirements: [AGENT-07]`. The AGENT-07 acceptance contract is fully covered:

- **Tool Protocol/ABC:** BaseTool ABC with `__init_subclass__` ClassVar guard — 17-01-T4 + T1 tests
- **RetrieveTool:** v1.3 `execute_tool_call` body migrated verbatim via `_retrieve_impl` — 17-02-T3, T4
- **≥1 placeholder:** WebSearchTool returning canned ToolResult(content="[WebSearchTool placeholder — v1.5+]") — 17-02-T5, T2
- **Static registry:** ToolRegistry + get_tool_registry() singleton — 17-01-T5
- **MCP-replaceable:** ToolRegistry API surface (register/get/list/schemas_for) designed per D-07; MCP replacement would subclass or swap the singleton without callsite changes

Note on SC2 wording: ROADMAP says "RetrieveTool wraps QueryPipeline.run()." CONTEXT.md D-04 and DISCUSSION-LOG.md GA2-A explicitly clarify that wrapping `execute_tool_call` (not `QueryPipeline.run`) is the correct interpretation — approved by the user. The plans correctly implement D-04.

No uncovered requirement dimensions. No requirement with zero tasks.

---

## Dimension 2: Task Completeness — PASS (1 warning)

All 20 tasks reviewed for `<action>`, `<acceptance_criteria>` (done criteria), and verifiable exit conditions.

**TDD tasks:** 17-01-T1, T2, 17-02-T1, T2 — all have `<behavior>` (numbered test list), `<action>` (concrete file creation with pseudocode), `<acceptance_criteria>` (RED gate: pytest exits non-zero with ImportError).

**AUTO tasks:** 16 tasks across three plans. All have `<action>` with specific file paths, grep commands, or runnable Python one-liners. All have `<acceptance_criteria>` with concrete, runnable verification (grep match counts, pytest exit codes, python -c assertions, git diff checks).

**WARNING:** 17-01-T4 `<action>` step 1 shows a code block for `__init__.py` containing BOTH `from services.agent.tools.base import BaseTool` AND `from services.agent.tools.registry import ToolRegistry, get_tool_registry`. The `<acceptance_criteria>` block explicitly corrects this: *"Correction: T4's `__init__.py` only re-exports `BaseTool`. T5 extends it with ToolRegistry + get_tool_registry. Update step 1 above accordingly when implementing."*

An executor reading `<action>` step 1 first would implement the wrong content. The correction is present but buried in `<acceptance_criteria>` rather than fixed in `<action>`. Self-correcting but ambiguous at read time.

---

## Dimension 3: Dependency Correctness — PASS

Dependency graph:
- 17-01: `depends_on: []` → Wave 1 ✓
- 17-02: `depends_on: ['17-01']` → Wave 2 ✓
- 17-03: `depends_on: ['17-01', '17-02']` → Wave 3 ✓

No cycles. No forward references. Wave assignments consistent with `depends_on`. 17-03 correctly depends on both prior plans:
- Wave 1 output needed by Wave 3: `get_tool_registry`, `ToolContext`, `ToolResult`, `BaseLLMClient.provider_name` (used in executor seam swap + pipeline callsite)
- Wave 2 output needed by Wave 3: registered tool names in registry, `retrieve_impl` shim (for SwarmQueryPipeline import switch)

Same-wave file conflict check: `services/agent/tools/__init__.py` is modified in both 17-01 and 17-02. These are sequential waves with `depends_on: ['17-01']` — no concurrent execution conflict.

---

## Dimension 4: Key Links Planned — PASS

All `must_haves.key_links` entries trace to task actions:

| key_link | Task | Evidence |
|----------|------|----------|
| BaseTool `__init_subclass__` → ClassVar enforcement at class-definition time | 17-01-T4 | `__init_subclass__` guard code shown verbatim in action step 2 |
| ToolRegistry.register → returns cls unchanged (decorator syntax) | 17-01-T5 | `return cls` in register() body; `@get_tool_registry().register` usage shown |
| ToolRegistry.schemas_for → Anthropic `input_schema` / OpenAI `type:function` mapping | 17-01-T5 | Full `if provider == "anthropic"` / `if provider in ("openai", "ollama")` branching shown |
| ToolContext ConfigDict(frozen=True, arbitrary_types_allowed=True) | 17-01-T3 | Both flags explicitly shown; rationale documented (RESEARCH Pitfall 3) |
| BaseLLMClient.provider_name → AgentQueryPipeline.run reads self._llm.provider_name | 17-01-T6 (adds ClassVar) + 17-03-T3 (reads in pipeline callsite) | ClassVar shown in T6 action; `registry.schemas_for(self._llm.provider_name, ...)` shown in T3 |
| @get_tool_registry().register → side-effect triggered by `__init__.py` explicit imports | 17-02-T4, T5 | Side-effect import lines shown; `# noqa: F401` noted |
| retrieve_impl shim → SwarmQueryPipeline import alias | 17-03-T3 | `from services.agent.tools.retrieve import retrieve_impl as _shared_execute_tool_call` shown; line 974 callsite preserved |
| Executor._dispatch_one → registry.get(tc.name).run(args, ctx) | 17-03-T1 | Rewritten `_dispatch_one` body shown verbatim |
| AgentQueryPipeline._build_tool_results → consumes ToolResult.content + ToolResult.chunks | 17-03-T3 | Updated method body shown in action step 5 with 3-case branch (BaseException / is_error / success) |

---

## Dimension 5: Scope Sanity — WARNING (task count)

| Plan | Tasks | Files | Files OK? | Tasks threshold |
|------|-------|-------|-----------|-----------------|
| 17-01 | 7 | 7 | ✓ (< 15) | WARNING (> 5) |
| 17-02 | 6 | 5 | ✓ (< 15) | WARNING (> 5) |
| 17-03 | 7 | 8 | ✓ (< 15) | WARNING (> 5) |

All three plans exceed the 5-task-per-plan threshold. File counts are within bounds (7/5/8, all < 15). TDD structure drives the task count: each plan follows a RED (2 tasks) → GREEN (3-4 tasks) → REFACTOR (1 task) pattern. Per-task complexity is low:
- RED tasks: write test files with no implementation context required
- GREEN tasks: single-module implementations (~80-100 lines each, one file per task)
- REFACTOR task: run pytest/mypy/ruff/git-diff commands

Effective complex-implementation task count per plan: ~4. The threshold was designed to prevent context exhaustion from complex multi-concern tasks. Individual tasks here are tightly scoped.

---

## Dimension 6: Verification Derivation — PASS

All `must_haves.truths` are executor-verifiable, not implementation-internal:

- "utils/models.py defines ToolResult with ConfigDict(frozen=True)..." → `python -c "from utils.models import ToolResult..."` verifiable ✓
- "ToolResult mutation raises pydantic.ValidationError" → asserted in test_base_tool.py TestToolResultModel ✓
- "pytest tests/unit/test_base_tool.py exits 0 (all 11 tests GREEN)" → runnable ✓
- "mypy --strict ... 0 NEW errors vs Phase 16 baseline of 296" → runnable with documented baseline ✓
- "grep -rnE 'from services.agent.tool_executor' returns 0 matches" → runnable ✓
- "schemas_for output BYTE-IDENTICAL to _AGENT_TOOLS" → test assertion in T2/T1 ✓

Artifacts include `contains:` class/function names that map to truths. key_links connect dependent artifacts. No truth is implementation-internal ("library installed" style).

---

## Dimension 7: Context Compliance — PASS

### Locked Decisions (D-01..D-12)

| Decision | Implementing Task(s) | Coverage |
|----------|---------------------|----------|
| D-01: BaseTool ABC at services/agent/tools/base.py | 17-01-T4 | ✓ |
| D-02: ToolResult Pydantic V2 frozen in utils/models.py | 17-01-T3 | ✓ |
| D-03: ToolContext Pydantic V2 frozen | 17-01-T3 | ✓ |
| D-04: execute_tool_call body migrated verbatim; tool_executor.py DELETED | 17-02-T3, 17-03-T4 | ✓ |
| D-05: RetrieveTool + RefinedRetrieveTool sharing _retrieve_impl | 17-02-T3, T4 | ✓ |
| D-06: _AGENT_TOOLS deleted; AGENT_TOOL_ALLOWLIST added | 17-03-T3 | ✓ |
| D-07: ToolRegistry class + get_tool_registry() singleton | 17-01-T5 | ✓ |
| D-08: Provider mapping in schemas_for(), not in LLM adapters | 17-01-T5 | ✓ |
| D-09: Executor dispatch through registry only; no name-imports of tools | 17-03-T1 | ✓ |
| D-10: WebSearchTool placeholder; excluded from AGENT_TOOL_ALLOWLIST | 17-02-T5, 17-03-T3 | ✓ |
| D-11: SwarmQueryPipeline scope-reduced; retrieve_impl shim handles import | 17-03-T3 | ✓ |
| D-12: No IntentRouter (carry-forward — nothing to do) | N/A — correctly omitted | ✓ |

### Discretion areas handled correctly
- docs stub content: 17-03-T6 with ≥4 subsections (Defining, Registering, parameters_schema shape, Allowlisting, Runnable Example) ✓
- `retrieve_multi_query` not exposed as tool ✓
- `provider_name: ClassVar[str]` on BaseLLMClient (over type().__name__ mapping): 17-01-T6 ✓
- `AGENT_TOOL_ALLOWLIST` module constant (over class flag): 17-03-T3 ✓
- Explicit named imports in `__init__.py` (RESEARCH Decision 3): 17-02-T4, T5 ✓

### Deferred ideas correctly excluded
Verified absent from all plan task actions: collapse search_knowledge_base + refine_search, MultiQueryRetrieveTool, SwarmQueryPipeline registry migration, real WebSearchTool implementation, SQLTool, MCP plug-in discovery, per-tool retry policy, tool lifecycle hooks, historical intent mapping table (Phase 19), README rewrite (Phase 19).

---

## Dimension 7b: Scope Reduction — PASS

No scope reduction language found for required items. Scanned all plan actions for: "v1", "simplified", "static for now", "hardcoded", "future enhancement", "placeholder" (for required items), "not wired to", "stub".

- "v1.5+" appears in WebSearchTool content string `"[WebSearchTool placeholder — v1.5+]"` — this IS the required canned content per D-10. Not scope reduction.
- "placeholder" in WebSearchTool description — D-10 requires this. Not reduction.
- "placeholder=True" in metadata — D-10 requires this. Not reduction.
- D-04 verbatim migration: plans show the byte-identical XML format string and args.get fallback chain in the action. Full delivery.
- D-06 _AGENT_TOOLS deletion: 17-03-T3 action shows the full deletion + AGENT_TOOL_ALLOWLIST addition + _AGENT_SYSTEM preservation. Full delivery.

No decision delivers less than what D-01..D-11 requires.

---

## Dimension 7c: Architectural Tier Compliance — PASS

RESEARCH.md §"Architectural Responsibility Map" maps capabilities to tiers. All plan tasks match:

| Capability | Expected Tier (RESEARCH.md) | Plan Task | File Assigned | Match |
|------------|---------------------------|-----------|---------------|-------|
| Tool protocol (BaseTool) | services/agent/tools/ | 17-01-T4 | services/agent/tools/base.py | ✓ |
| Tool registry + singleton | services/agent/tools/registry.py | 17-01-T5 | services/agent/tools/registry.py | ✓ |
| Provider-schema mapping | ToolRegistry.schemas_for() (NOT LLM adapters) | 17-01-T5 | Inside ToolRegistry only | ✓ |
| RetrieveTool dispatch | services/agent/tools/retrieve.py | 17-02-T3, T4 | services/agent/tools/retrieve.py | ✓ |
| Executor dispatch seam | services/agent/executor.py | 17-03-T1 | services/agent/executor.py | ✓ |
| ToolResult/ToolContext models | utils/models.py | 17-01-T3 | utils/models.py | ✓ |
| Swarm compatibility shim | services/agent/tools/retrieve.py | 17-02-T3 | services/agent/tools/retrieve.py | ✓ |

No security-sensitive capability placed in wrong tier. RLS/tenancy preserved: ToolContext.tf carries `tenant_id` through to `_retrieve_impl` → `retriever.retrieve(filters=...)` unchanged from v1.3. JWT and audit_service.log() callsites are explicitly noted as UNCHANGED in 17-03-T7 acceptance criteria.

---

## Dimension 8: Nyquist Compliance — SKIPPED

RESEARCH.md exists for this phase but contains a section titled "Nyquist Validation Strategy for AGENT-07 Acceptance" — not the required "Validation Architecture" section heading. Per Dimension 8 skip condition: RESEARCH.md has no "Validation Architecture" section → Dimension 8 SKIPPED.

Note: The Nyquist Validation Strategy section itself is thorough (Phase Requirements → Test Map table, Wave 0 gaps identified, sampling rate defined). The skip is a formal heading mismatch, not a substantive coverage gap.

---

## Dimension 9: Cross-Plan Data Contracts — PASS

Critical shared data pipeline: `_retrieve_impl` output → `ToolResult` wrapping (Wave 2) → `_build_tool_results` consumption (Wave 3).

- **Wave 2 transform (17-02-T3, T4):** `_retrieve_impl` returns `(chunks: list[RetrievedChunk], ctx_text: str)`. `RetrieveTool.run()` wraps as `ToolResult(content=ctx_text, chunks=list(chunks), metadata={latency_ms, query, chunk_count})`.
- **Wave 3 consumption (17-03-T3):** `_build_tool_results` reads `output.content` (LLM-facing tool_result content) and extends `all_chunks` with `output.chunks` (RAG accumulation). The updated method body is shown in 17-03-T3 action step 5.

No transform conflict: Wave 2 wraps; Wave 3 unwraps. The mapping is symmetric. ToolResult is frozen (Pydantic V2) — no mutation possible between waves.

Secondary path: `retrieve_impl` shim (Wave 2) returns `tuple[list[RetrievedChunk], str]` — same shape as old `execute_tool_call`. Wave 3 SwarmQueryPipeline test mock target `services.pipeline._shared_execute_tool_call` preserves the tuple return. Existing swarm test stubs return tuples → still correct after the import alias. Explicitly confirmed in 17-03-T5 action.

---

## Dimension 10: CLAUDE.md Compliance — PASS

| CLAUDE.md Directive | Plans | Compliance |
|--------------------|-------|-----------|
| No prototype code — Pydantic V2, mypy --strict, ruff | All | ToolResult/ToolContext use ConfigDict(frozen=True); explicit ClassVar annotations per RESEARCH Pitfall 6; mypy + ruff in every REFACTOR task ✓ |
| No bare except — narrow exception types (ERR-01) | 17-02-T4 | `_RETRIEVE_RUNTIME_ERRORS = (RuntimeError, ValueError, anthropic.APIError, openai.APIError, httpx.HTTPError, TimeoutError)` ✓ |
| No blocking I/O in async contexts | 17-02-T3, T4 | `_retrieve_impl` and all `.run()` methods are `async def` ✓ |
| Adapters for external deps | 17-01-T3 | retriever/llm accessed via ToolContext fields, not imported directly in tool modules ✓ |
| Structured logging | 17-02-T4 | `logger.error(...)` on exception paths in RetrieveTool and RefinedRetrieveTool ✓ |

No plan introduces patterns CLAUDE.md forbids. No required step skipped.

---

## Dimension 11: Research Resolution — WARNING

RESEARCH.md has `## Open Questions` section (lines 807-817). The heading lacks the required `(RESOLVED)` suffix.

Two questions listed:
1. **ToolContext.req type annotation** — Recommendation: use `GenerationRequest` directly (same module, no circular import). **Resolved in plans:** 17-01-T3 action shows `req: GenerationRequest` in ToolContext definition.
2. **Executor.execute_plan return type after Phase 17** — Recommendation: `list[ToolResult | BaseException]`. **Resolved in plans:** 17-03-T1 action updates the return type annotation explicitly.

Both questions are substantively answered with definitive recommendations in the research document and implemented in plans. No unresolved architectural decision blocks execution. The formal marker is missing.

---

## Dimension 12: Pattern Compliance — PASS

PATTERNS.md exists and maps 9 of 10 new/modified files (docs stub has no analog, explicitly noted). All new service modules reference their analogs in `<read_first>` blocks:

| New File | Analog | Plan Task | Referenced in read_first? |
|----------|--------|-----------|--------------------------|
| services/agent/tools/base.py | services/agent/planner.py lines 1-20 | 17-01-T4 | ✓ |
| services/agent/tools/registry.py | services/agent/executor.py lines 97-104 | 17-01-T5 | ✓ |
| services/agent/tools/retrieve.py | services/agent/tool_executor.py | 17-02-T3 | ✓ |
| services/agent/tools/web_search.py | tool_executor.py (shape only) | 17-02-T5 | ✓ |
| utils/models.py (ToolResult+ToolContext) | utils/models.py ToolCall/ToolPlan | 17-01-T3 | ✓ |
| tests/unit/test_base_tool.py | tests/unit/test_planner.py | 17-01-T1 | ✓ |
| tests/unit/test_tool_registry.py | tests/unit/test_planner.py | 17-01-T2 | ✓ |
| tests/unit/test_retrieve_tool.py | tests/unit/test_executor.py | 17-02-T1 | ✓ |
| docs/agent-architecture.md | no analog (noted in PATTERNS.md) | 17-03-T6 | N/A |

Shared patterns (frozen model, singleton factory, consumer-path mock target, explicit ClassVar annotations) present in all applicable plan actions.

---

## Structured Issues

```yaml
issues:
  - plan: "17-01"
    dimension: task_completeness
    severity: warning
    description: "17-01-T4 <action> step 1 code block shows __init__.py with BaseTool AND ToolRegistry+get_tool_registry imports. The <acceptance_criteria> block explicitly corrects: 'Correction: T4 creates __init__.py with ONLY from services.agent.tools.base import BaseTool'. Executor reading <action> step 1 first would implement incorrect content. Self-correcting but ambiguous at read time."
    task: "17-01-T4"
    fix_hint: "Remove the ToolRegistry + get_tool_registry lines from the code block in <action> step 1. Show only BaseTool import and __all__=['BaseTool']. The full re-export block (with ToolRegistry) belongs in T5 step 2."

  - plan: "17-01, 17-02, 17-03"
    dimension: scope_sanity
    severity: warning
    description: "Plans 17-01 (7 tasks), 17-02 (6 tasks), 17-03 (7 tasks) all exceed the 5-task-per-plan threshold. TDD structure drives the count (2 RED + 3-4 GREEN + 1 REFACTOR). File counts are within bounds (7/5/8, all < 15). Effective complex-implementation tasks per plan is ~4."
    fix_hint: "No action required for execution. If context pressure materializes during execution, split Wave 1/2 GREEN tasks T3-T6 across two plans (e.g., 17-01a: models; 17-01b: BaseTool+Registry)."

  - plan: "17"
    dimension: research_resolution
    severity: warning
    description: "RESEARCH.md §'Open Questions' section (lines 807-817) lacks '(RESOLVED)' suffix on the heading. Both questions are substantively answered by research recommendations and implemented in plans: (1) ToolContext.req uses GenerationRequest — 17-01-T3; (2) execute_plan return type updated to list[ToolResult|BaseException] — 17-03-T1."
    fix_hint: "Change '## Open Questions' to '## Open Questions (RESOLVED)' in 17-RESEARCH.md to satisfy Dimension 11 formal check."
```

---

## Planner's Open Question Verdicts

### 1. validation_concern
**Q:** Are parity tests sufficient to validate that the registry schemas_for output matches the deleted _AGENT_TOOLS?

**A: RESOLVED — three-layer coverage.** The parity gate is validated at:
- 17-01-T2 (Wave 1): Test 13 byte-identical assertion — register `_FakeRetrieveTool`/`_FakeRefineTool` with literal strings from `services/pipeline.py:602-640`; assert `schemas_for("anthropic", ...)` equals hard-coded `_EXPECTED_AGENT_TOOLS`.
- 17-02-T1 (Wave 2): Test 16 byte-identical assertion — same check repeated after real RetrieveTool/RefinedRetrieveTool are registered.
- 17-03-T7 (Wave 3): Final integration smoke test asserts registry output is identical to the deleted literal. This is the Wave 3 deletion gate.

### 2. baseline_drift_check
**Q:** Is the Phase 16 baseline (656 tests, mypy 296, coverage 72.1%) anchored securely at each wave boundary?

**A: RESOLVED — git diff gate per wave.** Each plan's REFACTOR sweep task includes explicit `git diff --stat HEAD~N HEAD -- services/pipeline.py services/agent/executor.py services/agent/tool_executor.py` that MUST show 0 changes to consumer files. The 656-test floor is the explicit regression assertion in 17-01-T7, 17-02-T6, and 17-03-T7. Baseline cannot drift undetected.

### 3. init_export_choice
**Q:** Which `__init__.py` import strategy for triggering tool registration side effects?

**A: RESOLVED — explicit named imports (RESEARCH Decision 3).** Plans implement Option A consistently:
- Wave 1 (17-01): `__init__.py` exports BaseTool + ToolRegistry + get_tool_registry; no side-effect imports yet (no tool modules exist).
- Wave 2 (17-02-T4): adds `from services.agent.tools.retrieve import RetrieveTool, RefinedRetrieveTool, retrieve_impl  # noqa: F401`; triggers registration.
- Wave 2 (17-02-T5): adds `from services.agent.tools.web_search import WebSearchTool  # noqa: F401`.
- Registration is guaranteed at any `import services.agent.tools` call, which happens whenever `services.agent` is imported (via `__init__.py` re-exports).

---

## VERDICT: PASS

All three Phase 17 plans are structurally sound and will achieve the phase goal. AGENT-07 will close upon Wave 3 completion. ROADMAP SC1-5 are each traced to named task IDs. D-01..D-12 are all implemented. RESEARCH pitfalls 1-6 are addressed with defensive tests and guards. Backwards compatibility (656-test floor, mypy 296 baseline) is explicitly gated at each wave.

Three warnings exist — none block execution:
1. **17-01-T4 action/acceptance_criteria self-contradiction:** the correction is explicit in the same task; executor follows acceptance_criteria.
2. **Task count:** TDD structure drives the count; per-task complexity is low; file counts within limits.
3. **RESEARCH.md (RESOLVED) marker:** both questions substantively answered and implemented; formal marker missing only.

Execute `/gsd-execute-phase 17` to proceed. Verify at phase close with `/gsd-verify-work 17` checking ROADMAP SC1-5 grep evidence.
