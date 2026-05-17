---
gsd_state_version: 1.0
milestone: v1.7
milestone_name: Memory Tech-Debt Burn-Down
status: v1.7 shipped — Phase 28 complete; v1.8 not yet opened
stopped_at: Phase 28 28-04-SUMMARY committed; v1.7 archived to .planning/milestones/v1.7-*; CHANGELOG + release-notes + RUNBOOK + REQUIREMENTS-v1.8 scaffold all committed; ready for /gsd-new-milestone for v1.8 open
last_updated: "2026-05-17T23:30:00.000Z"
last_activity: "2026-05-17 — /gsd-execute-phase 28 complete. 5 plans across 2 waves: Wave 1 parallel (28-00 docs/RUNBOOK.md three-section ops runbook; 28-01 README + ARCHITECTURE + memory-eviction surgical patches + CHANGELOG v1.7.0 entry; 28-02 docs/release-notes-v1.7.md + .planning/milestones/v1.7-release-tag.md; 28-03 .planning/REQUIREMENTS-v1.8.md scaffold with 7 pre-seeded items SK/TOC/OAI/EVT/MYPY/TEST-INFRA). Wave 2 sequential (28-04 v1.7 milestone archive — ROADMAP+REQUIREMENTS snapshots, git mv Phase 26/27/28 → milestones/v1.7-phases/, ROADMAP v1.7 section collapsed into <details>, MILESTONES.md created at repo root with 8 v1.* backfill entries, STATE.md updated). v1.7 Memory Tech-Debt Burn-Down SHIPPED — 3 phases / 15 plans / 8 requirements (TD-01..07 + DOC-01) / 0 carry-forward blockers."
progress:
  total_phases: 3
  completed_phases: 3
  total_plans: 15
  completed_plans: 15
  percent: 100
---

# STATE — EnterpriseRAG (v1.7 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17 — v1.7 opened)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.7 Memory Tech-Debt Burn-Down — 7 deferred items from v1.6 ship + end-of-milestone doc sweep

## Current Position

Phase: v1.8 (not yet opened — run /gsd-new-milestone)
Plan: n/a
Status: v1.7 milestone shipped 2026-05-17 — all 3 phases (26, 27, 28) complete; 15/15 plans; 8/8 requirements; archived to .planning/milestones/v1.7-*
Last activity: 2026-05-17 — /gsd-execute-phase 28 complete. 5 plans across 2 waves; doc sweep + release artifacts (RUNBOOK / CHANGELOG / release-notes / REQUIREMENTS-v1.8 scaffold) + v1.7 milestone archive (snapshot + git mv phase dirs + ROADMAP collapse + MILESTONES.md backfill + STATE.md ship marker).

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 26 | Memory Infra Hygiene | TD-01, TD-03, TD-07 | ✅ Shipped 2026-05-17 (5 plans, 34 new tests) |
| 27 | Test Isolation + Memory Reliability | TD-02, TD-04, TD-05, TD-06 | ✅ Shipped 2026-05-17 (5 plans, 28+33 unit + 4 integration + 1 benchmark) |
| 28 | Doc Sweep + v1.7 Release | DOC-01 | ✅ Shipped 2026-05-17 (5 plans, doc sweep + v1.7 release artifacts) |

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

### Open Blockers Carried Into v1.8

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
- [ ] v1.8+ follow-up: backport Phase 26 Plan 26-04 P1 fix (`_get_pool` resets `self._pool = None` on `_create_tables` failure) to `services/memory/memory_service.py::LongTermMemory._get_pool` — same partial-init bug exists in v1.6-shipped MEM-* path. Surfaced by `/plan-eng-review 26` Finding P1.
- [ ] v1.8+ follow-up: graceful-shutdown close-then-reuse discipline — after `audit_service.close()` / `memory_service.close()`, in-flight background tasks may lazily re-build the pool. Needs project-wide `_closed: bool` guard pattern. Surfaced by `/plan-eng-review 26` architecture notes.
- [ ] v1.8+ follow-up: AuditService pool `application_name=audit_service` for `pg_stat_activity` dashboard visibility. Surfaced by `/plan-eng-review 26` Claude's Discretion review.
- [ ] v1.8+ follow-up: **openai SDK signature drift cleanup** — 32 unit tests fail with `APIError.__init__() missing 1 required positional argument: 'request'`. Files: `test_agent_pipeline_refactor.py` (11), `test_agent_sse.py` (9), `test_pipeline_coverage.py` (10), `test_feedback_ab_forward.py` (1), `test_memory_controller.py`, `test_recall_tool.py`. Has been latent on master since v1.5 (lint gate masked it). Surfaced by Phase 26 PR #9 CI (run 25981918166 — first run where lint passed and unit tests actually executed). NOT introduced by Phase 26.

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

**Last updated:** 2026-05-17 — `/gsd-execute-phase 28` complete. v1.7 Memory Tech-Debt Burn-Down SHIPPED — 3 phases / 15 plans / 8 requirements / 0 carry-forward blockers. Archived to `.planning/milestones/v1.7-{ROADMAP,REQUIREMENTS}.md` + `.planning/milestones/v1.7-phases/{26,27,28}-*/`. MILESTONES.md created at repo root with v1.0..v1.7 backfill.
**Stopped at:** Phase 28 28-04-SUMMARY committed; v1.7 archive complete.
**Next action:** Run `/gsd-new-milestone` to open v1.8 (pre-seeded items in `.planning/REQUIREMENTS-v1.8.md`: SK-01, TOC-01, OAI-01, EVT-01, MYPY-01, TEST-INFRA-01, TEST-INFRA-02). Optional pre-v1.8: cut the v1.7.0 annotated tag per `.planning/milestones/v1.7-release-tag.md`.

**Planned Phase:** v1.8 not yet opened.
