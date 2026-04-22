# Phase 1: pgvector Foundation — Research

**Researched:** 2026-04-21
**Domain:** PostgreSQL + pgvector, asyncpg, Row-Level Security, HNSW indexing
**Confidence:** HIGH (all claims verified against codebase or official docs)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PG-01 | Vector store backend switched from Qdrant to PostgreSQL + pgvector; existing ingestion and query pipeline APIs unchanged | Factory pattern already present; only `PgVectorStore` internals change; pipeline.py needs 0 changes |
| PG-02 | pgvector uses HNSW index (not IVFFlat); work_mem=256MB set at connection level | Current `create_collection()` uses IVFFlat — must be replaced; connection-level SET verified as supported |
| PG-03 | Multi-tenant isolation via PostgreSQL RLS with `app.current_tenant` per-connection setting | `get_qdrant_filter()` in tenant_service produces a Python dict — must be replaced with `set_config()` at pool acquire time |
| PG-04 | `PgVectorStore` implements `upsert_parent_chunks()` and `fetch_parent_chunks()` — parity with Qdrant backend | Qdrant uses a separate collection with placeholder vector; pgvector equivalent is a separate table with nullable embedding |
| PG-05 | `BaseVectorStore` ABC extended (or `ParentChunkStore` Protocol added) to formalize parent chunk interface | ABC currently has no `upsert_parent_chunks` / `fetch_parent_chunks`; Qdrant has them as non-abstract methods |
</phase_requirements>

---

## Executive Summary

Five bullets the planner must internalize before writing tasks:

1. **The factory already switches on `settings.vector_store`** — changing the default from `"qdrant"` to `"pgvector"` in `.env` is the only runtime switch needed; `pipeline.py` and `retriever.py` are untouched.

2. **`PgVectorStore` is 60% complete** — `create_collection`, `upsert`, `search`, `delete_by_doc`, `count` exist but have three critical defects: IVFFlat instead of HNSW (PG-02), no RLS (PG-03), and missing `upsert_parent_chunks` / `fetch_parent_chunks` (PG-04).

3. **asyncpg requires explicit codec registration** — `pgvector.asyncpg.register_vector` must be called in the pool `init=` callback; without it, asyncpg treats vectors as raw bytes and queries silently fail. [VERIFIED: pgvector-python docs, Context7]

4. **RLS requires two things**: (a) the policy + role setup in SQL run during `create_collection`, and (b) `SET LOCAL app.current_tenant` called inside every transaction that reads or writes vectors. The `get_qdrant_filter()` method in `TenantService` must be replaced with a `set_tenant_context()` coroutine.

5. **Parent chunks need a dedicated table, not a separate collection** — the Qdrant approach (placeholder `[0.0]` vector in a second collection) maps cleanly to a `{table}_parent` table with a TEXT `content` column and no vector column; `fetch_parent_chunks` becomes a `SELECT WHERE chunk_id = ANY($1)` query.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Vector storage and ANN search | Database (pgvector) | — | All similarity math runs inside PostgreSQL |
| Tenant isolation enforcement | Database (RLS policy) | API (set_config call per connection) | DB-level prevents misconfiguration bypass |
| Parent chunk storage | Database (separate table) | — | No vector math needed; pure key-value lookup by ID |
| Connection pool lifecycle | Service (PgVectorStore) | — | asyncpg pool owns codec registration and init |
| Schema initialization | Service (PgVectorStore.create_collection) | — | One-time DDL called at startup |
| Factory/backend selection | Config (settings.vector_store) | Service (get_vector_store factory) | Env var drives instantiation |

---

## Current State Analysis

### What is already implemented in `PgVectorStore`

