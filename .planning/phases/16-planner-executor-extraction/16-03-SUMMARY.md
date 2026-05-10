---
phase: 16-planner-executor-extraction
plan: 03
subsystem: api
tags: [python, asyncio, agentic, planner, executor, tool-use, pipeline, rag]

# Dependency graph
requires:
  - phase: 16-01
    provides: services/agent/tool_executor.execute_tool_call extracted, _execute_tool_call delegate methods added
  - phase: 16-02
    provides: Planner, Executor, ToolPlan model built + unit tested in isolation

provides:
  - "AgentQueryPipeline.run rewritten as 43-line thin orchestrator delegating to Planner+Executor"
  - "MAX_ITERATIONS=5 promoted to module-level constant (AGENT-06)"
  - "Both _execute_tool_call delegate methods deleted from AgentQueryPipeline and SwarmQueryPipeline (AGENT-09)"
  - "ToolPlan carries raw_assistant_msg and stop_reason for orchestrator use"
  - "Executor.execute_plan uses return_exceptions=True for per-tool error isolation"
  - "Filter extractor stored as instance attribute in both pipeline classes (testability)"

affects: [phase-17, phase-18, phase-19, test-infra]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Consumer-path monkeypatching: patch services.pipeline.get_planner / get_executor in unit tests (not the class method)"
    - "Thin orchestrator: AgentQueryPipeline.run delegates all LLM planning to Planner, all tool execution to Executor"
    - "Helper method extraction: _build_tf, _build_initial_messages, _build_tool_results, _dedup_chunks, _persist_turn"

key-files:
  created:
    - ".planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md"
  modified:
    - "services/pipeline.py"
    - "services/agent/planner.py"
    - "services/agent/executor.py"
    - "utils/models.py"
    - "tests/unit/test_agent_pipeline_refactor.py"
    - "tests/unit/test_executor.py"
    - "tests/unit/test_swarm_pipeline.py"

key-decisions:
  - "ToolPlan.raw_assistant_msg and .stop_reason added (frozen model with defaults) so orchestrator can append assistant turn to messages without a separate AgenticTurn reference"
  - "Executor.execute_plan switched to return_exceptions=True (returning BaseException | tuple per step) to preserve v1.3 per-tool error isolation; orchestrator builds is_error=True tool_results"
  - "Filter extractor stored as self._filter_extractor in both AgentQueryPipeline and SwarmQueryPipeline for unit testability (no live LLM call in unit tests)"
  - "MAX_ITERATIONS promoted to module-level constant (not class attribute) per AGENT-06/CONTEXT.md D-12"
  - "Planner.plan_from_messages passes messages= as keyword arg to preserve test assertion on await_args_list[N].kwargs['messages']"
  - "test_execute_plan_propagates_exceptions renamed to test_execute_plan_returns_exception_as_value to accurately describe new return_exceptions=True semantics"

patterns-established:
  - "Thin orchestrator pattern: AgentQueryPipeline.run is 43 lines, with helpers for tf-build, message-init, tool-result-build, dedup, and persist"
  - "consumer-path patch: test doubles injected via monkeypatch.setattr('services.pipeline.get_planner', ...) matching Phase 13+15 conventions"

requirements-completed: [AGENT-06, AGENT-09, NLU-03]

# Metrics
duration: 45min
completed: 2026-05-09
---

# Phase 16 Plan 03: Seam Swap — AgentQueryPipeline.run delegates to Planner+Executor (Wave 3, AGENT-06/09 close)

**AgentQueryPipeline.run shrunk from ~180 lines to 43 lines; both _execute_tool_call delegate methods deleted; Planner+Executor wired end-to-end with return_exceptions=True error isolation**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-05-09T17:40:00Z
- **Completed:** 2026-05-09T18:25:00Z
- **Tasks:** 4
- **Files modified:** 7

## Accomplishments

- Rewrote `AgentQueryPipeline.run` to 43 lines (from ~180); helpers extracted for tf-build, message-init, tool-result-build, dedup, and persist+audit
- Deleted both `_execute_tool_call` delegate methods (AgentQueryPipeline + SwarmQueryPipeline) — AGENT-09 acceptance verified (`grep` → 0 matches)
- All 11 `test_agent_pipeline_refactor.py` tests pass with consumer-path patches on `get_planner`/`get_executor`
- Full unit suite: 656 passed, 1 skipped; coverage 72.1% (floor 70% passed); ruff clean; mypy 296 errors (same as v1.3 baseline — 0 new)

## Task Commits

1. **Task T1: Replace AgentQueryPipeline.run body + supporting changes** — `f69a4b0` (feat)
2. **Task T2: Delete _execute_tool_call delegates + test_executor/swarm fixture updates** — `47451c9` (feat)
3. **Task T3: Update test_agent_pipeline_refactor.py mock targets** — `97c7560` (feat)
4. **Task T4: ruff fix — remove unused AgenticTurn/ToolCall imports** — `989177a` (feat)

## Files Created/Modified

