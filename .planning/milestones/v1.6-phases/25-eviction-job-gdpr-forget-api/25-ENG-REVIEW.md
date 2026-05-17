# Phase 25 Eng Review — 2026-05-16

**Reviewer:** `/plan-eng-review` (Claude Opus 4.7 + Claude subagent outside voice)
**Branch:** master
**Commit at review:** e6dc73e
**Phase plans reviewed:** 25-01..25-07 (7 plans, 4 waves)
**Plan-check baseline:** PASS-WITH-WARNINGS (0 blockers, 3 warnings W1–W3, 1 info)

## Decisions Applied (must land before /gsd-execute-phase 25)

Nine decisions captured during interactive review. Five from primary review, four from outside voice (Claude subagent). Each amends one or more plan files.

| # | Decision | Plan(s) affected | Effort (human / CC) |
|---|----------|------------------|---------------------|
| T1 | **Audit-write failure handling.** Wrap `audit_svc.log()` in try/except in BOTH forget controller AND eviction script. Loud structured log with full would-be detail payload. Never propagate to caller (forget returns 200; sweep loop continues). New unit tests: `test_forget_audit_write_failure_returns_200` + `test_evict_audit_write_failure_continues_sweep`. | 04, 05 | 45 min / 8 min |
| T2 | **Tighten 25-04 mount-point spec.** Existing pattern: `controllers/api.py:44` defines `router = APIRouter(prefix=settings.api_prefix)`, `main.py:386` mounts via `app.include_router(router)`. Plan 25-04 must name `main.py` as the mount file. `files_modified` swaps `controllers/__init__.py` → `main.py`. Acceptance grep gate tightens from `grep "memory" controllers/__init__.py` to `grep "include_router(memory_router)" main.py`. (Resolves plan-check W3; absorbs outside-voice F5.) | 04 | 10 min / 2 min |
| T3 | **Cross-tenant admin forget semantics.** Document 200/deleted=0 behavior (admin from tenant A querying user that lives in tenant B → idempotent no-op, admin is JWT-scoped). Add unit test `test_forget_cross_tenant_unreachable_returns_200_zero`. Add one note to OpenAPI doc + 25-07 Forget API section: "200 + deleted=0 means user has no facts in your tenant." | 04, 07 | 10 min / 2 min |
| T4 | **Integration test seed: dummy `[0.0]*1024` vector.** Column `embedding` is nullable today (`services/memory/memory_service.py:211` — `ALTER ADD COLUMN IF NOT EXISTS embedding vector(1024)` without NOT NULL). Future-proof against schema tightening; matches Phase 23 MEM-02 zero-partial-write invariant. (Resolves plan-check W2.) | 06 | 5 min / 1 min |
| T5 | **SC-5 anchor verification N/A annotation + grep gate.** Doc has only flat `## section` headings, no `[text](#anchor)` cross-links. Annotate SC-5 "no anchor links — mechanically N/A" in 25-07 acceptance_criteria. Add gate `grep -c '\](#' docs/memory-eviction.md` equals 0. (Resolves plan-check W1.) | 07 | 3 min / 30 sec |
| T6 | **Reject `MEMORY_FACTS_CAP_PER_USER=0` at settings-load.** Pydantic V2 `Field(default=500, ge=1)` rejects zero/negative. T-25-01-D1 STRIDE disposition flips from "accept" to "mitigate". Closes P1 total-data-loss-from-typo failure mode. (Outside voice F4.) | 01 | 2 min / 30 sec |
| T7 | **Chunk `LongTermMemory.forget_user` DELETE at 1000 rows/txn.** Mirror `evict_bucket` chunked-loop pattern: `DELETE ... WHERE id IN (SELECT id ... WHERE user_id=$1 AND tenant_id=$2 LIMIT 1000)` until `"DELETE 0"`, sum total, audit ONCE with total. Eliminates statement_timeout failure on large pre-eviction buckets; reduces lock-contention window with concurrent cron sweep. New unit test: `test_forget_user_chunks_large_bucket`. (Outside voice F1.) | 02 | 30 min / 5 min |
| T8 | **Re-COUNT post-DELETE for evict audit `remaining_count`.** Plan 25-05 currently sets `remaining_count = row_count - total_deleted` from the stale pre-DELETE COUNT. Under concurrent save_fact / forget_user, that field lies in the audit row. Replace with `await pool.fetchval("SELECT COUNT(*) FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2", user_id, tenant_id)` just before building AuditEvent. Preserves chunked-1000/txn EVICT-01 contract. (Outside voice F2.) | 05 | 10 min / 2 min |
| T9 | **Reorder forget controller body: role-check 403 before header-check 400.** Skeleton currently runs header check first → non-admin with missing header gets 400 instead of 403, leaking endpoint existence. Reorder: `is_admin or user.user_id == target_user_id` → 403, then `x_confirm_delete != "yes"` → 400. New unit test: `test_forget_non_admin_no_header_returns_403`. Add VALIDATION matrix row: "non-admin + no header → 403 (role wins)." (Outside voice F3.) | 04 | 5 min / 1 min |

