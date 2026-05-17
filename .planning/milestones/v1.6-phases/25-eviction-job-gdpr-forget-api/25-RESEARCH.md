# Phase 25: Eviction job + GDPR forget API — Research

**Researched:** 2026-05-16
**Domain:** asyncpg chunked-DELETE, FastAPI admin endpoints, audit-log integration, k8s CronJob
**Confidence:** HIGH (all key patterns verified against live codebase)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Theme 1 — Forget API surface**
- D-1.1: auth gate = admin OR self-delete (`jwt.user_id == target_user_id`); 403 if neither
- D-1.2: scope = `long_term_facts` ONLY; short-term Redis + `user_profile` NOT cleared (v1.6)
- D-1.3: 200 + `deleted_row_count=0` (idempotent); 404 for bad user_id format or tenant mismatch; 403 auth fail; 400 missing X-Confirm-Delete
- D-1.4: `X-Confirm-Delete: yes` header REQUIRED; 400 if absent
- D-1.5: `forget_user` raises typed `MemoryForgetError` on `asyncpg.PostgresError`; controller catches → 500 sanitized

**Theme 2 — Audit-log shape**
- D-2.1: TWO new `AuditAction` values: `MEMORY_FORGET` + `MEMORY_EVICT`
- D-2.2: ONE `audit_log` row PER bucket touched in a sweep (not per sweep run)
- D-2.3: audit write AFTER the DELETE, with actual `deleted_row_count`
- D-2.4: forget detail = `{target_user_id, target_tenant_id, deleted_row_count, actor_user_id, actor_is_admin, requesting_ip}`; evict detail = `{target_user_id, target_tenant_id, deleted_count, cap_value, remaining_count, mode}`

**Theme 3 — Eviction operator UX**
- D-3.1: audit-mode output = stdout JSON-lines + `audit_log` table (both sinks); no separate file
- D-3.2: first-run safety = runbook only; no code-enforced preflight
- D-3.3: CronJob YAML = k8s only; other runtimes are operator's responsibility
- D-3.4: daily @ 3am UTC (`0 3 * * *`)

**Theme 4 — Docs reconciliation**
- D-4.1: EVICT-03 is currently UN-MARKED (`[ ]`); re-mark `[x]` at Phase 25 verifier close
- D-4.2: single file `docs/memory-eviction.md`; keep existing 49 LOC; add ~80-130 LOC; final ~120-180 LOC

### Claude's Discretion

- `MemoryForgetError` location: alongside `MemoryFactWriteError` in `services/memory/memory_service.py`
- `forget_user` row count: `int(status.split()[1])` from `conn.execute()` return value (cheaper than RETURNING)
- OpenAPI grouping: `tags=["admin", "gdpr"]`
- Unit tests mock `controllers.memory.audit_service.log` (consumer-path per v1.3 D-13/D-15)
- Eviction CLI flags: `--mode={audit,enforce}`, `--batch-size N` (default 1000), `--user-id UUID` (optional scoped sweep)
- `forget` endpoint: `?user_id=alice` query-param; no request body
- CronJob YAML field values: match existing `k8s/rag-api/deployment.yaml` (namespace `rag-enterprise`, image `rag-enterprise:latest`)
- `sweep_run_id`: UUID generated once at script start; propagated in each bucket's audit row `detail` for sweep-level correlation

### Deferred Ideas (OUT OF SCOPE)

- `save_fact` pre-INSERT cap check (v1.7+)
- Forget API extension to short-term Redis + `user_profile` (v1.7+)
- Per-tenant capacity overrides + importance decay (v1.7+)
- Cap auto-tuning from distribution percentiles (v1.7+)
- Code-enforced enforce-mode preflight (v1.7+)
- `docs/memory-ops.md` rename (v1.7+)
- Bulk-forget admin endpoint for entire tenant (v1.7+)

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EVICT-01 | `scripts/evict_long_term_facts.py` — per-bucket cap enforcement, importance+created_at tie-break, 1000 rows/txn chunked DELETE, idempotent, audit-log per bucket | Pitfall 1 (register_vector), Pitfall 2 (chunked DELETE row count), Code Example §E1, §E2 |
| EVICT-02 | `--mode=audit\|enforce` flag; audit logs to stdout JSON-lines + audit_log; enforce deletes | Pitfall 3 (audit_db_enabled=False), Pitfall 5 (AuditAction enum position), Code Example §E3 |
| EVICT-03 | `docs/memory-eviction.md` extension: k8s CronJob YAML, cap tuning, audit→enforce workflow, forget-API curl; ~120-180 LOC final | k8s YAML pattern from `k8s/rag-api/deployment.yaml`, existing 49 LOC preserved |
| GDPR-01 | `LongTermMemory.forget_user(user_id, tenant_id) → int`; narrow-except asyncpg.PostgresError; typed MemoryForgetError | Code Example §E4, Pitfall 2 (row count parsing), Pitfall 4 (InterfaceError) |
| GDPR-02 | `DELETE /api/v1/memory/forget?user_id=...`; admin OR self-delete auth; X-Confirm-Delete header; 200/400/403/404 | Code Example §E5, Pitfall 6 (Header alias casing), Pitfall 7 (Depends order) |
| GDPR-03 | Audit-log entry per forget call (actor, target, count, timestamp); AFTER DELETE (D-2.3); MEMORY_FORGET enum | Code Example §E3, §E5, Pitfall 3 (audit_db_enabled), Pitfall 5 (enum extension) |

</phase_requirements>

---

## Summary

Phase 25 ships three production surfaces: (1) `scripts/evict_long_term_facts.py` — a standalone operator CLI with `--mode=audit|enforce` that caps `long_term_facts` growth per `(user_id, tenant_id)` bucket via chunked DELETE ordered by lowest importance then oldest created_at; (2) `LongTermMemory.forget_user(user_id, tenant_id) → int` + `DELETE /api/v1/memory/forget` admin endpoint with admin-or-self-delete auth and a `X-Confirm-Delete: yes` guard header; (3) two new `AuditAction` enum values (`MEMORY_FORGET`, `MEMORY_EVICT`) with per-call and per-bucket audit rows written post-fact. The phase also extends `docs/memory-eviction.md` from 49 to ~120-180 LOC with the CronJob YAML, audit→enforce runbook, and forget-API curl.

