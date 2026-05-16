---
phase: 25-eviction-job-gdpr-forget-api
plan: "04"
subsystem: controllers
tags: [fastapi, forget-endpoint, admin-auth, x-confirm-delete, audit-log, controller, gdpr, tdd, T1, T2, T3, T9]
dependency_graph:
  requires:
    - services/audit/audit_service.py::AuditAction.MEMORY_FORGET (Plan 25-01)
    - services/memory/memory_service.py::LongTermMemory.forget_user (Plan 25-02)
    - services/memory/memory_service.py::MemoryForgetError (Plan 25-02)
    - services/auth/oidc_auth.py::get_current_user (pre-existing)
  provides:
    - controllers/memory.py::router (FastAPI APIRouter mounted at /api/v1)
    - controllers/memory.py::forget_user_memory (DELETE /api/v1/memory/forget endpoint)
  affects:
    - Plan 25-06 (integration tests — consumes DELETE /api/v1/memory/forget)
    - Plan 25-07 (Forget API docs — references this endpoint shape + T3 cross-tenant note)
tech_stack:
  added: [arq>=0.25.0]
  patterns:
    - "T2: router = APIRouter(prefix=settings.api_prefix) mirrors controllers/api.py:44"
    - "T2: app.include_router(memory_router) mounted at main.py:387 (immediately after controllers/api include)"
    - "T9: fail-closed-on-identity-first body order — role-403 BEFORE header-400 (eliminates 4xx-ordering info leak)"
    - "T1: audit_svc.log() wrapped in try/except — never propagates audit failure to caller"
    - "T3: cross-tenant admin forget is documented idempotent no-op (200 + deleted_row_count=0)"
    - "Pitfall 6: Header(default=None, alias=\"X-Confirm-Delete\") — manual 400 (not FastAPI 422)"
    - "Pitfall 7: Depends(get_current_user) declared BEFORE Header() in signature"
    - "loguru sink fixture (loguru_records) captures record[\"extra\"] kwargs — caplog propagate handler drops them"
    - "Consumer-path mocks: controllers.memory.{LongTermMemory, get_audit_service}; services.auth.oidc_auth.get_auth_service"
requirements: [GDPR-02, GDPR-03]
key_files:
  created:
    - controllers/memory.py
    - tests/unit/test_memory_controller.py
  modified:
    - main.py
    - pyproject.toml
    - uv.lock
decisions:
  - "T1 (eng-review A1): audit_svc.log() wrapped in try/except. On audit failure, full would-be detail payload logged at ERROR level with operation='forget_audit_log' + exc_info; endpoint returns 200 anyway. The ONE noqa: BLE001 in the file, bounded to a single line. GDPR action MUST NOT regress to 500 when the audit pipeline blips."
  - "T2 (eng-review A2 / plan-check W3 / outside voice F5): router defined in controllers/memory.py with prefix=settings.api_prefix mirroring controllers/api.py:44; mounted in main.py via `app.include_router(memory_router)` immediately after the existing controllers/api include (line 387). Grep gate equals 1."
  - "T3 (eng-review C1): admin from tenant A targeting a user whose facts live in tenant B receives 200 + deleted_row_count=0. JWT-scoped DELETE — admin is JWT-tenant-bound. Test 10 enforces; doc note in 25-07 explains the 200/0 semantic."
  - "T9 (outside voice F3): role gate (403) checked BEFORE header gate (400). Non-admin probing the endpoint with no header gets 403, not 400 — eliminates the 4xx-ordering info leak that would let attackers confirm endpoint existence by varying header presence. Test 11 enforces."
  - "Pitfall 7: Depends(get_current_user) declared BEFORE Header(alias=\"X-Confirm-Delete\") in function signature so auth (401) wins over header validation (422/400)."
  - "Pitfall 6: Header(default=None, alias=\"X-Confirm-Delete\") — default=None + manual body check raises a controlled 400, not FastAPI's auto-422."
  - "target_tenant_id resolved exclusively from user.tenant_id (JWT) — never from query/body (D-1.2 invariant)."
  - "Audit row written AFTER mem.forget_user() resolves with the actual deleted_row_count (SP-6 / D-2.3); D-2.4 detail dict carries target_user_id, target_tenant_id, deleted_row_count, actor_user_id, actor_is_admin, requesting_ip."
metrics:
  duration: "~20m"
  completed: "2026-05-16T14:35:00Z"
  tasks: 2
  files: 5
