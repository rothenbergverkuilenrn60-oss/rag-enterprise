---
phase: 22-per-module-70-coverage-lift
plan: "01"
subsystem: tests
tags: [coverage, pipeline, tdd, unit-tests]
dependency_graph:
  requires: [22-00]
  provides: [pipeline-coverage-gte-70]
  affects: [services/pipeline.py]
tech_stack:
  added: []
  patterns: [consumer-path-monkeypatch, AsyncMock, pytest-asyncio, coverage.py]
key_files:
  created:
    - tests/unit/test_pipeline_coverage.py
  modified: []
decisions:
  - "Wave-2 backfill targeted QueryPipeline._run_query (happy path + 3 branch variants) and SwarmQueryPipeline._synthesize to close the 67%->70% gap; final coverage 79.9%"
  - "monkeypatching _persist_turn on AgentQueryPipeline instance avoids real memory/audit I/O in error-branch tests while keeping the outer run() loop exercised"
metrics:
  duration: "~25 min"
  completed: "2026-05-10"
  tasks_completed: 2
  files_created: 1
---

# Phase 22 Plan 01: Pipeline Coverage Lift Summary

Coverage tests for `services/pipeline.py` that lift per-module line coverage from 66.2% to 79.9%.

## One-liner

SC1-prescribed branch tests + QueryPipeline backfill lift pipeline.py from 66.2% to 79.9% line coverage via 24 new unit tests.

## Final Coverage

| Module | Before | After |
|--------|--------|-------|
| `services/pipeline.py` | 66.2% | 79.9% |

Gate: `coverage report --include=services/pipeline.py --fail-under=70` exits 0.

## Test Inventory

**Total: 24 tests** in `tests/unit/test_pipeline_coverage.py` (865 lines)

**SC1-prescribed branches (CF-07):**

| Section | Tests |
|---------|-------|
| `_dedup_chunks` | collapses duplicates, preserves order, empty input |
| `_build_initial_messages` | basic (query only), with short-term history |
| `AgentQueryPipeline.run` errors | planner APIError graceful response; executor raises (BaseException); tool is_error=True continues; NotImplementedError fallback |
| `AgentQueryPipeline.run_streaming` | planner APIError emits SynthesizerFinalEvent; NotImplementedError emits SynthesizerFinalEvent; terminal plan emits SynthesizerFinalEvent with answer; emits PlannerPlanEvent on step plan |
| `SwarmQueryPipeline` synthesis | synthesis composes peer answers; no verifier hop; N=1 delegates to agent pipeline; sub-agent exception produces error marker |

**Wave-2 backfill:**

| Section | Tests |
|---------|-------|
| `QueryPipeline._run_query` | happy path end-to-end; tenant permission denied; CHITCHAT intent uses LLM.chat; pre-query rule BLOCK |
| `SwarmQueryPipeline._synthesize` | all-failed graceful degradation; normal path calls LLM |
| Singletons | `get_swarm_pipeline` singleton |

## Wave-2 Backfill Scope

After Task 1, pipeline.py was at 67.0% (unit-only). Added 7 tests covering:
- `QueryPipeline._run_query` main path (lines 296-465 region)
- `_synthesize` branches (lines 1167-1188 region)
- `get_swarm_pipeline` singleton (lines 1302-1304)

Final: 79.9% -- well above 70% minimum.

## Lock Confirmation

| Lock | Status |
|------|--------|
| CF-01: zero production .py changes | PASS -- no .py files in services/ modified |
| CF-02: all mocks at `services.pipeline.<dep>` | PASS -- 31 consumer-path setattr calls; zero anthropic./openai./services.agent. mocks |
| CF-04: no `# pragma: no cover` additions | PASS -- git diff services/pipeline.py shows 0 lines |
| CF-06: diff-cover >=80% | PASS -- test file is 100% new code |

## Deviations from Plan

**1. [Rule 1 - Bug] MemoryContext requires additional positional args**
- Found during: Task 1 initial test run
- Issue: `MemoryContext(short_term=[], long_term_facts=[], user_profile=None)` fails -- requires `session_id`, `user_id`, `tenant_id`
- Fix: Added those fields to `_make_mem_ctx()` helper
- Files modified: `tests/unit/test_pipeline_coverage.py` only

**2. [Rule 1 - Bug] QueryIntent.QA does not exist**
- Found during: Wave-2 backfill
- Issue: `QueryIntent.QA` used in test setup -- correct value is `QueryIntent.FACTUAL`
- Fix: Replaced with `QueryIntent.FACTUAL`
- Files modified: `tests/unit/test_pipeline_coverage.py` only

**3. [Rule 1 - Bug] ToolSpanStartEvent field mismatch**
- Found during: Task 1 streaming test
- Issue: Used `tool_call_id` and `tool_name` which do not exist; correct are `name`, `span_id`; `ToolSpanEndEvent` uses `latency_ms`, `chunk_count`, `is_error`, `content_preview`
- Fix: Corrected to actual Pydantic model fields
- Files modified: `tests/unit/test_pipeline_coverage.py` only

## Known Stubs

None -- all 24 tests exercise real code paths via consumer-path monkeypatching.

## Threat Flags

None -- no new network endpoints, auth paths, or schema changes introduced.

## Self-Check: PASSED

- `tests/unit/test_pipeline_coverage.py` exists: FOUND
- Commit eb9cf37 exists: FOUND
- `coverage report --include=services/pipeline.py --fail-under=70` exits 0: CONFIRMED (79.9%)
- 24 tests pass: CONFIRMED
- CF-01 zero production py changes: CONFIRMED
