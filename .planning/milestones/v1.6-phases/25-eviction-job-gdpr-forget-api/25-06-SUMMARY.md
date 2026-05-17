---
phase: 25-eviction-job-gdpr-forget-api
plan: 06
subsystem: integration-tests
tags: [integration, pgvector, real-pg, e2e, eviction, gdpr-forget, audit-log-db, sc-1, sc-2, sc-3, sc-4]
requirements: [EVICT-01, EVICT-02, GDPR-01, GDPR-02, GDPR-03]
depends_on: [25-04, 25-05]
wave: 3
review_amendments_applied:
  - id: T4
    summary: "Both _seed_facts helpers insert embedding=[0.0] * 1024 (dummy 1024-dim zero vector). Future-proofs against schema tightening to NOT NULL."
provides:
  - "tests/integration/test_evict_long_term_facts_e2e.py — 4 eviction e2e tests covering SC-1 + SC-2"
  - "tests/integration/test_memory_forget_e2e.py — 4 forget API e2e tests covering SC-3 + SC-4"
requires:
  - "scripts/evict_long_term_facts.py (Plan 25-05) — main_async entry point"
  - "controllers/memory.py (Plan 25-04) — DELETE /api/v1/memory/forget route"
  - "services/memory/memory_service.py — LongTermMemory.forget_user"
  - "services/audit/audit_service.py — AuditAction.MEMORY_FORGET, get_audit_service, audit_db_enabled flag, flush()"
  - "tests/conftest.py — PG_AVAILABLE, pgvector_pool, clean_long_term_facts"
affects: []
tech_stack:
  added: []
  patterns:
    - "Analog 9 integration marker block (verbatim from test_recall_tool_planner_pick.py, single-line skipif for grep-friendliness)"
    - "Auth mock at services.auth.oidc_auth.get_auth_service singleton-factory (matches unit-test pattern from test_oidc_auth_dependency.py)"
    - "Pitfall 3 mitigation: monkeypatch settings.audit_db_enabled=True + await get_audit_service().flush() before audit_log SELECT"
    - "T4 future-proof seed: embedding=[0.0] * 1024 (dummy 1024-dim zero vector) on every long_term_facts INSERT"
key_files:
  created:
    - "tests/integration/test_evict_long_term_facts_e2e.py"
    - "tests/integration/test_memory_forget_e2e.py"
  modified: []
decisions:
  - "Inlined pytest.mark.skipif onto a single line so the acceptance-criteria grep regex (`pytest.mark.skipif.*PG_AVAILABLE`) matches without -P/-z multiline flags. Reference test_recall_tool_planner_pick.py uses a multi-line form but the plan's grep gate is the load-bearing contract."
  - "Auth mock pattern: monkeypatch services.auth.oidc_auth.get_auth_service (singleton-factory) rather than FastAPI app.dependency_overrides[get_current_user]. Mirrors test_oidc_auth_dependency.py's existing pattern, hits the same code path the real OIDC client takes, and avoids leaking overrides between tests."
  - "SC-4 audit-row test scope-purges any pre-existing audit_log rows for the test user_id before the forget call (with try/except for asyncpg.UndefinedTableError on first-run when the audit_log table hasn't been created yet). Ensures the assertion count is deterministic without DROP TABLE."
  - "test_forget_api_e2e_non_admin_403 is the only sync test — the 403 fires before any pool acquisition, so async harness isn't needed and a sync test exercises the role-gate-only path cleanly."
metrics:
  duration: "0h 28m"
  completed_date: "2026-05-16"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
  test_files: 2
  tests_added: 8
---

# Phase 25 Plan 06: Integration Tests for Eviction CLI + GDPR Forget API Summary

Production-grade pytest integration suite validating all four Phase 25 ROADMAP success criteria (SC-1 audit/enforce, SC-2 tie-break, SC-3 admin/idempotent/403, SC-4 audit_log DB row) against a live PostgreSQL + pgvector instance — 8 tests across 2 files, Analog 9 skip-gated for PG-less CI hosts.

## What Was Built

Two integration test files under `tests/integration/`:

