---
phase: 28
phase_name: Doc Sweep + v1.7 Release
slug: doc-sweep-v1.7-release
created: 2026-05-17
status: context_gathered
requirements: [DOC-01]
---

# Phase 28 — Doc Sweep + v1.7 Release — CONTEXT

## Phase Domain

Documentation refresh aligning all in-repo docs to the post-v1.7 codebase (TD-01..TD-07) **and** v1.7 release artifacts (CHANGELOG entry, public release notes, tag ceremony, milestone archive). Zero production code changes. DOC-01 is the only requirement.

## Canonical refs

| Ref | Path |
|-----|------|
| Project core | `.planning/PROJECT.md` |
| Requirements | `.planning/REQUIREMENTS.md` (DOC-01 at line 41) |
| Roadmap | `.planning/ROADMAP.md` (Phase 28 §lines 45–55) |
| Current state | `.planning/STATE.md` |
| Phase 26 artifacts | `.planning/phases/26-memory-infra-hygiene/26-*-SUMMARY.md` (5 plans, audit_log auto-create + asyncpg_helper + bge-m3 resolver) |
| Phase 27 artifacts | `.planning/phases/27-test-isolation-memory-reliability/27-*-SUMMARY.md` + `27-VERIFICATION.md` + `27-02-DIAGNOSTIC.md` + `27-BENCHMARK.md` + `deferred-items.md` |
| Repo CHANGELOG | `CHANGELOG.md` (has [Unreleased] + [1.6.0]; pre-existing [1.5.0] gap is NOT in scope) |
| Repo README | `README.md` (~170 lines; Quick demo / Architecture / Tools / Platform features / Module layout / Testing & coverage / Observability / Quick start / Docker stack) |
| Repo ARCHITECTURE | `ARCHITECTURE.md` (repo root, 486 lines) |
| Repo docs/ | `docs/DOCKER_DEPLOY.md`, `docs/agent-architecture.md`, `docs/memory-eviction.md`, `docs/v1.4-design.md`, `docs/demo.cast` |
| v1.6 archive pattern | `.planning/milestones/v1.6-ROADMAP.md`, `.planning/milestones/v1.6-REQUIREMENTS.md`, `.planning/milestones/v1.6-phases/` |
| Codebase maps | `.planning/codebase/{ARCHITECTURE,CONCERNS,CONVENTIONS,INTEGRATIONS,STACK,STRUCTURE,TESTING}.md` |

## Carry-forward decisions (still in force)

| Decision | Source | Applies how |
|----------|--------|-------------|
| Audit-mode-before-enforce discipline | v1.6 Phase 25 EVICT-02 + v1.7 Phase 27 D-09 | CHANGELOG + release notes MUST call out: v1.7 ships near-dup as audit-mode-only (`MEMORY_NEAR_DUPLICATE_SKIPPED` audit row emitted, INSERT still runs); v1.8 will promote to silent-skip with TOCTOU mitigation. |
| Keep-a-changelog format | Existing `CHANGELOG.md` | v1.7 entry follows same shape as [1.6.0]: `### Added`, `### Changed`, `### Fixed`. |
| v1.6 archive pattern | v1.6 close-out | v1.7 archive reuses: snapshot ROADMAP/REQ → `.planning/milestones/v1.7-*.md`; move phase dirs → `.planning/milestones/v1.7-phases/`; ROADMAP `<details>` collapse on completed v1.7 section. |
| INSERT-ONLY audit_log invariant | v1.0 Phase 2 | Docs MUST NOT suggest UPDATE/DELETE on audit_log. |
| Mock-at-consumer-path pattern | v1.3 Phase 13+15 | RUNBOOK troubleshooting section references it for the `tests/integration/test_extractor_e2e.py` v1.8 fix. |
| diff-cover ≥ 80% on touched files | v1.1 Phase 10 | Even doc-only PRs respect this; if any executable script lands (release tag automation), it carries coverage. |

## Locked decisions (from this discuss session)

