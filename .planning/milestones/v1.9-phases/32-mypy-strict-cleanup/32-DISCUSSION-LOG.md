# Phase 32: mypy `--strict` Cleanup - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-18
**Phase:** 32-mypy-strict-cleanup
**Areas discussed:** Silence cap scope, Audit scope expansion (MYPY-03 + MYPY-04), asyncpg stub policy, Structural duplicate-module fix

---

## Silence cap scope (must_have #4 reconciliation)

| Option | Description | Selected |
|--------|-------------|----------|
| Bounded scope cap=25 + tests/ separately audited (Recommended) | Lock cap to `services/+config/+utils/+controllers/+scripts/`; tests/ tracked but uncapped. Matches Phase 30-03 reality. | ✓ |
| Full-repo cap=25 (plan-as-written) | Stick to ROADMAP literal; requires ~200 LOC of tests/ type annotation work to get from 141 to 25. | |
| Re-baseline cap to current full-repo count | Accept 141 as ceiling; loses Phase 30-03 discipline signal. | |

**User's choice:** Bounded scope cap=25 + tests/ separately audited.
**Notes:** Aligns with audit-mode-before-enforce carry-forward. ROADMAP literal "full-repo ≤25" was a planning-doc artifact, not a Phase 30 enforcement reality.

---

## Audit scope expansion (MYPY-03 + MYPY-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Fix all surfaced sites (Recommended) | Expand MYPY-03 to 4 bare ignores (1 named + 3 audit-surfaced) and MYPY-04 to 4 asyncpg sites (2 named + 2 audit-surfaced). Audit treated as enforcement. | ✓ |
| Fix only named scope; capture rest as deferred surplus | Stick to ROADMAP scope; add audit findings to deferred-items.md for v1.10. Breaks "convention auditable via grep" promise. | |
| Fix named + bare ignores; defer untyped-import expansion | Compromise; couples MYPY-04 expansion to stub-install decision in Area 3. | |

**User's choice:** Fix all surfaced sites.
**Notes:** Matches goal #4 ("convention auditable via grep") and audit-mode-before-enforce. CONTEXT.md D-AUDIT-02 + D-AUDIT-03 enumerate the expanded scope concretely.

---

## asyncpg stub policy (MYPY-02 + MYPY-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Install upstream stubs where available; silence the rest (Recommended) | `uv add --dev asyncpg-stubs`, `pandas-stubs`. Silence pgvector.asyncpg, rank_bm25, datasets with `# why:` per site. Highest fix/silence ratio. | ✓ |
| Silence everything with why-comments | No new deps; ~5+ silences added against cap. Loses asyncpg type-checking benefit. | |
| Local `stubs/` package for asyncpg + pgvector.asyncpg | Hand-rolled minimal stubs; tight local control; excessive for hardening phase. | |

**User's choice:** Install upstream stubs where available; silence the rest.
**Notes:** Planner verifies on PyPI that `asyncpg-stubs` + `pandas-stubs` are currently maintained (≤12-month release) before committing — fallback to silence if stale.

---

## Structural duplicate-module fix (`scripts/evict_long_term_facts.py`)

| Option | Description | Selected |
|--------|-------------|----------|
| Add `--explicit-package-bases` to mypy config (Recommended) | Edit `[tool.mypy]` in pyproject.toml; config-only; zero blast radius outside type-checking. | ✓ |
| Add `scripts/__init__.py` | Project-structural; may affect entry-point invocation patterns; requires audit of test imports from `scripts.*`. | |
| Silence with `# type: ignore[duplicate-module]  # why:` | Lowest effort; adds 1 silence to the cap; skips structural cleanup. | |

**User's choice:** Add `--explicit-package-bases` to mypy config.
**Notes:** D-STRUCT-01 captures the edit; D-STRUCT-02 rules out the package conversion.

---

## Claude's Discretion

- Specific silence-comment wording — `why:` clause phrasing per site.
- Order of execution within plan (fix deferred → bare ignores → untyped imports, OR interleave per file).
- Single plan (32-00) vs split (stub install + structural fix as 32-00, audit-expanded sweep as 32-01) — planner picks based on Wave / parallelism analysis.

## Deferred Ideas

- **Drive tests/ silence count toward 0** — ~200 LOC of test-fixture annotation work; belongs in a future test-infra polish phase.
- **Hand-roll local `stubs/`** — rejected for v1.9; reconsider if pgvector.asyncpg / rank_bm25 / datasets grows past 10 call-sites or surfaces real production bugs.
- **`scripts/` → real Python package** — rejected per D-STRUCT-02; reconsider if entry-point patterns change for other reasons.
