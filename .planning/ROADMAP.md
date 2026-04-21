# Roadmap — EnterpriseRAG Hardening

## Overview

6 phases | 22 requirements | Harden an existing production RAG platform: migrate the vector store to pgvector, close security gaps, fix silent failures, implement image extraction and async ingest tracking, and reach 80% test coverage with a meaningful eval suite.

## Phases

- [ ] **Phase 1: pgvector Foundation** — Replace Qdrant with PostgreSQL + pgvector; HNSW index; RLS multi-tenancy; parent chunk interface
- [ ] **Phase 2: Security Hardening + Operational Fixes** — JWT startup validation; per-route rate limiting; blocking PII; CORS tightening; MODEL_DIR and Rule.check() fixes
- [ ] **Phase 3: Error Handling Sweep** — Replace 50+ broad except clauses with specific types; attach done_callback to every create_task
- [ ] **Phase 4: Image Extraction** — PDF-embedded image extraction in Stage 2; image chunking with LLM captions in Stage 4; standalone image file ingestion; retrieval support
- [ ] **Phase 5: Async Ingest Tracking** — task_id returned from async ingest endpoint; Redis-backed ARQ job status polling
- [ ] **Phase 6: Test Coverage and Eval** — Unit tests for 11 uncovered modules; 80% coverage floor in CI; 200+ QA eval pairs with RAGAS gates

## Phase Table

| # | Phase | Goal | Requirements |
|---|-------|------|--------------|
| 1 | pgvector Foundation | Ingest and query pipelines run entirely on pgvector with HNSW index and RLS tenant isolation | PG-01, PG-02, PG-03, PG-04, PG-05 |
| 2 | Security Hardening + Operational Fixes | System refuses to start with weak JWT secrets; rate limits enforce per-route; PII blocks ingest; CORS is explicit; startup env vars validated | SEC-01, SEC-02, SEC-03, SEC-04, OPS-01, OPS-02 |
| 3 | Error Handling Sweep | No broad exception swallowing; every failure reaches the audit log or structured logger; every background task exception is captured | ERR-01, ERR-02 |
| 4 | Image Extraction | PDF-embedded images and standalone image files are ingested as captioned, embedded chunks retrievable alongside text | IMG-01, IMG-02, IMG-03, IMG-04 |
| 5 | Async Ingest Tracking | Clients receive a task_id immediately on async ingest and can poll job status with full error detail | ASYNC-01, ASYNC-02 |
| 6 | Test Coverage and Eval | All 11 previously untested service modules have unit tests; CI enforces 80% coverage; eval suite has 200+ stratified QA pairs with RAGAS CI gates | TEST-01, TEST-02, TEST-03 |

## Phase Details

### Phase 1: pgvector Foundation
**Goal:** Ingest and query pipelines run entirely on pgvector with HNSW index and RLS tenant isolation, replacing Qdrant with no API contract changes.
**Depends on:** Nothing (first phase)
**Requirements:** PG-01, PG-02, PG-03, PG-04, PG-05
**Success Criteria:**
1. Documents ingested via existing `/ingest` endpoint are stored in PostgreSQL; Qdrant is no longer referenced at runtime
2. Vector similarity queries return recall@10 within 5% of the Qdrant baseline using the HNSW index
3. A query issued with tenant A's token cannot retrieve documents belonging to tenant B (RLS enforcement verified)
4. `PgVectorStore.upsert_parent_chunks()` and `fetch_parent_chunks()` round-trip correctly for parent-child chunk relationships
**Plans:** TBD
Plans:
- [ ] 01-01-PLAN.md — Test scaffolding: unit and integration test stubs for PG-01..PG-05
- [ ] 01-02-PLAN.md — PgVectorStore: HNSW index, codec registration, RLS DDL, parent chunk methods
- [ ] 01-03-PLAN.md — TenantService rename + set_tenant_context; pipeline.py call-site updates
- [ ] 01-04-PLAN.md — requirements.txt pgvector package; settings.py default backend switch

