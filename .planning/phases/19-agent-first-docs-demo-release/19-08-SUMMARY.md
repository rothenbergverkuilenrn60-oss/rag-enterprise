---
phase: 19-agent-first-docs-demo-release
plan: 08
subsystem: release-prep
tags: [agent-08, release-prep, tag-annotation, gh-release, runbook, autonomous-false, sc5]
requires:
  - .planning/phases/19-agent-first-docs-demo-release/19-CONTEXT.md (D-12, D-13, D-15)
  - CHANGELOG.md (plan 19-07)
  - docs/v1.4-design.md (plan 19-07)
  - .planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md
  - .planning/phases/17-tool-abstraction-retrievetool/17-03-SUMMARY.md
  - .planning/phases/18-sse-planner-trace-event-stream/18-03-SUMMARY.md
  - .planning/phases/19-agent-first-docs-demo-release/19-{01..07}-SUMMARY.md
provides:
  - .planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md (tag annotation + GitHub release prose)
  - .planning/phases/19-agent-first-docs-demo-release/release-tag-commands.md (7-step user-runnable runbook + rollback)
affects:
  - "ROADMAP SC5: v1.4 release tag-and-notes ready to cut from master after PR merge"
  - "v1.4 milestone closure: AGENT-08 fully drafted; user runs ceremony post-merge per D-12"
tech-stack:
  added: []
  patterns:
    - "tag-annotation-as-fenced-codeblock (Section A copy-paste-ready into git tag -a -m)"
    - "section-B-extracted-to-tmp-via-awk (release-tag-commands.md Step 5 separates ceremonial draft from gh-release-create payload)"
    - "<owner>/<repo>-placeholder + sed-substitution-step (T-19-08-02 mitigation; placeholder leaked-into-public-release threat)"
    - "human-in-the-loop tag-cut (D-12; autonomous: false; Claude drafts only)"
    - "demo embed form C — docs/demo.cast link + asciinema-play instruction (no .demo-cast-url file, no docs/demo.gif on host; matches plan 19-06 decision)"
key-files:
  created:
    - .planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md (177 lines)
    - .planning/phases/19-agent-first-docs-demo-release/release-tag-commands.md (141 lines)
  modified: []
decisions:
  - "Demo embed: form C (link to docs/demo.cast + asciinema-play instruction). Forms A (asciinema.org embed) and B (docs/demo.gif inline) ruled out — no .demo-cast-url file, no docs/demo.gif on host. Matches plan 19-06's decision (cast file is the single source of truth; user uploads to asciinema.org post-merge if desired and can patch the embed URL later)."
  - "Tag annotation kept verbatim from D-15 spec (1 headline + 4 phase bullets + 1 thesis paragraph = 6 content lines + 2 separator blank lines). No editorial rewrites."
  - "Release notes section A is canonical for the tag annotation; section B is canonical for the GitHub release body. release-tag-commands.md Step 3 extracts A via awk; Step 5 extracts B via awk to /tmp/v1.4.0-release-notes.md. Single source of truth lives in release-notes-v1.4.md."
  - "Rollback section provided (T-19-08-04 mitigation). v1.4.0 is permanent if Step 6 verification passes; the path is documented for safety."
  - "Plan is autonomous: false; Tasks 1+2 only DRAFTED the artifacts. NO git tag was cut. NO gh release was created. Task 3 (the human-action checkpoint) is the user's post-PR-merge work — Claude does NOT execute it (T-19-08-05 mitigation; D-12 contract)."
metrics:
  duration_minutes: 4
  tasks_completed: 2 (of 2 Claude-executable; Task 3 is human-action checkpoint)
  commits: 2
  files_created: 2
  files_modified: 0
  total_lines: 318 (release-notes 177 + release-tag-commands 141)
  completed_date: 2026-05-09
---

# Phase 19 Plan 08: v1.4 Release Ceremony Preparation — Summary

**One-liner:** Two draft artifacts shipped — `release-notes-v1.4.md` (Section A: copy-paste tag annotation per D-15; Section B: full GitHub release prose per D-13, ~177 lines) and `release-tag-commands.md` (7-step user-runnable runbook + rollback per D-12). Plan is `autonomous: false`: Claude DRAFTED only. The user runs the ceremony post-PR-merge. Closes ROADMAP SC5; v1.4 milestone (AGENT-08) is now ready to ship.

## Tasks Executed

| Task | Commit  | Files                                                                                          | Status |
| ---- | ------- | ---------------------------------------------------------------------------------------------- | ------ |
| T1   | `435cb2b` | `.planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md` (177 lines)           | All 13 acceptance gates passed (see below). |
| T2   | `3c44450` | `.planning/phases/19-agent-first-docs-demo-release/release-tag-commands.md` (141 lines)         | All 11 acceptance gates passed (see below). |
| T3   | n/a       | (human-action checkpoint — `autonomous: false`)                                                  | Pending: user runs the runbook after the v1.4 PR merges to `master`. |

## Files Created

### `.planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md` (177 lines)

