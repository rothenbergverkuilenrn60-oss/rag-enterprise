---
phase: 28
plan: 3
plan_id: 28-03
subsystem: planning
tags: [requirements, scaffold, v1.8-backlog, doc-sweep]
dependency_graph:
  requires: []
  provides: [REQUIREMENTS-v1.8.md scaffold with 7 pre-seeded v1.8 backlog items]
  affects: [.planning/REQUIREMENTS-v1.8.md]
tech_stack:
  added: []
  patterns: [ID-prefixed category sections matching v1.7 REQUIREMENTS.md structure]
key_files:
  created:
    - .planning/REQUIREMENTS-v1.8.md
  modified: []
decisions:
  - "Accepted D-06 locked categorized ID schema: SK / TOC / OAI / EVT / MYPY / TEST-INFRA"
  - "7 pre-seeded items only — scaffold discipline; gsd-new-milestone expands on v1.8 open"
  - "Format mirrors v1.7 REQUIREMENTS.md for navigability by familiarity"
metrics:
  duration: "~5 minutes"
  completed: "2026-05-17"
  tasks_completed: 1
  files_created: 1
  files_modified: 0
---

# Phase 28 Plan 3: REQUIREMENTS-v1.8 Scaffold Summary

**One-liner:** v1.8 backlog scaffold with 6 ID-prefix categories + 7 fully-specified items (Owner / Blocker / When / Acceptance) seeded from v1.7 deferred work.

## Task Results

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Draft .planning/REQUIREMENTS-v1.8.md (7 pre-seeded items, 6 categories) | a774f96 | .planning/REQUIREMENTS-v1.8.md (created, 102 lines) |

## File Details

**`.planning/REQUIREMENTS-v1.8.md`** — 102 lines

- 6 category sections with H3 headings (matching v1.7 REQUIREMENTS.md section format)
- 7 checkbox items using `- [ ] **ID**:` format matching v1.7
- Each item has Owner / Blocker / When / Acceptance sub-bullets (2-space indent)
- Traceability table at end (matches v1.7 structure)
- Footer datestamp

## ID Schema Confirmation (D-06 locked)

All 7 IDs present and match locked schema:

| ID | Category | Blocker | When |
|----|----------|---------|------|
| SK-01 | Silent-skip enforcement | TOC-01 | v1.8 |
| TOC-01 | TOCTOU mitigation | None | v1.8 |
| OAI-01 | openai SDK drift cleanup | None | v1.8 |
| EVT-01 | Event-loop singleton leaks | None | v1.8 |
| MYPY-01 | mypy --strict cleanup | None | v1.8 |
| TEST-INFRA-01 | extractor_e2e embedder fixture | None | v1.8 |
| TEST-INFRA-02 | save_facts bulk-SELECT mock rewrite | None | v1.8 |

## Forward Reference Anchors

CHANGELOG (28-01), RUNBOOK (28-00), release-notes (28-02) cross-reference these IDs.
All anchors are navigable in `.planning/REQUIREMENTS-v1.8.md`:

- `SK-01` — line 22 (`### Silent-Skip Enforcement` section)
- `OAI-01` — line 43 (`### openai SDK Drift Cleanup` section)
- `EVT-01` — line 56 (`### Event-Loop Singleton Leaks` section)
- `TEST-INFRA-01` — line 76 (`### Test Infra Fixes` section)

## Verification Gate Results

All plan gates passed:

```
test -f .planning/REQUIREMENTS-v1.8.md           → PASS
grep **SK-01**, **TOC-01**, **OAI-01**, etc.       → PASS (all 7)
grep -E '^### Silent-Skip'                         → PASS
grep -E '^### TOCTOU'                              → PASS
grep -E '^### openai SDK'                          → PASS
grep -E '^### Event-Loop'                          → PASS
grep -E '^### mypy'                                → PASS
grep -E '^### Test Infra'                          → PASS
grep -E '^\| REQ-ID'                               → PASS (traceability table)
grep -c '^- \[ \] \*\*' == 7                      → PASS
line count: 102 (target 80–160)                    → PASS
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — this is a scaffold file by design. All 7 items have `Phase: TBD (v1.8)` in traceability; this is intentional and documented in the file header. Plan 28-04 (archive) will not change these — they remain TBD until v1.8 milestone opens.

## Threat Flags

None — no production code, endpoints, or auth paths touched.

## Self-Check: PASSED

- [x] `.planning/REQUIREMENTS-v1.8.md` exists (102 lines)
- [x] Commit a774f96 exists (`git log --oneline | grep a774f96`)
- [x] All 7 IDs present with correct `- [ ] **ID**:` format
- [x] 6 H3 category sections present
- [x] Traceability table present with all 7 rows
