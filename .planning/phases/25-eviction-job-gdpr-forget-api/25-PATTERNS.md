# Phase 25: Eviction job + GDPR forget API — Pattern Map

**Mapped:** 2026-05-16
**Files analyzed:** 11 (6 NEW, 5 MODIFIED)
**Analogs found:** 10 / 11 (1 no-analog: `X-Confirm-Delete` Header dep)

---

## File Classification

| New / Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/evict_long_term_facts.py` (NEW) | operational CLI | batch / chunked-DELETE / cursor | `scripts/backfill_fact_embeddings.py` (Plan 24-06) | **exact (2 documented swaps)** |
| `controllers/memory.py` (NEW) | controller / router | request-response (DELETE) | `controllers/api.py:400` (`@router.delete("/cache", tags=["admin"])`) | **exact (4 documented swaps)** |
| `services/memory/memory_service.py::MemoryForgetError` (NEW class) | typed exception | — | `services/memory/memory_service.py:21-27` (`MemoryFactWriteError`) | **exact (rename only)** |
| `services/memory/memory_service.py::LongTermMemory.forget_user` (NEW method) | service method | request-response (DELETE) | `services/memory/memory_service.py:339-376` (`save_fact`) | **exact (3 documented swaps)** |
| `services/audit/audit_service.py::AuditAction` (MODIFY enum) | enum extension | — | `services/audit/audit_service.py:25-37` (existing 12 values) | **exact (append-only)** |
| `config/settings.py` (MODIFY — new field) | config | config-load | `config/settings.py:302` (`extractor_enabled: bool = True`) | exact |
| `tests/unit/test_evict_long_term_facts.py` (NEW) | unit test | mock-at-consumer-path | `tests/unit/test_memory_save_fact.py` (fake-pool harness) | **exact** |
| `tests/unit/test_memory_forget.py` (NEW) | unit test | mock-at-consumer-path | `tests/unit/test_memory_save_fact.py` (fake-pool harness) | **exact** |
| `tests/unit/test_memory_controller.py` (NEW) | unit test | FastAPI TestClient + JWT mock | `tests/unit/test_agent_stream_route.py` (TestClient + monkeypatch) | role-match |
| `tests/integration/test_gdpr_forget_e2e.py` (NEW) | integration test | pgvector marker, real PG | `tests/integration/test_recall_tool_planner_pick.py` | **exact** |
| `docs/memory-eviction.md` (EXTEND) | docs | static | existing 49 LOC (Plan 24-06) + `k8s/rag-api/deployment.yaml` YAML shape | role-match |

---

## Shared Patterns

These rules apply across ALL Phase 25 files.

### SP-1: `from __future__ import annotations`

Every new `.py` file starts with this. Verified in all production files and test files.

```python
from __future__ import annotations
```

### SP-2: Lazy imports for circular-import resilience

Any import that crosses the `services.` ↔ `controllers.` or `services.memory` ↔ `services.vectorizer` boundary goes inside the function body with a comment.

**Source:** `services/memory/memory_service.py:349-351`

```python
# Lazy imports (circular-import resilience per repo convention).
import httpx
from services.vectorizer.embedder import get_embedder
```

### SP-3: Narrow-exception only — no bare `except` (ERR-01)

Every `except` clause names a specific exception type. `(asyncpg.PostgresError, asyncpg.InterfaceError)` is the correct asyncpg narrow-pair for CLI scripts; `asyncpg.PostgresError` alone is correct for single-txn service methods (D-1.5 + Pitfall 4).

### SP-4: Structured logging via loguru

All logs use keyword arguments:

```python
logger.error("memory service failure", operation="forget_user", exc_info=exc)
logger.info("eviction sweep complete", mode=mode, total_deleted=total_deleted)
```

**Source:** `services/memory/memory_service.py:375` + `scripts/backfill_fact_embeddings.py:168`

### SP-5: `int(status.split()[1])` for asyncpg DELETE row count (Pitfall 2)

`conn.execute()` returns a status string `"DELETE N"`. Never use `cursor.rowcount`. Always parse immediately after the `await`.

```python
status = await conn.execute("DELETE FROM ... WHERE ...", ...)
deleted_row_count = int(status.split()[1])  # "DELETE 5" → 5
```

### SP-6: Audit write AFTER the DELETE (D-2.3)

`audit_service.log(event)` is always called after `conn.execute()` returns (or after the last batch commit). If the DELETE fails, the exception propagates and no audit row is written. This mirrors the v1.0 Phase 2 post-fact pattern.

### SP-7: `get_audit_service()` singleton — never re-instantiate

```python
from services.audit.audit_service import get_audit_service
...
await get_audit_service().log(event)
```

**Source:** `services/audit/audit_service.py:116` + usage pattern in `controllers/api.py`

### SP-8: Mock at consumer path (v1.3 D-13/D-15)

Unit tests patch `controllers.memory.audit_service.log` (not `services.audit.audit_service.log`). Unit tests patch `services.memory.memory_service.LongTermMemory.forget_user` (not the pool directly) when testing the controller.

---

## Pattern Assignments

---

### Analog 1 — `scripts/evict_long_term_facts.py`

**Analog source:** `scripts/backfill_fact_embeddings.py` (Plan 24-06, 220 LOC)
**Match quality:** exact — same role, same data flow (chunked-commit, cursor, asyncio.run, pool reuse)

#### Before (backfill shape)

Key lines from `scripts/backfill_fact_embeddings.py`:

```python
# lines 22-30: module header + from __future__
from __future__ import annotations
import argparse, asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from loguru import logger
from services.memory.memory_service import LongTermMemory
```

```python
# lines 91-93: pool reuse (Pitfall 1 mitigation)
mem = LongTermMemory()
pool = await mem._get_pool()
```

```python
# lines 154-169: chunked txn + narrow-except (T4 + T5)
try:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE long_term_facts SET embedding = u.emb ...",
                ids, vectors,
            )
