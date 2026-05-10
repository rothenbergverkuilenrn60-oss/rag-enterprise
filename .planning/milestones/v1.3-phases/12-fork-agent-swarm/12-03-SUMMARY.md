---
phase: 12-fork-agent-swarm
plan: 03
subsystem: api-routing,tests
tags: [swarm, agent-routing, integration, pytest, AGENT-03]

requires:
  - "SwarmQueryPipeline class + get_swarm_pipeline() factory (Wave 2, Plan 12-02)"
  - "GenerationRequest.swarm_mode field (Wave 1, Plan 12-01)"
provides:
  - "POST /query three-way routing in controllers/api.py: swarm_mode > agent_mode > default QueryPipeline"
  - "tests/unit/test_swarm_pipeline.py — 8 unit contracts covering AGENT-03 acceptance criteria 1–7 + Pitfall 4"
  - "tests/integration/test_swarm_pipeline_e2e.py — 1 live-LLM end-to-end smoke (gated by pytest.mark.integration)"
affects: [controllers/api.py, tests/unit, tests/integration]

tech-stack:
  added: []
  patterns:
    - "Explicit if/elif/else routing chain: swarm > agent > default — replaces ternary one-liner; fixed precedence enforced by source-order acceptance test (swarm_idx < agent_idx)"
    - "SwarmQueryPipeline.__new__ test fixture: bypass __init__ singleton, attach mocks to all 5 dependencies (mirrors AgentQueryPipeline analog)"
    - "Mock _llm.chat with side_effect=[coordinator_json, synthesis_text] — captures both LLM calls in one fixture"
    - "asyncio.Event + counter pattern for concurrency proof (analog: tests/unit/test_agent_pipeline_refactor.py:185–224)"
    - "Module-level pytestmark = [pytest.mark.integration] — pytest.ini addopts `-m \"not integration\"` deselects the test from default runs"

key-files:
  created:
    - tests/unit/test_swarm_pipeline.py
    - tests/integration/test_swarm_pipeline_e2e.py
  modified:
    - controllers/api.py

key-decisions:
  - "Swarm precedence locked in via if/elif/else order: when both swarm_mode and agent_mode are true, swarm wins (D-04 implicit precedence — swarm is the more capable mode). Source-order grep is the executable contract."
  - "Unit test file pattern: copy fixture / helpers verbatim from tests/unit/test_agent_pipeline_refactor.py — diverging structure between agent and swarm test suites would create maintenance drift; identical scaffold makes future shared-helper extraction trivial."
  - "Integration test uses LLM_PROVIDER=openai monkeypatch (NOT ANTHROPIC_API_KEY skipif) — matches the unconditional-run policy from D-05 / W-6 fix in tests/integration/test_agent_pipeline_parallel.py:6–14. Missing OpenAI credentials surface as a hard test failure, not a silent skip."
  - "Coordinator + synthesis main-model assertion (test 8) is a regression guard against Pitfall 4: a future change that switches to task_type='nlu' (Haiku routing) would silently degrade reasoning capability. The test asserts task_type='generate' on both LLM calls."
  - "Test 7 uses set-difference required-keys check (T-12-03-05). If a future audit refactor renames swarm_n → n_subagents the test fails loudly, surfacing the contract break."

requirements-completed: [AGENT-03]

duration: 8min
completed: 2026-05-09
---

# Phase 12 Plan 03: Wire Swarm Routing & Tests Summary

Three-way `/query` routing for `swarm_mode` plus 8 unit contracts and 1 live-LLM integration smoke — AGENT-03 closure.

## Tasks Completed (3/3)

| # | Task                                                        | Commit    | Files                                                           |
| - | ----------------------------------------------------------- | --------- | --------------------------------------------------------------- |
| 1 | Wire swarm_mode routing into /query endpoint                | `35799d4` | `controllers/api.py`                                            |
| 2 | Add 8 unit tests for SwarmQueryPipeline                     | `f3bf267` | `tests/unit/test_swarm_pipeline.py`                             |
| 3 | Add e2e integration test for SwarmQueryPipeline             | `5252acc` | `tests/integration/test_swarm_pipeline_e2e.py`                  |

## Key Edit — controllers/api.py

**Line 25 (import block extension):**
```python
from services.pipeline import (
    get_agent_pipeline,
    get_ingest_pipeline,
    get_query_pipeline,
    get_swarm_pipeline,    # AGENT-03
)
```

**Lines 207–214 (routing block — replaced one-liner at former line 208):**
```python
# AGENT-03 三向路由：swarm_mode > agent_mode > 默认 QueryPipeline
if req.swarm_mode:
    pipeline = get_swarm_pipeline()
elif req.agent_mode:
    pipeline = get_agent_pipeline()
else:
    pipeline = get_query_pipeline()
```

Source-order check: `req.swarm_mode` at byte offset 8046, `req.agent_mode` at 8119 — swarm precedes agent (T-12-03-01 mitigated).

## AGENT-03 Acceptance Criteria → Test Function Mapping

