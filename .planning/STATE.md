---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Fork Swarm, NLU & Quality
status: "roadmap_ready"
stopped_at: Roadmap created — ready for Phase 12 planning
last_updated: "2026-05-08"
last_activity: 2026-05-08 — v1.3 roadmap created (4 phases, 5 requirements)
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# STATE — EnterpriseRAG v1.3 Fork Swarm, NLU & Quality

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-08)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** Phase 12 — Fork-Agent Swarm

## Current Position

Phase: 12 (not started — roadmap ready)
Plan: —
Status: Ready for `/gsd-plan-phase 12`
Last activity: 2026-05-08 — v1.3 roadmap created

| Field | Value |
|-------|-------|
| Milestone | v1.3 Fork Swarm, NLU & Quality |
| Current phase | 12 — Fork-Agent Swarm |
| Current plan | — |
| Phase status | Not started |
| Overall progress | 0/4 phases |

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 12 | Fork-Agent Swarm | AGENT-03 | Not started |
| 13 | LLM Filter Fallback | NLU-02 | Not started |
| 14 | Frontend Split and DOM Modernization | UI-02 | Not started |
| 15 | Coverage Combine and 70% Floor | TEST-04, TEST-06 | Not started |

## Accumulated Context

### Carry-Forward from v1.2 (key decisions still in force)

| Decision | Source | Why it matters in v1.3 |
|----------|--------|------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All v1.3 work runs on this stack |
| Section heading text in embedded content; numeric IDs in metadata only | v1.1 Phase 8 D-02 | Any new chunker work must preserve this rule |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 | Pattern to reuse for any new filtered queries |
| Regex-first filter extractor in `services/nlu/filter_extractor.py` | v1.1 Phase 8 QUERY-01 | NLU-02 extends this module — regex path must remain the first branch |
| FastAPI StaticFiles mount at `/ui/`; `static/index.html → ui.html` symlink | v1.1 Phase 9 | UI-02 must preserve this; only add `ui.js` / `ui.css` alongside |
| `diff-cover ≥ 80%` gate on v1.1+ files | v1.1 Phase 10 TEST-03 | All v1.3 PRs MUST pass this gate |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | Sub-agents in Phase 12 reuse this interface — don't add `@abstractmethod` |
| `parallel_tool_calls=True` explicit in OpenAI; `disable_parallel_tool_use=False` explicit in Anthropic | v1.2 Phase 11 | Swarm coordinator inherits this pattern for sub-agent dispatch |
| `asyncio.gather` for concurrent tool execution | v1.2 Phase 11 | Phase 12 swarm uses `asyncio.gather` to run N sub-agents concurrently |

### Phase 12 Implementation Notes

- Build on `AgentQueryPipeline` or introduce `SwarmQueryPipeline` in `services/pipeline.py`
- Coordinator decomposition is itself an LLM call (prompt: "split this query into N independent sub-questions")
- Each sub-agent is a standalone coroutine calling `call_agentic_turn` with its own fresh `messages` list
- `MAX_SWARM_AGENTS = 5`, `MAX_SWARM_TURNS_PER_AGENT = 5` must be env-var-configurable (OPS-01 pattern)
- Synthesis call is a second LLM call: receives all N sub-agent final answers, returns one unified response
- Audit log fields: `swarm_n`, `per_agent_turns: list[int]`, `per_agent_tool_calls: list[int]`, `swarm_latency_ms`, `synthesis_latency_ms`
- N = 1 must fall back to single-agent path without spawning swarm machinery

### Phase 13 Implementation Notes

- Extend `FilterExtractor` in `services/nlu/filter_extractor.py` — keep existing regex logic untouched as first branch
- Cache: prefer `functools.lru_cache` for simplicity if Redis TTL not needed at this layer; revisit if multi-process needed
- `fallback_source: Literal["regex", "llm"] | None` — add to `QueryFilter` model or as wrapper field on extractor return
- LLM prompt must specify strict JSON schema; parse with `json.loads` inside try/except; return `None` on any parse failure
- Unit test must mock the LLM client and assert call count (not called on regex hit; called once on cache miss)

### Phase 14 Implementation Notes

- Extract CSS first (simpler, no logic), then JS (event wiring, DOM refs)
- `addEventListener` wiring: document-level `DOMContentLoaded` or module-level initialization in `ui.js`
- No bundler unless ES module splits are clearly beneficial — decide at implementation time per acceptance criterion 5
- Visual regression check: manual smoke test of upload + query + result flows; no automated visual diff required

### Phase 15 Implementation Notes

- TEST-04 (CI plumbing) must be done first within this phase; TEST-06 tests come second
- `coverage run --data-file=.coverage.unit` for unit suite; `coverage run --data-file=.coverage.integration` for integration suite
- `coverage combine .coverage.unit .coverage.integration` → `.coverage` → `coverage report --fail-under=70`
- Identify undercovered modules by running `coverage report` at v1.2 close; prioritize service modules over utils
- New tests must themselves pass the `diff-cover ≥ 80%` gate on the test file lines they introduce

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

**Last updated:** 2026-05-08 — v1.3 roadmap created (4 phases: 12–15)
**Stopped at:** Roadmap complete; ready for planning
**Next action:** `/gsd-plan-phase 12` (Fork-Agent Swarm)