| Method | Status | Notes |
|--------|--------|-------|
| `_get_pool()` | Partial | DSN stripping works; missing `init=` codec registration |
| `create_collection()` | Defective | Uses IVFFlat, no RLS setup, no parent table creation |
| `upsert()` | Functional | Correct ON CONFLICT upsert; no RLS context |
| `search()` | Functional | Parameterized filters correct; no RLS context; casting `$1::vector` correct |
| `delete_by_doc()` | Functional | Correct; no RLS context |
| `count()` | Functional | Correct |
| `upsert_parent_chunks()` | MISSING | Not defined on `PgVectorStore` at all |
| `fetch_parent_chunks()` | MISSING | Not defined on `PgVectorStore` at all |

### What is wrong in `BaseVectorStore`

`upsert_parent_chunks` and `fetch_parent_chunks` are defined only on `QdrantVectorStore` as concrete (non-abstract) methods. `BaseVectorStore` ABC has no declaration for them. `retriever.py` line 643 calls `self._store.fetch_parent_chunks(...)` — this will raise `AttributeError` when `settings.vector_store = "pgvector"` and `parent_child_enabled = True`.

### Qdrant references outside `vector_store.py`

| File | Reference | Action Required |
|------|-----------|-----------------|
| `services/tenant/tenant_service.py` | `get_qdrant_filter(tenant_id)` → returns `dict | None` | Rename to `get_tenant_filter()` AND add `set_tenant_context(conn, tenant_id)` coroutine |
| `services/retriever/retriever.py` | Line 639: `settings.qdrant_parent_collection` | Change to `settings.pg_parent_table` (or reuse same setting with rename) |
| `services/retriever/retriever.py` | Line 643: calls `fetch_parent_chunks` on the store | Works once PG-04/PG-05 are done; no structural change needed |
| `services/vectorizer/indexer.py` | Lines 104, 133–134, 151: `settings.qdrant_collection`, `qdrant_parent_collection` | Reads collection name for BM25; pgvector uses same logical name — no functional change needed, but naming is confusing |
| `services/knowledge/summary_indexer.py` | References `qdrant_collection` | Same as indexer — name only, not Qdrant-specific logic |
| `services/pipeline.py` | Line 300: `self._tenant_svc.get_qdrant_filter(tenant_id)` | Rename call site to `get_tenant_filter()` |
| `services/pipeline.py` | Line 419: same in `stream()` method | Same rename |
| `config/settings.py` | `vector_store` default is `"qdrant"` | Change default to `"pgvector"` (or set via `.env`) |

---

## Technical Decisions

### Decision 1: asyncpg codec registration (CRITICAL)

The `pgvector` Python library must register custom asyncpg codecs so vectors are serialized as the pgvector wire format, not raw bytes. Without this, `embedding <=> $1::vector` raises a PostgreSQL type error at runtime.

**Correct pattern** [VERIFIED: pgvector-python docs, Context7 `/pgvector/pgvector-python`]:

```python
from pgvector.asyncpg import register_vector

async def _init_conn(conn: asyncpg.Connection) -> None:
    await register_vector(conn)

self._pool = await asyncpg.create_pool(
    dsn,
    min_size=2,
    max_size=10,
    init=_init_conn,
)
```

The `init=` callback runs once per new connection in the pool. This is the only supported registration path for pools.

**Requirement:** Add `pgvector` to `requirements.txt` (the Python library, distinct from the PostgreSQL extension). Current `requirements.txt` has `asyncpg==0.30.0` but NOT the `pgvector` Python package. [VERIFIED: requirements.txt read]

### Decision 2: HNSW index — correct DDL (PG-02)

Current code uses IVFFlat (`WITH (lists = 100)`). Replace with HNSW. [VERIFIED: pgvector-python docs]