Two sections separated by a horizontal rule:

- **Section A — Tag annotation** (`## Tag annotation`): a fenced code block with the verbatim 6-line headline copy-paste-ready into `git tag -a v1.4.0 -m "..."`. Shape: 1 headline (`v1.4.0 — Agent-first architecture inversion`) + 4 phase bullets (Phases 16/17/18/19 with their REQ-IDs) + 1 thesis paragraph (the architectural-inversion thesis). Per D-15.

- **Section B — GitHub release notes** (`## GitHub release notes`): full prose for `gh release create --notes-file`. ~150 prose lines. Structure: title + thesis paragraph; "What changed" with one subsection per phase (each closing the matching REQ-ID and linking the phase SUMMARY); Demo block (form C — `docs/demo.cast` link + `asciinema play` instruction); Carried forward from v1.3 (7-bullet capability list); Upgrade notes (3 paragraphs: endpoint surface / tool registration / SSE schema stability); Roadmap (next, 5-item v1.5+ deferred list); Acknowledgements (CHANGELOG + milestone-archive links); footer compare-link `v1.3.0...v1.4.0`. Per D-13.

### `.planning/phases/19-agent-first-docs-demo-release/release-tag-commands.md` (141 lines)

7-step runbook + rollback section. Each step has its own verification gate:

| Step | Action | Verification |
|------|--------|--------------|
| 1 | `sed` substitute `<owner>/<repo>` placeholder in `CHANGELOG.md` + `release-notes-v1.4.md`; commit + push | `grep -c "<owner>/<repo>"` returns 0 |
| 2 | `git checkout master && git pull --ff-only` | Confirm v1.4 PR merge commit is HEAD |
| 3 | `awk` extract Section A from release-notes-v1.4.md → `git tag -a v1.4.0 master -m "$TAG_MSG"` | `git tag -v v1.4.0 \| head -5` |
| 4 | `git push origin v1.4.0` | Visit `https://github.com/${REPO}/releases/tag/v1.4.0` |
| 5 | `awk` extract Section B → `/tmp/v1.4.0-release-notes.md`; `gh release create v1.4.0 --notes-file --verify-tag` | `head -10` + `wc -l` of the extract; verify tag attached |
| 6 | 6-item verification checklist on the published release | Title / body markdown / phase-summary links / cast link / compare-link |
| 7 | Edit STATE.md to `status: shipped`; commit + push | (state advancement) |
| Rollback | `git push --delete origin v1.4.0` + `git tag -d v1.4.0` + `gh release delete v1.4.0 --yes` | (used only if Step 6 reveals a problem) |

## Acceptance Gates Verification

### Task 1 — release-notes-v1.4.md (13/13 gates pass)

| Gate | Result |
|------|--------|
| File exists, 100-300 lines | 177 ✓ |
| `## Tag annotation` heading present | 1 ✓ |
| Headline matches `^v1\.4\.0 — Agent-first architecture inversion$` | 1 ✓ |
| Phase bullets `^Phase 1[6-9]: ` count ≥ 4 | 4 ✓ |
| `## GitHub release notes` heading present | 1 ✓ |
| All 4 phase SUMMARYs linked (16-03, 17-03, 18-03, 19-08) | 4 ✓ |
| `v1.4-design.md` link present | 1 ✓ |
| `CHANGELOG.md` link present | 1 ✓ |
| All 6 v1.4 REQ-IDs cited (AGENT-04, 06, 07, 08, 09, NLU-03) | 8 lines (6+ distinct) ✓ |
| Demo embed (≥1 of asciinema.org / docs/demo.gif / docs/demo.cast) | 1 (docs/demo.cast — form C) ✓ |
| Core architectural terms (Planner/Executor/Synthesizer/ToolPlan/RetrieveTool) cited ≥ 5 | 19 ✓ |
| Compare-link `compare/v1\.3\.0\.\.\.v1\.4\.0` present | 1 ✓ |
| No real credentials (sk-… / Bearer …) | 0 ✓ |

### Task 2 — release-tag-commands.md (11/11 gates pass)

| Gate | Result |
|------|--------|
| File exists, 50-150 lines | 141 ✓ |
| 7 numbered step headings (`^## Step [1-7] `) | 7 ✓ |
| `git tag -a v1.4.0 master` command present | 1 ✓ |
| `git push origin v1.4.0` command present | 1 ✓ |
| `gh release create v1.4.0` command present | 1 ✓ |
| `release-notes-v1.4.md` file referenced ≥ 3 times | 9 ✓ |
| `<owner>/<repo>` placeholder cited (substitution + examples) ≥ 2 | 6 ✓ |
| `## Rollback` section present | 1 ✓ |
| `gh release delete v1.4.0` rollback command present | 1 ✓ |
| `STATE.md` referenced ≥ 1 | 4 ✓ |
| No actual `v1.4.0` tag cut on the local repo | 0 ✓ |

### Plan-level key_links pattern checks

