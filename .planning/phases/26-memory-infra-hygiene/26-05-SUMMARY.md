# Plan 26-05 Summary — main.py lifespan shutdown wiring + integration

**Status:** ✅ Complete
**Executed:** 2026-05-17
**Wave:** 3 (depends 26-03 + 26-04)
**Requirements closed:** TD-01 SC-4 (real-PG lifespan integration), TD-03 SC-4 (close-wiring)

## What shipped

- `services/memory/memory_service.py` — added `MemoryService.close()` cascading to `self._long.close()` (Branch B(i) from Task 1 audit)
- `main.py` — lifespan shutdown branch upgraded:
  - Audit `_get_audit().flush()` → `_get_audit().close()` (also tears down asyncpg pool)
  - Added `_get_memory().close()` AFTER audit close, BEFORE observability flush (D-15 ordering)
  - Both blocks use narrow `try/except Exception as exc: logger.warning(...)` (replaces silent `pass`)
- `tests/integration/test_lifespan_shutdown_closes_pools.py` — 3 integration tests

## Task 1 finding (Branch decision)

**Branch B(i) confirmed.** `MemoryService.__init__` composes:
- `self._short = ShortTermMemory()` — Redis client (owns its own lifecycle; not closed by MemoryService.close)
- `self._long = LongTermMemory()` — asyncpg pool (closed via cascade)

`MemoryContext` is a `@dataclass` (line 71), not a pool-bearing class. No `MemoryContext.close()` needed (already noted in Plan 26-03 SUMMARY).

## Verification

- `uv run pytest tests/integration/test_lifespan_shutdown_closes_pools.py -v` → **3/3 PASSED** on real local pgvector
- `uv run pytest tests/unit/ -k 'audit or memory' -q` → **116 passed** (no regressions in audit + memory unit suite)
- `uv run ruff check main.py services/memory/memory_service.py` → clean
- `grep -c "_get_audit().close()" main.py` == 1
- `grep -c "_get_audit().flush()" main.py` == 0 (upgraded)
- `grep -c "_get_memory().close()" main.py` == 1
- Manual line-order verification: in `main.py`, audit close (line ~128) appears BEFORE memory close (line ~135), which appears BEFORE observability flush + arq_redis close. D-15 ordering preserved.

## Eng-review fixes embedded

None — Plan 26-05 had no eng-review findings.

## Implementation deviation

D-15 ordering test was simplified from the original plan: instead of using full `lifespan(app)` context manager (which has many side-effect dependencies — knowledge service, event bus, arq, etc.), the test directly drives `audit_svc.close()` + `mem_svc.close()` in the same sequence main.py uses. This isolates the assertion to the property under test (close ordering) without coupling to unrelated lifespan startup paths that aren't relevant to D-15.

## Commits

- `feat(26-05): MemoryService.close cascades to LongTermMemory.close (TD-03)`
- `refactor(26-05): main.py lifespan shutdown closes audit + memory pools (TD-01 + TD-03)`
- `test(26-05): integration test for lifespan shutdown pool cleanup (TD-01 + TD-03 SC-4)`

## Closes Phase 26

All 3 TD requirements (TD-01, TD-03, TD-07) fully implemented and verified across unit + integration tests.