### D-01 — Dev runbook = new `docs/RUNBOOK.md` (full ops runbook)
- New file at `docs/RUNBOOK.md`. NOT a README section, NOT a DOCKER_DEPLOY expansion.
- Sets the pattern for v1.8+ milestone runbook updates (each milestone appends new ops procedures).
- Section scope (multi-select confirmed): **Local dev setup**, **Ops procedures**, **Troubleshooting**.
  - On-call playbook **deferred to v1.8** (no incident management infra yet — premature).

### D-02 — Local dev setup section content
- From-zero local environment: `uv venv`, `uv add`/`uv sync`, postgres docker bring-up, redis docker bring-up, `MODEL_DIR` env var, `.env` template, first `uv run pytest -m 'not benchmark'` invocation.
- Reference: existing README Quick demo + Docker stack sections; do NOT duplicate verbatim — link back and only fill gaps.

### D-03 — Ops procedures section content
- Verify `audit_log` auto-create on fresh PG (TD-01 / Phase 26)
- Run eviction job (v1.6 Phase 25 carry-over, link existing `docs/memory-eviction.md`)
- GDPR forget API usage (v1.6 Phase 25 T1 carry-over)
- bge-m3 model dir layout (TD-07 / Phase 26 — vanilla HF cache path; document the legacy `{MODEL_DIR}/embedding_models/bge-m3/` fallback)
- asyncpg URL `?ssl=disable` strip behaviour (TD-03 / Phase 26 — surface via `utils/asyncpg_helper.py`)

