# Phase 25: Eviction job + GDPR forget API — Context

**Gathered:** 2026-05-16
**Status:** Plans → eng-reviewed → 9 amendments T1-T9 applied inline (2026-05-16). Ready for `/gsd:plan-check 25` re-validation, then `/gsd-execute-phase 25`.
**Mode:** discuss (default; ADVISOR_MODE off)

## Eng-Review Amendment Trail (2026-05-16)

Inline amendments applied to plan files after `/plan-eng-review 25`. See `25-ENG-REVIEW.md` for the full review report + tasks JSONL artifact at `~/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/tasks-eng-review-*.jsonl`.

| Amendment | Plan(s) | Source |
|-----------|---------|--------|
| T1 — audit_svc.log() try/except in forget controller + eviction sweep | 25-04, 25-05 | Architecture A1 |
| T2 — Mount memory_router in main.py (not controllers/__init__.py); router uses `prefix=settings.api_prefix` | 25-04 | Architecture A2 / Plan-check W3 / outside voice F5 |
| T3 — Cross-tenant admin forget 200/0 semantics: unit test + Forget API doc note | 25-04, 25-07 | Code Quality C1 |
| T4 — Integration test seed uses dummy `embedding=[0.0]*1024` (future-proof against NOT NULL) | 25-06 | Plan-check W2 |
| T5 — SC-5 anchor verification: annotate N/A + grep gate `grep -c '\](#'` equals 0 | 25-07 | Plan-check W1 |
| T6 — Pydantic `Field(default=500, ge=1)` rejects cap=0 at settings-load (closes T-25-01-D1 silent-wipe) | 25-01 | Outside voice F4 |
| T7 — Chunk LongTermMemory.forget_user DELETE at 1000 rows/txn (mirror evict_bucket) | 25-02 | Outside voice F1 |
| T8 — Re-COUNT post-DELETE for evict audit `remaining_count` (race accuracy) | 25-05 | Outside voice F2 |
| T9 — Reorder forget controller body: role-403 BEFORE header-400 (fail-closed identity) | 25-04 | Outside voice F3 |

**Plan-check status after amendments:** W1, W2, W3 all closed. Expect PASS clean on re-run.

**Test count growth from amendments:** 25-01 4→5, 25-02 6→7, 25-04 8→11, 25-05 10→11. Plans 25-03 / 25-06 / 25-07 test counts unchanged but content amended.

<domain>
## Phase Boundary

Bound `long_term_facts` growth + meet GDPR right-to-be-forgotten. Three production surfaces:

1. **`scripts/evict_long_term_facts.py`** — operator CLI. Per `(user_id, tenant_id)` bucket where row count > `settings.memory_facts_cap_per_user` (env `MEMORY_FACTS_CAP_PER_USER`, default 500), deletes lowest-importance rows (tie-break: oldest `created_at` first), chunked at 1000 rows/txn, idempotent. Supports `--mode=audit|enforce`. Audit mode logs distribution + zero deletes; enforce mode deletes. **Audit-mode-before-enforce** is documented as mandatory but enforced via runbook, NOT via a script-level precondition check (Decision-3.2 — runbook over bulletproof).
2. **`LongTermMemory.forget_user(user_id, tenant_id) → int`** + admin controller `DELETE /api/v1/memory/forget?user_id=...` — deletes all `long_term_facts` rows for a `(user_id, tenant_id)`. Scope is `long_term_facts` ONLY (Decision-1.2 — design doc Premise 7 confirmed; v1.6 boundary, NOT all-stores). Tenant resolved from JWT. Auth: admin role OR self-delete (`jwt.user_id == target_user_id`). Confirmation header `X-Confirm-Delete: yes` required to prevent accidental DELETEs (Decision-1.4).
3. **Audit-log integration** — `MEMORY_FORGET` + `MEMORY_EVICT` (TWO new `AuditAction` enum values, Decision-2.1). Each forget call → 1 audit row (post-fact, with actual deleted_row_count). Each eviction sweep → 1 row PER bucket touched (Decision-2.2 — GDPR per-data-subject trace).

Plus `docs/memory-eviction.md` extension: keep current 49 LOC Backfill content (from Plan 24-06); ADD Eviction + Audit Workflow + Enforce Mode + CronJob YAML + Forget API sections. Single file (Decision-4.2). Final ~120-180 LOC.

</domain>

<decisions>
## Implementation Decisions

### Theme 1 — Forget API surface

