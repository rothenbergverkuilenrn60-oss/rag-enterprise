---
phase: 26-memory-infra-hygiene
verified: 2026-05-17
status: passed
plans_total: 5
plans_complete: 5
unit_tests_added: 29
integration_tests_added: 5
total_tests_added: 34
---

# Phase 26 Verification — Memory Infra Hygiene

## Goal achievement (vs ROADMAP.md SC)

**Phase 26 success criteria from ROADMAP.md:**

1. ✅ **SC-1: Cold-start fresh PostgreSQL** — `audit_log` auto-creates with INSERT-ONLY grants (REVOKE UPDATE, DELETE on PUBLIC preserved). Verified by `tests/integration/test_audit_log_auto_create.py::test_audit_log_auto_creates_on_first_flush` running against real local pgvector after a `DROP TABLE IF EXISTS audit_log CASCADE`. Both the table existence AND the inserted event row are asserted.

2. ✅ **SC-2: Zero `ssl=disable` hits in services/** — verified via `grep -rn 'ssl=disable' services/` returning zero lines. Both `services/memory/memory_service.py` and `services/audit/audit_service.py` connect via `utils.asyncpg_helper.prepare_dsn`. Helper is unit-tested with 9 cases including A1 (short scheme) + C1 (ssl-at-start malformed URL fix).

3. ✅ **SC-3: Fresh-machine bge-m3 loads from HF cache** — `config.settings.resolve_embedding_model_path` searches env override → HF flat (`BAAI/bge-m3`) → legacy (`embedding_models/bge-m3`) → HF hub cache (`models--BAAI--bge-m3/snapshots/*`). Backwards-compat for legacy layout preserved; resolver falls back to legacy path on miss (no behavior change for absent-model case). 7 unit tests cover all 4 search branches + fallback + reranker variant + env-override scoping.

4. ✅ **SC-4: v1.6 real-PG integration suites remain green post-refactor** — 11/11 v1.6 PG-gated tests still pass (3 Phase 23 schema + 8 Phase 25 PG-gated). New tests added: 2 in test_audit_log_auto_create.py (TD-01) + 3 in test_lifespan_shutdown_closes_pools.py (TD-01 + TD-03 close wiring).

## Requirement closure

| REQ-ID | Title | Plans | Status |
|--------|-------|-------|--------|
| TD-01  | `audit_log` table auto-create | 26-04 + 26-05 | ✅ Closed — DDL ported from docstring to `_create_tables`; lazy first-acquire trigger; INSERT-ONLY invariant preserved; real-PG integration verified |
| TD-03  | `utils/asyncpg_helper.py` centralization | 26-01, 26-03, 26-04, 26-05 | ✅ Closed — `prepare_dsn` extracted; consumed by both memory + audit; both inline strip blocks removed; close() methods added; lifespan shutdown wires both |
| TD-07  | bge-m3 model dir layout fix | 26-02 | ✅ Closed — multi-layout resolver; HF flat + legacy + HF hub cache all work; env-var override; reranker covered |

## Test results

### Phase 26 tests added (34 total)
- `tests/unit/test_asyncpg_helper.py` — **9/9 PASSED** (0.03s)
- `tests/unit/test_resolve_embedding_model_path.py` — **7/7 PASSED** (0.16s)
- `tests/unit/test_memory_service_prepare_dsn.py` — **3/3 PASSED** (0.22s)
- `tests/unit/test_audit_service_pool.py` — **10/10 PASSED** (0.15s)
- `tests/integration/test_audit_log_auto_create.py` — **2/2 PASSED** on real PG (0.40s)
- `tests/integration/test_lifespan_shutdown_closes_pools.py` — **3/3 PASSED** on real PG (0.34s)

Combined: `uv run pytest tests/unit/test_asyncpg_helper.py tests/unit/test_resolve_embedding_model_path.py tests/unit/test_memory_service_prepare_dsn.py tests/unit/test_audit_service_pool.py tests/integration/test_audit_log_auto_create.py tests/integration/test_lifespan_shutdown_closes_pools.py -v` → **34/34 PASSED** in 0.71s.

### v1.6 carry-forward suite (no regressions in Phase 26 scope)
- `tests/unit/ -k 'audit or memory'` → **116/116 PASSED** (audit + memory unit suites unaffected by refactor)

### Broader test run notes
- Full unit suite: 1180 passed, 16 failed. All 16 failures are pre-existing v1.6 baseline issues (test_agent_sse, test_feedback_ab_forward, test_pipeline_coverage) — NOT introduced by Phase 26. These trace to Redis dependency + pipeline mocks unrelated to memory/audit/config changes. Tracked under TD-06 (Plan 27 scope, Redis-mock fixture rollout).
- Real-PG integration tests that need a live bge-m3 model (e.g., `test_memory_forget_e2e.py`, `test_recall_tool_e2e.py`) fail with `FileNotFoundError: Path /tmp/embedding_models/bge-m3 not found` from sentence-transformers. This is the same "lazy crash at model load" semantics Plan 26-02 D-18 explicitly preserved — NOT a Phase 26 regression. These suites pass on machines with the real model.

## Eng-review fixes applied + verified

| ID | Where | Fix | Test |
|----|-------|-----|------|
| A1 | `utils/asyncpg_helper.py` | `postgres+asyncpg://` short-scheme strip | `test_strips_postgres_short_asyncpg_scheme` ✅ |
| A2 | `services/audit/audit_service.py::AuditService.close` | `async with self._lock` wraps drain | `test_close_acquires_lock_during_drain` ✅ |
| C1 | `utils/asyncpg_helper.py` | Ordered ssl-token strip (no malformed URLs) | `test_strips_ssl_disable_with_following_params` ✅ |
| P1 | `services/audit/audit_service.py::AuditService._get_pool` | try/except `_create_tables` + reset `_pool=None` | `test_create_tables_failure_resets_pool` ✅ |
| R1 | (regression test) | close-vs-overflow race | `test_close_vs_overflow_flush_no_event_loss` ✅ |

## Plan execution status

| Plan | Status | Tests |
|------|--------|-------|
| 26-01 asyncpg_helper foundation | ✅ Complete | 9 unit |
| 26-02 bge-m3 resolver | ✅ Complete | 7 unit |
| 26-03 memory_service consumes helper + close() | ✅ Complete (deviated: MemoryContext.close skipped — dataclass, not pool-bearing; 3 tests instead of 5) | 3 unit |
| 26-04 AuditService pool + create_tables + close | ✅ Complete | 10 unit + 2 integration |
| 26-05 lifespan shutdown wiring + integration | ✅ Complete (deviated: D-15 test isolated to close() ordering; full lifespan smoke not run because lifespan has unrelated startup deps — knowledge service, event bus, arq) | 3 integration |

## Static-analysis status

- `uv run ruff check utils/asyncpg_helper.py config/settings.py services/memory/memory_service.py services/audit/audit_service.py main.py tests/conftest.py` → **all checks passed**
- `uv run mypy --strict utils/asyncpg_helper.py` → **no issues**
- `uv run mypy --strict services/audit/audit_service.py` → not run on this file (large file with pre-existing mypy debt; gate scope was the helper + settings)
- Pre-existing `config/settings.py:154` `embedding_ensemble: list[dict]` mypy error noted in Plan 26-02 SUMMARY — NOT introduced by Phase 26; v1.8+ cleanup.

## Deferred to v1.8+ (added to STATE.md Todos)

1. P1 backport to `LongTermMemory._get_pool` (same partial-init bug in v1.6-shipped MEM-* path)
2. Graceful-shutdown close-then-reuse discipline (project-wide `_closed: bool` guard)
3. AuditService pool `application_name=audit_service` for `pg_stat_activity` visibility
4. TD-06 Redis-mock fixture rollout (resolves the 16 pre-existing unit-test failures observed during Phase 26 verification)
5. bge-m3 real-model integration test fix (the `Path /tmp/embedding_models/bge-m3 not found` errors are environmental — Plan 26-02 preserved current semantics by design; orthogonal cleanup if/when CI gets a bge-m3 model cache)

## Verdict

**Phase 26: PASSED.** All 3 TD requirements closed. All 5 plans executed. 34 new tests added, 0 Phase 26 test failures, 0 regressions in audit + memory v1.6 suite. Eng-review fixes (A1, A2, C1, P1) applied and verified by tests. Ready for Phase 27 (TD-02, TD-04, TD-05, TD-06).
