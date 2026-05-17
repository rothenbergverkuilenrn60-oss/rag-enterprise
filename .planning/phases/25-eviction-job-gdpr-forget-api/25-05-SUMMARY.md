---
phase: 25-eviction-job-gdpr-forget-api
plan: 05
subsystem: memory
tags: [eviction-cli, chunked-delete, asyncpg, audit-mode, enforce-mode, sweep, cron, pgvector, gdpr]

requires:
  - phase: 25-eviction-job-gdpr-forget-api / 25-01
    provides: "AuditAction.MEMORY_EVICT enum value, AuditResult.SKIPPED enum value, settings.memory_facts_cap_per_user (default 500)"
provides:
  - "scripts/evict_long_term_facts.py — operator CLI implementing EVICT-01 (chunked importance-tie-broken DELETE) + EVICT-02 (--mode={audit,enforce})"
  - "Per-bucket audit_log row with sweep_run_id correlation (D-2.4)"
  - "T1 contract: audit-write failure during sweep is loud-logged (operation='evict_audit_log') and does NOT abort the sweep"
  - "T8 contract: remaining_count in audit detail is re-fetched post-DELETE (concurrent-write-safe)"
affects: [25-06, 25-07]

tech-stack:
  added: []
  patterns:
    - "Analog 1 (verbatim backfill skeleton) with 4 documented swaps for eviction"
    - "Extended fake-pool harness with fetchrow (Analog 7) — supports side_effect lists for sequential COUNT calls (pre/post DELETE)"
    - "T1: try/except wrapper around audit_svc.log() with structured ERROR fallback log"
    - "T8: post-DELETE re-COUNT for accurate audit detail under concurrent writes"

key-files:
  created:
    - "scripts/evict_long_term_facts.py"
    - "tests/unit/test_evict_long_term_facts.py"
  modified: []

key-decisions:
  - "Audit failure NEVER aborts sweep (T1) — DELETE has already committed; the structured ERROR log is the recovery record so the operator can backfill the missing audit row manually"
  - "remaining_count is re-fetched via post-DELETE COUNT(*) (T8) — stale row_count - total_deleted arithmetic lies when save_fact / forget_user run concurrently"
  - "Audit-mode SKIPPED path is also wrapped in T1 try/except — same contract: log the would-be payload, continue the sweep"

patterns-established:
  - "Operator CLI shape (Analog 1): #!/usr/bin/env python + from __future__ + sys.path.insert + LongTermMemory()._get_pool() + setup_logger() inside main_async + audit_svc.flush() before exit"
  - "Per-bucket exception isolation: outer main_async catches (asyncpg.PostgresError, asyncpg.InterfaceError) and continues to the next bucket; CronJob restartPolicy: OnFailure handles sweep-level retry"
  - "T1 audit-failure log fields: operation='evict_audit_log' + audit_payload (the would-be detail dict) + user_id + tenant_id + sweep_run_id + mode + deleted_count + exc_info"
  - "T8 grep gate: stale 'remaining_count = row_count - total_deleted' arithmetic form must NOT appear (acceptance-time grep-banned)"

requirements-completed: [EVICT-01, EVICT-02]

duration: 6min
completed: 2026-05-16
---

# Phase 25 Plan 05: Eviction CLI Summary

**Chunked-DELETE eviction CLI with audit/enforce modes, T1 audit-fail-continues-sweep, and T8 post-DELETE re-COUNT for concurrent-write-safe audit detail.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-16T14:27:07Z
- **Completed:** 2026-05-16T14:32:48Z
- **Tasks:** 2 (RED + GREEN)
- **Files created:** 2

## Accomplishments

