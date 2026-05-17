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

---

## v1.4 Agent-First Architecture Inversion — 2026-05-10

**Shipped:** 2026-05-10
**Phases:** 16–19 | **Plans:** (see ROADMAP archive) | **Commits:** (stacked — PR #3)
**Timeline:** 2026-05-09 → 2026-05-10 (2 days)

**Delivered:** Inverted the architecture so the agent runtime is the project's core — `Planner` / `Executor` / `Synthesizer` triad behind frozen Pydantic V2 contracts; `BaseTool` ABC + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST` constant; SSE event schema documented in `docs/agent-architecture.md`; v1.4 release tagged. Agentic RAG becomes one tool the agent calls.

**Key accomplishments:**
1. `Planner` / `Executor` / `Synthesizer` triad behind frozen Pydantic V2 contracts (Phase 16, AGENT-06/AGENT-09/NLU-03)
2. `BaseTool` ABC + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST` constant in `services/pipeline.py` (Phase 17)
3. Structured SSE event stream on `POST /api/v1/agent/v1/run/stream` — six event types (`planner.plan` / `tool.span.start|end|error` / `executor.parallel` / `synthesizer.final`); each carries `trace_id`, monotonic `seq`, `ts_ms` (Phase 18, AGENT-04)
4. `docs/agent-architecture.md` Event Schema Reference + agent-first docs / demo / release ceremony (Phase 19, AGENT-08)

**Known deferred items:** None at close (per ROADMAP).

**Archive:** [milestones/v1.4-ROADMAP.md](milestones/v1.4-ROADMAP.md) · [milestones/v1.4-REQUIREMENTS.md](milestones/v1.4-REQUIREMENTS.md)

---

## v1.5 Web Search + Multi-Agent Debate + Coverage Lift — 2026-05-11

**Shipped:** 2026-05-11
**Phases:** 20–22 | **Plans:** 18 | **Commits:** 1 (squash — PR #4); 78 individual commits before squash
**Timeline:** 2026-05-08 → 2026-05-11 (4 days)
**Audit:** none (skipped — three phases each individually verify-work PASSED)

**Delivered:** Replaced the v1.4 `WebSearchTool` placeholder with a real Tavily-backed implementation behind the same `BaseTool` ABC; introduced a single-pass verifier sub-agent that runs after `SwarmQueryPipeline`'s peer fan-out when `req.debate=True` and surfaces evidence-supported divergence; raised five high-traffic modules above per-module ≥70% line coverage and wired CI to enforce a per-module floor on combined coverage data.

**Key accomplishments:**
1. **Tavily WebSearch real impl** (Phase 20, AGENT-10..13) — `services/tools/web_search_tool.py` Tavily SDK adapter behind `BaseTool` ABC; tenacity retry + typed error results; planner picks `web_search` when KB returns < N chunks; results map to `RetrievedChunk` so existing source-citation UI renders unchanged (byte-identical static UI assets vs `d9ffc0a`); 15/15 unit + 4/4 planner-pick integration tests
2. **AGENT-05 verifier sub-agent** (Phase 21, AGENT-05/14/15) — `services/agent/verifier.py` `Verifier` class + `VerifierVerdict` Pydantic V2 contract with CF-04 forced-disagree on empty evidence; verifier hop gated on `req.debate` at `services/pipeline.py:1314-1469`; 3 new SSE event types (`verifier.start`/`.complete`/`.disagreement`) extend the v1.4 schema; `synthesizer.final` remains terminal; latency bounded by `max(peer) + verifier`, not `sum` (3 peers × 0.3s + verifier 0.2s → asserts `450 < elapsed_ms < 700`)
3. **Per-module 70% coverage lift** (Phase 22, TEST-08..12) — five new test files (159 tests) lift `services/pipeline.py` 42.7% → 81.0%, `services/generator/llm_client.py` 53.0% → 70.6%, `services/vectorizer/vector_store.py` 44.2% → 80.0%, `services/retriever/retriever.py` 34.5% → 85.0%, `services/extractor/extractor.py` 37.3% → 73.5%; consumer-path mocks only (CF-02); zero production `.py` changes (CF-01)
4. **CI per-module hard-fail floor** (Phase 22 D-08) — `.github/workflows/ci.yml` `coverage-combine` job: 5 hard-fail per-module gates with run-all-then-fail semantics (D-02); replaces 22-00's warning-only staging; combined coverage gate raised effectiveness from "average-around-able" to "module-by-module enforced"
5. **`debate=False` byte-identical to v1.3 swarm** — verifier never invoked, no `agent_05` audit-detail key, `_llm.chat.await_count == 2` (decompose+synth, no verifier hop) — backward-compat lock honored
6. **Open Q#5 closed per Phase 22 D-05** — `pipeline.py` measured as a whole-file ≥70% target (no per-class breakdown; long-standing v1.3 question resolved)

**Known deferred items:** Docker Build Validation in CI still `continue-on-error: true` (paddleocr / paddlex / paddlepaddle ABI churn — pre-existing v1.1 bootstrap exception, not v1.5 scope). MyPy still `continue-on-error: true` (~70 pre-existing errors). Carry-forward todos: asyncpg pool RLS production verification, PyMuPDF AGPL commercial licensing, Phase 9/14 visual diff at first deploy.

**In-flight CI fixes during ship:** ruff I001/E402/F841 (commit `0e49bc4`); `actions/upload-artifact@v4` `include-hidden-files: true` for `.coverage*` dotfiles (commit `d41425e`); `.coverage` → `.coverage.unit/integration` rename fallback (`d6cc54c`).

**Archive:** [milestones/v1.5-ROADMAP.md](milestones/v1.5-ROADMAP.md) · [milestones/v1.5-REQUIREMENTS.md](milestones/v1.5-REQUIREMENTS.md)

## v1.6 Memory Tool — Agent-Authored Long-Term Facts — 2026-05-17

**Shipped:** 2026-05-17
**Phases:** 23, 24, 25 | **Plans:** 20 | **Commits:** 3 squash (PRs #5, #7, #8); ~105 individual commits before squash
**Timeline:** 2026-05-15 → 2026-05-17 (3 days; intense same-day Phase 25 + integration burn-down)
**Audit:** none (skipped — three phases each individually verified; real-PG integration verified at ship)

**Delivered:** Closed 10x roadmap #1 (Memory Tool). Added a third memory store distinct from pgvector chunks (static KB) and `memory_service.py` (session turns): agent-authored long-term facts written by a background extractor sub-agent, read semantically via planner-callable `RecallTool`, bounded by per-`(user_id, tenant_id)` capacity-cap eviction, and made GDPR-erasable via admin `DELETE /api/v1/memory/forget`.

**Key accomplishments:**
1. **Background extractor + schema** (Phase 23, MEM-01..05) — `long_term_facts` table with `embedding vector(1024)` + HNSW cosine index (m=16, ef_construction=64); `register_vector` codec on every connection (Pitfall #1); `services/agent/extractor.py` Extractor sub-agent runs post-turn via `asyncio.create_task` (non-blocking); `LongTermMemory.save_fact` writes typed facts behind narrow `asyncpg.PostgresError` + `MemoryFactWriteError`; 27 unit + 7 PG-gated integration tests.
2. **Semantic RecallTool + load_context shift** (Phase 24, MEM-06..10) — `LongTermMemory.get_relevant_facts()` rewritten from `ORDER BY importance DESC` (popularity) to query-embedding + pgvector cosine with `SET LOCAL hnsw.iterative_scan = strict_order` + raised `ef_search` (v1.1 Phase 8 pattern); `services/agent/tools/recall.py::RecallTool` registered via `BaseTool` ABC; `AGENT_TOOL_ALLOWLIST` 3→4. Semantic shift documented + regression-tested at all 4 `load_context` call sites. SQL-only HNSW p95 latency <50ms @ 10k rows. `scripts/backfill_fact_embeddings.py` for existing-row backfill.
3. **Capacity-cap eviction CLI** (Phase 25, EVICT-01..03) — `scripts/evict_long_term_facts.py` with `--mode={audit,enforce}`, chunked DELETE @ 1000 rows/txn, `ORDER BY importance ASC, created_at ASC` tie-break, re-COUNT post-DELETE for accurate audit (T8), audit-fail-continues-sweep (T1). Audit-mode-before-enforce discipline mandatory for first prod run.
4. **GDPR forget API** (Phase 25, GDPR-01..03) — `LongTermMemory.forget_user(user_id, tenant_id) -> int` chunked DELETE (T7) wrapped in typed `MemoryForgetError`; `DELETE /api/v1/memory/forget?user_id=…` controller with JWT-resolved tenant, admin-or-self auth, `X-Confirm-Delete` header guard; audit-log entry per call (actor + target + row count + timestamp), audit-write failure does NOT block GDPR action (T1); body order role-403 first, header-400 second, 404 third (T9).
5. **Real-PG integration verified at ship** — 8/8 Phase 25 PG-gated tests + 3/3 Phase 23 schema tests green on local pgvector after three same-day surgical fixes: conftest `pg_pool` fixture → function-scope (PR #7); `services/memory/memory_service` + `services/audit/audit_service` strip `?ssl=disable` URL-param (asyncpg URL parser misroutes as server_settings); per-test singleton-graph reset autouse fixture for FastAPI app singletons.

**Known deferred items (v1.7 candidates):**
- `audit_log` table never auto-created by `audit_service` — DDL only in docstring. Add `_create_tables` matching `LongTermMemory._create_tables` pattern.
- Module-level singleton graph + FastAPI app singleton makes per-test isolation expensive — consider per-test `create_app()` factory.
- `?ssl=disable` strip pattern duplicated in `memory_service` + `audit_service` — centralize as `utils/asyncpg_helper.py`.
- `save_fact` near-duplicate guard (`<embedding> <=> $vec < 0.05` precheck) — per eng-review A3 (Phase 23).
- `save_facts(list[ExtractedFact])` batch path — 1× embed_batch + executemany vs current 3× round-trips per turn.
- Pre-existing Redis-dependent unit-test failures (32 in baseline) — Phase 24 documented; need Redis-mock fixture rollout.
- bge-m3 model dir layout asymmetry — code expects files at `{MODEL_DIR}/embedding_models/bge-m3/`, HF cache puts them at `.../BAAI/bge-m3/`; resolved locally via symlinks.

**Bonus delivered (not in roadmap, surfaced during ship):**
- `tests/conftest.py::pg_pool` fixture flipped to function-scope (PR #7) — unblocks ALL PG-gated integration suites across Phases 23/24/25; was a latent pytest-asyncio 1.x scope bug nobody hit until v1.6 ship.

**Archive:** [milestones/v1.6-ROADMAP.md](milestones/v1.6-ROADMAP.md) · [milestones/v1.6-REQUIREMENTS.md](milestones/v1.6-REQUIREMENTS.md)