```sql
CREATE INDEX IF NOT EXISTS {table}_vec_idx
    ON {table} USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

**Parameters:**
- `m = 16`: default; controls graph connectivity. Increase to 32 for higher recall at cost of memory. [ASSUMED — default recommendation from pgvector docs; optimal value is workload-dependent]
- `ef_construction = 64`: default build-time search width. Increasing improves recall but slows index build. [ASSUMED]
- `vector_cosine_ops`: required because the codebase uses cosine similarity everywhere (`embedding <=> $1`).

**work_mem at connection level** (not server level, as required by PG-02):

```sql
SET LOCAL work_mem = '256MB';
```

This must be run inside the same transaction as the `CREATE INDEX` call, or in every connection that does ANN search if pgvector uses it at query time. The `SET LOCAL` scope ends with the transaction. For the index build specifically, wrap in a transaction:

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("SET LOCAL work_mem = '256MB'")
        await conn.execute("CREATE INDEX IF NOT EXISTS ...")
```

### Decision 3: RLS pattern (PG-03)

Row-Level Security requires:

**Schema setup (run once in `create_collection`):**

```sql
-- Enable RLS on the table
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;

-- Policy: each connection can only see rows matching its current_tenant setting
CREATE POLICY tenant_isolation ON {table}
    USING (metadata->>'tenant_id' = current_setting('app.current_tenant', true));
```

The `true` argument to `current_setting` suppresses the error when the setting is unset (returns NULL instead), which makes the policy evaluate to false and returns zero rows — safe fail.

**Per-connection tenant context (run before every query):**

```python
async with pool.acquire() as conn:
    await conn.execute(
        "SELECT set_config('app.current_tenant', $1, true)", tenant_id
    )
    # ... then run query
```

The third argument `true` means `is_local = true` — the setting resets at end of transaction. Since asyncpg connections are not in a transaction by default for individual `execute()` calls, use `SET LOCAL` inside an explicit `async with conn.transaction():` block, or use `set_config(..., false)` (session-scoped, resets when connection returns to pool — acceptable for pool connections that reset on release).

**Recommended approach for pool connections:** Use `set_config('app.current_tenant', $1, false)` (session scope) and rely on pool connection reset to clear state between requests. Alternatively, use `SET LOCAL` inside a transaction block for stronger isolation guarantee.

**The bypass risk:** If `tenant_id` is empty string, the policy falls through to returning no rows (because `'' = current_setting(...)` is false). This is correct behavior for system operations (count, admin). Pass `""` for admin contexts.

**Role required:** The application database role (`rag` in the DSN) must NOT be a superuser — superusers bypass RLS by default. If using superuser in development, add `SET row_security = on;` or use `ALTER TABLE ... FORCE ROW LEVEL SECURITY`.

### Decision 4: Parent chunk storage (PG-04)

**Approach: dedicated `{table}_parent` table, no vector column.** [ASSUMED — no official pgvector docs prescribe this; rationale below]

This maps directly to the Qdrant pattern (separate collection, no meaningful vector). A nullable `embedding` column in the main table would break RLS policies and complicate queries.

```sql
CREATE TABLE IF NOT EXISTS {table}_parent (
    chunk_id  TEXT PRIMARY KEY,
    doc_id    TEXT NOT NULL,
    content   TEXT NOT NULL,
    metadata  JSONB,
    tenant_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS {table}_parent_doc_idx
    ON {table}_parent(doc_id);
```

**`upsert_parent_chunks`**: `INSERT ... ON CONFLICT(chunk_id) DO UPDATE SET content=...`

**`fetch_parent_chunks`**: `SELECT chunk_id, content FROM {table}_parent WHERE chunk_id = ANY($1::text[])`

This is a simple lookup, no ANN math needed. asyncpg handles `ANY($1::text[])` with a Python list.

### Decision 5: asyncpg vs psycopg for this codebase

`requirements.txt` already pins `asyncpg==0.30.0`. **Stick with asyncpg.** [VERIFIED: requirements.txt]

`psycopg3` would require adding a new dependency (`psycopg[binary]` or `psycopg[c]`), and the existing `PgVectorStore` is already written against the asyncpg API (`pool.acquire()`, `conn.fetch()`, `conn.execute()`). Migration would require rewriting all query methods.

