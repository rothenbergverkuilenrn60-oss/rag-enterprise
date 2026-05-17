---
phase: 25-eviction-job-gdpr-forget-api
plan: 07
subsystem: docs / coverage-accounting
tags: [docs, memory-eviction, cronjob-yaml, runbook, forget-api-curl, coverage-gate, diff-cover, evict-03-remark, phase-25-close]
requires:
  - 25-06-PLAN.md (integration tests landed; coverage XML basis available)
  - 25-05-PLAN.md (scripts/evict_long_term_facts.py — referenced by CronJob YAML)
  - 25-04-PLAN.md (controllers/memory.py — referenced by Forget API curl)
  - Plan 24-06 (existing docs/memory-eviction.md — preserved verbatim)
provides:
  - docs/memory-eviction.md (49 → 178 LOC, +129 lines; 5 new sections)
  - .planning/REQUIREMENTS.md EVICT-03 re-marked [x] with completion timestamp
affects:
  - EVICT-03 honest accounting cycle closes (un-marked by Plan 25-03 → re-marked by Plan 25-07)
tech-stack:
  added: []
  patterns:
    - "Append-only doc extension (existing Plan 24-06 sections preserved verbatim per Analog 10)"
    - "Verbatim YAML embed from RESEARCH.md §E6 — operator pastes into kubectl"
    - "Flat ## heading style (no internal anchor cross-links — T5 mechanical N/A for SC-5)"
key-files:
  created:
    - .planning/phases/25-eviction-job-gdpr-forget-api/25-07-SUMMARY.md
  modified:
    - docs/memory-eviction.md (49 → 178 LOC; 5 new sections appended)
    - .planning/REQUIREMENTS.md (EVICT-03 line: [ ] → [x] + completion timestamp)
decisions:
  - "Coverage measured over FULL unit suite (minus pre-existing collection-error files), not Phase 25 tests alone. Reason: services/memory/memory_service.py has Phase 23/24-tested methods (save_fact, recall_facts) that Phase 25 tests do not exercise. Per-module ≥ 70% achievable only when phase-23/24 unit tests also run."
  - "Three pre-existing unit-test collection errors (test_ab_test_service.py, test_ingest_status.py, test_memory_service.py — missing fakeredis import) excluded via --ignore. Pre-existing Phase 24 issue, unrelated to Phase 25 scope (see Deferred Issues)."
  - "32 pre-existing test failures kept as baseline (Phase 24 Redis-connection failures, documented in 25-RESEARCH.md and the orchestrator prompt). No NEW Phase 25 regressions."
  - "STATE.md / ROADMAP.md updates left to orchestrator (worktree mode policy in <parallel_execution>)."
metrics:
  duration: "~11 min"
  completed: 2026-05-16
  tasks_completed: 2/2
  commits: 2
---

# Phase 25 Plan 07: Docs Extension + Coverage Gate + EVICT-03 Re-mark — Summary

Final Wave 4 plan. Extended `docs/memory-eviction.md` from 49 → 178 LOC with 5 new operator-facing sections (cron schedule + cap, audit mode workflow, enforce mode, verbatim CronJob YAML, forget API curl + cross-tenant doc note), executed the coverage gate (≥ 70% per Phase 25 module) and diff-cover gate (≥ 80% on touched lines), and re-marked EVICT-03 `[x]` to close the D-4.1 honest accounting cycle that Plan 25-03 had opened.

## Tasks

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Extend docs/memory-eviction.md with 5 new sections | `4166939` | docs/memory-eviction.md |
| 2 | Coverage gate + diff-cover gate + re-mark EVICT-03 | `fd00680` | .planning/REQUIREMENTS.md |

## Task Detail

### Task 1 — docs/memory-eviction.md (49 → 178 LOC)

Appended 5 new sections after the existing Plan 24-06 content (no rewrites; existing
sections — `## Cost Formula`, `## Backfill — Run Once`, `## Failure Modes`,
`## Recurring Backfill` — preserved verbatim):

