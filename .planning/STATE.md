---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: Agent-First Architecture Inversion
status: planning
stopped_at: v1.3 milestone closed (2026-05-09); v1.4 milestone opened — requirements + roadmap defined, no phase started yet
last_updated: "2026-05-09T16:38:09.000Z"
last_activity: 2026-05-09 — v1.4 Agent-First Architecture Inversion milestone opened (PROJECT.md updated, REQUIREMENTS.md created, ROADMAP.md extended, design doc referenced)
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# STATE — EnterpriseRAG (v1.4 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-09 after v1.4 open)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.4 Agent-First Architecture Inversion — invert the architecture so the agent runtime is the project core; agentic RAG becomes one tool the agent calls.

## Current Position

Phase: Not started (defining requirements complete; ready for `/gsd-plan-phase 16`)
Plan: —
Status: Defining requirements / awaiting first phase plan
Last activity: 2026-05-09 — Milestone v1.4 started

| Field | Value |
|-------|-------|
| Milestone | v1.4 Agent-First Architecture Inversion |
| Current phase | 16 — Planner + Executor Extraction (not started) |
| Current plan | — |
| Phase status | 0/4 phases started |
| Overall progress | 0/4 phases; v1.4 is just opened |

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 16 | Planner + Executor Extraction | AGENT-06, AGENT-09, NLU-03 | Not started |
| 17 | Tool Abstraction + RetrieveTool | AGENT-07 | Not started |
| 18 | SSE Planner Trace Event Stream | AGENT-04 | Not started |
| 19 | Agent-First Docs + Demo + Release | AGENT-08 | Not started |

## Accumulated Context

### Carry-Forward from v1.3 (key decisions still in force)

| Decision | Source | Why it matters in v1.4 |
|----------|--------|------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All v1.4 work runs on this stack; multi-tenancy preserved by construction |
| Section heading text in embedded content; numeric IDs in metadata only | v1.1 Phase 8 D-02 | Any new chunker / retrieval work must preserve this rule |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 | Pattern reused for any new filtered queries inside `RetrieveTool` |
| Regex-first filter extractor in `services/nlu/filter_extractor.py` | v1.1 Phase 8 QUERY-01 | NLU-03 (intent classification by planner) must NOT regress regex-first behavior — regex stays the cheap first branch inside `RetrieveTool`'s filter handling |
| FastAPI StaticFiles mount at `/ui/`; `static/index.html → ui.html` symlink | v1.1 Phase 9 | UI demo for agent-first must preserve this; only update content, not mount |
| `diff-cover ≥ 80%` gate on touched files | v1.1 Phase 10 TEST-03 | All v1.4 PRs MUST pass this gate |
| Combined coverage `--fail-under=70` global floor | v1.3 Phase 15 | New v1.4 modules included from day one — no exemption |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | New `Planner` and `Executor` reuse this provider-neutral interface — don't add `@abstractmethod` |
| `parallel_tool_calls=True` explicit in OpenAI; `disable_parallel_tool_use=False` explicit in Anthropic | v1.2 Phase 11 | New `Executor` inherits this pattern for tool dispatch |
| `asyncio.gather` for concurrent tool execution | v1.2 Phase 11 | New `Executor` runs `ToolPlan.steps` via `asyncio.gather` (parallelism factor logged) |
| `AgentQueryPipeline` body byte-identical baseline (v1.2 close → v1.3 D-01) | v1.3 Phase 12 | v1.4 Phase 16 explicitly modifies this — refactor MUST keep behavioral parity via tests against v1.3 baseline before any new behavior lands |
| `_execute_tool_call` duplicated verbatim across `SwarmQueryPipeline` + `AgentQueryPipeline` | v1.3 Phase 12 + 15 audit | v1.4 Phase 16 extracts the shared helper (AGENT-09); both pipelines must call the helper after extraction |
| Sub-agents do NOT inherit chat history | v1.3 D-06 | True context isolation; preserved if Phase 16 planner ever fans into swarm-style sub-agents (deferred to v1.5+ AGENT-05 but design hooks must not block) |
| `BaseException` (not `Exception`) for `asyncio.gather` isolation | v1.3 Phase 12 | New `Executor` uses the same exception scope to avoid `CancelledError` / `TimeoutError` propagation |
| Mock at consumer path (`services.<mod>.<dep>`) not source | v1.3 Phase 13 + 15 | All v1.4 unit tests follow this pattern |
| Phase 15 D-08 `parallel = false` in `[tool.coverage.run]` | v1.3 Phase 15 | Combine job topology preserved verbatim across v1.4 |

### Source Design Document

`/home/ubuntu/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` — Approach A (incremental refactor, no framework lock-in). Read at the start of `/gsd-plan-phase 16`.

### Open Questions Carried into Planning

(From the source design doc — to be resolved during phase discussions, not blockers for opening v1.4.)

1. **Planner output schema.** Pydantic model fields for `ToolPlan` (`steps: list[ToolCall]`, `parallel_groups: list[list[int]]`, `rationale: str`). Decide in Phase 16 plan.
2. **Tool registration mechanism.** Static class registry vs plugin discovery. Recommend static registry for v1.4 with abstraction clean enough that MCP can replace it without callsite changes.
3. **Iteration cap policy.** v1.3's hardcoded `max_iterations=5` vs adaptive cap. Recommend keep static for v1.4 to constrain blast radius.
4. **Backwards compatibility.** Keep `/query?agent_mode=true` working as a thin alias for `/agent/v1/run`? Recommend alias.
5. **Sub-agent reuse.** `SwarmQueryPipeline` as a tool (composes naturally) vs separate execution mode. Recommend tool — confirm in Phase 16 discussion.
6. **Cross-model second opinion.** Skipped during /office-hours. Worth running `codex review` on the design doc before locking Phase 16 plan.

### Blockers

None.

### Todos (carry-forward, not v1.4-scoped but tracked)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9/14 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10/15 live PR through CI confirms `coverage-combine` job + HTML artifact (natural confirmation on first PR)
- [ ] Push tags `v1.1`, `v1.2`, `v1.3` to origin (currently local-only)
- [ ] PR #1 + PR #2 + PR #3 (v1.3) review + merge
- [ ] v1.5+ follow-up: lift 5 large modules above per-module 70% (pipeline, llm_client, vector_store, retriever, extractor)
- [ ] v1.5+ follow-up: AGENT-05 multi-agent debate / sub-agent verify (10x roadmap #2)
- [ ] v1.5+ follow-up: UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke test

## Session Continuity

**Last updated:** 2026-05-09 — v1.4 Agent-First Architecture Inversion milestone opened
**Stopped at:** v1.4 PROJECT.md / STATE.md / ROADMAP.md / REQUIREMENTS.md written; no phase plan yet
**Next action:** Run `/gsd-plan-phase 16` to plan Phase 16 (Planner + Executor Extraction). Read the source design doc first; resolve Open Questions #1, #2, #5 in the phase discussion.
