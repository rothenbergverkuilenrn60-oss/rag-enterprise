# Phase 1: pgvector Foundation — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-21
**Phase:** 01-pgvector-foundation
**Areas discussed:** ParentChunk interface (PG-05), RLS implementation pattern, Parent chunk storage schema, Qdrant removal scope

---

## ParentChunk Interface (PG-05)

| Option | Description | Selected |
|--------|-------------|----------|
| Extend BaseVectorStore ABC | Add upsert_parent_chunks / fetch_parent_chunks as abstract methods. All backends forced to implement stubs. Unified interface, no isinstance guards in retriever. | ✓ |
| Separate ParentChunkStore Protocol | New Protocol class. PgVectorStore and QdrantVectorStore implement it; Chroma doesn't. Retriever checks isinstance before calling. | |
| You decide | Claude picks given existing code. | |

**User's choice:** Extend BaseVectorStore ABC
**Notes:** Simpler retriever code — no isinstance guards needed.

---

## RLS Implementation Pattern

| Option | Description | Selected |
|--------|-------------|----------|
| SET LOCAL inside each transaction | Wrap every upsert/search in explicit transaction; SET LOCAL app.current_tenant = $1 resets at transaction end. Safe for pool reuse. | ✓ |
| asyncpg pool init callback | Set at connection creation time. Does not work for multi-tenant pooling — setting is fixed per-connection. | |
| WHERE clause only (no RLS) | Keep existing WHERE tenant_id filter. No DB-level enforcement. | |

**User's choice:** SET LOCAL inside each transaction
**Notes:** State.md flagged asyncpg pool compatibility with RLS as an open question — this resolves it.

---

## Parent Chunk Storage Schema

| Option | Description | Selected |
|--------|-------------|----------|
| Separate table {table}_parent | CREATE TABLE with (chunk_id, doc_id, content, metadata JSONB). No vector column — ID fetch only. Mirrors Qdrant separate collection model. | ✓ |
| Same table, NULL vector | Add is_parent BOOL, NULL embedding. Simpler but pollutes ANN index. | |
| You decide | Claude picks given retriever code. | |

**User's choice:** Separate table {table}_parent
**Notes:** Retriever already uses `settings.qdrant_collection + "_parent"` as collection name — maps directly to table name.

---

## Qdrant Removal Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Full removal — code + dep | Remove QdrantVectorStore, all Qdrant imports, qdrant-client from requirements.txt. Clean break. | ✓ |
| Keep as disabled fallback | Keep class and dep, switch default to pgvector. Rollback easier but maintenance burden. | |
| Remove code, keep dep | Remove class but keep qdrant-client in requirements. | |

**User's choice:** Full removal — code + dep
**Notes:** PG-01 success criteria: "Qdrant is no longer referenced at runtime." Full removal satisfies this literally.

---

## Claude's Discretion

- HNSW index parameters: m=16, ef_construction=64 (standard pgvector recommendations)
- work_mem mechanism: `server_settings={"work_mem": "256MB"}` in asyncpg.create_pool()
- asyncpg pool sizing: keep existing min_size=2

## Deferred Ideas

None.