Key risks: (1) asyncpg returns a status string (not a rowcount integer) from `conn.execute()`; the eviction loop and `forget_user` must parse `int(status.split()[1])` — mishandling this silently returns 0. (2) The `audit_log` table is INSERT-ONLY (REVOKE UPDATE, DELETE) — Phase 25 writes only; any UPDATE/DELETE attempt against it will fail at the DB layer. (3) `audit_db_enabled` defaults to `False` in `config/settings.py`; audit rows are file-logged but NOT written to PG unless the setting is True — integration tests must set this flag to verify the DB sink.

**Primary recommendation:** Mirror `scripts/backfill_fact_embeddings.py` exactly for the eviction CLI shape; mirror `save_fact` exactly for `forget_user`; mirror `controllers/api.py:400` for the endpoint template; extend `AuditAction` in-place with two new string-enum values.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Cap enforcement (eviction) | Database / Storage | — | Bulk DELETE against `long_term_facts`; no API boundary crossed |
| Forget-user deletion | API / Backend | Database | HTTP endpoint drives asyncpg DELETE; controller owns auth gate |
| Auth (admin / self-delete) | API / Backend | — | JWT-decoded `AuthenticatedUser` is resolved in FastAPI Depends |
| Confirmation header | API / Backend | — | FastAPI `Header(alias="X-Confirm-Delete")` dependency |
| Audit logging | API / Backend | Database / Storage | `AuditService.log()` is called from controller + eviction script; DB flush is async |
| GDPR scope (long_term_facts only) | API / Backend | — | D-1.2 locks scope; no Redis / user_profile involvement |
| Operator runbook (CronJob) | CDN / Static (docs) | — | YAML lives in docs; k8s schedules the CronJob |

---

## Standard Stack

### Core (zero new packages — all reused from existing project)

| Module | Purpose in Phase 25 | Source |
|--------|---------------------|--------|
| `asyncpg` 0.30.0 | chunked DELETE + pool reuse | already installed |
| `fastapi` | `Header`, `HTTPException`, `Depends`, `APIRouter` | already installed |
| `loguru` | structured logging in CLI + service | already installed |
| `services/audit/audit_service.py` | `AuditAction`, `AuditEvent`, `AuditResult`, `get_audit_service()` | existing |
| `services/auth/oidc_auth.py` | `AuthenticatedUser`, `get_current_user` | existing |
| `services/memory/memory_service.py` | `LongTermMemory`, `MemoryFactWriteError` (pattern source) | existing |
| `scripts/backfill_fact_embeddings.py` | CLI shape reference | existing |
| `controllers/api.py:400` | admin endpoint template | existing |

**Installation:** No new packages required.

---

## Package Legitimacy Audit

> Not applicable — Phase 25 installs zero new packages. All dependencies are pre-existing project dependencies.

**Packages removed due to slopcheck verdict:** none
**Packages flagged as suspicious:** none

---

## Architecture Patterns

### System Architecture Diagram

```
Operator / CronJob
     │  --mode=audit|enforce
     ▼
scripts/evict_long_term_facts.py
     │  SELECT buckets over cap
     │  → stdout JSON-lines (audit mode)
     │  → DELETE WHERE id IN ($chunk) (enforce mode)
     ▼
LongTermMemory._get_pool()        ← register_vector codec (Pitfall 1)
     │
     ├── audit_service.log(MEMORY_EVICT)  ←── AFTER each bucket DELETE (D-2.3)
     └── stdout JSON-lines  ←── D-3.1 both sinks

HTTP Client (admin JWT)
     │  DELETE /api/v1/memory/forget?user_id=alice
     │  X-Confirm-Delete: yes
     ▼
controllers/memory.py  FastAPI router
     │  Depends(get_current_user)     ← AuthenticatedUser (401 if missing)
     │  Header(alias="X-Confirm-Delete")  ← 400 if absent/wrong
     │  auth gate (is_admin OR self)  ← 403 if fails
     │  user_id format validation     ← 404 if invalid
     ▼
LongTermMemory.forget_user(user_id, tenant_id) → int
     │  asyncpg DELETE WHERE user_id=$1 AND tenant_id=$2
     │  int(status.split()[1])   ← row count (Pitfall 2)
     └── asyncpg.PostgresError → MemoryForgetError (D-1.5)
     ▼
audit_service.log(MEMORY_EVICT)  ←── AFTER DELETE (D-2.3)
     │
     ├── loguru file (always)
     └── PG audit_log INSERT (if audit_db_enabled=True)  ← INSERT-ONLY table
```

### Recommended Project Structure

