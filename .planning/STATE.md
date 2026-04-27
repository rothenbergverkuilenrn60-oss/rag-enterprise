---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Retrieval Depth & Frontend
status: in_progress
stopped_at: "v1.1 roadmap created; awaiting Phase 7 planning"
last_updated: "2026-04-27T18:00:00Z"
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# STATE — EnterpriseRAG v1.1 Retrieval Depth & Frontend

## Project Reference

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** Phase 7 — OCR Engine Integration (PP-StructureV3 + async/concurrency/baked models)

## Current Position

Phase: 7
Plan: Not started
Phase status: Not started

| Field | Value |
|-------|-------|
| Milestone | v1.1 Retrieval Depth & Frontend |
| Current phase | 7 — OCR Engine Integration |
| Current plan | Not started |
| Phase status | Not started |
| Overall progress | 0/4 phases (v1.1) |

```
Progress: [          ] 0%
```

## Phase Overview

| Phase | Status |
|-------|--------|
| 7. OCR Engine Integration | Not started |
| 8. Multimodal Metadata + Query Filter | Not started |
| 9. Frontend Extraction | Not started |
| 10. Coverage Gate on New Code | Not started |

## Performance Metrics

| Metric | Value |
|--------|-------|
| Phases completed (v1.1) | 0/4 |
| Requirements complete (v1.1) | 0/7 |
| Plans executed (v1.1) | 0 |

## Accumulated Context

### Key Decisions Logged (v1.1)

| Decision | Rationale |
|----------|-----------|
| PP-StructureV3 over raw PP-OCRv5 | Layout + table + reading-order recovery in one pipeline; right granularity for GB national-standard PDFs |
| Bake OCR models into Docker image | Cold-start download is 10–60s and flaky behind enterprise proxies; image size delta (~600MB–1.2GB) is acceptable |
| Singleton + asyncio.to_thread + bounded semaphore | PP-StructureV3 has no documented thread safety; this is the safe contract under FastAPI/ARQ |
| Section heading text in embedded content; numeric IDs in metadata only | High-cardinality numerics (page_number) dilute embeddings; heading words help recall (verified anti-pattern via LlamaIndex guidance) |
| pgvector `hnsw.iterative_scan = relaxed_order` + raised `ef_search` when filter active | Default post-filter recall collapses on selective filters; iterative scan keeps walking the HNSW graph until k matches found |
| Regex-first query filter extractor (no LLM in v1.1) | 100% deterministic, zero per-query cost; LLM fallback deferred to v1.2 |
| Static HTML via FastAPI StaticFiles (no bundler) | v1.1 ceiling is "edit like a normal frontend file" — no React/Vue/build step |
| Diff-cover gate on touched files only | Legacy 46% floor stays as informational; v1.1 does not block on legacy code |

### Pitfalls to Avoid (v1.1)

- PaddleOCR is **not thread-safe** — never call `predict()` from multiple threads on the same instance
- Forgetting `hnsw.iterative_scan` is the silent killer — `page_number=63` filter on default `ef_search=40` returns near-zero results
- Do not prepend "Page 63 — section 3.10:" into embedded text — verified to dilute recall
- CMYK is an *image-extraction* problem, not an OCR problem — full-page rasterization in PP-StructureV3 renders to RGB regardless of source colorspace
- Model warmup latency 10–60s on cold start — pre-warm in ARQ worker `on_startup`
- Section IDs in GB docs use multiple formats (`3.10`, `附录A.1`, `表5`) — start with `\d+\.\d+`, extend from real query logs; do not over-engineer upfront
- `ef_search=200` raises latency 3–5x — acceptable for v1.1 single-tenant low-QPS, revisit when scaling

### Open Questions (v1.1)

1. OCR worker placement — same ARQ pool with separate `ocr_queue` vs separate container? (research leans separate container)
2. PP-StructureV3 vs MinerU/Marker/Surya — flag for follow-up if PaddleOCR latency proves unacceptable on real GB PDFs
3. Section ID extraction — trust PP-StructureV3 `block_order` heading detection or run regex `^第?\d+(\.\d+)*\s+...` over markdown output? (recommend regex over markdown, fall back to V3 blocks)
4. paddlepaddle exact patch pin (3.0.0 vs 3.0.1) — needs `pip install --dry-run` on actual build host before locking Dockerfile
5. `hnsw.ef_search=200` is a guess — needs eval set with known page/section ground truth

### Blockers

None.

### Todos

- Plan Phase 7: `/gsd-plan-phase 7`

## Session Continuity

**Last updated:** 2026-04-27 — v1.1 roadmap drafted (4 phases, 7 requirements mapped, coverage validated)
**Stopped at:** ROADMAP.md and STATE.md written for v1.1; REQUIREMENTS.md traceability populated
**Next action:** `/gsd-plan-phase 7` to plan OCR Engine Integration

**Planned Phase:** 7 (OCR Engine Integration) — plans TBD — 2026-04-27T18:00:00Z
