---
phase: 23-background-extractor-schema-migration
plan: 01
subsystem: database
tags: [pgvector, hnsw, asyncpg, register_vector, ddl, schema-migration, long_term_facts, mem-01]

requires:
  - phase: 01-foundation
    provides: pgvector + asyncpg pool patterns; vector_store.py register_vector + HNSW DDL precedent reused verbatim
provides:
  - "long_term_facts.embedding vector(settings.embedding_dim) column (additive, idempotent ALTER)"
  - "ltf_emb_hnsw_idx HNSW index — vector_cosine_ops, m=16, ef_construction=64"
  - "register_vector init callback on LongTermMemory._get_pool (Pitfall #1 mitigation for Plan 23-02 $N::vector bindings)"
  - "MemoryFactWriteError typed exception in services/memory/memory_service.py (eng-review A5 placement — NOT in utils/exceptions.py)"
affects: [23-02, 23-05, 24, 25]

tech-stack:
  added: []
  patterns:
    - "Pure-additive idempotent schema migration (ALTER ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS; NO DROP INDEX on long_term_facts)"
    - "pgvector codec registration on asyncpg connection init (mirrors vector_store.py)"
    - "Typed business-error exception co-located with caller (eng-review A5 — no utils/exceptions.py)"
    - "Mock-at-consumer-path pytest discipline (v1.3 D-08) for DDL + pool tests"

key-files:
  created:
    - tests/unit/test_memory_schema.py
    - tests/unit/test_memory_pool.py
  modified:
    - services/memory/memory_service.py

key-decisions:
  - "Lazy 'from config.settings import settings' inside _create_tables (repo convention for circular-import resilience — matches existing _get_pool / ShortTermMemory._get_client lazy-import discipline)"
  - "Module-level 'from pgvector.asyncpg import register_vector' (matches pattern in vector_store.py:136; required so monkeypatch at consumer path can substitute the AsyncMock without raising)"
  - "ALTER TABLE statement on a single line (435 LOC > 426 upper-bound guard, but +9 was driven by exception-class block + register_vector init block; no accidental rewrite)"
  - "DROP INDEX explicitly NOT issued for long_term_facts (PATTERNS.md analog 2 forbids drop-rebuild here)"
  - "No try/except around new DDL (matches existing convention; surface DDL failures at startup)"

patterns-established:
  - "Phase 23 schema-migration shape: CREATE EXTENSION + ALTER ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS (idempotent across restarts)"
  - "pgvector register_vector init callback wiring on LongTermMemory pool (foundation for Plan 23-02 embedding writes + Phase 24 RecallTool reads)"

requirements-completed: [MEM-01]

duration: ~25min
completed: 2026-05-16
---

# Phase 23 Plan 01: Schema Migration Summary

**Added `embedding vector(1024)` column + `ltf_emb_hnsw_idx` HNSW index to `long_term_facts`, wired `register_vector` codec on the LongTermMemory asyncpg pool init, and introduced `MemoryFactWriteError` typed exception — unblocking Plan 23-02 embed-on-write.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-16T07:05:00Z
- **Completed:** 2026-05-16T07:30:40Z
- **Tasks:** 2 (Wave-0 RED + GREEN)
- **Files modified:** 3 (1 production + 2 new tests)

## Accomplishments

- TDD RED gate: 4 failing tests committed before any production change (DDL idempotency × 2, register_vector pool init × 1, MemoryFactWriteError importable × 1).
- TDD GREEN: 4 tests flip green via a bounded 37-insertion / 3-deletion edit to `services/memory/memory_service.py`.
- Pure-additive idempotency confirmed by running `_create_tables()` twice through a fake-pool AsyncMock — no `DROP INDEX` issued on `long_term_facts`.
- `register_vector` codec registration now fires on every connection acquired from the LongTermMemory pool, satisfying the Pitfall #1 prerequisite for the Plan 23-02 `$N::vector` binding inside `save_fact`.

## Task Commits

