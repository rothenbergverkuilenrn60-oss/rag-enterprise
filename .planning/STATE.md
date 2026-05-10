---
gsd_state_version: 1.0
milestone: v1.5
milestone_name: Web Search + Multi-Agent Debate + Coverage Lift
status: verifying
stopped_at: Phase 21 Wave 1 — Plan 21-01 + Plan 21-02 shipped; Wave 2 (Plan 21-03 Verifier class) ready
last_updated: "2026-05-10T13:00:00.000Z"
last_activity: 2026-05-10 — Plan 21-02 GREEN shipped (VerifierVerdict + 3 events + GenerationRequest.debate; D-01/D-08/D-09/D-10)
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 17
  completed_plans: 7
  percent: 41
---

# STATE — EnterpriseRAG (v1.5 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-10 after v1.5 open)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.5 milestone — replace v1.4 WebSearchTool placeholder with Tavily-backed real implementation; introduce AGENT-05 multi-agent debate / sub-agent verify (10x roadmap #2); lift 5 large modules above per-module ≥ 70% coverage.

## Current Position

Phase: 20 — WebSearchTool Real Implementation (Tavily)
Plan: 5/5 complete; awaiting verify_phase_goal + TDD review + security gate
Status: Verifying
Last activity: 2026-05-10 — Wave 4 shipped (Plan 20-05 SC5 gate + human-verify approved; Phase 20 acceptance roll-up landed)

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 20 | WebSearchTool Real Implementation (Tavily) | AGENT-10, AGENT-11, AGENT-12, AGENT-13 | Verifying — 5/5 plans shipped |
| 21 | AGENT-05 Multi-Agent Debate / Sub-Agent Verifier | AGENT-05, AGENT-14, AGENT-15 | Planning |
| 22 | Per-Module 70% Coverage Lift | TEST-08, TEST-09, TEST-10, TEST-11, TEST-12 | Planning |

## Accumulated Context

### Carry-Forward Decisions (still in force)

| Decision | Source | Why it matters in v1.5 |
|----------|--------|------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All v1.5 work runs on this stack; multi-tenancy preserved by construction |
| Section heading text in embedded content; numeric IDs in metadata only | v1.1 Phase 8 D-02 | Coverage lift on retriever/extractor must preserve this rule |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 | Pattern reused inside any new tool that does filtered queries |
| Regex-first filter extractor in `services/nlu/filter_extractor.py` | v1.1 Phase 8 QUERY-01 | Coverage lift must NOT regress regex-first behavior |
| FastAPI StaticFiles mount at `/ui/`; `static/index.html → ui.html` symlink | v1.1 Phase 9 | Preserved; UI not in v1.5 scope |
| `diff-cover ≥ 80%` gate on touched files | v1.1 Phase 10 TEST-03 | All v1.5 PRs MUST pass this gate |
| Combined coverage `--fail-under=70` global floor | v1.3 Phase 15 | v1.5 coverage lift hardens this further on 5 modules |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | New verifier / debate sub-agent reuses this provider-neutral interface |
| `parallel_tool_calls=True` explicit in OpenAI; `disable_parallel_tool_use=False` explicit in Anthropic | v1.2 Phase 11 | Inherited by AGENT-05 sub-agents |
| `asyncio.gather` for concurrent tool execution | v1.2 Phase 11 | AGENT-05 debate runs N verifier sub-agents in parallel |
| Sub-agents do NOT inherit chat history | v1.3 D-06 | AGENT-05 verifier sub-agent context isolation MUST follow this rule |
| `BaseException` (not `Exception`) for `asyncio.gather` isolation | v1.3 Phase 12 | AGENT-05 verifier failure isolation follows the same scope |
| Mock at consumer path (`services.<mod>.<dep>`) not source | v1.3 Phase 13 + 15 | Coverage lift unit tests follow this pattern |
| Phase 15 D-08 `parallel = false` in `[tool.coverage.run]` | v1.3 Phase 15 | Combine job topology preserved verbatim across v1.5 |
| `Planner` / `Executor` / `Synthesizer` triad behind frozen Pydantic V2 contracts | v1.4 Phase 16 | AGENT-05 verifier role plugs in as either an additional Executor pass or an additional planner-loop hop |
| `BaseTool` ABC + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST` constant in `services/pipeline.py` | v1.4 Phase 17 | WebSearchTool real impl swaps in behind the same ABC; allowlist updated to include `web_search` |
| SSE event schema in `docs/agent-architecture.md` | v1.4 Phase 18 | AGENT-05 debate trace events extend the existing schema, do not introduce a new transport |

### Open Questions Carried into v1.5 Planning

(To be resolved during phase discussions, not blockers for opening v1.5.)

1. **WebSearch citation contract.** Tavily returns URL + snippet + title. Where do these flow in `RetrievedChunk` / `ToolResult` so the existing source-citation UI (`来源N · page=...`) works without UI rewrite? Decide in WebSearch phase discussion.
2. **WebSearch when knowledge base is empty vs supplements it.** Should `web_search` be planner-pickable for any query, or only when `search_knowledge_base` returns < N chunks? Decide in WebSearch phase plan.
3. **AGENT-05 debate shape.** Two competing patterns: (a) verifier role (one extra sub-agent reads N answers, picks the best or flags disagreement); (b) peer debate (N sub-agents critique each other's answers iteratively). Recommend (a) for v1.5 — simpler, lower latency cap, same SSE event surface.
4. **AGENT-05 trigger.** Always-on for swarm queries vs opt-in flag (`debate=true`)? Recommend opt-in for v1.5 to constrain blast radius and latency.
5. **Coverage lift scope drift.** When `pipeline.py` covers AgentQueryPipeline + SwarmQueryPipeline + QueryPipeline (5500+ lines), 70% may force test bloat. Per-class breakdown vs whole-file? Decide in coverage-lift phase plan.
6. **Tavily quota / fallback.** What does the system do when Tavily rate-limits or 5xx? Tenacity retry with exponential backoff is the v1.0+ pattern; final-failure UX (return error chunk vs fall through to RAG-only) decided in plan.

### Blockers

None.

### Todos (carry-forward, not v1.5-scoped but tracked)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9/14 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10/15 live PR through CI confirms `coverage-combine` job + HTML artifact (natural confirmation on first PR)
- [ ] Push tags `v1.1`, `v1.2`, `v1.3` to origin (currently local-only)
- [ ] v1.6+ follow-up: Memory tool (10x roadmap #1) — needs `/office-hours` first
- [ ] v1.6+ follow-up: Code-acting / SQLTool (10x roadmap #4) — sandbox selection unresolved
- [ ] v1.6+ follow-up: UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke test

## Session Continuity

**Last updated:** 2026-05-10 — Phase 21 Plan 21-02 shipped (VerifierVerdict + 3 events + GenerationRequest.debate)
**Stopped at:** Phase 21 Wave 1 complete (Plan 21-01 + Plan 21-02 shipped); Wave 2 (Plan 21-03 Verifier class) ready
**Next action:** Begin Phase 21 Wave 2 — Plan 21-03 (Verifier sub-agent class consuming VerifierVerdict)

**Planned Phase:** 21 (AGENT-05 Multi-Agent Debate / Sub-Agent Verifier) — 6 plans, 2 complete (21-01, 21-02) — 2026-05-10
