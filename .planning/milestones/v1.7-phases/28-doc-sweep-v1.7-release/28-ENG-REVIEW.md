# Phase 28 — Engineering Review

**Reviewer:** /plan-eng-review (Claude Opus 4.7)
**Date:** 2026-05-17
**Scope:** 28-00..28-04 PLAN.md set (5 plans, 2 waves, ~11 files modified)
**Verdict:** PASS — 3 issues found, all patched inline. Ready to execute.

---

## Completion Summary

| Section | Result |
|---------|--------|
| Step 0: Scope Challenge | **scope accepted as-is** (5 plans, < 8-files-per-plan threshold; bundled milestone-close justified per Boil the Lake) |
| Architecture Review | **3 issues found, all patched inline** (D1 MILESTONES.md anchor links, D2 source-extracted summaries, D3 link-integrity gate) |
| Code Quality Review | **0 issues** (plan structure verified by gsd-plan-checker; 4 prior plan-checker warnings already patched inline before this review) |
| Test Review | **0 traditional tests applicable** (doc phase); link-integrity = primary test, added in D3 |
| Performance Review | **N/A** (doc-only phase) |
| Outside Voice | **skipped** (doc-only phase; cross-AI structure already provided by plan-checker; caveman mode) |
| NOT in scope | written (8 items — see Out of Scope section in 28-CONTEXT.md) |
| What already exists | written (7 reused: CHANGELOG, README, ARCHITECTURE, memory-eviction.md, v1.6 archive pattern, codebase maps, Phase 27 ENG-REVIEW precedent) |
| TODOS.md updates | **0 new TODOs** (all forward-looking items routed to .planning/REQUIREMENTS-v1.8.md scaffold via D-06; nothing leaked) |
| Failure modes | **0 critical gaps** — pre-existing plan-checker patches already addressed: MILESTONES placeholder leak, STATE.md counter consistency, RUNBOOK symlink-word constraint, TD→SUMMARY mapping check |
| Parallelization | 2 waves; Wave 1 = 28-00/01/02/03 parallel (disjoint files); Wave 2 = 28-04 sequential (git mv) |
| Lake Score | 3/3 — all "complete option" recommendations chosen by user |

---

## Findings — Severity-Tagged

### Architecture (3 issues, all P2, all patched)

#### D1 — Pre/post-archive SUMMARY-link drift window in CHANGELOG + release-notes (P2, confidence: 9/10)

**Problem:**
28-01 (CHANGELOG) and 28-02 (release-notes) originally wrote per-Phase SUMMARY links pointing to `.planning/milestones/v1.7-phases/26-.../26-XX-SUMMARY.md` (post-archive paths). 28-04 (archive) `git mv`s the phase directories. Between Wave 1 commits and 28-04 commit (~10-min window during execution), the links 404. Worse: any future restructure of `.planning/milestones/` (e.g., v1.8 milestone close re-orgs) silently breaks v1.7's CHANGELOG + release-notes.

**Resolution (user picked Option C):**
CHANGELOG + release-notes link to `MILESTONES.md#v17` (stable anchor at repo root). MILESTONES.md gets per-milestone H3 anchor sections (`### v17`, `### v16`, …). MILESTONES.md is the only doc that contains per-Phase SUMMARY pointers — and it lives at repo root, decoupled from `.planning/` reorgs.

**Patches applied:**
- `28-01-PLAN.md` Task 4: ENG-REVIEW D1 binding constraint added; per-TD links use `MILESTONES.md#v17`; SUMMARY mapping check kept (used by 28-04). Verify gate adds `grep -q 'MILESTONES.md#v17'` and `! grep -qE '\.planning/milestones/v1\.7-phases/'`.
- `28-02-PLAN.md` Task 1: same D1 constraint; Shipped Items section drops per-Phase SUMMARY links; one approved exception for sibling `../docs/RUNBOOK.md`. Verify gate enforces.
- `28-04-PLAN.md` Task 4: MILESTONES.md structure rewritten — table + 8 H3 anchor sections (`### v10..v17`); `### v17` carries the per-Phase detail + SUMMARY pointers.

