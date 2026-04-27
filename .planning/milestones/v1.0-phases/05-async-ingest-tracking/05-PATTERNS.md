# Phase 5: Async Ingest Tracking — Pattern Map

**Mapped:** 2026-04-27
**Files analyzed:** 7 new/modified files
**Analogs found:** 6 / 7

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `requirements.txt` | config | — | `requirements.txt` (existing) | exact |
| `config/settings.py` | config | — | `config/settings.py` lines 276-280 (Redis block) | exact |
| `services/ingest_worker.py` | service | event-driven | `services/auth/oidc_auth.py` (singleton service pattern) | role-match |
| `controllers/api.py` (modify) | controller | request-response | `controllers/api.py` lines 103-120 (ingest_async stub) | exact |
| `services/auth/oidc_auth.py` (modify) | middleware | request-response | `services/auth/oidc_auth.py` lines 83-95 (verify_token) | exact |
| `tests/unit/test_ingest_worker.py` | test | — | `tests/unit/test_tasks.py` | exact |
| `tests/unit/test_ingest_status.py` | test | — | `tests/unit/test_tasks.py` | role-match |

---

## Pattern Assignments

### `requirements.txt` (config)

**Analog:** `requirements.txt` (existing file — append two lines)

**Pattern:** Two lines appended at the end of the existing dependency block:
```
arq==0.28.0
fakeredis==2.35.1
```

---

### `config/settings.py` (config — add two fields)

**Analog:** `config/settings.py` lines 275-280

**Existing Redis block to extend** (lines 275-280):
```python
    # ══════════════════════════════════════════════════════════════════════════
    # 缓存（Redis）
    # ══════════════════════════════════════════════════════════════════════════
    redis_url:      str  = "redis://localhost:6379/0"
    cache_ttl_sec:  int  = 3600
    cache_enabled:  bool = True
```

**New fields to add immediately after line 280:**
```python
    arq_keep_result_sec: int  = 86400   # ASYNC-02: 24h TTL for job results
    arq_job_timeout:     int  = 300     # max seconds per worker job
```

**Pattern rules:**
- Field name: `snake_case`, type-annotated, default value on same line
- Comment: inline `#` with requirement ID if traceability applies
- Group under the existing Redis section — no new section header needed

---

### `services/ingest_worker.py` (service, event-driven)

**Analog:** `services/auth/oidc_auth.py` — singleton factory + service class pattern

**Imports pattern** (copy from oidc_auth.py lines 1-22, adapt):
```python
from __future__ import annotations

from loguru import logger
from arq.connections import RedisSettings
from config.settings import settings
```

**Singleton factory pattern** (oidc_auth.py lines 235-242):
```python
_auth_service: OIDCAuthService | None = None

def get_auth_service() -> OIDCAuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = OIDCAuthService()
    return _auth_service
```
Apply this pattern for `get_ingest_pipeline()` import inside the task body (already in api.py line 87).

**ARQ task function pattern** (new — no codebase analog; follow RESEARCH.md Pattern 1):
```python
async def ingest_task(ctx: dict, req_data: dict) -> dict:
    """ARQ worker task — wraps IngestionPipeline.run().

    ctx: injected by ARQ (job metadata); not used directly here.
    req_data: IngestionRequest.model_dump(mode='json') — must be JSON-serializable.
    Returns dict; ARQ stores this in Redis with TTL=keep_result.
    Raises any exception to mark the job as failed; ARQ serializes the exception.
    """
    from services.pipeline import get_ingest_pipeline
    from utils.models import IngestionRequest
    pipeline = get_ingest_pipeline()
    req = IngestionRequest(**req_data)
    result = await pipeline.run(req)
    return {"doc_id": result.doc_id, "success": result.success, "error": result.error}
```

**WorkerSettings pattern** (new — follow RESEARCH.md Pattern 2):
```python
class WorkerSettings:
    functions = [ingest_task]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    keep_result = settings.arq_keep_result_sec   # 86400 — ASYNC-02
    keep_result_forever = False
    job_timeout = settings.arq_job_timeout        # 300s
    max_jobs = 10
```

