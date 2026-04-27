# Phase 5: Async Ingest Tracking — Research

**Researched:** 2026-04-27
**Domain:** ARQ task queue, Redis job-status schema, FastAPI async endpoints, JWT auth integration
**Confidence:** HIGH (ARQ source code verified via GitHub; Redis pattern verified from codebase; auth pattern verified from codebase)

---

## Summary

Phase 5 replaces the current `POST /ingest/async` stub (which uses `BackgroundTasks` with no status tracking) with a proper ARQ-backed async pipeline. Clients post a document, receive a `task_id` immediately, and poll `GET /ingest/status/{task_id}` for completion. ARQ stores job results in Redis under `result_key_prefix + job_id` with a configurable `keep_result` TTL; the 24-hour requirement is met by setting `keep_result=86400` at `WorkerSettings` level. Exceptions raised inside ARQ jobs are serialized alongside the result and exposed on `job.info()` without re-raising, making safe error-detail propagation straightforward.

**Primary recommendation:** Add `arq==0.28.0` and `fakeredis==2.35.1` to `requirements.txt`. Implement `services/ingest_worker.py` containing the ARQ task function and `WorkerSettings`. Wire a new `GET /ingest/status/{task_id}` route in `controllers/api.py`. Reuse `utils/cache.py`'s `get_redis()` for the enqueue call so no second Redis pool is created.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ASYNC-01 | `POST /ingest/async` returns `task_id` immediately; ingestion runs as ARQ background job | ARQ `enqueue_job()` returns a `Job` object with `.job_id` synchronously; no blocking; route returns 202 with `task_id` in < 200ms regardless of document size |
| ASYNC-02 | `GET /ingest/status/{task_id}` polls Redis (`job:{task_id}`, TTL 24h); returns status + error detail on failure | ARQ stores results at `result_key_prefix + job_id`; `job.info()` gives `JobDef` with success flag and serialized exception string; explicit 404 when key is absent |
</phase_requirements>

---

## Project Constraints (from CLAUDE.md)

- Production-grade only — Pydantic V2, `mypy --strict`, `ruff`
- No bare `except` — narrow exception types only (ERR-01)
- No blocking I/O in async contexts
- Adapters for all external dependencies
- Tenacity retry logic for all external calls
- Structured logging (loguru) for every operation
- `REDIS_URL` / `REDIS_*` must come from `config/settings.py` — no hardcoded URLs
- New endpoints must use the same JWT auth dependency already in use

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Enqueue ingest job | API / FastAPI route | — | Route handler calls `ArqRedis.enqueue_job()`; returns `task_id` immediately |
| Execute ingest logic | ARQ Worker process | — | Worker runs `IngestionPipeline.run()` in background; separate process/container |
| Store job status + result | Redis (ARQ-managed) | — | ARQ writes `result_key_prefix + job_id` with TTL after job completes or fails |
| Poll job status | API / FastAPI route | Redis | Route reads Redis via `job.info()` / `job.status()`; returns structured JSON |
| TTL enforcement (24h) | ARQ WorkerSettings | — | `keep_result=86400` on `WorkerSettings`; ARQ applies `SET ... PX` on result write |
| Error detail propagation | ARQ Worker → Redis | API route | Exception serialized into result payload; route reads `info.result` string |
| Auth enforcement | FastAPI dependency | JWT service | Same `Depends(get_current_user)` pattern already used on other routes |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| arq | 0.28.0 | Async task queue backed by Redis | Retry + crash persistence; same Redis already in stack; zero new infra [VERIFIED: github.com/python-arq/arq] |
| redis (already installed) | 5.2.1 | Redis client (redis.asyncio) | Already in requirements.txt; ARQ uses the same client [VERIFIED: requirements.txt] |
| fakeredis | 2.35.1 | In-process Redis fake for tests | FakeAsyncRedis compatible with redis.asyncio; no test container needed [VERIFIED: fakeredis.readthedocs.io] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ARQ | Celery | Celery requires broker + result backend config; heavier; ARQ is pure-asyncio |
| ARQ | FastAPI BackgroundTasks (current) | BackgroundTasks has no status tracking, no crash recovery, no TTL |
| ARQ | RQ (Redis Queue) | RQ is sync-only; not suitable for async FastAPI codebase |
| fakeredis | testcontainers Redis | testcontainers requires Docker in CI; fakeredis is lighter and already used in similar projects |