```
scripts/
└── evict_long_term_facts.py      # NEW — operator CLI (EVICT-01, EVICT-02)

services/memory/
└── memory_service.py             # MODIFIED — add MemoryForgetError + forget_user()

services/audit/
└── audit_service.py              # MODIFIED — add MEMORY_FORGET + MEMORY_EVICT to AuditAction

controllers/
└── memory.py                     # NEW — DELETE /api/v1/memory/forget endpoint (GDPR-02)

docs/
└── memory-eviction.md            # EXTENDED — keep 49 LOC, add ~80-130 LOC (EVICT-03)

config/
└── settings.py                   # MODIFIED — add memory_facts_cap_per_user: int = 500

tests/unit/
├── test_evict_long_term_facts.py # NEW
├── test_memory_forget.py         # NEW (forget_user unit tests)
└── test_memory_controller.py     # NEW (GDPR-02 controller tests)

tests/integration/
└── test_gdpr_forget_e2e.py       # NEW (live PG + admin JWT)
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| asyncpg row count from DELETE | Manual RETURNING id + len() | `int(status.split()[1])` on execute() return | No row-data transfer; asyncpg cursor.py already uses this pattern (line 319) |
| FastAPI header parsing | Manual request.headers.get() | `Header(alias="X-Confirm-Delete")` as function param | Auto-generates OpenAPI docs; raises 422 on missing (override to 400 in the handler body after catching the string value) |
| Chunked DELETE IDs | Recursive CTEs | `SELECT id ... LIMIT N` + `DELETE WHERE id = ANY($1::uuid[])` in a txn | Simple, readable, matches backfill pattern |
| Audit singleton | Re-instantiating AuditService | `get_audit_service()` singleton | Service owns its buffer + flush lifecycle |
| Admin auth check | Re-implementing JWT parsing | `Depends(get_current_user)` + `user.is_admin` | OIDCAuthService already handles local JWT + OIDC modes |
| Per-bucket row count | COUNT(*) query before and after | ORDER BY importance ASC, created_at ASC + DELETE first N rows | One ordered DELETE; `int(status.split()[1])` gives count without extra round-trip |

**Key insight:** `asyncpg.Connection.execute()` returns a PostgreSQL status string (`"DELETE N"`). Parsing `int(status.split()[1])` is the idiomatic asyncpg row count path — confirmed in `asyncpg/cursor.py:319`. Never use `RETURNING` for a simple row count; it transfers all row data unnecessarily.

---

## Common Pitfalls

### Pitfall 1: Missing `register_vector` codec in eviction CLI
**What goes wrong:** `evict_long_term_facts.py` runs outside the FastAPI app. If it creates a bare `asyncpg.create_pool()` without the `init=_init_conn` hook that calls `register_vector(conn)`, the `vector` type codec is absent and any comparison involving the `embedding` column (even a WHERE clause that doesn't use it) may fail with `DataError: unknown type`.
**Why it happens:** The pgvector codec must be registered per-connection, not just once at module import. The eviction script reads `importance` and `created_at` only — but asyncpg still decodes the full row type at DESCRIBE time if `SELECT *` is used, or raises on the `embedding` column if it appears in the result set.
**How to avoid:** Reuse `LongTermMemory()._get_pool()` exactly as `backfill_fact_embeddings.py` does:
```python
mem = LongTermMemory()
pool = await mem._get_pool()
```
Do NOT call `asyncpg.create_pool()` directly in the eviction script. The `_get_pool()` method registers the codec via `init=_init_conn`.
**Warning signs:** `UndefinedObjectError: type "vector" does not exist` or `DataError: unknown type` in eviction script logs when running against a DB that has the `embedding` column.

---

### Pitfall 2: asyncpg `execute()` returns a string, not an int
**What goes wrong:** `deleted_count = await conn.execute("DELETE FROM long_term_facts WHERE ...")` assigns the string `"DELETE 5"` (or `"DELETE 0"`) to `deleted_count`. If the code then compares `deleted_count > 0` or passes it as an integer, it silently misbehaves (string `"DELETE 5"` is truthy; no TypeError raised).
**Why it happens:** `asyncpg.Connection.execute()` follows the PostgreSQL wire protocol: it returns the command completion tag as a string. This is consistent with `asyncpg/cursor.py:319` which does `int(status.split()[1])`.
**How to avoid:** Always parse immediately:
```python
status = await conn.execute(
    "DELETE FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
    user_id, tenant_id,
)
deleted_row_count = int(status.split()[1])  # "DELETE 5" → 5
```
**Warning signs:** `forget_user()` always returns 0 (string `"DELETE 0"` evaluated as int is 0, but `"DELETE 5"` returns truthy integer — easy to miss in tests if the 0-delete case is not covered).

---

### Pitfall 3: `audit_db_enabled` defaults to `False` — audit rows appear in file log only
**What goes wrong:** `AuditService.log()` writes the file log unconditionally but only appends to the buffer (and flushes to PG) when `settings.audit_db_enabled` is `True`. In `config/settings.py`, the default is `False`. Integration tests that assert the `audit_log` table has a new row will find it empty.
**Why it happens:** The two-sink design is intentional (file log is the high-reliability sink; DB is for queryable dashboards). The default `False` means a fresh deployment doesn't require a DB audit table.
**How to avoid:**
- Integration tests: `monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", True)` + force `await audit_service.flush()` at the end of the test before asserting DB rows.
- Unit tests: mock `audit_service.log` at the consumer path (`controllers.memory.audit_service.log`) — don't test the DB sink at unit level.
- EVICT-03 doc: note the operator must set `AUDIT_DB_ENABLED=true` in CronJob env vars to get PG-queryable eviction records; stdout JSON-lines always work regardless.
**Warning signs:** Integration test asserts `SELECT count(*) FROM audit_log WHERE action='MEMORY_FORGET'` returns 1 but gets 0. Check whether `audit_db_enabled` is patched to `True` in the test.

---

### Pitfall 4: `asyncpg.InterfaceError` not caught alongside `asyncpg.PostgresError`
**What goes wrong:** `asyncpg.InterfaceError` (connection pool closed, connection in wrong state) is NOT a subclass of `asyncpg.PostgresError`. The backfill script catches both as `asyncpg.Error` — which is the common base. If `forget_user` only catches `asyncpg.PostgresError`, a pool-level failure during forget will propagate as an untyped exception.
**Why it happens:** The asyncpg exception hierarchy:
```
asyncpg.Error
├── asyncpg.PostgresError    # server-side errors
└── asyncpg.InterfaceError   # client-side pool/state errors
```
**How to avoid:** Catch `asyncpg.PostgresError` in `forget_user` per D-1.5 (mirrors `save_fact`). For the eviction script's chunked DELETE loop (where pool integrity matters more), catch `(asyncpg.PostgresError, asyncpg.InterfaceError)` as the backfill does. The distinction is: `forget_user` is a short single-txn call (PostgresError is sufficient); the eviction loop runs many txns (add InterfaceError for robustness).
**Warning signs:** `forget_user` unit tests pass, but integration test with a pool fault raises `asyncpg.InterfaceError` which appears as an unhandled 500 with a non-sanitized traceback.

---

### Pitfall 5: Extending `AuditAction` enum — string enum ordering and import caching
**What goes wrong:** `AuditAction` is a `str` Enum used as a DB column value. Adding new values must preserve existing string values exactly. If a dev accidentally renames an existing value (e.g., capitalizes `MEMORY_FORGET` as `Memory_Forget`), existing audit rows won't match the enum.
**Why it happens:** `AuditAction` extends `str`, so the enum _value_ is the string persisted to DB. Reordering members doesn't matter; values must be stable. The audit singleton is module-level — tests that import `audit_service` before patching will get the old enum.
**How to avoid:**
- Add new values at the END of the enum block (below `TOKEN_VERIFIED`). Do not insert between existing members.
- Values: `MEMORY_FORGET = "MEMORY_FORGET"` and `MEMORY_EVICT = "MEMORY_EVICT"` (uppercase, matches existing pattern).
- Unit tests that check `AuditAction.MEMORY_FORGET.value == "MEMORY_FORGET"` catch regressions.
- Reset the audit singleton in autouse fixtures: `monkeypatch.setattr(mod, "_audit_service", None)` — already done in `test_audit_service.py`.
**Warning signs:** `AttributeError: 'AuditAction' has no 'MEMORY_FORGET'` — enum extension not imported; `KeyError` in audit_log query — value mismatch between code and DB.