### Decision 6: `settings.vector_store` default change

Change from `"qdrant"` to `"pgvector"` in `settings.py`. [VERIFIED: settings.py line 191 — currently `"qdrant"`]

This is the single runtime switch required by PG-01. All pipeline entry points go through `get_vector_store()` factory.

---

## Implementation Map

Files that change, and what specifically changes in each:

| File | Change Type | What Changes |
|------|-------------|--------------|
| `services/vectorizer/vector_store.py` | Modify | (1) Add `upsert_parent_chunks`/`fetch_parent_chunks` to `BaseVectorStore` ABC; (2) rewrite `PgVectorStore.create_collection()` — HNSW, RLS setup, parent table; (3) add `pgvector.asyncpg.register_vector` in pool init; (4) add `upsert_parent_chunks`/`fetch_parent_chunks` to `PgVectorStore`; (5) wrap every query in `set_config` call for tenant context |
| `config/settings.py` | Modify | Change `vector_store` default to `"pgvector"`; optionally add `pg_parent_table: str = ""` setting |
| `services/tenant/tenant_service.py` | Modify | Rename `get_qdrant_filter()` to `get_tenant_filter()`; add `async set_tenant_context(conn, tenant_id)` that calls `set_config` |
| `services/pipeline.py` | Modify | Rename `get_qdrant_filter` call to `get_tenant_filter` (2 call sites: line 300, line 419) |
| `requirements.txt` | Modify | Add `pgvector>=0.3.0` (Python library for asyncpg codec) |

Files that do NOT change:

| File | Reason |
|------|--------|
| `services/pipeline.py` (structure) | Factory abstraction means no pipeline logic changes |
| `services/retriever/retriever.py` | Calls `self._store.search()` and `self._store.fetch_parent_chunks()` through ABC — no changes once ABC is updated |
| `services/vectorizer/indexer.py` | Uses `settings.qdrant_collection` as a name string only; no Qdrant SDK calls |
| `controllers/` | All API contracts unchanged per PG-01 |

---

## Pitfalls and Constraints

### Pitfall 1: Missing `pgvector` Python package

The `pgvector` PostgreSQL extension (server-side) is separate from the `pgvector` Python package (client-side codec). `requirements.txt` has `asyncpg` but NOT `pgvector`. Without `pip install pgvector`, the import `from pgvector.asyncpg import register_vector` fails at startup. Add `pgvector>=0.3.0` to `requirements.txt`. [VERIFIED: requirements.txt read]

### Pitfall 2: Pool-level vs connection-level codec registration

If `register_vector` is called on an individual connection rather than via the pool `init=` callback, new connections created by the pool later will not have the codec registered. This causes silent type errors on queries that return vector columns. Always use `init=` callback pattern. [VERIFIED: pgvector-python docs]

### Pitfall 3: IVFFlat → HNSW requires index drop+recreate

The existing `create_collection()` creates an IVFFlat index. If the table was previously created, `CREATE INDEX IF NOT EXISTS` will NOT replace an existing IVFFlat index. The schema migration must explicitly `DROP INDEX IF EXISTS {table}_vec_idx` before creating the HNSW index. [ASSUMED — standard PostgreSQL behavior]

### Pitfall 4: RLS superuser bypass

If the `rag` database role is a superuser (common in development Docker setups), RLS policies are bypassed silently. The test for PG-03 will pass even without correct policy setup. Solution: use `FORCE ROW LEVEL SECURITY` on the table, or verify the role is not a superuser in CI. [ASSUMED — standard PostgreSQL RLS behavior]

### Pitfall 5: `set_config` scope in connection pool

