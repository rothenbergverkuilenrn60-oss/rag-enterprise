# Phase 25: Eviction job + GDPR forget API — Validation Architecture

**Created:** 2026-05-16
**Status:** Ready for execution
**Coverage targets:** per-module ≥ 70% on touched modules; diff-cover ≥ 80% on Phase 25 touched lines

---

## Row Map: Requirements × Success Criteria × ASSUMED Claims

Each row traces one verifiable behavior from source (REQ-ID / SC / ASSUMED) → plan → task → test file → gate type → expected GREEN state.

| # | Source | Behavior | Plan | Task | Test File | Test Name | Gate Type | Expected GREEN |
|---|--------|----------|------|------|-----------|-----------|-----------|----------------|
| 1 | EVICT-01 | `settings.memory_facts_cap_per_user` exists with default 500 | 25-01 | Task 2 | `tests/unit/test_phase25_foundations.py` | `test_memory_facts_cap_per_user_default` | unit | `settings.memory_facts_cap_per_user == 500` |
| 2 | EVICT-01 | Settings field is type `int` | 25-01 | Task 2 | `tests/unit/test_phase25_foundations.py` | `test_memory_facts_cap_per_user_is_int` | unit | `field.annotation is int` |
| 3 | EVICT-01 | Audit mode: bucket at 600 rows produces stdout JSON-line, zero deletes | 25-05 | Task 2 | `tests/unit/test_evict_long_term_facts.py` | `test_audit_mode_no_delete_and_stdout` | unit | stdout JSON with `over_cap_by==100`; DELETE not called |
| 4 | EVICT-01 | Enforce mode: bucket drops to cap; small bucket untouched | 25-06 | Task 1 | `tests/integration/test_evict_long_term_facts_e2e.py` | `test_enforce_mode_caps_bucket` | integration (pgvector) | `SELECT count(*) WHERE user_id=big` = 500; small bucket = 100 |
| 5 | EVICT-01 | Tie-break: cap=2 on 3 rows — oldest lowest-importance deleted | 25-06 | Task 1 | `tests/integration/test_evict_long_term_facts_e2e.py` | `test_eviction_tiebreak_correctness` | integration (pgvector) | Row A (importance=0.2, oldest) gone; rows B+C survive |
| 6 | EVICT-01 | Idempotent: bucket already at cap → 0 deletes | 25-05 | Task 2 | `tests/unit/test_evict_long_term_facts.py` | `test_enforce_mode_idempotent_at_cap` | unit | `evict_bucket` returns 0; no execute call |
| 7 | EVICT-01 | Chunked DELETE uses `ORDER BY importance ASC, created_at ASC LIMIT $N` | 25-05 | Task 2 | `tests/unit/test_evict_long_term_facts.py` | `test_evict_bucket_chunks_large_over_cap` | unit (grep gate) | `grep 'ORDER BY importance ASC, created_at ASC' scripts/evict_long_term_facts.py` matches |
| 8 | EVICT-01 | Row count parsed via `int(status.split()[1])` — not cursor.rowcount | 25-05 | Task 2 | `tests/unit/test_evict_long_term_facts.py` | `test_row_count_parsing_string_to_int` | unit | `int("DELETE 7".split()[1]) == 7` |
| 9 | EVICT-01 | PG error during batch DELETE raises and outer loop continues to next bucket | 25-05 | Task 2 | `tests/unit/test_evict_long_term_facts.py` | `test_main_async_skips_failed_bucket_continues` | unit | Function returns 0; second bucket processed |
| 10 | EVICT-02 | Audit mode writes to both sinks: stdout JSON-lines AND audit_log SKIPPED | 25-05 | Task 2 | `tests/unit/test_evict_long_term_facts.py` | `test_audit_mode_both_sinks` | unit | stdout line present; `audit_svc.log` called with `result=AuditResult.SKIPPED` |
| 11 | EVICT-02 | Audit mode audit_log detail: `deleted_count=0`, `mode="audit"`, `sweep_run_id` present | 25-05 | Task 2 | `tests/unit/test_evict_long_term_facts.py` | `test_audit_mode_writes_audit_log_skipped` | unit | `detail["deleted_count"]==0`, `detail["mode"]=="audit"`, `detail["sweep_run_id"]` non-empty |
| 12 | EVICT-02 | Enforce mode audit_log: `result=SUCCESS`, actual `deleted_count`, `sweep_run_id` in detail | 25-05 | Task 2 | `tests/unit/test_evict_long_term_facts.py` | `test_enforce_audit_detail_fields` | unit | `detail` has all 7 required keys per D-2.4 |
| 13 | EVICT-02 | `--mode` CLI flag accepted; `--batch-size` default 1000; `--user-id` optional | 25-05 | Task 2 | acceptance_criteria (grep) | — | `uv run python scripts/evict_long_term_facts.py --help` shows all 3 flags |
| 14 | EVICT-03 | docs/memory-eviction.md contains `## CronJob YAML` section with runnable YAML | 25-07 | Task 1 | acceptance_criteria (grep) | — | `grep '0 3 \* \* \*' docs/memory-eviction.md` ≥ 1 |
| 15 | EVICT-03 | docs contains `## Audit Mode Workflow` + `## Enforce Mode` + `## Eviction — Schedule & Cap` | 25-07 | Task 1 | acceptance_criteria (grep) | — | 5 section headings present; `wc -l` between 120-180 |
| 16 | EVICT-03 | docs contains `## Forget API` with curl example + `X-Confirm-Delete: yes` | 25-07 | Task 1 | acceptance_criteria (grep) | — | `grep -c 'X-Confirm-Delete' docs/memory-eviction.md` ≥ 1 |
| 17 | GDPR-01 | `LongTermMemory.forget_user("alice", "acme")` returns int 3 on success | 25-02 | Task 2 | `tests/unit/test_memory_forget.py` | `test_forget_user_returns_row_count` | unit | Return value is `int(3)` |
| 18 | GDPR-01 | `forget_user` on user with 0 rows returns 0 (idempotent) | 25-02 | Task 2 | `tests/unit/test_memory_forget.py` | `test_forget_user_idempotent_zero` | unit | Return value is `int(0)` |
| 19 | GDPR-01 | `asyncpg.PostgresError` → `MemoryForgetError` raised with `__cause__` chained | 25-02 | Task 2 | `tests/unit/test_memory_forget.py` | `test_forget_user_raises_memory_forget_error_on_pg_error` | unit | `MemoryForgetError` raised; `exc.__cause__` is original |
| 20 | GDPR-01 | SQL targets `long_term_facts` with parameterized `user_id=$1 AND tenant_id=$2` | 25-02 | Task 2 | `tests/unit/test_memory_forget.py` | `test_forget_user_sql_args` | unit | `execute.call_args` SQL contains `WHERE user_id=$1 AND tenant_id=$2`; args = `("alice", "acme")` |
| 21 | GDPR-01 | Integration: admin forget call removes all rows; re-call returns 0 | 25-06 | Task 2 | `tests/integration/test_memory_forget_e2e.py` | `test_forget_api_e2e_idempotent` | integration (pgvector) | First call → N deleted; second call → 0 deleted |
| 22 | GDPR-02 | Admin JWT + `X-Confirm-Delete: yes` → 200 + `{deleted_row_count: N}` | 25-04 | Task 2 | `tests/unit/test_memory_controller.py` | `test_forget_admin_jwt_200` | unit | Status 200; JSON body correct |
| 23 | GDPR-02 | Non-admin self-delete (`jwt.user_id == target`) → 200 | 25-04 | Task 2 | `tests/unit/test_memory_controller.py` | `test_forget_self_delete_200` | unit | Status 200 |
| 24 | GDPR-02 | Non-admin for different user_id → 403 | 25-04 | Task 2 | `tests/unit/test_memory_controller.py` | `test_forget_non_admin_other_user_403` | unit | Status 403 |
| 25 | GDPR-02 | Missing `X-Confirm-Delete` header → 400 | 25-04 | Task 2 | `tests/unit/test_memory_controller.py` | `test_forget_missing_confirm_header_400` | unit | Status 400 |
| 26 | GDPR-02 | `X-Confirm-Delete: no` → 400 | 25-04 | Task 2 | `tests/unit/test_memory_controller.py` | `test_forget_wrong_confirm_header_400` | unit | Status 400 |
| 27 | GDPR-02 | `MemoryForgetError` from service → 500 (sanitized) | 25-04 | Task 2 | `tests/unit/test_memory_controller.py` | `test_forget_memory_forget_error_500` | unit | Status 500; detail is "Memory forget failed" (not raw PG message) |
| 28 | GDPR-02 | Integration: admin forget e2e — rows gone from DB | 25-06 | Task 2 | `tests/integration/test_memory_forget_e2e.py` | `test_forget_api_e2e_admin_200` | integration (pgvector) | 200 + `deleted_row_count > 0`; `SELECT count(*) = 0` after |
| 29 | GDPR-03 | Audit row written AFTER DELETE with `action=MEMORY_FORGET` | 25-04 | Task 2 | `tests/unit/test_memory_controller.py` | `test_forget_audit_called_after_forget_user` | unit | `audit_svc.log` call count = 1; called after `forget_user` mock resolves |
| 30 | GDPR-03 | Audit row detail has all D-2.4 fields: `target_user_id`, `target_tenant_id`, `deleted_row_count`, `actor_user_id`, `actor_is_admin`, `requesting_ip` | 25-04 | Task 2 | `tests/unit/test_memory_controller.py` | `test_forget_audit_row_content` | unit | All 6 keys present in `detail` arg |
| 31 | GDPR-03 | DB-level audit_log row retrievable with `action='MEMORY_FORGET'` when `audit_db_enabled=True` | 25-06 | Task 2 | `tests/integration/test_memory_forget_e2e.py` | `test_forget_api_audit_log_row` | integration (pgvector) | 1 row in `audit_log` with correct detail JSONB; Pitfall 3 mitigated via `monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", True)` + `flush()` |

