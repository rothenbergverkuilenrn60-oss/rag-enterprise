---
gsd_state_version: 1.0
milestone: v1.7
milestone_name: Memory Tech-Debt Burn-Down
status: planning
stopped_at: v1.7 opened — defining requirements
last_updated: "2026-05-17T04:00:00.000Z"
last_activity: "2026-05-17 — v1.7 Memory Tech-Debt Burn-Down milestone opened; PROJECT.md updated; requirements + roadmap pending"
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# STATE — EnterpriseRAG (v1.7 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17 — v1.7 opened)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.7 Memory Tech-Debt Burn-Down — 7 deferred items from v1.6 ship + end-of-milestone doc sweep

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-05-17 — Milestone v1.7 started

## Phase Overview

(Phases will be derived from REQUIREMENTS.md during roadmap step.)

## Accumulated Context

### Carry-Forward Decisions (still in force)

| Decision | Source | Why it matters going forward |
|----------|--------|------------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All v1.7 work runs on this stack; multi-tenancy preserved |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 / v1.6 Phase 24 | Reused for `LongTermMemory.get_relevant_facts()` cosine query |
| `diff-cover ≥ 80%` gate on touched files | v1.1 Phase 10 TEST-03 | All v1.7 PRs must pass; carries forward |
| Combined coverage `--fail-under=70` global floor | v1.3 Phase 15 / v1.5 Phase 22 | Per-module hard-fail gate inherited |
| Mock at consumer path (`services.<mod>.<dep>`) not source | v1.3 Phase 13+15 | v1.7 test refactors follow this verbatim |
| `BaseTool` ABC + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST` constant in `services/pipeline.py` | v1.4 Phase 17 | Memory tool surface stays untouched in v1.7 |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | ExtractorAgent reuses; not modified in v1.7 |
| Sub-agents do NOT inherit chat history | v1.3 D-06 | ExtractorAgent isolation preserved |
| INSERT-ONLY audit_log invariant (REVOKE UPDATE/DELETE) | v1.0 Phase 2 | TD-01 auto-create must preserve this — no UPDATE/DELETE grants in DDL |
| Audit-mode-before-enforce discipline for destructive sweeps | v1.6 Phase 25 EVICT-02 | TD-04 dedupe guard must default to audit-mode metric before any silent skip |
| Audit-write failure must NOT block GDPR/destructive action | v1.6 Phase 25 T1 | Symmetry preserved across v1.7 refactors |

### Resolved Blockers

None — v1.7 opens clean.

### Open Blockers Carried Into v1.7

None.

### Todos (carry-forward, NOT v1.7-scoped)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9/14 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [x] Push tags v1.1..v1.5 to origin — verified
- [ ] v1.8+ follow-up: Code-acting / SQLTool (10x roadmap #4) — sandbox selection unresolved
- [ ] v1.8+ follow-up: UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke test
- [ ] v1.8+ follow-up: SSE memory events (memory.extracted, memory.recalled) — explicit-trace differentiation extension
- [ ] v1.8+ follow-up: Per-tenant capacity overrides / importance decay for `LongTermMemory`
- [ ] v1.8+ follow-up: Per-module coverage floor raise (>70%) or branch-coverage activation (Phase 22 D-08 follow-up)
- [ ] v1.8+ follow-up: Docker Build CI fix (paddleocr / paddlex / paddlepaddle ABI churn — currently `continue-on-error: true`)

### Promoted Into v1.7 Active Scope

The following v1.7 candidates were promoted out of "todos" into requirements (see REQUIREMENTS.md):

- TD-01 `audit_log` auto-create
- TD-02 Per-test `create_app()` factory
- TD-03 `utils/asyncpg_helper.py` centralization
- TD-04 `save_fact` near-duplicate guard
- TD-05 `save_facts` batch path
- TD-06 Redis-mock fixture rollout
- TD-07 bge-m3 model dir layout fix
- DOC-01 doc + CHANGELOG sweep

## Session Continuity

**Last updated:** 2026-05-17 — v1.7 milestone opened via `/gsd-new-milestone`. PROJECT.md updated (Current Milestone → v1.7, v1.6 → Previous Milestone Archived). STATE.md reset to v1.7 frontmatter. REQUIREMENTS.md + ROADMAP.md pending in this same session.
**Stopped at:** v1.7 opened — defining requirements
**Next action:** Continue `/gsd-new-milestone` flow → REQUIREMENTS.md → ROADMAP.md (inline, since GSD subagents not installed).

**Planned Phase:** Phase 26 (first v1.7 phase — name TBD by roadmap step).
