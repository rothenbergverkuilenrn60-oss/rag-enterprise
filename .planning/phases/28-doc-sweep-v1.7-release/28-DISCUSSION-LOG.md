# Phase 28 — Discussion Log

**Session:** 2026-05-17  
**Mode:** default (single-question turns, batched per-area)  
**Output:** `28-CONTEXT.md`

This log captures the AskUserQuestion turns verbatim for audit purposes. It is NOT consumed by downstream agents — `28-CONTEXT.md` is the canonical handoff.

---

## Turn 1 — Gray area selection (multiSelect)

**Question:** Which gray areas should we discuss for Phase 28? (top 4 plan-shaping decisions; remaining items defer to sensible defaults unless you flag them)

**Options presented:**
1. Dev runbook decision
2. v1.7 milestone archive in scope
3. v1.8 deferred-items handling
4. Release-notes + tag-commands location/audience

**User selected (all 4):** Dev runbook decision, v1.7 milestone archive in scope, v1.8 deferred-items handling, Release-notes + tag-commands location/audience

**Implicit acceptance of Claude's-discretion defaults** for the 4 NOT selected areas (presented in initial scout but trimmed to fit AskUserQuestion's 4-option cap):
- CHANGELOG v1.7 entry scope
- README + ARCHITECTURE.md update depth
- memory-eviction.md update depth
- VERSION file introduction

---

## Turn 2 — 4 primary area decisions (batched)

### Q2.1 Dev runbook interpretation

**Options:**
- Interpret as README only (skip new file)
- New `docs/RUNBOOK.md` (full ops runbook)
- Expand `docs/DOCKER_DEPLOY.md` into runbook
- Both: README refresh + new `docs/RUNBOOK.md`

**User selected:** New `docs/RUNBOOK.md` (full ops runbook) → **D-01**

### Q2.2 v1.7 milestone archive fold/split

**Options:**
- Fold archive INTO Phase 28 (one plan owns it)
- Separate post-merge step (v1.6-style)
- Fold into Phase 28 but as optional final plan

**User selected:** Fold archive INTO Phase 28 (one plan owns it) → **D-05**

### Q2.3 v1.8 deferred-items handling

**Options:**
- CHANGELOG call-out only
- Draft `.planning/REQUIREMENTS-v1.8.md` scaffold now
- Consolidated `docs/v1.8-preview.md`
- Append to existing BACKLOG/TODOS

**User selected:** Draft `.planning/REQUIREMENTS-v1.8.md` scaffold now → **D-06**

### Q2.4 Release-notes + tag-commands location/audience

**Options:**
- `docs/release-notes-v1.7.md` (public/ops-focused)
- `.planning/milestones/v1.7-release-notes.md` (planning-internal)
- Both: `docs/release-notes-v1.7.md` + `.planning/milestones/v1.7-release-tag.md`
- GitHub Release body only (no in-repo file)

**User selected:** Both split by audience → **D-07**

---

## Turn 3 — Detail follow-ups (batched)

### Q3.1 docs/RUNBOOK.md sections (multiSelect)

**Options:** Local dev / Ops procedures / Troubleshooting / On-call playbook

**User selected:** Local dev, Ops procedures, Troubleshooting → On-call playbook **deferred to v1.8** (locked in D-01 / D-02..D-04 detail)

### Q3.2 v1.7 archive plan scope (multiSelect)

**Options:** Snapshot ROADMAP/REQ / Move phase dirs / Collapse ROADMAP <details> / Append MILESTONES.md (create if missing)

**User selected:** All 4 → locked in D-05; Claude's discretion on MILESTONES.md backfill scope (v1.0–v1.7 backfill) recorded in CONTEXT under Claude's-discretion table.

### Q3.3 REQUIREMENTS-v1.8.md item ID scheme + detail level

**Options:**
- Categorized IDs (SK-/TOC-/OAI-/EVT-) + minimal one-liner each
- Sequential TD- prefix continuation
- Categorized IDs + full acceptance bullet (owner, blocker, when)
- Free-form narrative grouped by source-phase

**User selected:** Categorized IDs + full acceptance bullet → **D-06** (extended schema includes MYPY- and TEST-INFRA- categories per Claude's accumulated v1.8 follow-up sweep)

### Q3.4 docs/release-notes-v1.7.md audience + format

**Options:**
- Mixed audience, 5-section template (Highlights / Shipped Items / Ops Impact / Upgrade Notes / Breaking Changes)
- Ops/SRE-focused only
- Developer-focused only
- Narrative paragraph + bullets

**User selected:** Mixed audience, 5-section template → **D-07** (exact template structure locked in CONTEXT)

---

## Deferred ideas (captured during discussion)

| Idea | Source | When |
|------|--------|------|
| RUNBOOK on-call playbook section | Q3.1 trim | v1.8+ (no incident-management infra yet) |
| MILESTONES.md backfill scope > v1.7 | Q3.2 elaboration | One-time cost in v1.7 — folded into Claude's-discretion defaults |
| v1.8 backlog items (SK/TOC/OAI/EVT/MYPY/TEST-INFRA) implementation | D-06 scaffold | v1.8 phases — scaffold only ships in v1.7 |
| Code-acting / SQLTool docs | PROJECT.md carry-forward | v1.8+ (sandbox unresolved) |
| RLS production verification on long_term_facts | PROJECT.md carry-forward | v1.8+ |
| PyMuPDF AGPL license resolution | PROJECT.md carry-forward | v1.8+ |
| VERSION file introduction | Claude's discretion (Q1 trim) | Deferred until packaging requested |
| CHANGELOG [1.5.0] backfill | Pre-existing gap | Not v1.7 scope |

---

## Scope creep redirects

None this session. User stayed inside the doc-sweep + release-artifacts boundary throughout.
