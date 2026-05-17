---
phase: 29
plan: 1
subsystem: memory
tags: [sk-01, silent-skip, near-duplicate, tdd, red-green-refactor, audit]
dependency_graph:
  requires: [29-00]
  provides: [SK-01 silent-skip enforcement in save_facts rows_to_insert filter]
  affects: [services/memory/memory_service.py, tests/unit/memory/test_save_facts_batch_dedupe.py, tests/unit/memory/test_save_fact_precheck.py, tests/unit/memory/test_save_fact_precheck_failure.py]
tech_stack:
  added: []
  patterns: [enumerate(indexed) filter by local_i not in dup_zero_idxs, empty-batch short-circuit before executemany]
key_files:
  created: []
  modified:
    - services/memory/memory_service.py
    - tests/unit/memory/test_save_facts_batch_dedupe.py
    - tests/unit/memory/test_save_fact_precheck.py
    - tests/unit/memory/test_save_fact_precheck_failure.py
decisions:
  - "SK-01 v1.8 enforcement: rows_to_insert built with enumerate(indexed) filter -- local_i not in dup_zero_idxs"
  - "Empty-batch short-circuit: if not rows_to_insert: return SaveFactsResult() before executemany (avoids asyncpg undefined behavior on empty batch)"
  - "Audit emit unchanged: _fire_near_duplicate_audit still fires per dup; failure still swallowed (v1.6 T1 Pattern D preserved)"
  - "Wrapper tests adjusted: test_save_fact_precheck.py T1 + test_save_fact_precheck_failure.py audit-failure test flipped to executemany==0 (Open Risks #3 resolved)"
  - "test_memory_save_fact.py: no changes required -- no saved_count==1 assertions for dup-text cases existed (Open Risks #3 N/A)"
  - "REFACTOR: 2 residual audit-mode-only comments in module header + Step 4 comment updated inline"
metrics:
  duration: "38m"
  completed: "2026-05-17T11:44:17Z"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
---

# Phase 29 Plan 1: SK-01 Silent-Skip Enforcement Summary

One-liner: SK-01 v1.8 -- near-duplicate rows filtered from rows_to_insert via enumerate(indexed)+dup_zero_idxs before executemany; audit emit preserved; empty-batch short-circuit added.

## What Was Built

Promotes v1.7 D-09 audit-mode-only near-duplicate handling to SK-01 silent-skip
enforcement in `LongTermMemory.save_facts`. Duplicates identified by
`_bulk_near_duplicate_check_raw` are now filtered from `rows_to_insert` before
`conn.executemany`, so only non-duplicate rows are INSERTed.

### Core change (Step 5 of save_facts)

Before (v1.7):
```python
rows_to_insert = [
    (user_id, tenant_id, f.fact, source_doc, f.importance, e)
    for _, f, e in indexed
]
```

After (v1.8 SK-01):
```python
rows_to_insert = [
    (user_id, tenant_id, f.fact, source_doc, f.importance, e)
    for local_i, (_, f, e) in enumerate(indexed)
    if local_i not in dup_zero_idxs
]
if not rows_to_insert:
    return SaveFactsResult(
        saved_count=0,
        skipped_near_duplicates=len(dup_zero_idxs),
        skipped_embed_failures=embed_failures,
    )
```

### Preserved invariants

- `_fire_near_duplicate_audit` called per dup BEFORE the filter (Step 4 unchanged)
- Audit-write failure still swallowed (`except Exception` -- v1.6 GDPR T1 Pattern D)
- `SaveFactsResult.skipped_near_duplicates` = `len(dup_zero_idxs)` (unchanged)
- `SaveFactsResult.saved_count` = `len(rows_to_insert)` (now excludes dups)
- `save_fact` D-12 wrapper: no code change; silently inherits SK-01 via delegation

## Task Results

| Task | Commit | Result |
|------|--------|--------|
| Task 0 RED -- flip v1.7 pin to SK-01 assertion shape | 44278ab | 3 tests RED-fail; fail-open test passes |
| Task 1 GREEN -- SK-01 filter in save_facts Step 5 | cf916e2 | All 29 unit tests pass; wrapper tests adjusted |
| Task 2 REFACTOR -- docstring sweep | 5bbae8f | Residual audit-mode wording removed; 29 tests pass |

## Test Evidence

### Unit tests (all passing after Task 1 GREEN)

```
uv run pytest tests/unit/memory/ tests/unit/test_memory_save_fact.py -v
29 passed in 0.42s
```

Includes all 4 batch_dedupe tests:
- `test_dedupe_in_batch_fires_audit_AND_executemany_inserts_non_dup_rows_only` PASSED
- `test_bulk_dedupe_fail_open_on_postgres_error` PASSED
- `test_audit_write_failure_does_not_block_skip_insert` PASSED
- `test_all_duplicates_short_circuits_executemany` PASSED

### Audit-emit-failure test passing output

```
tests/unit/memory/test_save_facts_batch_dedupe.py::test_audit_write_failure_does_not_block_skip_insert PASSED
```
Confirms: _fire_near_duplicate_audit raising RuntimeError("audit DB down") does NOT
prevent executemany receiving the 3 non-dup rows. Open Risks #4 pinned.