- `services/pipeline.py` — AgentQueryPipeline.run rewritten (43 lines); helper methods extracted; _execute_tool_call (both classes) deleted; SwarmQueryPipeline callsite updated; _filter_extractor stored as instance attr in both classes; MAX_ITERATIONS module-level; AgenticTurn/ToolCall imports removed (unused after refactor)
- `services/agent/planner.py` — _turn_to_plan populates raw_assistant_msg + stop_reason in all ToolPlan paths; plan_from_messages passes messages= as keyword arg
- `services/agent/executor.py` — execute_plan uses asyncio.gather(return_exceptions=True); return type updated to list[tuple | BaseException]; per-step error logging added
- `utils/models.py` — ToolPlan gains raw_assistant_msg (dict[str, Any]) and stop_reason (str) fields with defaults
- `tests/unit/test_agent_pipeline_refactor.py` — mock_pipeline fixture accepts monkeypatch; patches get_planner/get_executor at consumer paths; _filter_extractor mocked via ExtractionResult stub
- `tests/unit/test_executor.py` — test_execute_plan_propagates_exceptions renamed + rewritten to assert BaseException returned as value (not raised)
- `tests/unit/test_swarm_pipeline.py` — mock_pipeline fixture adds _filter_extractor mock

## Decisions Made

- **ToolPlan model extension**: Added `raw_assistant_msg` and `stop_reason` to `ToolPlan` with defaults so the orchestrator can append the assistant message verbatim and log max_tokens warnings without keeping a separate `AgenticTurn` reference. Frozen model with `Field(default_factory=dict)` is non-breaking.
- **return_exceptions=True in Executor**: Old v1.3 code used `asyncio.gather(..., return_exceptions=True)` directly. New Executor inherits this behavior explicitly. Orchestrator (`_build_tool_results`) handles `BaseException` entries as `is_error=True` tool results.
- **Filter extractor as instance attribute**: Moving `get_filter_extractor()` from module-level call in `run()` to `self._filter_extractor` stored in `__init__` allows unit tests to inject a mock without patching the global. Applied to both AgentQueryPipeline and SwarmQueryPipeline.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Executor.execute_plan did not preserve per-tool error isolation**
- **Found during:** T1 (analyzing test_agent_pipeline_refactor.py test 4)
- **Issue:** Original `Executor.execute_plan` used `asyncio.gather` WITHOUT `return_exceptions=True` and re-raised on any failure. Old AgentQueryPipeline.run used `return_exceptions=True` directly. Without fixing Executor, test 4 (error → is_error=True) would break.
- **Fix:** Changed Executor.execute_plan to use `asyncio.gather(*coros, return_exceptions=True)`; updated return type to `list[tuple | BaseException]`; added per-step error logging.
- **Files modified:** `services/agent/executor.py`, `tests/unit/test_executor.py`
- **Verification:** All 46 relevant tests pass; test 4 (is_error=True) verified
- **Committed in:** f69a4b0 (T1), 47451c9 (T2)

**2. [Rule 2 - Missing Critical] Filter extractor not injectable in SwarmQueryPipeline tests**
- **Found during:** T2 (running test_swarm_pipeline.py in worktree with no LLM proxy)
- **Issue:** `SwarmQueryPipeline.run()` called `get_filter_extractor()` as a module-level global. Tests had no way to mock it without a working LLM. 8 swarm tests failing with AuthenticationError.
- **Fix:** Added `self._filter_extractor = get_filter_extractor()` to SwarmQueryPipeline.__init__; updated `run()` to use `self._filter_extractor.extract()`; added ExtractionResult mock to test fixture.
- **Files modified:** `services/pipeline.py`, `tests/unit/test_swarm_pipeline.py`
- **Verification:** 8 swarm tests pass without live LLM
- **Committed in:** f69a4b0 (T1), 47451c9 (T2)

**3. [Rule 1 - Bug] test_execute_plan_propagates_exceptions tested wrong behavior**
- **Found during:** T4 (full test suite run after Executor.execute_plan change)
- **Issue:** test was asserting RuntimeError raised — old behavior before return_exceptions=True fix.
- **Fix:** Renamed to test_execute_plan_returns_exception_as_value; updated to assert BaseException returned as list entry with both steps present.
- **Files modified:** `tests/unit/test_executor.py`
- **Verification:** test passes; all 46 relevant tests pass
- **Committed in:** 47451c9 (T2)

---

**Total deviations:** 3 auto-fixed (2 Rule 1 - Bug, 1 Rule 2 - Missing Critical)
**Impact on plan:** All auto-fixes necessary for correctness and testability. No scope creep.

## Issues Encountered

- Worktree environment has no LLM proxy (unlike main project dir), causing filter extractor calls to fail with AuthenticationError in unit tests. Resolved by storing filter extractor as instance attribute in both pipeline classes.

## Known Stubs

None — all paths are fully wired.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundaries introduced. AgentQueryPipeline.run is a refactor of existing behavior.

## Next Phase Readiness

- AGENT-06 (thin orchestrator), AGENT-09 (shared execute_tool_call), NLU-03 (planner rationale language) all close with this plan
- Phase 16 is complete; `/gsd-verify-work 16` can now verify parity + coverage + grep evidence
- Phase 17 (streaming SSE traces) can build on the Planner/Executor boundary — `planner.plan_from_messages` is the natural emission point for `planner.plan` SSE events

---
*Phase: 16-planner-executor-extraction*
*Completed: 2026-05-09*
