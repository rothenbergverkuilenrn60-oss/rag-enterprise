# Phase 25 Plan-Check Report — Post-Amendment Re-Run

**Checked:** 2026-05-16 (re-verification after eng-review amendments)
**Commit verified:** 9568d2f (`docs(25): apply eng-review amendments T1-T9`)
**Status: PASS**
**Plans:** 7 (25-01 through 25-07)
**Blockers:** 0
**Warnings:** 0
**Info:** 1
**Prior verdict (e6dc73e):** PASS-WITH-WARNINGS — 0 blockers, 3 warnings (W1, W2, W3), 1 info
**Delta:** All 3 prior warnings closed. No new blockers or warnings introduced by amendments.

---

## Prior Warning Closure

### W1 — SC-5 anchor verification not mechanically tested → CLOSED (T5)

- 25-07 Task 1 acceptance_criteria now contains literal grep gate: `grep -c '\](#' docs/memory-eviction.md` equals 0.
- 25-07 success_criteria explicitly annotates SC-5 as "mechanically closed via grep gate equals 0 — no anchor cross-links in the doc."
- Current state pre-execution: `grep -c '](#' docs/memory-eviction.md` returns 0 (verified). Gate is satisfiable.
- Doc uses flat `## section` heading style; SC-5 phrase "all internal anchors resolve" reduces to "zero anchor links present", which the grep gate enforces.
- Future-proof: any commit that adds an anchor link fails the gate, forcing the reviewer to add markdown-link-check.

### W2 — 25-06 seed rows use NULL embedding (NOT NULL constraint risk) → CLOSED (T4)

- 25-06 Task 1 + Task 2 helper `_seed_facts` now seeds rows with `embedding=[0.0] * 1024` (dummy 1024-dim zero vector).
- acceptance_criteria contains grep gate: `grep -cE '\[0\.0\]\s*\*\s*1024' tests/integration/test_evict_long_term_facts_e2e.py` ≥ 1 (and same for `test_memory_forget_e2e.py`).
- Verified the today-state: column nullable per `services/memory/memory_service.py:211` (`ALTER ADD COLUMN IF NOT EXISTS embedding vector(1024)` without NOT NULL). T4 is future-proofing, not a today-required fix — but absorbs the W2 risk regardless.
- Eviction reads only `importance + created_at + id`; zero-vector seed has no semantic effect on the eviction algorithm under test.

### W3 — 25-04 router mount-point ambiguity (main.py vs controllers/__init__.py) → CLOSED (T2)

- 25-04 `files_modified` now lists `main.py` (replaces `controllers/__init__.py` ambiguity).
- 25-04 Task 2 action explicitly states: `router = APIRouter(prefix=settings.api_prefix)` in controllers/memory.py mirroring `controllers/api.py:44`; `app.include_router(memory_router)` added near `main.py:386`.
- acceptance_criteria tightened: `grep -c 'app.include_router(memory_router)' main.py` equals 1 (was `grep "memory" controllers/__init__.py`).
- Also covered: `grep -n 'from controllers.memory import router as memory_router' main.py` matches one line.
- Outside-voice F5 (mount grep trivial) folded in.

**All 3 prior warnings resolved with mechanical grep gates. No residual ambiguity.**

---

## Amendment Cross-Plan Consistency Check (T1-T9)

