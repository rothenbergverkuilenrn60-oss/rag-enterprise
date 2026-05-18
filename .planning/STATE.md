---
gsd_state_version: 1.0
milestone: v1.9
milestone_name: Hardening Round 3
status: verified
stopped_at: .planning/phases/33-autouse-mock-opt-out-flaky-failures/33-VERIFICATION.md
last_updated: "2026-05-18T16:00:00.000Z"
last_activity: 2026-05-18
progress:
  total_phases: 5
  completed_phases: 3
  total_plans: 4
  completed_plans: 4
  percent: 100
---

# STATE — EnterpriseRAG (v1.9 Hardening Round 3 — phase 33 executed)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-18 — v1.9 planning started)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** Phase 33 executed; awaiting verifier sign-off, then advance to Phase 34.

## Current Position

Phase: 33
Plan: 33-00 + 33-01 (both complete + verified)
Status: Verified (passed) — ready to advance to Phase 34
Last activity: 2026-05-18

## Phase Overview

| Phase | Name | Status | Plans | REQ-IDs |
|-------|------|--------|-------|---------|
| 31 | Event-Loop Leak Sweep | Not started | 0/0 (TBD) | EVT-02 |
| 32 | mypy --strict Cleanup | Not started | 0/0 (TBD) | MYPY-02, MYPY-03, MYPY-04 |
| 33 | Autouse Opt-Out + Order-Dependent Failures | Verified ✓ | 2/2 | TEST-08, TEST-09 |
| 34 | Sentinel Drift Refresh | Not started | 0/0 (TBD) | TEST-10, TEST-11 |
| 35 | Planning Artifact Backfill | Not started | 0/0 (TBD) | DOC-02, DOC-03 |

## Accumulated Context

### Carry-Forward Decisions (still in force)

| Decision | Source | Why it matters going forward |
|----------|--------|------------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All work runs on this stack; multi-tenancy preserved |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 / v1.6 Phase 24 | Reused for `LongTermMemory.get_relevant_facts()` cosine query |
| `diff-cover ≥ 80%` gate on touched files | v1.1 Phase 10 TEST-03 | All PRs must pass |
| Combined coverage `--fail-under=70` global floor | v1.3 Phase 15 / v1.5 Phase 22 | Per-module hard-fail gate inherited |
| Mock at consumer path (`services.<mod>.<dep>`) not source | v1.3 Phase 13+15 | Test refactors follow this verbatim |
| `BaseTool` ABC + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST` constant in `services/pipeline.py` | v1.4 Phase 17 | Memory tool surface preserved |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | ExtractorAgent reuses |
| Sub-agents do NOT inherit chat history | v1.3 D-06 | ExtractorAgent isolation preserved |
| INSERT-ONLY audit_log invariant (REVOKE UPDATE/DELETE) | v1.0 Phase 2 | Auto-create paths must preserve this |
| Audit-mode-before-enforce discipline for destructive sweeps | v1.6 Phase 25 EVICT-02 | Dedupe guards default to audit-mode metric before silent skip |
| Audit-write failure must NOT block GDPR/destructive action | v1.6 Phase 25 T1 | Symmetry preserved |
| **TOC-01 advisory lock** wraps save_facts precheck+INSERT inside outer txn | v1.8 Phase 29-00 | All concurrent writers serialize on `(user_id, tenant_id)` to close the TOCTOU race |
| **SK-01 silent-skip filter** excludes near-duplicates from `rows_to_insert` before `executemany` | v1.8 Phase 29-01 | Audit-mode → enforce transition complete; audit row still fires |
| **`# type: ignore[code]  # why:` silence convention** with cap-bounded sweeps | v1.8 Phase 30-03 | All future mypy silences must follow this discipline |
| **`tests/integration/conftest.py` autouse mocks `HuggingFaceEmbedder.__init__` + `CrossEncoderReranker.__init__`** | v1.8 Phase 30-02 | Integration tests no longer require bge-m3 download; **caveat: no opt-out for real-embedder tests yet — TEST-08 v1.9** |

