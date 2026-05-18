# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.7.0] - 2026-05-17

Memory Tech-Debt Burn-Down. Production-cleans the memory subsystem (TD-01..TD-07) before adding more features. Zero new user-facing capabilities; pure refactor + reliability.

### Added

- **TD-01** — `services/audit/audit_service.py` self-bootstraps the `audit_log` PostgreSQL table on first call via `_get_pool` → `_create_tables`. INSERT-ONLY invariant (`REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC`) preserved. Cold-start fresh PG no longer requires manual DDL. See [v1.7 milestone detail](MILESTONES.md#v17).
- **TD-03** — `utils/asyncpg_helper.prepare_dsn(dsn)` centralizes asyncpg URL `?ssl=disable` strip (asyncpg URL parser misreads the literal). Both `services/memory/memory_service.py` and `services/audit/audit_service.py` import the helper; per-module inline copies removed. See [v1.7 milestone detail](MILESTONES.md#v17).
- **TD-07** — bge-m3 model loader resolves vanilla HuggingFace cache layout `{MODEL_DIR}/BAAI/bge-m3/` natively. Legacy `{MODEL_DIR}/embedding_models/bge-m3/` path still supported (backwards-compat). See [v1.7 milestone detail](MILESTONES.md#v17).
- **TD-02** — `tests/factories/app.py::create_app()` factory + `_configure_app(app)` extraction in `main.py`. Per-test isolated FastAPI app construction; parallel cross-contamination test green. 34-entry singleton inventory + completeness lint. See [v1.7 milestone detail](MILESTONES.md#v17).
- **TD-06** — `redis_mock` fixture in `tests/conftest.py` (fakeredis-backed) + `pytest_collection_modifyitems` hook auto-applies to `@pytest.mark.uses_redis` tests. `ShortTermMemory._get_client` now delegates to `utils.cache.get_redis` (single mock target). Unit suite runs without live Redis. See [v1.7 milestone detail](MILESTONES.md#v17).
- **TD-04** — `LongTermMemory._is_near_duplicate(text, threshold=0.05)` cosine precheck before save. Near-duplicate hits emit `MEMORY_NEAR_DUPLICATE_SKIPPED` audit row (new `AuditAction` enum value). New `MEMORY_NEAR_DUPLICATE_THRESHOLD` setting. See [v1.7 milestone detail](MILESTONES.md#v17).
- **TD-05** — `LongTermMemory.save_facts(list[ExtractedFact])` batch path: 1× `embed_batch` + 1× bulk dedupe SELECT (C1 `unnest($1::text[]) WITH ORDINALITY` + `vec_txt::vector` cast — sidesteps pgvector.asyncpg codec hijack) + 1× `executemany`. `save_fact` retained as thin D-12 wrapper. ExtractorAgent dispatch (D-17) migrated. Benchmark: p50 25.31ms → 5.51ms (speedup 19.80ms with MagicMock embedder; ~123ms expected with real bge-m3). See [v1.7 milestone detail](MILESTONES.md#v17).
- **DOC-01** — `docs/RUNBOOK.md` (new); `docs/release-notes-v1.7.md` (new); `.planning/REQUIREMENTS-v1.8.md` (new scaffold with 7 pre-seeded backlog items: SK-01, TOC-01, OAI-01, EVT-01, MYPY-01, TEST-INFRA-01, TEST-INFRA-02). README + ARCHITECTURE + memory-eviction.md surgically refreshed.

### Changed

- **Memory write path** — `LongTermMemory.save_fact` is now a thin wrapper that delegates to `save_facts([...])`. Signature unchanged; embed-failure raise contract preserved. ExtractorAgent (`services/agent/extractor.py`) calls `save_facts(...)` once per turn instead of the per-fact for-loop.
- **Test conventions** — Redis-dependent unit tests must apply `@pytest.mark.uses_redis` (auto-mocked via `redis_mock` fixture). Audit + memory integration suites can be migrated to `app_factory` fixture for per-test isolated app construction (existing tests left in place per Phase 27 D-05).

### Fixed

- **`audit_log` cold-start manual-DDL footgun** — fresh PG cluster no longer requires operator to run `audit_log` DDL by hand before first audit-write succeeds (TD-01).
- **asyncpg `?ssl=disable` URL literal misread** — duplicate per-module strip helpers consolidated to `utils/asyncpg_helper.prepare_dsn` (TD-03; per A1 also handles short-form `postgres+asyncpg://` → `postgres://` scheme normalization).
- **bge-m3 fresh-machine setup** — vanilla HuggingFace cache layout resolves without symlink (TD-07).

> Near-duplicate guard is **audit-mode** in v1.7 (`MEMORY_NEAR_DUPLICATE_SKIPPED` audit row emitted on hit; INSERT still runs). v1.8 will promote to silent-skip with TOCTOU mitigation — see [SK-01](.planning/REQUIREMENTS-v1.8.md) + [TOC-01](.planning/REQUIREMENTS-v1.8.md). This audit-mode-before-enforce discipline follows v1.6 EVICT-02 precedent.

## [1.6.0] - 2026-05-11

Streaming UI + Admin Console + RAGAS Pipeline Rescue + Retriever Tuning.

### Added
- **Basic SSE streaming in agent playground**. `POST /api/v1/query/stream` now drives the basic mode tile, with token-level streaming (`data: <token>\n\n` frames, `[DONE]` sentinel). Placeholder + elapsed counter for the LLM TTFT (5-20 s on Qwen). `static/agent.{html,js,css}`.
- **Feedback loop UI**. 👍 / 👎 buttons + comment field bound to the current session id; live aggregate stats from `GET /api/v1/feedback/stats`.
- **Ingest panel**. Submits `POST /api/v1/ingest/async`, polls `GET /api/v1/ingest/status/{task_id}` until terminal status.
- **Admin Console** at `/ui/admin.html` exposing every previously hidden backend: `/readiness`, `/stats`, `DELETE /cache`, `/knowledge/scan`, `/docs/{id}/versions` + rollback, `/annotation/tasks/*`, `/ab/experiments/*` + feedback recorder. New files `static/admin.{html,css,js}`.
- **GB 4785-2019 evaluation dataset** — `eval/datasets/qa_pairs_gb4785.json`, 10 Q&A pairs with ground-truth pulled from the standard, tightly aligned with the indexed KB.

### Fixed
- **OpenAI `chat_with_tools` thinking-mode 400**. DashScope rejects forced `tool_choice` under thinking mode; `OpenAILLMClient.chat_with_tools` now falls back to a JSON-text completion and parses the result. Restores NLU functionality on Qwen/DashScope. `services/generator/llm_client.py`.
- **NLU intent parser brittleness**. Loose match for unfamiliar enum labels (e.g. `"definition_query"` → `DEFINITION`); tolerate `entities` returned as either dicts or bare strings; same for `sub_queries`. `services/nlu/nlu_service.py`.
- **SSE `/query/stream` swallowed retry errors**. Added `tenacity.RetryError` to the except tuple and surface the inner cause in logs so client receives `[ERROR]` SSE frames instead of HTTP 500 JSON. `controllers/api.py`.
- **RAGAS pipeline end-to-end**. Five blocking bugs fixed:
  - Wrap judge LLM with `LangchainLLMWrapper` and embeddings with `LangchainEmbeddingsWrapper` (RAGAS 0.2 calls `set_run_config` only on these wrappers).
  - Set `check_embedding_ctx_length=False` on DashScope-routed embeddings to skip tiktoken pre-count which DashScope's shim rejects.
  - Use `text-embedding-v3` when `OPENAI_BASE_URL` points at DashScope (defaults differ from OpenAI proper).
  - Add `env_file: .env.docker` to the `ragas-eval` compose service so `OPENAI_BASE_URL` (not in the shared anchor) reaches the eval container.
  - Filter dataframe columns by `is_numeric_dtype` to avoid casting RAGAS 0.2 metadata columns (e.g. `user_input`) to float.
  - Emit both legacy and RAGAS 0.2 column names (`user_input` + `question`, `response` + `answer`, `retrieved_contexts` + `contexts`, `reference` + `ground_truth`) so ContextPrecision / ContextRecall resolve `reference`.

### Changed
- **Retriever sweep** — settled on `TOP_K_DENSE=40 / TOP_K_SPARSE=40 / TOP_K_RERANK=4` with `HYDE_ENABLED=false` and API `top_k=4`. Reached overall RAGAS score **0.7352** on the 10-question GB 4785 dataset (faithfulness 0.90, answer_relevancy 0.84, context_precision 0.60, context_recall 0.60).

## [1.4.0] - 2026-05-09

Agent-First Architecture Inversion. The agent runtime (Planner / Executor /
Synthesizer) is now the project's core; agentic RAG is one tool the agent
calls. See [v1.4 design](docs/v1.4-design.md) for the architectural thesis.

### Added
- Phase 16 — Planner + Executor extraction. `services/agent/{planner,executor}.py`; `ToolPlan` / `ToolCall` Pydantic V2 frozen models; query intent encoded as `ToolPlan` shape (no separate `IntentRouter`); shared `execute_tool_call` helper used by `SwarmQueryPipeline` and `Executor`. Closes AGENT-06, AGENT-09, NLU-03. See [Phase 16 SUMMARY](.planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md).
- Phase 17 — Tool abstraction. `BaseTool` ABC + static `ToolRegistry` + `RetrieveTool` (wraps `QueryPipeline.run`) + `RefinedRetrieveTool` + `WebSearchTool` placeholder. `Executor` dispatches strictly through the registry. Closes AGENT-07. See [Phase 17 SUMMARY](.planning/phases/17-tool-abstraction-retrievetool/17-03-SUMMARY.md).
- Phase 18 — SSE event stream on `POST /api/v1/agent/v1/run/stream`. Six event types: `planner.plan`, `tool.span.start`, `tool.span.end`, `tool.span.error`, `executor.parallel`, `synthesizer.final`. Latency assertion: parallel groups bounded by `max(tool_latency)` not sum. Closes AGENT-04. See [Phase 18 SUMMARY](.planning/phases/18-sse-planner-trace-event-stream/18-03-SUMMARY.md).
- Phase 19 — Agent-first docs + demo + release. `docs/agent-architecture.md` Concept → Tool authoring → Wire format trilogy; `make demo-agent` (4-tool parallel fan-out, fixture-driven, no API keys); asciinema cast embedded in README. Closes AGENT-08. See [Phase 19 SUMMARY](.planning/phases/19-agent-first-docs-demo-release/19-08-SUMMARY.md).

### Changed
- Architectural inversion: agent is the core, RAG is one tool. README rewritten with agent-first framing; v1.3 technical content preserved under `## Platform features`.
- `AgentQueryPipeline.run` body delegates to `Planner` → `Executor` → `Synthesizer`; thin orchestrator (43 lines, ≤ 50 line gate).
- `_execute_tool_call` consolidated to a single shared helper; both `SwarmQueryPipeline` and `Executor` call it (no copy duplicates).

## [1.3.0] - 2026-05-09

Fork Swarm, NLU & Quality. See [v1.3 milestone roadmap](.planning/milestones/v1.3-ROADMAP.md).

- Phase 12 — Fork-Agent Swarm: `SwarmQueryPipeline` with sub-agent fork via `call_agentic_turn`; sub-agents do NOT inherit chat history (true context isolation).
- Phase 13 — LLM Filter Fallback: regex-first filter extractor with LLM fallback when regex fails or yields ambiguous filters.
- Phase 14 — Frontend Split and DOM Modernization: `static/index.html` decomposed; FastAPI StaticFiles mount on `/ui/`.
- Phase 15 — Coverage Combine and 70% Floor: combined unit+integration coverage report; `--fail-under=70` global floor enforced in CI.

## [1.2.0] - 2026-05-08

Agentic Layer + Swarm. See [v1.2 milestone roadmap](.planning/milestones/v1.2-ROADMAP.md).

- Phase 11 — Provider-Agnostic Agentic Layer + Parallel Tool-Call Burst: `BaseLLMClient.call_agentic_turn` non-abstract default-raise; `parallel_tool_calls=True` (OpenAI) / `disable_parallel_tool_use=False` (Anthropic) explicit; `asyncio.gather` for concurrent tool execution.

## [1.1.0] - 2026-05-08

Retrieval Depth & Frontend. See [v1.1 milestone roadmap](.planning/milestones/v1.1-ROADMAP.md).

- Phase 7 — OCR Engine Integration: PaddleOCR fallback for image-only PDFs.
- Phase 8 — Multimodal Metadata + Query Filter: section heading text in embedded content; numeric IDs in metadata only; regex-first filter extractor; HNSW `iterative_scan = strict_order` + `ef_search` GUC pattern when filter active.
- Phase 9 — Frontend Extraction: FastAPI StaticFiles mount at `/ui/`; `static/index.html → ui.html` symlink.
- Phase 10 — Coverage Gate on New Code: `diff-cover ≥ 80%` gate on touched files (TEST-03) on every PR.

## [1.0.0] - 2026-04-27

Initial release — production-grade RAG platform. See [v1.0 milestone roadmap](.planning/milestones/v1.0-ROADMAP.md).

- Phase 1 — pgvector Foundation: PostgreSQL + pgvector backend with HNSW + Row-Level Security (multi-tenant by construction).
- Phase 2 — Security Hardening + Operational Fixes: JWT startup validation, per-route rate limiting, PII blocking, CORS lockdown.
- Phase 3 — Error Handling Sweep: no bare `except`; narrow exception types; structured logging on every error path.
- Phase 4 — Image Extraction: PDF-embedded images extracted via PyMuPDF, captioned by LLM, stored as retrievable `chunk_type="image"` chunks. PyMuPDF AGPL-3.0 license note.
- Phase 5 — Async Ingest Tracking: `POST /ingest/async` returns `task_id`; ARQ/Redis worker; poll status via `GET /ingest/status/{task_id}`.
- Phase 6 — Test Coverage and Eval: 200 stratified RAGAS QA pairs; `faithfulness > 0.85`, `answer_relevancy > 0.80` gates.

[Unreleased]: https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.7.0...HEAD
[1.7.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.6.0...v1.7.0
[1.6.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.4.0...v1.6.0
[1.4.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.3.0...v1.4.0
[1.3.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.2.0...v1.3.0
[1.2.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.1.0...v1.2.0
[1.1.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.0.0...v1.1.0
[1.0.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/releases/tag/v1.0.0