1. **`test_evict_long_term_facts_e2e.py`** (4 tests — `15fefae`)
   - `test_audit_mode_no_deletes` — SC-1 audit half: 600-row + 100-row buckets seeded; `await main_async(mode="audit", ...)` emits stdout JSON-line with `over_cap_by=100` for the big bucket; row counts unchanged in PG (600 + 100).
   - `test_enforce_mode_caps_bucket` — SC-1 enforce half: 600-row bucket → 500 rows; 100-row bucket untouched.
   - `test_enforce_mode_small_bucket_untouched` — SC-1 corollary, standalone signal: under-cap bucket alone never loses rows.
   - `test_eviction_tiebreak_correctness` — SC-2: 3-row bucket (A: 0.2@T0, B: 0.2@T1, C: 0.8@T2) with cap=2; row A (oldest among lowest-importance) deleted via the ORDER BY importance ASC, created_at ASC clause; B + C survive.

2. **`test_memory_forget_e2e.py`** (4 tests — `95a026b`)
   - `test_forget_api_e2e_admin_200` — SC-3 admin path: 5-row seed → admin DELETE returns 200 + `deleted_row_count=5`; PG rows gone.
   - `test_forget_api_e2e_idempotent` — SC-3 idempotency: first call returns 5; second call (same headers) returns 0.
   - `test_forget_api_e2e_non_admin_403` — SC-3 auth gate: Bob (non-admin) attempts to forget Alice's data → 403 (role check before X-Confirm-Delete check per controller body order T9). Sync test — no DB seed needed.
   - `test_forget_api_audit_log_row` — SC-4: Pitfall 3 mitigation in full — `monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", True)` + `await get_audit_service().flush()` before `SELECT * FROM audit_log WHERE action='MEMORY_FORGET'`; asserts `detail.target_user_id`, `target_tenant_id`, `deleted_row_count=3`, `actor_user_id="admin-user"`.

Both files use the Analog 9 integration marker block (`pytest.mark.integration` + `pytest.mark.pgvector` + `pytest.mark.skipif(not PG_AVAILABLE, ...)`) so they collect on every host and SKIP gracefully when PostgreSQL is unreachable. No production code was modified.

## Validation Performed in This Run

| Gate | Command | Result |
|---|---|---|
| Combined collection | `uv run pytest tests/integration/test_evict_long_term_facts_e2e.py tests/integration/test_memory_forget_e2e.py --collect-only -q --override-ini="addopts="` | 8 tests collected |
| PG-unavailable skip | `uv run pytest <both files> -m pgvector -q --override-ini="addopts="` | 8 skipped, exit 0 |
| `pytest.mark.pgvector` present (both files) | grep | 1 match each |
| Single-line skipif gate | grep `pytest.mark.skipif.*PG_AVAILABLE` | 1 match each |
| T4 dummy embedding gate | grep `'\[0\.0\]\s*\*\s*1024'` | 6 matches in evict, 3 in forget (both ≥ 1) |
| Pitfall 3 mitigation | grep `audit_db_enabled.*True` + `flush()` + `MEMORY_FORGET` in forget file | 2 + 3 + 3 (all ≥ 1) |
| Tie-break (SC-2) | grep `tiebreak\|tie.break` in evict file | 5 |
| Audit/Enforce mode (SC-1) | grep `mode="audit"` / `mode="enforce"` | 1 + 3 |
| Auth path (SC-3) | grep `403` in forget file | 7 |
| Idempotent re-call (SC-3) | grep `deleted_row_count.*0` in forget file | 4 |
| X-Confirm-Delete header (SC-3) | grep `X-Confirm-Delete` in forget file | 2 |

## Important Limitation — PG-Skipped on This Run

PostgreSQL + pgvector is **not available** in the worktree execution environment. All 8 tests SKIP via `pytest.mark.skipif(not PG_AVAILABLE, ...)`. The acceptance criteria for live-PG behavior (SC-1 audit JSON-line shape, SC-1 enforce 600→500, SC-2 tie-break correctness, SC-3 200/idempotent/403, SC-4 audit_log row content) have been **specified and asserted in code** but **NOT exercised against a running database** in this run.

**Pre-tag manual verification required** (per 25-RESEARCH.md §Pre-tag Manual Verification): a developer must run `uv run pytest tests/integration/test_evict_long_term_facts_e2e.py tests/integration/test_memory_forget_e2e.py -m pgvector -x -q` on a PG-capable host (docker-compose up pg + pgvector extension) before the phase tag is cut. Expected outcome: 8 passed, 0 skipped.

