# Requirements — EnterpriseRAG Hardening

## v1 Requirements

### Security

- [ ] **SEC-01**: System rejects any JWT secret that matches a known-weak denylist or is shorter than 32 characters — at startup, before accepting traffic, in ALL environments
- [ ] **SEC-02**: Rate limiting is enforced per-route via `@limiter.limit()` decorators; global middleware alone is not sufficient
- [ ] **SEC-03**: PII detection blocks ingest by default for configured BLOCK_ENTITIES (SSN, credit card, etc.); non-blocking mode is opt-in per tenant
- [ ] **SEC-04**: CORS allowed origins are explicitly configured via environment variable; no localhost origins permitted in production config

### Error Handling

- [ ] **ERR-01**: All `except Exception` catch sites replaced with specific exception types; swallowed errors are eliminated — every failure surfaces through audit log or structured logging
- [ ] **ERR-02**: Every `asyncio.create_task()` call has a `done_callback` that logs or re-raises unhandled exceptions

### pgvector Migration

- [ ] **PG-01**: Vector store backend switched from Qdrant to PostgreSQL + pgvector; existing ingestion and query pipeline APIs unchanged
- [ ] **PG-02**: pgvector uses HNSW index (not IVFFlat); `work_mem=256MB` set at connection level for index operations
- [ ] **PG-03**: Multi-tenant isolation enforced via PostgreSQL Row-Level Security (RLS) with `app.current_tenant` per-connection setting
- [ ] **PG-04**: `PgVectorStore` implements `upsert_parent_chunks()` and `fetch_parent_chunks()` — parity with Qdrant backend
- [ ] **PG-05**: `BaseVectorStore` ABC extended (or `ParentChunkStore` Protocol added) to formalize parent chunk interface

### Image Extraction

- [ ] **IMG-01**: Ingestion pipeline extracts images embedded in PDF documents during Stage 2 (extractor); `ExtractedContent` model includes `images: list[ExtractedImage]`
- [ ] **IMG-02**: Image chunks are generated in Stage 4 (chunker) with `chunk_type="image"` discriminator; LLM vision generates caption, caption is embedded via existing BGE-M3 embedder
- [ ] **IMG-03**: Image chunks are retrievable alongside text chunks in query pipeline; retrieved image chunks include caption text and base64 raw bytes in metadata
- [ ] **IMG-04**: Ingestion pipeline accepts standalone image files (jpg, png, webp) as documents; LLM vision generates caption, caption is embedded and stored as a single chunk with `chunk_type="image"`

### Async Ingest Tracking

- [ ] **ASYNC-01**: `POST /ingest/async` endpoint returns a `task_id` immediately; ingestion runs as an ARQ background job
- [ ] **ASYNC-02**: `GET /ingest/status/{task_id}` polls job status from Redis (`job:{task_id}` key, TTL 24h); returns status and error detail on failure

### Test Coverage

- [ ] **TEST-01**: Unit tests added for all 11 currently uncovered service modules: auth, memory, feedback, audit, tenant, events, NLU, knowledge, ab_test, rules, vectorizer
- [ ] **TEST-02**: Unit test coverage floor raised from 60% to 80% (enforced in CI)
- [ ] **TEST-03**: Eval dataset expanded from 10 to ≥200 QA pairs; stratified by document type and topic; 20% holdout documents never ingested; RAGAS CI gate with `faithfulness > 0.85`, `answer_relevancy > 0.80`

### Operational Fixes

- [ ] **OPS-01**: `MODEL_DIR` default removed; startup validation requires env var to be set explicitly; server refuses to start if unset
- [ ] **OPS-02**: `Rule.check()` abstract method raises `NotImplementedError` at class definition time (via ABC), not at runtime call site

---

## v2 Requirements (Deferred)

- Multi-region tenant isolation — single-region RLS sufficient for v1
- Additional vector store backends (ChromaDB, Milvus) — pgvector is the target; others deferred
- Automatic eval dataset generation CI pipeline — manual bootstrap sufficient for v1

---

## Out of Scope

- New pipeline stages or enterprise features — harden what exists; no new capabilities
- Milvus backend — replacing with pgvector; Milvus never had a working implementation
- OIDC provider additions — existing OIDC integration is out of scope
- Frontend / UI — API only

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| PyMuPDF (AGPL) | Proceed; licensing handled separately by team |
| ARQ for async queue | Full retry + persistence; Docker Compose worker service acceptable |
| LLM caption for image embedding | Quality over cost; CLIP available as fallback |
| HNSW over IVFFlat | Handles incremental ingestion correctly; matches Qdrant behavior |
| RLS for multi-tenancy | DB-level enforcement; misconfiguration cannot leak across tenants |

---

## Traceability

*(Filled by roadmapper)*

| REQ-ID | Phase |
|--------|-------|
| SEC-01–04 | — |
| ERR-01–02 | — |
| PG-01–05 | — |
| IMG-01–04 | — |
| ASYNC-01–02 | — |
| TEST-01–03 | — |
| OPS-01–02 | — |
