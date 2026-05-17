---
gsd_state_version: 1.0
milestone: v1.6
milestone_name: Memory Tool — Agent-Authored Long-Term Facts
status: "v1.6 milestone shipped + archived; awaiting next-milestone open"
stopped_at: v1.6 archived (PRs #5/#7/#8 merged; phase 23/24/25 dirs moved to milestones/v1.6-phases/; ROADMAP/REQUIREMENTS snapshotted; MILESTONES.md entry written)
last_updated: "2026-05-17T03:30:00.000Z"
last_activity: "2026-05-17 — v1.6 milestone archived: PRs #5 (Phase 23+24) + #7 (conftest infra) + #8 (Phase 25) merged; phase dirs archived to milestones/v1.6-phases/; ROADMAP/REQUIREMENTS snapshotted; MILESTONES.md v1.6 entry appended; ROADMAP.md collapsed Phases 23–25 into <details>; Progress table marked Complete ✓"
progress:
  total_phases: 3
  completed_phases: 3
  total_plans: 20
  completed_plans: 20
  percent: 100
---

# STATE — EnterpriseRAG (v1.6 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17 after v1.6 close)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.6 archived; next-milestone open paused per user

## Current Position

Phase: — (between milestones)
Plan: v1.6 archived (20/20 plans shipped across phases 23/24/25)
Status: v1.6 milestone archived; awaiting next-milestone open
Last activity: 2026-05-17 — v1.6 milestone archived: PRs #5 + #7 + #8 merged; phase 23/24/25 dirs archived to milestones/v1.6-phases/; ROADMAP/REQUIREMENTS snapshotted; MILESTONES.md entry written

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 23 | Background Extractor + schema migration | MEM-01..05 | Shipped (PR #5) — 2026-05-16 |
| 24 | pgvector RecallTool + semantic recall rewrite | MEM-06..10 | Shipped (PR #5) — 2026-05-16 |
| 25 | Eviction job + GDPR forget API | EVICT-01..03, GDPR-01..03 | Shipped (PR #8) — 2026-05-17 |

## Accumulated Context

### Carry-Forward Decisions (still in force)

| Decision | Source | Why it matters going forward |
|----------|--------|------------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All v1.6 work runs on this stack; multi-tenancy preserved |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 / v1.6 Phase 24 | Reused for `LongTermMemory.get_relevant_facts()` cosine query |
| `diff-cover ≥ 80%` gate on touched files | v1.1 Phase 10 TEST-03 | All v1.6 PRs passed; carries forward |
| Combined coverage `--fail-under=70` global floor | v1.3 Phase 15 / v1.5 Phase 22 | Per-module hard-fail gate inherited |
| Mock at consumer path (`services.<mod>.<dep>`) not source | v1.3 Phase 13+15 | Phase 25 unit tests follow this verbatim |
| `BaseTool` ABC + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST` constant in `services/pipeline.py` | v1.4 Phase 17 | `RecallTool` (Phase 24) plugs into the same surface |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | Extractor sub-agent (Phase 23) reuses provider-neutral interface |
| Sub-agents do NOT inherit chat history | v1.3 D-06 | Extractor sub-agent isolation follows this |
| INSERT-ONLY audit_log invariant (REVOKE UPDATE/DELETE) | v1.0 Phase 2 | Phase 25 forget + eviction write-only; never updates/deletes audit rows |
| Audit-mode-before-enforce discipline for destructive sweeps | v1.6 Phase 25 EVICT-02 | First-prod-run runbook locked; new destructive CLIs follow this pattern |
| Audit-write failure must NOT block GDPR/destructive action | v1.6 Phase 25 T1 | Try/except wrap with loud ERROR log; applied symmetrically in forget controller + eviction script |

### Resolved Blockers

None — all v1.6 blockers closed at ship.

### Open Blockers Carried Into Next Milestone

None.

### Todos (carry-forward, not v1.6-scoped but tracked)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9/14 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10/15 live PR through CI confirms `coverage-combine` job + HTML artifact (now happening on every PR)
- [x] Push tags v1.1..v1.5 to origin — verified
- [ ] v1.7+ follow-up: `audit_log` table auto-creation (`audit_service._create_tables` matching `LongTermMemory._create_tables` pattern). DDL currently in docstring only — caught at Phase 25 ship.
- [ ] v1.7+ follow-up: Module-level singleton graph + FastAPI app singleton — consider per-test `create_app()` factory to make integration tests cheaper.
- [ ] v1.7+ follow-up: `?ssl=disable` URL-param strip duplicated in `memory_service` + `audit_service` — centralize as `utils/asyncpg_helper.py::create_pool_from_dsn`.
- [ ] v1.7+ follow-up: `LongTermMemory.save_fact` near-duplicate guard (`SELECT 1 ... <=> $embedding < 0.05` precheck). Eng-review A3 from Phase 23.
- [ ] v1.7+ follow-up: `LongTermMemory.save_facts(list[ExtractedFact])` batch path — 1× `embed_batch` + `executemany` cuts 3× round-trips to 1. Eng-review perf-2 from Phase 23.
- [ ] v1.7+ follow-up: Redis-mock fixture rollout — 32 pre-existing baseline failures in unit suite all stem from missing Redis on CI/test hosts.
- [ ] v1.7+ follow-up: Code-acting / SQLTool (10x roadmap #4) — sandbox selection unresolved.
- [ ] v1.7+ follow-up: UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke test.

## Session Continuity

**Last updated:** 2026-05-17 — v1.6 milestone archived: PRs #5 + #7 + #8 merged (squash `e89bad0` + `051dddb` + `7fea209`); phase 23/24/25 directories moved to `milestones/v1.6-phases/`; `milestones/v1.6-ROADMAP.md` + `milestones/v1.6-REQUIREMENTS.md` snapshots written; MILESTONES.md entry appended; ROADMAP.md v1.6 section collapsed into `<details>` and Progress table phases 23/24/25 marked Complete ✓.
**Stopped at:** v1.6 archived; awaiting next-milestone open (paused per user)
**Next action:** Open v1.7 with `/gsd-new-milestone` when ready. Optional: `/gsd-extract-learnings` (v1.6 patterns), v1.7 conftest infra refactor (singleton graph + per-test app factory + audit_log auto-create + asyncpg ssl helper).

**Planned Phase:** —
