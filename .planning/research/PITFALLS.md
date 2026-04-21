# Pitfalls Research

## Summary

pgvector's IVFFlat index is the most common migration trap — it requires a post-load rebuild phase that breaks incremental ingest. Multi-tenant data leakage via missing `tenant_id` filters is the most common RAG production failure. Broad exception swallowing in async Python is especially dangerous because asyncio silently drops unhandled exceptions from background tasks. Eval dataset quality issues compound: a contaminated or imbalanced dataset gives false confidence in RAG quality.

## pgvector Migration Traps

**IVFFlat vs HNSW:**
- IVFFlat requires `VACUUM ANALYZE` after bulk inserts before recall is accurate — don't benchmark until after
- IVFFlat recall degrades with incremental inserts (lists become unbalanced); HNSW handles incremental correctly
- **Use HNSW by default** — only use IVFFlat for very large static datasets

**Memory configuration:**
```sql
SET work_mem = '256MB';  -- per-connection, needed for HNSW build
```
Without this, pgvector falls back to disk-based build and becomes 10-100x slower.

**Multi-tenancy + filtering:**
- Using `WHERE tenant_id = ?` alongside a vector index on the full table forces a full index scan + post-filter
- For large tenant counts: partition by `tenant_id` or use separate tables
- RLS with `current_setting('app.current_tenant')` is enforced at DB level — safest approach

**UPDATE vs DELETE+INSERT:**
- HNSW indexes accumulate dead entries on UPDATE (vectors can't be updated in-place)
- Always DELETE the old vector + INSERT a new one; run periodic `REINDEX` on large deployments

**Migration verification:**
- Run recall@10 comparison: Qdrant vs pgvector on the same query set before cutover
- Target: recall within 5% of Qdrant baseline

## RAG Security Failure Modes

**Tenant data leakage (most common):**
- Pattern: chat endpoint has auth + tenant filter, but the retrieval endpoint (`/search`, `/query`) does not
- Result: unauthenticated callers can retrieve documents from other tenants via the retrieval API
- Fix: enforce tenant filter at the vector store query level, not just the API layer

**Adversarial content in retrieved context:**
- Retrieved document chunks can contain instructions that influence LLM behavior
- Defense: system prompt must assert its authority over retrieved content; retrieved chunks should be framed as "external data" not "instructions"
- Never interpolate retrieved content directly into the system prompt

**Default credentials in non-production environments:**
- Staging environments sharing the production JWT secret is a common misconfiguration
- Fix: generate secrets per-environment at deploy time, validate entropy at startup

**Unguarded admin endpoints:**
- Admin routes (annotation, knowledge versioning, A/B config) are high-value targets
- Verify every admin route has both authentication AND authorization checks

## Broad Exception Handling Anti-patterns

**The core problem:**
```python
# WRONG — swallows errors silently
try:
    result = await pipeline.run(doc)
except Exception:
    pass  # or: logger.error("failed") and return None

# RIGHT — narrow catch, always re-raise or explicitly handle
try:
    result = await pipeline.run(doc)
except VectorizationError as e:
    await audit_log.record_failure(doc.id, e)
    raise  # let the caller decide
except PipelineConfigError as e:
    raise HTTPException(status_code=500, detail=str(e))
```

**asyncio background tasks silently drop exceptions:**
```python
# WRONG — exceptions from create_task() are silently dropped
asyncio.create_task(some_coroutine())

# RIGHT — always attach a done callback
task = asyncio.create_task(some_coroutine())
task.add_done_callback(lambda t: t.exception() and logger.error("Task failed", exc_info=t.exception()))
```

**Rules for replacing broad catches:**
1. Catch only exceptions you can handle meaningfully
2. If you can't handle it, re-raise
3. Never catch `BaseException` (catches `KeyboardInterrupt`, `SystemExit`)
4. Log with full context before re-raising, not after swallowing

## Rate Limiting Pitfalls in FastAPI

**Starlette middleware is LIFO:**
- Middleware added last executes first
- Rate limiting middleware must be added AFTER auth middleware in code (so it runs BEFORE auth in execution)
- Wrong order = rate limiter never sees authenticated user identity

**In-process state is shared across test instances:**
```python
# WRONG — TestClient instances share in-process limiter state
client1 = TestClient(app)
client2 = TestClient(app)  # shares rate limit counters with client1

# RIGHT — use Redis backend + flush between tests
@pytest.fixture(autouse=True)
async def flush_rate_limits(redis):
    await redis.flushdb()  # or use a test-specific key prefix
    yield
```

**Middleware constructors must not open async connections:**
- Opening Redis connections in `__init__` of a middleware class fails because `__init__` is synchronous
- Open connections in `async def __call__` on first use, or via FastAPI lifespan

**`slowapi` decorator requirement:**
- `@limiter.limit("N/minute")` decorator is required on each route
- Global `app.state.limiter` registration only handles the exception response — it does not apply any limit on its own

## Eval Dataset Construction Mistakes

**Contamination:**
- Never generate eval QA pairs from documents that are also in the retrieval index
- Hold out 20% of documents as eval-only — these must never be ingested
- Re-validate after every index refresh that eval documents haven't leaked in

**Distribution bias:**
- 10 pairs from one document type will have near-zero variance — not a meaningful signal
- Stratify by: document type, topic category, answer length, required reasoning depth

**Imbalance:**
- Include ~20% "unanswerable" questions (no relevant context in the index)
- Measuring only answerable questions inflates faithfulness scores

**Multi-annotator quality:**
- Require inter-annotator agreement (kappa > 0.7) before accepting human-labeled pairs
- LLM-generated pairs need human review for factual correctness before use as ground truth

**Automation:**
```
ragas.testset.TestsetGenerator  # generate synthetic QA from existing docs
```
Bootstrap 200 pairs from ingested documents using LLM generation, then human-review a 20% sample. This is faster than manual construction from scratch.

## Sources

- pgvector performance guide: https://github.com/pgvector/pgvector#performance
- RAGAS eval: https://docs.ragas.io/en/latest/concepts/testset_generation.html
- asyncio exception handling: https://docs.python.org/3/library/asyncio-task.html#asyncio.Task.add_done_callback
- slowapi docs: https://slowapi.readthedocs.io/en/latest/