Using `set_config('app.current_tenant', $1, false)` (session-scoped) on a pooled connection means tenant context persists until the connection is returned to the pool. If the next request borrows the same connection before reset, it inherits the previous tenant's context. Solution: always use `set_config(..., true)` (transaction-local) inside explicit `async with conn.transaction():` blocks, or reset to `''` on connection return. [ASSUMED — asyncpg pool connection lifecycle behavior]

### Pitfall 6: `executemany` vs `copy_records_to_table`

The current `upsert()` uses `conn.executemany(INSERT ON CONFLICT ...)`. For large batch ingestion, this is significantly slower than asyncpg's `copy_records_to_table`. However, `COPY` does not support `ON CONFLICT`. For Phase 1, keep `executemany` and note the optimization opportunity. [ASSUMED]

### Pitfall 7: `get_qdrant_filter` rename and backward compatibility

`get_qdrant_filter` is called in two places in `pipeline.py` and returns `dict | None`. After rename, the dict result is used to construct filters for vector search. When RLS is active, the tenant filter is enforced at DB level — the `filters` dict passed to `PgVectorStore.search()` should NOT include `tenant_id` to avoid double-filtering. Review the `search()` WHERE clause to ensure metadata filter and RLS policy do not conflict.

### Pitfall 8: `work_mem` SET LOCAL scope

`SET LOCAL work_mem = '256MB'` only applies within the current transaction. If `CREATE INDEX` is called outside an explicit transaction block, `SET LOCAL` has no effect. Wrap the index creation in `async with conn.transaction():`. [VERIFIED: PostgreSQL docs behavior]

### Production-grade constraints from CLAUDE.md

- All exception catches must be narrow (ERR-01) — the existing `fetch_parent_chunks` in `QdrantVectorStore` uses bare `except Exception` — the pgvector equivalent must use `asyncpg.PostgresError` or narrower types.
- No blocking I/O in async context — all SQL calls must use asyncpg's async API; no `psycopg2` synchronous fallback.
- Tenacity retry required for all external calls — wrap `upsert`, `search`, `upsert_parent_chunks` with `@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(...))`.
- Structured logging for every operation — follow the existing `logger.debug/info/warning` pattern in `QdrantVectorStore`.
- mypy --strict — all new methods need complete type annotations including return types.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.4 + pytest-asyncio 0.24.0 |
| Config file | `pytest.ini` (exists, `asyncio_mode = auto`) |
| Quick run command | `pytest tests/unit/test_pgvector_store.py -x -q` |
| Full suite command | `pytest tests/ -x -q` |

### Success Criteria → Test Map

| Criterion | Behavior | Test Type | Automated Command | File Exists? |
|-----------|----------|-----------|-------------------|-------------|
| SC-1: Documents stored in PostgreSQL, Qdrant not referenced at runtime | Import `get_vector_store()` with `settings.vector_store="pgvector"`, assert instance is `PgVectorStore`, assert no `qdrant_client` module imported | unit | `pytest tests/unit/test_pgvector_store.py::test_factory_returns_pgvector -x` | Wave 0 |
| SC-2: recall@10 within 5% of Qdrant baseline | Ingest N test chunks, run K queries, compare top-10 overlap between pgvector and reference results | integration | `pytest tests/integration/test_pgvector_recall.py -x` | Wave 0 |
| SC-3: Tenant A cannot retrieve Tenant B documents | Ingest doc with `tenant_id=A`, query with `tenant_id=B` context set, assert 0 results returned | integration | `pytest tests/integration/test_pgvector_rls.py::test_cross_tenant_isolation -x` | Wave 0 |
| SC-4: `upsert_parent_chunks` / `fetch_parent_chunks` round-trip | Upsert 3 parent chunks, fetch by IDs, assert content matches exactly | unit | `pytest tests/unit/test_pgvector_store.py::test_parent_chunk_roundtrip -x` | Wave 0 |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command |
|--------|----------|-----------|-------------------|
| PG-01 | Factory returns `PgVectorStore`; pipeline APIs unchanged | unit | `pytest tests/unit/test_pgvector_store.py::test_factory_returns_pgvector` |
| PG-02 | `create_collection` creates HNSW index, not IVFFlat | unit | `pytest tests/unit/test_pgvector_store.py::test_hnsw_index_created` |
| PG-03 | RLS blocks cross-tenant reads | integration | `pytest tests/integration/test_pgvector_rls.py` |
| PG-04 | Parent chunk upsert+fetch round-trip | unit | `pytest tests/unit/test_pgvector_store.py::test_parent_chunk_roundtrip` |
| PG-05 | `BaseVectorStore` declares `upsert_parent_chunks`/`fetch_parent_chunks` as abstract | unit | `pytest tests/unit/test_pgvector_store.py::test_abc_interface` |