### Resolved Blockers

None — v1.8 shipped clean. v1.9 inherits no blockers.

### Open Blockers Carried Into v1.9

None blocking. v1.9 scope = paying down v1.8 deferred items (all known, all enumerated below).

### v1.9 Inherited Tech Debt (now promoted to active milestone scope)

All 10 items are now mapped to v1.9 phases via REQUIREMENTS.md + ROADMAP.md:

- **EVT-02** → Phase 31 — ~10 remaining event-loop singleton leak sites; `_SINGLETON_INVENTORY` grows from 34 toward 48; needs PG host enumeration
- **MYPY-02** → Phase 32 — 7 violations in `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/deferred-items.md`
- **MYPY-03** → Phase 32 — bare `# type: ignore` at `services/nlu/nlu_service.py:538` (pre-existing since v1.3/v1.6)
- **MYPY-04** → Phase 32 — asyncpg + pgvector.asyncpg `import-untyped` silences in `tests/integration/memory/test_save_facts_toctou.py:32, 57`
- **TEST-08** → Phase 33 — `@pytest.mark.real_embedder` opt-out marker for `tests/integration/conftest.py` autouse mock
- **TEST-09** → Phase 33 — 7 order-dependent unit-test failures (registry-singleton pollution + `embed_one`/`embed_batch` mock mismatch)
- **TEST-10** → Phase 34 — `test_no_v1_5_regression` — `q=` vs `query=` GenerationRequest schema drift
- **TEST-11** → Phase 34 — `test_ui_static_serves_html` — `<title>` sentinel drift since v1.4
- **DOC-02** → Phase 35 — Phase 29 + 30 `*-VALIDATION.md` (Nyquist backfill via `/gsd:validate-phase`)
- **DOC-03** → Phase 35 — MILESTONES.md v1.7 entry backfill (v1.7-close oversight)

### Carry-forward Todos (NOT v1.9-scoped — still tracked for v1.10+)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9/14 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] v1.10+ follow-up: Code-acting / SQLTool (10x roadmap #4) — sandbox selection unresolved
- [ ] v1.10+ follow-up: UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke test
- [ ] v1.10+ follow-up: SSE memory events (memory.extracted, memory.recalled) — explicit-trace differentiation extension
- [ ] v1.10+ follow-up: Per-tenant capacity overrides / importance decay for `LongTermMemory`
- [ ] v1.10+ follow-up: Per-module coverage floor raise (>70%) or branch-coverage activation (Phase 22 D-08 follow-up)
- [ ] v1.10+ follow-up: Docker Build CI fix (paddleocr / paddlex / paddlepaddle ABI churn — currently `continue-on-error: true`)
- [ ] v1.10+ follow-up: backport Phase 26 Plan 26-04 P1 fix (`_get_pool` resets `self._pool = None` on `_create_tables` failure) to `services/memory/memory_service.py::LongTermMemory._get_pool` — same partial-init bug exists in v1.6-shipped MEM-* path
- [ ] v1.10+ follow-up: graceful-shutdown close-then-reuse discipline — project-wide `_closed: bool` guard pattern
- [ ] v1.10+ follow-up: AuditService pool `application_name=audit_service` for `pg_stat_activity` dashboard visibility

## Session Continuity

**Last updated:** 2026-05-18 — gsd-roadmapper wrote ROADMAP.md (5 phases, 31–35), updated REQUIREMENTS.md traceability (10/10 mapped), refreshed STATE.md Phase Overview. No deviations from the input phase split.
**Stopped at:** .planning/phases/33-autouse-mock-opt-out-flaky-failures/33-CONTEXT.md
**Next action:** Run `/gsd:plan-phase 31` to decompose the Event-Loop Leak Sweep into executable plans.