- **D-1.1 (auth gate):** `admin role OR self-delete` (matches ROADMAP). Non-admin can only forget their own `user_id` (`jwt.user_id == target_user_id`). Standard GDPR shape. 403 if neither.
- **D-1.2 (scope):** `long_term_facts` ONLY. Short-term Redis history + `user_profile` are NOT cleared by this API in v1.6. Documented as "GDPR scope: agent-authored facts only; conversational data has separate retention policy". v1.7+ can extend to true forget-all. Confirms design doc Premise 7.
- **D-1.3 (status codes):** `200 with deleted_row_count=0` when user has no facts (idempotent — forget-is-no-op-if-nothing-to-forget). `404` reserved for `user_id` format invalid OR tenant_id mismatch in JWT. `403` for auth failure (non-admin attempting to forget another user). `400` for missing/invalid `X-Confirm-Delete` header.
- **D-1.4 (confirmation header):** `DELETE /api/v1/memory/forget?user_id=...` REQUIRES `X-Confirm-Delete: yes` header. Returns 400 if absent. Documented in OpenAPI. Cheap accident-prevention (matches AWS S3 bucket-delete pattern).
- **D-1.5 (error handling — Claude default):** `LongTermMemory.forget_user` raises typed `MemoryForgetError` on `asyncpg.PostgresError` (mirrors Phase 23 `save_fact` → `MemoryFactWriteError` precedent). Controller catches `MemoryForgetError` → returns 500 with sanitized detail. Pre-existing v1.0 Phase 3 error-handling sweep conventions apply.

### Theme 2 — Audit-log shape

- **D-2.1 (AuditAction enum):** Add TWO new values to `services/audit/audit_service.py::AuditAction`: `MEMORY_FORGET` + `MEMORY_EVICT`. Clean separation in dashboards/queries; matches existing granularity (LOGIN/LOGOUT separate; not just AUTH). Pre-existing 12 enum values stay verbatim.
- **D-2.2 (eviction granularity):** ONE audit_log row PER bucket touched in a sweep (NOT one per sweep run). Each `MEMORY_EVICT` row carries `deleted_count + cap_value + remaining_count` in `detail`. Reviewable per-user; matches GDPR per-data-subject trace. Volume bounded by bucket-count, not row-count.
- **D-2.3 (write timing):** AFTER the DELETE, with actual `deleted_row_count`. Matches existing v1.0 Phase 2 post-fact pattern. If DELETE fails, no audit row written (exception propagates to caller). Audit-log infra has its own retry queue for the audit-write itself.
- **D-2.4 (detail dict — Claude default):** Forget audit `detail`: `{target_user_id, target_tenant_id, deleted_row_count, actor_user_id, actor_is_admin, requesting_ip}`. Evict audit `detail`: `{target_user_id, target_tenant_id, deleted_count, cap_value, remaining_count, mode}`. Both reuse `AuditEvent` Pydantic shape from `audit_service.py`.

### Theme 3 — Eviction operator UX

- **D-3.1 (audit-mode output):** stdout JSON-lines (one per bucket, operator can pipe to `jq`) + `audit_log` table (one `MEMORY_EVICT` row per bucket with `result=SKIPPED`, `detail.mode=audit`). Both sinks. No separate output file.
- **D-3.2 (first-run safety):** Runbook only. `docs/memory-eviction.md` prominently documents the audit→enforce workflow. enforce-mode runs immediately on invocation, no precondition check. Operator discipline > code complexity. Trade-off accepted: someone running `--mode=enforce` on a fresh DB might over-delete; mitigated by docs + the cap default of 500 (most fresh DBs are under cap anyway).
- **D-3.3 (CronJob YAML scope):** k8s CronJob YAML ONLY. Single runnable spec block with image, env vars (`PG_DSN`, `MEMORY_FACTS_CAP_PER_USER`), schedule, `restartPolicy: OnFailure`. Other runtimes (docker-compose, systemd) are operator's responsibility.
- **D-3.4 (cron frequency):** Daily @ 3am UTC (`0 3 * * *`). Catches over-cap accumulation within 24h. Low load (bounded by over-cap bucket count). Off-hours = low DB contention.

### Theme 4 — Docs reconciliation