1. **`## Eviction — Schedule & Cap`** — default cap 500, env override `MEMORY_FACTS_CAP_PER_USER`, daily 03:00 UTC schedule, cap-tuning workflow (audit → ~95th-percentile + 20% headroom → ConfigMap update → re-audit → enforce), enforce-mode warning (no preflight; audit-first is operator discipline).
2. **`## Audit Mode Workflow`** — stdout JSON-line shape per D-3.1: `{"bucket": {...}, "row_count": ..., "over_cap_by": ..., "would_delete_count": ..., "sweep_run_id": ...}`; jq pipeline example to surface heavy buckets.
3. **`## Enforce Mode`** — deletion order (importance ASC, created_at ASC), 1000-row chunking, idempotency, partial-sweep recovery via CronJob `restartPolicy: OnFailure`, `AUDIT_DB_ENABLED=true` writes `audit_log` rows, tie-break worked example.
4. **`## CronJob YAML`** — verbatim §E6 YAML block (apiVersion, kind, schedule `0 3 * * *`, `successfulJobsHistoryLimit: 3`, `failedJobsHistoryLimit: 1`, restartPolicy OnFailure, PG_DSN secretKeyRef, MEMORY_FACTS_CAP_PER_USER configMapKeyRef, AUDIT_DB_ENABLED "true", resource requests/limits). Field notes call out AUDIT_DB_ENABLED criticality (Pitfall 3 from `25-RESEARCH.md`).
5. **`## Forget API`** — DELETE endpoint shape, scope (`long_term_facts` ONLY per D-1.2), admin-vs-self authorization, **T3 cross-tenant 200/0 doc note** (admin in tenant A targeting user in tenant B receives `200 + deleted_row_count=0`; "the user has no facts in YOUR tenant"), curl example with admin JWT + `X-Confirm-Delete: yes`, **T9 order-of-failures note** (role-403 wins over header-400), error-code table.

**Acceptance gates verified post-edit:**

| Gate | Result |
|------|--------|
| `wc -l docs/memory-eviction.md` (target 120–180) | **178** ✓ |
| 5 new section headings present (each `== 1`) | ✓✓✓✓✓ |
| Total `^## ` headings (≥ 9) | **9** ✓ (4 existing + 5 new) |
| Existing `## Cost Formula \| ## Backfill` preserved | **2** ✓ |
| `0 3 \* \* \*` (CronJob schedule) | **1** ✓ (≥ 1) |
| `successfulJobsHistoryLimit` (history bound) | **2** ✓ |
| `X-Confirm-Delete` (forget API curl marker) | **3** ✓ |
| `AUDIT_DB_ENABLED` (Pitfall 3 marker) | **3** ✓ |
| T3 — `"your tenant"` cross-tenant doc note | **1** ✓ |
| T5 — anchor cross-links `](#` (must = 0) | **0** ✓ (SC-5 mechanical N/A) |

### Task 2 — Coverage gate + diff-cover gate + EVICT-03 re-mark

**Step 1 — Coverage gate (per-module ≥ 70%):**

Phase 25 unit-only run (4 test files, 34 tests) gave `services/memory/memory_service.py`
only 41% because the test suite intentionally targets the *new* methods (`forget_user`,
audit/evict CLI surface). Memory_service's full surface (save_fact, recall_facts, etc.)
is exercised by Phase 23/24 unit tests. So coverage was re-run over the full
`tests/unit/` (minus three pre-existing collection-error files) with the same `--cov`
modules; result:

```
Name                                Stmts   Miss  Cover   Missing
-----------------------------------------------------------------
controllers/memory.py                  31      1  96.8%   70
scripts/evict_long_term_facts.py       84     15  82.1%   148-149, 189, 227-228, 262, 277-284, 324-349
services/memory/memory_service.py     210     12  94.3%   98-101, 275-276, 448-449, 467-468, 479-480, 600
-----------------------------------------------------------------
TOTAL                                 325     28  91.4%
```

All three Phase 25 modules ≥ 70% ✓. Total 91.4%, threshold 70% — gate green.