If any test fails on the PG-capable host, the failure is real (assertions in the test code) and should drive a follow-up plan or amendment — not be silenced.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Multi-line `pytest.mark.skipif` would fail the plan's grep acceptance gate**
- **Found during:** Task 1 initial implementation.
- **Issue:** First draft followed the reference `test_recall_tool_planner_pick.py` shape (skipif arguments split across 4 lines). The plan's acceptance criterion `grep -n 'pytest.mark.skipif.*PG_AVAILABLE' <file>` matched 0 lines because `not PG_AVAILABLE` is on the next line from `pytest.mark.skipif(`.
- **Fix:** Inlined the skipif onto a single physical line in both files: `pytest.mark.skipif(not PG_AVAILABLE, reason="...")`.
- **Files modified:** Both test files (during Task 1, before Task 1 commit; Task 2 used the inline form from the start).
- **Commit:** Included in `15fefae` (Task 1).

No other deviations. All other plan instructions were executable as written.

## Known Stubs

None. Both files seed real data, drive real code paths, and assert real DB outcomes. Stub-shaped values (`embedding=[0.0] * 1024`, `Authorization: Bearer fake`) are intentional fixtures and documented inline:
- The dummy embedding is the T4 amendment (eviction never reads the column; the value is irrelevant).
- The `Bearer fake` token never reaches a JWT parser — the mocked `get_auth_service().verify_token` short-circuits to the configured AuthenticatedUser instance.

## Threat Flags

None. The threat surface introduced is purely test-only (synthetic user_ids, scoped DELETE in `clean_long_term_facts`, no UPDATE/DELETE on `audit_log` at the app layer). The SC-4 test's `DELETE FROM audit_log WHERE action='MEMORY_FORGET' AND resource_id=$1` runs **before** the forget call as a deterministic-baseline purge, scoped to a single synthetic test user_id, wrapped in try/except for `asyncpg.UndefinedTableError` on first-run. It does not violate the audit-log's INSERT-only invariant at the application layer (the REVOKE happens at the DB grant level on the production role, not the test role).

## Decisions Made

1. **Auth mock at `services.auth.oidc_auth.get_auth_service`** rather than `app.dependency_overrides[get_current_user]`. Matches the existing unit-test pattern (`tests/unit/test_oidc_auth_dependency.py`), exercises the same dependency-resolution code path the real OIDC service goes through, and avoids cross-test leakage of FastAPI dependency overrides.
2. **Inline single-line `skipif`** to satisfy the plan's grep-based acceptance gate without multiline-regex tooling.
3. **Scope-purge `audit_log` for the test user_id in the SC-4 test** (try/except UndefinedTableError) — guarantees the `count(*) == 1` assertion is deterministic even if prior tests on the same DB inserted MEMORY_FORGET rows. Does not violate the production INSERT-only grant policy because tests run under the developer role.
4. **`test_forget_api_e2e_non_admin_403` is the sole sync test.** The 403 fires before pool acquisition in the controller, so async harness adds no signal and a focused sync test exercises only the auth gate.

## Self-Check: PASSED

Files created (verified via `git log` for the two task commits):
- FOUND: `tests/integration/test_evict_long_term_facts_e2e.py` (commit `15fefae`)
- FOUND: `tests/integration/test_memory_forget_e2e.py` (commit `95a026b`)

Commits exist (verified via `git log --oneline`):
- FOUND: `15fefae test(25-06): eviction e2e integration tests — SC-1 + SC-2 (EVICT-01, EVICT-02)`
- FOUND: `95a026b test(25-06): GDPR forget API e2e integration tests — SC-3 + SC-4 (GDPR-01, GDPR-02, GDPR-03)`

Acceptance gates (all verified above):
- 8 tests collected in combined collection
- 8 skipped with `-m pgvector` on PG-less host (exit 0)
- All grep gates ≥ required threshold in both files
- T4 dummy embedding present in both `_seed_facts` helpers
- Pitfall 3 mitigation (audit_db_enabled=True + flush) present in SC-4 test

No modifications to `STATE.md` or `ROADMAP.md` — owned by the orchestrator (per worktree execution mode and explicit objective constraint).
