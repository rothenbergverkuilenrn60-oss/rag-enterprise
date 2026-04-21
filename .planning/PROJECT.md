# EnterpriseRAG

## What This Is

EnterpriseRAG is a production-grade Retrieval-Augmented Generation platform built on FastAPI. It serves enterprise tenants with multi-tenant document ingestion, hybrid retrieval (dense + BM25), LLM-powered query answering, and advanced operational features (A/B testing, audit logging, OIDC auth, annotation queues, streaming SSE). The current goal is to harden the existing system: close security gaps, complete missing features, and reach production readiness.

## Core Value

Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.

## Requirements

### Validated

- ✓ Multi-tenant document ingestion pipeline (6-stage: preprocess → extract → PII → chunk → vectorize → audit) — existing
- ✓ Query pipeline with hybrid retrieval and RRF fusion (10-stage) — existing
- ✓ Agentic RAG mode via Anthropic Tool Use (max 5 iterations) — existing
- ✓ FastAPI HTTP layer with CORS, GZip, rate-limit middleware, trace-ID injection — existing
- ✓ OIDC/JWT authentication — existing
- ✓ A/B testing service — existing
- ✓ Audit logging with flush buffer — existing
- ✓ Human annotation task queue — existing
- ✓ Conversation memory via Redis — existing
- ✓ Business rules engine — existing
- ✓ Streaming SSE responses — existing
- ✓ Prometheus metrics endpoint — existing
- ✓ Knowledge versioning and quality validation — existing

### Active

**Security**
- [ ] Reject default JWT secret (`CHANGE-ME-IN-PRODUCTION-USE-256BIT-KEY`) in ALL environments, not just production
- [ ] Enforce rate limiter at controller/route level (currently configured but not applied per-route)
- [ ] Make PII detection blocking by default (currently advisory)
- [ ] Tighten CORS to explicitly configured allowed origins (remove localhost defaults for production)

**Error Handling**
- [ ] Replace ~50+ broad `except Exception` catch sites with specific exception types and proper propagation
- [ ] Ensure all swallowed errors surface through audit log or structured logging

**Test Coverage**
- [ ] Add unit tests for 11 uncovered service modules: auth, memory, feedback, audit, tenant, events, NLU, knowledge, ab_test, rules, vectorizer
- [ ] Raise unit test coverage floor from 60% to 80%
- [ ] Expand eval dataset from 10 QA pairs to a meaningful evaluation suite (≥100 pairs)

**Operational**
- [ ] Remove hardcoded WSL2 `MODEL_DIR` default (`/mnt/f/my_models`) — use configurable env var with validation at startup
- [ ] Fix `Rule.check()` — raise error at class definition time, not at runtime call site

**Feature Completion**
- [ ] Switch vector store backend from Qdrant to PostgreSQL + pgvector
- [ ] Implement image extraction from PDFs/documents during ingestion (currently declared, not implemented)
- [ ] Add task ID to async ingest endpoint response — enable clients to poll job status

### Out of Scope

- Milvus / ChromaDB backends — replacing with pgvector; no need to maintain others
- Standalone image file uploads (jpg/png as documents) — embedded PDF images only for now
- New enterprise features (new pipeline stages, new auth providers) — harden existing first

## Context

**Existing codebase:** EnterpriseRAG v3.0.0. All core infrastructure is implemented. Main issues are quality/correctness gaps rather than missing architecture.

**Vector store migration:** Current code references both Qdrant and Milvus; Milvus has no `pymilvus` in requirements. Moving to pgvector consolidates on PostgreSQL for both relational data and vector similarity, simplifying ops.

**Testing state:** 4 of 18 service modules have unit tests. Integration tests require a live stack. CI runs lint → unit → integration (integration non-blocking).

**Security state:** Default JWT secret passes validation in dev/staging environments. Rate limiter middleware exists but is not wired to individual routes. PII detection runs but does not block ingest by default.

**Image extraction:** `services/extractor/` has an image extraction interface declared but the implementation raises `NotImplementedError`. PDFs are the primary document type.

## Constraints

- **Tech stack**: Python / FastAPI — no runtime changes
- **Vector store**: PostgreSQL + pgvector (replacing Qdrant) — must maintain API compatibility with existing query/ingest pipelines
- **Compatibility**: Existing API contracts must not break — clients depend on current endpoint shapes
- **Security**: Fix critical issues before any other hardening work (JWT, rate limiter)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| pgvector over Qdrant | Consolidates on PostgreSQL already in stack; eliminates external Qdrant dependency; simpler ops | — Pending |
| PII detection blocking by default | Non-blocking PII is a compliance risk for enterprise tenants | — Pending |
| Reject bad JWT in all envs | Security guarantees must not depend on `ENVIRONMENT` env var being set correctly | — Pending |
| Expand eval to ≥100 pairs | 10 QA pairs provides no statistical signal for RAG quality regression | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

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
*Last updated: 2026-04-21 after initialization*