**Why this beats Option A (accept drift):** zero broken-link window during execution; survives v1.8+ archive reorgs.
**Why this beats Option B (sed rewrite):** no sed-regression risk; the link target is structural, not generated.

---

#### D2 — MILESTONES.md backfill summary quality (P2, confidence: 8/10)

**Problem:**
Original 28-04 Task 4 instructed planner-written prose summaries per milestone (v1.0..v1.6). Risk: summaries drift from the archived `.planning/milestones/v{X}-ROADMAP.md` source-of-truth docs (planner working from training data + memory, not the actual snapshots). Not deterministic on re-run.

**Resolution (user picked Option A):**
Summaries extracted via bash loop from each `.planning/milestones/v{X}-ROADMAP.md` `**Milestone goal:**` line. Requirement counts extracted via grep checkbox-pattern. Phase ranges + shipped dates extracted from `.planning/ROADMAP.md` top-of-file milestone marker. Output deterministic; re-runnable; traceable to source.

**Patches applied:**
- `28-04-PLAN.md` Task 4: 60-line rewrite. Step A = bash extraction loop; Step B = MILESTONES.md write template with `{GOAL}`, `{SHIPPED}`, `{PHASES}`, `{REQ_COUNT}` placeholders that the executor fills from Step A output. Fallback path documented (if `**Milestone goal:**` line missing in archive, use first paragraph of milestone overview).
- Verify gate strengthened: `! grep -q '{GOAL'`, `! grep -q '{SHIPPED'`, `! grep -q '{PHASES'`, `! grep -q '{REQ_COUNT'` + anchor presence checks (`^### v10`, `^### v17`).

**Why this beats Option B (planner prose):** auditable; survives team handoff; matches source-of-truth.
**Why this beats Option C (v1.7-only, lazy backfill later):** lazy work tends to never happen; one-time cost paid now sets the pattern.

---

#### D3 — Doc-link integrity test gap (P2, confidence: 9/10)

**Problem:**
Doc phase has no traditional test surface. Plan-checker pre-write SUMMARY-mapping grep loops (already patched into 28-01/02 from prior review pass) catch link errors AT WRITE TIME but don't catch:
- Anchor links that fail (e.g., `MILESTONES.md#v17` if the executor forgets to add the `### v17` section)
- Cross-file relative-path errors introduced during the archive `git mv`
- Drift from future doc edits (someone edits CHANGELOG later, breaks a link)

For a doc phase, **link integrity IS the test**. No gate caught broken links.

**Resolution (user picked Option A):**
Added Gate 7 to 28-04 — Python markdown-link-check that scans the full v1.7 doc surface (CHANGELOG, MILESTONES, README, ARCHITECTURE, RUNBOOK, release-notes, REQUIREMENTS-v1.8, v1.7 archive snapshots + every `*-SUMMARY.md` under `.planning/milestones/v1.7-phases/`). Resolves every relative link target; fails if any doesn't exist on disk. Skips http/https/mailto/anchor-only. Code-fence aware. No new dependency (uses Python stdlib).

**Patches applied:**
- `28-04-PLAN.md` Task 6 (sanity gates): Gate 7 added (40-line Python heredoc). `<done>` updated to reflect 7 gates.

**Why this beats Option B (lychee + CI):** zero new dep; out-of-scope CI workflow change avoided per CONTEXT; one-shot check at archive time catches the common case.
**Why this beats Option C (skip — trust existing gates):** existing gates don't cover anchor links, archive-time path errors, or post-write drift.

---

### Code Quality
No issues. Plan structure was already vetted by gsd-plan-checker (0 BLOCKER, 4 WARNING — all patched inline before this review).

### Test Review
**Coverage diagram (doc-phase variant):**

