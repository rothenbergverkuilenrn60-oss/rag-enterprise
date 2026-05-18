# EnterpriseRAG — Milestones

Single-row-per-milestone navigation surface. Each row links to the full milestone roadmap snapshot under `.planning/milestones/`. Section anchors below the table provide stable deep-links for `CHANGELOG.md` + `docs/release-notes-v{X}.md` references — these survive `.planning/` directory restructuring.

## Shipped

| Version | Shipped | Phases | Requirements | Anchor |
|---------|---------|--------|--------------|--------|
| [v1.0 Hardening](.planning/milestones/v1.0-ROADMAP.md) | 2026-04-27 | 1–6 | 22 | [details](#v10) |
| [v1.1 Retrieval Depth & Frontend](.planning/milestones/v1.1-ROADMAP.md) | 2026-05-08 | 7–10 | 7 | [details](#v11) |
| [v1.2 Agentic Layer + Swarm](.planning/milestones/v1.2-ROADMAP.md) | 2026-05-08 | 11 | 0 | [details](#v12) |
| [v1.3 Fork Swarm, NLU & Quality](.planning/milestones/v1.3-ROADMAP.md) | 2026-05-09 | 12–15 | 25 | [details](#v13) |
| [v1.4 Agent-First Architecture Inversion](.planning/milestones/v1.4-ROADMAP.md) | 2026-05-10 | 16–19 | 6 | [details](#v14) |
| [v1.5 Web Search + Multi-Agent Debate + Coverage Lift](.planning/milestones/v1.5-ROADMAP.md) | 2026-05-11 | 20–22 | 12 | [details](#v15) |
| [v1.6 Memory Tool — Agent-Authored Long-Term Facts](.planning/milestones/v1.6-ROADMAP.md) | 2026-05-17 | 23–25 | 16 | [details](#v16) |
| [v1.7 Memory Tech-Debt Burn-Down](.planning/milestones/v1.7-ROADMAP.md) | 2026-05-17 | 26–28 | 8 | [details](#v17) |

## In Planning

(none — run `/gsd-new-milestone` to open v1.8.)

---

### v10

Hardened an existing production RAG platform: migrated the vector store from Qdrant to PostgreSQL+pgvector, closed security gaps (JWT, rate limiting, PII, CORS), replaced 50+ broad exception handlers, implemented PDF image extraction with LLM captioning, added async ingest task tracking via ARQ, and established a test baseline of 263 unit tests with RAGAS eval gates.

[Roadmap snapshot](.planning/milestones/v1.0-ROADMAP.md) · [Requirements snapshot](.planning/milestones/v1.0-REQUIREMENTS.md) · [Phase artifacts](.planning/milestones/v1.0-phases/)

### v11

Closed v1.0's image-PDF retrieval gap (`data/raw/GB4785-2019.pdf` returned wrong sources for "第N页" / section-scoped queries because captions did not carry page or section context).

[Roadmap snapshot](.planning/milestones/v1.1-ROADMAP.md) · [Requirements snapshot](.planning/milestones/v1.1-REQUIREMENTS.md) · [Phase artifacts](.planning/milestones/v1.1-phases/)

### v12

Closed the provider-agnostic gap in `AgentQueryPipeline`: `agent_mode=True` now executes the real tool-use loop on both OpenAI and Anthropic providers.

[Roadmap snapshot](.planning/milestones/v1.2-ROADMAP.md) · [Requirements snapshot](.planning/milestones/v1.2-REQUIREMENTS.md) · [Phase artifacts](.planning/milestones/v1.2-phases/)

### v13

Upgraded `agent_mode` to true multi-agent fork swarm with isolated sub-agent contexts, added an LLM filter-extractor fallback for natural-language section references the regex misses, modernized the frontend to multi-file with `addEventListener` wiring, and raised the CI coverage floor from 46% to 70% backed by combined unit + integration measurement.

[Roadmap snapshot](.planning/milestones/v1.3-ROADMAP.md) · [Requirements snapshot](.planning/milestones/v1.3-REQUIREMENTS.md) · [Phase artifacts](.planning/milestones/v1.3-phases/)

### v14

Invert the architecture so the agent runtime is the project's core (planner + executor + tool registry), and agentic RAG becomes one tool the agent calls.

[Roadmap snapshot](.planning/milestones/v1.4-ROADMAP.md) · [Requirements snapshot](.planning/milestones/v1.4-REQUIREMENTS.md) · [Phase artifacts](.planning/milestones/v1.4-phases/)

### v15

Replace v1.4's `WebSearchTool` placeholder with a Tavily-backed real implementation; introduce AGENT-05 multi-agent debate / sub-agent verify on top of v1.3 `SwarmQueryPipeline`; lift 5 large modules above per-module ≥ 70% coverage.

[Roadmap snapshot](.planning/milestones/v1.5-ROADMAP.md) · [Requirements snapshot](.planning/milestones/v1.5-REQUIREMENTS.md) · [Phase artifacts](.planning/milestones/v1.5-phases/)

### v16

Ship 10x roadmap #1 (Memory tool) as an agent-callable durable-facts surface.

[Roadmap snapshot](.planning/milestones/v1.6-ROADMAP.md) · [Requirements snapshot](.planning/milestones/v1.6-REQUIREMENTS.md) · [Phase artifacts](.planning/milestones/v1.6-phases/)

### v17

Knock out all 7 deferred items surfaced at v1.6 ship — production-clean the memory subsystem before adding more features.

**TD-01..07 + DOC-01** — Refactor + reliability milestone. Pure tech-debt burn-down; zero new user-facing capabilities.
- Phase 26 (TD-01, TD-03, TD-07): audit_log self-bootstrap; asyncpg helper centralization; bge-m3 vanilla HF cache
- Phase 27 (TD-02, TD-04, TD-05, TD-06): create_app() factory; near-dup audit-mode (D-09 — INSERT still runs, v1.8 promotes to silent-skip); save_facts batch; redis_mock fixture
- Phase 28 (DOC-01): docs sweep + release artifacts + v1.8 scaffold + milestone archive

[Roadmap snapshot](.planning/milestones/v1.7-ROADMAP.md) · [Requirements snapshot](.planning/milestones/v1.7-REQUIREMENTS.md) · [Phase artifacts](.planning/milestones/v1.7-phases/)  · [Release notes](docs/release-notes-v1.7.md) · [Tag ceremony](.planning/milestones/v1.7-release-tag.md)