| # | Amendment | Plan(s) | Internal Consistency | Verdict |
|---|-----------|---------|---------------------|---------|
| T1 | audit_svc.log() try/except wrapper | 25-04, 25-05 | 25-04 truths assert `except Exception as audit_exc:` + `operation="forget_audit_log"`. 25-05 truths assert same shape with `operation="evict_audit_log"`. STRIDE T-25-04-P2 + T-25-05-R2 both flipped to mitigate with matching language. Tests T9/T11 in respective plans. `noqa: BLE001` justifications consistent. | CONSISTENT |
| T2 | main.py mount + APIRouter(prefix=settings.api_prefix) | 25-04 | `files_modified` lists `main.py`. `must_haves.truths` describes both pieces (router def + include line). 3 grep gates + 1 line-number assertion. Pattern mirrors existing `controllers/api.py:44`. | CONSISTENT |
| T3 | Cross-tenant 200/0 test + doc note | 25-04, 25-07 | 25-04 Task 1 Test 10 (`test_forget_cross_tenant_unreachable_returns_200_zero`) seeds the unit gate. 25-07 Task 1 Forget API section asserts doc note "200 + deleted_row_count=0 means user has no facts in YOUR tenant." 25-07 acceptance_criteria: `grep -ic 'your tenant\|in YOUR tenant\|your-tenant' docs/memory-eviction.md` ≥ 1. STRIDE T-25-04-P3 mitigated via doc + test. | CONSISTENT |
| T4 | Integration seed embedding=[0.0]*1024 | 25-06 | Helper `_seed_facts` in BOTH integration files seeds dummy vector. Grep gates in both Task 1 and Task 2 acceptance_criteria. | CONSISTENT |
| T5 | SC-5 anchor N/A grep gate | 25-07 | `grep -c '\](#' docs/memory-eviction.md` equals 0 acceptance gate. Annotated in truths + success_criteria. | CONSISTENT |
| T6 | Field(default=500, ge=1) cap rejection | 25-01 | `must_haves.truths` includes Pydantic ValidationError on cap=0. Test 3 (`test_memory_facts_cap_zero_rejected`) added (count 4→5). STRIDE T-25-01-D1 flipped accept→mitigate. acceptance_criteria has `grep -n 'memory_facts_cap_per_user: int = Field(default=500, ge=1)' config/settings.py` literal match. | CONSISTENT |
| T7 | Chunk forget_user at 1000/txn | 25-02 | forget_user body: `while True:` loop, `LIMIT 1000`, `int(status.split()[1])`, `total_deleted` accumulation, terminate on `"DELETE 0"`. Test 7 (`test_forget_user_chunks_large_bucket`) with 4-chunk side_effect (1000+1000+500+0=2500). STRIDE T-25-02-D1 flipped accept→mitigate. 5 grep gates enforce loop structure. **Cross-plan check:** 25-04 controller still calls `await mem.forget_user(user_id, target_tenant_id)` and consumes the int return; controller does NOT need to know about chunking. forget_user signature unchanged (`-> int`). No 25-04 amendment needed. | CONSISTENT |
| T8 | Re-COUNT post-DELETE for remaining_count | 25-05 | acceptance_criteria contains TWO must-pass gates: (a) `grep -cE 'SELECT COUNT\(\*\)\s+(AS\s+\w+\s+)?FROM long_term_facts' scripts/evict_long_term_facts.py` ≥ 2 (one pre, one post-DELETE); (b) `grep -c 'remaining_count = row_count - total_deleted'` equals 0 (stale form banned). Test 10 (`test_enforce_audit_detail_fields`) updated to mock TWO distinct fetchrow returns and assert detail comes from post-DELETE fetchrow. STRIDE T-25-05-R3 flipped accept→mitigate. | CONSISTENT |
| T9 | Role-403 before header-400 ordering | 25-04 | Body steps explicit: Step 1 = role gate (403); Step 2 = header gate (400). acceptance_criteria has line-number comparison: `grep -nE 'is_admin\s+or\s+user\.user_id\s*==\s*user_id' controllers/memory.py | head -1` line LESS THAN `grep -n 'x_confirm_delete != "yes"' controllers/memory.py | head -1`. Test 11 (`test_forget_non_admin_no_header_returns_403`) added (count 10→11). STRIDE T-25-04-I2 flipped accept→mitigate. | CONSISTENT |

**Cross-plan-pair invariants verified:**

- T1 (25-04) ↔ T1 (25-05): Both use `except Exception as audit_exc` + `noqa: BLE001` + structured log with `operation` field + audit_payload dump. Pattern is identical (single source of truth: 25-ENG-REVIEW.md A1). No drift.
- T7 (25-02) ↔ 25-04 controller call: 25-04 calls `await mem.forget_user(user_id, target_tenant_id)`. T7 keeps signature `(user_id: str, tenant_id: str) -> int`. Caller is chunking-agnostic; only sees the summed int return. PASS.
- T8 (25-05 re-COUNT) ↔ 25-05 audit detail keys (D-2.4): The `remaining_count` key was already part of D-2.4's 7-key contract; T8 only changes HOW that field is computed, not whether it appears. Test 10 (`test_enforce_audit_detail_fields`) was already gating the key presence; the T8 amendment adds the second-fetchrow mock + assertion. No contract surface change. PASS.
- T3 (25-04 unit test) ↔ T3 (25-07 doc note): Test 10 in 25-04 mocks `mem.forget_user` returning 0; 25-07 Forget API section documents the 200/0 semantic. Both reference the same behavior contract from a different verification angle. PASS.

