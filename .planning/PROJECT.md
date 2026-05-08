# EnterpriseRAG

## What This Is

EnterpriseRAG is a production-grade Retrieval-Augmented Generation platform built on FastAPI. It serves enterprise tenants with multi-tenant document ingestion (6-stage pipeline), hybrid retrieval (dense + BM25, RRF fusion), LLM-powered query answering, and advanced operational features (A/B testing, audit logging, OIDC auth, annotation queues, streaming SSE).

v1.0 Hardening shipped: the system now runs on PostgreSQL+pgvector (no Qdrant), enforces JWT/PII/rate-limit security at startup, surfaces all exceptions through structured logging, extracts and indexes PDF-embedded images, supports async ingest with job status polling, and has 263 unit tests with a RAGAS eval gate.

v1.1 Retrieval Depth & Frontend shipped: closed the image-only-PDF retrieval gap (PP-StructureV3 OCR + section-aware metadata + page/section query filter), extracted the inline UI to a static asset served via FastAPI StaticFiles, and added a diff-coverage gate that holds new code at ≥ 80% without blocking on legacy.

v1.2 Agentic Layer + Swarm shipped: `agent_mode=True` now executes the real tool-use loop on both OpenAI and Anthropic providers. `BaseLLMClient.call_agentic_turn` abstraction added; Anthropic-only fallback removed; `asyncio.gather` parallel burst executes N ≥ 2 tool calls concurrently per turn.

## Current State