---

## ASSUMED Claim Verification

| # | Claim | Risk | Verification Plan | Plan | Verified by |
|---|-------|------|-------------------|------|-------------|
| A1 | `settings.audit_db_enabled` defaults to `False` | Integration tests find empty audit_log | Integration test patches to `True` before asserting DB rows; unit tests mock `audit_service.log` at consumer path (never test DB sink at unit level) | 25-06 Task 2 | `test_forget_api_audit_log_row` + Pitfall 3 mitigation |
| A2 | `asyncpg.Connection.execute()` returns `"DELETE N"` as string | Silent 0 row count | Unit tests assert `forget_user` with `execute=AsyncMock(return_value="DELETE 3")` returns `int(3)`; `test_row_count_parsing_string_to_int` isolates the parsing | 25-02, 25-05 | `test_forget_user_returns_row_count`, `test_row_count_parsing_string_to_int` |
| A3 | `audit_log` table has REVOKE UPDATE, DELETE grant | Phase 25 might violate INSERT-only | Phase 25 only INSERTs to audit_log; no UPDATE/DELETE attempted; acceptance_criteria grep gates confirm no `UPDATE audit_log` or `DELETE FROM audit_log` in Phase 25 production code | all plans | `grep 'UPDATE audit_log\|DELETE.*audit_log' controllers/memory.py scripts/evict_long_term_facts.py` must return 0 |
| A4 | `controllers/memory.py` does not yet exist | Planner must create new file | Plan 25-04 creates the file as new; acceptance_criteria asserts file exists and router is importable | 25-04 | `python -c "from controllers.memory import router"` exits 0 |
| A5 | `settings.memory_facts_cap_per_user` does not yet exist in `config/settings.py` | Field must be added | Plan 25-01 adds the field; `test_memory_facts_cap_per_user_default` is RED before and GREEN after | 25-01 | `test_memory_facts_cap_per_user_default` |