except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
    logger.error(f"txn UPDATE failed, rollback complete: {exc!r}")
    return 1
```

```python
# lines 182-215: argparse + asyncio.run shape
def main() -> None:
    setup_logger()
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--dry-run", action="store_true", ...)
    parser.add_argument("--batch-size", type=int, default=100, ...)
    parser.add_argument("--resume-from-id", type=str, default=None, ...)
    args = parser.parse_args()
    exit_code = asyncio.run(backfill(...))
    sys.exit(exit_code)
```

#### Swap list (backfill → eviction)

| Backfill | Evict | Reason |
|---|---|---|
| `--dry-run` flag | `--mode={audit,enforce}` + `--user-id UUID` | ROADMAP spec; "audit" replaces dry-run semantics |
| `--batch-size` default=100 | `--batch-size` default=1000 | EVICT-01 spec |
| `--resume-from-id` cursor | no resume cursor | Eviction is idempotent-from-start; cursor is "rows over cap" |
| `UPDATE ... FROM unnest(...)` | `DELETE FROM long_term_facts WHERE id IN (SELECT id ... LIMIT $N)` | Evict deletes; backfill updates |
| `embedder.embed_batch()` call | no embedder; only pool queries | Eviction reads `importance` + `created_at` columns |
| single `backfill()` async function | `main_async()` outer loop + `evict_bucket()` inner function | Bucket-per-sweep structure |
| no audit_service call | `audit_svc.log(AuditEvent(...))` per bucket (post-DELETE) | EVICT-02 / D-2.2 |
| no stdout JSON-lines | `print(json.dumps({...}), file=sys.stdout, flush=True)` in audit mode | D-3.1 |
| no sweep_run_id | `sweep_run_id = uuid.uuid4().hex` at top of `main_async` | D-2.4 correlation |

#### Anti-pattern callouts

- DO NOT call `asyncpg.create_pool()` directly — use `LongTermMemory()._get_pool()` (Pitfall 1: register_vector codec)
- DO NOT use `conn.execute()` return value as integer directly — parse `int(status.split()[1])` (Pitfall 2)
- DO NOT catch bare `Exception` — use `(asyncpg.PostgresError, asyncpg.InterfaceError)` in the batch loop (Pitfall 4 + ERR-01)
- DO NOT call DELETE per-row — `WHERE id IN (SELECT id ... LIMIT $batch_size)` chunked 1000/txn (EVICT-01)
- DO NOT add `--mode=enforce` precondition check — runbook only (D-3.2)
- DO NOT write audit row BEFORE the DELETE — post-fact only (D-2.3 / SP-6)
- DO NOT include short-term Redis or user_profile in eviction scope (D-1.2)

#### Verbatim skeleton

```python
#!/usr/bin/env python
"""scripts/evict_long_term_facts.py — Phase 25 / EVICT-01 + EVICT-02.

Caps long_term_facts growth per (user_id, tenant_id) bucket.
Deletes lowest-importance rows (tie-break: oldest created_at first), chunked
at batch_size rows/txn, idempotent. Supports --mode=audit|enforce.

Usage:
  uv run python scripts/evict_long_term_facts.py --mode=audit
  uv run python scripts/evict_long_term_facts.py --mode=enforce --batch-size 1000
  uv run python scripts/evict_long_term_facts.py --mode=enforce --user-id <uuid>
"""
from __future__ import annotations

