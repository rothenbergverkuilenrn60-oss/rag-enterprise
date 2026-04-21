# STATE — EnterpriseRAG Hardening

## Project Reference

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** Phase 1 — pgvector Foundation

## Current Position

| Field | Value |
|-------|-------|
| Milestone | v1 Hardening |
| Current phase | 1 — pgvector Foundation |
| Current plan | None (planning not yet started) |
| Phase status | Not started |
| Overall progress | 0/6 phases complete |

```
Progress: [----------] 0%
```

## Phase Overview

| Phase | Status |
|-------|--------|
| 1. pgvector Foundation | Not started |
| 2. Security Hardening + Operational Fixes | Not started |
| 3. Error Handling Sweep | Not started |
| 4. Image Extraction | Not started |
| 5. Async Ingest Tracking | Not started |
| 6. Test Coverage and Eval | Not started |

## Performance Metrics

| Metric | Value |
|--------|-------|
| Phases completed | 0/6 |
| Requirements complete | 0/22 |
| Plans executed | 0 |

## Accumulated Context

### Key Decisions Logged

| Decision | Rationale |
|----------|-----------|
| pgvector over Qdrant | Consolidates on PostgreSQL; eliminates external Qdrant dependency |
| HNSW index | IVFFlat degrades on incremental inserts; HNSW handles continuous ingest |
| Single table + PostgreSQL RLS | DB-level tenant enforcement; misconfiguration cannot leak data |
| Caption-then-embed for images | Keeps vector space uniform; CLIP available as zero-cost fallback |
| ARQ for async task queue | Retry + crash persistence; same Redis already in stack; zero new infra |
| PII blocking before chunking (Stage 3) | PII split across chunk boundaries becomes undetectable |
| JWT startup entropy check + denylist | Missing/weak secret = crash at boot, not silent runtime failure |
| PyMuPDF AGPL | Proceed; licensing handled separately by team |

### Pitfalls to Avoid

- IVFFlat index — recall degrades with incremental inserts; use HNSW; set `work_mem='256MB'`
- Tenant data leakage — enforce RLS at vector store level, not only at API layer
- asyncio silent drops — always attach `add_done_callback` to every `create_task()`
- slowapi middleware-only — `@limiter.limit()` decorator required per-route; middleware is LIFO
- Singleton leakage in tests — call `cache_clear()` in teardown after `dependency_overrides.clear()`
- HNSW vector UPDATE — always DELETE + INSERT; schedule periodic `REINDEX`
- Eval contamination — never generate QA pairs from documents in the retrieval index; 20% holdout first

### Open Questions

1. PyMuPDF commercial license — needed for enterprise on-premise before shipping image extraction?
2. ARQ worker process (separate Docker service) vs. `asyncio.create_task + Redis` — ops overhead decision
3. LLM captioning cost at ingest scale — per-document budget, or CLIP as default?
4. Eval holdout set — 20% of current documents available, or entirely synthetic bootstrap needed?
5. asyncpg pool compatibility with RLS — `app.current_tenant` must be set per-connection; verify against current pool config

### Blockers

None at project start.

### Todos

- Start Phase 1 planning: `/gsd-plan-phase 1`

## Session Continuity

**Last updated:** 2026-04-21 — Roadmap initialized
**Next action:** Run `/gsd-plan-phase 1` to generate the execution plan for pgvector Foundation