- New operator CLI `scripts/evict_long_term_facts.py` (361 LOC including docstrings) implementing EVICT-01 (chunked DELETE 1000 rows/txn, importance ASC + created_at ASC tie-break, idempotent) and EVICT-02 (`--mode={audit,enforce}`, `--batch-size`, `--user-id`).
- 11 RED→GREEN unit tests in `tests/unit/test_evict_long_term_facts.py` — covers both modes, idempotence at-cap, chunking, PG error propagation, sweep continuation across failed buckets, audit-detail fields, T1 audit-fail invariant, T8 re-COUNT invariant.
- T1 (eng-review Architecture A1): `audit_svc.log()` wrapped in try/except in BOTH audit-mode and enforce-mode branches; failure emits structured ERROR log with `operation="evict_audit_log"` and the would-be detail payload; sweep continues.
- T8 (eng-review outside voice F2): `remaining_count` in audit detail dict comes from a second `pool.fetchrow(SELECT COUNT(*) ...)` after the chunked DELETE loop — concurrent-write-safe.
- Pitfall 1 (register_vector codec): `LongTermMemory()._get_pool()` used; AST verification confirms zero `*.create_pool` call sites.
- Pitfall 2 (status string): `int(status.split()[1])` parses asyncpg DELETE return.
- Pitfall 4 (CLI runs many txns): batch loop catches `(asyncpg.PostgresError, asyncpg.InterfaceError)`.

## Task Commits

1. **Task 1: RED — eviction CLI unit tests** — `9da2813` (test)
2. **Task 2: GREEN — create scripts/evict_long_term_facts.py** — `e39dadb` (feat)

_Note: Task 2 commit also carries a small test fix (monkeypatch `setup_logger` to no-op + guarded handler removal in Test 11) — needed because main_async's internal `setup_logger()` call replaces loguru handlers mid-test._

## Files Created/Modified

- `scripts/evict_long_term_facts.py` — operator CLI: `evict_bucket()` + `main_async()` + `main()` with T1+T8 amendments
- `tests/unit/test_evict_long_term_facts.py` — 11 RED→GREEN tests + extended fake-pool harness with `fetchrow` (sequential side_effects for pre/post DELETE COUNT)

## Decisions Made

- **T1 contract scope**: Wrapped audit_svc.log() in BOTH audit-mode and enforce-mode branches (not just enforce). The audit-mode SKIPPED row is just as load-bearing for compliance reporting; same loud-log-and-continue semantics.
- **T8 grep ban form**: The acceptance check `grep -c 'remaining_count = row_count - total_deleted\|remaining_count=row_count - total_deleted'` enforces "no stale arithmetic". The implementation explicitly does the re-fetch in a dedicated `post_row = await pool.fetchrow(...)` line followed by `remaining_count = int(post_row["n"])`.
- **Docstring rewording for grep cleanliness**: The original Pitfall 1 docstring referenced `asyncpg.create_pool()` as an anti-pattern callout. The acceptance grep `grep -v '^#' | grep -c 'asyncpg.create_pool'` strips Python `#` comments but NOT triple-quoted docstrings, so the docstring text was triggering a false-positive match. Reworded the docstring to say "never the raw asyncpg pool factory directly" — preserves the safety guidance and AST-confirms zero call sites of `*.create_pool`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test 11 broke when main_async called setup_logger() mid-test**

- **Found during:** Task 2 (GREEN gate run)
- **Issue:** `test_evict_audit_write_failure_continues_sweep` added a loguru sink with `_logger.add(sink, level="ERROR")` BEFORE invoking `mod.main_async(...)`. main_async calls `setup_logger()` internally, which in turn calls `logger.remove()` to reset handlers — invalidating the test's handler_id. The `finally: _logger.remove(handler_id)` then raised `ValueError: There is no existing handler with id 3` and the test failed for the wrong reason.
- **Fix:** Monkeypatched `mod.setup_logger` to a no-op for this test (the test doesn't need real logger setup; it only needs the capture sink intact). Also wrapped `_logger.remove(handler_id)` in a `try/except ValueError: pass` for belt-and-suspenders.
- **Files modified:** `tests/unit/test_evict_long_term_facts.py` (Test 11 only)
- **Verification:** All 11 tests green; the sink correctly captures the `operation="evict_audit_log"` ERROR log; the T1 invariant assertions pass.
- **Committed in:** `e39dadb` (Task 2 commit — bundled with the GREEN script since the test is the gate for the GREEN script)

**2. [Rule 3 - Blocking] Docstring text triggered false positive on `asyncpg.create_pool` grep gate**

- **Found during:** Task 2 acceptance-gate verification
- **Issue:** Acceptance criterion required `grep -v '^#' scripts/evict_long_term_facts.py | grep -c 'asyncpg.create_pool'` to equal 0. The implementation correctly never CALLS `asyncpg.create_pool()` (AST walk confirmed zero call sites), but the module-level docstring contained the anti-pattern callout `"NEVER asyncpg.create_pool() directly"`. The grep filter `grep -v '^#'` strips Python `#` line-comments but NOT triple-quoted docstrings.
- **Fix:** Reworded the docstring callout from `"NEVER asyncpg.create_pool() directly"` to `"never the raw asyncpg pool factory directly"`. Preserves the safety guidance to future readers; satisfies the grep gate; AST-confirms zero call sites.
- **Files modified:** `scripts/evict_long_term_facts.py` (docstring only)
- **Verification:** `grep -v '^#' scripts/evict_long_term_facts.py | grep -c 'asyncpg.create_pool'` returns 0; all 11 tests still green; ruff clean.
- **Committed in:** `e39dadb` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 test-infra bug, 1 acceptance-gate false positive)
**Impact on plan:** Both auto-fixes are mechanical: one fixes a test harness invalidation by the production-code setup_logger() reset; the other fixes a grep filter that doesn't strip docstrings. No scope creep, no behavior change to the script.