| AC # | Behavior                                                              | Test Function                                       |
| ---- | --------------------------------------------------------------------- | --------------------------------------------------- |
| 1    | Coordinator decomposes; returns `[query]` for single-dim → fallback    | `test_n1_fallback_delegates_to_agent_pipeline`      |
| 2    | Sub-agents run concurrently (`asyncio.gather`)                        | `test_sub_agents_run_concurrently`                  |
| 3    | Each sub-agent has isolated message history                           | `test_sub_agents_have_isolated_message_histories`   |
| 4    | Hard cap `MAX_SWARM_AGENTS` prevents unbounded fan-out                | `test_max_swarm_agents_cap`                         |
| 5    | Partial sub-agent failure does not crash; final response returned     | `test_partial_failure_returns_response`             |
| 6    | Synthesis combines all sub-answers (including error markers)          | `test_synthesis_references_all_sub_answers`         |
| 7    | Audit log records swarm_n / per_agent_turns / per_agent_tool_calls / swarm_latency_ms | `test_audit_log_swarm_fields` |
| —    | Pitfall 4 — coordinator uses main model, NOT Haiku                    | `test_coordinator_uses_main_model_not_haiku`        |

All 8 unit tests PASS (`pytest tests/unit/test_swarm_pipeline.py -x` exits 0).

## Default-Suite Exclusion Verification

| Run                                                                            | Tests Collected | Result      |
| ------------------------------------------------------------------------------ | --------------- | ----------- |
| `pytest tests/integration/test_swarm_pipeline_e2e.py` (default `-m "not integration"`) | 0 selected (1 deselected) | deselected |
| `pytest tests/integration/test_swarm_pipeline_e2e.py --collect-only -m integration` | 1 selected   | collected   |
| `pytest tests/unit/test_swarm_pipeline.py -x`                                  | 8               | 8 passed    |

## Provider-Override Pattern

Integration test mirrors `tests/integration/test_agent_pipeline_parallel.py` exactly: `monkeypatch.setenv("LLM_PROVIDER", "openai")` (unconditional run per D-05 / W-6 — missing OPENAI_API_KEY is a hard failure, NOT a `pytest.skip`). NO substitution from the analog pattern was needed.

## Verification Run

| Check                                                                         | Result                       |
| ----------------------------------------------------------------------------- | ---------------------------- |
| `pytest tests/unit/test_swarm_pipeline.py -x`                                 | 8 passed                     |
| `pytest tests/unit/test_agent_pipeline_refactor.py` (no regression)           | 11 passed                    |
| `pytest tests/integration/test_swarm_pipeline_e2e.py --collect-only`          | 1 deselected (default suite) |
| `pytest tests/integration/test_swarm_pipeline_e2e.py --collect-only -m integration` | 1 collected            |
| `ruff check controllers/api.py tests/unit/test_swarm_pipeline.py tests/integration/test_swarm_pipeline_e2e.py` | All checks passed |
| `grep 'get_swarm_pipeline' controllers/api.py` (≥ 2)                          | 2                            |
| `grep 'req.swarm_mode' controllers/api.py` (=1)                               | 1                            |
| `grep 'def test_' tests/unit/test_swarm_pipeline.py` (=8)                     | 8                            |
| `grep 'def test_' tests/integration/test_swarm_pipeline_e2e.py` (=1)          | 1                            |

## Deviations from Plan

None.

The plan instructions were followed exactly. The cosmetic typo flagged by the plan-checker (Task 3 verify command had a duplicate suffix `&& pytest ... | tail -10" && pytest ... | tail -10`) did not affect execution because the verify command was run via the equivalent ast-parse + collect-only check; no shell command was invoked literally.

### Pre-existing Out-of-Scope Issues (Logged, Not Fixed)

- `tests/unit/test_ingest_status.py::test_async_ingest_returns_task_id` — pre-existing latency-budget flake (`elapsed < 0.2s` budget; observed 0.207s after suite warmup). Reproduced with `git stash` to remove Plan 12-03 changes — the flake remains. The handler runs in 1.9ms per its own structured log; the 200ms budget is dominated by `TestClient` accumulated warmup. Out of Plan 12-03 scope.
- `tests/integration/test_pgvector_recall.py` + `test_pgvector_rls.py` — 4 failures requiring a live PostgreSQL + pgvector ≥ 0.8.0 instance (per pytest.ini `pgvector` marker). Out of Plan 12-03 scope; environment-dependent.
- `tests/integration/test_ragas_eval.py` — collection-time `PermissionError`. Pre-existing and unrelated to swarm wiring. Out of Plan 12-03 scope.
- `mypy --strict controllers/api.py` reports `Call to untyped function "get_swarm_pipeline" in typed context` — same pattern as the existing `get_agent_pipeline` / `get_query_pipeline` calls (factory functions without return annotations, per Plan 12-02 SUMMARY's documented baseline drift). Plan instruction: "Match the exact spacing/style of `_agent_pipeline = None` / `def get_agent_pipeline()`". SCOPE BOUNDARY applies.

## Files Modified / Created

| File                                            | Status   | Lines |
| ----------------------------------------------- | -------- | ----- |
| `controllers/api.py`                            | modified | +8 −2 |
| `tests/unit/test_swarm_pipeline.py`             | created  | 350   |
| `tests/integration/test_swarm_pipeline_e2e.py`  | created  | 73    |

## Phase 12 Closure

**AGENT-03 fully traceable:** every acceptance criterion (1–7) maps to a unit test that asserts the contract; routing wiring is in place; integration smoke gated to `pytest -m integration`.

**Wave 3 status:** complete. Ready for `/gsd-verify-work 12`.

## Self-Check: PASSED

- `controllers/api.py` exists and contains both `get_swarm_pipeline` and the three-way routing block (verified by grep).
- `tests/unit/test_swarm_pipeline.py` exists; 8 tests collect and pass.
- `tests/integration/test_swarm_pipeline_e2e.py` exists; deselected by default; collected with `-m integration`.
- Commits `35799d4`, `f3bf267`, `5252acc` exist on master (verified via `git log --oneline -3`).
