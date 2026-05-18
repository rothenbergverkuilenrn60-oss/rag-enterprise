# Phase 31 — Discussion Log

**Phase:** 31 — Event-Loop Leak Sweep
**Milestone:** v1.9 Hardening Round 3
**Date:** 2026-05-18
**Mode:** Default (no flags)
**Duration:** Single session

For human reference only — audits / retrospectives. Not consumed by downstream agents (researcher, planner, executor read CONTEXT.md instead).

## Initial Analysis

Domain: Enumerate residual module-level singletons that bind to import-time event loops, fix them via `create_app()` factory pattern (or per-test event_loop fixture for outliers), grow `_SINGLETON_INVENTORY` from 34 entries toward 48 on PG host.

Carry-forward applied (no re-discussion):
- `create_app()` factory pattern (v1.7 Phase 27 TD-02)
- Factory-default; outliers get per-test event_loop fixture (v1.8 Phase 30 EVT-01)
- Enumeration is execute-time, not context-time (v1.8 Phase 30)
- TDD relaxed for `type: execute` (v1.8 Phase 30)
- `tests/integration/conftest.py` autouse embedder/reranker mock active (v1.8 Phase 30-02)
- `_SINGLETON_INVENTORY` count = 34 (verified live)
- `docker rag-postgres pgvector/pgvector:pg16` healthy (verified live)

## Areas Selected for Discussion

User multiSelected ALL 4 presented gray areas:
1. Enumeration discovery pattern
2. Acceptance gate priority
3. Plan structure
4. Enumeration failure handling

## Area 1 — Enumeration Discovery Pattern

**Q:** Phase 30 used `grep 'no current event loop'` only. Should Phase 31 EVT-02 also catch `'attached to a different loop'` + `'got Future attached'` shapes?

**Options:**
1. Broader regex (3 error shapes) — **Recommended**
2. Phase 30 baseline only (1 shape)
3. Broader regex + RuntimeError catch-all

**User selection:** Broader regex (Recommended)

**Recorded as:** D-01 in CONTEXT.md

**Notes:** Phase 30 EVT-01 used shape 1 only → only ~4 sites surfaced + Plan 30-01 superseded. Shapes 2+3 catch asyncpg-style loop binding violations (more common with PG-backed services). Acceptance gate (D-02) is zero-error not "+N sites" — broader regex is safer because count is descriptive.

## Area 2 — Acceptance Gate Priority

**Q:** Zero-error gate (hard, observable) vs +14 site count (heuristic). If PG-host run finds 5 sites or 20 sites instead of ~10, which gate wins?

**Options:**
1. Zero-error gate dominates — **Recommended**
2. Site count gate dominates
3. Both required (intersection)

**User selection:** Zero-error gate dominates (Recommended)

**Recorded as:** D-02 in CONTEXT.md

**Notes:** Site count is descriptive, not prescriptive. Phase 30 precedent: "execute-time enumeration is truth; estimate is just a starting point." Rigid count gate risks padding or scope creep.

## Area 3 — Plan Structure

**Q:** Single plan 31-00 (~10 sites, Phase 30 cadence) OR split by area (memory / agent / nlu / misc)?

**Options:**
1. Single plan 31-00 — **Recommended**
2. Two plans: enumerate + remediate
3. Three plans: enumerate + remediate + verify

**User selection:** Single plan 31-00 (Recommended)

**Recorded as:** D-03 in CONTEXT.md

**Notes:** Matches Phase 30 single-plan cadence for EVT-class work. Site count is below the threshold that warrants wave-splitting. Atomic git commits within the plan provide the audit trail.

## Area 4 — Enumeration Failure Handling

**Q:** If PG-host suite hits unrelated skips/fails during enumeration (9 failed / 3 errors pre-existing from v1.8 close), do we filter them out + still enumerate, or abort + triage first?

**Options:**
1. Filter-then-enumerate — **Recommended**
2. Triage-first-then-enumerate
3. Exclude-known-failures-then-enumerate (deselect list)

**User selection:** Filter-then-enumerate (Recommended)

**Recorded as:** D-04 in CONTEXT.md

**Notes:** Triage-first inverts scope (Phase 33+34 own the pre-existing failures). Deselect-list rots. Filter-at-parse is robust because the 9+3 failures don't emit event-loop error messages — they're invisible to D-01 regex by construction.

## Deferred Ideas (Noted for Later)

- `_SINGLETON_INVENTORY` schema migration (add `category: str` per entry for per-area lint) — v1.10+ test-infra polish.
- Static-import-time analysis (AST scan flagging new module-level singletons) — v1.10+ tooling.
- `event_loop` fixture promotion to `tests/conftest.py` — only if outlier count surfaces a consistent pattern post-enumeration; deferred to executor decision.
- Phase 26-04 P1 backport to `LongTermMemory._get_pool` — same partial-init class of bug but different surface; v1.10+.

## Scope Creep Redirected

None. All 4 gray areas were narrow implementation choices within the locked phase boundary (EVT-02 acceptance).

## Claude's Discretion Items (not asked)

- Per-site factory-vs-fixture choice (decided at execute time per site).
- Commit message convention (`chore(31-00):` / `test(31-00):`).
- Whether to add new fixtures inline in `tests/integration/conftest.py` or per-test-file conftest.
- Logger level for any new test diagnostics (debug).
- Order of remediation across sites (alphabetical, by service area, by error shape).
- Whether to add a new helper in `tests/factories/app.py` for per-test event_loop creation (only if outlier count ≥ 3).

## Outcome

CONTEXT.md captures 4 decisions (D-01 through D-04) + 12 carry-forward entries + 11 codebase anchors + 9 canonical refs. Phase 31 ready for `/gsd-plan-phase 31`. Plan structure locked to single plan 31-00. Enumeration deferred to plan execute time per D-01 command and D-02 priority + D-04 filter handling.
