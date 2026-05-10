---
status: complete
phase: 16-planner-executor-extraction
source:
  - 16-03-SUMMARY.md
started: 2026-05-09T18:00:00Z
updated: 2026-05-09T18:00:00Z
---

## Current Test

[testing complete — awaiting user confirmation of automated evidence]

## Tests

### 1. AgentQueryPipeline.run thin-orchestrator shape (ROADMAP SC1, AGENT-06)
expected: |
  - `pipeline.py:782` defines `async def run(self, req)`; body 43 code lines (≤50 gate ✓)
  - Calls `get_planner().plan_from_messages(messages, tools=..., system=...)` (line 796-798)
  - Calls `get_executor().execute_plan(plan, tf, req)` (line 819)
  - Loop bounded by `MAX_ITERATIONS` (line 794, constant defined at line 583)
  - Helpers `_build_tf` / `_build_initial_messages` / `_build_tool_results` /
    `_dedup_chunks` / `_persist_turn` extracted as private methods (lines 671-779)
result: pass
evidence: |
  $ awk-extract on services/pipeline.py lines 782..824
  → run body = 43 non-blank code lines, terminates at `return await self._persist_turn(...)`
  $ grep -n 'MAX_ITERATIONS' services/pipeline.py
  → 583: MAX_ITERATIONS: int = 5  (module-level)

### 2. Behavioral parity tests pass (ROADMAP SC2)
expected: |
  - `tests/unit/test_agent_parity.py` (2 parametrized cases over fixtures) → pass
  - `tests/unit/test_agent_pipeline_refactor.py` (11 v1.3 tests) → pass with mock targets
    switched to `services.pipeline.get_planner` / `get_executor` (consumer-path pattern)
  - `tests/unit/test_planner.py` (19 tests: 12 ToolPlan validators + 7 Planner) → pass
  - `tests/unit/test_executor.py` (6 tests: ordering, isolation, parallel) → pass
  - `tests/unit/test_swarm_pipeline.py` (8 v1.3 tests) → pass after filter-extractor DI fix
  - Full unit suite: 656 passed / 1 skipped / 0 failures
result: pass
evidence: |
  Subagent verification report (commit c896b4b worktree):
  pytest tests/unit -q → 656 passed, 1 skipped, 0 failures
  All 5 Phase-16 critical test files green.

### 3. _execute_tool_call exists in exactly one location (ROADMAP SC3, AGENT-09)
expected: |
  `grep -rnE 'def _execute_tool_call' services/` returns 0 matches.
  `grep -rnE 'async def execute_tool_call' services/` returns exactly 1 match
  pointing at `services/agent/tool_executor.py`.