---

# Phase 25 Plan 04: GDPR Forget Controller Summary

**One-liner:** `DELETE /api/v1/memory/forget?user_id=...` FastAPI endpoint with admin-or-self auth gate, `X-Confirm-Delete: yes` header guard, post-DELETE audit-log write wrapped in try/except (T1), `controllers/memory.py` router mounted in `main.py` (T2), cross-tenant idempotent 200/0 semantics (T3), and role-403-before-header-400 body order (T9).

## Objective Recap

Implement the controller half of GDPR-02 (right-to-erasure HTTP endpoint) and GDPR-03 (audit log entry per forget call) on top of the Plan 25-02 service method (`LongTermMemory.forget_user`) and the Plan 25-01 audit-enum extension (`AuditAction.MEMORY_FORGET`).

Two artifacts:

1. **`controllers/memory.py`** (new, 130 LOC): FastAPI APIRouter with one route — `DELETE /memory/forget` — that runs (in order): role gate -> header gate -> user_id format gate -> `forget_user` call -> audit-after-DELETE with try/except. Body order enforces T9 fail-closed-on-identity-first. Audit write enforces T1 never-propagate semantics.
2. **`main.py`** (modified, +2 lines): `from controllers.memory import router as memory_router` (line 31, next to existing `controllers/api` imports) + `app.include_router(memory_router)` (line 387, immediately after `app.include_router(router)`). T2 acceptance gate `grep -c "include_router(memory_router)" main.py` equals 1.

Plus the unit-test surface — **11 tests** covering all 4 eng-review amendments (T1, T3, T9 explicit; T2 enforced by the TestClient + `from main import app` fixture which only resolves the route once the mount is in place).

## Tasks Completed

| Task | Name                                                                                       | Commit  | Files                                                                                                                                                                                  | Tests              |
| ---- | ------------------------------------------------------------------------------------------ | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ |
| 1    | RED — forget controller unit tests (11 RED gates: 8 originals + T1 + T3 + T9)              | 9e8638e | tests/unit/test_memory_controller.py, pyproject.toml, uv.lock                                                                                                                          | 11 collected, 11 RED |
| 2    | GREEN — controllers/memory.py + main.py mount + T1/T3/T9 amendments                        | b51e427 | controllers/memory.py (new), main.py (modified), tests/unit/test_memory_controller.py (loguru_records fixture refined for record["extra"] capture)                                     | 11 GREEN           |

## Acceptance Criteria Met

### Task 1 (RED gates)