---

## STRIDE Disposition Audit

Eng-review amendments require these explicit flips (accept→mitigate):

| Threat ID | Plan | Pre-amendment | Post-amendment | Verified |
|-----------|------|--------------|----------------|----------|
| T-25-01-D1 (cap=0 silent wipe) | 25-01 | accept | **mitigate** (T6) | YES — line 246 mitigation cell present; `Field(ge=1)` referenced |
| T-25-02-D1 (large forget_user DELETE timeout) | 25-02 | accept | **mitigate** (T7) | YES — line 336 mitigation cell present; chunking referenced |
| T-25-04-I2 (4xx ordering info leak) | 25-04 | NEW (not pre-amend) | **mitigate** (T9) | YES — line 360 present; Test 11 enforces |
| T-25-04-P2 (audit-log fail drops GDPR trail) | 25-04 | NEW | **mitigate** (T1) | YES — line 364 present; Test 9 enforces |
| T-25-04-P3 (cross-tenant 200/0 ambiguity) | 25-04 | NEW | **mitigate** via doc (T3) | YES — line 365 present; Test 10 enforces |
| T-25-05-R2 (mid-sweep audit-fail repudiation) | 25-05 | NEW | **mitigate** (T1) | YES — line 347 present; Test 11 enforces |
| T-25-05-R3 (stale remaining_count repudiation) | 25-05 | NEW | **mitigate** (T8) | YES — line 348 present; re-COUNT enforced |

All 7 STRIDE register entries reflect the amendment dispositions. No accept→accept stragglers.

---

## SC Coverage (ROADMAP Phase 25) — Re-Run

| SC | Plans | Closure Evidence | Status |
|----|-------|-----------------|--------|
| SC-1 | 25-05, 25-06 | `test_audit_mode_no_delete_and_stdout`, `test_enforce_mode_caps_bucket`, `test_enforce_mode_small_bucket_untouched` | COVERED |
| SC-2 | 25-05, 25-06 | `test_eviction_tiebreak_correctness` + grep gate on `ORDER BY importance ASC, created_at ASC` | COVERED |
| SC-3 | 25-04, 25-06 | `test_forget_admin_jwt_200`, `test_forget_non_admin_other_user_403`, `test_forget_api_e2e_idempotent`, **+ T9 `test_forget_non_admin_no_header_returns_403`** | COVERED (strengthened) |
| SC-4 | 25-04, 25-06 | `test_forget_audit_row_content`, `test_forget_api_audit_log_row` with Pitfall 3 patch; **+ T1 `test_forget_audit_write_failure_returns_200`** | COVERED (strengthened) |
| SC-5 | 25-07 | 5 section headings + §E6 verbatim YAML + grep gates + wc -l 120-180 + **T5 anchor grep equals 0** | COVERED (mechanically closed) |

---

## Requirement Coverage

| Req | Plan(s) | Tasks | Status |
|-----|---------|-------|--------|
| EVICT-01 | 25-01 (settings + ge=1, T6), 25-05 (CLI + T1 + T8) | 25-05 T2 | COVERED |
| EVICT-02 | 25-01 (enum), 25-05 (CLI + T1) | 25-05 T2 | COVERED |
| EVICT-03 | 25-03 (un-mark), 25-07 (docs + T3 + T5 + re-mark) | 25-07 T1+T2 | COVERED |
| GDPR-01 | 25-02 (forget_user + T7) | 25-02 T2 | COVERED |
| GDPR-02 | 25-04 (controller + T1 + T2 + T3 + T9) | 25-04 T2 | COVERED |
| GDPR-03 | 25-01 (enum), 25-04 (audit write + T1) | 25-04 T2 | COVERED |

All 6 requirements have covering plans + tasks. All 6 IDs present in at least one plan's `requirements:` frontmatter.

---

## EVICT-03 Lifecycle Audit

| Stage | Plan | State | Verified |
|-------|------|-------|----------|
| Un-mark `[x]` → `[ ]` | 25-03 Task 1 | Single-line edit + NOTE | YES — current REQUIREMENTS.md line 52 shows `[ ]` + NOTE (Case A: pre-applied) |
| Re-mark `[ ]` → `[x]` | 25-07 Task 2 Step 4 | After all gates pass (coverage ≥ 70% per-module; diff-cover ≥ 80%; full unit suite zero failures) | acceptance_criteria gates verified |
| Cycle integrity | 25-03 → 25-07 | depends_on chain: 25-07 depends_on [25-06]; 25-06 depends_on [25-04, 25-05]; 25-03 independent (Wave 1) | VALID — no circular, no forward reference |