---

### Pitfall 6: FastAPI `Header` dependency and `X-Confirm-Delete` header casing
**What goes wrong:** FastAPI's `Header` dependency converts hyphenated header names to underscored, lowercased parameter names by default. `X-Confirm-Delete` becomes `x_confirm_delete`. If the function signature uses `confirm_delete: str = Header(...)` without `alias`, FastAPI looks for the `confirm-delete` header (lowercased, hyphenated). The client sends `X-Confirm-Delete` (HTTP/2 lowercases it to `x-confirm-delete`); FastAPI's `alias` must match.
**Why it happens:** FastAPI header aliasing converts `_` → `-` in the `alias` string. The correct pattern is `Header(alias="X-Confirm-Delete")` which matches `x-confirm-delete` (case-insensitive HTTP header matching).
**How to avoid:**
```python
from fastapi import Header

async def forget_user_endpoint(
    ...
    x_confirm_delete: str | None = Header(default=None, alias="X-Confirm-Delete"),
) -> ...:
    if x_confirm_delete != "yes":
        raise HTTPException(status_code=400, detail="X-Confirm-Delete: yes header required")
```
Use `default=None` (not `...`) so FastAPI doesn't auto-raise a 422 — instead raise a controlled 400 in the handler body. OpenAPI will document the header automatically.
**Warning signs:** Client sends `X-Confirm-Delete: yes` and gets `400 X-Confirm-Delete: yes header required` even though the header is present. Cause: alias mismatch; FastAPI saw the header but matched it to a different parameter.

---

### Pitfall 7: `Depends(get_current_user)` must come before `Header` dependency in function signature
**What goes wrong:** FastAPI resolves dependencies in declaration order within the function signature. If `Header(alias="X-Confirm-Delete")` is declared before `Depends(get_current_user)`, a missing/invalid JWT will generate a 422 from the Header validator before the 401 from the auth dependency — reversing the expected priority.
**Why it happens:** FastAPI processes all dependencies concurrently (or in order for synchronous deps). The first dep that raises an exception wins. Auth should always be checked first.
**How to avoid:** Declare `user: AuthenticatedUser = Depends(get_current_user)` as the first parameter after `user_id: str` (the query param). Declare `x_confirm_delete` after.
**Warning signs:** A request with no Authorization header and no `X-Confirm-Delete` header returns 422 (Header validation) instead of 401 (auth). Test: send a request with no auth but with `X-Confirm-Delete: yes` — should get 401, not 403/400.

---

### Pitfall 8: Chunked DELETE in eviction — losing position after a partial batch error
**What goes wrong:** The eviction loop selects N rows `WHERE row_count_per_bucket > cap ORDER BY importance ASC, created_at ASC LIMIT $batch_size`, deletes them, then repeats. If the DELETE txn fails mid-sweep and the script exits, the next run starts from scratch (idempotent). But if the loop retries the same batch without re-selecting, it may attempt to delete already-deleted rows (harmless for the DELETE itself, but the audit row would show `deleted_count=0` for a bucket that was partially evicted).
**Why it happens:** The eviction script is designed to be idempotent (re-run safe), not resumable from a mid-batch checkpoint. The backfill script uses `--resume-from-id` for resumability; the eviction script has no equivalent because the "cursor" is defined by which rows are still over-cap.
**How to avoid:** Accept idempotent-from-start behavior (same as EVICT-01 requirement). On error, log the exception, write `result=FAILED` to the audit row (or skip the audit row for that bucket), and either `continue` to the next bucket or `return 1` to abort the sweep. The next CronJob run will re-process the failed bucket from scratch. Document this in the runbook.
**Warning signs:** Audit log shows a bucket with `deleted_count < over_cap_by` — indicates partial eviction followed by a txn failure. Re-run to complete.

---

## ASSUMED Claims

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `settings.audit_db_enabled` defaults to `False` in all production deployments — operators who want PG-queryable audit rows must set `AUDIT_DB_ENABLED=true` explicitly. Verified in `config/settings.py:404`. | Pitfall 3, Code Examples | If a deployment overrides this to `True` by default, integration tests don't need to patch it — low-risk. But if production has it `False`, operators won't see audit rows in the DB until they set the env var. |
| A2 | `asyncpg.Connection.execute()` returns `"DELETE N"` as a string (not an integer). Pattern confirmed from `asyncpg/cursor.py:319` in installed `.venv`. If asyncpg upgrades change this, row-count parsing breaks silently. | Pitfall 2, Code Examples | asyncpg 0.30.0 installed. Verify against installed version before execution. |
| A3 | The `audit_log` table's `REVOKE UPDATE, DELETE` grant was applied at deployment time (v1.0 Phase 2). Phase 25 unit tests mock the DB; integration tests only INSERT. If the table was re-created without the REVOKE, Phase 25 code would still work (INSERT-only by convention, not by DB enforcement in dev). | Architecture | Low risk — Phase 25 never attempts UPDATE/DELETE on audit_log. |
| A4 | `controllers/memory.py` does not yet exist. The planner must create a new file with a `FastAPI APIRouter` and mount it in the main app. The mount point (in `controllers/api.py` or in `main.py` / `app.py`) must be verified before execution. | Standard Stack | If `controllers/memory.py` already exists (e.g. from a stale worktree), the planner must reconcile. |
| A5 | `settings.memory_facts_cap_per_user` does not yet exist in `config/settings.py`. The planner must add it. Verified by grepping settings.py — no match found. | Standard Stack | Low risk — adding a new settings field is a Wave 0 or Wave 1 task. |

---

## Code Examples

### §E1 — Eviction main loop (enforce mode, chunked DELETE)

