---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Fork Swarm, NLU & Quality
status: "planning"
stopped_at: Defining requirements
last_updated: "2026-05-08"
last_activity: 2026-05-08 — Milestone v1.3 started
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# STATE — EnterpriseRAG v1.3 Fork Swarm, NLU & Quality

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-08)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** Defining v1.3 requirements

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-05-08 — Milestone v1.3 started

| Field | Value |
|-------|-------|
| Milestone | v1.3 Fork Swarm, NLU & Quality |
| Current phase | — |
| Current plan | — |
| Phase status | — |
| Overall progress | 0/0 phases |

## Phase Overview

(populated after roadmap creation)

## Accumulated Context

### Carry-Forward from v1.2 (key decisions still in force)

| Decision | Source | Why it matters in v1.3 |
|----------|--------|------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All v1.3 work runs on this stack |
| Section heading text in embedded content; numeric IDs in metadata only | v1.1 Phase 8 D-02 | Any new chunker work must preserve this rule |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 | Pattern to reuse for any new filtered queries |
| Regex-first filter extractor in `services/nlu/filter_extractor.py` | v1.1 Phase 8 QUERY-01 | LLM fallback (NLU-02) is v1.3 candidate — extends this module |
| FastAPI StaticFiles mount at `/ui/`; `static/index.html → ui.html` symlink | v1.1 Phase 9 | If JS/CSS extracted in v1.3, preserve this approach |
| `diff-cover ≥ 80%` gate on v1.1+ files | v1.1 Phase 10 TEST-03 | All v1.3 PRs MUST pass this gate |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | All future LLM adapters inherit this contract — don't add `@abstractmethod` |
| `parallel_tool_calls=True` explicit in OpenAI; `disable_parallel_tool_use=False` explicit in Anthropic | v1.2 Phase 11 | Defaults exist but explicit is the pattern — apply to any new adapter |
| `asyncio.gather` for concurrent tool execution; `zip(tool_calls, tool_outputs)` for ID correlation | v1.2 Phase 11 | Pattern to follow in any future agentic extension (swarm, sub-agent) |

### v1.3 Candidate Themes (deferred from v1.2)

1. **AGENT-03 — True swarm with fork agents** — multi-agent orchestration; requires clean v1.2 `call_agentic_turn` baseline
2. **NLU-02 — LLM-based filter extractor** — extends `services/nlu/filter_extractor.py` with LLM fallback when regex misses
3. **UI-02 — Frontend modernization** — JS/CSS extraction from `static/ui.html`; potentially React/Vue + build step
4. **TEST-04 — Integration-test coverage merging** — `coverage combine` across unit + integration
5. **TEST-06 — Raise legacy 46% global coverage floor**

### Blockers

None.

### Todos (carry-forward, not v1.3-scoped but tracked)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10 live PR through CI confirms `coverage-diff` step + HTML artifact (natural confirmation on first PR)
- [ ] Push tags `v1.1` and `v1.2` to origin (currently local-only)
- [ ] PR #1 + PR #2 review + merge

## Session Continuity

**Last updated:** 2026-05-08 — v1.2 milestone archived; v1.2 git tag created locally
**Stopped at:** v1.2 milestone close complete
**Next action:** Run `/gsd-new-milestone v1.3` to define requirements + roadmap
