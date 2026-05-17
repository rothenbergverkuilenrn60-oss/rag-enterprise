# Plan 26-04 Summary — AuditService pool + _create_tables + close

**Status:** ✅ Complete
**Executed:** 2026-05-17
**Wave:** 2 (depends 26-01)
**Requirements closed:** TD-01 (audit_log auto-create), TD-03 (audit side)

## What shipped

- `services/audit/audit_service.py`:
  - Module-level imports `import asyncpg` + `from utils.asyncpg_helper import prepare_dsn`
  - `AuditService.__init__` initializes `self._pool: asyncpg.Pool | None = None`
  - Added `_get_pool` — lazy singleton with P1 try/except reset on `_create_tables` failure
  - Added `_create_tables` — verbatim DDL port from docstring + `REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC` (INSERT-ONLY invariant preserved)
  - Refactored `_flush_to_db` — uses pool `acquire()` instead of per-flush `asyncpg.connect()`; narrow `asyncpg.PostgresError` then broad fallback for non-PG pool errors
  - Added `close()` — A2 lock-wrapped drain + idempotent pool teardown
  - Updated class docstring: "应用首次部署时执行" → "由 _get_pool() 首次调用时自动执行 — Plan 26-04 / TD-01"
- `tests/unit/test_audit_service_pool.py` — 10 unit tests
- `tests/integration/test_audit_log_auto_create.py` — 2 real-PG integration tests

## Verification

- `uv run pytest tests/unit/test_audit_service_pool.py -v` → **10/10 PASSED** in 0.15s
- `uv run pytest tests/integration/test_audit_log_auto_create.py -v` → **2/2 PASSED** on real local pgvector
- `grep -nE 'ssl=disable|postgresql\+asyncpg://' services/audit/audit_service.py` → zero hits (TD-03 acceptance met)
- `grep -nE 'asyncpg\.connect\(' services/audit/audit_service.py` → zero hits (pool-only path)
- `uv run ruff check services/audit/audit_service.py` → clean

## Eng-review fixes embedded

- **A2** — close() drain wrapped in `async with self._lock` (symmetric with existing `flush()`)
- **P1** — `_get_pool` try/except `_create_tables`; on failure pool closed + `self._pool = None` + raise
- **T1 R1** — regression test `test_close_vs_overflow_flush_no_event_loss` proves A2 lock fix prevents event loss under concurrent close() + buffer-overflow

## Implementation deviation

A2 unit test rewritten mid-execution: original `monkeypatch.setattr(svc._lock, "__aenter__", spy_aenter)` doesn't intercept `async with` (Python looks up `__aenter__` via type-level descriptor, not instance). Replaced with a blocking-strategy test: acquire the lock before calling close(); assert flush hasn't fired; release lock; assert flush fires after release. Proves the same property more robustly.

## Commits

- `test(26-04): RED gates for AuditService pool + create_tables + close + race regression (TD-01 + TD-03)`
- `refactor(26-04): AuditService singleton pool + lazy _create_tables + close (TD-01 + TD-03)`
- `test(26-04): real-PG cold-start integration test for audit_log auto-create (TD-01 SC-1)`

## Unblocks

- Plan 26-05 main.py lifespan shutdown wiring (will call `get_audit_service().close()`)
