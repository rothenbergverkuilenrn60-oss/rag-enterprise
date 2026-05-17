---
phase: 29
plan: 2
subsystem: tests/unit/memory
tags: [test-infra, bulk-select, sql-shape-pin, sk-01, nearest-distance-none]
dependency_graph:
  requires: [29-00, 29-01]
  provides: [TEST-INFRA-02]
  affects: [tests/unit/memory/test_save_fact_precheck.py, tests/unit/memory/test_save_fact_precheck_failure.py]
tech_stack:
  added: []
  patterns: [bulk-SELECT mock shape, vec_literals text[], zero_idx dict return, fail-OPEN coverage]
key_files:
  created: []
  modified:
    - tests/unit/memory/test_save_fact_precheck.py
    - tests/unit/memory/test_save_fact_precheck_failure.py
decisions:
  - "Rewrote precheck tests in-place to C1 bulk-SELECT SQL shape (unnest($1::text[]) WITH ORDINALITY + vec_txt::vector)"
  - "Used copy-paste helper pattern (no conftest.py extraction) — both files under LOC bound with copy-paste; conftest not needed"
  - "Replaced _patch_embedder (singular embed_one) with _patch_embedder_batch(n=N) to match production embed_batch path"
  - "Promoted parametrized exc_cls test to two explicit single-exception test functions for (i) PostgresError and (ii) InterfaceError"
metrics:
  duration: "~15 minutes"
  completed_date: "2026-05-17"
  tasks_completed: 2
  files_modified: 2
---

# Phase 29 Plan 02: TEST-INFRA-02 Precheck Test Rewrite Summary

Rewrote `test_save_fact_precheck.py` and `test_save_fact_precheck_failure.py`
in-place to assert the C1 bulk-SELECT SQL shape (`unnest($1::text[]) WITH ORDINALITY`
plus `vec_txt::vector` cast) — replacing legacy per-fact `_is_near_duplicate`
singular SELECT test coverage with the live production path.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 0 | Rewrite test_save_fact_precheck.py to bulk-SELECT shape | 12d6ed9 | tests/unit/memory/test_save_fact_precheck.py |
| 1 | Rewrite test_save_fact_precheck_failure.py — failure paths + nearest_distance=None | 0122b1e | tests/unit/memory/test_save_fact_precheck_failure.py |

## LOC Deltas

| File | LOC_BEFORE | LOC_AFTER | Delta | Bound |
|------|-----------|----------|-------|-------|
| test_save_fact_precheck.py | 276 | 403 | +127 | ≤ +150 ✓ |
| test_save_fact_precheck_failure.py | 211 | 305 | +94 | ≤ +150 ✓ |

Both deltas measured against post-29-01 state.

## Zero Services/ Edits Confirmation

```
git diff --name-only services/
# (empty output — no services/ files touched)
```

Both commits contain zero production-code changes. Test-only plan per spec.

## Case (b) SK-01 Unconditional Shape Confirmation (Plan-Review Q1)

`test_precheck_emits_audit_when_near_duplicate_and_still_inserts` (Task 0) asserts
the **unconditional** SK-01 silent-skip shape — no conditional logic:

```python
assert conn.executemany.await_count == 0  # empty rows_to_insert short-circuit
```

Additionally `test_precheck_save_facts_dup_result_counts` asserts direct `save_facts`
result:

```python
assert result.saved_count == 0
assert result.skipped_near_duplicates == 1
assert conn.executemany.call_count == 0
```

No conditional assertion — plan-review Q1 `depends_on: [29-00, 29-01]` guarantees
Plan 29-01 GREEN has shipped when this plan executes.

## TEST-INFRA-02 nearest_distance=None Branch Coverage

`test_precheck_empty_table_nearest_distance_none_branch` (Task 1) explicitly covers
the empty-table / no-dup branch:

- `conn.fetch` returns `[]` for a 3-fact batch
- `dup_zero_idxs == set()` (implicit: all rows pass)
- `executemany` called once with 3 rows
- `result.skipped_near_duplicates == 0`, `result.saved_count == 3`
- C1 SQL shape assertion: `unnest($1::text[]) WITH ORDINALITY` present

Annotated with "TEST-INFRA-02 nearest_distance=None branch coverage" per req acceptance.

## conftest.py Extraction Decision

No `tests/unit/memory/conftest.py` was created. Both files copy-paste the same
set of helpers (`_AcquireCtx`, `_make_fake_pool`, `_make_long`, `_patch_embedder_batch`,
`_patch_audit`, `_make_facts`) per v1.7 convention of independent test files. Total
LOC delta was 127 and 94 respectively — well under the +150 bound without conftest.
Conftest would save ~80 LOC per file but adds cross-file coupling; not needed here.

## SQL Shape Pin Coverage

Both files now assert C1 SQL tokens:

| File | `unnest($1::text[]) WITH ORDINALITY` | `vec_txt::vector` | `zero_idx` |
|------|--------------------------------------|-------------------|------------|
| test_save_fact_precheck.py | 6 occurrences | 5 occurrences | 6 occurrences |
| test_save_fact_precheck_failure.py | 3 occurrences | 0 explicit | 2 occurrences |

Both files: `grep -c "fetchrow"` == 0 (legacy singular shape fully removed).

## Test Results

```
uv run pytest tests/unit/memory/ -v
27 passed in 0.36s
```

All tests pass including SK-01 tests from Plan 29-01 (no regression).

## Deviations from Plan

None — plan executed exactly as written. The merge of master into the worktree
branch was required to bring in the 29-00/29-01 changes (test files in
`tests/unit/memory/` were created by prior plans on master).

## Threat Flags

None — test-only plan. No production trust boundaries introduced.

## Self-Check: PASSED

- test_save_fact_precheck.py: FOUND
- test_save_fact_precheck_failure.py: FOUND
- Commit 12d6ed9: FOUND
- Commit 0122b1e: FOUND
- services/ edits: 0 (confirmed)
- LOC delta: +127 and +94 (both ≤ +150)
- 27 tests passed