## Plans Affected Summary

| Plan | Decisions | Net change |
|------|-----------|-----------|
| 01 | T6 | `memory_facts_cap_per_user: int = Field(default=500, ge=1)`; acceptance grep gate for `ge=1` literal; STRIDE T-25-01-D1 flips to mitigate |
| 02 | T7 | Chunk forget_user at 1000 rows/txn; mirror evict_bucket pattern; one extra unit test |
| 03 | — | None (single-line REQUIREMENTS.md un-mark) |
| 04 | T1, T2, T3, T9 | Audit-write try/except; mount in `main.py:~386` w/ tightened grep; cross-tenant test; reorder role-403 before header-400; new tests |
| 05 | T1, T8 | Audit-write try/except in sweep loop; re-COUNT post-DELETE for `remaining_count`; one extra unit test |
| 06 | T4 | Seed helper uses `embedding=[0.0]*1024` |
| 07 | T3, T5 | Cross-tenant 200/0 doc note in Forget API section; SC-5 N/A annotation + `grep -c '\](#' ...` equals 0 gate |

## NOT in Scope (deferred, with rationale)

| Item | Rationale | When |
|------|-----------|------|
| `save_fact` pre-INSERT cap check | Changes extractor contract; re-evaluate after audit-mode data | v1.7+ |
| Forget API extension to short-term + user_profile | D-1.2 v1.6 scope = `long_term_facts` ONLY; partial-failure handling design needed | v1.7+ |
| Per-tenant capacity overrides + importance decay | Carry-forward from STATE.md Open Question §5 | v1.7+ |
| Cap auto-tuning from observed percentiles | Need real bucket distribution first | v1.7+ |
| Audit-log enforce-mode preflight (code-enforced) | D-3.2 runbook-over-bulletproof; re-evaluate after real incident | v1.7+ |
| `docs/memory-ops.md` rename | Defer broader doc consolidation | v1.7+ |
| Bulk-forget admin endpoint (`?tenant_id=X`) | Tenant-offboarding flow; out of v1.6 scope | v1.7+ |
| Audit-log query/dashboard UI | v1.0 Phase 2 ships write path only | v1.7+ |
| RLS enforcement on `long_term_facts` | Carry-forward from v1.0 Phase 2 | v1.7+ |
| `markdown-link-check` invocation | Replaced by grep-gate-equals-0 (T5) | If anchor links ever added |
| Atomic single-statement `DELETE ... OFFSET cap` form for eviction | Breaks chunked-1000/txn EVICT-01 contract; T8 cheaper fix | N/A |
| Existence check for "user exists in any tenant" before 200/0 | Cross-tenant leak vs forged-JWT-only attack — T3 doc note sufficient | N/A |

## What Already Exists (heavily reused, good)