- ✅ **v1.0 Hardening** shipped 2026-04-27 — [archive](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Retrieval Depth & Frontend** shipped 2026-05-08 — [archive](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Agentic Layer + Swarm** shipped 2026-05-08 — [archive](milestones/v1.2-ROADMAP.md)

## Current Milestone: v1.3 Fork Swarm, NLU & Quality

**Goal:** Upgrade `agent_mode` to true multi-agent fork swarm with isolated sub-agent contexts, add LLM filter fallback for missed regex queries, modernize the frontend to multi-file + clean DOM, and raise test coverage to 70%.

**Target features:**
- AGENT-03: True fork-agent swarm — coordinator spawns N sub-agents, each with isolated message history, tool registry, and iteration budget; builds on v1.2 `call_agentic_turn` baseline
- NLU-02: LLM-based filter extractor — regex-first; LLM called only when regex returns empty (confidence-gated, zero cost on hits); extends `services/nlu/filter_extractor.py`
- UI-02: Frontend mid-modernization — JS/CSS split to `static/ui.js` + `static/ui.css`; modern DOM API cleanup; possibly lightweight bundler (Vite/esbuild); no React/Vue; `static/ui.html` stays as entry point
- TEST-04: `coverage combine` across unit + integration pipelines
- TEST-06: raise global coverage floor 46% → 70%

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

**v1.1 Retrieval Depth & Frontend**
- ✓ PP-StructureV3 layout-aware OCR for scanned PDFs (OCR-01) — v1.1
- ✓ Async-safe OCR with bounded concurrency + Docker-baked models (OCR-02) — v1.1
- ✓ Section-heading enrichment in chunk content; `section_id`/`section_title` in metadata (META-01) — v1.1
- ✓ pgvector JSONB filter retrieval with HNSW iterative_scan + GUCs + B-tree expression indexes (META-02) — v1.1
- ✓ Regex-first Chinese query filter extractor for `第N页` / `第N.M节` (QUERY-01) — v1.1
- ✓ Inline `_UI_HTML` extracted to `static/ui.html`, served via FastAPI StaticFiles mount (UI-01) — v1.1
- ✓ `diff-cover` ≥ 80% gate on v1.1-touched files; legacy 46% floor preserved as informational (TEST-03) — v1.1

**v1.2 Agentic Layer + Swarm**
- ✓ Provider-neutral `BaseLLMClient.call_agentic_turn` — `AgenticTurn` + `ToolCall` Pydantic V2 models; default-raise on base, implemented by both adapters (AGENT-01) — v1.2
- ✓ `AnthropicLLMClient.call_agentic_turn` + `OpenAILLMClient.call_agentic_turn` — wire differences absorbed inside adapters; Anthropic-only gate at `pipeline.py:599-604` removed (AGENT-01) — v1.2
- ✓ `asyncio.gather` parallel tool-call burst; parallelism factor logged per turn; tool result correlation via `tool_call.id` (AGENT-02) — v1.2
- ✓ 7 hand-curated wire fixtures (4 Anthropic + 3 OpenAI); 13-test parametrized suite + integration test (AGENT-01/02) — v1.2

### Active

- [ ] **AGENT-03**: Fork-agent swarm — coordinator spawns N sub-agents with isolated context per sub-question
- [ ] **NLU-02**: LLM-based filter extractor — confidence-gated LLM fallback when regex returns empty
- [ ] **UI-02**: Frontend multi-file split (JS/CSS); modern DOM API cleanup; possibly Vite/esbuild
- [ ] **TEST-04**: `coverage combine` across unit + integration pipelines
- [ ] **TEST-06**: Raise global coverage floor 46% → 70%

**Carried over (not milestone-scoped, still tracked):**
- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10 live PR through CI confirms `coverage-diff` step + HTML artifact (natural confirmation on first PR)
- [ ] Push tags `v1.1` and `v1.2` to origin (currently local-only)
- [ ] PR #1 + PR #2 review + merge

### Out of Scope

- Milvus / ChromaDB backends — pgvector is the target; no need to maintain others
- Multi-region tenant isolation — single-region RLS sufficient until scale requires it
- Additional auth providers — existing OIDC integration covers enterprise needs
- Automatic eval dataset generation pipeline — manual bootstrap sufficient for v1
- LLM-based filter extractor — regex-only in v1.1; LLM fallback deferred to v1.3 (NLU-02)
- React/Vue/Streamlit frontend — single static HTML is the v1.1 ceiling
- 80% coverage on legacy modules — v1.1 only gates new code (TEST-03)
- MinerU / raw PP-OCRv5 alternatives to PP-StructureV3 — research recommends PP-StructureV3

## Context

**Codebase state:** ~5000+ lines of service code (Python/FastAPI). All core infrastructure shipped across v1.0–v1.2.

**Vector store:** PostgreSQL + pgvector with HNSW index. Qdrant fully removed.

**Agentic layer:** `agent_mode=True` functional on both OpenAI and Anthropic. `AgentQueryPipeline` uses `call_agentic_turn` abstraction + `asyncio.gather` parallel burst. `services/pipeline.py:599-604` gate removed.

**Testing:** 263+ unit tests; diff-cover ≥ 80% gate on v1.1+ files; 46.63% global coverage floor (legacy). CI pipeline: lint → unit → integration → security scan → Docker build → eval gate (main only).

**Known issues / tech debt:**
- HNSW UPDATE path: always DELETE + INSERT; schedule periodic `REINDEX`
- PyMuPDF commercial license: needed for enterprise on-premise
- `agent_mode: bool = False` field in `utils/models.py:215` stays as toggle; the old Anthropic gate it guarded is gone

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
| PP-StructureV3 over raw PP-OCRv5 (v1.1) | Layout + table + reading-order recovery in one pipeline; right granularity for GB national-standard PDFs | ✓ Good — Phase 7 |
| Bake OCR models into Docker image (v1.1) | Cold-start download is 10–60s and flaky behind enterprise proxies; image size delta acceptable | ✓ Good — Phase 7 |
| Section heading text in embedded content; numeric IDs in metadata only (v1.1) | High-cardinality numerics (page_number) dilute embeddings; heading words help recall | ✓ Good — Phase 8 D-02 |
| pgvector `hnsw.iterative_scan = strict_order` + raised `ef_search` when filter active (v1.1) | Default post-filter recall collapses on selective filters; iterative scan keeps walking HNSW until k matches found | ✓ Good — Phase 8 |
| Regex-first query filter extractor, no LLM (v1.1) | 100% deterministic, zero per-query cost; LLM fallback deferred to v1.2 | ✓ Good — Phase 8 |
| Static HTML via FastAPI StaticFiles, no bundler (v1.1) | v1.1 ceiling is "edit like a normal frontend file" — no React/Vue/build step | ✓ Good — Phase 9 |
| `static/index.html → ui.html` symlink (v1.1) | `StaticFiles(html=True)` looks for `index.html`; symlink preserves SC #1 file-name AND makes SC #2 work | ✓ Good — Phase 9 (deviation surfaced at executor checkpoint) |
| Diff-cover gate on touched files only (v1.1) | Legacy 46% floor stays as informational; v1.1 does not block on legacy code | ✓ Good — Phase 10 |
| CI vs `v1.0` tag, local vs `origin/master` (v1.1) | REQ baseline-vs-milestone-delta in CI; SC dev-loop ref locally; each ref serves its written use case | ✓ Good — Phase 10 D-01/D-02 split |
| Non-abstract default-raise `call_agentic_turn` on `BaseLLMClient` (v1.2) | Avoids breaking subclasses that don't need agentic mode; `NotImplementedError` is the safe fallback | ✓ Good — Phase 11 |
| `_RAW_DICT_FIELDS = {"input"}` lock in `ToolCall` model (v1.2) | Prevents Pydantic from coercing opaque `input` dict into typed model; preserves arbitrary tool schemas | ✓ Good — Phase 11 |
| Wire fixtures hand-curated against real provider SDKs (v1.2) | Tests exercise actual parsing logic against real response shapes; generated fixtures would miss format nuances | ✓ Good — Phase 11-02 |
| `parallel_tool_calls=True` explicit in OpenAI; `disable_parallel_tool_use=False` explicit in Anthropic (v1.2) | Defaults exist on both, but explicit makes the contract auditable and self-documenting | ✓ Good — Phase 11 |
| `zip(turn.tool_calls, tool_outputs)` for result correlation (v1.2) | Preserves `tool_call.id` round-trip without additional bookkeeping; order-stable under `asyncio.gather` | ✓ Good — Phase 11-04 |

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
*Last updated: 2026-05-08 — v1.3 milestone started (Fork Swarm, NLU & Quality)*
