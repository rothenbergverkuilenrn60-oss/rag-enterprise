# Architecture Research

## Summary

The codebase already has a `BaseVectorStore` ABC with a pgvector backend — it's incomplete (two missing methods) and uses a single global singleton (breaks multi-tenancy). The migration is a completion task, not a rewrite. Image extraction belongs in Stage 2 of the ingestion pipeline alongside existing text/table/OCR extraction. Async task tracking maps cleanly to existing Redis infrastructure with a `job:{id}` key pattern.

## Vector Store Abstraction Layer

**Already exists:** `services/vectorizer/vector_store.py` defines `BaseVectorStore` ABC with `QdrantVectorStore`, `PgVectorStore`, and `ChromaVectorStore` implementations.

**`PgVectorStore` is incomplete — two missing methods:**

`upsert_parent_chunks()` and `fetch_parent_chunks()` are called by the retriever but only implemented on `QdrantVectorStore`. They are not in the ABC.

**Fix:** Either extend the `BaseVectorStore` ABC (preferred) or define a `ParentChunkStore` Protocol for capability detection:

```python
class ParentChunkStore(Protocol):
    async def upsert_parent_chunks(self, chunks: list[Chunk]) -> None: ...
    async def fetch_parent_chunks(self, ids: list[str]) -> list[Chunk]: ...
```

**Current `PgVectorStore` gaps:**
1. Uses `ivfflat` index → switch to HNSW
2. Missing `upsert_parent_chunks` / `fetch_parent_chunks`
3. No per-tenant table namespacing

## pgvector Multi-Tenancy

**Current approach (Qdrant):** separate collection per tenant — strong isolation, simple.

**pgvector options:**

| Strategy | Isolation | Complexity | Recommended |
|----------|-----------|------------|-------------|
| Separate table per tenant | Strong | High (migrations) | No |
| Schema per tenant | Strong | Medium | No |
| Single table + tenant_id filter | Weak (if misconfigured) | Low | Yes + RLS |
| Single table + RLS | Strong | Medium | **Yes** |

**Recommendation:** Single `embeddings` table + PostgreSQL Row-Level Security (RLS):
```sql
ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON embeddings
    USING (tenant_id = current_setting('app.current_tenant')::uuid);
```

Set `app.current_tenant` at connection setup per request. RLS enforced at DB level — misconfigurations don't leak data.

## Singleton Factory → Per-Tenant Registry

**Current problem:**
```python
@lru_cache()
def get_vector_store() -> BaseVectorStore:
    return PgVectorStore(...)  # ONE global instance
```

A single global instance with a per-request tenant filter is safe with RLS, but the factory must be aware of tenant context. **Fix:**

```python
_store_registry: dict[str, BaseVectorStore] = {}

async def get_vector_store(tenant_id: str) -> BaseVectorStore:
    if tenant_id not in _store_registry:
        _store_registry[tenant_id] = PgVectorStore(tenant_id=tenant_id)
    return _store_registry[tenant_id]
```

## Image Extraction in Ingestion Pipeline

**Fits in Stage 2 (extractor),** not after chunking. The extractor already branches on PDF type.

**ExtractedContent model extension:**
```python
@dataclass
class ExtractedImage:
    page: int
    bytes: bytes
    ext: str  # "png", "jpeg", etc.
    caption: str | None = None  # filled by embedding stage

@dataclass
class ExtractedContent:
    text: str
    tables: list[Table]
    images: list[ExtractedImage]  # NEW
    metadata: dict
```

**Pipeline flow with images:**
```
Stage 2 (extractor): PDF → text + tables + images (bytes)
Stage 3 (PII):       scan text + image captions
Stage 4 (chunker):   text chunks + image chunks (caption as text)
Stage 5 (vectorizer): embed all chunks uniformly
```

Image chunks use `chunk_type="image"` discriminator; raw bytes stored as base64 in chunk metadata.

## Async Task Tracking Pattern

**Job lifecycle:**
```
POST /ingest/async
  → create job_id (UUID)
  → store Redis key: job:{job_id} = {"status": "queued", "tenant_id": ...} TTL 86400
  → enqueue background task
  → return {"task_id": job_id, "status": "queued"}

Background task runs:
  → update Redis: status = "processing"
  → run IngestionPipeline
  → update Redis: status = "completed" | "failed", result/error

GET /ingest/status/{job_id}
  → read Redis key: job:{job_id}
  → return status + result/error
```

**Redis key pattern:** `job:{job_id}` — use existing `utils/cache.py` Redis client, no new connection pool needed.

**Implementation options:**
1. **ARQ** (recommended for heavy load) — full task queue with retry, persistence, worker pool
2. **asyncio.create_task + Redis** (simpler) — fire-and-forget with Redis for status; no retry on crash

## Build Order

1. **Fix pgvector backend** — HNSW index + missing methods + per-tenant registry (unblocks everything)
2. **Extend BaseVectorStore ABC** — ParentChunkStore Protocol (parallel with 1)
3. **Image extraction in Stage 2** — `ExtractedImage` model + PyMuPDF extraction (parallel with 1-2)
4. **Image chunking in Stage 4** — depends on Stage 2 changes
5. **Async job tracking** — independent of all above, can ship any time

## Sources

- pgvector RLS patterns: https://github.com/pgvector/pgvector
- PostgreSQL RLS: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- FastAPI background tasks: https://fastapi.tiangolo.com/tutorial/background-tasks/
- ARQ: https://arq-docs.helpmanual.io/