| New thing | Built on |
|-----------|----------|
| `MEMORY_FORGET` + `MEMORY_EVICT` enum | `services/audit/audit_service.py::AuditAction` (12 existing values verbatim) |
| `audit_svc.log(AuditEvent(...))` calls | `services/audit/audit_service.py` `AuditEvent` Pydantic shape; `_flush_to_db` batched writes |
| `MemoryForgetError` | Phase 23 `MemoryFactWriteError` at `services/memory/memory_service.py` (frozen Pydantic exception shape) |
| `LongTermMemory.forget_user` | Phase 23 `save_fact` narrow-exception pattern (`except asyncpg.PostgresError` + structured log + typed raise) |
| `controllers/memory.py` DELETE endpoint | `controllers/api.py:400` `@router.delete("/cache", tags=["admin"])` template; `Depends(get_current_user)` from `services/auth/oidc_auth.py` |
| `evict_long_term_facts.py` CLI shape | Phase 24 `scripts/backfill_fact_embeddings.py` (argparse, asyncio.run, `LongTermMemory()._get_pool()` reuse, chunked txn) |
| Audit INSERT-only invariant | v1.0 Phase 2 `audit_log` table REVOKE UPDATE, DELETE; Phase 25 INSERTs only |

## Failure Modes (per new codepath)

| Codepath | Failure | Test | Error handling | User visibility |
|----------|---------|------|----------------|-----------------|
| `forget_user` chunked DELETE | statement_timeout on one chunk | T7 large-bucket test | asyncpg.PostgresError → MemoryForgetError → 500 | Loud structured log + 500 to client; retry safe (auto-commit) |
| `forget_user` audit-write fail | `audit_svc.log()` raises | T1 forget-audit-fail test | try/except → loud log w/ payload, return 200 anyway | 200 success to client; operator sees ERROR-level log |
| Eviction sweep audit-write fail | `audit_svc.log()` raises mid-loop | T1 evict-audit-fail test | try/except → loud log w/ payload, continue to next bucket | exit 0; operator sees ERROR-level log per failed bucket |
| Eviction concurrent with forget | COUNT/DELETE race → stale `remaining_count` | covered by re-COUNT in T8 | re-COUNT post-DELETE | Audit detail accurate even under race |
| Forget cross-tenant admin attempt | DELETE matches 0 rows | T3 cross-tenant test | None needed — documented as idempotent 200/0 | 200 + deleted=0; doc note explains |
| Forget non-admin missing header | 403 wins over 400 (post-T9) | T9 non-admin-no-header test | role check returns 403 first | Consistent fail-closed-on-identity |
| cap=0 env var | Pydantic validator rejects | grep gate for `ge=1` | Settings-load fails | CronJob/API process exits before any DB write |
| Mid-sweep crash recovery | Partial sweep + audit rows for buckets done | None (runbook); CronJob `restartPolicy: OnFailure` | Re-running sweep is idempotent (re-fetches over-cap buckets); audit row count > bucket count is acceptable | Documented in `docs/memory-eviction.md` |

**Critical gaps (no test AND no error handling AND silent failure):** **0.**

## Coverage Diagram

See conversation output above (also captured in test-plan artifact `~/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-master-eng-review-test-plan-20260516-211800.md`).

Summary: 38/40 paths (95%), code paths 28/30 (93%), user flows 10/10 (100%), 32 ★★★ / 5 ★★ (NEW from amendments) / 0 ★. Remaining gaps: `forget_user` InterfaceError handling (CLI catches both per Pitfall 4; FastAPI request-handler single-txn — defer to T7 chunked path), mid-sweep crash recovery e2e (runbook-acceptable).

## Worktree Parallelization Strategy

After amendments land, wave structure preserved:

| Step | Modules touched | Depends on |
|------|----------------|------------|
| 25-01 (settings + audit enum) | config/, services/audit/, tests/unit/ | — |
| 25-02 (forget_user method) | services/memory/, tests/unit/ | — |
| 25-03 (EVICT-03 un-mark) | .planning/ | — |
| 25-04 (forget controller) | controllers/, main.py, tests/unit/ | 25-01, 25-02 |
| 25-05 (eviction CLI) | scripts/, tests/unit/ | 25-01 |
| 25-06 (integration tests) | tests/integration/ | 25-02, 25-04, 25-05 |
| 25-07 (docs + verifier + EVICT-03 re-mark) | docs/, .planning/ | 25-06 |