- **D-4.1 (EVICT-03 mark):** UN-MARK `EVICT-03` from `[x]` to `[ ]` in `REQUIREMENTS.md` NOW (before Phase 25 starts). Plan 24-06 only delivered the Backfill section (49 LOC); cron + audit→enforce + forget-curl were never delivered. Re-mark `[x]` after Phase 25 verifier passes. Honest accounting; STATE.md/ROADMAP reflect reality.
- **D-4.2 (doc shape):** Single file `docs/memory-eviction.md`. KEEP current 49 LOC (Backfill, Cost Formula, Failure Modes). ADD: `## Eviction — Schedule & Cap`, `## Audit Mode Workflow`, `## Enforce Mode`, `## CronJob YAML`, `## Forget API` (with `curl` example). Final size ~120-180 LOC. Single source of truth.

### Claude's Discretion (no further user input needed)

- Exact CronJob YAML field values (image tag, namespace, resource requests) — pattern from existing v1.4 k8s manifests if any, else generic Pod spec.
- `MemoryForgetError` class location and shape — alongside `MemoryFactWriteError` in `services/memory/memory_service.py`. Pydantic-V2-frozen exception with `message: str` field.
- OpenAPI doc structure for the new `/api/v1/memory/forget` endpoint — auto-generated via FastAPI's response_model; add `tags=["admin", "gdpr"]` for OpenAPI grouping.
- Tests that mock `audit_service.log` for unit-level assertion of audit-row content — mock-at-consumer-path per v1.3 D-13/D-15 convention.
- Whether `forget_user` returns row count via `cursor.rowcount` or via a `RETURNING id` count — `cursor.rowcount` (cheaper, no row-data transfer; asyncpg supports it through `result` parse).
- `evict_long_term_facts.py` flag naming — `--mode={audit,enforce}` (ROADMAP-spec'd); `--batch-size N` (default 1000 per ROADMAP); optional `--user-id <uuid>` for scoped enforcement (single bucket, useful for manual cleanup).
- HTTP request-body schema vs query-param for the forget endpoint — `?user_id=alice` query-param per ROADMAP; no request body (matches DELETE semantics).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked requirements + roadmap

- `.planning/REQUIREMENTS.md` lines 31-39, 41-49 — EVICT-01, EVICT-02, EVICT-03, GDPR-01, GDPR-02, GDPR-03 acceptance bullets. **NOTE:** EVICT-03 currently marked `[x]` — Phase 25 Plan 01 MUST flip to `[ ]` per D-4.1 before any other work; re-mark `[x]` at phase verifier close.
- `.planning/ROADMAP.md` §Phase 25 — goal, depends-on, canonical refs, 5 success criteria.
- `.planning/STATE.md` §Carry-Forward Decisions + §Open Questions §5 (cap tuning — resolved here as D-3.2 runbook).

### Production surfaces (new + modified)

- `scripts/evict_long_term_facts.py` (NEW) — CLI per EVICT-01 + EVICT-02. Pattern source: `scripts/backfill_fact_embeddings.py` (Plan 24-06).
- `controllers/memory.py` (NEW) — `/api/v1/memory/forget` endpoint per GDPR-02. Pattern source: `controllers/api.py:400` `@router.delete("/cache", tags=["admin"])` template.
- `services/memory/memory_service.py::LongTermMemory.forget_user` (NEW method) — per GDPR-01.
- `services/memory/memory_service.py::MemoryForgetError` (NEW exception class) — alongside Phase 23 `MemoryFactWriteError`. Per D-1.5.
- `services/audit/audit_service.py::AuditAction` — extend enum with `MEMORY_FORGET`, `MEMORY_EVICT`. Per D-2.1.
- `docs/memory-eviction.md` (EXTENDED) — keep 49 LOC, add ~80-130 LOC per D-4.2.

### Pattern sources (reuse, do not reinvent)

- `services/audit/audit_service.py` — `AuditEvent`, `AuditAction`, `AuditResult` enums; `_flush_to_db` batched writes; `log_rule_blocked` shape (model for `log_memory_forget` / `log_memory_evict` if helper methods added).
- `services/auth/oidc_auth.py` — `AuthenticatedUser.is_admin`, `roles: list[str]`, `is_authorized(action="delete")`, `get_current_user` FastAPI dep. Reuse verbatim.
- `controllers/api.py:400` — `@router.delete("/cache", tags=["admin"])` admin-endpoint template.
- `services/memory/memory_service.py::save_fact` (Phase 23 Plan 02) — narrow-exception pattern: catch `asyncpg.PostgresError`, log via loguru with `operation="..."`, raise typed error from caught exception. `forget_user` mirrors this shape.
- `scripts/backfill_fact_embeddings.py` (Plan 24-06) — async CLI shape: argparse, asyncio.run, `LongTermMemory()._get_pool()` reuse (Pitfall 1 — register_vector codec), chunked txn pattern.

### Invariants

- `CLAUDE.md` — narrow exception types only (ERR-01); structured logging; Pydantic V2 frozen; mypy --strict; ruff.
- `Claude.md` (project) — production-grade only; no prototype code; no bare `except`.
- v1.0 Phase 2 — `audit_log` table is INSERT-ONLY (REVOKE UPDATE, DELETE). Phase 25 writes only; never updates/deletes audit rows.
- v1.3 Phase 13 + 15 — mock at consumer path (`services.<mod>.<dep>`) not source. Phase 25 unit tests mock `controllers.memory.audit_service.log` rather than `services.audit.audit_service.log`.
- v1.5 Phase 22 — per-module coverage ≥ 70% on touched modules. New modules (controllers/memory.py, scripts/evict_long_term_facts.py, forget_user method) targeted to ≥ 70%.
- v1.1 Phase 10 TEST-03 — diff-cover ≥ 80%.

### Companion docs

- `docs/memory-eviction.md` — current 49 LOC (Plan 24-06). Phase 25 extends per D-4.2.
- Phase 24 `24-ENG-REVIEW.md` — reference for eng-review amendment patterns; Phase 25 should expect a similar review pass.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`AuditEvent` Pydantic model** + **`AuditAction` enum** + **`AuditResult` enum** at `services/audit/audit_service.py` — extend enum with two new values; reuse `AuditEvent` shape verbatim.
- **`audit_service.log(event)` async API** — single call; buffer-and-flush handles DB writes. Phase 25 calls this from the forget controller AND from the eviction script.
- **`AuthenticatedUser` + `get_current_user`** at `services/auth/oidc_auth.py` — `Depends(get_current_user)` in the forget controller; check `user.is_admin or user.user_id == target_user_id`.
- **`LongTermMemory()._get_pool()`** with `register_vector` codec — eviction script reuses this (Pitfall 1 mitigation).
- **`controllers/api.py:400` `/cache` admin endpoint shape** — template for `/api/v1/memory/forget`.
- **Phase 23 `MemoryFactWriteError`** at `services/memory/memory_service.py` — mirror for `MemoryForgetError`.
- **Phase 24 Plan 24-06 backfill CLI shape** at `scripts/backfill_fact_embeddings.py` — argparse, asyncio.run, idempotent cursor, chunked txn. Phase 25 eviction script follows this skeleton.

### Established Patterns

- **Narrow-exception isolation** (Phase 23 save_fact, Phase 24 get_relevant_facts, Plan 24-06 backfill) — `except asyncpg.PostgresError` + structured log + typed raise. `forget_user` mirrors. Eviction script's batch-DELETE also.
- **`@router.delete("/path", tags=["admin"])` + `Depends(get_current_user)`** — admin endpoints in `controllers/api.py`. `controllers/memory.py` (new file) follows same shape.
- **`asyncio.create_task(...)` + `utils/tasks.log_task_error`** — NOT applicable here. Forget + eviction are NOT background (operator-invoked or sync request handler).
- **Chunked-commit txn** (Plan 24-06 `UPDATE ... FROM unnest`) — Phase 25 eviction uses chunked `DELETE FROM long_term_facts WHERE id IN ($1::uuid[])` per chunk; 1000 rows/txn per EVICT-01.

### Integration Points

- **Forget controller ↔ audit_service** — sync await on `audit_service.log(event)` AFTER the DELETE completes (D-2.3 post-fact). Audit-write failure doesn't roll back the DELETE (already committed); logged as warning.
- **Eviction script ↔ audit_service** — async-loop level; one `log()` call per bucket per sweep. Script runs to completion before exit (no graceful shutdown needed; CronJob's `restartPolicy: OnFailure` handles partial-failure recovery).
- **JWT tenant resolution ↔ forget controller** — `target_tenant_id = jwt.tenant_id` (NOT a query param). User CANNOT specify a different tenant. This + `is_admin` check are the auth invariants.
- **`MEMORY_FACTS_CAP_PER_USER` env ↔ settings** — new `settings.memory_facts_cap_per_user: int = 500` field; consumed by eviction script + (optionally) by save_fact path if pre-check optimization is added later (v1.7+).

</code_context>

<specifics>
## Specific Ideas

- **D-4.1's un-mark-now pattern**: Plan 25-01 (or a Wave-0 doc-prep plan) should be a tiny commit that flips `EVICT-03` from `[x]` to `[ ]` in `REQUIREMENTS.md`. No code changes. Commit message: `docs(25): un-mark EVICT-03 to reflect Plan 24-06 partial delivery (cron + forget-curl deferred to Phase 25)`. Single line edit; surfaces the accounting fix in git history.
- **D-1.4's `X-Confirm-Delete: yes` header**: implementation pattern in FastAPI: `confirm_delete: str = Header(..., alias="X-Confirm-Delete")` + `if confirm_delete != "yes": raise HTTPException(400, ...)`. Standard FastAPI Header dependency; documented automatically in OpenAPI.
- **D-2.2's per-bucket eviction audit row**: each row's `event_id` is UUID-generated per call (audit_service handles this); ops can correlate buckets-in-a-sweep via `detail.sweep_run_id` (set once at script start, propagated to all per-bucket rows). Adds ~36 chars per audit row; useful for "show me everything that happened in the 2026-05-17 sweep" dashboards.
- **D-3.1's stdout JSON-lines**: each line = `{"bucket": {"user_id":..., "tenant_id":...}, "row_count":..., "over_cap_by":..., "would_delete_count":...}`. Operator pipes to `jq '. | select(.over_cap_by > 100)'` for sorting. Audit row gets the same fields under `detail`.
- **D-3.3's CronJob spec**: include explicit `successfulJobsHistoryLimit: 3` + `failedJobsHistoryLimit: 1` to bound CronJob history accumulation (common k8s footgun). Document this in inline YAML comments.

</specifics>

<deferred>
## Deferred Ideas

### v1.7+ follow-ups (captured during this discussion)

- **`save_fact` pre-INSERT cap check** — short-circuit save_fact if `(user_id, tenant_id)` is already at cap, returning a soft-fail. Eliminates the need for nightly eviction in the steady state. Deferred because it changes the extractor's contract (save_fact currently never rejects valid input). Re-evaluate after Phase 25 audit-mode data shows real cap-hit rate.
- **Forget API extension to short-term + user_profile** (Decision-1.2 option B/C, REJECTED for v1.6) — true GDPR right-to-be-forgotten with full memory wipe. v1.7+ once long_term_facts forget API has production reps + the partial-failure handling (PG succeeded, Redis failed) is designed.
- **Per-tenant capacity overrides + importance decay** (carry-forward from STATE.md Open Question §5) — different tenants get different caps; importance decays over time. v1.7+ once cap-only policy has real production distribution data.
- **Cap auto-tuning** — script suggests a cap value from observed distribution percentiles (e.g., "95th percentile is at 380 rows; suggested cap=500"). v1.7+ once enough buckets exist for meaningful percentile math.
- **Audit-log enforce-mode preflight** (Decision-3.2 option B, REJECTED for v1.6) — code-enforced first-run-audit guard. Re-evaluate if a real ops incident proves operator discipline insufficient.
- **`docs/memory-ops.md` rename** (Decision-4.2 option C, REJECTED for v1.6) — file is becoming broader than eviction. Defer the rename to v1.7+ doc consolidation pass.
- **bulk-forget admin endpoint** — `DELETE /api/v1/memory/forget?tenant_id=X` to forget an entire tenant (not just a user). v1.7+ tenant-offboarding flow; out of scope for v1.6.

### Out of v1.6 scope (re-confirming carry-forward)

- RLS enforcement on `long_term_facts` (v1.0 Phase 2 carry-forward).
- Audit-log query/dashboard UI (v1.0 Phase 2 ships the write path; query UI was deferred).
- Compliance certification (SOC2, ISO27001) artifacts — beyond eng scope.

</deferred>

<branch_strategy>
## Branch Strategy for Phase 25

- Phase 24 work is on `gsd/v1.6-phases-23-24` (PR #5 open). Local `master` is at the same HEAD as that branch.
- Phase 25 planning + execution will accumulate commits on `master` locally (per project's `branching_strategy=none` config).
- Once PR #5 merges, Phase 25 ships as a separate PR via a new `gsd/phase-25-eviction-gdpr` branch forked from updated `master`.
- If PR #5 sits unmerged when Phase 25 is ready to ship, Phase 25 PR uses the v1.6 branch as base (stacked PR), OR rebases onto updated master at merge time.

</branch_strategy>

---

*Phase: 25-eviction-job-gdpr-forget-api*
*Context gathered: 2026-05-16*
*Themes covered: Forget API surface, Audit-log shape, Eviction operator UX, Docs reconciliation*
*Sub-areas deferred to Claude defaults: forget_user error class shape (D-1.5), audit detail dict fields (D-2.4), CronJob YAML field values, eviction script CLI flag naming.*