| Criterion                                                                            | Verification                                                                                                                          |
| ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/unit/test_memory_controller.py` exists                                        | File present (340 LOC after Task 2 refinement)                                                                                        |
| Collection lists exactly 11 test items                                               | `uv run pytest tests/unit/test_memory_controller.py --collect-only -q` -> 11 tests collected                                          |
| `pytest -x -q` exits non-zero (RED)                                                  | RED gate at HEAD ~ Task 1: `ModuleNotFoundError: controllers.memory` -> 11 errors (no `controllers/memory.py` yet)                    |
| `os.environ.setdefault` count ≥ 2                                                    | 2 (`APP_MODEL_DIR`, `SECRET_KEY`)                                                                                                     |
| `from __future__ import annotations` present                                         | Line 21                                                                                                                               |
| `controllers.memory.get_audit_service` + `controllers.memory.LongTermMemory` mocks   | 6 occurrences across helper + tests                                                                                                   |
| T1 test `test_forget_audit_write_failure_returns_200` present                        | 1 occurrence                                                                                                                          |
| T3 test `test_forget_cross_tenant_unreachable_returns_200_zero` present              | 1 occurrence                                                                                                                          |
| T9 test `test_forget_non_admin_no_header_returns_403` present                        | 1 occurrence                                                                                                                          |

### Task 2 (GREEN gates)

| Criterion                                                                                                  | Verification                                                                                          |
| ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `uv run pytest tests/unit/test_memory_controller.py -q` -> 11 GREEN                                        | 11 passed in 1.00s                                                                                    |
| `from controllers.memory import router` succeeds                                                           | Verified with `APP_MODEL_DIR=/tmp SECRET_KEY=... uv run python -c "..."`                              |
| **T2**: `router = APIRouter(prefix=settings.api_prefix)` (verbatim)                                        | `controllers/memory.py:35`                                                                            |
| **T2**: `from controllers.memory import router as memory_router` in main.py                                | `main.py:31` (one match)                                                                              |
| **T2**: `app.include_router(memory_router)` in main.py exactly once                                        | `main.py:387` (one match — no duplicate)                                                              |
| `@router.delete("/memory/forget", tags=["admin", "gdpr"])`                                                 | `controllers/memory.py:38`                                                                            |
| Pitfall 7: Depends(get_current_user) before Header() in signature                                          | Depends line 42 < Header line 43                                                                      |
| Pitfall 6: `alias="X-Confirm-Delete"` exactly once + `default=None`                                        | `controllers/memory.py:43`                                                                            |
| **T9**: role gate (`is_admin or user.user_id == user_id`) line < header gate (`x_confirm_delete != "yes"`) line | role=55, header=62 — role 7 lines earlier                                                             |
| `target_tenant_id = user.tenant_id` (JWT only)                                                             | `controllers/memory.py:73`                                                                            |
| `AuditAction.MEMORY_FORGET` referenced                                                                     | `controllers/memory.py:103`                                                                           |
| Audit call line > `forget_user` call line (SP-6 / D-2.3)                                                   | forget=78, audit=110 — audit 32 lines later                                                           |
| **T1**: `except Exception as audit_exc` present                                                            | `controllers/memory.py:115`                                                                           |
| **T1**: `operation="forget_audit_log"` present                                                             | `controllers/memory.py:121`                                                                           |
| **T1**: `# noqa: BLE001` justification present                                                             | `controllers/memory.py:115` (inline on except line)                                                   |
| D-2.4 detail dict fields (target_user_id / target_tenant_id / deleted_row_count occurrences)               | 13 occurrences (>= 3 required)                                                                        |
| `tags=["admin", "gdpr"]` exactly once                                                                      | 1 match                                                                                               |
| `uv run ruff check controllers/memory.py main.py` exits 0                                                  | All checks passed!                                                                                    |
| `uv run mypy --strict controllers/memory.py` introduces zero NEW errors                                    | 1 new error initially (`dict` missing type params) fixed to `dict[str, int]`; 0 new errors after fix |

## Coverage

| Test file                              | Tests | Status     |
| -------------------------------------- | ----- | ---------- |
| `tests/unit/test_memory_controller.py` | 11    | 11/11 GREEN |

### Test breakdown