Cycle is intact: un-mark before any code lands → re-mark after every code+docs+coverage gate green.

---

## Wave Dependency Graph (Re-Verified)

```
Wave 1 (parallel): 25-01 → config/settings.py, services/audit/audit_service.py, tests/unit/test_phase25_foundations.py
                   25-02 → services/memory/memory_service.py (forget_user + MemoryForgetError + T7 chunking), tests/unit/test_memory_forget.py
                   25-03 → .planning/REQUIREMENTS.md (un-mark only)

Wave 2 (parallel): 25-04 → depends_on: [25-01, 25-02] — controllers/memory.py, main.py (T2), tests/unit/test_memory_controller.py
                   25-05 → depends_on: [25-01]        — scripts/evict_long_term_facts.py, tests/unit/test_evict_long_term_facts.py

Wave 3:            25-06 → depends_on: [25-04, 25-05]  — tests/integration/test_evict_long_term_facts_e2e.py, tests/integration/test_memory_forget_e2e.py (T4 seed)

Wave 4:            25-07 → depends_on: [25-06]          — docs/memory-eviction.md, .planning/REQUIREMENTS.md (re-mark)
```

**Parallelism + ordering verified:**

- Wave 1: 25-01, 25-02, 25-03 touch disjoint files. SAFE.
- Wave 2: 25-04 (`controllers/`, `main.py`) ↔ 25-05 (`scripts/`) — disjoint module dirs. SAFE.
- No forward refs; no cycles. T2's main.py edit is bounded to Plan 25-04 (no other plan touches main.py).
- T7 (25-02) does NOT add a dependency on 25-04 — forget_user is callable in isolation; 25-04 is the consumer.

---

## Pitfall Mitigation (Re-Verified Post-Amendment)

All 8 pitfalls retain coverage. T7's chunked forget_user reinforces Pitfall 2 (status string parsing) by exercising it in two places (forget_user loop AND eviction loop). T8 strengthens Pitfall 3 (audit_db_enabled) tangentially — re-COUNT happens regardless of audit_db_enabled state.

| Pitfall | Plan | Status |
|---------|------|--------|
| P-1 register_vector codec | 25-05 | INTACT — `LongTermMemory()._get_pool()` grep gate |
| P-2 "DELETE N" string parse | 25-02 (T7-strengthened), 25-05 | INTACT — both plans grep `int(status.split` |
| P-3 audit_db_enabled patch | 25-06 | INTACT |
| P-4 InterfaceError in batch loops | 25-05 | INTACT |
| P-5 AuditAction append-only | 25-01 | INTACT |
| P-6 Header alias | 25-04 | INTACT |
| P-7 Depends before Header | 25-04 | INTACT |
| P-8 Idempotent re-run | 25-05 | INTACT |

---

## Scope Creep Re-Check

All deferred ideas from CONTEXT.md `<deferred>` block verified absent from amended plans:

- save_fact pre-INSERT cap check: ABSENT
- Forget API extension to Redis/user_profile: ABSENT (D-1.2 long_term_facts ONLY enforced in 25-02 truths + 25-07 doc note)
- Per-tenant capacity overrides: ABSENT
- Bulk-forget admin endpoint (`?tenant_id=X`): ABSENT
- Cap auto-tuning code: ABSENT (manual percentile guidance in 25-07 docs only)
- Audit-log enforce-mode preflight: ABSENT (D-3.2 runbook-only honored)
- `docs/memory-ops.md` rename: ABSENT
- Atomic single-statement `DELETE ... OFFSET cap` eviction: ABSENT (would break chunked-1000 EVICT-01 contract)
- Existence check for "user exists in any tenant" before 200/0: ABSENT (T3 doc note sufficient — accepted trade-off)

No scope creep introduced by amendments.

---

## Context Compliance (CONTEXT.md Amendment Trail)

CONTEXT.md `## Eng-Review Amendment Trail (2026-05-16)` section was added in commit eaa5abe / 0556a78 and updated in 9568d2f. Each amendment T1-T9 is enumerated with plan(s) affected + source. Cross-referenced against amended plan frontmatter `review_amendments:` lists:

