# EnterpriseRAG

## What This Is

EnterpriseRAG is a production-grade Retrieval-Augmented Generation platform built on FastAPI. It serves enterprise tenants with multi-tenant document ingestion (6-stage pipeline), hybrid retrieval (dense + BM25, RRF fusion), LLM-powered query answering, and advanced operational features (A/B testing, audit logging, OIDC auth, annotation queues, streaming SSE).

v1.0 Hardening shipped: the system now runs on PostgreSQL+pgvector (no Qdrant), enforces JWT/PII/rate-limit security at startup, surfaces all exceptions through structured logging, extracts and indexes PDF-embedded images, supports async ingest with job status polling, and has 263 unit tests with a RAGAS eval gate.

## Core Value

Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.

## Requirements

### Validated

**Pre-existing (v0)**
- ✓ Multi-tenant document ingestion pipeline (6-stage: preprocess → extract → PII → chunk → vectorize → audit) — v0
- ✓ Query pipeline with hybrid retrieval and RRF fusion (10-stage) — v0
- ✓ Agentic RAG mode via Anthropic Tool Use (max 5 iterations) — v0
- ✓ FastAPI HTTP layer with CORS, GZip, rate-limit middleware, trace-ID injection — v0
- ✓ OIDC/JWT authentication — v0
- ✓ A/B testing service — v0
- ✓ Audit logging with flush buffer — v0
- ✓ Human annotation task queue — v0
- ✓ Conversation memory via Redis — v0
- ✓ Business rules engine — v0
- ✓ Streaming SSE responses — v0
- ✓ Prometheus metrics endpoint — v0
- ✓ Knowledge versioning and quality validation — v0

**v1.0 Hardening**
- ✓ pgvector backend with HNSW index + PostgreSQL RLS multi-tenancy (Qdrant removed) — v1.0
- ✓ JWT startup validation (denylist + 32-char minimum) in all environments — v1.0
- ✓ Per-route rate limiting via `@limiter.limit()` decorators — v1.0
- ✓ PII detection blocking by default (BLOCK_ENTITIES configurable) — v1.0
- ✓ CORS locked to explicit origins; localhost rejected in production — v1.0
- ✓ Narrow exception handling (50+ broad catch sites replaced) — v1.0
- ✓ `asyncio.create_task()` done_callbacks on all background tasks — v1.0
- ✓ PDF-embedded image extraction + LLM captioning → vector chunks — v1.0
- ✓ Standalone image file ingestion (jpg/png/webp → image chunk) — v1.0
- ✓ Async ingest endpoint with ARQ task queue + Redis status polling — v1.0
- ✓ 263 unit tests across 11 service modules; 46% CI coverage floor — v1.0
- ✓ 200 stratified RAGAS QA pairs with holdout discipline; CI eval gate — v1.0
- ✓ APP_MODEL_DIR required env var; Rule.check() enforced at class definition — v1.0

### Active

- [ ] Raise unit test coverage floor from 46% to 80% (TEST-02 deferred from v1.0)
- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments

### Out of Scope

- Milvus / ChromaDB backends — pgvector is the target; no need to maintain others
- Multi-region tenant isolation — single-region RLS sufficient until scale requires it
- Additional auth providers — existing OIDC integration covers enterprise needs
- Frontend / UI — API-only platform
- Automatic eval dataset generation pipeline — manual bootstrap sufficient for v1

## Context

**Codebase state:** ~5000 lines of service code (Python/FastAPI). All core infrastructure shipped. v1.0 Hardening closed security and quality gaps.

**Vector store:** PostgreSQL + pgvector with HNSW index. Qdrant fully removed.

**Testing:** 263 unit tests passing, 46.63% service coverage. CI pipeline: lint → unit (46% floor) → integration → security scan → Docker build → eval gate (main only).

**Known issues / tech debt:**
- Unit test coverage at 46% (80% target deferred to v1.1)
- HNSW UPDATE path: always DELETE + INSERT; schedule periodic `REINDEX`
- PyMuPDF commercial license: needed for enterprise on-premise

## Constraints

- **Tech stack**: Python / FastAPI — no runtime changes
- **Vector store**: PostgreSQL + pgvector — must maintain API compatibility
- **Compatibility**: Existing API contracts must not break
- **Security**: All v1.0 security requirements shipped and enforced

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| pgvector over Qdrant | Consolidates on PostgreSQL; eliminates external Qdrant dependency | ✓ Good — Qdrant fully removed |
| HNSW over IVFFlat | Handles incremental inserts correctly; matches Qdrant behavior | ✓ Good |
| Single table + PostgreSQL RLS | DB-level tenant enforcement; misconfiguration cannot leak data | ✓ Good |
| PII detection blocking by default | Non-blocking is a compliance risk for enterprise tenants | ✓ Good |
| Reject bad JWT in all envs | Security guarantees must not depend on ENVIRONMENT var | ✓ Good |
| Caption-then-embed for images | Keeps vector space uniform; CLIP available as zero-cost fallback | ✓ Good |
| ARQ for async task queue | Retry + crash persistence; reuses Redis already in stack | ✓ Good |
| PyMuPDF AGPL | Proceed; licensing handled separately by team | ⚠ Revisit — commercial license needed for on-premise |
| CI coverage floor at 46% | 80% target unrealistic with current test suite; guards regression | ⚠ Revisit — raise in v1.1 |
| RAGAS eval gate (main-branch only) | Avoid API budget burn on every PR; gpt-4o-mini keeps cost low | ✓ Good |

## Evolution

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-27 after v1.0 Hardening milestone*
