---
phase: 25-eviction-job-gdpr-forget-api
plan: "02"
subsystem: memory
tags: [forget_user, MemoryForgetError, asyncpg, chunked-delete, gdpr, narrow-except, wave1-service, tdd, T7]
dependency_graph:
  requires: []
  provides:
    - services/memory/memory_service.py::MemoryForgetError (typed exception)
    - services/memory/memory_service.py::LongTermMemory.forget_user (chunked-DELETE service method)
  affects:
    - Plan 25-04 (forget controller — consumes MemoryForgetError + forget_user)
tech_stack:
  added: []
  patterns:
    - chunked-DELETE loop at 1000 rows/txn (mirrors evict_bucket EVICT-01 T7)
    - "DELETE ... WHERE id IN (SELECT id ... LIMIT $3)" subquery form
    - 'DELETE N' status-tag parsing via int(status.split()[1]) (Pitfall 2 / SP-5)
    - narrow-except (asyncpg.PostgresError) + typed wrap (raise MemoryForgetError from exc)
    - fake-pool harness (_AcquireCtx / _make_fake_pool / _make_long) copied verbatim from test_memory_save_fact.py
requirements: [GDPR-01]
key_files:
  created:
    - tests/unit/test_memory_forget.py
  modified:
    - services/memory/memory_service.py
decisions:
  - "T7 (eng-review outside voice F1): chunk forget_user DELETE at 1000 rows/txn — mirrors evict_bucket; eliminates statement_timeout failure mode on large pre-eviction buckets; bounds AccessExclusiveLock contention window with eviction CronJob"
  - "D-1.2: scope is long_term_facts ONLY; no Redis, no user_profile touched here"
  - "D-2.3 / SP-6: forget_user does NOT write audit row — caller (Plan 25-04 controller) writes audit AFTER this method returns"
  - "Pitfall 4: single-pool-acquire chunked loop does NOT need asyncpg.InterfaceError catch (only PostgresError); InterfaceError is for batch loops that reacquire connections"
metrics:
  duration: "~12m"
  completed: "2026-05-16T14:17:00Z"
  tasks: 2
  files: 2
---

# Phase 25 Plan 02: forget_user Service Method + MemoryForgetError Summary

**One-liner:** `LongTermMemory.forget_user(user_id, tenant_id) -> int` with chunked DELETE at 1000 rows/txn (T7) and `MemoryForgetError` typed exception for GDPR-01 right-to-erasure; mirrors `save_fact` narrow-except shape but uses `evict_bucket` chunking pattern for the DELETE loop.

## Objective Recap

Implement the service-layer method that Plan 25-04 (forget controller, Wave 2) will call. Two artifacts:

1. `MemoryForgetError` typed exception class (immediately after `MemoryFactWriteError` in source order, lines 30–35 of `services/memory/memory_service.py`).
2. `LongTermMemory.forget_user(user_id, tenant_id) -> int` method (lines 386–432) that deletes all `long_term_facts` rows for the given (user_id, tenant_id) pair, chunked at 1000 rows per transaction (T7), and returns the cumulative row count across chunks.

The chunked loop runs inside a single `pool.acquire()` context and uses asyncpg's implicit auto-commit per `execute` — so a mid-loop failure leaves prior chunks committed and the next call resumes idempotently from the bucket's current state.

## Tasks Completed

| Task | Name                                                    | Commit  | Files                                                            | Tests                              |
| ---- | ------------------------------------------------------- | ------- | ---------------------------------------------------------------- | ---------------------------------- |
| 1    | RED — forget_user contract tests (7 RED gates)          | bf38195 | tests/unit/test_memory_forget.py                                 | 7 collected, 7 RED                 |
| 2    | GREEN — MemoryForgetError + forget_user chunked-DELETE  | 4ab53a4 | services/memory/memory_service.py                                | 7 GREEN                            |

## Acceptance Criteria Met

| Criterion                                                                | Verification                                                                                                                |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| `MemoryForgetError` class exists, subclasses Exception                   | `from services.memory.memory_service import MemoryForgetError` + `issubclass(..., Exception)` ⇒ True                       |
| `MemoryForgetError` placed immediately after `MemoryFactWriteError`      | `MemoryFactWriteError` at line 21; `MemoryForgetError` at line 30 (one blank-line block separator between)                  |
| `LongTermMemory.forget_user(user_id, tenant_id) -> int` exists           | `'forget_user' in dir(LongTermMemory)` ⇒ True; signature returns `int`                                                      |
| Chunked DELETE at BATCH = 1000                                           | `BATCH = 1000` (line 403); `LIMIT $3` (line 414) with `BATCH` bound positionally                                            |
| Subquery DELETE form `WHERE id IN (SELECT id FROM long_term_facts ...)`  | Present at lines 410–415                                                                                                    |
| Loop terminates on `"DELETE 0"` and sums totals                          | `while True:` (line 408) with `if deleted == 0: break` (line 420); `total_deleted += deleted` (line 419)                    |
| Status parsing per Pitfall 2 / SP-5                                      | `int(status.split()[1])` (line 418)                                                                                         |
| Narrow except on `asyncpg.PostgresError` with `raise ... from exc`       | `except asyncpg.PostgresError as exc:` (line 423); `raise MemoryForgetError("forget failed") from exc` (line 432)           |
| Structured logging on failure                                            | `logger.error("memory service failure", operation="forget_user", user_id=..., tenant_id=..., deleted_before_failure=...)` |
| Scope limited to `long_term_facts` (D-1.2)                               | Only one DELETE inside method; no Redis touch; no user_profile touch                                                        |
| No audit_service call inside `forget_user` (D-2.3 / SP-6)                | `grep -c 'audit_service' services/memory/memory_service.py` inside forget_user body ⇒ 0                                     |
| Test 7 (T7) — chunked-large-bucket gate                                  | `test_forget_user_chunks_large_bucket` PASSED with 4-chunk side_effect ("DELETE 1000"×2, "DELETE 500", "DELETE 0") ⇒ 2500 |
| ruff clean                                                               | `uv run ruff check services/memory/memory_service.py tests/unit/test_memory_forget.py` ⇒ All checks passed                  |