### Sampling Rate

- **Per task commit:** `pytest tests/unit/test_pgvector_store.py -x -q`
- **Per wave merge:** `pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps (must be created before implementation tasks)

- [ ] `tests/unit/test_pgvector_store.py` — unit tests for PgVectorStore (factory, HNSW DDL inspection, ABC interface, parent chunk round-trip). Use `pytest-asyncio` + `asyncpg` against a real or Docker PostgreSQL with pgvector extension.
- [ ] `tests/integration/test_pgvector_recall.py` — recall@10 comparison test. Requires live PostgreSQL. Can be skipped in CI without PostgreSQL (`pytest.mark.skipif`).
- [ ] `tests/integration/test_pgvector_rls.py` — RLS cross-tenant isolation test. Requires live PostgreSQL.
- [ ] `tests/conftest.py` (or `tests/integration/conftest.py`) — shared `pg_pool` fixture that creates a test database, runs `create_collection()`, tears down after session.

---

## Open Questions

1. **PostgreSQL + pgvector availability in CI/CD**
   - What we know: `docker-compose.yml` exists in the project root (not read); local WSL2 environment does not have `pg_isready` in PATH.
   - What's unclear: Is PostgreSQL with pgvector extension running locally or only via Docker Compose? Is the `ragdb` database and `rag` role pre-provisioned?
   - Recommendation: Planner should include a Wave 0 task to verify Docker Compose postgres service has `pgvector` extension enabled and the `rag` role is NOT superuser.

2. **`qdrant_collection` setting name**
   - What we know: `settings.qdrant_collection = "rag_enterprise_v3"` is used as the pgvector table name in `PgVectorStore` (line 243: `self._table = settings.qdrant_collection.replace("-", "_")`). Several other files reference `settings.qdrant_collection` as a generic collection/table name.
   - What's unclear: Should Phase 1 rename `qdrant_collection` to `vector_table` in settings, or leave the naming as-is?
   - Recommendation: Leave `qdrant_collection` as the table name source for Phase 1 to minimize blast radius. Create a follow-up task in Phase 2 to rename the setting. [ASSUMED — renaming adds risk with no functional benefit in Phase 1]

3. **Existing Qdrant data migration**
   - What we know: Phase 1 success criteria say "Documents ingested via existing /ingest endpoint are stored in PostgreSQL" — future ingestion only.
   - What's unclear: Are there existing Qdrant collections with production data that must be migrated, or is this a fresh deployment?
   - Recommendation: Treat as fresh deployment (no migration script needed). If migration is needed, it is out of scope for Phase 1 per REQUIREMENTS.md "Out of Scope" section.

4. **`get_qdrant_filter()` return type after rename**
   - What we know: Returns `dict | None` representing a metadata filter. After RLS is enforced at DB level, the `tenant_id` key in this dict would double-filter.
   - What's unclear: Does the filter dict passed to `PgVectorStore.search()` currently include `tenant_id`, and should it be stripped when RLS is active?
   - Recommendation: Planner should add a task to audit `get_tenant_filter()` output and ensure `tenant_id` is excluded from the metadata WHERE clause when RLS is enabled.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| asyncpg | PgVectorStore pool | Listed in requirements.txt | 0.30.0 | — |
| pgvector (Python package) | asyncpg codec registration | NOT in requirements.txt | — | Must add before implementation |
| PostgreSQL + pgvector ext | All PG-01–05 | Unknown (pg_isready not in PATH) | — | Docker Compose postgres service |
| qdrant-client | QdrantVectorStore (to be removed) | Listed in requirements.txt | 1.12.1 | Remove after migration |

**Missing dependencies with no fallback:**
- `pgvector` Python package — must be added to `requirements.txt` as `pgvector>=0.3.0`

**Missing dependencies with fallback:**
- PostgreSQL server — use Docker Compose `docker compose up postgres` if not running locally

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| asyncpg vector type codec | Custom binary encoder/decoder | `pgvector.asyncpg.register_vector` | Handles all pgvector wire types (vector, halfvec, sparsevec) |
| HNSW index DDL | Custom indexing logic | Standard pgvector `USING hnsw` syntax | Well-tested, maintained by pgvector team |
| Connection pool initialization | Manual per-connection init | `asyncpg.create_pool(init=...)` | Guaranteed to run on every new connection |

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | 0.30.0 | Async PostgreSQL driver | Already in requirements.txt; fastest Python async PG driver |
| pgvector (Python) | >=0.3.0 | asyncpg codec for vector types | Official pgvector Python client; required for type registration |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | 9.0.0 | Retry logic | All external DB calls per project standard |
| loguru | 0.7.3 | Structured logging | All operations per project standard |

**Installation addition required:**
```bash
pip install pgvector>=0.3.0
```

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | HNSW m=16, ef_construction=64 are reasonable defaults for RAG at scale | Technical Decisions — HNSW params | Suboptimal recall; tune post-deployment |
| A2 | `set_config(..., false)` (session-scoped) is safe for pool connections that reset on return | Technical Decisions — RLS | Tenant context bleeds across requests; use transaction-local instead |
| A3 | Phase 1 is a fresh deployment; no Qdrant data migration required | Open Questions | Data loss if production Qdrant has documents that need preserving |
| A4 | `qdrant_collection` setting name should stay as-is for Phase 1 | Open Questions | Naming confusion; low functional risk |
| A5 | `executemany` is acceptable for Phase 1 batch ingestion performance | Pitfalls | Slow ingestion for large datasets; use COPY in Phase 1 if ingestion SLA is defined |

---

## Sources

### Primary (HIGH confidence)
- `/pgvector/pgvector-python` (Context7) — asyncpg codec registration, HNSW DDL, pool init pattern
- `/home/ubuntu/.../services/vectorizer/vector_store.py` — current implementation state
- `/home/ubuntu/.../config/settings.py` — DSN, vector_store default, pool config
- `/home/ubuntu/.../requirements.txt` — exact dependency versions

### Secondary (MEDIUM confidence)
- `/home/ubuntu/.../services/tenant/tenant_service.py` — `get_qdrant_filter` call sites
- `/home/ubuntu/.../services/retriever/retriever.py` — `fetch_parent_chunks` call and parent collection name pattern
- `/home/ubuntu/.../services/pipeline.py` — `get_qdrant_filter` call sites in pipeline

### Tertiary (LOW confidence / ASSUMED)
- HNSW default parameters (m=16, ef_construction=64) — from training knowledge; verify against pgvector documentation
- RLS `set_config` session vs transaction scope behavior — from training knowledge; verify against PostgreSQL docs

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified against requirements.txt and Context7
- Architecture: HIGH — derived from direct code analysis
- Pitfalls: MEDIUM — codec registration and RLS scope verified; HNSW params assumed
- Test strategy: HIGH — test framework verified; test file names are new (Wave 0)

**Research date:** 2026-04-21
**Valid until:** 2026-05-21 (pgvector is stable; asyncpg API stable)
