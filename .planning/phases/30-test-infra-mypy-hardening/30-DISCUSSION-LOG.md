# Phase 30 — Discussion Log

**Phase:** 30 — Test Infra + mypy Hardening
**Date:** 2026-05-17
**Mode:** default (no flags)
**Skill:** /gsd-discuss-phase

For human reference only. NOT consumed by downstream agents (researcher, planner, executor) — `30-CONTEXT.md` is the canonical decision record.

---

## Pre-Discussion Gate

**Carry-forward decisions reviewed (from v1.7 + Phase 29):**
- Strict TDD per project standard (RED→GREEN→REFACTOR)
- Mock at consumer path `services.<mod>.<dep>` (v1.3 D-mock)
- `create_app()` factory pattern + `_SINGLETON_INVENTORY` (Phase 27 TD-02)
- diff-cover ≥ 80%; --fail-under=70 global floor
- No bare `except`; mypy --strict + ruff clean
- INSERT-ONLY `audit_log` invariant
- `_bulk_near_duplicate_check_raw` is the new save_facts helper (Phase 29 A1-A)

**Phase 30 domain:** Test surface + type-check hardening. Zero user-facing capability change.

---

## Round 0 — Area Selection

### Q0: Which gray areas to discuss?

**Options:** OAI-01 fix shape / EVT-01 approach / TEST-INFRA-01 fix path / MYPY-01 scope.

**Selection:** All 4.

**Notes:** Surgical hardening phase; each requirement has 2-3 candidate paths in REQUIREMENTS.md. User wanted to lock all of them in CONTEXT.md.

### Q0b: Plan structure preview?

**Options:** 4 plans (1/req) / 2 plans (bundles) / defer to planner.

**Selection:** 4 plans, 1 per requirement (matches Phase 29 cadence).

---

## Round 1 — OAI-01

### Q1: OAI-01 fix shape — inline vs helper vs autouse?

**Options:**
1. Centralized helper `make_api_error()` in `tests/unit/conftest.py` (Recommended) — single locus, future SDK drift = 1-site fix.
2. Inline at each call site — mechanical sweep, ~150 LOC duplication.
3. Module-level autouse fixture monkeypatching `APIError.__init__` — magic; hides drift.

**Selection:** Centralized helper (Recommended).

**Notes:** Helper signature defined in CONTEXT.md. All 6 affected files import it.

### Q2: OAI-01 — production-code scope?

**Options:**
1. Test-fixture only (Recommended) — matches REQUIREMENTS.md acceptance.
2. Sweep production too — out of acceptance, scope creep.

**Selection:** Test-fixture only.

**Notes:** Plan 30-00 grep at execute time confirms zero `services/` `APIError(...)` callsites. If any surface, fix in same plan.

---

## Round 2 — EVT-01

### Q3: EVT-01 default approach — factory vs per-test loop?

**Options:**
1. `create_app()` factory by default; per-test fixture for outliers (Recommended) — Phase 27 TD-02 pattern.
2. Full factory mandate — rigid for outliers.
3. Per-test loop fixtures across the board — reverses Phase 27 direction.

**Selection:** Factory by default + per-test fixture for outliers.

**Notes:** Per-site choice documented in `30-01-SUMMARY.md`.

### Q4: EVT-01 — enumerate +14 sites now or at execute time?

**Options:**
1. Enumerate at execution time (Recommended) — REQUIREMENTS.md acceptance command captured in CONTEXT.md.
2. Enumerate now via best-effort — undercount risk on no-PG host.

**Selection:** Enumerate at execution time.

**Notes:** Plan 30-01 Task 0 runs the documented `pytest tests/integration/ -v 2>&1 | grep "no current event loop" | sort -u` command on a PG-enabled host. Executor surfaces delta to user if count significantly differs from 14.

---

## Round 3 — TEST-INFRA-01

### Q5: TEST-INFRA-01 fix path — (a)/(b)/(c)?

**Options:**
1. (c) mock `HuggingFaceEmbedder.__init__` directly (Recommended) — most surgical; no CI dep.
2. (a) move `embedder_or_mock` patch earlier — risk of autouse side effects.
3. (b) CI pre-download bge-m3 — 1.3GB, slow CI, infra dep.

**Selection:** (c) mock __init__ directly.

**Notes:** ~20 LOC test fixture. Mock at consumer path per v1.3 D-mock.

---

## Round 4 — MYPY-01

### Q6: MYPY-01 scope — single line / bounded sweep / full sweep?

**Options:**
1. Fix named site + bounded sweep cap 25 violations (Recommended) — predictable size.
2. Single line only — under-delivers vs REQUIREMENTS.md.
3. Full repo sweep no cap — unbounded scope.

**Selection:** Bounded sweep cap = 25.

**Notes:** Overflow → `deferred-items.md` for v1.9. Phase 29 baseline = 40 pre-existing errors.

### Q7: MYPY-01 silencing convention?

**Options:**
1. `# type: ignore[error-code]` with `# why:` comment (Recommended) — specific + auditable.
2. Fix everything, no silences — third-party lib stubs unfix-able.

**Selection:** `# type: ignore[error-code]` + `# why:`.

**Notes:** Bare `# type: ignore` not allowed. Pattern matches CLAUDE.md production standards.

---

## Deferred Ideas (captured for v1.9+)

- MYPY-01 overflow above 25 violations → `deferred-items.md`
- bge-m3 CI pre-download (TEST-INFRA-01 option b) → revisit if option (c) fails CI
- Centralized `tests/factories/openai_errors.py` (refactor helper out of `tests/unit/conftest.py`) if integration tests later need it
- Pyproject-locked `[tool.mypy] strict = true` selectively per-file

## Claude's Discretion (no decision needed — captured in CONTEXT.md)

- Helper module exact location (conftest vs factories) — pick at execute time
- Commit message convention (existing `feat(30-NN):` / `test(30-NN):` / `chore(30-NN):` / `docs(30-NN):` pattern)
- Logger level for any new test-fixture diagnostics
- Whether `tests/unit/conftest.py` exists pre-edit (create if missing)

## Scope Creep Surfaced

None. All proposed gray areas map directly to OAI-01 / EVT-01 / TEST-INFRA-01 / MYPY-01 requirements.