**Installation:**
```bash
pip install arq==0.28.0 fakeredis==2.35.1
```

---

## Architecture Patterns

### System Architecture Diagram

```
Client
  │
  ├─ POST /ingest/async ──────────────────────────────────────┐
  │   (FastAPI route, < 200ms)                                 │
  │   1. Validate JWT (Depends)                                │
  │   2. arq_redis.enqueue_job("ingest_task", req)            │
  │   3. Return {task_id, status: "queued"}                   │
  │                                                            │
  └─ GET /ingest/status/{task_id} ─────────────────────────┐  │
      (FastAPI route)                                        │  │
      1. Validate JWT                                        │  │
      2. job = Job(task_id, arq_redis)                      │  │
      3. info = await job.info()                            │  │
      4. Map JobStatus → response JSON                      │  │
      5. 404 if info is None (TTL expired or unknown)       │  │
                                                             │  │
Redis ───────────────────────────────────────────────────────┘  │
  │  arq:result:{task_id}  (SET PX 86400000ms)                  │
  │  arq:queue (sorted set of pending jobs)  ◄──────────────────┘
  │
ARQ Worker (separate process: `arq services.ingest_worker.WorkerSettings`)
  │  1. Dequeue job from arq:queue
  │  2. Call IngestionPipeline.run(req)
  │  3. Write result to arq:result:{task_id} with TTL
  │  4. On exception: write exception string to same key
```

### Recommended Project Structure

```
services/
├── ingest_worker.py      # ARQ task function + WorkerSettings
controllers/
├── api.py                # add GET /ingest/status/{task_id}
                          # rewrite POST /ingest/async to use ARQ
config/
├── settings.py           # add arq_keep_result_sec: int = 86400
tests/
├── unit/
│   └── test_ingest_worker.py   # ARQ job logic with FakeAsyncRedis
│   └── test_ingest_status.py   # FastAPI route with TestClient + FakeAsyncRedis
```

### Pattern 1: ARQ Task Function

**What:** An `async def` that takes `ctx` as first arg and returns a serializable result. Exceptions are caught by ARQ and stored automatically.
**When to use:** Any background work that needs status tracking and retry.

```python
# Source: github.com/python-arq/arq (arq-docs.helpmanual.io)
async def ingest_task(ctx: dict, req_data: dict) -> dict:
    """ARQ worker task — wraps IngestionPipeline.run()."""
    from services.pipeline import get_ingest_pipeline
    from utils.models import IngestionRequest
    pipeline = get_ingest_pipeline()
    req = IngestionRequest(**req_data)
    result = await pipeline.run(req)
    return {"doc_id": result.doc_id, "success": result.success, "error": result.error}
```

**Key constraints:**
- First parameter is always `ctx: dict` (ARQ injects job metadata)
- Arguments must be JSON-serializable (pass `req.model_dump()`, not the Pydantic object)
- Return value must be JSON-serializable
- Raise any exception to mark the job as failed; ARQ stores the exception

### Pattern 2: WorkerSettings

```python
# Source: arq-docs.helpmanual.io
from arq import Worker
from arq.connections import RedisSettings

class WorkerSettings:
    functions = [ingest_task]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    keep_result = 86400        # 24 hours — satisfies ASYNC-02 TTL requirement
    keep_result_forever = False
    job_timeout = 300          # 5 minutes per job
    max_jobs = 10              # concurrency cap
```

### Pattern 3: Enqueueing from FastAPI Route