---

## Success Criteria Coverage (ROADMAP Phase 25)

| SC | Description | Plans | Integration Test | Unit Tests |
|----|-------------|-------|-----------------|------------|
| SC-1 | Audit-mode zero deletes + enforce drops 600→500; 100-row untouched | 25-05, 25-06 | `test_audit_mode_no_deletes`, `test_enforce_mode_caps_bucket`, `test_enforce_mode_small_bucket_untouched` | `test_audit_mode_no_delete_and_stdout`, `test_enforce_mode_idempotent_at_cap` |
| SC-2 | Tie-break: cap=2, 3 rows — oldest 0.2 deleted; 0.2@T1 + 0.8 survive | 25-05, 25-06 | `test_eviction_tiebreak_correctness` | `test_evict_bucket_chunks_large_over_cap` (verifies ORDER BY clause present) |
| SC-3 | Admin JWT → 200 + deleted_row_count; non-admin other user → 403; idempotent re-call → 0 | 25-04, 25-06 | `test_forget_api_e2e_admin_200`, `test_forget_api_e2e_non_admin_403`, `test_forget_api_e2e_idempotent` | `test_forget_admin_jwt_200`, `test_forget_non_admin_other_user_403`, `test_forget_self_delete_200` |
| SC-4 | Audit_log MEMORY_FORGET row retrievable with correct detail fields | 25-04, 25-06 | `test_forget_api_audit_log_row` | `test_forget_audit_row_content`, `test_forget_audit_called_after_forget_user` |
| SC-5 | docs/memory-eviction.md has CronJob YAML, audit→enforce workflow, cap tuning, backfill cost ref, forget-API curl | 25-07 | — (content check) | grep acceptance_criteria in 25-07 Task 1 |

