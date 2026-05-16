# Phase 25 Plan-Check Report

**Checked:** 2026-05-16
**Status: PASS-WITH-WARNINGS**
**Plans:** 7 (25-01 through 25-07)
**Blockers:** 0
**Warnings:** 3
**Info:** 1

---

## SC Coverage (ROADMAP Phase 25)

| SC | Requirement | Plans | Closure Evidence | Status |
|----|-------------|-------|-----------------|--------|
| SC-1 | Audit-mode zero deletes + enforce drops 600→500; 100-row untouched | 25-05 (unit), 25-06 (integration) | `test_audit_mode_no_delete_and_stdout`, `test_enforce_mode_caps_bucket`, `test_enforce_mode_small_bucket_untouched` | COVERED |
| SC-2 | Tie-break: cap=2, 3 rows — oldest 0.2 deleted | 25-05 (unit ORDER BY gate), 25-06 (integration) | `test_eviction_tiebreak_correctness` + grep gate on `ORDER BY importance ASC, created_at ASC` | COVERED |
| SC-3 | Admin → 200+count; non-admin other user → 403; idempotent re-call → 0 | 25-04 (unit), 25-06 (integration) | `test_forget_admin_jwt_200`, `test_forget_non_admin_other_user_403`, `test_forget_api_e2e_idempotent` | COVERED |
| SC-4 | audit_log MEMORY_FORGET row with correct detail fields | 25-04 (unit), 25-06 (integration `test_forget_api_audit_log_row`) | Pitfall 3 mitigation explicit in 25-06 Task 2 (monkeypatch audit_db_enabled + flush) | COVERED |
| SC-5 | docs/memory-eviction.md — CronJob YAML + audit→enforce + curl + backfill cross-ref + anchors | 25-07 Task 1 | 5 new section headings; §E6 verbatim YAML; grep gates in acceptance_criteria; wc -l 120-180 | COVERED |

SC-5 note: plan acceptance_criteria checks `grep -c '^## '` (section count) but does NOT explicitly gate on internal anchor resolution (no `[text](#anchor)` links in the doc template). Since the doc uses flat `##` sections (no anchor cross-references), this is low risk but noted below as WARNING-1.

---

## Requirement Coverage

| Req | Description | Plan(s) | Task | Status |
|-----|-------------|---------|------|--------|
| EVICT-01 | evict_long_term_facts.py chunked DELETE + tie-break + audit-per-bucket | 25-01 (settings), 25-05 (CLI) | 25-05 T2 | COVERED |
| EVICT-02 | --mode=audit|enforce; both sinks; enforce deletes | 25-01 (enum), 25-05 (CLI) | 25-05 T2 | COVERED |
| EVICT-03 | docs/memory-eviction.md extension (120-180 LOC) | 25-03 (un-mark), 25-07 (docs + re-mark) | 25-07 T1+T2 | COVERED |
| GDPR-01 | LongTermMemory.forget_user → int; MemoryForgetError | 25-02 | 25-02 T2 | COVERED |
| GDPR-02 | DELETE /api/v1/memory/forget; admin-or-self; X-Confirm-Delete | 25-04 | 25-04 T2 | COVERED |
| GDPR-03 | audit-log entry per forget call; MEMORY_FORGET enum | 25-01 (enum), 25-04 (controller audit write) | 25-04 T2 | COVERED |

All 6 requirements have covering plans + tasks. All 6 appear in at least one plan's `requirements` frontmatter field.

---

## Decision Coverage (D-1.1..D-4.2)

