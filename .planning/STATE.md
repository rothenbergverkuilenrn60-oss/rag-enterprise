---
gsd_state_version: 1.0
milestone: v1.7
milestone_name: Memory Tech-Debt Burn-Down
status: Phase 28 planned (5 plans, 2 waves, plan-checker 0 BLOCKER + 4 WARNING fixed inline)
stopped_at: Phase 28 PLAN.md set written + plan-checker verdict (0 blockers; 4 warnings patched in plans 28-00/28-01/28-02/28-04); ready for /gsd-execute-phase 28
last_updated: "2026-05-17T22:00:00.000Z"
last_activity: "2026-05-17 — /gsd-execute-phase 27 complete. 5 plans across 3 waves (27-00 Wave 0 test infra, 27-01+27-02 Wave 1 parallel, 27-03→27-04 Wave 2 sequential). Verifier PASSED 5/5 SC: SC-1 create_app factory + parallel-contamination + 34-entry singleton inventory + 2 factory-migrated integration tests; SC-2 redis_mock fixture + ShortTermMemory._get_client delegate (TD-06 bonus) + D-22 diagnostic captured; SC-3 save_fact cosine precheck D-09 audit-mode-only (INSERT still runs, MEMORY_NEAR_DUPLICATE_SKIPPED enum + memory_near_duplicate_threshold setting); SC-4 save_facts batch (C1 unnest($1::text[]) WITH ORDINALITY + ::vector cast verified, C2 gather(return_exceptions=True) fallback verified, D-12 wrapper retention verified, D-17 ExtractorAgent migration); SC-5 latency benchmark captured (p50 25.31→5.51ms, speedup 19.80ms with MagicMock; ~123ms expected with real bge-m3) — pytest -m 'not benchmark' is default CI gate. ROADMAP SC-3 wording corrected to match D-09 (INSERT still runs). 8 v1.8+ follow-ups documented: silent-skip enforcement, TOCTOU mitigation, openai-SDK signature drift cleanup (+14 newly-exposed TD-02-style event-loop singleton leaks from marker rollout)."
progress:
  total_phases: 3
  completed_phases: 2
  total_plans: 10
  completed_plans: 10
  percent: 67
---

# STATE — EnterpriseRAG (v1.7 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17 — v1.7 opened)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.7 Memory Tech-Debt Burn-Down — 7 deferred items from v1.6 ship + end-of-milestone doc sweep

## Current Position

Phase: 28 — Doc Sweep + v1.7 Release (planned)
Plan: 5 PLAN.md files (28-00 runbook / 28-01 docs+CHANGELOG / 28-02 release-notes+tag / 28-03 REQUIREMENTS-v1.8 scaffold / 28-04 archive); Wave 1 = 28-00..03 parallel, Wave 2 = 28-04 sequential
Status: Ready for /gsd-execute-phase 28 (plan-checker 0 BLOCKER; 4 warnings patched inline — MILESTONES placeholder gate, STATE.md total_plans, RUNBOOK symlink-word constraint, TD→SUMMARY pre-write mapping check)
Last activity: 2026-05-17 — /gsd-execute-phase 27 complete. Wave 0 (27-00 test infra: tests/factories/app.py + redis_mock fixture + 34-entry _SINGLETON_INVENTORY + fakeredis dev dep). Wave 1 parallel (27-01 _configure_app(app) extraction from main.py + parallel-contamination tests + audit-suite SC-1; 27-02 ShortTermMemory._get_client delegate to utils.cache.get_redis bonus + uses_redis marker rollout to 4 files + 27-02-DIAGNOSTIC.md). Wave 2 sequential (27-03 save_fact cosine precheck D-09 audit-mode-only + MEMORY_NEAR_DUPLICATE_SKIPPED enum + memory_near_duplicate_threshold setting; 27-04 save_facts batch C1+C2+D-09+D-12+D-17 + 27-BENCHMARK.md SC-5 latency capture + memory-suite factory-migrated integration test). ROADMAP SC-3 wording fixed (INSERT still runs per D-09). 8 v1.8+ items deferred (silent-skip enforcement, TOCTOU mitigation, openai-SDK drift cleanup, +14 newly-exposed event-loop singleton leaks).

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 26 | Memory Infra Hygiene | TD-01, TD-03, TD-07 | ✅ Shipped 2026-05-17 (5 plans, 34 new tests) |
| 27 | Test Isolation + Memory Reliability | TD-02, TD-04, TD-05, TD-06 | ✅ Shipped 2026-05-17 (5 plans, 28+33 unit + 4 integration + 1 benchmark) |
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

**Last updated:** 2026-05-17 — `/gsd-ship` opened PR #9 (https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/pull/9) on branch `gsd/phase-26-memory-infra-hygiene`. PR base = `master`. 22 commits + 3522 insertions / 113 deletions across 30 files. Local master is ahead of origin/master by the same 22 commits (will reconcile via `git pull --rebase` after PR merges).
**Stopped at:** Phase 26 PR #9 awaiting CI + merge
**Next action:** Wait for CI + reviewer; after merge → `git checkout master && git pull --rebase` to sync local master. Then `/gsd-discuss-phase 27` (Test Isolation + Memory Reliability — TD-02 + TD-04 + TD-05 + TD-06). Phase 27 will also close the 16 pre-existing unit-test failures via Redis-mock fixture rollout.

**Planned Phase:** Phase 27 — Test Isolation + Memory Reliability.