**Lane A:** 25-01 → 25-04 (sequential — 25-04 reads new enum)
**Lane B:** 25-02 (independent of 01; mirrors save_fact pattern)
**Lane C:** 25-03 (disjoint — .planning/ only)
**Lane D:** 25-05 (after 25-01 — needs new enum + settings field)
**Lane E:** 25-06 → 25-07 (sequential after 02 + 04 + 05)

**Execution order:** Wave 1 — A1 (25-01) ‖ B (25-02) ‖ C (25-03). Wave 2 — A2 (25-04) ‖ D (25-05) [no shared module; A2 touches controllers/main.py, D touches scripts/]. Wave 3 — 25-06. Wave 4 — 25-07.

**Conflict flags:** None. Lane A2 (25-04) and Lane D (25-05) are disjoint module dirs.

**Phase 24 lesson applied:** Some Phase 24 worktrees forked from stale base; cherry-pick remediation worked but added friction. For Phase 25, recommend **sequential on master per wave** if context budget allows, OR `isolation="worktree"` from current HEAD `e6dc73e` to avoid stale-base risk.

## Cross-Model Tension (summary)

| Topic | Primary review | Outside voice (Claude subagent) | Resolution |
|-------|---------------|-------------------------------|------------|
| F1 forget_user chunking | Missed | Chunk DELETE at 1000/txn | Accepted (T7) |
| F2 audit remaining_count race | Missed | Re-COUNT post-DELETE | Accepted (T8) |
| F3 400/403 order | Missed | Reorder role-403 first | Accepted (T9) |
| F4 cap=0 silent wipe | Missed | Field(ge=1) | Accepted (T6) |
| F5 mount grep trivial | T2 already covered mount-point but grep was loose | Tighten grep to `include_router(memory_router) main.py` | Folded into T2 |

**4 of 5 outside voice findings landed substantively.** Mirrors Phase 24 precedent (5/6 substantive points right). No primary-review findings overturned by outside voice.

## Unresolved Decisions

**None.** All 11 substantive findings resolved (9 amendments accepted, 2 follow-on observations documented).

## Implementation Tasks

Synthesized from this review's findings. Each task derives from a specific finding above. Run with Claude Code or Codex; checkbox as you ship.

- [ ] **T1 (P1, human: ~45min / CC: ~8min)** — controllers/memory.py + scripts/evict_long_term_facts.py — Wrap `audit_svc.log()` in try/except in both surfaces
  - Surfaced by: Architecture — audit-write failure handling
  - Files: `controllers/memory.py`, `scripts/evict_long_term_facts.py`, `tests/unit/test_memory_controller.py`, `tests/unit/test_evict_long_term_facts.py`
  - Verify: `uv run pytest tests/unit/test_memory_controller.py tests/unit/test_evict_long_term_facts.py -k "audit_write_fail" -x -q` passes (2 GREEN)
- [ ] **T2 (P1, human: ~10min / CC: ~2min)** — controllers/memory.py + main.py — Tighten 25-04 mount-point: define `router` in controllers/memory.py with `prefix=settings.api_prefix`, add `app.include_router(memory_router)` near `main.py:386`
  - Surfaced by: Architecture / Plan-check W3
  - Files: `controllers/memory.py`, `main.py`, `.planning/phases/25-eviction-job-gdpr-forget-api/25-04-PLAN.md`
  - Verify: `grep -c "include_router(memory_router)" main.py` equals 1