**Error handling:** Do NOT catch exceptions inside `ingest_task`. ARQ catches all exceptions automatically and serializes them. Adding a bare `except` here violates ERR-01 and breaks ARQ's failure tracking.

**Logging pattern** (copy from api.py lines 98-100):
```python
logger.error(f"[Worker:ingest] doc_id={req_data.get('doc_id')} error={exc}")
```
Only log if you need additional context before re-raising a specific exception type.

---

### `controllers/api.py` (controller, request-response — two modifications)

**Analog:** `controllers/api.py` — modify in-place; full file already read.

#### Modification 1: Rewrite `POST /ingest/async` (lines 103-120)

**Existing pattern to replace** (lines 103-120):
```python
@router.post("/ingest/async", response_model=APIResponse, tags=["ingestion"])
@_limiter.limit(f"{settings.rate_limit_ingest_rpm}/minute")
async def ingest_async(request: Request, req: IngestionRequest, bg: BackgroundTasks) -> APIResponse:
    trace_id = str(uuid.uuid4())[:8]
    async def _bg_ingest() -> None:
        ...
    bg.add_task(_bg_ingest)
    return APIResponse(success=True, data={"trace_id": trace_id, "status": "queued"}, trace_id=trace_id)
```

**New pattern** (RESEARCH.md Pattern 3 + codebase conventions):
```python
@router.post("/ingest/async", response_model=APIResponse, status_code=202, tags=["ingestion"])
@_limiter.limit(f"{settings.rate_limit_ingest_rpm}/minute")
async def ingest_async(
    request: Request,
    req: IngestionRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> APIResponse:
    """异步摄取（大文件）：立即返回 202 + task_id，ARQ 后台处理。"""
    try:
        arq_redis = request.app.state.arq_redis
        job = await arq_redis.enqueue_job("ingest_task", req.model_dump(mode="json"))
        task_id = job.job_id if job else str(uuid.uuid4())
        logger.info(f"[API:ingest_async] task_id={task_id} doc_id={req.doc_id}")
        return APIResponse(
            success=True,
            data={"task_id": task_id, "status": "queued"},
            trace_id=task_id,
        )
    except redis.RedisError as exc:
        logger.error(f"[API:ingest_async] redis error={exc}")
        raise HTTPException(status_code=503, detail="任务队列暂时不可用，请稍后重试")
```

**Key changes from existing pattern:**
- Remove `BackgroundTasks` param — replaced by `arq_redis` from `app.state`
- Add `status_code=202` to decorator
- Add `Depends(get_current_user)` — new auth dependency
- Use `req.model_dump(mode="json")` not `req` directly (ARQ serialization)
- Error handling: narrow to `redis.RedisError` (ERR-01 compliant)

#### Modification 2: Add `GET /ingest/status/{task_id}` (new route)

**Analog route shape** (api.py lines 248-255 — `get_version` pattern with 404):
```python
@router.get("/docs/{doc_id}/versions/{version}", tags=["versioning"])
async def get_version(doc_id: str, version: int) -> APIResponse:
    v = await get_version_service().get_version(doc_id, version)
    if not v:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    return APIResponse(success=True, data=v.model_dump())
```