**Step 2 — diff-cover gate (≥ 80% on Phase 25 touched lines):**

```
Diff: origin/master...HEAD
controllers/memory.py             (96.8%): Missing lines 70
scripts/evict_long_term_facts.py  (82.1%): Missing 148-149, 189, 227-228, 262, 277, 283-284, 324, 327, 334, 341, 348-349
services/memory/memory_service.py (100%)
-------------
Total:   166 lines
Missing: 16 lines
Coverage: 90%
```

**90% ≥ 80%** ✓. Exit 0.

**Step 3 — Full unit suite baseline (no NEW regressions):**

```
============ 32 failed, 1118 passed, 2 skipped, 402 warnings in ~21s ============
```

- **34/34 Phase 25 tests pass** (clean run: `pytest tests/unit/test_evict_long_term_facts.py tests/unit/test_memory_forget.py tests/unit/test_memory_controller.py tests/unit/test_phase25_foundations.py` → 34 passed, exit 0)
- **32 pre-existing failures** match the prompt's documented Phase 24 Redis-dependent baseline (`agent_pipeline_refactor`, `agent_sse`, `feedback_ab_forward`, `pipeline_coverage` — all manifest as `redis.exceptions.ConnectionError: Error 111` in isolation; no Redis server in this environment by design — PG also unavailable per orchestrator prompt)
- **0 NEW Phase 25 regressions**

**Step 4 — Re-mark EVICT-03:**

- `.planning/REQUIREMENTS.md` line 52: `- [ ] **EVICT-03**:` → `- [x] **EVICT-03**:`
- Appended: `**Completed 2026-05-16 — Phase 25 Plan 07 (docs extension 49→178 LOC + coverage ≥ 70% per module on all 3 Phase 25 modules + diff-cover 90% ≥ 80% all gates green).**`
- `grep 'EVICT-03' .planning/REQUIREMENTS.md | grep -c '\[x\]'` = **1** ✓
- `Completed 2026-05` present in the multi-line EVICT-03 entry (verified via `awk '/^- \[x\] \*\*EVICT-03/,/^$/'`) ✓