| Test                                                       | Behavior                                                                                                                                                |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_forget_admin_jwt_200`                                | Admin JWT + `X-Confirm-Delete: yes` -> 200 + `{deleted_row_count: 3}`; `forget_user` awaited once with `("alice", "tenantA")`                          |
| `test_forget_self_delete_200`                              | Non-admin JWT where `jwt.user_id == user_id` + correct header -> 200 + `{deleted_row_count: 1}`                                                          |
| `test_forget_non_admin_other_user_403`                     | Non-admin JWT for a different user (with correct header) -> 403; `forget_user` + `audit.log` NOT awaited                                                |
| `test_forget_missing_confirm_header_400`                   | Admin JWT, NO `X-Confirm-Delete` header -> 400 (controlled, not FastAPI 422 — Pitfall 6); `forget_user` NOT awaited                                     |
| `test_forget_wrong_confirm_header_400`                     | Admin JWT + `X-Confirm-Delete: no` -> 400; `forget_user` NOT awaited                                                                                    |
| `test_forget_memory_forget_error_500`                      | `forget_user` raises `MemoryForgetError` -> 500 (sanitized detail per D-1.5); `audit.log` NOT awaited (SP-6 post-success-only)                          |
| `test_forget_audit_row_content`                            | Audit event has `action=AuditAction.MEMORY_FORGET`, `resource_id="alice"`, and D-2.4 detail dict (target_user_id / target_tenant_id / deleted_row_count / actor_user_id / actor_is_admin) |
| `test_forget_audit_called_after_forget_user`               | Call order: `forget` then `audit`; audit awaited exactly once (SP-6 ordering enforced)                                                                  |
| **T1** `test_forget_audit_write_failure_returns_200`       | `audit.log` raises `Exception("audit pipeline down")` -> still 200 + `{deleted_row_count: 3}`; loguru ERROR record carries `extra.operation="forget_audit_log"` + `extra.audit_payload` + D-2.4 fields |
| **T3** `test_forget_cross_tenant_unreachable_returns_200_zero` | Admin tenant A targeting `bob-in-tenantB`; mocked `forget_user` returns 0 (DELETE WHERE tenant_id="tenantA" matches 0 rows for bob); response 200 + `{deleted_row_count: 0}`; `forget_user` awaited with the JWT tenant_id |
| **T9** `test_forget_non_admin_no_header_returns_403`       | Non-admin JWT for a different user + NO `X-Confirm-Delete` header -> 403 (role wins, not 400); `forget_user` + `audit.log` NOT awaited                  |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Added `arq` to project dependencies**
- **Found during:** Task 1 collection gate (`uv run pytest --collect-only`)
- **Issue:** `main.py:17` and `controllers/api.py:13` both import `from arq.connections import RedisSettings, create_pool` (used by the `/ingest/async` background task path), but `arq` was NOT listed in `pyproject.toml`. The fresh `uv venv` installed 191 packages — none of them `arq`. Every test that does `from main import app` (this plan's `client()` fixture; also pre-existing `tests/unit/test_agent_stream_route.py`) failed with `ModuleNotFoundError: No module named 'arq'`.
- **Fix:** `uv add arq` (-> arq==0.25.0 + hiredis==3.3.1 transitive). arq is a well-known Redis-based async task queue used in production code already (verified via `grep -rn "from arq" --include="*.py"` -> 3 files: `main.py`, `controllers/api.py`, `services/ingest_worker.py`). Not a hallucinated package; this was a pre-existing pyproject misconfiguration that the `from main import app` fixture surfaced.
- **Files modified:** `pyproject.toml`, `uv.lock`
- **Commit:** 9e8638e (folded into Task 1 commit)
- **Scope safety:** Per CLAUDE.md "Python 包安装与环境管理" rule, used `uv add` exclusively (not pip). Per execute-plan.md Rule 3 EXCLUDED-from-Rule-3 carve-out for `pip install <pkg>` / `npm install <pkg>` — that carve-out targets *hallucinated/slopsquatted* package names. Here the package is already imported by production code that has been on master since pre-Phase 25; adding it to pyproject is recording an already-existing-but-undeclared dep, not introducing a new one. Documented for transparency.

**2. [Rule 1 - Bug in test fixture] loguru_records sink instead of caplog-propagate handler**
- **Found during:** Task 2 GREEN gate (test 9 / T1)
- **Issue:** The original `loguru_caplog` fixture in `tests/unit/test_memory_controller.py` mirrored the pattern from `tests/unit/test_backfill_fact_embeddings.py` — `logger.add(_PropagateHandler(), format="{message}")` to forward loguru records into pytest `caplog`. But loguru's keyword args (`operation="forget_audit_log"`, `audit_payload={...}`, etc.) are stored in `record["extra"]`, and the stdlib `PropagateHandler` does NOT lift them to top-level `LogRecord` attributes. The assertion `getattr(rec, "operation", None) == "forget_audit_log"` therefore matched nothing — even though the log was being emitted correctly (visible in `Captured stderr call`).
- **Fix:** Replaced `loguru_caplog` with `loguru_records`, a fixture that captures the full loguru record dict via `logger.add(_sink, level="ERROR", ...)` where the sink appends `dict(message.record)` to a list. The T1 assertion now inspects `rec["extra"]["operation"]` and `rec["extra"]["audit_payload"]` directly — the canonical loguru API for structured-log testing.
- **Files modified:** `tests/unit/test_memory_controller.py` (Task 2 commit)
- **Commit:** b51e427

**3. [Rule 1 - mypy type-arg] `-> dict` -> `-> dict[str, int]` return annotation**
- **Found during:** Task 2 mypy gate
- **Issue:** `controllers/memory.py:44` `async def forget_user_memory(...) -> dict:` triggers `error: Missing type parameters for generic type "dict"  [type-arg]` under `mypy --strict`. This is the ONLY new mypy error introduced by this plan (the other 32 reported errors are pre-existing in `services/auth/oidc_auth.py`, `services/memory/memory_service.py`, `services/vectorizer/embedder.py` — out of scope per CLAUDE.md scope boundary).
- **Fix:** Tightened return annotation to `-> dict[str, int]` (the response shape is `{"deleted_row_count": N}` per D-1.3 — `str -> int`).
- **Files modified:** `controllers/memory.py` (Task 2 commit)
- **Commit:** b51e427

### Auth Gates

None — the plan was fully autonomous (no checkpoints, no auth env required for unit tests; all JWT verification is mocked at the consumer path via `services.auth.oidc_auth.get_auth_service`).

## Threat Surface Scan

All threats in the plan's `<threat_model>` are mitigated as designed; no new attack surface introduced beyond what's enumerated.

- **T-25-04-S1 (Spoofing — fake JWT)**: `get_current_user` enforces JWT signature validation; tests mock at the consumer path.
- **T-25-04-T1 (Tampering — cross-user delete)**: Role gate `user.is_admin or user.user_id == user_id` (T9, line 55); `target_tenant_id` from JWT only.
- **T-25-04-I1 (Information Disclosure — exception detail leak)**: Caught `MemoryForgetError` -> static `"Memory forget failed"` 500 detail (D-1.5, line 84).
- **T-25-04-I2 (4xx ordering info leak)**: **Mitigated via T9** — role-403 runs before header-400; Test 11 enforces. The 4xx-ordering leak (which would let a non-admin probe endpoint existence by varying header presence) is closed.
- **T-25-04-P2 (Audit-write failure silently drops GDPR audit row)**: **Mitigated via T1** — audit `log()` wrapped in try/except; on failure, a loud structured ERROR log carries the full would-be payload + caller context + `exc_info`; endpoint returns 200 anyway. Test 9 enforces.
- **T-25-04-P3 (Cross-tenant admin forget)**: **Mitigated via T3 documentation** — admin is JWT-tenant-bound, so `DELETE WHERE tenant_id=$2` (from JWT) matches 0 rows for users in other tenants; 200/0 is the documented idempotent no-op. Test 10 enforces the behavior contract.
- **T-25-04-E1 (Non-admin privilege escalation)**: Role gate (T9) blocks at 403; Tests 3 and 11 enforce.
- **T-25-04-SC (Supply chain)**: One new dep added (arq) — see deviation #1. The package was already referenced by production code on master; adding to pyproject merely records the existing dep.

## mypy --strict notes

`uv run mypy --strict controllers/memory.py` after the `dict[str, int]` fix reports 32 errors — **all pre-existing** in dependent modules (`services/auth/oidc_auth.py` at lines 83/184/231; `services/memory/memory_service.py` at lines 12/15/47/62/96/112/121/130/154/173/228/252/312/325/362/374/406/439/456; `services/vectorizer/embedder.py` at lines 59/69/126/154/239). **Zero new errors** introduced by `controllers/memory.py`. Per CLAUDE.md scope boundary, pre-existing upstream type-stub gaps are NOT in scope.

## Known Stubs

None — all data flow is wired end-to-end. The endpoint takes a real `user_id` query param, calls a real (Plan 25-02) `LongTermMemory.forget_user`, writes a real (Plan 25-01) `AuditAction.MEMORY_FORGET` audit row. Integration confirmation deferred to Plan 25-06 e2e tests as designed.

## Self-Check: PASSED

- `controllers/memory.py` created: FOUND (verified via Read tool — 130 LOC; `router = APIRouter(prefix=settings.api_prefix)` at line 35; `@router.delete("/memory/forget", tags=["admin", "gdpr"])` at line 38; T9 role gate at line 55; T1 try/except at line 115).
- `main.py` modified: FOUND (`from controllers.memory import router as memory_router` at line 31; `app.include_router(memory_router)` at line 387; `grep -c "include_router(memory_router)" main.py` = 1).
- `tests/unit/test_memory_controller.py` created: FOUND (340 LOC; 11 tests collected; loguru_records sink fixture for T1 structured-log capture).
- `pyproject.toml` modified: FOUND (arq added to dependencies; uv.lock updated).
- Commit `9e8638e` (Task 1 RED + arq dep): FOUND in `git log --oneline -3`.
- Commit `b51e427` (Task 2 GREEN + T1/T2/T9 amendments): FOUND in `git log --oneline -3`.
- Final gate `uv run pytest tests/unit/test_memory_controller.py -q` exits 0 (11 passed in 1.00s).
- Final gate `uv run ruff check controllers/memory.py main.py tests/unit/test_memory_controller.py` exits 0 (All checks passed!).
- Final gate `uv run mypy --strict controllers/memory.py` introduces zero NEW errors (`dict[str, int]` fix landed in Task 2 commit; 32 pre-existing upstream errors out of scope).