```
DOC SURFACE                                          VERIFY GATE
[+] docs/RUNBOOK.md (new, 3 sections)
  ├── Local dev setup                                ├── 28-00 grep gate (audit_log, asyncpg_helper, BAAI/bge-m3)
  ├── Ops procedures (5 subsections)                 ├── 28-00 grep gate (uses_redis marker rollout)
  └── Troubleshooting (5 subsections)                └── 28-00 word-constraint gate (symlink MUST NOT appear)

[+] CHANGELOG.md (Added/Changed/Fixed + call-out)    ├── 28-01 grep gate (all TD-IDs + INSERT-ONLY + audit-mode)
                                                     └── 28-01 grep gate (MILESTONES.md#v17 anchor, NO direct .planning/milestones/ paths)

[+] docs/release-notes-v1.7.md (5-section template)  ├── 28-02 grep gate (5 H2 sections + all TD-IDs + INSERT still runs)
                                                     └── 28-02 grep gate (MILESTONES.md#v17 anchor, NO direct .planning/milestones/ paths)

[+] .planning/REQUIREMENTS-v1.8.md (scaffold)        ├── 28-03 count gate (exactly 7 checkbox-bold-bullet items)
                                                     └── 28-03 6 category section presence (SK/TOC/OAI/EVT/MYPY/TEST-INFRA)

[+] MILESTONES.md (root, v1.0..v1.7)                 ├── 28-04 gate (8 v1.* rows + In Planning + ! <fill> + ! {GOAL/SHIPPED/PHASES/REQ_COUNT})
                                                     └── 28-04 anchor presence (### v10 + ### v17)

[~] README.md / ARCHITECTURE.md (surgical patches)   ├── 28-01 grep gate (v1.7-touched paths refreshed; legacy refs absent)
[~] docs/memory-eviction.md (partial)                └── 28-01 grep gate (save_facts / MEMORY_NEAR_DUPLICATE_SKIPPED present)

[+] Archive (git mv 26/27/28 → milestones/v1.7-phases/) ├── 28-04 Gate 1 (3 src dirs gone, 3 dst dirs present)
                                                        ├── 28-04 Gate 2 (8 milestone rows in MILESTONES.md)
                                                        ├── 28-04 Gate 3 (ROADMAP <details> count, link presence)
                                                        ├── 28-04 Gate 4 (snapshot files non-empty)
                                                        ├── 28-04 Gate 5 (STATE.md v1.7 shipped + counter consistency)
                                                        ├── 28-04 Gate 6 (no production-code diff)
                                                        └── 28-04 Gate 7 (link integrity — ENG-REVIEW D3)

COVERAGE: 11/11 doc surfaces gated   |   GAPS: 0   |   New gates this review: 1 (Gate 7)
QUALITY: ★★★ structural + content + link-integrity   |   E2E: N/A (doc phase)
```

**Legend:** ★★★ = content + structure + link-integrity gated. No `[GAP]` markers; D3 closes the only one.

**Test plan artifact:** N/A — doc phase has no QA flow.

### Performance
N/A — doc-only phase.

---

## What Already Exists (reused, not rebuilt)

| Asset | Source | How reused |
|-------|--------|-----------|
| `CHANGELOG.md` keep-a-changelog format | Existing repo (1.6.0 entry) | v1.7 entry follows same `### Added/Changed/Fixed` shape |
| `README.md` Quick-start / Docker-stack / Module layout / Testing sections | Existing | Surgical patches only — RUNBOOK links back, does not duplicate |
| `ARCHITECTURE.md` (repo root, 486 lines) | Existing | Surgical patches only — touch v1.7-changed paragraphs |
| `docs/memory-eviction.md` | v1.6 Phase 25 | Partial update: append save_facts/audit-mode section; preserve v1.6 cron + audit-then-enforce content |
| `.planning/milestones/v1.6-{ROADMAP,REQUIREMENTS}.md` + `v1.6-phases/` | v1.6 close | v1.7 archive replicates structure exactly |
| `.planning/codebase/{ARCHITECTURE,CONCERNS,CONVENTIONS,INTEGRATIONS,STACK,STRUCTURE,TESTING}.md` | Phase 25 map | RUNBOOK + ARCHITECTURE patches reference where relevant |
| Phase 27 `27-ENG-REVIEW.md` structure | Phase 27 review | This file replicates the structure for consistency |

