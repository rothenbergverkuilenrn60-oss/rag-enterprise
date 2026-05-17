---
phase: 28
plan: 1
subsystem: docs
tags: [doc-sweep, v1.7, readme, architecture, changelog, memory-eviction]
dependency_graph:
  requires: []
  provides: [README-v1.7-patches, ARCHITECTURE-v1.7-patches, memory-eviction-v1.7-deltas, CHANGELOG-v1.7-entry]
  affects: [28-04-archive]
tech_stack:
  added: []
  patterns: [keep-a-changelog, surgical-doc-patches, new-section-appended]
key_files:
  created: []
  modified:
    - README.md
    - ARCHITECTURE.md
    - docs/memory-eviction.md
    - CHANGELOG.md
decisions:
  - "docs/memory-eviction.md: new-section path chosen (no existing near-dup/cosine/save_facts content found via grep -n -E)"
  - "TD→SUMMARY mapping verified: TD-01→26-04, TD-02→27-01, TD-03→26-01, TD-04→27-03, TD-05→27-04, TD-06→27-02, TD-07→26-02"
  - "All CHANGELOG per-TD links use MILESTONES.md#v17 anchor (ENG-REVIEW D1 binding constraint enforced)"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-17"
  tasks_completed: 4
  files_modified: 4
---

# Phase 28 Plan 1: README + ARCHITECTURE + memory-eviction + CHANGELOG Summary

One-liner: Surgical doc refresh aligning README/ARCHITECTURE/memory-eviction/CHANGELOG to v1.7 Memory Tech-Debt Burn-Down (TD-01..TD-07, DOC-01).

## Tasks Completed

| Task | File | Commit |
|------|------|--------|
| 1 — README.md surgical patches | README.md | c4223fc |
| 2 — ARCHITECTURE.md §5.2.11 + §5.2.13 + §3.2 | ARCHITECTURE.md | 223ca4f |
| 3 — docs/memory-eviction.md partial refresh | docs/memory-eviction.md | b172d84 |
| 4 — CHANGELOG.md v1.7.0 entry | CHANGELOG.md | b41f7d9 |

## Exact Patches Applied

### README.md (c4223fc)

1. **Module layout (~line 107)** — `memory/` line: appended `(v1.7: save_facts batch + near-duplicate audit guard)` parenthetical.
2. **Project status (~line 289)** — Updated `**Current release:**` to v1.7 Memory Tech-Debt Burn-Down (Phases 26–28). Phase summaries now link to 26-05-SUMMARY.md and 27-04-SUMMARY.md. Prior milestones chain extended through v1.6.
3. **Local dev (~line 245-250)** — Replaced `conda activate torch_env` + `pip install -r requirements.txt` with `uv venv` + `uv sync` + `uv run uvicorn main:app --reload --port 8000`. Added `Detailed runbook: [docs/RUNBOOK.md](docs/RUNBOOK.md)` line.
4. **Configuration table (~line 286)** — Added `MEMORY_NEAR_DUPLICATE_THRESHOLD` row (cosine distance threshold, default 0.05, v1.7 audit-mode-only, SK-01 reference).

