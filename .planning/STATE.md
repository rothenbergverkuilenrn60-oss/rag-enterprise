---
gsd_state_version: 1.0
milestone: v1.7
milestone_name: Memory Tech-Debt Burn-Down
status: Phase 26 SHIPPED — TD-01 + TD-03 + TD-07 closed
stopped_at: Phase 26 verified passed (5/5 plans, 34/34 new tests green)
last_updated: "2026-05-17T13:00:00.000Z"
last_activity: "2026-05-17 — /gsd-execute-phase 26 complete: 5 plans shipped in 3 waves, 34 new tests (29 unit + 5 integration), eng-review fixes verified, 26-VERIFICATION.md written"
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 5
  completed_plans: 5
  percent: 33
---

# STATE — EnterpriseRAG (v1.7 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17 — v1.7 opened)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.7 Memory Tech-Debt Burn-Down — 7 deferred items from v1.6 ship + end-of-milestone doc sweep

## Current Position

Phase: 26 — Memory Infra Hygiene ✅ SHIPPED
Plan: 5/5 complete (W1 26-01 + 26-02, W2 26-03 + 26-04, W3 26-05); 34 new tests green
Status: Awaiting Phase 27 (Test Isolation + Memory Reliability — TD-02, TD-04, TD-05, TD-06)
Last activity: 2026-05-17 — Phase 26 execute + verify complete. New code: `utils/asyncpg_helper.py` (NEW), `config/settings.py::resolve_embedding_model_path`, `LongTermMemory.close()`, `MemoryService.close()`, `AuditService._get_pool` + `_create_tables` + `close()`, `main.py` lifespan shutdown wiring

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 26 | Memory Infra Hygiene | TD-01, TD-03, TD-07 | ✅ Shipped 2026-05-17 (5 plans, 34 new tests) |
| 27 | Test Isolation + Memory Reliability | TD-02, TD-04, TD-05, TD-06 | Planning |
| 28 | Doc Sweep + v1.7 Release | DOC-01 | Planning |

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
- [ ] v1.8+ follow-up: backport Phase 26 Plan 26-04 P1 fix (`_get_pool` resets `self._pool = None` on `_create_tables` failure) to `services/memory/memory_service.py::LongTermMemory._get_pool` — same partial-init bug exists in v1.6-shipped MEM-* path. Surfaced by `/plan-eng-review 26` Finding P1.
- [ ] v1.8+ follow-up: graceful-shutdown close-then-reuse discipline — after `audit_service.close()` / `memory_service.close()`, in-flight background tasks may lazily re-build the pool. Needs project-wide `_closed: bool` guard pattern. Surfaced by `/plan-eng-review 26` architecture notes.
- [ ] v1.8+ follow-up: AuditService pool `application_name=audit_service` for `pg_stat_activity` dashboard visibility. Surfaced by `/plan-eng-review 26` Claude's Discretion review.

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

**Last updated:** 2026-05-17 — `/gsd-execute-phase 26` shipped all 5 plans across 3 waves. New artifacts: `utils/asyncpg_helper.py` + `config/settings.py::resolve_embedding_model_path` + `LongTermMemory.close()` + `MemoryService.close()` + `AuditService._get_pool/_create_tables/close()` + main.py lifespan wiring. 34 new tests (29 unit + 5 integration) all green; v1.6 audit + memory suites (116 unit tests) still green. Eng-review fixes A1/A2/C1/P1 + R1 regression test verified. 26-VERIFICATION.md status: passed.
**Stopped at:** Phase 26 shipped; awaiting Phase 27
**Next action:** `/gsd-discuss-phase 27` → `/gsd-plan-phase 27` → `/gsd-execute-phase 27`. Phase 27 = Test Isolation + Memory Reliability (TD-02 create_app factory + TD-04 save_fact dedupe + TD-05 save_facts batch + TD-06 Redis-mock fixture). Or `/gsd-ship` to PR Phase 26 first.

**Planned Phase:** Phase 27 — Test Isolation + Memory Reliability.

**Planned Phase:** Phase 26 — Memory Infra Hygiene (TD-01 + TD-03 + TD-07).