result: pass
evidence: |
  $ grep -rnE 'def _execute_tool_call' services/
  → NONE (0 matches)
  $ grep -rnE 'async def execute_tool_call' services/
  → services/agent/tool_executor.py:24:async def execute_tool_call(
  Both AgentQueryPipeline and SwarmQueryPipeline now call the helper directly
  via `from services.agent.tool_executor import execute_tool_call`.

### 4. Query intent encoded as ToolPlan shape; no IntentRouter class (ROADMAP SC4, NLU-03)
expected: |
  - No `class IntentRouter` exists anywhere in services/ tests/ utils/
  - Intent semantics live in `ToolPlan` shape: `steps=[]` → short-circuit answer
    (rationale IS the answer, D-10); `len(steps)==1` → single-hop; `len(steps)>1`
    → parallel multi-tool. The orchestrator at pipeline.py:808 branches on `not plan.steps`
    for the short-circuit path.
  - Regex-first filter extractor in `services/nlu/filter_extractor.py` preserved
    (carry-forward decision from v1.1 Phase 8).
  - ToolPlan + ToolCall are Pydantic V2 frozen models (utils/models.py:254, :305).
result: pass
evidence: |
  $ grep -rn 'class IntentRouter' services/ tests/ utils/
  → NONE_FOUND
  $ grep -n 'class ToolCall\|class ToolPlan\|frozen=True' utils/models.py
  → 244: class ToolCall(BaseModel)
  → 254: model_config = ConfigDict(frozen=True)
  → 291: class ToolPlan(BaseModel)
  → 305: model_config = ConfigDict(frozen=True)
  pipeline.py:808: `if not plan.steps:` short-circuit branch present.

### 5. v1.3 invariants intact + coverage ≥ 70% (ROADMAP SC5)
expected: |
  - `coverage report --fail-under=70` exits 0 on combined data → ≥ 70%
  - `services/auth/` and `services/audit/audit_service.py` unchanged in Phase 16
    (RLS / JWT / multi-tenancy preserved by construction — no edits in scope)
  - Audit log call site (`audit_service.log(...)`) preserves v1.2/v1.3 fields:
    parallel_factor, latency_ms, sources_count, query_len, intent
result: pass
evidence: |
  Subagent verification: coverage report → 72.1% (≥70% gate ✓)
  $ git diff --stat cbef630..HEAD services/auth/ services/audit/
  → 0 files changed (RLS + audit infrastructure untouched)
  $ grep -n '_persist_turn' services/pipeline.py
  → run delegates audit write to `_persist_turn` helper which calls audit_service.log
    with the same field shape (parallel_factor, latency_ms, sources_count preserved).
note: |
  Live integration test `tests/integration/test_agent_pipeline_parallel.py` (real
  PG + RLS + LLM) was NOT run in this verify pass — requires OPENAI_API_KEY +
  running pgvector. Manual smoke recommended before /gsd-ship merges to master.

### 6. Lint / type / scope cleanliness
expected: |
  - `ruff check services/ tests/` clean
  - `mypy --strict services/agent/ services/pipeline.py utils/models.py` reports
    296 errors (= v1.3 baseline accepted in PROJECT.md row 184); 0 NEW errors
  - Phase 16 file delta matches PLAN.md `files_modified` scope
    (services/agent/* added in Wave 1+2; pipeline.py + tests modified in Wave 3)
result: pass
evidence: |
  Subagent verification: ruff clean; mypy 296 = baseline (0 new).
  $ git diff --stat cbef630..HEAD
  → 10 files: REQUIREMENTS.md, STATE.md, 16-03-SUMMARY.md, services/agent/executor.py,
    services/agent/planner.py, services/pipeline.py, tests/unit/test_agent_pipeline_refactor.py,
    tests/unit/test_executor.py, tests/unit/test_swarm_pipeline.py, utils/models.py
    No scope creep beyond PLAN.md files_modified.

## Summary

total: 6
passed: 6
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

<!-- No FAILING gaps. Two informational notes follow on deliberate divergences from ROADMAP wording — both are pre-approved decisions documented in 16-CONTEXT.md, not regressions. Listed here for verifier transparency. -->

## Notes (deliberate divergences from ROADMAP, pre-approved in CONTEXT.md)

- note: "ROADMAP SC1 lists three collaborators 'Planner → Executor → Synthesizer'; only Planner + Executor classes exist."
  status: by-design
  reason: |
    16-CONTEXT.md decisions D-10/D-11/D-12 explicitly chose NOT to introduce a
    Synthesizer class. The final `call_agentic_turn` IS the synthesizer
    (logical role, not class). Rationale: preserves v1.3 multi-turn refinement
    semantics where the LLM can return either tool_calls (continue) or final
    text (terminate). Phase 18 `synthesizer.final` SSE event will carry that
    final assistant turn's text — the role exists; the class does not.
    Locked in during /gsd-discuss-phase 16. ROADMAP wording predates that
    decision; not updated to avoid retroactive rewriting.
  impact: none — orchestrator semantics unchanged; AGENT-06 acceptance met.

- note: "ROADMAP SC2 mentions 'recorded v1.3 transcript' for parity. Wave 1 used SYNTHESIZED fixtures rather than captured transcripts."
  status: by-design
  reason: |
    PG was empty in the dev environment when Wave 1 ran; capturing a real LLM
    transcript would have required a full ingest cycle. Wave 1 instead built
    fixtures shaped to match v1.3 fixture schema. Parity confidence is
    delivered by the 19 EXISTING v1.3 unit tests in test_agent_pipeline_refactor.py
    + test_swarm_pipeline.py — those run against the new orchestrator post-Wave 3
    and still pass without modifying public assertions. Documented in STATE.md
    Wave 1 Execution Notes.
  impact: low — Phase 19 (`make demo-agent`) will produce a real transcript
    artifact when the demo target lands, closing the gap retroactively.