import argparse
import asyncio
import json
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


async def evict_bucket(
    pool: asyncpg.Pool,
    user_id: str,
    tenant_id: str,
    cap: int,
    batch_size: int,
    mode: str,
    sweep_run_id: str,
    audit_svc,
) -> int:
    """Evict one (user_id, tenant_id) bucket down to cap. Returns rows deleted."""
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS n FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        user_id, tenant_id,
    )
    row_count = int(row["n"]) if row else 0
    over_cap_by = max(0, row_count - cap)

    if over_cap_by == 0:
        return 0  # idempotent — nothing to do

    if mode == "audit":
        print(json.dumps({
            "bucket": {"user_id": user_id, "tenant_id": tenant_id},
            "row_count": row_count,
            "cap": cap,
            "over_cap_by": over_cap_by,
            "would_delete_count": over_cap_by,
            "sweep_run_id": sweep_run_id,
        }), file=sys.stdout, flush=True)
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
                break  # idempotent — nothing left
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            logger.error(
                "eviction chunk DELETE failed",
                user_id=user_id, tenant_id=tenant_id,
                exc_info=exc, operation="evict_bucket_chunk",
            )
            raise

    # audit AFTER DELETE (D-2.3 / SP-6)
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


async def main_async(mode: str, batch_size: int, user_id: str | None) -> int:
    setup_logger()
    mem = LongTermMemory()                    # Pitfall 1: pool reuse = register_vector inherited
    pool = await mem._get_pool()
    audit_svc = get_audit_service()
    sweep_run_id = uuid.uuid4().hex           # D-2.4 correlation ID across buckets
    cap = settings.memory_facts_cap_per_user  # A5: new setting, default 500

    if user_id:
        buckets = await pool.fetch(
            """SELECT user_id, tenant_id, COUNT(*) AS n
               FROM long_term_facts WHERE user_id=$1
               GROUP BY user_id, tenant_id HAVING COUNT(*) > $2""",
            user_id, cap,
        )
    else:
        buckets = await pool.fetch(
            """SELECT user_id, tenant_id, COUNT(*) AS n
               FROM long_term_facts
               GROUP BY user_id, tenant_id HAVING COUNT(*) > $1""",
            cap,
        )

    if not buckets:
        logger.info("eviction: no buckets over cap", cap=cap, mode=mode)
        return 0

    total_deleted = 0
    for b in buckets:
        try:
            deleted = await evict_bucket(
                pool=pool, user_id=b["user_id"], tenant_id=b["tenant_id"],
                cap=cap, batch_size=batch_size, mode=mode,
                sweep_run_id=sweep_run_id, audit_svc=audit_svc,
            )
            total_deleted += deleted
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            logger.error("eviction bucket failed", exc_info=exc)
            # continue — CronJob restartPolicy: OnFailure handles retry

    await audit_svc.flush()
    logger.info("eviction sweep complete", mode=mode, total_deleted=total_deleted)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evict long_term_facts rows over per-user cap.")
    parser.add_argument("--mode", choices=["audit", "enforce"], default="audit")
    parser.add_argument("--batch-size", type=int, default=1000, metavar="N")
    parser.add_argument("--user-id", type=str, default=None, metavar="UUID")
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args.mode, args.batch_size, args.user_id)))


if __name__ == "__main__":
    main()
```

---

### Analog 2 — `controllers/memory.py`

**Analog source:** `controllers/api.py:400-403` (`@router.delete("/cache", tags=["admin"])`)
**Match quality:** exact as starting point; 4 documented swaps add auth gate, Header dep, and error handling not present in the cache endpoint

#### Before (cache-clear template — `controllers/api.py:400-403`)

```python
@router.delete("/cache", tags=["admin"])
async def clear_cache() -> APIResponse:
    deleted = await cache_invalidate("rag:*")
    return APIResponse(success=True, data={"deleted_keys": deleted})
```

Note: this endpoint has no auth gate — the forget endpoint MUST add `Depends(get_current_user)`.

#### Secondary analog — auth gate shape (`controllers/api.py:21` + `services/auth/oidc_auth.py:251-270`)

```python
# controllers/api.py:21
from services.auth.oidc_auth import AuthenticatedUser, get_current_user

