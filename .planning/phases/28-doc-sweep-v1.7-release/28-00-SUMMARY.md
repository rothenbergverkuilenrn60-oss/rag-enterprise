---
plan: 28-00
phase: 28
subsystem: docs
tags: [runbook, ops, local-dev, troubleshooting, doc-sweep]
dependency_graph:
  requires: []
  provides: [docs/RUNBOOK.md]
  affects: [docs/]
tech_stack:
  added: []
  patterns: []
key_files:
  created:
    - docs/RUNBOOK.md
  modified: []
decisions:
  - "Single mixed-audience file (dev onboarding + ops day-2) per CONTEXT D-01 defaults"
  - "On-call playbook deferred to v1.8 as specified in D-01"
  - "Near-duplicate guard documented as audit-mode-only (MEMORY_NEAR_DUPLICATE_SKIPPED audit row, INSERT still runs) per CONTEXT carry-forward row 1"
  - "INSERT-ONLY audit_log invariant preserved — no UPDATE/DELETE on audit_log anywhere in file"
  - "No symlink workaround documented — bge-m3 framed as vanilla HF cache (primary) + legacy directory (backwards-compat)"
metrics:
  duration_minutes: 5
  completed_date: "2026-05-17"
  task_count: 1
  file_count: 1
---

# Phase 28 Plan 00: RUNBOOK Summary

**One-liner:** New `docs/RUNBOOK.md` — three-section mixed-audience ops runbook seeding v1.7 deltas (TD-01 audit_log auto-create, TD-03 asyncpg URL handling, TD-07 bge-m3 HF cache layout, TD-06 redis-mock marker pattern).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Draft docs/RUNBOOK.md | eecc985 | docs/RUNBOOK.md |

## Artifact

**`docs/RUNBOOK.md`** — 323 lines.

### Ops procedures (5 subsections, H3)

1. **Verify audit_log auto-create on fresh PG (TD-01 / Phase 26)** — expected behavior, verification SQL, INSERT-ONLY invariant call-out, cite 26-04-SUMMARY.md.
2. **Run the eviction job (v1.6 Phase 25 carry-over)** — one-line summary + link to `docs/memory-eviction.md`.
3. **GDPR forget API (v1.6 Phase 25 carry-over)** — curl example + link to `docs/memory-eviction.md`.
4. **bge-m3 model dir layout (TD-07 / Phase 26)** — vanilla HF cache `{MODEL_DIR}/BAAI/bge-m3/` as primary, legacy path as backwards-compat. No symlink mention (gate verified). Cite 26-05-SUMMARY.md.
5. **asyncpg URL `?ssl=disable` handling (TD-03 / Phase 26)** — `utils/asyncpg_helper.prepare_dsn` usage, action required only for new modules. Cite 26-01-SUMMARY.md.

### Troubleshooting (5 subsections, H3)

1. **Redis-ConnectionError on unit suite** — `@pytest.mark.uses_redis` marker fix (TD-06). Reference 27-02-SUMMARY.md.
2. **openai SDK signature drift — 32 pre-existing unit failures** — symptom, diagnosis, workaround, tracked as **OAI-01** in `.planning/REQUIREMENTS-v1.8.md`.
3. **asyncpg DSN `ssl=disable` literal misread** — fix via `prepare_dsn` (TD-03).
4. **Event-loop singleton leaks after marker rollout (+14)** — `create_app()` factory workaround, tracked as **EVT-01** in `.planning/REQUIREMENTS-v1.8.md`.
5. **`test_extractor_e2e.py` FileNotFoundError on bge-m3** — three fix paths, tracked as **TEST-INFRA-01** in `.planning/REQUIREMENTS-v1.8.md`.

## Verification Gates

All automated gates from plan `<verify>` block passed:

```
test -f docs/RUNBOOK.md                                  OK
grep -c '^## ' docs/RUNBOOK.md | awk '$1 >= 3 ...'      OK (3 H2 sections)
## Local dev setup                                        OK
## Ops procedures                                         OK
## Troubleshooting                                        OK
audit_log                                                 OK
utils/asyncpg_helper                                      OK
BAAI/bge-m3                                              OK
MEMORY_NEAR_DUPLICATE_SKIPPED                            OK
uses_redis                                               OK
OAI-01                                                   OK
EVT-01                                                   OK
TEST-INFRA-01                                            OK
! grep UPDATE audit_log | DELETE FROM audit_log          OK (absent)
! grep -i symlink                                         OK (absent)
```

## Deviations from Plan

None — plan executed exactly as written.

Note: file length is 323 lines vs. 150–250 target range. The additional lines come from
substantive shell snippets (docker run, psql, curl, pytest) and diagnostic code blocks
in Troubleshooting — all content required by D-02/D-03/D-04. The `min_lines: 120`
hard gate is satisfied (323 > 120).

## Known Stubs

None. All sections are complete with real content; no forward stubs that prevent
the plan's goal.

## Threat Flags

None — docs-only plan. No new network endpoints, auth paths, or schema changes.

## Self-Check: PASSED

- [x] `docs/RUNBOOK.md` exists (verified `test -f docs/RUNBOOK.md`)
- [x] Commit `eecc985` exists (`git log --oneline` confirms)
- [x] All automated gates passed (output above)
- [x] Zero production code touched (`git diff --name-only HEAD~1 HEAD` = `docs/RUNBOOK.md` only)
