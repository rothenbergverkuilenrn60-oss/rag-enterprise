# Stack Research

## Summary

Key libraries are largely already pinned in `requirements.txt`. pgvector adds only 3 new packages (`pgvector`, `SQLAlchemy 2.0`, `alembic`). PyMuPDF for image extraction is already present. ARQ is the right async task queue — uses existing Redis infrastructure with zero new services. Image embedding uses caption-then-embed via the already-integrated LLM, keeping the vector space uniform.

## pgvector Setup (Python)

**Add to requirements.txt:**
```
pgvector==0.3.6          # SQLAlchemy Vector type + asyncpg codec
SQLAlchemy==2.0.36       # async ORM engine (AsyncSession, AsyncEngine)
alembic==1.14.0          # schema migrations for vector column
```

**asyncpg 0.30.0 already pinned.** Critical setup:
```python
from pgvector.asyncpg import register_vector

async def init_connection(conn):
    await register_vector(conn)

engine = create_async_engine(
    DATABASE_URL,
    connect_args={"init": init_connection}
)
```

**Index choice:** Use HNSW (not ivfflat) for production:
```sql
CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops);
```
HNSW (pgvector ≥ 0.5.0) handles incremental ingestion without a post-load ANALYZE phase. Matches Qdrant's behavior.

## Image Extraction from PDFs

**PyMuPDF 1.25.1 already pinned** — no new dependency needed.

```python
import fitz  # PyMuPDF

def extract_images(pdf_path: str) -> list[dict]:
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        for img_ref in page.get_images():
            xref = img_ref[0]
            img = doc.extract_image(xref)
            images.append({
                "bytes": img["image"],
                "ext": img["ext"],
                "page": page.number
            })
    return images
```

**License note:** PyMuPDF is AGPL-3.0. Enterprise on-premise deployment may require a commercial Artifex license — needs legal review.

## Async Task Tracking in FastAPI

**ARQ** is the correct fit — uses Redis already in the stack, zero new infrastructure.

```
arq==0.26.1
```

**Pattern:**
```python
# POST /ingest/async — returns job_id immediately
async def ingest_async(file: UploadFile, redis: Redis = Depends(get_redis)):
    pool = await create_pool(RedisSettings.from_url(REDIS_URL))
    job = await pool.enqueue_job("ingest_document", file_bytes, tenant_id)
    return {"task_id": job.job_id, "status": "queued"}

# GET /tasks/{task_id} — poll status
async def get_task_status(task_id: str, redis: Redis = Depends(get_redis)):
    job = Job(task_id, redis)
    status = await job.status()
    return {"task_id": task_id, "status": status.value}
```

ARQ worker runs as a separate Docker Compose service using the same Redis instance.

**Alternative (lighter):** For simple fire-and-forget without a worker process, use `asyncio.create_task()` + Redis key `job:{task_id}` with TTL 24h. Simpler but loses task queue guarantees (no retry, no persistence across restart).

## Image Embedding Strategy

**Recommendation: caption-then-embed** (no new model infrastructure).

```python
# 1. Extract image bytes from PDF
# 2. Send to existing LLM (Claude/GPT-4o) with vision capability
caption = await llm.generate(prompt="Describe this image concisely", image=img_bytes)
# 3. Embed the caption text using existing BGE-M3 embedder
embedding = embedder.encode(caption)
# 4. Store with chunk_type="image" discriminator
chunk = Chunk(text=caption, embedding=embedding, chunk_type="image", raw_image_b64=...)
```

**Fallback:** CLIP (`clip-ViT-B-32` via `sentence-transformers`, already pinned) if LLM captioning cost is prohibitive at scale.

**Cost consideration:** Caption generation via LLM API adds cost at ingestion time. Benchmark before committing — CLIP fallback is zero additional cost.

## Sources

- pgvector Python package: https://github.com/pgvector/pgvector-python
- ARQ docs: https://arq-docs.helpmanual.io/
- PyMuPDF docs: https://pymupdf.readthedocs.io/
- pgvector HNSW indexing: https://github.com/pgvector/pgvector#hnsw
