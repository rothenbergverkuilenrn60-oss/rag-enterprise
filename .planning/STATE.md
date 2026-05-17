---
gsd_state_version: 1.0
milestone: v1.8
milestone_name: Production Hardening Round 2
status: v1.8 opened — Phase 29 + 30 in planning; 7 pre-seeded reqs (SK-01, TOC-01, TEST-INFRA-02 → Phase 29; OAI-01, EVT-01, TEST-INFRA-01, MYPY-01 → Phase 30)
stopped_at: /gsd-new-milestone complete — REQUIREMENTS-v1.8.md promoted to active REQUIREMENTS.md; PROJECT.md + ROADMAP.md + STATE.md updated; ready for /gsd-discuss-phase 29
last_updated: "2026-05-17T23:45:00.000Z"
last_activity: "2026-05-17 — /gsd-new-milestone complete. v1.8 Production Hardening Round 2 opened. Skipped research per user pref (pre-seeded backlog from v1.7 Phase 28 plan 28-03 sufficient). 7 reqs promoted: TOC-01 + SK-01 + TEST-INFRA-02 into Phase 29 (TOCTOU + Silent-Skip Enforcement — paired by same code paths); OAI-01 + EVT-01 + TEST-INFRA-01 + MYPY-01 into Phase 30 (Test Infra + mypy Hardening). Zero new user-facing capabilities — pure reliability + test infra polish."
progress:
  total_phases: 2
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# STATE — EnterpriseRAG (v1.8 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17 — v1.8 opened)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.8 Production Hardening Round 2 — 7 deferred items from v1.7 (silent-skip enforcement + TOCTOU + openai SDK drift + event-loop leaks + mypy strict sweep + test infra)

## Current Position

Phase: 29 — TOCTOU + Silent-Skip Enforcement (planning — not yet discussed)
Plan: n/a — next action `/gsd-discuss-phase 29`
Status: v1.8 opened 2026-05-17; Phase 29 + 30 in planning; 0/2 phases complete; 0/0 plans (none drafted yet)
Last activity: 2026-05-17 — /gsd-new-milestone complete. v1.8 Production Hardening Round 2 opened with 7 pre-seeded reqs split across Phase 29 + 30.

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 29 | TOCTOU + Silent-Skip Enforcement | TOC-01, SK-01, TEST-INFRA-02 | Planning (not yet discussed) |
| 30 | Test Infra + mypy Hardening | OAI-01, EVT-01, TEST-INFRA-01, MYPY-01 | Planning (not yet discussed) |

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

### Todos (carry-forward, NOT v1.8-scoped)

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

### Promoted Into v1.8 Active Scope

The following v1.7-deferred candidates were promoted into v1.8 requirements (see REQUIREMENTS.md):

- SK-01 Silent-skip near-duplicate enforcement (Phase 29)
- TOC-01 TOCTOU mitigation (Phase 29)
- TEST-INFRA-02 save_facts precheck test rewrite (Phase 29)
- OAI-01 openai SDK signature drift cleanup (Phase 30)
- EVT-01 +14 event-loop singleton leaks (Phase 30)
- TEST-INFRA-01 extractor_e2e embedder fixture ordering (Phase 30)
- MYPY-01 mypy --strict cleanup (Phase 30)

## Session Continuity

**Last updated:** 2026-05-17 — `/gsd-new-milestone` complete. v1.8 Production Hardening Round 2 opened. 7 pre-seeded reqs from v1.7 Phase 28 plan 28-03 scaffold promoted to active. Phase 29 = TOC-01 + SK-01 + TEST-INFRA-02 (same code paths). Phase 30 = OAI-01 + EVT-01 + TEST-INFRA-01 + MYPY-01 (test surface + type-check sweep).
**Stopped at:** REQUIREMENTS.md + PROJECT.md + ROADMAP.md + STATE.md updated for v1.8 open; ready for Phase 29 discussion.
**Next action:** Run `/gsd-discuss-phase 29` (TOCTOU + Silent-Skip Enforcement) to clarify approach. Optional pre-Phase-29: cut v1.7.0 annotated tag per `.planning/milestones/v1.7-release-tag.md` (independent ceremony).

**Planned Phase:** Phase 29 — TOCTOU + Silent-Skip Enforcement.
