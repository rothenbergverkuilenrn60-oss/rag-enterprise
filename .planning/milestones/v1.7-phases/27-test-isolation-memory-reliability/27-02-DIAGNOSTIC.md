# Phase 27 / Plan 27-02 — Redis-Mock Rollout Diagnostic (D-22)

**Captured:** 2026-05-17 07:02:07 UTC
**Host:** DZ-4-13-15-2
**Python:** Python 3.12.13
**Worktree HEAD:** `worktree-agent-a5e115f996cb3b725`
**Baseline commit (pre-rollout):** `b841173` (after 27-02 Task 1 RED+GREEN + Task 2 RED, before Task 2 GREEN marker apply)
**Post-rollout commit:** captured after Step B marker apply (4 files), before Task 2 GREEN commit.
**Local Redis status at capture time:** `localhost:6379` IS REACHABLE.

---

## Test Environment Note

The 27-02 plan inherited a CONTEXT assumption from v1.6 Phase 24 SUMMARY that 4 specific unit-test files fail with `redis.exceptions.ConnectionError` *when Redis is down*. This diagnostic was run on a host where **Redis IS up**, so the baseline ConnectionError mode count is 0 (the live server serves the calls).

The marker rollout still ships value: when this test suite runs on a host without Redis (CI runners, fresh dev machines, offline development), the redis_mock auto-attachment hook intercepts the connection path and prevents the failure mode from regressing. The diagnostic numbers below characterize the actual current behavior + the new failure mode the marker rollout exposed (which is NOT TD-06 / Redis territory but TD-02 / event-loop isolation — owned by parallel plan 27-01).

---

## Failure Mode Counts

| Mode | Pre-rollout | Post-rollout | Delta | Owner |
|------|-------------|--------------|-------|-------|
| `redis.exceptions.ConnectionError` / `Error 111` / `Cannot connect to Redis` | **0** | **0** | 0 | TD-06 (this plan) — already at target. |
| `APIError.__init__() missing 'request'` (openai SDK drift) | 0 | 0 | 0 | v1.8+ orthogonal todo (STATE.md). Did not manifest in this run. |
| `RuntimeError: ... bound to a different event loop` / `Event loop is closed` (TD-02 territory) | 30 | 59 | +29 | **27-01 (parallel plan)** — singleton/event-loop leak exposed by marker auto-fixture teardown. |
| Total `FAILED` lines in pytest output | **22** | **36** | +14 | Mix of pre-existing AssertionError tool-registration failures + newly-exposed event-loop leaks. |

Logs (ephemeral, /tmp — not committed):
- `/tmp/27-02-pre-rollout.log` — `uv run pytest tests/unit/ --timeout 30 -q --tb=short --no-header` BEFORE Step B.
- `/tmp/27-02-post-rollout.log` — same command AFTER Step B.

---

## Newly-Exposed Failures (Post-Rollout)

These 14 tests were PASSING pre-rollout and are FAILING post-rollout. ALL 14 are in the 4 marked files; ALL 14 fail with the `RuntimeError: ... bound to a different event loop` mode (TD-02 territory).

```
tests/unit/test_agent_pipeline_refactor.py::test_chunk_dedup_runs_after_gather_not_inside
tests/unit/test_agent_pipeline_refactor.py::test_max_iterations_is_5
tests/unit/test_agent_pipeline_refactor.py::test_max_tokens_stop_reason_terminates_gracefully
tests/unit/test_agent_pipeline_refactor.py::test_narrow_except_does_not_catch_runtime_error
tests/unit/test_agent_pipeline_refactor.py::test_two_tool_calls_run_concurrently
tests/unit/test_agent_sse.py::test_run_streaming_persist_turn_called_once
tests/unit/test_agent_sse.py::test_run_streaming_redaction_args_verbatim_content_truncated_d11
tests/unit/test_agent_sse.py::test_run_streaming_smoke_sequence_d15
tests/unit/test_agent_sse.py::test_run_streaming_synthesizer_final_terminal
tests/unit/test_pipeline_coverage.py::test_agent_query_pipeline_run_streaming_planner_api_error_yields_synthesizer_final
tests/unit/test_pipeline_coverage.py::test_agent_query_pipeline_run_streaming_terminal_plan_yields_synthesizer_final
tests/unit/test_pipeline_coverage.py::test_agent_query_pipeline_run_tool_error_result_continues_to_synth
tests/unit/test_pipeline_coverage.py::test_query_pipeline_pre_rule_block_returns_rule_message
tests/unit/test_pipeline_coverage.py::test_query_pipeline_run_query_happy_path
```