Preserved: agent-first framing, §Quick demo, §Architecture, §Tools, §Docker stack, qdrant line at ~202 (not v1.7-touched, left per CONTEXT Claude's-discretion default).

### ARCHITECTURE.md (223ca4f)

1. **§3.2 line 126** — `_persist_turn → memory_service + audit_service` got parenthetical: `（v1.7：memory_service 走批量 save_facts，audit_service pool 单例自启）`.
2. **§5.2.11 services/memory/** — Appended 3 rows after the existing `memory_service.py` row:
   - `LongTermMemory.save_facts` batch path (embed_batch + bulk dedupe SELECT + executemany; MEMORY_NEAR_DUPLICATE_SKIPPED audit mode; D-09/SK-01 forward ref)
   - `LongTermMemory._is_near_duplicate` cosine precheck
   - `LongTermMemory._get_pool / close` asyncpg_helper.prepare_dsn (TD-03)
3. **§5.2.13 services/audit/** — Appended 3 rows after the existing `audit_service.py` row:
   - `AuditService._create_tables` audit_log auto-create on cold start (INSERT-ONLY invariant, no manual DDL, TD-01)
   - `AuditService._get_pool / close` singleton asyncpg pool + asyncpg_helper (TD-03)
   - `AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED` new audit action enum (audit-mode)

Preserved: zh-CN tone, sections 1/2/4/5.1, all other §5.2.* sections, directory tree, heading count (47 `## ` matches, well above 5).

Note: Verify gate `grep -q 'audit_log 自动创建'` fails because the text reads `` `audit_log` 自动创建 `` (backtick-wrapped identifier). Content is semantically correct; the literal grep pattern does not match backtick-wrapped text.

### docs/memory-eviction.md (b172d84)

**Path chosen: new H2 section** — `grep -n -E "near.?dup|dedupe|cosine|batch|save_facts"` found only eviction CronJob `--batch-size` references (unrelated to the save_facts batch path). Near-dup/cosine terms not present. Appended-section path selected per plan instructions.

Added `## v1.7 deltas` at end of file with two subsections:
- `### Near-duplicate guard (audit-mode)` — MEMORY_NEAR_DUPLICATE_SKIPPED audit row emitted on hit; INSERT still runs; v1.8 SK-01/TOC-01 forward reference; link to 27-03-SUMMARY.md.
- `### Batch save path` — save_facts collapses N round-trips to 1× embed_batch + 1× executemany; p50 benchmark 25.31ms → 5.51ms; link to CHANGELOG + 27-04-SUMMARY.md.

Final length: 190 lines (within ≤ 220 gate). v1.6 CronJob YAML, cap-tuning, audit→enforce workflow, Forget API content untouched.

### CHANGELOG.md (b41f7d9)

Replaced `## [Unreleased]` heading block with `## [Unreleased]` + new `## [1.7.0] - 2026-05-17` entry.

**Structure:**
- Summary paragraph: Memory Tech-Debt Burn-Down, zero user-facing capabilities, pure refactor + reliability.
- `### Added` — 8 bullets in order: TD-01, TD-03, TD-07 (Phase 26), TD-02, TD-06, TD-04, TD-05 (Phase 27), DOC-01 (Phase 28).
- `### Changed` — 2 bullets: memory write path delegation; test conventions (uses_redis marker).
- `### Fixed` — 3 bullets: audit_log cold-start footgun; asyncpg ssl=disable consolidation; bge-m3 symlink removal.
- Audit-mode call-out blockquote: near-dup is audit-mode in v1.7; v1.8 SK-01/TOC-01 promotion; EVICT-02 precedent.

**ENG-REVIEW D1 compliance:** All per-TD bullets link to `MILESTONES.md#v17`. Zero direct links to `.planning/milestones/v1.7-phases/` paths. SK-01/TOC-01 in audit-mode call-out link to `.planning/REQUIREMENTS-v1.8.md` (stable single file).

**Compare-link footer:** Updated `[Unreleased]` to `v1.7.0...HEAD`; added `[1.7.0]: compare/v1.6.0...v1.7.0`; added `[1.6.0]: compare/v1.4.0...v1.6.0`. Pre-existing `[1.5.0]` gap untouched per CONTEXT out-of-scope row 6.

## TD→SUMMARY Mapping (verified pre-write)

| TD | Primary SUMMARY | Status |
|----|----------------|--------|
| TD-01 | 26-04-SUMMARY.md | ✓ confirmed |
| TD-02 | 27-01-SUMMARY.md | ✓ confirmed (27-00 + 27-01 both match; primary is 27-01 per plan) |
| TD-03 | 26-01-SUMMARY.md | ✓ confirmed |
| TD-04 | 27-03-SUMMARY.md | ✓ confirmed |
| TD-05 | 27-04-SUMMARY.md | ✓ confirmed |
| TD-06 | 27-02-SUMMARY.md | ✓ confirmed (27-00 + 27-02 both match; primary is 27-02 per plan) |
| TD-07 | 26-02-SUMMARY.md | ✓ confirmed |

## Deviations from Plan

### Auto-fixed Issues

None.

### Minor Deviations

**1. ARCHITECTURE.md verify gate `grep -q 'audit_log 自动创建'` — content present, literal pattern mismatch**
- **Found during:** Task 2 verification
- **Issue:** The written text reads `` `audit_log` 自动创建 `` (backtick-wrapped identifier in markdown table cell). The plan's verify gate uses `audit_log 自动创建` (no backticks), which does not match backtick-wrapped identifiers.
- **Decision:** Content is semantically correct and matches plan intent. Literal grep pattern is overly strict for backtick-wrapped markdown. No change to content; deviation documented here.
- **Impact:** Verify gate passes on all other checks (save_facts, _is_near_duplicate, asyncpg_helper, MEMORY_NEAR_DUPLICATE_SKIPPED, INSERT-ONLY, heading count). Substantive content fully correct.

## ROADMAP Success Criteria

- SC-1 (README + ARCHITECTURE refresh): README references v1.7 batch path + near-dup guard; ARCHITECTURE §5.2.11 + §5.2.13 updated; no stale manual audit_log DDL / per-module ssl=disable / bge-m3 symlink references. DONE.
- SC-2 (memory-eviction.md partial refresh): v1.7 near-dup audit-mode + batch path mentioned in new ## v1.7 deltas section; v1.6 content untouched. DONE.
- SC-3 (CHANGELOG v1.7 entry): Complete [1.7.0] entry with one item per TD-* + DOC-01 + audit-mode→SK-01/TOC-01 call-out + compare-link footer. DONE.

## Self-Check: PASSED

Files exist:
- README.md — modified ✓
- ARCHITECTURE.md — modified ✓
- docs/memory-eviction.md — modified ✓
- CHANGELOG.md — modified ✓

Commits exist:
- c4223fc docs(28-01): README.md surgical patches ✓
- 223ca4f docs(28-01): ARCHITECTURE.md patches ✓
- b172d84 docs(28-01): memory-eviction.md partial refresh ✓
- b41f7d9 docs(28-01): CHANGELOG.md v1.7.0 entry ✓
