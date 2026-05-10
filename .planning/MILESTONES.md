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

---

## v1.1 Retrieval Depth & Frontend — 2026-05-08

**Shipped:** 2026-05-08
**Phases:** 7–10 | **Plans:** 9 | **Commits:** (stacked — PR #1)
**Timeline:** 2026-05-08 → 2026-05-08 (1 day)

**Delivered:** Closed the image-only-PDF retrieval gap with PP-StructureV3 layout-aware OCR, added section-aware metadata and JSONB filter retrieval, extracted the inline UI to a static HTML file served via FastAPI StaticFiles, and added a diff-coverage gate holding new code at ≥ 80% without blocking on legacy.

**Key accomplishments:**
1. PP-StructureV3 layout-aware OCR for scanned PDFs — section headings, tables, and reading order recovered in one pipeline (OCR-01, OCR-02)
2. Section heading text embedded in chunk content; `section_id`/`section_title` in JSONB metadata with B-tree expression indexes (META-01)
3. pgvector HNSW `iterative_scan = strict_order` + raised `ef_search` for JSONB filter queries — recall preserved under selective filters (META-02)
4. Regex-first Chinese query filter extractor for `第N页`/`第N.M节` patterns (QUERY-01)
5. `static/ui.html` extracted from inline `_UI_HTML`; served via FastAPI `StaticFiles`; `index.html → ui.html` symlink (UI-01)
6. `diff-cover ≥ 80%` gate on v1.1-touched files; legacy 46% floor preserved as informational (TEST-03)

**Known deferred items:** None at close.

**Archive:** [milestones/v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md) · [milestones/v1.1-REQUIREMENTS.md](milestones/v1.1-REQUIREMENTS.md)

---

## v1.2 Agentic Layer + Swarm — 2026-05-08

**Shipped:** 2026-05-08
**Phases:** 11 | **Plans:** 4 | **Commits:** (stacked — PR #2)
**Timeline:** 2026-05-08 → 2026-05-08 (1 day)

**Delivered:** Made `agent_mode=True` a real product feature for both OpenAI and Anthropic providers — removed the Anthropic-only gate in `pipeline.py`, abstracted `call_agentic_turn` behind a provider-neutral interface, and added `asyncio.gather` parallel tool-call burst so multi-dimension queries execute N tools concurrently.

**Key accomplishments:**
1. `ToolCall` + `AgenticTurn` Pydantic V2 frozen models in `utils/models.py` — provider-neutral wire shape for all agentic turn data (Plan 11-01)
2. 7 hand-curated wire-format JSON fixtures (4 Anthropic + 3 OpenAI) in `tests/unit/fixtures/agentic_turn/` — realistic API response mocking (Plan 11-02)
3. `AnthropicLLMClient.call_agentic_turn` + `OpenAILLMClient.call_agentic_turn` — wire differences absorbed inside each adapter; 13-test parametrized suite (Plan 11-03)
4. `AgentQueryPipeline.run` refactored onto `call_agentic_turn`; Anthropic-only fallback at `pipeline.py:599-604` removed; `asyncio.gather` parallel burst with audit log (Plan 11-04)

**Known deferred items:** None at close (AGENT-03 swarm deferred by design to v1.3).

**Archive:** [milestones/v1.2-ROADMAP.md](milestones/v1.2-ROADMAP.md) · [milestones/v1.2-REQUIREMENTS.md](milestones/v1.2-REQUIREMENTS.md)

---

## v1.3 Fork Swarm, NLU & Quality — 2026-05-09

**Shipped:** 2026-05-09
**Phases:** 12–15 | **Plans:** 9 | **Commits:** 48
**Timeline:** 2026-04-27 → 2026-05-09 (12 days)
**Audit:** [v1.3-MILESTONE-AUDIT.md](milestones/v1.3-MILESTONE-AUDIT.md) — 5/5 requirements satisfied · status `tech_debt`

**Delivered:** Upgraded `agent_mode` to true multi-agent fork swarm with isolated sub-agent contexts, added an LLM filter-extractor fallback for natural-language section references the regex misses, modernized the frontend to multi-file with `addEventListener` wiring, and raised the CI coverage floor from 46% to 70% backed by combined unit + integration measurement.

**Key accomplishments:**
1. `SwarmQueryPipeline` — coordinator decomposes multi-dimension queries into N sub-questions; N independent sub-agents run isolated `call_agentic_turn` loops concurrently via `asyncio.gather`; synthesis LLM produces unified answer; `MAX_SWARM_AGENTS=5` + `MAX_SWARM_TURNS_PER_AGENT=5` caps; per-swarm audit log (AGENT-03)
2. `FilterExtractor` class composes regex-first then LLM-fallback for natural-language section references; cache layer reuses `utils/cache.py` (zero hand-rolled MD5/Redis); `fallback_source` traces which path produced the filter; 4/4 pipeline callsites migrated to async (NLU-02)
3. `static/ui.html` split into `static/ui.css` + `static/ui.js` (IIFE-wrapped, addEventListener wiring); inline event handlers eliminated; main.py + StaticFiles symlink unchanged (UI-02)
4. CI 3-job coverage topology: `unit-tests` writes `.coverage.unit`, `integration-tests` writes `.coverage.integration` with `--cov-append` + `continue-on-error: true`, new `coverage-combine` job (`needs: [unit-tests, integration-tests]`, `if: always()`) runs combine + 70% floor + diff-cover; pyproject `[tool.coverage.*]` config with `fail_under = 70`, `show_missing = true`, `parallel = false` (Pitfall 1) (TEST-04)
5. Wave 2 backfill: 20 services/ modules below 70% at v1.2 close received new unit test files (one happy + one error path each); combined coverage 53.2% → 71.9% (+18.7pp); `coverage report --fail-under=70` exits 0 (TEST-06)
6. Phase 15 SECURITY audit: 14 STRIDE threats verified — 9 mitigated (CI-gate hard-coding, debug step audit trail, consumer-path mocking, secret-pattern grep clean, auth path coverage), 5 accepted (inherited GitHub Actions trust, artifact retention, pytest --timeout, measure-then-plan boundary)

**Known deferred items:** 3 v1.4 follow-ups documented in v1.3-MILESTONE-AUDIT.md — (1) extract `_execute_tool_call` to shared helper between SwarmQueryPipeline + AgentQueryPipeline, (2) browser smoke test for UI-02 visual regression at first deploy, (3) lift 5 large modules (pipeline, llm_client, vector_store, retriever, extractor) above per-module 70% via deep mocking or live-service integration tests.

**Archive:** [milestones/v1.3-ROADMAP.md](milestones/v1.3-ROADMAP.md) · [milestones/v1.3-REQUIREMENTS.md](milestones/v1.3-REQUIREMENTS.md) · [milestones/v1.3-MILESTONE-AUDIT.md](milestones/v1.3-MILESTONE-AUDIT.md)
