# EnterpriseRAG

## What This Is

EnterpriseRAG is a production-grade Retrieval-Augmented Generation platform built on FastAPI. It serves enterprise tenants with multi-tenant document ingestion (6-stage pipeline), hybrid retrieval (dense + BM25, RRF fusion), LLM-powered query answering, and advanced operational features (A/B testing, audit logging, OIDC auth, annotation queues, streaming SSE).

v1.0 Hardening shipped: the system now runs on PostgreSQL+pgvector (no Qdrant), enforces JWT/PII/rate-limit security at startup, surfaces all exceptions through structured logging, extracts and indexes PDF-embedded images, supports async ingest with job status polling, and has 263 unit tests with a RAGAS eval gate.

v1.1 Retrieval Depth & Frontend shipped: closed the image-only-PDF retrieval gap (PP-StructureV3 OCR + section-aware metadata + page/section query filter), extracted the inline UI to a static asset served via FastAPI StaticFiles, and added a diff-coverage gate that holds new code at ≥ 80% without blocking on legacy.

v1.2 Agentic Layer + Swarm shipped: `agent_mode=True` now executes the real tool-use loop on both OpenAI and Anthropic providers. `BaseLLMClient.call_agentic_turn` abstraction added; Anthropic-only fallback removed; `asyncio.gather` parallel burst executes N ≥ 2 tool calls concurrently per turn.

v1.5 Web Search + Multi-Agent Debate + Coverage Lift shipped: replaced the v1.4 `WebSearchTool` placeholder with a real Tavily-backed implementation behind the same `BaseTool` ABC; introduced AGENT-05 verifier sub-agent that runs after `SwarmQueryPipeline`'s peer fan-out when `req.debate=True` and surfaces evidence-supported divergence; raised five high-traffic modules above per-module ≥70% line coverage and wired CI to enforce a per-module floor on combined coverage data.

## Current State