---

## AuditAction Enum Verification

| Claim | Plan | Test | Gate |
|-------|------|------|------|
| `AuditAction.MEMORY_FORGET.value == "MEMORY_FORGET"` | 25-01 | `test_audit_action_memory_forget_exists` | unit |
| `AuditAction.MEMORY_EVICT.value == "MEMORY_EVICT"` | 25-01 | `test_audit_action_memory_evict_exists` | unit |
| Both new values appended AFTER `TOKEN_VERIFIED` (Pitfall 5) | 25-01 | acceptance_criteria grep (line number ordering check) | grep gate |
| Total enum count = 14 (12 existing + 2 new) | 25-01 | `python -c "from services.audit.audit_service import AuditAction; assert len(list(AuditAction)) == 14"` | smoke |

---

## Pitfall Coverage Summary

| Pitfall | Description | Plan Mitigating | Test/Gate |
|---------|-------------|-----------------|-----------|
| Pitfall 1 | `register_vector` codec missing in CLI — use `LongTermMemory()._get_pool()` not `asyncpg.create_pool()` | 25-05 | `grep -v 'asyncpg.create_pool' scripts/evict_long_term_facts.py` count = 0; `grep '_get_pool' ...` ≥ 1 |
| Pitfall 2 | `asyncpg.execute()` returns `"DELETE N"` string — must parse `int(status.split()[1])` | 25-02, 25-05 | `test_forget_user_returns_row_count`, `test_row_count_parsing_string_to_int` |
| Pitfall 3 | `audit_db_enabled` defaults `False` — integration tests must patch to `True` | 25-06 | `test_forget_api_audit_log_row` patches + flushes before asserting |
| Pitfall 4 | `asyncpg.InterfaceError` not subclass of `PostgresError` — CLI must catch both | 25-05 | `grep 'asyncpg.InterfaceError' scripts/evict_long_term_facts.py` ≥ 1 |
| Pitfall 5 | AuditAction enum append-only — new values AFTER TOKEN_VERIFIED | 25-01 | Line-number ordering acceptance_criteria |
| Pitfall 6 | `Header(alias="X-Confirm-Delete")` required — not bare `Header(...)` | 25-04 | `grep 'alias="X-Confirm-Delete"' controllers/memory.py` ≥ 1; `grep 'default=None.*Header\|Header.*default=None' ...` ≥ 1 |
| Pitfall 7 | `Depends(get_current_user)` must come before `Header(...)` in function signature | 25-04 | `grep -n 'Depends(get_current_user)' controllers/memory.py` line number < `grep -n 'alias="X-Confirm-Delete"' ...` line number |
| Pitfall 8 | Chunked DELETE idempotent re-run — accept partial-sweep, next CronJob run recovers | 25-05 | `test_enforce_mode_idempotent_at_cap`, `test_main_async_skips_failed_bucket_continues` |

---

## Sampling Rate Schedule

| Gate | Command | When |
|------|---------|------|
| Per-plan commit | `uv run pytest tests/unit/test_phase25_foundations.py tests/unit/test_memory_forget.py tests/unit/test_memory_controller.py tests/unit/test_evict_long_term_facts.py -x -q` | After each GREEN task |
| Per-wave merge | `uv run pytest tests/unit/ -x -q --tb=short` | After Wave 1 (plans 01-03) and Wave 2 (plans 04-05) complete |
| Phase gate (unit) | `uv run pytest tests/unit/ -x -q --cov=services/memory/memory_service --cov=controllers/memory --cov=scripts/evict_long_term_facts --cov-fail-under=70` | Plan 25-07 Task 2 |
| Phase gate (integration) | `uv run pytest tests/integration/test_evict_long_term_facts_e2e.py tests/integration/test_memory_forget_e2e.py -m pgvector -x -q` | Plan 25-06 + pre-verify |
| diff-cover | `uv run diff-cover coverage.xml --compare-branch=origin/master --fail-under=80` | Plan 25-07 Task 2 |
| Full v1.5 baseline | `uv run pytest tests/ -x -q --ignore=tests/integration --tb=short` | Before `/gsd-verify-work 25` |

---

*Phase: 25-eviction-job-gdpr-forget-api*
*Validation created: 2026-05-16*
*Total rows: 31 (3 REQ-ID structural, 8 EVICT-01, 3 EVICT-02, 1 EVICT-03 content, 5 GDPR-01, 6 GDPR-02, 2 GDPR-03 + 5 ASSUMED + 5 SC + 4 enum + 8 pitfall = 31 verifiable claims across 7 plans)*