| Decision | Requirement | Plan | Closure Evidence |
|----------|-------------|------|-----------------|
| D-1.1 admin OR self-delete; 403 | GDPR-02 | 25-04 | `if not (user.is_admin or user.user_id == user_id): raise HTTPException(403)` in verbatim skeleton; tested in `test_forget_non_admin_other_user_403` |
| D-1.2 long_term_facts ONLY | GDPR-01 | 25-02, 25-04 | forget_user docstring + acceptance_criteria grep `grep -v 'Redis\|user_profile'`; no Redis import in plan skeleton |
| D-1.3 200+count=0 idempotent; 404 for empty user_id; 403 auth | GDPR-02 | 25-04 | Steps 2+3 in endpoint action; tested in 8 unit tests |
| D-1.4 X-Confirm-Delete: yes header required; 400 if absent | GDPR-02 | 25-04 | `Header(default=None, alias="X-Confirm-Delete")` + 400 check; 2 tests (missing + wrong) |
| D-1.5 MemoryForgetError on asyncpg.PostgresError → 500 | GDPR-01, GDPR-02 | 25-02, 25-04 | `except asyncpg.PostgresError` + `raise MemoryForgetError`; controller `except MemoryForgetError → HTTPException(500)` |
| D-2.1 TWO new AuditAction values MEMORY_FORGET + MEMORY_EVICT | GDPR-03 | 25-01 | Task 2 appends after TOKEN_VERIFIED; 2 unit tests verify string values |
| D-2.2 ONE audit_log row PER bucket per sweep (not per sweep run) | EVICT-01 | 25-05 | `evict_bucket` calls `audit_svc.log` once per bucket; `test_enforce_audit_detail_fields` |
| D-2.3 audit write AFTER DELETE with actual deleted_row_count | GDPR-03, EVICT-01 | 25-04, 25-05 | SP-6 enforced; acceptance_criteria grep `grep -n 'await get_audit_service'` appears AFTER forget_user call |
| D-2.4 detail dict fields for forget + evict | GDPR-03 | 25-04, 25-05 | All 6 forget detail keys listed in action; all 7 evict detail keys listed; `test_forget_audit_row_content` + `test_enforce_audit_detail_fields` |
| D-3.1 stdout JSON-lines + audit_log (both sinks) | EVICT-02 | 25-05 | `print(json.dumps({...}))` + `audit_svc.log(SKIPPED)` in audit mode; `test_audit_mode_both_sinks` |
| D-3.2 runbook only; no code-enforced preflight | EVICT-01 | 25-05, 25-07 | anti-pattern callout in 25-PATTERNS Analog 1: "DO NOT add --mode=enforce precondition check"; runbook in docs |
| D-3.3 k8s CronJob YAML only | EVICT-03 | 25-07 | §E6 YAML embedded verbatim; "other runtimes are operator's responsibility" in doc action |
| D-3.4 daily @ 3am UTC (0 3 * * *) | EVICT-03 | 25-07 | acceptance_criteria `grep -c '0 3 \* \* \*' docs/memory-eviction.md` ≥ 1 |
| D-4.1 EVICT-03 un-mark before Phase 25 starts; re-mark at verifier close | EVICT-03 | 25-03 (un-mark), 25-07 (re-mark) | 25-03 acceptance_criteria; 25-07 T2 re-marks after gates pass |
| D-4.2 single file docs/memory-eviction.md; keep 49 LOC; add 80-130 LOC | EVICT-03 | 25-07 | wc -l 120-180 gate; existing sections preserved check; append-only action |

All 13 decisions covered (D-1.1..D-1.5, D-2.1..D-2.4, D-3.1..D-3.4, D-4.1..D-4.2).

---

## Pitfall Mitigation Coverage

| Pitfall | Description | Plan | Gate |
|---------|-------------|------|------|
| P-1 | register_vector codec — use `LongTermMemory()._get_pool()` not `asyncpg.create_pool()` | 25-05 | `grep -v 'asyncpg.create_pool' scripts/evict_long_term_facts.py` count=0; `grep '_get_pool'` ≥ 1 — present in 25-05 acceptance_criteria |
| P-2 | asyncpg returns `"DELETE N"` string; parse `int(status.split()[1])` | 25-02, 25-05 | `test_forget_user_returns_row_count` (mock returns `"DELETE 3"` → int 3); `test_row_count_parsing_string_to_int`; grep gate in 25-02 + 25-05 |
| P-3 | audit_db_enabled defaults False — integration tests must patch to True | 25-06 | `monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", True)` + `flush()` explicit in 25-06 T2 action and acceptance_criteria |
| P-4 | asyncpg.InterfaceError not subclass of PostgresError — CLI must catch both | 25-05 | `grep 'asyncpg.InterfaceError' scripts/evict_long_term_facts.py` ≥ 1 in acceptance_criteria; single-txn forget_user catches PostgresError only (correctly per Pitfall 4 note) |
| P-5 | AuditAction enum — append-only after TOKEN_VERIFIED | 25-01 | `grep -n 'TOKEN_VERIFIED' ... | head -1` line number < MEMORY_FORGET line in acceptance_criteria |
| P-6 | Header(alias="X-Confirm-Delete") required; default=None not ... | 25-04 | `grep 'alias="X-Confirm-Delete"'` + `grep 'default=None.*Header'` in 25-04 acceptance_criteria |
| P-7 | Depends(get_current_user) before Header in function signature | 25-04 | Line-number ordering check in 25-04 acceptance_criteria |
| P-8 | Chunked DELETE idempotent re-run — accept partial-sweep | 25-05 | `test_enforce_mode_idempotent_at_cap` + `test_main_async_skips_failed_bucket_continues` |