```python
# Source: mirrors scripts/backfill_fact_embeddings.py (Plan 24-06) + EVICT-01 spec
# Key: reuse LongTermMemory._get_pool() for register_vector (Pitfall 1)
# Key: int(status.split()[1]) for row count (Pitfall 2)

async def evict_bucket(
    pool: asyncpg.Pool,
    user_id: str,
    tenant_id: str,
    cap: int,
    batch_size: int,
    mode: str,  # "audit" | "enforce"
    sweep_run_id: str,
    audit_svc: AuditService,
) -> int:
    """Evict one (user_id, tenant_id) bucket down to cap. Returns rows deleted."""
    # Count current rows in bucket
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS n FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        user_id, tenant_id,
    )
    row_count = int(row["n"]) if row else 0
    over_cap_by = max(0, row_count - cap)

    if over_cap_by == 0:
        return 0  # idempotent — nothing to do

    if mode == "audit":
        # stdout JSON-lines (D-3.1)
        import json, sys
        print(json.dumps({
            "bucket": {"user_id": user_id, "tenant_id": tenant_id},
            "row_count": row_count,
            "cap": cap,
            "over_cap_by": over_cap_by,
            "would_delete_count": over_cap_by,
            "sweep_run_id": sweep_run_id,
        }), file=sys.stdout, flush=True)
        # audit_log row with result=SKIPPED (D-3.1: both sinks)
        await audit_svc.log(AuditEvent(
            action=AuditAction.MEMORY_EVICT,
            user_id=user_id,
            tenant_id=tenant_id,
            result=AuditResult.SKIPPED,
            detail={
                "target_user_id": user_id,
                "target_tenant_id": tenant_id,
                "deleted_count": 0,
                "cap_value": cap,
                "remaining_count": row_count,
                "mode": "audit",
                "sweep_run_id": sweep_run_id,
            },
        ))
        return 0

    # enforce mode — chunked DELETE
    total_deleted = 0
    remaining_to_delete = over_cap_by

    while remaining_to_delete > 0:
        chunk = min(batch_size, remaining_to_delete)
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    status = await conn.execute(
                        """
                        DELETE FROM long_term_facts
                        WHERE id IN (
                            SELECT id FROM long_term_facts
                            WHERE user_id=$1 AND tenant_id=$2
                            ORDER BY importance ASC, created_at ASC
                            LIMIT $3
                        )
                        """,
                        user_id, tenant_id, chunk,
                    )
            deleted_in_chunk = int(status.split()[1])  # "DELETE N" → N (Pitfall 2)
            total_deleted += deleted_in_chunk
            remaining_to_delete -= deleted_in_chunk
            if deleted_in_chunk == 0:
                break  # idempotent — nothing left to delete
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            logger.error(
                "eviction chunk DELETE failed",
                user_id=user_id, tenant_id=tenant_id,
                exc_info=exc, operation="evict_bucket_chunk",
            )
            raise  # propagate to caller; outer loop handles audit

    # audit_log row AFTER DELETE (D-2.3) — actual deleted_count
    await audit_svc.log(AuditEvent(
        action=AuditAction.MEMORY_EVICT,
        user_id=user_id,
        tenant_id=tenant_id,
        result=AuditResult.SUCCESS,
        detail={
            "target_user_id": user_id,
            "target_tenant_id": tenant_id,
            "deleted_count": total_deleted,
            "cap_value": cap,
            "remaining_count": row_count - total_deleted,
            "mode": "enforce",
            "sweep_run_id": sweep_run_id,
        },
    ))
    return total_deleted
```

---

### §E2 — Eviction script CLI skeleton (async main)

```python
# Source: mirrors scripts/backfill_fact_embeddings.py argparse + asyncio.run shape
#!/usr/bin/env python
"""scripts/evict_long_term_facts.py — Phase 25 / EVICT-01 + EVICT-02 eviction CLI."""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from loguru import logger

from config.settings import settings
from services.audit.audit_service import AuditAction, AuditEvent, AuditResult, get_audit_service
from services.memory.memory_service import LongTermMemory
from utils.logger import setup_logger


async def main_async(mode: str, batch_size: int, user_id: str | None) -> int:
    setup_logger()
    # Pitfall 1: reuse LongTermMemory pool (register_vector codec inherited)
    mem = LongTermMemory()
    pool = await mem._get_pool()
    audit_svc = get_audit_service()
    sweep_run_id = uuid.uuid4().hex  # D-2.4 correlation ID across buckets

    cap = settings.memory_facts_cap_per_user  # A5: new setting, default 500

    # SELECT buckets over cap (or single user if --user-id provided)
    if user_id:
        buckets = await pool.fetch(
            """
            SELECT user_id, tenant_id, COUNT(*) AS n
            FROM long_term_facts
            WHERE user_id=$1
            GROUP BY user_id, tenant_id
            HAVING COUNT(*) > $2
            """,
            user_id, cap,
        )
    else:
        buckets = await pool.fetch(
            """
            SELECT user_id, tenant_id, COUNT(*) AS n
            FROM long_term_facts
            GROUP BY user_id, tenant_id
            HAVING COUNT(*) > $1
            """,
            cap,
        )

    if not buckets:
        logger.info("eviction: no buckets over cap", cap=cap, mode=mode)
        return 0

    total_deleted = 0
    for b in buckets:
        try:
            deleted = await evict_bucket(
                pool=pool,
                user_id=b["user_id"],
                tenant_id=b["tenant_id"],
                cap=cap,
                batch_size=batch_size,
                mode=mode,
                sweep_run_id=sweep_run_id,
                audit_svc=audit_svc,
            )
            total_deleted += deleted
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            logger.error("eviction bucket failed", exc_info=exc)
            # continue to next bucket — CronJob restartPolicy: OnFailure handles retry

    await audit_svc.flush()  # flush buffer before script exit
    logger.info("eviction sweep complete", mode=mode, total_deleted=total_deleted)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evict long_term_facts rows over per-user cap.")
    parser.add_argument("--mode", choices=["audit", "enforce"], default="audit",
                        help="audit: log only; enforce: delete rows (default: audit)")
    parser.add_argument("--batch-size", type=int, default=1000, metavar="N",
                        help="Rows per txn commit batch (default: 1000)")
    parser.add_argument("--user-id", type=str, default=None, metavar="UUID",
                        help="Scope sweep to a single user_id (optional)")
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args.mode, args.batch_size, args.user_id)))


if __name__ == "__main__":
    main()
```

---

### §E3 — AuditAction enum extension (two new values)