The original entry retains the Plan 25-03 un-mark NOTE explaining the cycle ("Un-marked
from `[x]` to `[ ]`. ... Re-mark `[x]` at Phase 25 verifier close.") — kept for honest
accounting auditability.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Coverage `--cov` argument syntax — filesystem-path → dotted module path**

- **Found during:** Task 2 Step 1 (first coverage gate run)
- **Issue:** `--cov=services/memory/memory_service` (as written in plan command) yielded `CoverageWarning: Module services/memory/memory_service was never imported. (module-not-imported)` and "No data was collected." Coverage 0.0%. This is a path-vs-module-name confusion in the plan command.
- **Fix:** Switched all three to dotted-module form: `--cov=services.memory.memory_service --cov=controllers.memory --cov=scripts.evict_long_term_facts`. coverage.py recognized the modules and collected data.
- **Files modified:** none (CLI invocation only)
- **Commit:** captured in Task 2 commit `fd00680` (gate logic; no source change needed)

**2. [Rule 3 - Blocking] Three pre-existing collection-error files block full-suite coverage run**

- **Found during:** Task 2 Step 1 (full-suite coverage)
- **Issue:** `tests/unit/test_ab_test_service.py`, `tests/unit/test_ingest_status.py`, and `tests/unit/test_memory_service.py` all `ImportError: No module named 'fakeredis'` at collection time. Pre-existing Phase 24 issue (these test files reference an unpinned optional dep). Causes `Interrupted: 3 errors during collection` and prevents any coverage from being produced for the full suite.
- **Fix:** Added `--ignore=tests/unit/test_ab_test_service.py --ignore=tests/unit/test_ingest_status.py --ignore=tests/unit/test_memory_service.py` to the pytest invocation. With those excluded, the suite collects + runs: 1118 passed, 32 failed (baseline), 2 skipped.
- **Note logged to deferred:** `fakeredis` missing — should be added as a test-time dep in pyproject.toml in a future Phase 24 follow-up (see Deferred Issues).
- **Files modified:** none (CLI invocation only)
- **Commit:** captured in Task 2 commit `fd00680`

**3. [Rule 4 — not invoked, but flagged for transparency] Coverage scope interpretation**

The plan's success_criteria from the prompt said "Coverage gate uses UNIT tests only on
Phase 25 modules per plan command" and listed the 4 Phase 25 test files. The plan's
`<action>` block said `tests/unit/`. The plan's `<verify>` block said `tests/unit/`.
For per-module ≥ 70% on `services/memory/memory_service.py` to be achievable, the full
unit suite must run (Phase 23/24 tests cover the non-Phase-25 methods). I chose the
full-suite path (matching `<action>` and `<verify>`) and documented both runs here.
**No architectural change** — just a scope choice within plan-allowed interpretations.

## Deferred Issues

These are out-of-scope for Plan 25-07 and not regressions Phase 25 introduced. Logged
for future remediation:

| Item | File / Component | Pre-existing as of | Suggested phase |
|------|------------------|--------------------|-----------------|
| 3 unit test files fail to collect — `fakeredis` import missing | `tests/unit/test_ab_test_service.py`, `test_ingest_status.py`, `test_memory_service.py` | Phase 24 (or earlier) | Test-infra cleanup phase; add `fakeredis` as dev dep |
| 32 pre-existing Redis-connection failures in agent_pipeline / agent_sse / pipeline_coverage / feedback_ab_forward | Various | Phase 24 (documented) | Provision Redis in test env, or refactor to use `fakeredis` |
| 1 uncovered line in `controllers/memory.py` (line 70) | Defensive branch in forget controller | Phase 25 (this) | Minor; non-blocking; defer to v1.7 polish |
| 15 uncovered lines in `scripts/evict_long_term_facts.py` (mostly `__main__` argparse + error-path branches around lines 277-284, 324-349) | CLI entry, exception print branches | Phase 25 (this) | Acceptable; CLI argparse is integration-tested via 25-06 |

## Known Stubs

None. No placeholder data wired into UI components; no hardcoded empty returns. All
new doc content is concrete; the YAML block is a deployable manifest verbatim from
`25-RESEARCH.md §E6`.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced by this plan
(docs + accounting only). The CronJob YAML embedded as documentation does not deploy
itself.

## Files Touched

```
docs/memory-eviction.md            | 129 ++++++++++++++++++++++++++++++++++++++
.planning/REQUIREMENTS.md          |   2 +-
.planning/phases/25-eviction-job-gdpr-forget-api/25-07-SUMMARY.md | (this file)
```

## Phase 25 Close Note

EVICT-03 is the final un-marked Phase 25 requirement. With `[x]` set + timestamp, the
D-4.1 honest accounting cycle that Plan 25-03 opened closes here. All 6 Phase 25
requirements (EVICT-01, EVICT-02, EVICT-03, GDPR-01, GDPR-02, GDPR-03) are now in a
verifier-evaluable state; Wave 4 is complete. STATE.md/ROADMAP.md updates left to the
orchestrator (worktree-mode policy).

## Self-Check: PASSED

```
[ Files exist ]
FOUND: docs/memory-eviction.md
FOUND: .planning/REQUIREMENTS.md
FOUND: .planning/phases/25-eviction-job-gdpr-forget-api/25-07-SUMMARY.md

[ Commits in branch ]
FOUND: 4166939  (docs(25): extend memory-eviction.md ...)
FOUND: fd00680  (docs(25): re-mark EVICT-03 [x] ...)

[ Acceptance markers ]
5 new section headings present  ✓
1 `[x] **EVICT-03**` line in REQUIREMENTS.md  ✓
178 LOC in docs/memory-eviction.md (target 120–180)  ✓
0 anchor cross-links in docs/memory-eviction.md (T5)  ✓
```

No missing items. Final metadata commit follows.