All 8 pitfalls have explicit grep gates or named test functions. P-2 grep gate for `int(status.split` is present in both 25-02 and 25-05 acceptance_criteria.

---

## Wave Dependency Graph + Parallelism

```
Wave 1 (parallel): 25-01 (settings + enum)   → files: config/settings.py, services/audit/audit_service.py
                   25-02 (forget_user)        → files: services/memory/memory_service.py
                   25-03 (EVICT-03 un-mark)   → files: .planning/REQUIREMENTS.md

Wave 2 (parallel): 25-04 (controller)         → depends_on: [25-01, 25-02] — files: controllers/memory.py, controllers/__init__.py
                   25-05 (eviction CLI)        → depends_on: [25-01]        — files: scripts/evict_long_term_facts.py

Wave 3:            25-06 (integration tests)  → depends_on: [25-04, 25-05]  — files: tests/integration/...

Wave 4:            25-07 (docs + coverage)    → depends_on: [25-06]          — files: docs/memory-eviction.md, REQUIREMENTS.md
```

**Parallelism check:**
- Wave 1: 25-01, 25-02, 25-03 touch disjoint files. SAFE.
- Wave 2: 25-04 and 25-05 touch disjoint files (controllers/ vs scripts/). SAFE.
- No forward references: 25-04 depends on 25-01 and 25-02 (both Wave 1). 25-05 depends on 25-01 only. 25-06 depends on 25-04 and 25-05 (both Wave 2). 25-07 depends on 25-06. VALID.
- No cycles detected.

One dependency observation: 25-04 declares `depends_on: [25-01, 25-02]` but not `[25-03]`. This is correct — 25-03 only edits REQUIREMENTS.md (accounting only) and 25-04 doesn't consume it. VALID.

---

## ASSUMED Claim Verification Coverage

| Claim | Risk | Plan | Test Gate |
|-------|------|------|-----------|
| A1 audit_db_enabled defaults False | Medium | 25-06 | Pitfall 3 patch in integration test; documented |
| A2 asyncpg returns "DELETE N" string | Medium | 25-02, 25-05 | test_forget_user_returns_row_count + test_row_count_parsing_string_to_int |
| A3 audit_log REVOKE UPDATE/DELETE in place | Low | all plans | grep gate in VALIDATION.md: no UPDATE/DELETE audit_log in production code |
| A4 controllers/memory.py does not yet exist | Low | 25-04 | 25-04 creates file; acceptance_criteria imports router |
| A5 settings.memory_facts_cap_per_user absent | Low | 25-01 | test_memory_facts_cap_per_user_default RED→GREEN |

All 5 ASSUMED claims have visible verification steps.

---

## Scope Creep Check

Deferred ideas verified absent from all plans:
- save_fact pre-INSERT cap check: NOT present in any plan. CLEAN.
- Forget API extension to Redis/user_profile: NOT present. CLEAN.
- Per-tenant capacity overrides: NOT present. CLEAN.
- Bulk-forget endpoint (entire tenant): NOT present. CLEAN.
- Cap auto-tuning: NOT present (docs mention percentile guidance as manual runbook, not code). CLEAN.

No scope creep found.

---

## Warnings

