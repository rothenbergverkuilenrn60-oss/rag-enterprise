# Plan 26-03 Summary — memory_service consumes prepare_dsn + close()

**Status:** ✅ Complete
**Executed:** 2026-05-17
**Wave:** 2 (depends 26-01)
**Requirements closed:** TD-03 (memory side)

## What shipped

- `services/memory/memory_service.py`:
  - Added module import `from utils.asyncpg_helper import prepare_dsn`
  - `LongTermMemory._get_pool` replaced 7-line inline strip with `dsn, ssl_kwarg = prepare_dsn(settings.pg_dsn)`
  - Added `LongTermMemory.close()` method — idempotent pool teardown
- `tests/unit/test_memory_service_prepare_dsn.py` — 3 unit tests

## Implementation deviation from plan

Plan 26-03 originally expected 5 tests (including 2 MemoryContext branch tests). **Reality:** `MemoryContext` in this codebase is a `@dataclass` (line 71-83), NOT a pool-bearing class — it's a typed value object returned by `MemoryService.load_context`. Only `LongTermMemory` (line 144) owns the asyncpg pool. The MemoryContext-side tests + `close()` method were dropped (would be no-op on a dataclass).

This collapses Plan 26-03 from 5 tests → 3 tests. Plan 26-05's `MemoryService.close()` cascade simplifies similarly: only needs to call `self._long.close()` (no `self._short.close()` — Redis short-term memory uses its own client lifecycle; no MemoryContext.close() — dataclass).

## Verification

- `uv run pytest tests/unit/test_memory_service_prepare_dsn.py -v` → **3/3 PASSED** in 0.22s
- `grep -nE 'ssl=disable|postgresql\+asyncpg://' services/memory/memory_service.py` → **zero hits** (TD-03 acceptance criterion met)
- `uv run ruff check services/memory/memory_service.py` → clean
- pgvector `register_vector` `_init_conn` callback preserved verbatim — RecallTool + save_fact behavior unchanged

## Eng-review fixes embedded

None — Plan 26-03 had no eng-review findings.

## Commits

- `test(26-03): RED gates for memory_service prepare_dsn adoption + close (TD-03)`
- `refactor(26-03): memory_service adopts prepare_dsn + close() (TD-03)`

## Unblocks

- Plan 26-05 Task 3 (main.py lifespan shutdown calls `get_memory_service().close()` which will cascade through MemoryService.close → LongTermMemory.close)