- [ ] **T3 (P2, human: ~10min / CC: ~2min)** — controllers/memory.py + docs/memory-eviction.md — Cross-tenant test + doc note
  - Surfaced by: Code Quality — GDPR tenant boundary
  - Files: `tests/unit/test_memory_controller.py` (add `test_forget_cross_tenant_unreachable_returns_200_zero`), `docs/memory-eviction.md` (Forget API section)
  - Verify: `uv run pytest tests/unit/test_memory_controller.py::test_forget_cross_tenant_unreachable_returns_200_zero -x -q` passes; `grep -c "your tenant" docs/memory-eviction.md` ≥ 1
- [ ] **T4 (P2, human: ~5min / CC: ~1min)** — tests/integration — Seed helper uses dummy `[0.0]*1024` vector
  - Surfaced by: Test review / Plan-check W2
  - Files: `tests/integration/test_evict_long_term_facts_e2e.py` (seed fixture), `.planning/phases/25-eviction-job-gdpr-forget-api/25-06-PLAN.md`
  - Verify: `grep -c "\[0.0\] \* 1024\|\[0.0\]\*1024" tests/integration/test_evict_long_term_facts_e2e.py` ≥ 1
- [ ] **T5 (P3, human: ~3min / CC: ~30sec)** — 25-07-PLAN.md + docs/memory-eviction.md — SC-5 N/A annotation + grep gate equals 0
  - Surfaced by: Test review / Plan-check W1
  - Files: `.planning/phases/25-eviction-job-gdpr-forget-api/25-07-PLAN.md`
  - Verify: `grep -c '\](#' docs/memory-eviction.md` equals 0 (added to 25-07 acceptance_criteria)
- [ ] **T6 (P1, human: ~2min / CC: ~30sec)** — config/settings.py — `memory_facts_cap_per_user: int = Field(default=500, ge=1)`
  - Surfaced by: Outside voice F4
  - Files: `config/settings.py`, `tests/unit/test_phase25_foundations.py` (add `test_memory_facts_cap_zero_rejected`), `.planning/phases/25-eviction-job-gdpr-forget-api/25-01-PLAN.md`
  - Verify: `python -c "from config.settings import Settings; Settings(memory_facts_cap_per_user=0)"` raises ValidationError
- [ ] **T7 (P2, human: ~30min / CC: ~5min)** — services/memory/memory_service.py — Chunk forget_user DELETE at 1000 rows/txn
  - Surfaced by: Outside voice F1
  - Files: `services/memory/memory_service.py`, `tests/unit/test_memory_forget.py` (add `test_forget_user_chunks_large_bucket`)
  - Verify: `uv run pytest tests/unit/test_memory_forget.py::test_forget_user_chunks_large_bucket -x -q` passes; `grep -c "LIMIT 1000\|batch_size" services/memory/memory_service.py` ≥ 1 in forget_user body
- [ ] **T8 (P3, human: ~10min / CC: ~2min)** — scripts/evict_long_term_facts.py — Re-COUNT post-DELETE for audit `remaining_count`
  - Surfaced by: Outside voice F2
  - Files: `scripts/evict_long_term_facts.py`
  - Verify: `grep -A2 'remaining_count' scripts/evict_long_term_facts.py | grep -c "fetchval\|COUNT(\*)"` ≥ 1
- [ ] **T9 (P2, human: ~5min / CC: ~1min)** — controllers/memory.py — Reorder body: role-403 before header-400
  - Surfaced by: Outside voice F3
  - Files: `controllers/memory.py`, `tests/unit/test_memory_controller.py` (add `test_forget_non_admin_no_header_returns_403`)
  - Verify: `uv run pytest tests/unit/test_memory_controller.py::test_forget_non_admin_no_header_returns_403 -x -q` passes

## Completion Summary

