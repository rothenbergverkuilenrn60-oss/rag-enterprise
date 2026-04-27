---
plan: 05-01
phase: 05-async-ingest-tracking
status: complete
completed: "2026-04-27"
requirements: [ASYNC-01, ASYNC-02]
---

# 05-01 Summary: ARQ Dependencies + Failing Test Stubs

## What Was Built

Established Wave 0 test scaffolding and declared ARQ + FakeRedis dependencies.

1. **`requirements.txt`** — added `arq==0.28.0` under STAGE 5 section
2. **`requirements-dev.txt`** — created with `fakeredis==2.35.1` (test-only)
3. **`tests/unit/test_ingest_worker.py`** — 7 failing stubs for `ingest_task` + `WorkerSettings`:
   - success path, failure detail, exception propagation, tenant_id passthrough
   - `WorkerSettings.keep_result == 86400` (ASYNC-02 24h TTL)
   - `ingest_task in WorkerSettings.functions`
   - `WorkerSettings.job_timeout == 300`
4. **`tests/unit/test_ingest_status.py`** — 10 failing stubs for the async ingest API:
   - POST /ingest/async → 202 + task_id < 200ms
   - enqueue_job called with "ingest_task"
   - 401 without auth on both routes
   - status pending/complete/failed
   - 404 for unknown, expired, cross-tenant task_ids
   - 400 for malformed task_id

## Self-Check: PASSED

- `grep -c '^arq==0.28.0' requirements.txt` → 1 ✓
- `grep -c '^fakeredis==2.35.1' requirements-dev.txt` → 1 ✓
- `grep -c 'def test_' tests/unit/test_ingest_worker.py` → 7 ✓
- `grep -c 'def test_' tests/unit/test_ingest_status.py` → 10 ✓
- All imports inside function bodies → pytest collection succeeds before Plan 03 ✓
- No `except Exception` bare clauses (ERR-01) ✓
- `WorkerSettings.keep_result == 86400` pinned ✓

## Key Files

### Modified
- `requirements.txt` — +1 line: `arq==0.28.0`

### Created
- `requirements-dev.txt` — fakeredis==2.35.1
- `tests/unit/test_ingest_worker.py` — 7 RED stubs (117 lines)
- `tests/unit/test_ingest_status.py` — 10 RED stubs (361 lines)

## Commits
- `2c0d8f3 feat(05-01): pin arq==0.28.0 and fakeredis==2.35.1 dependencies`
- `a6fb936 test(05-01): add failing RED test stubs for ingest_worker and ingest_status`

## Deviations
None — implemented exactly per plan spec. Tests fail RED until Plan 03 creates services/ingest_worker.py and the new routes.