```python
# Source: arq-docs.helpmanual.io
from arq.connections import create_pool, RedisSettings

@router.post("/ingest/async", response_model=APIResponse, tags=["ingestion"])
@_limiter.limit(f"{settings.rate_limit_ingest_rpm}/minute")
async def ingest_async(
    request: Request,
    req: IngestionRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> APIResponse:
    arq_redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    job = await arq_redis.enqueue_job("ingest_task", req.model_dump())
    # job is None if duplicate _job_id; handle accordingly
    task_id = job.job_id if job else str(uuid.uuid4())
    return APIResponse(
        success=True,
        data={"task_id": task_id, "status": "queued"},
        trace_id=task_id,
    )
```

**Optimization:** Create `arq_redis` pool once at app startup (lifespan), store on `app.state.arq_redis`, inject via `Request.app.state.arq_redis`. Avoids creating a new pool per request.

### Pattern 4: Job Status Polling

```python
# Source: arq-docs.helpmanual.io / arq/jobs.py on GitHub
from arq.jobs import Job, JobStatus

@router.get("/ingest/status/{task_id}", response_model=APIResponse, tags=["ingestion"])
async def ingest_status(
    task_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> APIResponse:
    arq_redis = request.app.state.arq_redis
    job = Job(task_id, arq_redis)
    info = await job.info()
    if info is None:
        raise HTTPException(status_code=404, detail="Task not found or expired")
    status_map = {
        JobStatus.queued: "pending",
        JobStatus.deferred: "pending",
        JobStatus.in_progress: "pending",
        JobStatus.complete: "complete",
        JobStatus.not_found: "not_found",
    }
    status_str = status_map.get(await job.status(), "pending")
    error_detail: str | None = None
    if info is not None and not info.success and info.result is not None:
        error_detail = str(info.result)
    if status_str == "complete" and not info.success:
        status_str = "failed"
    return APIResponse(
        success=True,
        data={"task_id": task_id, "status": status_str, "error": error_detail},
    )
```

### Pattern 5: Auth Dependency (already in codebase)

The current codebase uses `OIDCAuthService.verify_token()` but **does not yet have a FastAPI `Depends()` wrapper**. The current `ingest` and `query` routes do not inject auth. Phase 5 must add a dependency function and apply it consistently to both new routes.