### D-04 — Troubleshooting section content
- Redis-ConnectionError on unit suite → apply `@pytest.mark.uses_redis` marker (TD-06 pattern from Phase 27)
- openai SDK signature drift (32 PR #9 unit failures) → **v1.8 backlog item OAI-01**; document workaround if any
- asyncpg URL `ssl=disable` literal misread → use `utils/asyncpg_helper.create_pool_from_dsn` (TD-03)
- +14 event-loop singleton leaks newly exposed by 27-02 marker rollout → **v1.8 backlog item EVT-01**; pattern from Phase 27 SC-1 (create_app factory) applies
- `tests/integration/test_extractor_e2e.py` FileNotFoundError on bge-m3 → **v1.8 backlog item TEST-INFRA-01**; ref `.planning/phases/27-test-isolation-memory-reliability/deferred-items.md`

### D-05 — v1.7 milestone archive folded INTO Phase 28 (one final plan owns it)
- Phase 28 final plan = `archive-v1.7-milestone` (after all doc plans verified). Sub-tasks (all 4 in scope per user multi-select):
  1. Snapshot `ROADMAP.md` → `.planning/milestones/v1.7-ROADMAP.md`; snapshot `REQUIREMENTS.md` → `.planning/milestones/v1.7-REQUIREMENTS.md`
  2. Move `.planning/phases/{26,27,28}-*` → `.planning/milestones/v1.7-phases/`
  3. Collapse ROADMAP v1.7 section into `<details>` block + update progress table (Phase 28 → Complete ✓)
  4. Append `MILESTONES.md` entry. **MILESTONES.md does NOT exist at repo root** — create it. **Claude's discretion: backfill v1.0–v1.7 entries** (one-time cost, future milestones inherit the file; matches v1.6 archive intent which referenced "MILESTONES.md entry appended" even though the file was never written).

### D-06 — `.planning/REQUIREMENTS-v1.8.md` scaffold = categorized IDs + full acceptance bullet (owner / blocker / when)
- File created in this phase (one plan owns it). Format matches v1.7 `REQUIREMENTS.md` structure: section per category, item per backlog entry, full acceptance bullet (owner placeholder TBD, blocker if any, target window).
- Categorized ID schema (locked):
  - **SK-** silent-skip enforcement (near-duplicate save promotion)
  - **TOC-** TOCTOU mitigation (close race window between SELECT precheck + INSERT)
  - **OAI-** openai SDK signature drift cleanup (32 PR #9 unit failures)
  - **EVT-** event-loop singleton leaks (+14 newly exposed by 27-02 marker rollout)
  - **MYPY-** mypy --strict cleanup (`config/settings.py:154` dict generic + any other accumulated pre-existing)
  - **TEST-INFRA-** test-infra fixes (extractor_e2e embedder fixture ordering; bulk-SELECT mock pattern + nearest_distance=None for save_facts precheck test rewrite)
- Pre-seeded items (CAN be expanded by gsd-new-milestone later):
  - **SK-01** silent-skip near-duplicate enforcement (save_fact + save_facts batch; depends on TOC-01)
  - **TOC-01** TOCTOU mitigation between precheck + INSERT
  - **OAI-01** openai SDK signature drift cleanup (32 PR #9 unit failures; APIError missing `request` arg)
  - **EVT-01** +14 event-loop singleton leaks fix (TD-02-style; uses create_app pattern from Phase 27 SC-1)
  - **MYPY-01** `config/settings.py:154 embedding_ensemble: list[dict] = []` → `list[dict[str, Any]]`
  - **TEST-INFRA-01** `tests/integration/test_extractor_e2e.py` embedder fixture ordering (FileNotFoundError on bge-m3)
  - **TEST-INFRA-02** save_facts precheck test rewrite (bulk SELECT mock pattern + nearest_distance=None handling; ~150 lines per file per 27 deferred-items.md)

### D-07 — Release notes = `docs/release-notes-v1.7.md` (public/ops-focused) **and** `.planning/milestones/v1.7-release-tag.md` (planning-internal tag ceremony)
- Split by audience. Both files created in this phase.
- `docs/release-notes-v1.7.md` format = **5-section template (locked)**:
  1. **Highlights** — 2-3 sentence summary (v1.7 is a refactor + reliability milestone; zero new user-facing capabilities; production-cleans the memory subsystem)
  2. **Shipped Items** — grouped by TD-ID (TD-01..TD-07), one bullet each, link to relevant SUMMARY.md
  3. **Ops Impact** — what changes in production: `audit_log` auto-creates on cold start; asyncpg `?ssl=disable` strip centralized; bge-m3 loads from vanilla HF cache; redis-mock fixture means unit suite no longer requires live Redis; near-dup save emits new audit metric (audit-mode-only, INSERT still runs)
  4. **Upgrade Notes** — none required (zero-prod-behavior change milestone). State this explicitly so ops doesn't waste time hunting.
  5. **Breaking Changes** — none. State this explicitly.
- `.planning/milestones/v1.7-release-tag.md` = annotated git tag command + body template + checklist (CHANGELOG updated? README updated? ARCHITECTURE updated? RUNBOOK created? release-notes-v1.7 written? milestone archived?).

## Claude's discretion (sensible defaults — flag in plan if these need revisit)

| Area | Default | Why |
|------|---------|-----|
| CHANGELOG v1.7 entry format | Strict keep-a-changelog (`### Added`, `### Changed`, `### Fixed`) with item-per-TD + final paragraph call-out: "Near-duplicate guard is **audit-mode** in v1.7 (`MEMORY_NEAR_DUPLICATE_SKIPPED` audit row; INSERT still runs). v1.8 will promote to silent-skip with TOCTOU mitigation. See [SK-01](.planning/REQUIREMENTS-v1.8.md)." | Matches existing CHANGELOG.md voice; per-TD granularity matches ROADMAP SC-3; audit-mode call-out preserves v1.6 EVICT-02 → v1.7 D-09 → v1.8 SK-01 traceability for future readers |
| README + ARCHITECTURE.md update depth | Surgical patches only — touch only paragraphs that mention v1.7-changed code (TD-01/03/07 paths). NO full structural review. | ARCHITECTURE.md is 486 lines; full review is scope creep. v1.7 is zero-prod-behavior so most structure is unchanged. |
| `docs/memory-eviction.md` update depth | Partial — only update sections that v1.7 touched (near-dup audit-mode discussion if mentioned; batch path mention if mentioned). NO full review. | Doc was last touched in v1.6; non-touched sections are not stale. |
| VERSION file introduction | **Do not introduce.** Continue git-tag-only. Add `pyproject.toml [project] version` if/when packaging is needed; out of scope for v1.7. | Adds a sync surface (VERSION ↔ git tag ↔ pyproject) without solving an actual problem in v1.7. Defer until packaging/distribution is requested. |
| MILESTONES.md backfill scope | Backfill v1.0 → v1.7 entries (one entry per milestone with: shipped date, phase range, requirements count, brief 1-2 sentence summary, link to `.planning/milestones/v{X}-ROADMAP.md`). | One-time cost (~7 entries); future milestone closes inherit a populated file. Avoids the v1.6 mistake (referenced MILESTONES.md but never created it). |
| RUNBOOK audience framing | Mixed (developer onboarding + ops day-2). Single file, sections clearly labelled. | Project is small enough that one file beats splitting; matches D-01 "full ops runbook" intent. |

## Out of scope (deferred / future)

- **On-call playbook** in RUNBOOK → v1.8+ (no incident management infra yet)
- **Code-acting / SQLTool** documentation → v1.8+ (still unresolved per PROJECT.md)
- **RLS on long_term_facts + asyncpg pool `app.current_tenant` production verification** → v1.8+ (per PROJECT.md carry-forward)
- **PyMuPDF AGPL license** resolution → v1.8+ (per v1.6 STATE carry-forward)
- **VERSION file introduction** → deferred until packaging requested
- **CHANGELOG [1.5.0] backfill** for pre-existing gap → not v1.7 scope
- Any new user-facing capability docs → wrong milestone
- v1.8 backlog items themselves (SK/TOC/OAI/EVT/MYPY/TEST-INFRA) → only the scaffold file ships in v1.7; implementation = v1.8 phases

## Phase 28 work shape (input for gsd-plan-phase)

Estimated 4–5 plans (planner to confirm):

1. **`28-00-runbook`** — create `docs/RUNBOOK.md` with 3 sections (Local dev, Ops procedures, Troubleshooting) per D-01..D-04
2. **`28-01-docs-refresh`** — surgical patches to `README.md`, `ARCHITECTURE.md` (repo root), `docs/memory-eviction.md` per Claude's-discretion defaults; CHANGELOG v1.7 entry per locked format
3. **`28-02-release-artifacts`** — create `docs/release-notes-v1.7.md` (5-section template per D-07) + `.planning/milestones/v1.7-release-tag.md` (annotated tag ceremony + checklist)
4. **`28-03-v1.8-scaffold`** — create `.planning/REQUIREMENTS-v1.8.md` (categorized IDs SK-/TOC-/OAI-/EVT-/MYPY-/TEST-INFRA- with full acceptance bullets per D-06)
5. **`28-04-archive`** — final plan: snapshot ROADMAP/REQ to `.planning/milestones/v1.7-*`; move phase 26/27/28 dirs to `.planning/milestones/v1.7-phases/`; collapse ROADMAP v1.7 section into `<details>`; create + backfill `MILESTONES.md` v1.0..v1.7 entries per D-05

Dependency graph:
- 28-00, 28-01, 28-02, 28-03 can run in parallel (disjoint file sets)
- 28-04 must run last (depends on all prior — it archives them)

## Notes for downstream agents

- **No production code changes.** Any plan that touches `services/`, `controllers/`, `utils/`, `config/`, `tests/` outside of doc-related comments is out of scope — flag and reject.
- **Verifier check:** every TD-01..TD-07 should be findable in CHANGELOG v1.7 + release-notes-v1.7 + RUNBOOK (where ops-relevant). Zero stale references to pre-v1.7 manual procedures (manual `audit_log` DDL, per-module `?ssl=disable` strip, bge-m3 symlink).
- **Archive plan timing:** plan 28-04 must run after 28-01/02/03 commit. STATE.md update at end of 28-04 marks v1.7 milestone complete and points to `/gsd-new-milestone` for v1.8 open.