# services/auth/oidc_auth.py:251-270
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization required")
    user = await get_auth_service().verify_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user
```

#### `AuthenticatedUser` relevant fields (`services/auth/oidc_auth.py:28-43`)

```python
@dataclass
class AuthenticatedUser:
    user_id:   str
    tenant_id: str
    roles:     list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles
```

#### Swap list (cache-clear → forget endpoint)

| Cache template | Forget endpoint | Reason |
|---|---|---|
| no auth dep | `user: AuthenticatedUser = Depends(get_current_user)` as first dep | D-1.1 auth gate |
| no confirmation header | `x_confirm_delete: str | None = Header(default=None, alias="X-Confirm-Delete")` | D-1.4; Pitfall 6 |
| no auth check logic | `if not (user.is_admin or user.user_id == user_id): raise HTTPException(403)` | D-1.1 |
| no error handling | `try/except MemoryForgetError → 500` | D-1.5 |
| `tags=["admin"]` | `tags=["admin", "gdpr"]` | OpenAPI grouping (Claude's Discretion) |
| no audit_service call | `await get_audit_service().log(AuditEvent(...))` after DELETE | GDPR-03 / D-2.3 |
| `return APIResponse(...)` | `return {"deleted_row_count": N}` | D-1.3 response shape |
| `clear_cache()` fn name | `forget_user_memory(...)` | clarity |

#### Anti-pattern callouts

- DO NOT declare `Header(alias="X-Confirm-Delete")` before `Depends(get_current_user)` — auth dep must come first (Pitfall 7)
- DO NOT use `Header(...)` with positional-only (no `alias`) — FastAPI lowercases and underscores the param name; `alias="X-Confirm-Delete"` is required (Pitfall 6)
- DO NOT use `Header(default=...)` with `...` (required) — use `default=None` and manually raise 400 so the response is 400 not 422 (Pitfall 6)
- DO NOT write audit row BEFORE `mem.forget_user()` resolves — post-fact only (D-2.3)
- DO NOT use `target_tenant_id` from a query param — resolve from `user.tenant_id` (JWT) only (D-1.2 invariant)
- DO NOT expose raw exception detail in 500 response — use sanitized string (D-1.5)

#### Verbatim skeleton

```python
# controllers/memory.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger

from services.audit.audit_service import AuditAction, AuditEvent, AuditResult, get_audit_service
from services.auth.oidc_auth import AuthenticatedUser, get_current_user
from services.memory.memory_service import LongTermMemory, MemoryForgetError

router = APIRouter()