```python
# Source: services/audit/audit_service.py — extend in-place below TOKEN_VERIFIED
# Verified: AuditAction is a str Enum with 12 existing values (TOKEN_VERIFIED is last)

class AuditAction(str, Enum):
    QUERY             = "QUERY"
    INGEST            = "INGEST"
    DELETE_DOC        = "DELETE_DOC"
    LOGIN             = "LOGIN"
    LOGOUT            = "LOGOUT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED      = "RATE_LIMITED"
    PII_DETECTED      = "PII_DETECTED"
    RULE_BLOCKED      = "RULE_BLOCKED"
    FEEDBACK          = "FEEDBACK"
    KB_UPDATE         = "KB_UPDATE"
    TOKEN_VERIFIED    = "TOKEN_VERIFIED"
    # Phase 25 — D-2.1 — GDPR forget API + eviction job
    MEMORY_FORGET     = "MEMORY_FORGET"   # forget_user() API call
    MEMORY_EVICT      = "MEMORY_EVICT"    # eviction sweep (one row per bucket)
```

---

### §E4 — `forget_user` method body (GDPR-01)

```python
# Source: mirrors save_fact narrow-exception pattern (memory_service.py:339-376)
# Key: int(status.split()[1]) for row count (Pitfall 2)
# Key: D-1.5 — asyncpg.PostgresError → MemoryForgetError

class MemoryForgetError(Exception):
    """Typed error for forget_user DB failure.

    Wraps ``asyncpg.PostgresError`` so the controller can surface a sanitized
    500 without exposing DB internals. Mirrors ``MemoryFactWriteError``.
    """


# Inside LongTermMemory:

async def forget_user(self, user_id: str, tenant_id: str) -> int:
    """Delete all long_term_facts rows for a (user_id, tenant_id) pair.

    Returns the number of rows deleted (0 = idempotent no-op if nothing to delete).
    Scope: long_term_facts ONLY (D-1.2). Short-term Redis and user_profile are NOT cleared.

    Raises:
        MemoryForgetError: on asyncpg.PostgresError (wraps DB error; caller surfaces 500).
    """
    try:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
                user_id, tenant_id,
            )
        return int(status.split()[1])  # "DELETE N" → N  (Pitfall 2)
    except asyncpg.PostgresError as exc:
        logger.error(
            "memory service failure", operation="forget_user", exc_info=exc,
        )
        raise MemoryForgetError("forget failed") from exc
```

---

### §E5 — `DELETE /api/v1/memory/forget` controller (GDPR-02 + GDPR-03)

```python
# Source: mirrors controllers/api.py:400 admin endpoint + oidc_auth.py:251 get_current_user
# New file: controllers/memory.py
# Key: Header(alias="X-Confirm-Delete", default=None) — Pitfall 6
# Key: Depends order — user before header — Pitfall 7
# Key: audit AFTER DELETE — D-2.3

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger

from services.audit.audit_service import AuditAction, AuditEvent, AuditResult, get_audit_service
from services.auth.oidc_auth import AuthenticatedUser, get_current_user
from services.memory.memory_service import LongTermMemory, MemoryForgetError

router = APIRouter()


@router.delete("/memory/forget", tags=["admin", "gdpr"])
async def forget_user_memory(
    user_id: str,                                                         # query param
    request: Request,                                                     # for ip_address
    user: AuthenticatedUser = Depends(get_current_user),                  # auth FIRST (Pitfall 7)
    x_confirm_delete: str | None = Header(default=None, alias="X-Confirm-Delete"),  # Pitfall 6
) -> dict:
    """Delete all long_term_facts for a given user_id.

    Requires admin claim OR self-delete (jwt.user_id == target user_id).
    Requires X-Confirm-Delete: yes header (accident prevention, D-1.4).
    Scope: long_term_facts ONLY. Short-term Redis history and user_profile are NOT cleared (D-1.2).
    Returns: {deleted_row_count: N} — idempotent, 200 even if N==0 (D-1.3).
    """
    # 1. Confirmation header gate (400) — D-1.4
    if x_confirm_delete != "yes":
        raise HTTPException(
            status_code=400,
            detail="X-Confirm-Delete: yes header required",
        )

    # 2. Auth gate (403) — D-1.1: admin OR self-delete
    if not (user.is_admin or user.user_id == user_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    # 3. user_id format validation (404) — D-1.3
    # user_id from JWT tenant_id must match the authenticated user's tenant
    target_tenant_id = user.tenant_id
    if not user_id:  # empty string or malformed
        raise HTTPException(status_code=404, detail="user_id required")

    # 4. Execute forget
    try:
        # Lazy import — circular-import resilience (repo convention)
        mem = LongTermMemory()
        deleted_row_count = await mem.forget_user(user_id, target_tenant_id)
    except MemoryForgetError as exc:
        logger.error("forget_user failed", user_id=user_id, exc_info=exc)
        raise HTTPException(status_code=500, detail="Memory forget failed")

    # 5. Audit log AFTER DELETE (D-2.3) — with actual deleted_row_count
    ip_address = request.client.host if request.client else ""
    await get_audit_service().log(AuditEvent(
        user_id=user.user_id,    # actor (admin performing the forget, or self)
        tenant_id=target_tenant_id,
        action=AuditAction.MEMORY_FORGET,
        resource_id=user_id,     # target user whose data was deleted
        ip_address=ip_address,
        result=AuditResult.SUCCESS,
        detail={
            "target_user_id": user_id,
            "target_tenant_id": target_tenant_id,
            "deleted_row_count": deleted_row_count,
            "actor_user_id": user.user_id,
            "actor_is_admin": user.is_admin,
            "requesting_ip": ip_address,
        },
    ))

    return {"deleted_row_count": deleted_row_count}
```

---

### §E6 — k8s CronJob YAML (EVICT-03 / D-3.3 + D-3.4)

