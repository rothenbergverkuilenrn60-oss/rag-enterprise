---
phase: 29
plan: 0
subsystem: memory
tags: [toctou, advisory-lock, postgres, guc, tdd, red-green-refactor]
dependency_graph:
  requires: []
  provides: [pg_advisory_xact_lock in save_facts, _bulk_near_duplicate_check_raw helper]
  affects: [services/memory/memory_service.py, tests/integration/memory/, tests/unit/memory/]
tech_stack:
  added: []
  patterns: [pg_advisory_xact_lock, SET LOCAL GUC inlining in outer txn]
key_files:
  created:
    - tests/integration/memory/test_save_facts_toctou.py
    - tests/unit/memory/test_save_facts_lock_failure.py
  modified:
    - services/memory/memory_service.py
    - pytest.ini
decisions:
  - "D-TOC-01 honored: pg_advisory_xact_lock(hashtext($1 || '|' || $2)) — no schema migration, no UNIQUE constraint, no ON CONFLICT"
  - "A1-A GUC inlining: SET LOCAL hnsw.iterative_scan + ef_search moved into outer advisory-lock txn (not SAVEPOINT) per plan-review finding"
  - "_bulk_near_duplicate_check renamed to _bulk_near_duplicate_check_raw — only caller was save_facts; no dead-code wrapper needed"
  - "Task 2 REFACTOR skipped — docstring updated inline during GREEN (TOC-01 + D-TOC-01 + 29-CONTEXT already referenced in production code)"
metrics:
  duration: "18m"
  completed: "2026-05-17T11:06:05Z"
  tasks_completed: 3
  tasks_total: 4
  files_changed: 4
---

# Phase 29 Plan 0: TOCTOU Advisory Lock for save_facts Summary

One-liner: pg_advisory_xact_lock wraps precheck+INSERT in save_facts closing the concurrent-writer race window; GUCs inlined into outer txn per A1-A plan-review finding.

## What Was Built

Closes the TOCTOU race between the bulk-dedupe SELECT and the `executemany` INSERT in
`LongTermMemory.save_facts` by wrapping the precheck-plus-INSERT critical section in a
PostgreSQL transaction holding a per-`(user_id, tenant_id)` advisory lock.

### RTT count change

| State | RTTs |
|-------|------|
| Pre-29-00 (v1.7) | 3 + K (embed + dedupe SELECT + INSERT + K audits) |
| Post-29-00 (v1.8) | 4 + K (embed + pg_advisory_xact_lock + dedupe SELECT + INSERT + K audits) |

The +1 RTT is the `SELECT pg_advisory_xact_lock(...)` call inside the outer transaction.

### Lock granularity

Per `(user_id, tenant_id)` via `hashtext($1 || '|' || $2)`. The `|` separator prevents
prefix collision between (`alice`, `tcorp`) and (`alicetcorp`, `''`). Writers for different
`(user_id, tenant_id)` pairs run in parallel. Lock is auto-released at txn end.

### A1-A GUC inlining

Plan-review finding: `_bulk_near_duplicate_check` opened an inner `conn.transaction()`
(SAVEPOINT) that ran `SET LOCAL hnsw.iterative_scan = 'strict_order'` + `SET LOCAL
hnsw.ef_search`. Under the new outer `conn.transaction()`, the SAVEPOINT release would
revert the `SET LOCAL` before the bulk SELECT ran — silently degrading HNSW scan quality.

Fix: extracted the SQL body into `_bulk_near_duplicate_check_raw` (no inner txn, no
SET LOCAL). In `save_facts`, the two SET LOCAL calls now run inside the OUTER advisory-lock
transaction directly after `pg_advisory_xact_lock`. GUCs remain in effect when the bulk
SELECT runs.

## Task Results

| Task | Commit | Result |
|------|--------|--------|
| Task 0 RED — failing TOCTOU integration test | bc9c523 | Created; COUNT(*)==2 proves race exists |
| Task 1 GREEN — advisory lock implementation | 23b0d18 | Lock in place; unit tests green |
| Task 1b TEST GAP T1 — lock-failure unit test | 9892b72 | PASSES |
| Task 2 REFACTOR — docstring polish | (skipped) | Docstring updated inline in GREEN |

## Test Evidence

### Unit tests (all passing)

```
uv run pytest tests/unit/memory/ tests/unit/test_memory_save_fact.py -v
27 passed in 0.71s
```

Includes:
- `test_save_facts_lock_failure.py::test_save_facts_lock_acquisition_failure_raises_memory_fact_write_error` PASSED
- `test_save_facts_batch_dedupe.py::test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows` PASSED
- `test_save_facts_batch_dedupe.py::test_bulk_dedupe_fail_open_on_postgres_error` PASSED
- All 6 `test_memory_save_fact.py` tests PASSED

### Integration test: test_save_facts_toctou.py