**New route** (RESEARCH.md Pattern 4 + codebase conventions):
```python
@router.get("/ingest/status/{task_id}", response_model=APIResponse, tags=["ingestion"])
async def ingest_status(
    task_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> APIResponse:
    """轮询异步摄取任务状态（ARQ job status via Redis）。"""
    import re
    if not re.fullmatch(r"[0-9a-f\-]{32,36}", task_id):
        raise HTTPException(status_code=400, detail="Invalid task_id format")
    try:
        from arq.jobs import Job, JobStatus
        arq_redis = request.app.state.arq_redis
        job = Job(task_id, arq_redis)
        info = await job.info()
        if info is None:
            raise HTTPException(status_code=404, detail="Task not found or expired")
        status_map = {
            JobStatus.queued:      "pending",
            JobStatus.deferred:    "pending",
            JobStatus.in_progress: "pending",
            JobStatus.complete:    "complete",
            JobStatus.not_found:   "not_found",
        }
        job_status = await job.status()
        status_str = status_map.get(job_status, "pending")
        error_detail: str | None = None
        if not info.success and info.result is not None:
            # SECURITY: use result.error (sanitized IngestionResponse field),
            # NOT str(info.result) which may expose internal paths
            result_dict = info.result if isinstance(info.result, dict) else {}
            error_detail = result_dict.get("error")
            status_str = "failed"
        # Tenant isolation: reject cross-tenant reads with 404 (not 403)
        result_tenant = (info.result or {}).get("tenant_id") if isinstance(info.result, dict) else None
        if result_tenant and result_tenant != current_user.tenant_id:
            raise HTTPException(status_code=404, detail="Task not found or expired")
        return APIResponse(
            success=True,
            data={"task_id": task_id, "status": status_str, "error": error_detail},
        )
    except HTTPException:
        raise
    except redis.RedisError as exc:
        logger.error(f"[API:ingest_status] task_id={task_id} redis error={exc}")
        raise HTTPException(status_code=503, detail="状态查询暂时不可用")
```

**Import additions needed at top of api.py:**
```python
from fastapi import Depends
from services.auth.oidc_auth import get_current_user, AuthenticatedUser
```

---

### `services/auth/oidc_auth.py` (middleware — add `get_current_user` dependency)

**Analog:** Same file lines 83-95 (`verify_token`) + RESEARCH.md Pattern 5

**Add at end of file, after `get_auth_service()`** (lines 235-242):
```python
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_bearer = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """FastAPI dependency: extract + verify JWT Bearer token."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization required")
    user = await get_auth_service().verify_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user
```

**Pattern rules:**
- `auto_error=False` on `HTTPBearer` — lets us return a clean 401 instead of FastAPI's default 403
- `get_auth_service()` reuses the existing singleton (line 239) — no new instantiation
- Do NOT add auth to existing `POST /ingest` or `POST /query` routes in this phase (surgical change rule)

---

### `tests/unit/test_ingest_worker.py` (test)

**Analog:** `tests/unit/test_tasks.py` — full file read above

**Imports pattern** (test_tasks.py lines 1-11):
```python
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
```

**Test function pattern** (test_tasks.py lines 17-33):
```python
@pytest.mark.asyncio
async def test_log_task_error_no_log_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given a task that completed successfully, log_task_error must NOT call logger.error."""
    mock_logger = MagicMock()
    monkeypatch.setattr("utils.tasks.logger", mock_logger)

    from utils.tasks import log_task_error  # import after monkeypatch
    ...
```

**Apply to worker tests:**
```python
@pytest.mark.asyncio
async def test_ingest_task_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """ingest_task returns dict with success=True when pipeline.run() succeeds."""
    # Arrange
    mock_result = MagicMock()
    mock_result.doc_id = "doc-001"
    mock_result.success = True
    mock_result.error = None

    mock_pipeline = MagicMock()
    mock_pipeline.run = AsyncMock(return_value=mock_result)
    monkeypatch.setattr("services.ingest_worker.get_ingest_pipeline", lambda: mock_pipeline)

    from services.ingest_worker import ingest_task
    # Act — call directly, bypassing ARQ queue
    ctx: dict = {}
    result = await ingest_task(ctx, {"doc_id": "doc-001", "content": "test", "tenant_id": "t1"})
    # Assert
    assert result["success"] is True
    assert result["doc_id"] == "doc-001"
```

**Key rule:** Call `ingest_task(ctx, req_data)` directly — do NOT start the ARQ worker in unit tests. Use `monkeypatch` for pipeline dependency, not fixtures that require Redis.

---

### `tests/unit/test_ingest_status.py` (test)

**Analog:** `tests/unit/test_tasks.py` + FastAPI `TestClient` pattern