### WARNING-1 — SC-5 anchor verification is documentation-only, not mechanically tested
**Severity:** WARNING
**Dimension:** Verification Derivation / SC Coverage
**Description:** SC-5 requires "all internal anchors resolve (no broken links)." The 25-07 acceptance_criteria checks section heading presence and wc -l but does not run an anchor-resolution tool (e.g. `markdown-link-check`). The doc template uses flat `##` sections with no anchor cross-links (`[text](#section)` syntax), so in practice there are no anchors to break — but the ROADMAP SC-5 language is not mechanically closed.
**Suggested fix:** Add `python -c "import re,pathlib; content=pathlib.Path('docs/memory-eviction.md').read_text(); links=re.findall(r'\[.*?\]\(#(.*?)\)', content); ..."` verification step OR add `markdown-link-check docs/memory-eviction.md` to 25-07 Task 1 acceptance_criteria. Alternatively, confirm no `(#anchor)` links exist in the doc template, and annotate SC-5 as "no anchor links — mechanically N/A."

### WARNING-2 — 25-06 Task 1: embedding=NULL seed rows may violate NOT NULL constraint on embedding column
**Severity:** WARNING
**Dimension:** Task Completeness
**Description:** 25-06 Task 1 action states "Skip embedding column (NULL) — eviction only uses importance + created_at + id." However, Phase 23 added `embedding VECTOR(1024)` to long_term_facts. If the column has a `NOT NULL` constraint (likely, given Phase 23 MEM-02 zero-partial-write contract), INSERT without embedding will fail at the integration test seed step, causing the eviction e2e tests to error before any assertions run.
**Plan:** 25-06, Task 1
**Suggested fix:** Check whether the embedding column allows NULL (it does if `ALTER TABLE ... ADD COLUMN IF NOT EXISTS embedding VECTOR(1024)` was used without NOT NULL). If nullable, confirm in 25-06 context read step. If NOT NULL, the seed helper must embed a dummy vector (e.g. `[0.0] * 1024`) or use `gen_random_uuid()` for a placeholder.
**Impact if wrong:** 4 integration tests fail at setup; SC-1 and SC-2 cannot close.

### WARNING-3 — 25-04 Task 2: controllers/__init__.py router-mount wiring is "read first and mirror" without specifying the mount point
**Severity:** WARNING
**Dimension:** Key Links Planned
**Description:** Plan 25-04 Task 2 action says "Read `controllers/__init__.py` first to understand how other routers are included … may be in `main.py` instead of `__init__.py`." The actual mount point is left to executor discovery at runtime. If the executor misidentifies the mount location or the prefix, the TestClient will not resolve `/api/v1/memory/forget` and the 8 unit tests will fail with 404 errors unrelated to the endpoint logic.
**Plan:** 25-04, Task 2
**Suggested fix:** The `<interfaces>` block already shows the `controllers/__init__.py` pattern exists — but the plan should explicitly state whether the mount is in `main.py` or `__init__.py` based on RESEARCH.md ASSUMED A4. CONTEXT canonical refs point to `controllers/api.py:400` as template but don't confirm the mount location. The executor must verify this before writing the router include. Acceptable as-is if the executor reads `controllers/__init__.py` first (which is in `read_first`), but the ambiguity is a risk.

---

## Info

### INFO-1 — Plan 25-03 is minimal but justified as a standalone Wave 1 plan
The un-mark of EVICT-03 is a 1-line edit to REQUIREMENTS.md with a commit message requirement. It could be folded into 25-01, but exists as a separate plan for git-history traceability (D-4.1 explicitly calls for a distinct commit). This is intentional, not redundant.

---

## Recommendation

**Proceed to execute.** No blockers found. Three warnings exist:

1. WARNING-2 (embedding NULL constraint) is the highest-priority item. The executor of 25-06 Task 1 must verify whether the `embedding` column is nullable before writing the seed helper. If it is NOT NULL, add a dummy vector to the seed INSERT. This is a one-line fix and should not block execution — but must be resolved before the integration tests run.

2. WARNING-1 (SC-5 anchor check) is low risk given the doc template has no `(#anchor)` hyperlinks.

3. WARNING-3 (router mount ambiguity) is mitigated by the `read_first` directive in 25-04 Task 2.

All 6 requirements covered, all 5 ROADMAP SCs covered, all 13 decisions honored, all 8 pitfalls mitigated, dependency graph valid, no scope creep.