### Phase 2: Security Hardening + Operational Fixes
**Goal:** The system refuses to start with a weak or default JWT secret, enforces rate limits per-route, blocks PII-containing ingest by default, and accepts no localhost CORS origins in production.
**Depends on:** Phase 1
**Requirements:** SEC-01, SEC-02, SEC-03, SEC-04, OPS-01, OPS-02
**Success Criteria:**
1. Server startup fails with a clear error when `JWT_SECRET` matches a denylist entry or is shorter than 32 characters, in any environment
2. Sending 11 rapid requests to a rate-limited route returns HTTP 429 on the 11th request; the global middleware alone is not the enforcement mechanism
3. Submitting a document containing an SSN or credit card number to the ingest endpoint returns a rejection response, not a warning
4. Starting the server without `MODEL_DIR` set fails at startup with a descriptive message; `Rule.check()` raises `NotImplementedError` at class definition via ABC
**Plans:** TBD

### Phase 3: Error Handling Sweep
**Goal:** Every failure path in the codebase surfaces through the audit log or structured logger; no exception is silently swallowed and no background task drops an exception.
**Depends on:** Phase 2
**Requirements:** ERR-01, ERR-02
**Success Criteria:**
1. A forced exception in any previously broad-catch site produces a structured log entry with full context rather than being silently absorbed
2. Every `asyncio.create_task()` call has a registered `done_callback`; a task that raises an unhandled exception produces a logged error record
3. Injecting a failure into each previously swallowed exception path shows the error in the audit log within the same request cycle
**Plans:** TBD

### Phase 4: Image Extraction
**Goal:** PDF-embedded images and standalone image files are ingested as captioned, embedded chunks that are retrievable alongside text chunks with no changes to the query API.
**Depends on:** Phase 1 (pgvector must be live to store image chunks)
**Requirements:** IMG-01, IMG-02, IMG-03, IMG-04
**Success Criteria:**
1. Ingesting a PDF containing embedded images produces `chunk_type="image"` chunks in the vector store, each with an LLM-generated caption and base64 raw bytes in metadata
2. A hybrid query that matches an image caption returns that image chunk alongside text chunks; the response includes caption text and base64 bytes
3. Uploading a standalone `.jpg` or `.png` file to the ingest endpoint produces a single image chunk with a generated caption stored and retrievable
4. `ExtractedContent.images` is populated by Stage 2 and flows through Stage 4 chunking without pipeline errors on PDFs with no images
**Plans:** TBD
**UI hint**: no

### Phase 5: Async Ingest Tracking
**Goal:** Clients receive a task_id immediately on async ingest and can poll for job status including error detail, backed by ARQ and Redis.
**Depends on:** Phase 2 (security must be hardened before exposing new endpoints)
**Requirements:** ASYNC-01, ASYNC-02
**Success Criteria:**
1. `POST /ingest/async` returns a JSON body containing a `task_id` within 200ms regardless of document size
2. `GET /ingest/status/{task_id}` returns `{"status": "pending"|"complete"|"failed", ...}` and on failure includes an error detail field
3. A task_id polled 25 hours after submission returns 404 (TTL expiry enforced at 24h)
**Plans:** TBD

### Phase 6: Test Coverage and Eval
**Goal:** All 11 previously untested service modules have unit tests; CI enforces an 80% coverage floor; the eval dataset has 200+ stratified QA pairs with RAGAS CI gates.
**Depends on:** Phase 3 (error handling must be stable before coverage is meaningful; false passes from swallowed exceptions are eliminated)
**Requirements:** TEST-01, TEST-02, TEST-03
**Success Criteria:**
1. Running `pytest` with coverage reporting shows tests for all 11 service modules (auth, memory, feedback, audit, tenant, events, NLU, knowledge, ab_test, rules, vectorizer)
2. CI pipeline fails the build when overall unit test coverage drops below 80%
3. The eval dataset contains at least 200 QA pairs stratified by document type and topic; RAGAS CI gate passes only when `faithfulness > 0.85` and `answer_relevancy > 0.80`
**Plans:** TBD

## Progress Table

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. pgvector Foundation | 0/4 | In progress | - |
| 2. Security Hardening + Operational Fixes | 0/0 | Not started | - |
| 3. Error Handling Sweep | 0/0 | Not started | - |
| 4. Image Extraction | 0/0 | Not started | - |
| 5. Async Ingest Tracking | 0/0 | Not started | - |
| 6. Test Coverage and Eval | 0/0 | Not started | - |