1. **Task 1 (RED): Wave-0 test scaffolding** — `25eecce` (test)
2. **Task 2 (GREEN): _create_tables + _get_pool + MemoryFactWriteError** — `71f8e1e` (feat)

Plan metadata commit follows separately (SUMMARY + STATE + ROADMAP).

## Files Created/Modified

- `services/memory/memory_service.py` — module-level `from pgvector.asyncpg import register_vector`, `MemoryFactWriteError` class, `_init_conn` callback in `_get_pool` (passed via `init=_init_conn` kwarg), 3 new `conn.execute` calls in `_create_tables` (CREATE EXTENSION + ALTER + HNSW INDEX). 401 → 435 LOC.
- `tests/unit/test_memory_schema.py` (created) — `test_create_tables_idempotent`, `test_hnsw_index_uses_settings_embedding_dim`, `test_memory_fact_write_error_importable`. Uses fake-pool AsyncMock fixture; concatenates `conn.execute.call_args_list` SQL for substring assertions.
- `tests/unit/test_memory_pool.py` (created) — `test_register_vector_init`. Patches `services.memory.memory_service.asyncpg.create_pool` + `services.memory.memory_service.register_vector` at consumer path; stubs `mem._create_tables` to short-circuit the `_get_pool` → `_create_tables` → `_get_pool` re-entry path.

## Decisions Made

- **`register_vector` imported at module level** (not lazy inside `_get_pool`). Matches `services/vectorizer/vector_store.py` convention and enables `monkeypatch.setattr("services.memory.memory_service.register_vector", AsyncMock())` in tests. The verifier-style lazy-import pattern in PATTERNS.md was a suggestion, not a hard constraint; the consumer-path-mocking discipline (v1.3 D-08) is the binding constraint, and module-level import is what makes it work cleanly.
- **`settings.embedding_dim` lazy-imported inside `_create_tables`**. Matches the existing `ShortTermMemory._get_client` + `LongTermMemory._get_pool` pattern in the same file. Avoids hoisting `config.settings` to module top (circular-import risk per PATTERNS.md §Lazy `from config.settings import settings`).
- **`MemoryFactWriteError` subclasses `Exception` (not `BaseException`)**. v1.3 Phase 12 `BaseException` rule is scoped to asyncio.gather isolation; this is a typed business error that callers handle via try/except, so the standard `Exception` parent is correct.

## Deviations from Plan

### Adjustments

**1. [Rule 3 — Test stub] `mem._create_tables` stubbed in `test_register_vector_init`**
- **Found during:** Task 1 (RED test authoring)
- **Issue:** `_get_pool` calls `self._create_tables()` after pool creation, which re-enters `_get_pool` (already non-None at that point, so it returns the sentinel mock). The sentinel mock's `acquire()` is not async-context-manager-shaped, causing the second `_create_tables` call to raise inside the awaited `pool.acquire().__aenter__`.
- **Fix:** Stub `mem._create_tables` to a no-op coroutine before calling `mem._get_pool()`. The test is focused on pool-init wiring (register_vector callback), not DDL — the DDL is covered by `test_create_tables_idempotent` separately.
- **Files modified:** `tests/unit/test_memory_pool.py`
- **Verification:** Test now passes GREEN; assertion on `register_vector_mock.assert_awaited_once_with(dummy_conn)` confirms the callback wiring.
- **Committed in:** `25eecce` (Task 1 commit)

**2. [Rule 3 — Acceptance criterion adjustment] HNSW DDL split across 3 lines**
- **Found during:** Task 2 (post-edit grep verification)
- **Issue:** PLAN acceptance criterion expects `vector_cosine_ops` line to ALSO contain `USING hnsw` + `m = 16` + `ef_construction = 64` — would force the DDL onto one ugly long line.
- **Fix:** Left the DDL as a 3-line triple-quoted SQL block (matches `services/vectorizer/vector_store.py:181-184` precedent). Verification is instead validated by `test_create_tables_idempotent`, which concatenates all `conn.execute` SQL strings and substring-asserts all 6 tokens (`USING hnsw`, `vector_cosine_ops`, `m = 16`, `ef_construction = 64`, `CREATE INDEX IF NOT EXISTS ltf_emb_hnsw_idx`, the HNSW access method). All 6 assertions pass.
- **Files modified:** `services/memory/memory_service.py`
- **Verification:** Unit test `tests/unit/test_memory_schema.py::test_create_tables_idempotent` PASSED.
- **Committed in:** `71f8e1e` (Task 2 commit)