**FakeAsyncRedis fixture pattern** (RESEARCH.md Code Examples):
```python
import pytest_asyncio
import fakeredis

@pytest_asyncio.fixture
async def fake_arq_redis():
    server = fakeredis.FakeServer()
    redis_client = fakeredis.FakeAsyncRedis(server=server)
    yield redis_client
    await redis_client.aclose()
```

**Route test pattern — 404 when key absent:**
```python
@pytest.mark.asyncio
async def test_status_404_when_key_absent(fake_arq_redis, monkeypatch) -> None:
    """GET /ingest/status/{task_id} returns 404 when job key is absent (TTL expired or unknown)."""
    from fastapi.testclient import TestClient
    # monkeypatch app.state.arq_redis with fake_arq_redis
    ...
    resp = client.get("/api/v1/ingest/status/nonexistent-id-xxx",
                      headers={"Authorization": "Bearer <test-token>"})
    assert resp.status_code == 404
```

**Pattern rules (from test_tasks.py):**
- `@pytest.mark.asyncio` on every async test
- `monkeypatch.setattr(...)` for all dependencies
- `from <module> import <name>` after monkeypatch (import after patch, not before)
- Descriptive docstring: "Given X, Y must Z"
- AAA structure: Arrange / Act / Assert with blank lines

---

## Shared Patterns

### Imports block (all new/modified Python files)

**Source:** `controllers/api.py` lines 1-16
```python
from __future__ import annotations
import uuid
import redis
from fastapi import APIRouter, HTTPException, Request, Depends
from loguru import logger
from config.settings import settings
```
Apply `from __future__ import annotations` as first line in all new `.py` files.

### Route decorator shape

**Source:** `controllers/api.py` lines 78-80, 103-105
```python
@router.post("/ingest/async", response_model=APIResponse, status_code=202, tags=["ingestion"])
@_limiter.limit(f"{settings.rate_limit_ingest_rpm}/minute")
async def ingest_async(request: Request, ...) -> APIResponse:
```
Always: `@router.<method>` first, `@_limiter.limit(...)` second, `async def` third.

### Error handling (controller layer)

**Source:** `controllers/api.py` lines 96-100
```python
    except HTTPException:
        raise
    except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError) as exc:
        logger.error(f"[API:ingest] trace={trace_id} error={exc}")
        raise HTTPException(status_code=500, detail="文档摄取失败，请稍后重试")
```
For ARQ routes: add `redis.RedisError` to the narrow exception tuple. Always re-raise `HTTPException` first. No bare `except Exception` (ERR-01).

### APIResponse envelope

**Source:** `controllers/api.py` lines 91-95, 116-119
```python
return APIResponse(
    success=True,
    data={"task_id": task_id, "status": "queued"},
    trace_id=task_id,
)
```
All routes return `APIResponse`. `data` is a dict. `trace_id` is optional.

### Singleton Redis pool (app.state pattern)

**Source:** `utils/cache.py` lines 15-36 (existing `get_redis()` singleton)
```python
_redis_client = None

async def get_redis():
    global _redis_client
    if _redis_client is None:
        from redis.asyncio import from_url
        from config.settings import settings
        _redis_client = await from_url(settings.redis_url, ...)
    return _redis_client
```
For ARQ: create `arq_redis` pool once in `main.py` lifespan, store as `app.state.arq_redis`. Access via `request.app.state.arq_redis` in routes. Do NOT create a new pool per request.

### Settings field pattern

**Source:** `config/settings.py` lines 278-280
```python
    redis_url:      str  = "redis://localhost:6379/0"
    cache_ttl_sec:  int  = 3600
    cache_enabled:  bool = True
```
Field format: `name: type = default  # comment`. Align colons optionally. New fields go in the existing Redis section.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `services/ingest_worker.py` (WorkerSettings class) | service | event-driven | No ARQ worker classes exist in codebase; use RESEARCH.md Pattern 2 directly |

---

## Metadata

**Analog search scope:** `controllers/`, `services/auth/`, `config/`, `utils/`, `tests/unit/`
**Files scanned:** 6 source files read in full
**Pattern extraction date:** 2026-04-27