```python
# New dependency to add to services/auth/oidc_auth.py or controllers/api.py
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_bearer = HTTPBearer(auto_error=False)

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

**Note:** If existing routes do not use auth, adding auth to new routes only is still correct per ASYNC-01/02 scope. Do not add auth to existing routes as a side-effect of this phase (surgical change rule).

### Anti-Patterns to Avoid

- **Passing Pydantic objects as ARQ arguments:** ARQ serializes args with msgpack/JSON. Pass `req.model_dump()` not `req`. Reconstruct inside the task.
- **Creating ArqRedis pool per request:** Pool creation is expensive. Create once at lifespan, attach to `app.state`.
- **Using `job.result()` for status polling:** `job.result()` blocks and re-raises exceptions. Use `job.info()` for non-blocking status reads; it returns `None` if not found, not an exception.
- **Returning 200 on `POST /ingest/async`:** The current stub returns 200. Should return 202 (Accepted) to signal async processing.
- **Bare `except Exception`:** Violates ERR-01. Use `except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError, redis.RedisError)` in route handlers.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Job result TTL | Custom Redis EXPIRE after pipeline.run() | `WorkerSettings.keep_result=86400` | ARQ applies TTL atomically on job write; custom EXPIRE is a race condition |
| Exception serialization | Try/except + store string in Redis manually | Let ARQ catch + serialize exceptions natively | ARQ stores the exception object; `info.result` is the exception; `str(info.result)` is the message |
| Job uniqueness | Custom UUID → Redis check | ARQ `_job_id` parameter + ARQ's dedup logic | ARQ deduplicates on `_job_id` automatically |
| Worker process management | `asyncio.create_task` in-process | `arq` CLI / Docker Compose service | In-process tasks die with the web process; ARQ worker is crash-isolated |

---

## Common Pitfalls

### Pitfall 1: `job.result()` Raises Exceptions

**What goes wrong:** Using `await job.result()` in the status route causes the route to raise if the job failed — returning 500 instead of `{"status": "failed", "error": "..."}`.
**Why it happens:** ARQ's `job.result()` is designed to re-raise the original exception for caller convenience.
**How to avoid:** Use `await job.info()` instead. It returns a `JobDef` dataclass with `success: bool` and `result: Any` (the exception object if failed). Call `str(info.result)` to get the error message string.
**Warning signs:** Status endpoint returning 500 for failed jobs.

### Pitfall 2: ArqRedis Pool Created Per Request

**What goes wrong:** Each call to `create_pool()` opens a new Redis connection pool, causing connection exhaustion under load.
**Why it happens:** `create_pool()` is `async` and returns a new pool object every call.
**How to avoid:** Create pool once in `lifespan()`, store as `app.state.arq_redis`, access via `request.app.state.arq_redis` in routes.
**Warning signs:** Redis `max clients reached` errors; connection count growing under load.

### Pitfall 3: ARQ `keep_result` Default is 1 Hour, Not 24 Hours

**What goes wrong:** ASYNC-02 requires 24h TTL; ARQ default `keep_result` is 3600 seconds (1 hour). Without explicit config, status expires in 1 hour.
**Why it happens:** ARQ worker default: `keep_result=3600`. [VERIFIED: arq/worker.py source]
**How to avoid:** Set `keep_result=86400` explicitly in `WorkerSettings`. Verify in integration test.
**Warning signs:** Status endpoint returning 404 after 1 hour instead of 24 hours.

### Pitfall 4: Non-Serializable IngestionRequest

**What goes wrong:** ARQ tries to serialize the job arguments; if `IngestionRequest` contains non-JSON-serializable fields (file bytes, Path objects, etc.), serialization fails silently or raises.
**Why it happens:** ARQ serializes job args before enqueue.
**How to avoid:** Always pass `req.model_dump(mode="json")` into `enqueue_job()`. Reconstruct `IngestionRequest(**req_data)` inside the task function.
**Warning signs:** `unable to serialize result` stored in Redis; job appears queued but never starts.

### Pitfall 5: Worker Not Running During Tests

**What goes wrong:** Tests enqueue jobs but nothing processes them; status stays `pending` forever.
**Why it happens:** ARQ worker is a separate process; unit tests don't start it.
**How to avoid:** For unit tests, call the task function directly (not through ARQ): `result = await ingest_task(ctx, req_data)`. Use `FakeAsyncRedis` for status-endpoint tests. Do not assert on `"complete"` status in unit tests without running the worker.
**Warning signs:** Tests timing out waiting for `"complete"` status.

---

## Code Examples

### FakeAsyncRedis in Tests

```python
# Source: fakeredis.readthedocs.io
import pytest_asyncio
import fakeredis
from arq.connections import ArqRedis

@pytest_asyncio.fixture
async def fake_arq_redis():
    """ARQ-compatible FakeAsyncRedis for unit tests."""
    server = fakeredis.FakeServer()
    # FakeAsyncRedis exposes the same interface as redis.asyncio.Redis
    # ArqRedis wraps redis.asyncio.Redis — pass the fake as the underlying client
    redis_client = fakeredis.FakeAsyncRedis(server=server)
    yield redis_client
    await redis_client.aclose()