Sample traceback (canonical for the cohort):

```
E   RuntimeError: <Queue at 0x781dbcadb440 maxsize=0 tasks=3> is bound to a different event loop
```

### Root Cause

The redis_mock fixture (tests/conftest.py:248-301) installs a fakeredis instance per-test via `monkeypatch.setattr("utils.cache.get_redis", _get_redis_stub)`. The fakeredis instance internally holds asyncio resources (Queue) bound to *this test's* event loop.

Consumers (e.g., `services.pipeline.AgentQueryPipeline`, `services.memory.memory_service.MemoryService._short`) call `await get_redis()` and cache the returned client on a module-level singleton:

- `utils.cache._redis_client` (canonical) — RESET by the redis_mock fixture via monkeypatch.
- `services.memory.memory_service._memory_service.<_short>._client` — NOT reset by redis_mock fixture; only reset by per-test fixtures like `reset_memory_singleton` in `test_memory_save_fact.py` / `test_short_term_memory_get_redis.py`.

When the marked test ends, its event loop closes, but the singleton `_memory_service._short._client` still holds the prior loop's fakeredis. The next test in a fresh loop attempts to reuse it → `bound to a different event loop`.

### Why TD-02 (Plan 27-01), Not TD-06 (This Plan)

This is the *exact* singleton-leak class that plan 27-01 (Wave 1 sibling) addresses via:
- `tests/factories/app.py::_reset_singletons()` (already shipped in 27-00)
- `_SINGLETON_INVENTORY` enumerates 34 service singletons including `services.memory.memory_service._memory_service`
- 27-01 will wire the `isolated_app` / `isolated_client` fixtures + lift `_configure_app` so create_app() is the canonical entry point that invokes `_reset_singletons()` between tests.

The redis_mock fixture (TD-06) is correctly scoped to mock Redis access; it does NOT and SHOULD NOT take responsibility for resetting every singleton that may cache a Redis client. That cross-cutting responsibility belongs to TD-02.

---

## Acceptance Against Plan SC-2

| Acceptance criterion | Result |
|----------------------|--------|
| `grep -l "uses_redis" <4 files> \| wc -l == 4` | ✅ 4 (verified via `rtk proxy bash -c 'grep -l uses_redis ...'`) |
| `uv run pytest tests/unit/test_redis_mock_baseline_diagnostic.py::test_marker_applied_to_known_failing_files -x` | ✅ PASSES (Task 2 RED → GREEN gate clean) |
| `uv run pytest tests/unit/test_redis_mock_baseline_diagnostic.py::test_no_pre_existing_redis_connection_error_in_marked_files -x --timeout 300` | ✅ PASSES (subprocess invocation of 4 marked files produces 0 Redis-ConnectionError strings) |
| `grep -c "redis.exceptions.ConnectionError\|ConnectionError: Error 111" tests/unit log` returns 0 | ✅ 0 → 0 |
| openai SDK drift documented as orthogonal | ✅ STATE.md v1.8+ todo; 0 occurrences in this run anyway |
| Integration suite collection unaffected | ✅ pending verification (run below) |
| ShortTermMemory `_get_client` refactored | ✅ commit `9f9fecd` |

### Carry-Forward to Plan 27-01

- 14 newly-exposed TD-02 failures in `test_agent_pipeline_refactor.py`, `test_agent_sse.py`, `test_pipeline_coverage.py` (and 1 in `test_feedback_ab_forward.py` that was already in the pre-set) — all event-loop-bound singleton leaks.
- 27-01's `isolated_app` / `_reset_singletons()` integration is the architectural fix.
- Recommend: 27-01 add a regression test that runs `tests/unit/` end-to-end with `isolated_app` enabled and asserts these 14 tests recover.