- **Step 0 — Scope Challenge:** scope accepted as-is (6 production files, under 8-file STOP threshold; no new infra)
- **Architecture Review:** 4 issues (2 amendments T1, T2; 1 deferred observation on per-bucket audit volume; 1 incorporated cross-tenant test as T3 in Section 2)
- **Code Quality Review:** 1 amendment (T3)
- **Test Review:** diagram produced; 2 gaps documented (forget_user InterfaceError handling, mid-sweep crash e2e — both runbook-acceptable); 2 amendments (T4 dummy embedding, T5 SC-5 grep)
- **Performance Review:** 0 issues
- **NOT in scope:** 12 items documented
- **What already exists:** 7 reuse points documented
- **TODOS.md updates:** No TODOS.md proposed (project doesn't use one; deferred items captured in §NOT in scope)
- **Failure modes:** 0 critical gaps
- **Outside voice:** ran (Claude subagent) — 4/5 findings substantively landed
- **Parallelization:** 5 lanes, 4 waves (Wave 1: 3 parallel; Wave 2: 2 parallel; Waves 3+4: sequential)
- **Lake Score:** 9/9 amendments chose complete option (A in every D2–D11 question)

## Retrospective Learning (from Phase 24 eng-review)

Phase 24 eng-review surfaced 9 substantive amendments. Phase 25 eng-review surfaces 9 amendments — same scale. Pattern: Phase 24's D-B1 double-fetch architectural wart was the kind of finding plan-check missed but eng-review caught. Phase 25's equivalent is **T7 forget_user chunking** (architectural inconsistency — eviction chunks, forget doesn't, on the same table). Both required outside voice or close reading of plan execution semantics, not static plan-check.

**Pre-existing problematic area:** `audit_log` write-path. Phase 24 didn't touch it. Phase 25 adds two new consumers (forget + eviction) and is the first phase to need audit-write failure handling. Both T1 + T8 cluster here. Future phases adding audit consumers should treat audit-write try/except as default pattern.

## Files of Note for Execute Phase

Amendment commit (single commit recommended):
```
docs(25): apply eng-review amendments (T1-T9)

- T1: audit-write failure handling in 25-04 + 25-05
- T2: mount in main.py (resolves W3)
- T3: cross-tenant 200/0 test + doc note
- T4: dummy [0.0]*1024 seed (resolves W2)
- T5: SC-5 anchor N/A + grep gate (resolves W1)
- T6: Field(ge=1) for memory_facts_cap_per_user (outside voice F4)
- T7: chunk forget_user at 1000/txn (outside voice F1)
- T8: re-COUNT post-DELETE for audit remaining_count (outside voice F2)
- T9: reorder role-403 before header-400 (outside voice F3)

Closes all 3 plan-check warnings (W1, W2, W3).
4 outside-voice findings landed substantively (F1, F2, F3, F4); F5 folded into T2.
```

Then re-run `/gsd:plan-check 25` (expect PASS clean), then `/gsd-execute-phase 25`.

---

*Generated by /plan-eng-review on 2026-05-16. Mirrors Phase 24 eng-review shape.*

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 2 | issues_found (claude subagent — Codex unavailable in env) | 5 outside-voice findings, 4 landed (F1–F4), F5 folded |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 (this run) | issues_open (PLAN) | 9 amendments T1–T9 (5 primary + 4 outside voice), 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **CODEX:** Codex CLI unavailable in this env (verified Phase 24 + 25); Claude subagent ran in its place. 4 of 5 substantive findings landed as T6–T9. F5 (mount grep gate trivial) reinforced T2.
- **CROSS-MODEL:** Primary review caught 5 findings (T1–T5) the outside voice did not raise (audit-write failure, mount-point W3, cross-tenant 200/0, dummy seed W2, anchor N/A W1). Outside voice caught 4 the primary review missed (F1 forget chunking, F2 audit race, F3 4xx ordering, F4 cap=0 wipe). No overlap. No contradictions.
- **UNRESOLVED:** 0. All 11 decisions D1–D11 received explicit user response; 9 amendments accepted, 2 deferred observations documented (per-bucket audit volume at v1.7+ scale; mid-sweep crash recovery e2e — runbook-acceptable).
- **VERDICT:** ENG REVIEW REPORTED — apply T1–T9 amendments (single `docs(25): apply eng-review amendments` commit), re-run `/gsd:plan-check 25` (expect PASS clean), then `/gsd-execute-phase 25`. Eng review status flips to `clean` after re-log post-amendments.