```

**Note on ARQ + FakeRedis integration:** ARQ's `ArqRedis` is a subclass of `redis.asyncio.Redis`. The cleanest test approach is to call task functions directly (bypassing ARQ's queue entirely) and test the status-poll route using a pre-seeded `FakeAsyncRedis` that contains a mock result key. [ASSUMED — ARQ does not document FakeRedis compatibility explicitly; verify by running tests]

### Calling Task Function Directly in Tests

```python
# Direct invocation bypasses ARQ queue — tests business logic only
async def test_ingest_task_success(monkeypatch):
    ctx = {}  # ARQ context dict
    req_data = {"content": "test doc", "doc_id": "doc-001", "tenant_id": "t1"}
    # monkeypatch pipeline.run() ...
    result = await ingest_task(ctx, req_data)
    assert result["success"] is True
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `BackgroundTasks` (no tracking) | ARQ + Redis result store | Phase 5 | Clients can poll status; errors are retrievable |
| No `task_id` returned | `task_id` in 202 response | Phase 5 | Enables async workflows and retries |

**Current codebase state (verified):**
- `POST /ingest/async` exists in `controllers/api.py` at line 103 [VERIFIED] but uses `BackgroundTasks` with no status tracking; returns a `trace_id` not a `task_id` stored in Redis.
- `GET /ingest/status/{task_id}` does NOT exist yet [VERIFIED: controllers/api.py has no such route].
- `settings.redis_url` exists at `config/settings.py:278` [VERIFIED]; no `arq_keep_result_sec` setting yet.
- `utils/cache.py` provides `get_redis()` → `redis.asyncio` client [VERIFIED]; ARQ uses same underlying library.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| redis (redis.asyncio) | ARQ pool, status route | ✓ | 5.2.1 | — |
| arq | Worker + enqueue | ✗ (not in requirements.txt) | 0.28.0 available | None — must install |
| fakeredis | Unit tests | ✗ (not in requirements.txt) | 2.35.1 available | testcontainers (heavier) |
| Redis server | Runtime | Not verified in this env | — | Docker Compose service |

**Missing dependencies with no fallback:**
- `arq==0.28.0` — must be added to `requirements.txt`