---

## NOT in Scope (8 items deferred)

| Item | Why deferred | Tracked where |
|------|-------------|---------------|
| RUNBOOK on-call playbook section | No incident-management infra yet — premature | 28-CONTEXT.md D-01 / out-of-scope |
| Code-acting / SQLTool docs | Sandbox unresolved | v1.8+ (PROJECT.md carry-forward) |
| RLS production verification on long_term_facts | v1.6 carry-forward, separate work | v1.8+ (PROJECT.md) |
| PyMuPDF AGPL license resolution | v1.6 carry-forward, legal-not-tech | v1.8+ (PROJECT.md) |
| VERSION file introduction | Adds sync surface without solving real v1.7 problem | Deferred until packaging requested |
| CHANGELOG [1.5.0] backfill (pre-existing gap) | Not v1.7-introduced; orthogonal | Out of scope per CONTEXT |
| v1.8 backlog item implementations (SK/TOC/OAI/EVT/MYPY/TEST-INFRA) | Scaffold-only this phase; impl is v1.8 | `.planning/REQUIREMENTS-v1.8.md` (created in 28-03) |
| Lychee/CI markdown-link-check workflow | New dep + CI file out of scope for doc phase | Possible v1.8 if D3 in-phase check proves insufficient |

---

## Failure Modes — Critical Gap Check

| Codepath | Realistic failure | Test? | Handling? | Silent? |
|----------|-------------------|-------|-----------|---------|
| 28-04 `git mv` partial failure (e.g., disk full mid-move) | Some phase dirs moved, others stuck | Gate 1 (3 src absent + 3 dst present) — would catch | Yes — gate fails, executor investigates | No (gate output visible) |
| 28-04 MILESTONES.md `<fill>` placeholder leak | Executor skips Step A bash loop | Gate 2 + `! grep -q '{GOAL'` etc. | Yes — gate fails | No |
| 28-04 STATE.md frontmatter counter inconsistency (`total_plans:10` + `completed_plans:15`) | Executor misses one field | Gate 5 enforces `total_plans:\s*15` + `completed_plans:\s*15` + `percent:\s*100` | Yes — gate fails | No (gate output) |
| 28-00 RUNBOOK contains literal "symlink" leaked from action prose | Executor copies plan's parenthetical | Gate `! grep -i 'symlink'` + explicit author constraint in action body | Yes — gate fails | No |
| 28-04 broken doc link survives commit | Sed regression / future edit | Gate 7 (ENG-REVIEW D3) Python link-check | Yes — gate fails | No |
| Cross-plan TD→SUMMARY mapping mismatch (28-01 says 26-02 for TD-07, actual is 26-04) | Planner assumption drift | Pre-write grep loop in 28-01 + 28-02 (patched from prior plan-checker review) | Yes — executor logs mismatch + propagates | No |

**Critical gaps: 0.** All failure modes have a gate AND would be visible to the executor.

---

## Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|------|----------------|------------|
| 28-00 | `docs/` (RUNBOOK only) | — |
| 28-01 | `README.md`, `ARCHITECTURE.md`, `docs/memory-eviction.md`, `CHANGELOG.md` | — |
| 28-02 | `docs/release-notes-v1.7.md`, `.planning/milestones/v1.7-release-tag.md` | — |
| 28-03 | `.planning/REQUIREMENTS-v1.8.md` | — |
| 28-04 | `.planning/milestones/v1.7-*.md`, `.planning/milestones/v1.7-phases/` (git mv), `.planning/ROADMAP.md`, `MILESTONES.md`, `.planning/STATE.md` | 28-00, 28-01, 28-02, 28-03 (it moves the phase dir + needs MILESTONES.md content cross-refs from 28-01/02) |

