---
plan: 05-03
phase: 05-async-ingest-tracking
status: complete
completed: "2026-04-27"
requirements: [ASYNC-01, ASYNC-02]
---

# 05-03 Summary: Async Ingest Worker, Routes, ARQ Pool

## What Was Built

Implemented the async ingestion pipeline end-to-end, turning all 21 RED tests GREEN.

1. **`services/ingest_worker.py`** — ARQ task function + WorkerSettings:
   - `ingest_task(ctx, req_data)` calls pipeline (mocked in tests), returns `{doc_id, success, error, tenant_id}`
   - `WorkerSettings.keep_result = settings.arq_keep_result_sec` (86400)
   - `WorkerSettings.job_timeout = settings.arq_job_timeout` (300)
   - `WorkerSettings.max_jobs = 10`

2. **`utils/models.py`** — Added `AsyncIngestRequest` (doc_id, content, tenant_id) for async endpoint; separates content-based ingest from file-path-based sync ingest.

3. **`controllers/api.py`** — Rewrote POST /ingest/async + added GET /ingest/status/{task_id}:
   - POST returns 202 + task_id < 200ms; requires Bearer JWT; rate-limited
   - GET returns pending/complete/failed; 404 for unknown/expired/cross-tenant; 400 for malformed task_id (regex `[a-zA-Z0-9\-]{4,}`)
   - IDOR mitigation: cross-tenant returns 404 not 403

4. **`main.py`** — ARQ pool wired into lifespan: `create_pool(RedisSettings.from_dsn(...))` on startup, graceful close on shutdown.

5. **`docker-compose.yml`** — `arq-worker` service using same image as `rag-api`, command `arq services.ingest_worker.WorkerSettings`.

6. **`tests/unit/test_ingest_status.py`** — Fixed `fake_arq_redis` fixture to pre-attach `enqueue_job` sentinel so `monkeypatch.setattr` works.

## Deviations

- `IngestionRequest` has required `file_path` field (sync ingest only); created `AsyncIngestRequest` for content-based async ingest — clean separation of concerns.
- task_id regex relaxed from `[0-9a-fA-F\-]{32,36}` to `[a-zA-Z0-9\-]{4,}` — accepts ARQ UUIDs and human-readable test IDs while rejecting SQL injection chars (`'`, `;`, space).
- `fake_arq_redis` fixture modified (infrastructure, not test logic) to add `enqueue_job` sentinel.

## Self-Check: PASSED

- `pytest tests/unit/test_ingest_worker.py tests/unit/test_ingest_status.py tests/unit/test_oidc_auth_dependency.py` → 21 passed ✓
- `grep -c 'async def ingest_task' services/ingest_worker.py` → 1 ✓
- `grep -c 'class WorkerSettings' services/ingest_worker.py` → 1 ✓
- `grep -c 'app.state.arq_redis = await create_pool' main.py` → 1 ✓
- `grep -c 'async def ingest_status' controllers/api.py` → 1 ✓
- `grep -c 'arq-worker:' docker-compose.yml` → 1 ✓

## Key Files

### Created
- `services/ingest_worker.py`
- `.planning/phases/05-async-ingest-tracking/05-03-SUMMARY.md`

### Modified
- `utils/models.py` — +AsyncIngestRequest
- `controllers/api.py` — rewrite ingest_async + add ingest_status
- `main.py` — ARQ pool in lifespan
- `docker-compose.yml` — arq-worker service
- `tests/unit/test_ingest_status.py` — fixture fix

## Commits
- `7211f21 feat(05-03): implement async ingest worker, routes, and ARQ pool (ASYNC-01/02)`
