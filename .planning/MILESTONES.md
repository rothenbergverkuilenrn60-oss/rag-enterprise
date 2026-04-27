# Milestones — EnterpriseRAG

## v1.0 Hardening — 2026-04-27

**Shipped:** 2026-04-27
**Phases:** 1–6 | **Plans:** 20 | **Commits:** 100
**Timeline:** 2026-04-20 → 2026-04-27 (7 days)

**Delivered:** Hardened an existing production RAG platform — pgvector migration, security lockdown, error handling sweep, image extraction, async ingest tracking, and test baseline with RAGAS eval gates.

**Key accomplishments:**
1. Replaced Qdrant with PostgreSQL+pgvector (HNSW index, RLS multi-tenant isolation) — zero API contract changes
2. Security hardening: JWT denylist startup check, per-route rate limiting, PII blocking by default, CORS locked to explicit origins
3. Narrowed 50+ broad `except Exception` sites; `done_callback` on every `asyncio.create_task()`
4. PDF image extraction with LLM captioning → retrievable `chunk_type="image"` vector chunks; standalone image file ingestion
5. Async ingest endpoint with ARQ/Redis task queue — `task_id` + status polling; 24h TTL
6. 263 unit tests across 11 service modules; 200 stratified RAGAS QA pairs; CI eval gate on main

**Known deferred items:** TEST-02 (80% coverage floor → 46% actual; deferred to v1.1)

**Archive:** [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) · [milestones/v1.0-REQUIREMENTS.md](milestones/v1.0-REQUIREMENTS.md)