```yaml
# docs/memory-eviction.md CronJob YAML block
# Namespace: rag-enterprise (matches k8s/rag-api/deployment.yaml)
# Schedule: daily 3am UTC (D-3.4)
# successfulJobsHistoryLimit: 3 + failedJobsHistoryLimit: 1 (D-2.4 specifics note)
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ltf-eviction
  namespace: rag-enterprise
spec:
  schedule: "0 3 * * *"         # daily @ 03:00 UTC (D-3.4)
  successfulJobsHistoryLimit: 3  # bound history accumulation
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: eviction
              image: rag-enterprise:latest
              command:
                - uv
                - run
                - python
                - scripts/evict_long_term_facts.py
                - --mode=enforce
                - --batch-size=1000
              env:
                - name: PG_DSN
                  valueFrom:
                    secretKeyRef:
                      name: rag-secrets
                      key: PG_DSN
                - name: MEMORY_FACTS_CAP_PER_USER
                  valueFrom:
                    configMapKeyRef:
                      name: rag-config
                      key: MEMORY_FACTS_CAP_PER_USER
                - name: AUDIT_DB_ENABLED
                  value: "true"  # write eviction records to PG audit_log
              resources:
                requests:
                  cpu: "200m"
                  memory: "256Mi"
                limits:
                  cpu: "500m"
                  memory: "512Mi"
```

---

## Validation Architecture