- ✅ **v1.0 Hardening** shipped 2026-04-27 — [archive](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Retrieval Depth & Frontend** shipped 2026-05-08 — [archive](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Agentic Layer + Swarm** shipped 2026-05-08 — [archive](milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Fork Swarm, NLU & Quality** shipped 2026-05-09 — [archive](milestones/v1.3-ROADMAP.md)
- ✅ **v1.4 Agent-First Architecture Inversion** shipped 2026-05-10 — [archive](milestones/v1.4-ROADMAP.md)
- ✅ **v1.5 Web Search + Multi-Agent Debate + Coverage Lift** shipped 2026-05-11 — [archive](milestones/v1.5-ROADMAP.md)
- ✅ **v1.6 Memory Tool — Agent-Authored Long-Term Facts** shipped 2026-05-17 — [archive](milestones/v1.6-ROADMAP.md)

## Current Milestone: v1.7 Memory Tech-Debt Burn-Down

**Goal:** Knock out all 7 deferred items surfaced at v1.6 ship — keep the memory subsystem production-clean before adding more features. No new user-facing capabilities; pure refactor + reliability.

**Target features:**
- `audit_log` table auto-create + `?ssl=disable` helper centralization + bge-m3 model dir layout fix (infra hygiene)
- Per-test `create_app()` factory (kill module-level singleton graph + FastAPI app singleton; cheap test isolation)
- `save_fact` near-duplicate guard (`<embedding> <=> $vec < 0.05` precheck) + `save_facts(list[ExtractedFact])` batch path (1× embed + executemany)
- Redis-mock fixture rollout (kill 32 pre-existing Redis-dependent unit-test failures)
- End-of-milestone doc + CHANGELOG sweep (README, ARCHITECTURE.md, dev runbook for touched modules)

**Key context (locked):**
- All 8 items originate from v1.6 known-deferred list (no scope creep)
- Continues phase numbering: v1.7 starts at **Phase 26** (no `--reset-phase-numbers` flag)
- Carry-forward gates still apply: `diff-cover ≥ 80%` on touched files, combined coverage `--fail-under=70`
- Zero production behavior change required — every refactor must preserve existing API + DB contracts; verified via regression tests on each touched module
- GSD subagents NOT installed → roadmap generated inline (per init JSON `agents_installed: false`)

**Carried forward (NOT v1.7 scope — tracked for v1.8+):**
- Code-acting / SQLTool (10x roadmap #4) — sandbox selection still unresolved
- RLS on `long_term_facts` + asyncpg pool `app.current_tenant` production verification
- SSE memory events (memory.extracted, memory.recalled)
- Per-tenant capacity overrides / importance decay
- UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke
- Per-module coverage floor raise (>70%) or branch-coverage activation
- PyMuPDF AGPL commercial licensing
- Docker Build CI fix (paddleocr / paddlex / paddlepaddle ABI churn — currently `continue-on-error: true`)

## Previous Milestone (Archived): v1.6 Memory Tool — Agent-Authored Long-Term Facts

**Shipped:** 2026-05-17 (PRs #5 + #7 + #8 squash-merged).

<details>
<summary>v1.6 milestone scope (collapsed — see <a href="milestones/v1.6-ROADMAP.md">archive</a> for full snapshot)</summary>

**Goal:** Ship 10x roadmap #1 (Memory tool) as agent-callable durable facts — background extractor writes, pgvector RecallTool reads, capacity-cap eviction bounds growth.

**Delivered:**
- **Background ExtractorAgent** — post-turn `asyncio.create_task` non-blocking dispatch; adversarial refusal for prompt-injection; importance buckets {0.2, 0.5, 0.8}; reuses `services/agent/verifier.py` provider-singleton pattern
- **pgvector RecallTool** — 4th tool in `AGENT_TOOL_ALLOWLIST`; `LongTermMemory.get_relevant_facts()` rewritten from popularity-rank to semantic cosine; `hnsw.iterative_scan = strict_order` + `ef_search` pattern reused; 4 `load_context` call sites in `services/pipeline.py` regression-tested
- **Eviction CLI + GDPR forget API** — `scripts/evict_long_term_facts.py` chunked importance-ASC eviction (audit-mode-before-enforce); `DELETE /api/v1/memory/forget` admin-or-self auth + `X-Confirm-Delete` header; audit-log entry per call (audit-write failure does NOT block GDPR action)

**Known deferred (now scoped into v1.7):** audit_log auto-create; per-test create_app factory; asyncpg_helper.py centralization; save_fact dedupe guard; save_facts batch path; Redis-mock fixture; bge-m3 dir layout.

</details>

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

**v1.3 Fork Swarm, NLU & Quality**
- ✓ `SwarmQueryPipeline` with coordinator decomposition + N independent sub-agents (isolated `messages`, tool registry, iteration budget) running concurrently via `asyncio.gather`; synthesis LLM produces unified answer; `MAX_SWARM_AGENTS=5` + `MAX_SWARM_TURNS_PER_AGENT=5` caps; per-swarm audit log (AGENT-03) — v1.3
- ✓ `FilterExtractor` class composes regex-first then LLM-fallback for natural-language section references (e.g., "关于第三章的内容"); cache layer reuses `utils/cache.py`; `fallback_source` traces path; 4/4 pipeline callsites migrated to async (NLU-02) — v1.3
- ✓ `static/ui.html` split into `static/ui.css` + `static/ui.js` (IIFE-wrapped, addEventListener wiring); inline event handlers eliminated; main.py + StaticFiles symlink unchanged; AC#6 visual regression accepted on mechanical proxies pending first-deploy browser smoke (UI-02) — v1.3
- ✓ CI 3-job coverage topology: `unit-tests` writes `.coverage.unit`, `integration-tests` writes `.coverage.integration` with `--cov-append` + `continue-on-error: true`, new `coverage-combine` job runs `combine + report --fail-under=70 + diff-cover`; pyproject `[tool.coverage.*]` config (`fail_under = 70`, `show_missing = true`, `parallel = false`) (TEST-04) — v1.3
- ✓ Combined coverage 53.2% → 71.9% (+18.7pp); 20 services/ modules below 70% at v1.2 close received new unit test files (one happy + one error path each); `coverage report --fail-under=70` exits 0 (TEST-06) — v1.3

**v1.4 Agent-First Architecture Inversion**
- ✓ `AgentQueryPipeline` refactored into `Planner` + `Executor` + `Synthesizer` collaborators; preserves v1.2/v1.3 multi-tenant, audit, JWT, RLS invariants (AGENT-06) — v1.4 Phase 16
- ✓ `_execute_tool_call` extracted to shared helper used by both `SwarmQueryPipeline` and the new `Executor` (AGENT-09) — v1.4 Phase 16
- ✓ Query intent classification subsumed by planner's `ToolPlan` output (no separate `IntentRouter` class) (NLU-03) — v1.4 Phase 16
- ✓ `BaseTool` ABC + `ToolRegistry` + `RetrieveTool` (`search_knowledge_base`) + `RefinedRetrieveTool` (`refine_search`) shipped; `WebSearchTool` placeholder registered but excluded from `AGENT_TOOL_ALLOWLIST` (AGENT-07) — v1.4 Phase 17
- ✓ SSE planner trace event stream at `POST /api/v1/agent/v1/run/stream`: `planner.plan`, `tool.span.start/end/error`, `executor.parallel`, `synthesizer.final`; schemas documented in `docs/agent-architecture.md` (AGENT-04) — v1.4 Phase 18
- ✓ Agent-first README rewrite + `docs/agent-architecture.md` (planner/executor model + tool authoring + SSE event schema) + `make demo-agent` target + recorded `docs/demo.cast` (AGENT-08) — v1.4 Phase 19

**v1.6 Memory Tool — Agent-Authored Long-Term Facts**
- ✓ `long_term_facts` table + `embedding vector(1024)` column + HNSW cosine index (MEM-01) — v1.6 Phase 23
- ✓ `LongTermMemory.save_fact` embedding-on-write + narrow `asyncpg.PostgresError` + typed `MemoryFactWriteError` (MEM-02) — v1.6 Phase 23
- ✓ Extractor sub-agent prompt + JSON-mode + adversarial refusal (MEM-03 + MEM-05) — v1.6 Phase 23
- ✓ Post-turn dispatch via `asyncio.create_task` non-blocking (MEM-04) — v1.6 Phase 23
- ✓ `LongTermMemory.get_relevant_facts()` semantic cosine query + `hnsw.iterative_scan = strict_order` + raised `ef_search` (MEM-06) — v1.6 Phase 24
- ✓ `scripts/backfill_fact_embeddings.py` idempotent backfill (MEM-07) — v1.6 Phase 24
- ✓ `services/agent/tools/recall.py::RecallTool` registered + `AGENT_TOOL_ALLOWLIST` grows 3→4 (MEM-08 + MEM-09) — v1.6 Phase 24
- ✓ `load_context` semantic-shift documented + regression-tested at 4 call sites (MEM-10) — v1.6 Phase 24
- ✓ `scripts/evict_long_term_facts.py` chunked importance-ASC eviction CLI (EVICT-01) — v1.6 Phase 25
- ✓ Audit-mode-before-enforce discipline + `--mode={audit,enforce}` (EVICT-02) — v1.6 Phase 25
- ✓ `docs/memory-eviction.md` 49→178 LOC: CronJob YAML + cap tuning + audit→enforce + backfill ref + forget-API curl (EVICT-03) — v1.6 Phase 25
- ✓ `LongTermMemory.forget_user` chunked DELETE @ 1000/txn + typed `MemoryForgetError` (GDPR-01) — v1.6 Phase 25
- ✓ Admin `DELETE /api/v1/memory/forget` endpoint + admin-or-self auth + `X-Confirm-Delete` header (GDPR-02) — v1.6 Phase 25
- ✓ Audit-log entry per forget — actor + target + row count + timestamp; audit-write failure does NOT block GDPR action (GDPR-03 + T1) — v1.6 Phase 25

### Active

**v1.7 Memory Tech-Debt Burn-Down (in planning — phases to be derived from these 8 requirements):**
- [ ] **TD-01**: `audit_log` table auto-creates on `audit_service` startup (port `_create_tables` from `LongTermMemory`)
- [ ] **TD-02**: Per-test `create_app()` factory eliminates module-level singleton graph + FastAPI app singleton; per-test isolation no longer requires monkeypatch
- [ ] **TD-03**: `utils/asyncpg_helper.py` centralizes `?ssl=disable` URL-param strip; `memory_service` + `audit_service` consume the helper (no duplicated logic)
- [ ] **TD-04**: `save_fact` near-duplicate guard via `<embedding> <=> $vec < 0.05` precheck (eng-review A3 from Phase 23)
- [ ] **TD-05**: `save_facts(list[ExtractedFact])` batch path uses 1× `embed_batch` + `executemany` (replaces 3× round-trips per turn)
- [ ] **TD-06**: Redis-mock fixture rollout closes the 32 pre-existing Redis-dependent unit-test failures
- [ ] **TD-07**: bge-m3 model dir layout fix — code path matches HF cache layout natively (no symlink workaround)
- [ ] **DOC-01**: Doc + CHANGELOG sweep — README, ARCHITECTURE.md, dev runbook refreshed for all touched modules; v1.7 CHANGELOG entry added

**v1.6 Memory Tool — Agent-Authored Long-Term Facts (validated, see above)**

**v1.5 Web Search + Multi-Agent Debate + Coverage Lift (validated, moved below)**

**v1.4 Agent-First Architecture Inversion (now validated, moved below)**

**Carried over (not v1.7-scoped, still tracked):**
- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9/14 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10/15 live PR through CI confirms `coverage-combine` job + HTML artifact (natural confirmation on first PR)
- [ ] Push tags `v1.1`, `v1.2`, `v1.3` to origin (currently local-only)
- [ ] v1.6+ follow-up: Memory tool (10x roadmap #1) — needs `/office-hours` first
- [ ] v1.6+ follow-up: Code-acting / SQLTool (10x roadmap #4) — sandbox selection unresolved
- [ ] v1.6+ follow-up: UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke test

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

**Codebase state:** ~5500+ lines of service code (Python/FastAPI). All core infrastructure shipped across v1.0–v1.3.

**Vector store:** PostgreSQL + pgvector with HNSW index. Qdrant fully removed.

**Agentic layer:** `agent_mode=True` functional on both OpenAI and Anthropic via `AgentQueryPipeline` (single agent) + `SwarmQueryPipeline` (N isolated sub-agents, parallel via `asyncio.gather`). Both built on the v1.2 `call_agentic_turn` abstraction. Routing: controllers/api.py uses `swarm > agent > default` precedence chain.

**NLU layer:** Filter extractor uses regex-first then LLM-fallback (`FilterExtractor` class). Cache layer reuses `utils/cache.py`. Cost on regex hits stays zero.

**Frontend:** `static/ui.html` references `static/ui.css` + `static/ui.js` (IIFE-wrapped). Inline `<script>`/`<style>` blocks and event handlers eliminated. main.py + StaticFiles symlink unchanged. No bundler.

**Testing:** 622 unit tests; combined unit + integration coverage 71.9%; CI gates `coverage report --fail-under=70` (global floor) + `diff-cover --fail-under=80` (per-file new code). CI pipeline: lint → unit-tests (writes `.coverage.unit`) → integration-tests (writes `.coverage.integration` with `--cov-append`, `continue-on-error: true`) → coverage-combine (combines + enforces both gates) → security scan → Docker build → eval gate (main only).

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
| `AgentQueryPipeline` body byte-identical to v1.2 baseline (v1.3 D-01) | Swarm is a separate pipeline class; preserving AgentQueryPipeline avoids regression risk on v1.2 contract | ✓ Good — Phase 12 |
| Sub-agents do NOT inherit chat history (v1.3 D-06) | True context isolation; one sub-question's noise cannot crowd another's reasoning | ✓ Good — Phase 12 |
| `BaseException` (not `Exception`) for asyncio.gather isolation (v1.3) | Covers `CancelledError` / `TimeoutError`; otherwise sub-agent cancellation propagates to swarm | ✓ Good — Phase 12 |
| `_execute_tool_call` duplicated verbatim between SwarmQueryPipeline + AgentQueryPipeline (v1.3) | Verified token-equivalent at commit `1664c42` via inspect.getsource normalized comparison; refactor deferred to v1.4 | ⚠ Revisit — extract shared helper in v1.4 |
| `FilterExtractor` composes regex-first then LLM (v1.3 D-11) | Single decision tree; preserves zero-cost regex behavior; LLM only on miss | ✓ Good — Phase 13 |
| Existing regex `extract_filters` AST byte-identical post-Wave-1 (v1.3 D-02) | Preserves freeze contract from v1.1 QUERY-01; new FilterExtractor wraps not replaces | ✓ Good — Phase 13 |
| Mock at consumer path (`services.<mod>.<dep>`) not source (v1.3) | Tests exercise real module code; only stubs external boundaries; established by Phase 13 plan-checker | ✓ Good — Phase 13 + reused in Phase 15 |
| Frontend AC#6 visual regression accepted on mechanical proxies (v1.3) | Sandbox lacks browser tooling; CSS byte-identical, JS preserves semantics, HTML shell intact, all 4 paths return HTTP 200; live smoke at first deploy | ⚠ Revisit — first-deploy browser smoke test |
| Phase 15 D-04 measure-then-plan for Wave 2 backfill | Pre-locking module list misses production-code drift; measurement at execute time matches reality | ✓ Good — Phase 15 |
| Phase 15 D-05 diff-cover migrates from `unit-tests` to `coverage-combine` (supersedes Phase 10 D-03) | Combined-data is the single source of truth for both 70% floor and diff-cover gate | ✓ Good — Phase 15 |
| Phase 15 D-08 `parallel = false` in `[tool.coverage.run]` | Pitfall 1: empirically breaks artifact path with `COVERAGE_FILE` env var; researcher-revised | ✓ Good — Phase 15 |
| 5 large modules below per-module 70% accepted at v1.3 close | Aggregate floor 71.9% met; deep-mocking heavy pipelines is out of CONTEXT D-04 scope; v1.4 follow-up | ⚠ Revisit — v1.4 |

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
*Last updated: 2026-05-17 — v1.7 Memory Tech-Debt Burn-Down milestone opened*
