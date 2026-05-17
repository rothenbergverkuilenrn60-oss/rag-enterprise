---
gsd_state_version: 1.0
milestone: v1.8
milestone_name: Production Hardening Round 2
status: shipped
shipped_at: "2026-05-17T22:25:00Z"
last_updated: "2026-05-17T22:25:00Z"
last_activity: 2026-05-17 — /gsd-complete-milestone v1.8 — archived v1.8 (ROADMAP + REQUIREMENTS + AUDIT to milestones/), MILESTONES.md entry appended, PROJECT.md evolved, RETROSPECTIVE.md updated, tag v1.8.0 created.
progress:
  total_phases: 2
  completed_phases: 2
  total_plans: 7
  completed_plans: 6
  superseded_plans: 1
  percent: 100
---

# STATE — EnterpriseRAG (post-v1.8 shipped; v1.9 planning placeholder)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-17 — v1.8 shipped)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** Planning v1.9 (no requirements drafted yet). Run `/gsd-new-milestone` to scaffold v1.9.

## Current Position

Phase: n/a — between milestones
Plan: n/a — next action `/gsd-new-milestone` (questioning → research → requirements → roadmap)
Status: v1.8 shipped 2026-05-17 (Phases 29 + 30 verified `passed` on PG host; milestone audit `passed`; 7 tech debt items routed to v1.9).
Last activity: 2026-05-17 — /gsd-complete-milestone v1.8 — archive + tag complete.

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 29 | TOCTOU + Silent-Skip Enforcement | TOC-01, SK-01, TEST-INFRA-02 | ✅ Shipped (v1.8) |
| 30 | Test Infra + mypy Hardening | OAI-01, EVT-01, TEST-INFRA-01, MYPY-01 | ✅ Shipped (v1.8 — 1 plan superseded; accepted override) |

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
| **`tests/integration/conftest.py` autouse mocks `HuggingFaceEmbedder.__init__` + `CrossEncoderReranker.__init__`** | v1.8 Phase 30-02 | Integration tests no longer require bge-m3 download; **caveat: no opt-out for real-embedder tests yet (v1.9 follow-up)** |

### Resolved Blockers

None — v1.8 ships clean.

### Open Blockers Carried Into v1.9

None blocking. Tech debt enumerated below.

### Todos (carry-forward, NOT yet promoted to v1.9 scope)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9/14 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [x] Push tags v1.1..v1.5 to origin — verified
- [ ] v1.9+ follow-up: Code-acting / SQLTool (10x roadmap #4) — sandbox selection unresolved
- [ ] v1.9+ follow-up: UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke test
- [ ] v1.9+ follow-up: SSE memory events (memory.extracted, memory.recalled) — explicit-trace differentiation extension
- [ ] v1.9+ follow-up: Per-tenant capacity overrides / importance decay for `LongTermMemory`
- [ ] v1.9+ follow-up: Per-module coverage floor raise (>70%) or branch-coverage activation (Phase 22 D-08 follow-up)
- [ ] v1.9+ follow-up: Docker Build CI fix (paddleocr / paddlex / paddlepaddle ABI churn — currently `continue-on-error: true`)
- [ ] v1.9+ follow-up: backport Phase 26 Plan 26-04 P1 fix (`_get_pool` resets `self._pool = None` on `_create_tables` failure) to `services/memory/memory_service.py::LongTermMemory._get_pool` — same partial-init bug exists in v1.6-shipped MEM-* path
- [ ] v1.9+ follow-up: graceful-shutdown close-then-reuse discipline — project-wide `_closed: bool` guard pattern
- [ ] v1.9+ follow-up: AuditService pool `application_name=audit_service` for `pg_stat_activity` dashboard visibility

### Items Surfaced During v1.8 (routed to v1.9 candidates — see v1.8-MILESTONE-AUDIT.md tech debt block)

- [ ] **EVT-01 residual** — ~10 remaining event-loop singleton leak sites; `_SINGLETON_INVENTORY` to grow from 34 toward 48; enumeration needs PG host
- [ ] **MYPY-01 overflow** — 7 violations in `.planning/phases/30-test-infra-mypy-hardening/deferred-items.md`
- [ ] **`tests/integration/memory/test_save_facts_toctou.py:32, 57`** asyncpg + pgvector.asyncpg `import-untyped` silences
- [ ] **`services/nlu/nlu_service.py:538`** bare `# type: ignore` (pre-existing since v1.3/v1.6)
- [ ] **`tests/integration/conftest.py` autouse mock opt-out** — add `@pytest.mark.real_embedder` marker
- [ ] **7 pre-existing order-dependent unit-test failures** (registry-singleton pollution + `embed_one` vs `embed_batch` mock mismatch)
- [ ] **`test_pipeline_load_context_audit::test_no_v1_5_regression`** — `q=` vs `query=` GenerationRequest schema drift
- [ ] **`test_ui_static::test_ui_static_serves_html`** — `<title>` sentinel drift since v1.4
- [ ] **Nyquist VALIDATION.md missing for Phases 29 + 30** — `/gsd:validate-phase 29` and `/gsd:validate-phase 30` (optional process polish)
- [ ] **MILESTONES.md missing v1.7 entry** — v1.7-close oversight; backfill in v1.9

## Session Continuity

**Last updated:** 2026-05-17 — `/gsd-complete-milestone v1.8` complete. v1.8 Production Hardening Round 2 shipped. Phases 29 + 30 verified `passed` on docker rag-postgres pgvector/pgvector:pg16 host. Audit `passed` (7/7 reqs, 1 accepted override). All v1.8 artifacts archived to `.planning/milestones/v1.8-*.md`. Tag `v1.8.0` created.
**Stopped at:** Between milestones — v1.8 closed.
**Next action:** Run `/gsd-new-milestone` to scaffold v1.9 (questioning → research → requirements → roadmap). The tech-debt items above are pre-seeded candidates for v1.9 promotion.