**3. [Rule 3 — Bounded-edit guard overshoot] Final LOC = 435 (guard upper bound 426)**
- **Found during:** Task 2 (post-edit `wc -l`)
- **Issue:** Plan acceptance criterion sets bounded-edit guard at `401 ± 25 = [376, 426]`. Final file is 435 LOC (+9 over upper bound). Guard intent is to catch accidental rewrites.
- **Root cause:** +34 net insertions: 11 lines (MemoryFactWriteError class + section header + docstring), 7 lines (`_init_conn` callback + `init=_init_conn` kwarg), 13 lines (3 new DDL `conn.execute` calls + comment block).
- **Fix:** No fix needed — every added line traces directly to plan requirements; zero refactor of existing code (only the 3 lines for `_get_pool` create_pool args were modified, and the `_create_tables` body received a single `from config.settings import settings` lazy-import insertion).
- **Verification:** `git diff --stat` shows `1 file changed, 37 insertions(+), 3 deletions(-)` — surgical, not a rewrite.
- **Committed in:** `71f8e1e` (Task 2 commit)

---

**Total deviations:** 3 adjustments (1 test scaffolding, 2 acceptance-criterion calibrations)
**Impact on plan:** None on functionality — all 4 Wave-0 RED gates flip to GREEN; ruff clean; zero new mypy errors. The three deviations are presentation/scope-guard calibrations, not scope creep.

## Issues Encountered

None.

## Self-Check: PASSED

**Files exist:**
- `services/memory/memory_service.py` — FOUND (435 LOC)
- `tests/unit/test_memory_schema.py` — FOUND
- `tests/unit/test_memory_pool.py` — FOUND
- `.planning/phases/23-background-extractor-schema-migration/23-01-SUMMARY.md` — FOUND (this file)

**Commits exist:**
- `25eecce` — `test(23-01): add memory schema + pool RED gates (MEM-01)` — FOUND
- `71f8e1e` — `feat(23-01): MEM-01 schema migration — embedding column + HNSW index + register_vector pool init + MemoryFactWriteError` — FOUND

**Verification gate:**
- `uv run pytest tests/unit/test_memory_schema.py tests/unit/test_memory_pool.py -x -q` → 4 passed ✓
- `uv run ruff check services/memory/memory_service.py` → All checks passed ✓
- `uv run pytest tests/unit/test_memory_service.py tests/unit/test_memory_schema.py tests/unit/test_memory_pool.py -q` → 8 passed (no regression in adjacent test_memory_service.py) ✓
- All 7 grep gates pass: ALTER=1, INDEX=1, vector_cosine_ops=1, register_vector import=1, init=_init_conn=1, DROP INDEX (non-comment)=0, register_vector usage=1

**mypy note:** 17 pre-existing baseline errors (asyncpg missing stubs, untyped `_get_pool`/`_get_client`, missing dict generics on dataclasses). Zero new errors introduced by this plan — `pgvector.asyncpg` import has the same `missing library stubs` shape as the existing `vector_store.py:136` import.

## Next Plan Readiness

Plan 23-02 (`save_fact` embed-on-write) can now proceed:
- `embedding` column exists on `long_term_facts` — INSERT can land the vector.
- `register_vector` codec registered on the pool — `$N::vector` binding will resolve.
- `MemoryFactWriteError` importable — Plan 23-02 has its typed-exception surface ready.

No blockers for Plan 23-03 (extractor) — that plan is independent of MEM-01 (Wave 1 parallel).

---
*Phase: 23-background-extractor-schema-migration*
*Completed: 2026-05-16*
