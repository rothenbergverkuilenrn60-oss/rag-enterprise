# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.4.0...HEAD
[1.4.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.3.0...v1.4.0
[1.3.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.2.0...v1.3.0
[1.2.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.1.0...v1.2.0
[1.1.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.0.0...v1.1.0
[1.0.0]:      https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/releases/tag/v1.0.0
