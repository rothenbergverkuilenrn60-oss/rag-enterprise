---
phase: 01-pgvector-foundation
plan: "01"
subsystem: test-scaffolding
tags: [pgvector, pytest, tdd, rls, hnsw, recall]
dependency_graph:
  requires: []
  provides:
    - tests/conftest.py: pg_pool and pg_store fixtures for integration tests
    - tests/unit/test_pgvector_store.py: RED-state unit tests for PG-01–PG-05
    - tests/integration/test_pgvector_rls.py: RED-state RLS isolation tests for PG-03
    - tests/integration/test_pgvector_recall.py: RED-state recall@10 gate for SC-2
  affects: []
tech_stack:
  added: [asyncpg, pgvector.asyncpg]
  patterns: [TDD RED-GREEN-REFACTOR, pytest session fixtures, asyncio.run() availability check]
key_files:
  created:
    - tests/conftest.py
    - tests/unit/test_pgvector_store.py
    - tests/integration/test_pgvector_rls.py
    - tests/integration/test_pgvector_recall.py
    - tests/__init__.py
    - tests/unit/__init__.py
    - tests/integration/__init__.py
  modified: []
decisions:
  - "fetch_parent_chunks([]) returns {} without DB connection — fast-path optimization built into test expectation"
  - "recall@10 test uses dim=64 (not full 1024) and isolated table name for speed and isolation"
  - "SC-2 changed from Qdrant-comparison to absolute recall@10 >= 0.95 against brute-force — D-05 removes Qdrant baseline"
  - "DocumentChunk.content_with_header is required (not optional) — sample_chunks fixture includes it"
  - "ChunkMetadata has no tenant_id field — tenant isolation uses PgVectorStore.upsert(tenant_id=) parameter instead"
metrics:
  duration: "~10 minutes"
  completed: "2026-04-21"
  tasks_completed: 4
  tasks_total: 4
  files_created: 7
  files_modified: 0
---

# Phase 01 Plan 01: Test Scaffolding Summary

**One-liner:** pytest test stubs for pgvector TDD — conftest with asyncpg pool, 8 unit tests (RED), RLS isolation tests, and recall@10 quality gate covering all 5 Phase 1 requirements.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | conftest.py with pg_pool and pg_store fixtures | dd4d37f | tests/conftest.py, tests/__init__.py |
| 2 | Unit test stubs for PG-01, PG-02, PG-04, PG-05 | 540051a | tests/unit/test_pgvector_store.py, tests/unit/__init__.py |
| 3 | Integration test stubs for PG-03 (RLS isolation) | ffeed9b | tests/integration/test_pgvector_rls.py, tests/integration/__init__.py |
| 4 | recall@10 baseline test for SC-2 | 88f7ea2 | tests/integration/test_pgvector_recall.py |

## What Was Built

### tests/conftest.py
- `_pg_available()`: checks PostgreSQL reachability at collection time using `asyncio.run()` (not deprecated `get_event_loop()`)
- `pg_pool` (session-scoped): creates asyncpg connection pool with `pgvector.asyncpg.register_vector` codec on every connection
- `pg_store` (function-scoped): instantiates `PgVectorStore`, resets `_store_instance` singleton before and after each test (T-1-00b threat mitigation)
- `PG_AVAILABLE`: module-level flag used by all integration tests for graceful skipif

### tests/unit/test_pgvector_store.py (8 tests, all RED)
- `test_abc_interface` — asserts `upsert_parent_chunks` + `fetch_parent_chunks` are abstract on `BaseVectorStore` (PG-05)
- `test_factory_returns_pgvector` — asserts `get_vector_store()` returns `PgVectorStore` when `vector_store=pgvector` (PG-01)
- `test_hnsw_index_ddl_pattern` — inspects `create_collection` source for HNSW DDL + `work_mem` (PG-02)
- `test_hnsw_rls_ddl_pattern` — inspects `create_collection` source for RLS DDL + `tenant_isolation` policy (PG-03)
- `test_parent_chunk_roundtrip_methods_exist` — asserts `upsert_parent_chunks` + `fetch_parent_chunks` are callable (PG-04)
- `test_parent_chunk_fetch_empty_returns_empty` — asserts `fetch_parent_chunks([])` returns `{}` (PG-04)
- `test_retry_decorator_on_upsert` — asserts tenacity `@retry` on `upsert` (PG-02)
- `test_retry_decorator_on_search` — asserts tenacity `@retry` on `search` (PG-02)