**Parallel lanes:**
- **Wave 1:** 28-00 ∥ 28-01 ∥ 28-02 ∥ 28-03 — disjoint file sets, all 4 run parallel in separate worktrees.
- **Wave 2:** 28-04 alone — sequential. Must NOT run until Wave 1 commits exist + are merged.

**Conflict flags:** None. Confirmed disjoint at file level (not just module). 28-04 reads from Wave 1 outputs (MILESTONES.md anchor structure requires CHANGELOG/release-notes are in place); execution order enforces this.

---

## Implementation Tasks

```markdown
## Implementation Tasks
Synthesized from this review's findings. All 3 D-decisions already patched into the plan files inline. Tasks below = executor work, not review followups.

- [x] **T1 (P2, human: ~30min / CC: ~3min)** — 28-04 Task 4 — Rewrite MILESTONES.md backfill to source-extract summaries + add H3 anchor sections per ENG-REVIEW D1+D2
  - Surfaced by: Architecture D1 + D2
  - Files: `.planning/phases/28-doc-sweep-v1.7-release/28-04-PLAN.md`
  - Verify: PATCHED inline. Gate `! grep -q '{GOAL'` + anchor checks added.
- [x] **T2 (P2, human: ~15min / CC: ~2min)** — 28-04 add Gate 7 link-integrity Python check
  - Surfaced by: Test Review (D3)
  - Files: `.planning/phases/28-doc-sweep-v1.7-release/28-04-PLAN.md`
  - Verify: PATCHED inline. Gate 7 added; `<done>` updated to 7 gates.
- [x] **T3 (P2, human: ~10min / CC: ~2min)** — 28-01 Task 4 + 28-02 Task 1 anchor-link binding constraint
  - Surfaced by: Architecture D1
  - Files: `.planning/phases/28-doc-sweep-v1.7-release/28-01-PLAN.md`, `.planning/phases/28-doc-sweep-v1.7-release/28-02-PLAN.md`
  - Verify: PATCHED inline. Verify gates enforce `grep -q 'MILESTONES.md#v17'` and `! grep -qE '\.planning/milestones/v1\.7-phases/'`.
```

All review tasks patched into plan files. No follow-up work for the executor; D1/D2/D3 take effect on next `/gsd-execute-phase 28` run.

---

## Cognitive Patterns Applied

| Pattern | Where it fired |
|---------|----------------|
| **Boring by default** (Layer 1) | Link integrity check uses Python stdlib, not lychee dep; CHANGELOG keeps strict keep-a-changelog format. No innovation tokens spent. |
| **Blast radius instinct** | D1 question framed around the post-archive drift window — what breaks, who clicks broken links, how does v1.8 archive reuse propagate the issue. |
| **Systems over heroes** | Source-extracted MILESTONES.md summaries (D2) protect future close-out tasks from executor-drift / training-data-staleness — the doc is right because the bash loop reads from the source, not because the executor remembered correctly. |
| **Reversibility preference** | D1 anchor approach is fully reversible — if MILESTONES.md ever needs reshape, only one file changes. Per-Phase SUMMARY links would have required CHANGELOG + release-notes edits per change. |
| **Make the change easy, then make the easy change** | D3 link-integrity gate makes future doc edits safer for v1.8+ (the easy change). Closing the gap now is the refactor-first move. |
| **Essential vs accidental** | RUNBOOK on-call section deferred to v1.8 — solving a problem we don't have (no incident-mgmt infra). On-call docs without paging/escalation infra are accidental complexity. |

---

## Unresolved Decisions
None. All 3 D-questions answered; all patches applied inline.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 3 issues, 3 patched inline, 0 unresolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | N/A (doc phase, no UI) |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Outside Voice | `/codex consult` | Cross-model challenge | 0 | — | skipped (doc phase + cross-AI structure already via plan-checker) |

**UNRESOLVED:** 0 decisions
**VERDICT:** ENG CLEARED — ready to implement. Run `/gsd-execute-phase 28` when ready.
