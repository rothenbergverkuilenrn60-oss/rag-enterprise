---
phase: 28
plan: "02"
subsystem: docs
tags: [release-notes, tag-ceremony, doc-sweep, v1.7]
dependency_graph:
  requires: []
  provides:
    - docs/release-notes-v1.7.md
    - .planning/milestones/v1.7-release-tag.md
  affects:
    - ROADMAP SC-4
    - DOC-01
tech_stack:
  added: []
  patterns:
    - 5-section release notes template (D-07)
    - MILESTONES.md#v17 anchor links (ENG-REVIEW D1)
    - audit-mode-before-enforce wording discipline (v1.6 EVICT-02 → v1.7 D-09)
key_files:
  created:
    - docs/release-notes-v1.7.md
    - .planning/milestones/v1.7-release-tag.md
  modified: []
decisions:
  - "MILESTONES.md#v17 anchor links used in Shipped Items (not per-Phase SUMMARY paths) per ENG-REVIEW D1 binding constraint — survives .planning/ archive reorganization"
  - "Tag annotation constructed inline in v1.7-release-tag.md (no awk extraction) — small enough to embed directly, more readable than extraction script"
  - "Canonical repo URL rothenbergverkuilenrn60-oss/rag-enterprise embedded directly (no <owner>/<repo> placeholder) — already known, reduces release-cutter steps"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-17"
  tasks: 2
  files_created: 2
  files_modified: 0
---

# Phase 28 Plan 02: Release Artifacts (Release Notes + Tag Ceremony) Summary

**One-liner:** v1.7 public release notes (5-section D-07 template) + planning-internal annotated tag ceremony with 12-item pre-tag checklist.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Draft docs/release-notes-v1.7.md | `00e7dc6` | docs/release-notes-v1.7.md (151 lines) |
| 2 | Draft .planning/milestones/v1.7-release-tag.md | `c38f8e3` | .planning/milestones/v1.7-release-tag.md (145 lines) |

## File Details

### docs/release-notes-v1.7.md (151 lines)

Public/ops-focused. Audience: operators + developers upgrading.

5 sections as required by D-07:
1. **Highlights** — 3-sentence refactor milestone summary
2. **Shipped Items** — grouped by phase/TD (TD-01..TD-07 + DOC-01); anchor to `MILESTONES.md#v17`
3. **Ops Impact** — 5 operational changes with actionable procedures
4. **Upgrade Notes** — explicit "None required" with optional fakeredis CI note
5. **Breaking Changes** — explicit "None" with public API endpoint table + `save_fact` signature note

Key constraint compliance:
- `MILESTONES.md#v17` used for per-Phase navigation (ENG-REVIEW D1)
- Zero direct `.planning/milestones/v1.7-phases/` links (D1 violation check passes)
- "the INSERT still runs" exact phrase for audit-mode (mirrors 27-VERIFICATION.md SC-3)
- SK-01 / TOC-01 forward refs to `.planning/REQUIREMENTS-v1.8.md`
- `v1.6.0...v1.7.0` compare-link in footer

### .planning/milestones/v1.7-release-tag.md (145 lines)

Planning-internal. Audience: release-cutter running locally after milestone PR merges.

Structure mirrors v1.4 `release-tag-commands.md` but uses v1.7 specifics:
- **Pre-tag checklist** (12 items): CHANGELOG entry, README v1.7, ARCHITECTURE patches, RUNBOOK, release-notes, REQUIREMENTS-v1.8 scaffold, phase archive dirs, ROADMAP/REQ snapshots, MILESTONES.md entry, gh auth, master up-to-date
- **Step 1** — Verify HEAD is merge commit
- **Step 2** — Construct tag annotation (inline, no awk extraction)
- **Step 3** — `git tag -a v1.7.0` + `git push origin v1.7.0`
- **Step 4** — `gh release create v1.7.0 --notes-file docs/release-notes-v1.7.md --verify-tag`
- **Step 5** — Post-publish verification checklist
- **Step 6** — Update STATE.md to shipped
- **Rollback** — delete remote tag + local tag + `gh release delete`

## SUMMARY-Link Path Strategy

Per ENG-REVIEW D1 constraint, `docs/release-notes-v1.7.md` does NOT link directly to
`.planning/milestones/v1.7-phases/` SUMMARY.md files. Instead it links to
`MILESTONES.md#v17` (repo-root stable anchor). The `### v17` section in MILESTONES.md
(created by 28-04 Task 4) holds all per-Phase SUMMARY pointers and survives future
`.planning/` archive reorganizations.

Post-archive paths confirmed (for 28-04 Task 4 MILESTONES.md assembly):
- TD-01 primary SUMMARY → `26-memory-infra-hygiene/26-04-SUMMARY.md` (under v1.7-phases/)
- TD-02 primary SUMMARY → `27-test-isolation-memory-reliability/27-01-SUMMARY.md`
- TD-03 primary SUMMARY → `26-memory-infra-hygiene/26-01-SUMMARY.md`
- TD-04 primary SUMMARY → `27-test-isolation-memory-reliability/27-03-SUMMARY.md`
- TD-05 primary SUMMARY → `27-test-isolation-memory-reliability/27-04-SUMMARY.md`
- TD-06 primary SUMMARY → `27-test-isolation-memory-reliability/27-02-SUMMARY.md`
- TD-07 primary SUMMARY → `26-memory-infra-hygiene/26-02-SUMMARY.md`

(Verified via grep across `.planning/phases/26-*/` and `.planning/phases/27-*/` SUMMARY.md files.)

## Deviations from Plan

None — both files executed exactly as specified in the PLAN.md task actions.

## Known Stubs

None. Both files are complete planning/documentation artifacts with no placeholder text
or deferred content.

## Threat Flags

None. No network endpoints, auth paths, file access patterns, or schema changes introduced.
Both files are pure Markdown documentation.

## Self-Check: PASSED

- `docs/release-notes-v1.7.md` exists: FOUND
- `.planning/milestones/v1.7-release-tag.md` exists: FOUND
- Commit `00e7dc6` exists: FOUND
- Commit `c38f8e3` exists: FOUND
- All 5 H2 sections present in release-notes: PASSED
- All TD-01..TD-07 + DOC-01 in release-notes: PASSED
- "INSERT still runs" phrase present: PASSED
- SK-01 forward ref present: PASSED
- MILESTONES.md#v17 anchor link present: PASSED
- No .planning/milestones/v1.7-phases/ links in release-notes: PASSED
- git tag -a v1.7.0 in tag ceremony: PASSED
- gh release create v1.7.0 in tag ceremony: PASSED
- Rollback section in tag ceremony: PASSED
- CHANGELOG, RUNBOOK, MILESTONES.md refs in tag ceremony: PASSED