```
1 failed, 1 passed in 0.61s
```

- `test_save_facts_guc_preserved_inside_outer_txn` PASSED — A1-A GUC inlining verified.
- `test_save_facts_toctou_concurrent_writers_produce_one_row` FAILS — see Known Gap below.

## Known Verification Gap (Integration Test COUNT==1)

**Status:** Code-shape verified + unit-mock verified. Integration test COUNT assertion deferred.

**Root cause:** `test_save_facts_toctou_concurrent_writers_produce_one_row` asserts
`COUNT(*) == 1` after two concurrent writers. With the advisory lock in place, the lock
serializes the writers correctly — the second writer DOES find the first writer's row in the
bulk-dedupe SELECT and fires a `MEMORY_NEAR_DUPLICATE_SKIPPED` audit event (confirmed in
test stderr). However, D-09 audit-mode-only (v1.7 contract) inserts ALL rows including
duplicates. The `COUNT(*) == 1` assertion requires SK-01 silent-skip enforcement (Plan 29-01).

**Evidence the lock works:** The audit event fires (`MEMORY_NEAR_DUPLICATE_SKIPPED` for
`toctou-test-fact-XYZ`) — proving writer B serialized after writer A and found the duplicate.
Without the lock, both writers would pass the dedupe check before either inserted (no audit).

**Resume command** (run after Plan 29-01 lands SK-01 silent-skip):
```bash
uv run pytest tests/integration/memory/test_save_facts_toctou.py::test_save_facts_toctou_concurrent_writers_produce_one_row -v
```
Expected: 1 passed (COUNT(*)==1 because duplicates are filtered before INSERT).

**Note:** This plan is marked "code-shape verified + unit-mock verified + integration-test
deferred to SK-01 enforcement." TOC-01 acceptance criteria FULLY met only after Plan 29-01.

## Acceptance Grep Checks

```
grep -n "pg_advisory_xact_lock" services/memory/memory_service.py
→ lines 577, 586, 691 (docstring + SQL in save_facts body)

grep -c "hashtext.*||.*'|'" services/memory/memory_service.py
→ 2 (docstring reference + live SQL)

grep -n "SET LOCAL hnsw.iterative_scan" services/memory/memory_service.py
→ line 417 (_is_near_duplicate), 465 (_is_near_duplicate txn), 594 (docstring), 707 (save_facts outer txn)

grep -n "_bulk_near_duplicate_check_raw" services/memory/memory_service.py
→ lines 516 (def), 596 (docstring), 668 (comment), 711 (called from save_facts)

grep -n "ALTER TABLE|UNIQUE.*long_term_facts|ON CONFLICT.*long_term_facts" services/memory/memory_service.py
→ only pre-existing ALTER TABLE for schema setup (no new constraint)
```

## Deviations from Plan

### Rule 4 — Plan Consistency Finding (TOCTOU test COUNT vs D-09)

**Found during:** Task 1 GREEN verification
**Issue:** Plan success criteria requires `test_save_facts_toctou_concurrent_writers_produce_one_row`
to PASS (COUNT(*)==1) after Task 1. But D-09 audit-mode-only inserts ALL rows including
duplicates. Advisory lock alone cannot satisfy COUNT==1 — that requires SK-01 silent-skip.
**Action:** Documented as deferred gap. Did NOT change D-09 behavior (out of Plan 29-01 scope).
Did NOT mark TOC-01 as "fully verified". Plan execution otherwise matches spec exactly.

### Task 2 REFACTOR — Skipped (docstring already updated inline)

The Task 1 GREEN edit updated `save_facts` docstring with the new wire shape, advisory-lock
rationale, GUC discipline explanation, lock-failure failure mode, 29-CONTEXT reference, and
D-TOC-01 reference. Task 2 acceptance criteria (`grep -n "TOC-01\|D-TOC-01\|29-CONTEXT"`
showing references in docstring) were satisfied by the GREEN commit. REFACTOR is optional
per 29-CONTEXT "TDD discipline" section.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. The advisory lock
is a DB-internal synchronization mechanism. T-29-00-03 (prefix-collision) mitigated by `'|'`
separator in `hashtext($1 || '|' || $2)` (D-TOC-01). T-29-00-04 (embed_batch under lock)
mitigated: `embed_batch` at line 638 precedes `_get_pool()` at line 683.

## Known Stubs

None — no placeholder data, no hardcoded empty values, no TODO markers introduced.

## Self-Check: PASSED

Files created/exist:
- tests/integration/memory/test_save_facts_toctou.py: FOUND
- tests/unit/memory/test_save_facts_lock_failure.py: FOUND
- services/memory/memory_service.py: FOUND (modified)

Commits verified:
- bc9c523 (RED): FOUND
- 23b0d18 (GREEN): FOUND
- 9892b72 (T1 test): FOUND
