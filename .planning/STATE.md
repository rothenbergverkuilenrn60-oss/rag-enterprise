---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Agentic Layer + Swarm
status: Defining requirements
stopped_at: Phase 11 context gathered
last_updated: "2026-05-08T11:22:08.674Z"
last_activity: 2026-05-08 — Milestone v1.2 started; v1.1 archived + tagged
progress:
  total_phases: 1
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
---

# STATE — EnterpriseRAG v1.2 Agentic Layer + Swarm

## Project Reference

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** Defining v1.2 requirements

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-05-08 — Milestone v1.2 started; v1.1 archived + tagged

| Field | Value |
|-------|-------|
| Milestone | v1.2 Agentic Layer + Swarm |
| Current phase | — |
| Current plan | — |
| Phase status | — |
| Overall progress | 0/0 phases (v1.2 not yet roadmapped) |

## Phase Overview

(empty — run `/gsd-new-milestone v1.2` to define requirements + roadmap)

## Accumulated Context

### Carry-Forward from v1.1 (key decisions still in force)

| Decision | Source | Why it matters in v1.2 |
|----------|--------|------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All v1.2 retrieval work runs on this stack |
| Section heading text in embedded content; numeric IDs in metadata only | v1.1 Phase 8 D-02 | Any new chunker work must preserve this rule |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 | Pattern to reuse for any new filtered queries |
| Regex-first filter extractor in `services/nlu/filter_extractor.py` | v1.1 Phase 8 QUERY-01 | LLM fallback is on v1.2 candidate list — extends this module |
| FastAPI StaticFiles mount at `/ui/` | v1.1 Phase 9 UI-01 | Frontend assets live in `static/` |
| `static/index.html → ui.html` symlink | v1.1 Phase 9 deviation | If JS/CSS extracted in v1.2, preserve this approach |
| `diff-cover ≥ 80%` gate on v1.1+ files | v1.1 Phase 10 TEST-03 | All v1.2 PRs MUST pass this gate |

### v1.2 Candidate Themes (captured during v1.1, awaiting prioritization)

1. **Provider-agnostic agentic layer** — `BaseLLMClient.call_agentic_turn` abstract method. Closes the OpenAI/Anthropic gap in `AgentQueryPipeline` (currently OpenAI silently falls back to non-agentic via `services/pipeline.py:599-604`). Office-hours design APPROVED 2026-05-08.
2. **Parallel tool-call burst** (single-turn multi-call) — README differentiator; uses `parallel_tool_calls=True` (OpenAI) / `disable_parallel_tool_use=False` (Anthropic). OpenAI probe verified working through OneAPI gateway.
3. **True swarm with fork agents** — references `claude-code` `forkedAgent.ts` pattern; deeper architectural change.
4. **LLM-based filter extractor** (fallback when regex misses) — extends `services/nlu/filter_extractor.py`.
5. **Frontend modernization** (JS/CSS extraction; DOM API rewrites; potentially React/Vue/build step).
6. **Integration-test coverage merging** via `coverage combine` — extends Phase 10 gate to integration paths.
7. **Per-file `# coverage:ignore-diff` overrides** — escape hatch if main.py-style boot becomes recurring blocker.
8. **Raising legacy 46% global coverage floor**.

### Open Questions (v1.2)

1. Which v1.2 candidate themes ship together vs separate? (office-hours design proposed: Step 0 + v0 in one milestone, v1 swarm in next)
2. Anthropic API key availability — Step 0 abstraction must work for both providers but live test only via OpenAI without key.
3. Migration plan for existing `agent_mode: bool = False` field in `utils/models.py:215` (currently dead code in OpenAI mode).
4. Should `services/pipeline.py:599-604` Anthropic-only gate be removed in Step 0 PR or in a follow-up?

### Pitfalls to Carry into v1.2

- `BaseLLMClient` abstraction must NOT leak provider-specific tool-call wire formats into call sites (`AgentQueryPipeline`)
- `parallel_tool_calls=True` is OpenAI default but must be EXPLICIT in Anthropic adapter (`disable_parallel_tool_use=False`)
- Worktree `isolation="worktree"` workflow has been used 4 phases without incident — keep this pattern for v1.2

### Blockers

None.

### Todos (carry-forward, not v1.2-scoped but tracked)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10 live PR through CI confirms `coverage-diff` step + HTML artifact (natural confirmation on first PR)
- [ ] Push tag `v1.1` to origin (currently local-only)
- [ ] PR #1 review + merge

## Session Continuity

**Last updated:** 2026-05-08 — v1.1 milestone archived; v1.1 git tag created locally
**Stopped at:** Phase 11 context gathered
**Next action:** Run `/gsd-new-milestone v1.2` (resume) to define requirements + roadmap from office-hours design + carry-forward themes