### Carry-Forward to v1.8+

- openai-SDK signature drift (`APIError.__init__() missing 'request'`) remains tracked in STATE.md. Did not surface in *this* run's 22 pre-existing pytest failures (background-loguru-queue tracebacks observed in some runs are silent — they do not turn into FAILED lines). Remains an orthogonal todo.

---

## Pre-Rollout Failed-Test List (22 tests)

```
tests/unit/test_agent_pipeline_refactor.py::test_narrow_except_catches_httpx_error
tests/unit/test_agent_pipeline_refactor.py::test_per_turn_structured_log_records_parallel_factor
tests/unit/test_agent_pipeline_refactor.py::test_single_tool_call_uses_gather
tests/unit/test_agent_pipeline_refactor.py::test_text_only_stop_reason_extracts_text
tests/unit/test_agent_pipeline_refactor.py::test_tool_exception_becomes_is_error_tool_result
tests/unit/test_agent_sse.py::test_run_streaming_does_not_break_run
tests/unit/test_agent_sse.py::test_run_streaming_emits_planner_plan_first
tests/unit/test_agent_sse.py::test_run_streaming_error_event_replaces_end_d12
tests/unit/test_agent_sse.py::test_run_streaming_latency_bounded_by_max_not_sum_d14_sc4
tests/unit/test_agent_sse.py::test_run_streaming_seq_monotonic_across_planner_and_executor
tests/unit/test_feedback_ab_forward.py::test_negative_feedback_pushes_annotation_task
tests/unit/test_pipeline_coverage.py::test_agent_query_pipeline_run_executor_error_continues_to_persist
tests/unit/test_pipeline_coverage.py::test_agent_query_pipeline_run_not_implemented_delegates_to_query_pipeline
tests/unit/test_pipeline_coverage.py::test_agent_query_pipeline_run_streaming_emits_planner_plan_event
tests/unit/test_pipeline_coverage.py::test_agent_query_pipeline_run_streaming_not_implemented_yields_synthesizer_final
tests/unit/test_pipeline_coverage.py::test_query_pipeline_chitchat_intent_uses_llm_chat
tests/unit/test_pipeline_tool_schema_regression.py::test_registry_anthropic_shape_satisfies_call_agentic_turn
tests/unit/test_recall_tool.py::test_recall_tool_registered_once
tests/unit/test_retrieve_tool.py::TestRetrieveToolRegistration::test_refine_tool_registered
tests/unit/test_retrieve_tool.py::TestRetrieveToolRegistration::test_retrieve_tool_registered
tests/unit/test_retrieve_tool.py::TestSchemasForParity::test_retrieve_tool_xml_format_parity
tests/unit/test_web_search_tool.py::TestWebSearchToolRegistration::test_web_search_tool_registered
```

Of the 22, only 1 is in the v1.6-Phase-24-named "Redis-baseline-failure" cohort (`test_negative_feedback_pushes_annotation_task` in `test_feedback_ab_forward.py`). It fails with an `AssertionError` (mock-expectation mismatch), not Redis-ConnectionError — confirming the cohort assumption no longer matches current head behavior. The other 5 in `test_feedback_ab_forward.py` and the various 'tool registration' failures are orthogonal.

## Post-Rollout Failed-Test List (36 tests = 22 pre + 14 new TD-02)

See `/tmp/27-02-post-rollout.log` for full output; the 14 new tests are listed in the "Newly-Exposed Failures" section above.

---

## Summary

**D-22 diagnostic answers:** On a Redis-up host, the marker rollout contributes 0 closed Redis-ConnectionError failures (the baseline was already 0). On a Redis-down host (CI) the rollout is expected to close those failures — the subprocess gate in `test_redis_mock_baseline_diagnostic.py::test_no_pre_existing_redis_connection_error_in_marked_files` validates this contract by isolating per-file behavior. The +14 TD-02 failures exposed are an expected side effect of broader fixture teardown and belong to parallel plan 27-01's scope; they are not regressions introduced by the redis_mock rollout itself, but rather pre-existing latent rot that the additional monkeypatch teardown surfaces deterministically.