## Coverage

| Test file                          | Tests | Status       |
| ---------------------------------- | ----- | ------------ |
| tests/unit/test_memory_forget.py   | 7     | 7/7 GREEN    |

### Test breakdown

| Test                                                       | Behavior                                                                                                             |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `test_memory_forget_error_class_exists`                    | `MemoryForgetError` importable + subclass of `Exception`                                                             |
| `test_forget_user_returns_row_count`                       | 2-chunk side_effect (`"DELETE 3"`, `"DELETE 0"`) returns int `3`; execute awaited twice                              |
| `test_forget_user_idempotent_zero`                         | Empty bucket — `"DELETE 0"` first call returns `0`; execute awaited exactly once                                     |
| `test_forget_user_raises_memory_forget_error_on_pg_error`  | `asyncpg.PostgresError` side_effect → `MemoryForgetError` raised                                                     |
| `test_forget_user_error_chains_cause`                      | `exc.__cause__ is pg_error` (raise from exc)                                                                         |
| `test_forget_user_sql_args`                                | SQL contains `WHERE user_id=$1 AND tenant_id=$2` and `LIMIT`; positional args include `("alice", "acme")`            |
| `test_forget_user_chunks_large_bucket` (T7)                | 4-chunk side_effect (`"DELETE 1000"`, `"DELETE 1000"`, `"DELETE 500"`, `"DELETE 0"`) → `2500` total; await_count = 4 |

## Deviations from Plan

None — plan executed exactly as written. All 7 acceptance criteria from `<acceptance_criteria>` of Task 1 met; all 11 acceptance criteria from `<acceptance_criteria>` of Task 2 met.

A small enhancement vs the literal plan SQL spec: the acceptance criteria mention `"WHERE user_id=$1 AND tenant_id=$2"` AND `"LIMIT 1000"`. The implementation uses `LIMIT $3` with `BATCH = 1000` bound positionally — this is semantically identical to `LIMIT 1000` (BATCH is a Python-side `int` constant) and matches the explicit code skeleton in the plan body (`<action>` step 2, lines 256–269 of 25-02-PLAN.md). The acceptance-criteria grep alternation `'BATCH = 1000\|LIMIT \$3'` accepts either form; both are present.

Test 6 (`test_forget_user_sql_args`) was authored to assert just `"LIMIT"` (rather than the literal `"LIMIT 1000"`) in the SQL so it stays robust to the `LIMIT $3` parameterization; this is a test-side latitude, not a deviation from the production-code spec.

## Threat Surface Scan

No new attack surface introduced beyond what `<threat_model>` enumerates in the plan. `T-25-02-D1` (statement_timeout / lock contention on large DELETE) flipped from `accept` → `mitigate` via T7 chunking, which Task 2 implements and Test 7 enforces. No HTTP path is added in this plan — the controller (Plan 25-04) is the auth gate (per `<threat_model>` T-25-02-S1 / T-25-02-E1 acceptance).

## mypy --strict notes

`uv run mypy --strict services/memory/memory_service.py` reports 26 errors — **all pre-existing** in this file or upstream dependencies (`config/settings.py`, `utils/logger.py`, `services/vectorizer/embedder.py`, asyncpg / pgvector library stubs absent). The new code at line 406 (`pool = await self._get_pool()`) inherits the same untyped-call pattern already used at line 374 (`save_fact`) — no NEW errors introduced. Verified by reading mypy output and confirming the line-number distribution is consistent with the pre-existing `_get_pool`/`get_embedder` untyped surface.

## Known Stubs

None. `forget_user` is fully wired end-to-end at the service layer; only the controller wiring (Plan 25-04, Wave 2) remains.

## Self-Check: PASSED

- `services/memory/memory_service.py` modified: FOUND (verified via Read tool — `MemoryForgetError` at line 30, `forget_user` at line 386, `raise MemoryForgetError` at line 432).
- `tests/unit/test_memory_forget.py` created: FOUND (180 lines, 7 tests collected, 7 GREEN).
- Commit `bf38195` (Task 1 RED): FOUND in `git log --oneline -3`.
- Commit `4ab53a4` (Task 2 GREEN): FOUND in `git log --oneline -3`.
- Final gate `uv run pytest tests/unit/test_memory_forget.py -x -q` exits 0 (7 passed in 0.16s).
- Final gate `uv run ruff check services/memory/memory_service.py tests/unit/test_memory_forget.py` exits 0 (All checks passed!).