### tests/integration/test_pgvector_rls.py (3 tests, skip without PostgreSQL)
- `test_cross_tenant_isolation` — inserts tenant-a row, queries as tenant-b, expects 0 rows (PG-03)
- `test_same_tenant_can_read_own_data` — queries as tenant-a, expects own row visible (PG-03)
- `test_qdrant_client_not_imported_at_runtime` — asserts no `qdrant_client` in `sys.modules` with pgvector backend (PG-01)

### tests/integration/test_pgvector_recall.py (1 test, skip without PostgreSQL)
- `test_recall_at_10` — 100 unit vectors, brute-force top-10 ground truth, HNSW query, asserts recall@10 >= 0.95 (SC-2)

## Deviations from Plan

### Model Field Adjustments (Rule 1 — Auto-fixed)

**1. [Rule 1 - Bug] DocumentChunk.content_with_header is required**
- **Found during:** Task 2 (reading utils/models.py)
- **Issue:** Plan's sample `DocumentChunk` construction omitted `content_with_header`, which is a required field (not Optional)
- **Fix:** Added `content_with_header` to all `DocumentChunk` instances in fixtures
- **Files modified:** tests/unit/test_pgvector_store.py, tests/integration/test_pgvector_recall.py

**2. [Rule 1 - Bug] ChunkMetadata has no tenant_id field**
- **Found during:** Task 2 (reading utils/models.py)
- **Issue:** Plan's sample fixtures used `ChunkMetadata(tenant_id="tenant-a")` but the model has no such field
- **Fix:** Removed `tenant_id` from `ChunkMetadata` construction; tenant isolation uses `store.upsert(tenant_id=)` parameter per PgVectorStore API
- **Files modified:** tests/unit/test_pgvector_store.py, tests/integration/test_pgvector_recall.py

### TDD Gate Compliance

This plan is entirely in the RED phase — all test files are stubs that MUST FAIL until Plans 02-04 implement the production code. The TDD GREEN gate will be confirmed in plan 01-04 (Factory + Settings).

| Gate | Commit | Status |
|------|--------|--------|
| RED (test commits) | dd4d37f, 540051a, ffeed9b, 88f7ea2 | PASSED — 4 test-only commits |
| GREEN | Plans 02-04 | Pending |

## Known Stubs

All tests are intentional stubs in RED state. This is correct per plan design:

| Stub | File | Reason |
|------|------|--------|
| `test_abc_interface` will FAIL | tests/unit/test_pgvector_store.py | `upsert_parent_chunks`/`fetch_parent_chunks` not yet in ABC (Plan 02 adds them) |
| `test_factory_returns_pgvector` will FAIL | tests/unit/test_pgvector_store.py | `get_vector_store()` returns Qdrant by default (Plan 04 changes default) |
| `test_hnsw_*` will FAIL | tests/unit/test_pgvector_store.py | `create_collection` has no HNSW/RLS DDL yet (Plan 02 rewrites it) |
| `test_parent_chunk_*` will FAIL | tests/unit/test_pgvector_store.py | `upsert_parent_chunks`/`fetch_parent_chunks` not implemented (Plan 02) |
| `test_retry_*` will FAIL | tests/unit/test_pgvector_store.py | `PgVectorStore.upsert`/`search` not yet implemented (Plan 02) |

## Threat Flags

No new security-relevant surface introduced. This plan creates test-only files. The hardcoded `rag:rag@localhost:5432/ragdb` DSN in conftest.py is dev-only per threat model T-1-00a (accepted).

## Self-Check: PASSED

Files verified to exist:
- tests/conftest.py — FOUND (dd4d37f)
- tests/unit/test_pgvector_store.py — FOUND (540051a)
- tests/integration/test_pgvector_rls.py — FOUND (ffeed9b)
- tests/integration/test_pgvector_recall.py — FOUND (88f7ea2)

Commits verified:
- dd4d37f — test(01-01): add conftest.py with pg_pool and pg_store fixtures
- 540051a — test(01-01): add unit test stubs for PG-01, PG-02, PG-03, PG-04, PG-05 (RED)
- ffeed9b — test(01-01): add RLS integration test stubs for PG-03 (RED)
- 88f7ea2 — test(01-01): add recall@10 quality gate test for SC-2 (RED)

Syntax verified: all 4 test files pass `ast.parse()` check.