## Issues Encountered

- None beyond the two deviations above.

## User Setup Required

None — no external service configuration required for this plan. The CLI requires `APP_MODEL_DIR` env var at runtime (project-wide invariant, already documented in CLAUDE.md OPS-01); the production k8s CronJob will inject this via the existing rag-api deployment env.

## Self-Check: PASSED

- `scripts/evict_long_term_facts.py` exists (361 LOC).
- `tests/unit/test_evict_long_term_facts.py` exists (605 LOC, 11 tests).
- Commits `9da2813` (test) and `e39dadb` (feat) both present in `git log --oneline`.
- `uv run pytest tests/unit/test_evict_long_term_facts.py -x -q` → 11 passed.
- `uv run ruff check scripts/evict_long_term_facts.py` → All checks passed.
- `APP_MODEL_DIR=/tmp SECRET_KEY=... uv run python scripts/evict_long_term_facts.py --help` exits 0 and shows `--mode`/`--batch-size`/`--user-id`.

### Grep Gates (Task 2 acceptance criteria)

| Gate | Required | Actual |
|---|---|---|
| `LongTermMemory()._get_pool()` | ≥1 | 1 |
| `int(status.split` | ≥1 | 2 |
| `ORDER BY importance ASC, created_at ASC` | ≥1 | 2 |
| `asyncpg.InterfaceError` | ≥1 | 4 |
| `AuditAction.MEMORY_EVICT` | ≥1 | 2 |
| `AuditResult.SKIPPED` | ≥1 | 1 |
| `AuditResult.SUCCESS` | ≥1 | 1 |
| `sweep_run_id` | ≥3 | 13 |
| `audit_svc.flush` | ≥1 | 2 |
| `asyncpg.create_pool` (no-call, post-strip) | =0 | 0 |
| `sys.path.insert` | =1 | 1 |
| **T1**: `except Exception as audit_exc` | ≥1 | 2 (both branches) |
| **T1**: `operation="evict_audit_log"` | ≥1 | 4 |
| **T1**: `noqa: BLE001` | ≥1 | 2 |
| **T8**: `SELECT COUNT(*) ... FROM long_term_facts` | ≥2 | 2 |
| **T8**: stale `remaining_count = row_count - total_deleted` | =0 | 0 |

## Threat Flags

None — all surface introduced by this plan is covered by the existing 25-05 PLAN.md `<threat_model>` register (operator shell → CLI is a known trust boundary; asyncpg queries are parameterized; audit_log is INSERT-only via Phase 2 REVOKE). T1 and T8 mitigations are implemented per the threat register's `mitigate` dispositions for T-25-05-R2 and T-25-05-R3 respectively.

## Next Phase Readiness

- Plan 25-05 (eviction CLI) is complete and unblocks Plan 25-06 (which validates the CLI against a real pgvector DB in `tests/integration/test_gdpr_forget_e2e.py` and tags the docker image for the CronJob).
- Wave 2 (Plans 25-04 + 25-05) can now hand off to Wave 3 (Plans 25-06 + 25-07).
- No outstanding TODOs or stubs. No deferred items.

---
*Phase: 25-eviction-job-gdpr-forget-api*
*Plan: 05*
*Completed: 2026-05-16*