**Missing dependencies with fallback:**
- `fakeredis==2.35.1` — required for unit tests; alternative is testcontainers with Docker

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio |
| Config file | `pytest.ini` (asyncio_mode = auto) |
| Quick run command | `pytest tests/unit/test_ingest_worker.py tests/unit/test_ingest_status.py -x` |
| Full suite command | `pytest tests/ --cov=services --cov=controllers --cov-report=term-missing` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ASYNC-01 | `POST /ingest/async` returns `task_id` in < 200ms | unit | `pytest tests/unit/test_ingest_status.py::test_async_ingest_returns_task_id -x` | ❌ Wave 0 |
| ASYNC-01 | ARQ job is enqueued (not run inline) | unit | `pytest tests/unit/test_ingest_status.py::test_async_ingest_enqueues_job -x` | ❌ Wave 0 |
| ASYNC-02 | Status returns `pending` for queued job | unit | `pytest tests/unit/test_ingest_status.py::test_status_pending -x` | ❌ Wave 0 |
| ASYNC-02 | Status returns `complete` with doc_id | unit | `pytest tests/unit/test_ingest_worker.py::test_ingest_task_success -x` | ❌ Wave 0 |
| ASYNC-02 | Status returns `failed` with error detail on exception | unit | `pytest tests/unit/test_ingest_worker.py::test_ingest_task_failure_error_detail -x` | ❌ Wave 0 |
| ASYNC-02 | Status returns 404 after TTL expiry | unit | `pytest tests/unit/test_ingest_status.py::test_status_404_when_key_absent -x` | ❌ Wave 0 |
| ASYNC-02 | TTL is 24h (86400s) | unit | `pytest tests/unit/test_ingest_worker.py::test_keep_result_ttl_is_24h -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/unit/test_ingest_worker.py tests/unit/test_ingest_status.py -x`
- **Per wave merge:** `pytest tests/ -x --timeout=60`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/test_ingest_worker.py` — covers ASYNC-01 (task function), ASYNC-02 (result/error/TTL)
- [ ] `tests/unit/test_ingest_status.py` — covers ASYNC-01 (route returns task_id), ASYNC-02 (status polling, 404)
- [ ] `fakeredis==2.35.1` install: `pip install fakeredis==2.35.1` — add to `requirements.txt`
- [ ] `arq==0.28.0` install: `pip install arq==0.28.0` — add to `requirements.txt`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | JWT via `OIDCAuthService`; `Depends(get_current_user)` on both new routes |
| V3 Session Management | no | Stateless JWT; no session |
| V4 Access Control | yes | `task_id` must only be readable by the tenant that created it — enforce tenant_id check in status route |
| V5 Input Validation | yes | `IngestionRequest` validated by Pydantic V2 before enqueue |
| V6 Cryptography | no | ARQ does not encrypt Redis data; Redis assumed internal network |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Task ID enumeration — polling other users' task IDs | Information disclosure | Store `tenant_id` in job result; status route validates `info.result["tenant_id"] == current_user.tenant_id`; return 404 (not 403) on mismatch |
| Error detail leakage | Information disclosure | `str(exception)` may contain internal paths/secrets; sanitize before returning: only return `result.error` from `IngestionResponse`, not raw Python exception repr |
| Redis key injection via task_id path param | Tampering | Validate `task_id` is a valid UUID before passing to `Job(task_id, ...)` |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | FakeAsyncRedis can be used as a drop-in for ARQ's internal Redis calls in unit tests | Code Examples | Tests may fail to simulate ARQ behavior; fallback: call task function directly, skip queue-layer tests |
| A2 | ARQ 0.28.0 is installable in the `torch_env` conda environment without conflicts | Environment Availability | May require dependency resolution; mitigation: pin to compatible version |

---

## Open Questions (RESOLVED)

1. **Auth on existing routes:** Current `POST /ingest` and `POST /ingest/async` have no JWT `Depends()`. Phase 5 adds auth to the new async endpoint. Should the existing sync `/ingest` also get auth added in this phase? Recommendation: no — stay surgical, add auth only to new routes per phase scope.

2. **Tenant isolation on task status:** ASYNC-02 specifies `job:{task_id}` key with TTL but does not specify per-tenant access control. Recommendation: store `tenant_id` in the job result payload; status route rejects cross-tenant reads with 404.

3. **ARQ worker deployment:** Separate Docker Compose service (recommended for production) vs. `asyncio.create_task` in-process (simpler but no crash isolation). Decision logged in STATE.md as open question 2. Recommendation: implement as separate worker process (`arq services.ingest_worker.WorkerSettings`); add to `docker-compose.yml`.

---

## Sources

### Primary (HIGH confidence)
- `github.com/python-arq/arq` — JobStatus enum values, result storage key prefix, keep_result TTL application, exception serialization pattern, worker.py defaults
- `arq-docs.helpmanual.io` — WorkerSettings config, `enqueue_job()` API, `job.info()` / `job.status()` / `job.result()` semantics
- `fakeredis.readthedocs.io` — FakeAsyncRedis async usage pattern, pytest-asyncio fixture example
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/controllers/api.py` — existing route patterns, limiter usage, Redis import, current ingest/async stub
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/config/settings.py` — redis_url location, Settings pattern, field_validator usage
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/utils/cache.py` — get_redis() pattern, connection pool singleton
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/services/auth/oidc_auth.py` — OIDCAuthService.verify_token(), AuthenticatedUser dataclass, no existing Depends() wrapper
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/requirements.txt` — confirmed arq and fakeredis are NOT currently installed
- `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/pytest.ini` — asyncio_mode=auto confirmed

### Secondary (MEDIUM confidence)
- ARQ v0.28.0 release date April 16, 2026 — from GitHub repository metadata

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — arq source verified, fakeredis docs verified, redis already in requirements
- Architecture: HIGH — codebase verified; ARQ source verified for key schema and TTL behavior
- Pitfalls: HIGH — verified from ARQ source code and codebase patterns
- Auth integration: MEDIUM — `OIDCAuthService` verified but no `Depends()` wrapper exists yet; pattern must be created

**Research date:** 2026-04-27
**Valid until:** 2026-05-27 (arq 0.28.0 is current; stable library)