### TOC-01 + SK-01 layered (no PG on this host)

```
Integration test tests/integration/memory/test_save_facts_toctou.py:
  - test_save_facts_guc_preserved_inside_outer_txn: SKIPPED (no PG)
  - test_save_facts_toctou_concurrent_writers_produce_one_row: SKIPPED (no PG)
```

The TOCTOU concurrent-writer integration test (Plan 29-00 Known Gap) requires
PostgreSQL. No PG is available on this host (WSL2 unit-only environment). SK-01
silent-skip is fully verified via mocked asyncpg.Connection unit tests. The
integration test is expected to pass once SK-01 + advisory lock are layered on a
PG host (see Plan 29-00 Known Verification Gap section).

## Acceptance Grep Checks

```
grep -c "not in dup_zero_idxs" services/memory/memory_service.py
→ 1

grep -n "if not rows_to_insert" services/memory/memory_service.py
→ 750:                if not rows_to_insert:

grep -c "test_dedupe_in_batch_fires_audit_AND_executemany_inserts_non_dup_rows_only" tests/unit/memory/test_save_facts_batch_dedupe.py
→ 1

grep -c "test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows" tests/unit/memory/test_save_facts_batch_dedupe.py
→ 1 (in comment only -- Renamed from: line; no function definition)

grep -c "test_audit_write_failure_does_not_block_skip_insert" tests/unit/memory/test_save_facts_batch_dedupe.py
→ 1

grep -c "test_all_duplicates_short_circuits_executemany" tests/unit/memory/test_save_facts_batch_dedupe.py
→ 1

grep -n "audit-mode-only|v1.7 still INSERT|v1.7 metric-only" services/memory/memory_service.py
→ (no output -- all residual wording removed by REFACTOR)
```

## mypy / ruff

```
uv run mypy --strict services/memory/memory_service.py
→ Found 40 errors in 7 files (pre-existing baseline -- unchanged from Plan 29-00)

uv run ruff check services/memory/memory_service.py
→ All checks passed!
```

## Wrapper-Test Edits Applied (Open Risks #3)

Two tests in the `tests/unit/memory/` subdirectory needed adjustment because
they pinned v1.7 D-09 audit-mode behavior (INSERT still runs for near-dup):

1. `tests/unit/memory/test_save_fact_precheck.py::test_precheck_emits_audit_when_near_duplicate_and_still_inserts`
   - Flipped: `executemany.await_count == 1` -> `executemany.await_count == 0`
   - Docstring updated: "INSERT STILL RAN" -> "INSERT must NOT run (silent-skip)"

2. `tests/unit/memory/test_save_fact_precheck_failure.py::test_audit_log_failure_is_non_fatal`
   - Flipped: `executemany.await_count == 1` -> `executemany.await_count == 0`
   - Rationale: audit failure non-fatal assertion preserved; dup is still skipped

`tests/unit/test_memory_save_fact.py` required NO changes -- none of its 6 tests
assert `saved_count==1` for a duplicate-text single save (Open Risks #3 was N/A for
this file).

## Deviations from Plan

### Rule 2 -- Wrapper tests in tests/unit/memory/ needed adjustment

**Found during:** Task 1 GREEN verification
**Issue:** `test_save_fact_precheck.py` test 1 and `test_save_fact_precheck_failure.py`
audit-failure test asserted `executemany.await_count == 1` for near-dup cases --
v1.7 contract. After SK-01, executemany should NOT run for a dup.
**Fix:** Both tests updated per Plan 29-01 explicit allowance ("wrapper-test edits;
document deltas in commit body").
**Files modified:** tests/unit/memory/test_save_fact_precheck.py,
tests/unit/memory/test_save_fact_precheck_failure.py
**Commit:** cf916e2

### Task 2 REFACTOR -- Not skipped (2 residual sites found)

Task 1 GREEN left 2 residual "audit-mode-only" comment sites:
- Module header comment (lines 92-94)
- Step 4 comment (line 728)
Both swept in REFACTOR commit 5bbae8f. Task 2 acceptance criteria
(`grep -n "audit-mode-only..."` returns no hits) satisfied.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes.
The SK-01 filter is a pure in-memory list comprehension operating on data already
fetched from PG. T-29-01-01 (Repudiation) mitigated: audit row still emitted per
dup. T-29-01-03 (Availability) mitigated: audit failure non-fatal (pinned by new
test). INSERT-ONLY audit_log invariant preserved.

## Known Stubs

None -- no placeholder data, no hardcoded empty values, no TODO markers introduced.

## Self-Check: PASSED

Files modified:
- services/memory/memory_service.py: FOUND (modified)
- tests/unit/memory/test_save_facts_batch_dedupe.py: FOUND (modified)
- tests/unit/memory/test_save_fact_precheck.py: FOUND (modified)
- tests/unit/memory/test_save_fact_precheck_failure.py: FOUND (modified)

Commits verified:
- 44278ab (RED): FOUND
- cf916e2 (GREEN): FOUND
- 5bbae8f (REFACTOR): FOUND