| Amendment | CONTEXT trail | Plan frontmatter `review_amendments:` |
|-----------|---------------|---------------------------------------|
| T1 | 25-04, 25-05 | 25-04: T1 listed; 25-05: T1 listed | MATCH |
| T2 | 25-04 | 25-04: T2 listed | MATCH |
| T3 | 25-04, 25-07 | 25-04: T3 listed; 25-07: T3 listed | MATCH |
| T4 | 25-06 | 25-06: T4 listed | MATCH |
| T5 | 25-07 | 25-07: T5 listed | MATCH |
| T6 | 25-01 | 25-01: T6 listed | MATCH |
| T7 | 25-02 | 25-02: T7 listed | MATCH |
| T8 | 25-05 | 25-05: T8 listed | MATCH |
| T9 | 25-04 | 25-04: T9 listed | MATCH |

CONTEXT.md is internally consistent with amended plans. STATE.md last_activity field updated to reference all 9 amendments. All match.

---

## VALIDATION.md Observation

The orchestrator flagged that VALIDATION.md (unchanged) lacks an explicit row for "non-admin + no header → 403 (role wins)" from T9. Verified: VALIDATION.md has 31 rows; the closest row is #24 (`test_forget_non_admin_other_user_403`, non-admin for different user WITH X-Confirm-Delete: yes), which covers the role-403 path but with the header present. T9's specific "role wins over missing header" case is gated by 25-04 acceptance_criteria (line-number ordering) and Test 11, NOT by a VALIDATION.md row.

**Assessment:** This is acceptable as INFO (not BLOCKER, not WARNING).

Rationale:
1. The Test 11 unit test (`test_forget_non_admin_no_header_returns_403`) is mechanically gated in 25-04 acceptance_criteria via grep.
2. 25-04 acceptance_criteria already gates the line-number ordering of role check vs header check (the structural enforcement).
3. VALIDATION.md is a traceability artifact; the test exists and is gated regardless of whether it appears as a numbered row.
4. T9 amendment summary in 25-04 review_amendments explicitly says "Add VALIDATION matrix row" — but VALIDATION.md was not modified in the amendment commit. Adding the row is a cosmetic/completeness improvement, not a coverage gap.

See INFO-1 below.

---

## Info

### INFO-1 — VALIDATION.md does not include a row for T9's "non-admin + no header → 403" case

**Severity:** INFO (cosmetic completeness)
**Description:** T9 amendment summary in 25-04 review_amendments notes "Add VALIDATION matrix row: 'non-admin + no header → 403 (role wins).'" VALIDATION.md was not modified in commit 9568d2f. The test (`test_forget_non_admin_no_header_returns_403`) IS gated via 25-04 acceptance_criteria grep + line-number ordering check, so coverage is enforced; this is purely about traceability artifact completeness.
**Recommendation:** Optional one-line addition to VALIDATION.md row map (a row #24a between rows 24 and 25):

```
| 24a | GDPR-02 (T9) | Non-admin for different user + no X-Confirm-Delete → 403 (role wins over header) | 25-04 | Task 2 | tests/unit/test_memory_controller.py | test_forget_non_admin_no_header_returns_403 | unit | Status 403 (not 400) |
```

Does NOT block execution. The 25-04 test gate provides the mechanical enforcement; VALIDATION.md row is a documentation refinement.

---

## Recommendation

**Proceed to execute. PASS clean.**

- 0 blockers.
- 0 warnings (all 3 prior warnings closed: W1 via T5, W2 via T4, W3 via T2).
- 1 INFO (VALIDATION.md row 24a — cosmetic, does not block execution).
- All 9 amendments (T1–T9) internally consistent across plans.
- All 7 STRIDE register flips present.
- All 6 requirements covered.
- All 5 ROADMAP SCs covered (SC-3 + SC-4 strengthened by new tests).
- All 13 user decisions (D-1.1..D-4.2) honored.
- All 8 pitfalls mitigated.
- Wave dependency graph valid, no cycles, parallelism preserved.
- EVICT-03 un-mark/re-mark lifecycle intact.
- No scope creep introduced by amendments.

Next step: `/gsd-execute-phase 25`.

---

*Re-verified: 2026-05-16 — post-amendment plan-check against commit 9568d2f.*
*Prior verdict: PASS-WITH-WARNINGS (e6dc73e). New verdict: PASS clean.*
*Test counts (post-amendment): 25-01 = 5 tests; 25-02 = 7 tests; 25-04 = 11 tests; 25-05 = 11 tests; 25-06 = 8 tests (4+4); 25-07 = grep-gated docs + coverage.*