| REQ-ID | Behavior | Test File | Fixtures | Gate Type | Expected GREEN |
|--------|----------|-----------|----------|-----------|----------------|
| EVICT-01 SC-1 audit mode | Audit run on 600-row + 100-row buckets: stdout JSON-lines for 600-row bucket; zero deletes | `tests/unit/test_evict_long_term_facts.py::test_audit_mode_logs_and_no_delete` | mock pool with fake fetchrow + fetchall | unit | 600-row bucket appears in stdout; `pool.execute` NOT called for DELETE |
| EVICT-01 SC-1 enforce mode | Enforce drops 600-row bucket to 500; 100-row untouched | `tests/integration/test_gdpr_forget_e2e.py::test_enforce_mode_caps_bucket` | `pgvector_pool`, `clean_long_term_facts` | integration | `SELECT COUNT(*) WHERE user_id=u1` returns 500; user_id=u2 bucket unchanged |
| EVICT-01 SC-2 tie-break | With cap=2, 3 rows (importance=0.2@T0, 0.2@T1, 0.8@T2): deletes 0.2@T0 | `tests/integration/test_gdpr_forget_e2e.py::test_eviction_tiebreak_correctness` | `pgvector_pool`, `clean_long_term_facts` | integration | Row with created_at=T0, importance=0.2 is gone; other two survive |
| EVICT-01 idempotent | Second enforce run on already-at-cap bucket: zero deletes | `tests/unit/test_evict_long_term_facts.py::test_enforce_idempotent` | mock pool returning 0-row bucket count | unit | `evict_bucket` returns 0; no DELETE executed |
| EVICT-02 audit stdout + audit_log | Audit mode writes JSON-line to stdout AND audit_log with result=SKIPPED | `tests/unit/test_evict_long_term_facts.py::test_audit_both_sinks` | mock pool, mock `audit_service.log` | unit | `audit_svc.log.call_args.kwargs` has `result=AuditResult.SKIPPED, action=AuditAction.MEMORY_EVICT` |
| EVICT-02 audit_log row content | MEMORY_EVICT row has `deleted_count=0, mode=audit, sweep_run_id` | (same test as above) | — | unit | `detail["mode"]=="audit"`, `detail["deleted_count"]==0`, `detail["sweep_run_id"]` is non-empty |
| EVICT-03 docs | `docs/memory-eviction.md` contains CronJob YAML, audit→enforce workflow, forget curl | `tests/unit/test_evict_long_term_facts.py::test_docs_anchors` | file read | unit (content check) | All section headings present; no broken anchors |
| GDPR-01 forget_user happy path | `forget_user("alice", "acme")` returns deleted_row_count > 0 | `tests/unit/test_memory_forget.py::test_forget_user_returns_row_count` | mock pool returning `"DELETE 3"` from execute() | unit | Return value is int 3 |
| GDPR-01 idempotent | `forget_user` on user with 0 rows returns 0 | `tests/unit/test_memory_forget.py::test_forget_user_idempotent` | mock pool returning `"DELETE 0"` | unit | Return value is int 0 |
| GDPR-01 MemoryForgetError | `asyncpg.PostgresError` in execute → `MemoryForgetError` raised | `tests/unit/test_memory_forget.py::test_forget_user_raises_on_pg_error` | mock pool raising PostgresError | unit | `MemoryForgetError` is raised (not PostgresError) |
| GDPR-02 SC-3 admin JWT | `DELETE /memory/forget?user_id=alice` with admin JWT → 200 + row count | `tests/unit/test_memory_controller.py::test_forget_admin_jwt_200` | FastAPI TestClient, mock `forget_user`, mock `audit_service.log` | unit | Status 200, `{"deleted_row_count": N}` |
| GDPR-02 SC-3 self-delete | Non-admin JWT with `user_id == jwt.user_id` → 200 | `tests/unit/test_memory_controller.py::test_forget_self_delete_200` | same | unit | Status 200 |
| GDPR-02 SC-3 forbidden | Non-admin JWT for different user_id → 403 | `tests/unit/test_memory_controller.py::test_forget_non_admin_other_user_403` | same | unit | Status 403 |
| GDPR-02 missing X-Confirm-Delete | No header → 400 | `tests/unit/test_memory_controller.py::test_forget_missing_confirm_header_400` | TestClient, no header | unit | Status 400 |
| GDPR-02 wrong X-Confirm-Delete | `X-Confirm-Delete: no` → 400 | `tests/unit/test_memory_controller.py::test_forget_wrong_confirm_header_400` | TestClient, header=no | unit | Status 400 |
| GDPR-02 integration | Admin JWT + real PG → rows deleted + 0 on re-call | `tests/integration/test_gdpr_forget_e2e.py::test_forget_api_e2e` | `pgvector_pool`, FastAPI TestClient with real JWT | integration | 200 with count; re-call returns count=0 |
| GDPR-03 audit row content | forget call produces MEMORY_FORGET audit row with actor + target + count | `tests/unit/test_memory_controller.py::test_forget_audit_row_content` | mock `audit_service.log`, check call_args | unit | `action=MEMORY_FORGET`, `detail["actor_user_id"]`, `detail["deleted_row_count"]`, `detail["target_user_id"]` all present |
| GDPR-03 audit AFTER DELETE | audit.log called AFTER `forget_user()` completes (not before) | (same test) | mock call order tracking | unit | `audit_service.log.call_count == 1` only after `forget_user` mock resolves |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit/test_evict_long_term_facts.py tests/unit/test_memory_forget.py tests/unit/test_memory_controller.py -x -q`
- **Per wave merge:** `uv run pytest tests/unit/ -x -q --tb=short`
- **Phase gate:** Full suite green + integration tests with `uv run pytest tests/integration/test_gdpr_forget_e2e.py -m pgvector -x -q` against live PG before `/gsd-verify-work 25`

### Wave 0 Gaps

- [ ] `tests/unit/test_evict_long_term_facts.py` — covers EVICT-01, EVICT-02
- [ ] `tests/unit/test_memory_forget.py` — covers GDPR-01
- [ ] `tests/unit/test_memory_controller.py` — covers GDPR-02, GDPR-03
- [ ] `tests/integration/test_gdpr_forget_e2e.py` — covers SC-1, SC-2, SC-3 (live PG)
- [ ] `controllers/memory.py` — new file; router must be mounted in app entry point
- [ ] `config/settings.py` — `memory_facts_cap_per_user: int = 500` (A5 gap)

---

## Pre-tag Manual Verification

The following can only be verified against a live PostgreSQL instance with pgvector + admin JWT:

1. **SC-1 audit→enforce workflow:** Run `uv run python scripts/evict_long_term_facts.py --mode=audit` against a seeded DB with one bucket at 600 rows. Verify stdout JSON-line appears and `SELECT count(*)` is unchanged. Then run `--mode=enforce`. Verify count drops to 500.

2. **SC-2 tie-break correctness:** Seed a bucket with exactly 3 rows (importance=0.2 @T0, 0.2 @T1, 0.8 @T2) and `MEMORY_FACTS_CAP_PER_USER=2`. Run enforce. Verify the T0 row is gone; T1 and T2 survive.

3. **SC-3 admin DELETE e2e:** Issue `curl -X DELETE "http://localhost:8000/api/v1/memory/forget?user_id=alice" -H "Authorization: Bearer $ADMIN_JWT" -H "X-Confirm-Delete: yes"`. Verify 200 with `deleted_row_count`. Issue same request again. Verify `deleted_row_count=0` (idempotent).

4. **SC-3 non-admin self-delete:** Issue same curl with a non-admin JWT where `sub=alice`. Verify 200. Issue with non-admin JWT where `sub=bob`. Verify 403.

5. **SC-4 audit_log DB row:** With `AUDIT_DB_ENABLED=true`, run forget. Query `SELECT * FROM audit_log WHERE action='MEMORY_FORGET'`. Verify `detail` JSONB has all required fields.

6. **SC-5 docs anchors:** `uv run python -c "import markdown; ..."` or just inspect `docs/memory-eviction.md` manually — confirm no broken section anchors, CronJob YAML is syntactically valid (`kubectl apply --dry-run=client -f` on the extracted YAML block).

---

## State of the Art

| Old Approach | Current Approach | Changed | Impact |
|---|---|---|---|
| `cursor.rowcount` (psycopg2) | `int(status.split()[1])` from `execute()` return | asyncpg design | Parse the status tag string; `cursor.rowcount` is not the asyncpg idiom |
| FastAPI `Header(convert_underscores=True)` (pre-0.95) | `Header(alias="X-Confirm-Delete")` | FastAPI ≥ 0.95 | `alias` is explicit; `convert_underscores` default behavior still applies when alias not set |
| k8s CronJob `startingDeadlineSeconds` omitted | include `successfulJobsHistoryLimit: 3 + failedJobsHistoryLimit: 1` | k8s 1.21+ | Bounds job history to prevent unbounded Pod accumulation |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL + pgvector | EVICT-01, GDPR-01, integration tests | Must be confirmed live | asyncpg 0.30.0 installed | Integration tests skip via `pgvector_pool` skip-if-unavailable |
| `asyncpg` | All DB operations | ✓ | 0.30.0 | — |
| `fastapi` | GDPR-02 controller | ✓ | Installed | — |
| `loguru` | Structured logging | ✓ | Installed | — |
| `kubectl` | SC-5 CronJob dry-run validation | Not checked | — | Manual YAML inspection |

---

## Sources

### Primary (HIGH confidence — verified against live codebase)

- `services/audit/audit_service.py` — `AuditAction` enum (12 values), `AuditEvent` dataclass fields, `AuditService.log()` signature, `audit_db_enabled` default, INSERT-ONLY invariant
- `services/memory/memory_service.py` — `save_fact` narrow-exception pattern, `_get_pool()` with `register_vector`, `MemoryFactWriteError` class shape
- `services/auth/oidc_auth.py` — `AuthenticatedUser.is_admin`, `get_current_user` Depends shape, `HTTPException` error codes
- `controllers/api.py:400` — admin endpoint template (`@router.delete("/cache", tags=["admin"])`)
- `scripts/backfill_fact_embeddings.py` — async CLI shape: argparse, `asyncio.run`, `LongTermMemory()._get_pool()` reuse, chunked txn, `(asyncpg.PostgresError, asyncpg.InterfaceError)` narrow catch
- `config/settings.py` — `audit_db_enabled: bool = False` default; no `memory_facts_cap_per_user` field confirmed
- `tests/conftest.py` — `pgvector_pool`, `clean_long_term_facts`, `embedder_or_mock` fixture shapes
- `.venv/lib/.../asyncpg/cursor.py:319` — `int(status.split()[1])` row count parsing idiom
- `k8s/rag-api/deployment.yaml` — namespace `rag-enterprise`, image `rag-enterprise:latest`, resource request pattern

### Secondary (MEDIUM confidence — derived from codebase + asyncpg docs)

- asyncpg `execute()` returns `"DELETE N"` status string — confirmed via `asyncpg/cursor.py:319` in installed venv; version 0.30.0
- FastAPI `Header(alias=...)` behavior — standard FastAPI pattern; consistent with existing controller code

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; all reused from live codebase
- Architecture: HIGH — verified all integration points against production files
- Pitfalls: HIGH — confirmed via direct code inspection (register_vector, asyncpg status string, audit_db_enabled default)
- Test patterns: HIGH — conftest fixtures verified; existing test files confirm mock-at-consumer-path convention

**Research date:** 2026-05-16
**Valid until:** 2026-06-16 (stable stack; asyncpg version pinned in .venv)
