# Phase 1: pgvector Foundation — Context

**Gathered:** 2026-04-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Ingest and query pipelines run entirely on pgvector with HNSW index and RLS tenant isolation. Qdrant is eliminated at runtime (code + dependency removed). Zero API contract changes — existing `/ingest` and `/query` endpoint shapes are preserved.

</domain>

<decisions>
## Implementation Decisions

### PG-05: Parent Chunk Interface
- **D-01:** Extend `BaseVectorStore` ABC with `upsert_parent_chunks` and `fetch_parent_chunks` as abstract methods. All backends (Chroma, future) must implement stubs. Unified interface — retriever code needs no `isinstance` guards.

### RLS Tenant Isolation (PG-03)
- **D-02:** Enforce RLS using `SET LOCAL app.current_tenant = $1` inside an explicit transaction wrapping every `upsert` and `search` call. The setting resets automatically at transaction end — safe for asyncpg connection pool reuse with no cross-tenant leakage risk.
- **D-03:** PostgreSQL RLS policy is the enforcement layer; the existing WHERE-clause tenant filter in `search()` is a defense-in-depth complement, not a replacement.

### Parent Chunk Storage Schema (PG-04)
- **D-04:** Store parent chunks in a separate PostgreSQL table `{table}_parent` with columns `(chunk_id TEXT PRIMARY KEY, doc_id TEXT, content TEXT, metadata JSONB)`. No vector column — parent chunks are fetched by ID only, never by ANN search. Matches Qdrant's separate collection model; retriever code already uses `settings.qdrant_collection + "_parent"` as the collection name, which maps directly to the table name.

### Qdrant Removal Scope (PG-01)
- **D-05:** Full removal. Remove `QdrantVectorStore` class, all Qdrant imports from `vector_store.py`, and `qdrant-client` from `requirements.txt`. Factory retains only `pgvector` and `chroma` backends. `vector_store` setting default switches to `"pgvector"`.

### HNSW + work_mem (PG-02)
- **D-06:** Claude's discretion on `work_mem` — set `256MB` via asyncpg pool `server_settings` parameter at pool creation, which sets it for all connections in the pool. This is per-connection and correct for index operations.
- **D-07:** HNSW index on the main table uses `CREATE INDEX IF NOT EXISTS ... USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)`. Current `create_collection()` likely uses `ivfflat` or plain btree for vec_idx — must be corrected.

### Claude's Discretion
- HNSW index parameters (`m`, `ef_construction`) — use standard pgvector recommendations (m=16, ef_construction=64)
- asyncpg pool sizing (min_size=2, max_size=10) — keep existing values
- `work_mem` setting mechanism — `server_settings={"work_mem": "256MB"}` in `create_pool()`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` — PG-01 through PG-05 with acceptance criteria
- `.planning/ROADMAP.md` §Phase 1 — success criteria and phase boundary

### Project Context
- `.planning/PROJECT.md` — constraints (no runtime stack changes, API compatibility)
- `.planning/STATE.md` — key decisions logged, pitfalls to avoid (IVFFlat, RLS leakage, asyncpg pool)

### Key Source Files
- `services/vectorizer/vector_store.py` — `BaseVectorStore` ABC + `PgVectorStore` (incomplete) + `QdrantVectorStore` (to be removed)
- `services/pipeline.py` — `IngestionPipeline`, `QueryPipeline` — must not change their public API
- `services/retriever/retriever.py` — calls `upsert_parent_chunks` / `fetch_parent_chunks`; uses `settings.qdrant_collection + "_parent"` as parent collection name
- `config/settings.py` — `pg_dsn`, `vector_store`, `qdrant_collection`, `embedding_dim`, `qdrant_parent_collection`

No external ADRs or specs — requirements fully captured in decisions above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PgVectorStore._get_pool()`: asyncpg pool setup exists — extend with `server_settings={"work_mem": "256MB"}` and fix HNSW index in `create_collection()`
- `PgVectorStore.search()`: WHERE clause tenant filtering already present — add `SET LOCAL` RLS inside a transaction
- `QdrantVectorStore.upsert_parent_chunks()` / `fetch_parent_chunks()`: Qdrant implementations serve as the behavioral spec for the PG equivalents
- `utils/cache.py`: Redis pool pattern — mirrors the singleton pool pattern used in `PgVectorStore._get_pool()`

### Established Patterns
- Global singleton factories (`get_vector_store()`, `get_ingest_pipeline()`) — `PgVectorStore` follows the same pattern
- `tenacity` retry decorators on all external calls — apply to `upsert_parent_chunks` and `fetch_parent_chunks`
- `log_latency` decorator — apply to new PgVectorStore methods consistent with existing methods
- Structured logging via `loguru` — `logger.info/debug/warning` at every operation boundary

### Integration Points
- `retriever.py:_expand_to_parent()` calls `self._store.fetch_parent_chunks(parent_ids, parent_col)` — `parent_col` is `settings.qdrant_collection + "_parent"`; this naming carries over to the PG table name
- `main.py` lifespan calls `vectorizer.ensure_collection()` → `_store.count()` — both must work with PgVectorStore
- `config/settings.py`: `vector_store` default must change from `"qdrant"` to `"pgvector"`; `qdrant_parent_collection` field name is misleading but can stay for now (it drives the parent table name)

</code_context>

<specifics>
## Specific Requirements

- `SET LOCAL app.current_tenant = $1` inside explicit `async with conn.transaction()` block — not connection-level SET
- Parent table name: `{self._table}_parent` (derived from `settings.qdrant_collection.replace("-", "_") + "_parent"`)
- HNSW params: `m=16, ef_construction=64, vector_cosine_ops`
- `work_mem='256MB'` via `asyncpg.create_pool(..., server_settings={"work_mem": "256MB"})`
- No API shape changes — `IngestionPipeline.run()` and `QueryPipeline.run()` signatures unchanged

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-pgvector-foundation*
*Context gathered: 2026-04-21*