@router.delete("/memory/forget", tags=["admin", "gdpr"])
async def forget_user_memory(
    user_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),          # auth FIRST (Pitfall 7)
    x_confirm_delete: str | None = Header(default=None, alias="X-Confirm-Delete"),  # Pitfall 6
) -> dict:
    """Delete all long_term_facts for a given user_id.

    Auth: admin claim OR self-delete (jwt.user_id == target user_id).
    Confirmation header X-Confirm-Delete: yes required (D-1.4).
    Scope: long_term_facts ONLY (D-1.2).
    Returns {deleted_row_count: N} — idempotent; 200 even if N==0 (D-1.3).
    """
    # 1. Confirmation header gate (400) — D-1.4
    if x_confirm_delete != "yes":
        raise HTTPException(status_code=400, detail="X-Confirm-Delete: yes header required")

    # 2. Auth gate (403) — D-1.1
    if not (user.is_admin or user.user_id == user_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    # 3. user_id format validation (404) — D-1.3
    if not user_id:
        raise HTTPException(status_code=404, detail="user_id required")

    target_tenant_id = user.tenant_id  # tenant from JWT only — never a query param

    # 4. Execute forget (lazy import — circular-import resilience)
    try:
        mem = LongTermMemory()
        deleted_row_count = await mem.forget_user(user_id, target_tenant_id)
    except MemoryForgetError as exc:
        logger.error("forget_user failed", user_id=user_id, exc_info=exc)
        raise HTTPException(status_code=500, detail="Memory forget failed")

    # 5. Audit AFTER DELETE (D-2.3 / SP-6)
    ip_address = request.client.host if request.client else ""
    await get_audit_service().log(AuditEvent(
        user_id=user.user_id,
        tenant_id=target_tenant_id,
        action=AuditAction.MEMORY_FORGET,
        resource_id=user_id,
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

### Analog 3 — `services/memory/memory_service.py::MemoryForgetError`

**Analog source:** `services/memory/memory_service.py:21-27` (`MemoryFactWriteError`)
**Match quality:** exact (rename only)

#### Before (`MemoryFactWriteError` — lines 21-27)

```python
class MemoryFactWriteError(Exception):
    """Typed error for save_fact embedding or persistence failure.

    Wraps either ``asyncpg.PostgresError`` OR an embedding-adapter exception
    so the ``dispatch_extraction`` wrapper can surface it via ``log_task_error``
    without conflating the two failure modes at the call site.
    """
```

#### After (`MemoryForgetError` — place immediately after `MemoryFactWriteError`)

```python
class MemoryForgetError(Exception):
    """Typed error for forget_user DB failure.

    Wraps ``asyncpg.PostgresError`` so the controller can surface a sanitized
    500 without exposing DB internals. Mirrors ``MemoryFactWriteError``.
    """
```

#### Swap list

| `MemoryFactWriteError` | `MemoryForgetError` | Reason |
|---|---|---|
| "embedding or persistence failure" | "DB failure" | forget has no embed step |
| two failure modes (embed + PG) | single failure mode (asyncpg.PostgresError) | D-1.5 |
| placed at `memory_service.py:21` | place immediately after `MemoryFactWriteError` | proximity to related exception |

---

### Analog 4 — `services/memory/memory_service.py::LongTermMemory.forget_user`

**Analog source:** `services/memory/memory_service.py:339-376` (`save_fact`)
**Match quality:** exact — same pool-acquire pattern, same narrow-except shape, same raise-from chain

#### Before (`save_fact` — lines 339-376)

```python
async def save_fact(
    self, user_id: str, tenant_id: str,
    fact: str, source_doc: str = "", importance: float = 0.5,
) -> None:
    import httpx
    from services.vectorizer.embedder import get_embedder

    try:
        embedding: list[float] = await get_embedder().embed_one(fact)
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        logger.error("memory service failure", operation="save_fact_embed", exc_info=exc)
        raise MemoryFactWriteError("embedding failed") from exc

    try:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO long_term_facts ...
                   VALUES ($1,$2,$3,$4,$5,$6::vector)""",
                user_id, tenant_id, fact, source_doc, importance, embedding,
            )
    except asyncpg.PostgresError as exc:
        logger.error("memory service failure", operation="save_fact", exc_info=exc)
        raise MemoryFactWriteError("persistence failed") from exc
```

#### After (`forget_user` — verbatim skeleton)

```python
async def forget_user(self, user_id: str, tenant_id: str) -> int:
    """Delete all long_term_facts rows for a (user_id, tenant_id) pair.

    Returns the number of rows deleted (0 = idempotent no-op if nothing to delete).
    Scope: long_term_facts ONLY (D-1.2). Short-term Redis and user_profile NOT cleared.

    Raises:
        MemoryForgetError: on asyncpg.PostgresError (wraps DB error; caller → 500).
    """
    try:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                "DELETE FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
                user_id, tenant_id,
            )
        return int(status.split()[1])  # "DELETE N" → N  (Pitfall 2 / SP-5)
    except asyncpg.PostgresError as exc:
        logger.error("memory service failure", operation="forget_user", exc_info=exc)
        raise MemoryForgetError("forget failed") from exc
```

#### Swap list

| `save_fact` | `forget_user` | Reason |
|---|---|---|
| embed step (Step 1 try block) | removed | forget has no embed step |
| `INSERT INTO long_term_facts` | `DELETE FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2` | opposite operation |
| `return None` | `return int(status.split()[1])` | GDPR-01 contract returns count |
| `raise MemoryFactWriteError` | `raise MemoryForgetError` | typed exception per D-1.5 |
| two try blocks | one try block | no separate embed/persist failure modes |

#### Anti-pattern callouts

- DO NOT catch bare `Exception` — narrow to `asyncpg.PostgresError` only (ERR-01 + D-1.5; Pitfall 4 notes InterfaceError is handled at CLI level, not single-txn service method)
- DO NOT use `RETURNING id` for row count — `int(status.split()[1])` is the asyncpg idiom (SP-5)
- DO NOT include short-term Redis or user_profile in the DELETE scope (D-1.2)

---

### Analog 5 — `services/audit/audit_service.py::AuditAction` enum extension

**Analog source:** `services/audit/audit_service.py:25-37` (existing 12-value enum)
**Match quality:** exact (append-only)

#### Before (current — `audit_service.py:25-37`)

```python
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
```

#### After (verbatim skeleton — append two values at END)

```python
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

#### Anti-pattern callouts

- DO NOT insert new values between existing members — append ONLY at end (Pitfall 5: preserves string values in DB)
- DO NOT use mixed case — `MEMORY_FORGET = "MEMORY_FORGET"` exactly (Pitfall 5: value must match existing uppercase pattern)
- DO NOT rename existing values — `TOKEN_VERIFIED` stays as-is; existing audit rows reference these strings

---

### Analog 6 — `config/settings.py` new field

**Analog source:** `config/settings.py:302` (`extractor_enabled: bool = True`)
**Match quality:** exact (same pattern: bool/int field with env-var-friendly name + comment block)

#### Analog pattern (`config/settings.py:296-304`)

```python
# Extractor sub-agent (Phase 23, MEM-03) ──────────────────────────────────
# extractor_enabled gates dispatch_extraction at the pipeline boundary
extractor_enabled:  bool                                = True
```

#### New field to add (place in `## 记忆` or audit section near `audit_db_enabled`)

```python
# Phase 25 / EVICT-01 — per-user long_term_facts row cap ─────────────────
# Consumed by scripts/evict_long_term_facts.py and (v1.7+) save_fact.
# Override via env MEMORY_FACTS_CAP_PER_USER=<int>.
memory_facts_cap_per_user: int = 500
```

---

### Analog 7 — `tests/unit/test_evict_long_term_facts.py` + `test_memory_forget.py`

**Analog source:** `tests/unit/test_memory_save_fact.py` (Phase 23, fake-pool harness)
**Match quality:** exact — same `_AcquireCtx` / `_make_fake_pool` / `_TxnCtx` helpers

#### Fake-pool harness (copy verbatim from `test_memory_save_fact.py:50-80`)

```python
class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool(execute_mock: AsyncMock) -> tuple[MagicMock, MagicMock]:
    """Return (pool, conn) where pool.acquire() yields a conn with the given execute mock."""
    conn = MagicMock(execute=execute_mock)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool, conn


def _make_long(pool: MagicMock) -> LongTermMemory:
    """Construct LongTermMemory with pool pre-injected (bypass _get_pool)."""
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool

    async def _get_pool():
        return pool

    lt._get_pool = _get_pool
    return lt
```

#### `test_memory_forget.py` module header pattern

```python
"""tests/unit/test_memory_forget.py — Phase 25 / GDPR-01.

Covers LongTermMemory.forget_user:
  Test 1: happy path — execute awaited with correct SQL args; return int(N).
  Test 2: idempotent — execute returns "DELETE 0"; return 0.
  Test 3: asyncpg.PostgresError → MemoryForgetError raised with __cause__ chained.
  Test 4: signature gate — user_id, tenant_id params; return type int.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from services.memory.memory_service import LongTermMemory, MemoryForgetError
```

#### `test_evict_long_term_facts.py` additional helpers needed

For `evict_bucket` tests, the pool needs `fetchrow` (COUNT query) + `execute` (DELETE) mocked. Extend `_make_fake_pool`:

```python
def _make_fake_pool_with_fetchrow(
    fetchrow_result: dict,
    execute_result: str = "DELETE 0",
) -> MagicMock:
    """Pool with both fetchrow (for COUNT) and execute (for DELETE) mocked."""
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=execute_result)

    pool = MagicMock()
    pool.fetchrow = AsyncMock(return_value=fetchrow_result)
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool
```

#### Swap list

| `test_memory_save_fact.py` | `test_memory_forget.py` | Reason |
|---|---|---|
| `execute_mock` returns None (INSERT) | `execute_mock` returns `"DELETE 3"` string | asyncpg DELETE returns status tag |
| tests `MemoryFactWriteError` | tests `MemoryForgetError` | different exception type |
| embedder mock needed | no embedder mock | forget has no embed step |
| two try blocks | one try block | see Analog 4 |

---

### Analog 8 — `tests/unit/test_memory_controller.py`

**Analog source:** `tests/unit/test_agent_stream_route.py` (TestClient + monkeypatch pattern)
**Match quality:** role-match (first controller test for DELETE endpoint with auth in unit tests)

#### TestClient setup pattern (`test_agent_stream_route.py:106-108`)

```python
@pytest.fixture
def client() -> TestClient:
    from main import app
    return TestClient(app)
```

**Note:** `controllers/memory.py` router must be mounted in `main.py` / `controllers/__init__.py` before this fixture works. The test file must verify the mount point is wired.

#### JWT mock pattern (`tests/unit/test_oidc_auth_dependency.py:10-25`)

```python
fake_user = AuthenticatedUser(user_id="u1", tenant_id="t1", roles=["admin"])
mock_svc = MagicMock()
mock_svc.verify_token = AsyncMock(return_value=fake_user)
monkeypatch.setattr("services.auth.oidc_auth.get_auth_service", lambda: mock_svc)
```

#### Controller test module header

```python
"""tests/unit/test_memory_controller.py — Phase 25 / GDPR-02 + GDPR-03.

Covers DELETE /api/v1/memory/forget endpoint:
  Test 1: admin JWT + X-Confirm-Delete: yes → 200 + {deleted_row_count: N}
  Test 2: non-admin self-delete (jwt.user_id == user_id) → 200
  Test 3: non-admin other user → 403
  Test 4: missing X-Confirm-Delete header → 400
  Test 5: X-Confirm-Delete: no → 400
  Test 6: MemoryForgetError from forget_user → 500
  Test 7: audit_service.log called AFTER forget_user; call_args match D-2.4 detail dict

Mock strategy (v1.3 D-13/D-15):
  - `controllers.memory.LongTermMemory` (or its forget_user method) — consumer path
  - `controllers.memory.get_audit_service` — consumer path
  - `services.auth.oidc_auth.get_auth_service` — consumer path for JWT decode
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from services.auth.oidc_auth import AuthenticatedUser
```

#### Swap list vs `test_agent_stream_route.py`

| `test_agent_stream_route.py` | `test_memory_controller.py` | Reason |
|---|---|---|
| POST `/agent/v1/run/stream` | DELETE `/api/v1/memory/forget?user_id=alice` | different method + route |
| mock `get_agent_pipeline` | mock `LongTermMemory.forget_user` + `get_audit_service` | different service under test |
| no auth gate (stream route) | auth gate via `get_auth_service` mock | D-1.1 |
| no confirmation header | `headers={"X-Confirm-Delete": "yes"}` in happy-path calls | D-1.4 |
| SSE event parsing | simple JSON response `{"deleted_row_count": N}` | D-1.3 |

---

### Analog 9 — `tests/integration/test_gdpr_forget_e2e.py`

**Analog source:** `tests/integration/test_recall_tool_planner_pick.py` (integration marker block)
**Match quality:** exact (same marker block structure, same conftest fixtures)

#### Integration marker block (copy verbatim, adjust reason string)

```python
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.skipif(
        not PG_AVAILABLE,
        reason="PostgreSQL + pgvector not available — skipping GDPR forget e2e test",
    ),
]

_USER_ID = "test-gdpr25-u"
_TENANT_ID = "test-gdpr25-t"
```

#### Conftest fixtures used

| Fixture | Source | Purpose |
|---|---|---|
| `pgvector_pool` | `tests/conftest.py:85-93` | session-scoped asyncpg pool with pgvector codec |
| `clean_long_term_facts` | `tests/conftest.py:166-177` | truncates `long_term_facts` before each test |

For forget e2e: also mock `get_auth_service` at module scope to return a controllable JWT without a real OIDC server (same pattern as `test_oidc_auth_dependency.py`).

---

### Analog 10 — `docs/memory-eviction.md` extension

**Analog source:** existing `docs/memory-eviction.md` (49 LOC from Plan 24-06) + `k8s/rag-api/deployment.yaml` YAML shape
**Match quality:** role-match (extend in place; YAML shape from deployment.yaml lines 1-40)

#### k8s CronJob YAML shape (from `k8s/rag-api/deployment.yaml:1-10`)

```yaml
apiVersion: apps/v1    # → batch/v1
kind: Deployment       # → CronJob
metadata:
  name: rag-api        # → ltf-eviction
  namespace: rag-enterprise  # keep
```

Namespace `rag-enterprise` and image `rag-enterprise:latest` are confirmed in `k8s/rag-api/deployment.yaml:5,33`.

#### Sections to ADD to `docs/memory-eviction.md` (per D-4.2)

```
## Eviction — Schedule & Cap
## Audit Mode Workflow
## Enforce Mode
## CronJob YAML
## Forget API
```

Keep existing sections verbatim: `## Cost Formula`, `## Backfill — Run Once`, `## Failure Modes`, `## Recurring Backfill`.

---

## No Analog Found

### `X-Confirm-Delete` FastAPI Header dependency

**Why no analog:** No existing controller in the codebase uses a custom `Header()` dependency with an `alias`. The `/cache` admin endpoint (`controllers/api.py:400`) has no confirmation guard at all.

**Canonical pattern from FastAPI docs + RESEARCH §Pitfall 6:**

```python
from fastapi import Header

# CORRECT — use alias + default=None + manual 400 check
async def forget_user_memory(
    ...
    x_confirm_delete: str | None = Header(default=None, alias="X-Confirm-Delete"),
) -> ...:
    if x_confirm_delete != "yes":
        raise HTTPException(status_code=400, detail="X-Confirm-Delete: yes header required")
```

**Why `default=None` not `...`:** `Header(default=...)` (required) causes FastAPI to auto-raise 422 (Unprocessable Entity) when the header is absent, bypassing the 400 contract in D-1.3. Use `default=None` and raise 400 manually.

**Why `alias="X-Confirm-Delete"`:** FastAPI's `Header` dependency converts underscores to hyphens in the `alias` parameter. HTTP/2 lowercases headers to `x-confirm-delete`; FastAPI matches case-insensitively. Without `alias`, FastAPI would look for `confirm-delete` (stripping the `X-` prefix behavior). With `alias="X-Confirm-Delete"`, it matches `x-confirm-delete` as sent by clients.

**OpenAPI documentation:** FastAPI auto-generates the header parameter in the OpenAPI spec when using `Header(alias=...)` — no manual schema annotation needed.

**Dependency order (Pitfall 7):** Declare `Depends(get_current_user)` BEFORE `Header(alias="X-Confirm-Delete")` in the function signature. FastAPI resolves deps in declaration order; auth should fail fast (401) before header validation.

---

## Mock-at-Consumer-Path Discipline (v1.3 D-13/D-15)

| Module under test | What to mock | Mock path |
|---|---|---|
| `controllers/memory.py` | `audit_service.log` | `controllers.memory.get_audit_service` (returns mock with `.log = AsyncMock()`) |
| `controllers/memory.py` | `LongTermMemory.forget_user` | `controllers.memory.LongTermMemory` or patch instance `.forget_user` method |
| `controllers/memory.py` | JWT decode | `services.auth.oidc_auth.get_auth_service` |
| `scripts/evict_long_term_facts.py` | audit_service | `scripts.evict_long_term_facts.get_audit_service` |
| `scripts/evict_long_term_facts.py` | LongTermMemory pool | patch `LongTermMemory._get_pool` to return fake pool |
| `services/memory/memory_service.py::forget_user` | asyncpg pool | inject fake pool via `_make_long(pool)` (copy from `test_memory_save_fact.py:71-80`) |

**Critical:** Do NOT mock at the source path (`services.audit.audit_service.log`) when testing the controller — the controller lazy-imports `get_audit_service` inside the request body, so the consumer-path patch (`controllers.memory.get_audit_service`) is the correct injection point.

---

## Test Harness Reuse Map

| New test file | Fixtures from conftest | Helpers to copy | From |
|---|---|---|---|
| `test_evict_long_term_facts.py` | none (unit; fake pool only) | `_AcquireCtx`, `_make_fake_pool` extended with `fetchrow` | `test_memory_save_fact.py:50-68` |
| `test_memory_forget.py` | none (unit; fake pool only) | `_AcquireCtx`, `_make_fake_pool`, `_make_long` | `test_memory_save_fact.py:50-80` |
| `test_memory_controller.py` | none (unit; TestClient) | `client()` fixture pattern | `test_agent_stream_route.py:105-108` |
| `test_gdpr_forget_e2e.py` | `pgvector_pool`, `clean_long_term_facts` | `pytestmark` block, `_USER_ID`/`_TENANT_ID` constants | `test_recall_tool_planner_pick.py:1-35` |

**Key conftest fixtures:**
- `pgvector_pool` — `tests/conftest.py:85` — session-scoped pool with register_vector
- `clean_long_term_facts` — `tests/conftest.py:166` — TRUNCATE before each integration test
- `PG_AVAILABLE` — `tests/conftest.py:33` — used in `pytestmark` `skipif`

**Integration test `audit_db_enabled` patch:**

```python
# In test setup for integration tests that assert DB audit rows:
monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", True)
await audit_service.flush()  # force flush before SELECT assertion
```

Source pattern: 25-RESEARCH §Pitfall 3.

---

## Metadata

**Analog search scope:** `scripts/`, `controllers/`, `services/memory/`, `services/audit/`, `services/auth/`, `tests/unit/`, `tests/integration/`, `config/`, `k8s/`
**Files scanned:** 17 source files read
**Pattern extraction date:** 2026-05-16