| Pattern | Source | Target | Result |
|---------|--------|--------|--------|
| `(v1.4-design\|CHANGELOG\|16-03-SUMMARY\|17-03-SUMMARY\|18-03-SUMMARY\|19-08-SUMMARY)\.md` | release-notes-v1.4.md | docs/v1.4-design.md + CHANGELOG.md + 4 phase SUMMARYs | All 6 distinct targets matched ✓ |
| `--notes-file.*release-notes-v1\.4\.md` | release-tag-commands.md | release-notes-v1.4.md (via gh release create flow) | 1 line matches (Step 5 explanatory line) ✓ |

## Threat Model Verification

| Threat ID | Disposition | Mitigation Verification |
|-----------|-------------|-------------------------|
| T-19-08-01 (Tampering — non-master tag cut) | mitigate | Runbook Step 2 explicitly checks `git log --oneline -5` and STOPs if HEAD ≠ v1.4 PR merge commit; Step 3 uses `git tag -a v1.4.0 master` (explicit `master` ref). ✓ |
| T-19-08-02 (Information Disclosure — `<owner>/<repo>` placeholder leak) | mitigate | Step 1 substitutes via `sed -i` on both CHANGELOG.md and release-notes-v1.4.md; verification grep gate `grep -c "<owner>/<repo>"` must return 0 before Step 2. ✓ |
| T-19-08-03 (Tampering — release-notes drift between Step 3 and Step 5) | accept | Documented risk; mitigation guidance is "run Steps 3-5 in one sitting." Drift is observable (release body would diverge from tag message). ✓ |
| T-19-08-04 (DoS — gh release create network/auth failure) | mitigate | `--verify-tag` flag added to `gh release create`; Rollback section provides delete commands if release publishes broken. ✓ |
| T-19-08-05 (EoP — Claude executing the release autonomously) | mitigate | Plan is `autonomous: false`. Tasks 1+2 DRAFTED only. NO `git tag`, NO `git push`, NO `gh release create` invoked by Claude. Task 3 is `checkpoint:human-action`. ✓ Verified: `git tag -l \| grep -c '^v1\.4\.0$'` returns 0. |
| T-19-08-06 (Tampering — forward-link `19-08-SUMMARY.md` not yet existing) | mitigate | This SUMMARY file is being created at plan completion (per `<output>` spec). It will exist before the user runs Step 3 of the runbook (Section B of release-notes-v1.4.md cross-links 19-08-SUMMARY.md at the v1.4.0 tag). ✓ |

## Deviations from Plan

### Auto-fixed Issues

**None — Tasks 1 and 2 executed verbatim from the plan's `<action>` blocks.**

The plan provided a single editorial choice in Task 1: pick exactly ONE of three demo-embed forms and delete the other two. Discovery during `<read_first>`:

- `.planning/phases/19-agent-first-docs-demo-release/.demo-cast-url` — does NOT exist
- `docs/demo.gif` — does NOT exist
- `docs/demo.cast` — exists (5,526 bytes; produced by plan 19-05)

Form C (link to `docs/demo.cast` + `asciinema play` instruction) was the only valid choice. This is editorial selection, not deviation — the plan explicitly enumerated the three forms with conditional `[If ...]` markers and required the executor to pick one.

### Auth gates / Architectural questions (Rule 4)

None.

### Carry-forward note

**Task 3 is intentionally NOT executed.** The plan is `autonomous: false`; per CONTEXT.md D-12, the release ceremony (cutting the tag, pushing it, publishing the GitHub release) is a human-in-the-loop gate because v1.4.0 is permanent and the cutter wants to review the merged code one more time before tagging. This is not a deviation — it is the plan's design.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. Both new files are markdown drafts under `.planning/phases/19-agent-first-docs-demo-release/`.

## Known Stubs

None. `<owner>/<repo>` placeholders in both files are intentional (T-19-08-02 mitigation contract: the user substitutes at Step 1 of the runbook and the substitution is verified by a `grep -c "<owner>/<repo>"` gate that must return 0 before tagging proceeds). These are not regressive stubs — they are explicit handoff parameters.

## Self-Check: PASSED

- File `.planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md` exists ✓ (177 lines)
- File `.planning/phases/19-agent-first-docs-demo-release/release-tag-commands.md` exists ✓ (141 lines)
- File `.planning/phases/19-agent-first-docs-demo-release/19-08-SUMMARY.md` exists ✓ (this file)
- Commit `435cb2b` exists in `git log` ✓ (`docs(19-08-T1): draft v1.4 release notes ...`)
- Commit `3c44450` exists in `git log` ✓ (`docs(19-08-T2): draft v1.4 release-tag commands runbook`)
- Branch is `gsd/v1.3-milestone` (sticky) ✓
- All 13 Task-1 acceptance gates pass ✓
- All 11 Task-2 acceptance gates pass ✓
- Plan-level key_links patterns satisfied ✓
- NO actual `v1.4.0` tag cut on the local repo ✓ (`git tag -l` returns only `v1.0`, `v1.1`, `v1.2`, `v1.3`)
- NO actual GitHub release published (tag absent → release cannot exist) ✓
