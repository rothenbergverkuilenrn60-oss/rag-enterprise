# Research Summary — EnterpriseRAG Hardening

## Key Findings

### Stack

- **All major dependencies already present** — PyMuPDF (images), asyncpg (pg), Redis (task queue). New additions only: `pgvector==0.3.6`, `SQLAlchemy==2.0.36`, `alembic==1.14.0`, `arq==0.26.1`, `presidio-analyzer`, `presidio-anonymizer`.
- **PyMuPDF is AGPL-3.0** — on-premise enterprise deployment needs legal review for a commercial Artifex license before shipping image extraction.
- **ARQ over asyncio.create_task** for async ingest tracking — ARQ provides retry and crash persistence; bare `create_task` silently drops exceptions on crash.

### Critical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| pgvector index type | HNSW | IVFFlat degrades on incremental inserts; HNSW handles ingest continuously |
| Multi-tenancy | Single table + PostgreSQL RLS | DB-level enforcement; misconfiguration cannot leak data across tenants |
| Image embedding | Caption-then-embed (LLM vision → BGE-M3) | Keeps vector space uniform; CLIP is zero-cost fallback |
| Async task queue | ARQ (Redis-backed) | Zero new infra; retry + persistence; same Redis already in stack |
| PII timing | Before chunking (Stage 3) | PII split across chunk boundaries becomes undetectable |
| JWT secret validation | Startup entropy check + denylist | Missing or weak secret = crash at boot, not silent runtime failure |

### Build Order

1. **Fix pgvector backend** — HNSW index + missing methods + per-tenant registry (unblocks all other work)
2. **Extend BaseVectorStore ABC** — add `ParentChunkStore` Protocol (parallel with step 1)
3. **Security hardening** — JWT startup validation, Presidio PII, slowapi per-route decorators, RLS policy
4. **Error handling sweep** — replace 50+ `except Exception` with narrow catches + done-callback on all `create_task` calls
5. **Image extraction** — `ExtractedImage` model + PyMuPDF in Stage 2; image chunking in Stage 4
6. **Async ingest tracking** — ARQ worker + `POST /ingest/async` + `GET /ingest/status/{job_id}`
7. **Test coverage** — dependency_overrides + `cache_clear()` teardown; 80% floor across 18 services
8. **Eval expansion** — `ragas.testset.TestsetGenerator` bootstrap; stratified 200-pair dataset

### Top Pitfalls to Avoid

1. **IVFFlat index** — recall degrades with incremental inserts; use HNSW; set `work_mem='256MB'` or index build falls back to disk (10-100x slower)
2. **Tenant data leakage** — retrieval endpoints missing tenant filter while chat endpoint has auth; enforce at vector store level, not API layer only
3. **asyncio silent drops** — `create_task()` silently discards exceptions; always attach `add_done_callback`
4. **slowapi middleware-only assumption** — middleware only handles the exception response; `@limiter.limit()` decorator required on every route; middleware is LIFO
5. **Singleton leakage in tests** — `lru_cache` bleeds across tests; always call `cache_clear()` in teardown after `dependency_overrides.clear()`
6. **HNSW vector UPDATE** — accumulates dead entries; always DELETE + INSERT; schedule periodic `REINDEX`
7. **Eval contamination** — never generate QA pairs from documents already in the retrieval index; 20% holdout before any ingest

### Eval Standards

- **Minimum viable:** 50 pairs for CI smoke test; 200+ for meaningful regression detection
- **RAGAS thresholds:** `faithfulness > 0.85`, `answer_relevancy > 0.80`, `context_precision > 0.75`, `context_recall > 0.70`
- **Bootstrap path:** `ragas.testset.TestsetGenerator` → 200 synthetic pairs → human-review 20% sample → stratify by doc type, topic, answer length; include ~20% unanswerable questions

## Implementation Guidance

**pgvector migration:** `PgVectorStore` already exists but is incomplete — two missing methods and wrong index type. Completion task, not a rewrite. Run recall@10 comparison against Qdrant baseline before cutover; target within 5%.

**Security hardening:** JWT validation in FastAPI lifespan startup handler. Presidio PII in Stage 3, before chunking. `@limiter.limit()` on each route + `request: Request` as first parameter. Every admin route needs both auth and authz checks.

**Error handling sweep:** Narrow exception types; always re-raise or log with full context. Attach `add_done_callback` to every `create_task`. Map domain exceptions to specific HTTP status codes.

**Image extraction:** Extend `ExtractedContent` with `images: list[ExtractedImage]` in Stage 2. Caption via LLM vision in Stage 5; embed through existing BGE-M3; store raw bytes as base64 with `chunk_type="image"`.

**Test coverage:** `app.dependency_overrides` + `cache_clear()` teardown as canonical pattern. Flush Redis between rate-limit tests — in-process state is shared.

## Open Questions

1. **PyMuPDF license:** Commercial Artifex license needed for enterprise on-premise? Blocks image extraction phase.
2. **Async task queue:** ARQ full worker process (separate Docker service) or `asyncio.create_task + Redis` to avoid operational overhead?
3. **Image embedding cost:** LLM captioning at ingest scale — is there a per-document budget, or should CLIP be the default?
4. **Eval holdout set:** Are 20% of current documents available as eval-only, or does bootstrapping require entirely synthetic data?
5. **RLS pool compatibility:** asyncpg pool must set `app.current_tenant` per-connection (not per-query) — needs verification against current pool config before RLS goes live.

## Suggested Phase Structure

| Phase | Focus | Key deliverables |
|-------|-------|-----------------|
| 1 | Foundation | pgvector: HNSW + missing methods + RLS + per-tenant registry |
| 2 | Hardening | JWT startup validation, Presidio PII, slowapi per-route, error handling sweep, admin auth audit |
| 3 | Features | Image extraction pipeline, async ingest tracking, test coverage to 80% |
| 4 | Quality | Eval dataset 200+ pairs, RAGAS CI gates |
