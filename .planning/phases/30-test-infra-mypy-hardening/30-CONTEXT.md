# Phase 30 — Test Infra + mypy Hardening — Context

**Phase:** 30
**Milestone:** v1.8 Production Hardening Round 2
**Requirements:** OAI-01, EVT-01, TEST-INFRA-01, MYPY-01
**Status:** Discussed 2026-05-17 — ready for `/gsd-plan-phase 30`

## Phase Goal (from ROADMAP)

Clean up the test surface that's been masking real failures + finish the mypy --strict sweep. Fixes 32 openai-SDK-drift failures + 14 event-loop singleton leaks + 1 known-flaky extractor_e2e test + parametric-type annotations. Zero new user-facing capabilities — pure reliability + test infra polish.

## Decisions Captured

### OAI-01: openai SDK-drift fix shape

**Decision:** Centralized helper `make_api_error(...)` in `tests/unit/conftest.py`. All 6 affected test files import + use it; no inline construction.

**Helper shape:**
```python
def make_api_error(
    message: str = "test error",
    *,
    status_code: int = 500,
    request: httpx.Request | None = None,
) -> APIError:
    """Construct an openai.APIError with the v1.x required `request` arg.
    See REQUIREMENTS.md OAI-01 for context (32 latent test failures on master)."""
    if request is None:
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return APIError(message=message, request=request, body=None)
```

**Rationale:**
- 32 occurrences across 6 files → centralized helper reduces duplication ~3x vs inline.
- Single locus of truth for next SDK drift (when openai changes shape again, fix one site).
- Easier grep + audit (one definition, N callers vs N constructions).
- Matches v1.3 D-mock convention (mock at consumer path — helper lives in unit-test consumer scope).

**Rejected alternatives:**
- **Inline construction at each call site** — 150+ LOC duplication; future drift = N-site sweep.
- **Module-level autouse fixture monkeypatching `APIError.__init__`** — magic that hides drift; rejected for observability.

### OAI-01: Production-code scope

**Decision:** Test-fixture only. No `services/` edits unless grep at execution time surfaces a `services/` callsite that mirrors the test construction (mock-at-consumer convention).

**Rationale:**
- REQUIREMENTS.md OAI-01 acceptance: "No production-code changes (test-only fix unless test mirrors a production codepath)".
- Production code constructs `APIError` via openai SDK internals, not directly.

**Execute-time check (Plan 30-00):** Run `grep -rn "APIError(" services/ controllers/ utils/` — if zero results, test-only fix stands. If any hit, fix that callsite in the same plan with the helper imported.

### EVT-01: Event-loop singleton leak approach

**Decision:** Default each of the +14 sites to the `create_app()` factory pattern (Phase 27 TD-02 evidence). Sites that don't fit factory get an explicit per-test `event_loop` fixture. Per-site choice documented in `30-01-SUMMARY.md`.

**Rationale:**
- Carry-forward gate: `create_app()` factory pattern shipped in Phase 27 TD-02 with `_SINGLETON_INVENTORY` of 34 entries. EVT-01 grows the inventory by +14.
- Factory approach uniformly resets singletons per test via `_reset_singletons()` — addresses root cause (stale-loop survival across tests).
- Per-test fixtures handle sites that import singletons outside the FastAPI lifecycle.

**Rejected:**
- Full factory mandate — rigid for outliers.
- Per-test loop fixtures across the board — reverses Phase 27 TD-02 direction; doesn't address root cause.

### EVT-01: Site enumeration

**Decision:** Enumerate the +14 leak sites at plan execution time, NOT in this CONTEXT.md.

**Reason:** Acceptance per REQUIREMENTS.md says `pytest tests/integration/ -v 2>&1 | grep "no current event loop" | sort -u`. This host has no PostgreSQL — integration suite would skip many tests, undercounting the leak set. Enumeration must run on a PG-enabled host as Plan 30-01 Task 0.

**Plan 30-01 Task 0 enumeration command (captured for executor):**

```bash
uv run pytest tests/integration/ -v 2>&1 | grep "no current event loop" | sort -u > /tmp/30-01-leak-sites.txt
wc -l /tmp/30-01-leak-sites.txt   # expect 14
```

If the count is significantly off (e.g., 7 or 20), executor halts and surfaces the gap to the user before committing remediation.

### TEST-INFRA-01: extractor_e2e fix path

**Decision:** Option (c) — mock `services.vectorizer.embedder.HuggingFaceEmbedder.__init__` directly at conftest scope before `AgentQueryPipeline` construction.

**Rationale:**
- Most surgical: prevents `FileNotFoundError` at construction time without reordering existing fixture topology.
- Test-only, no CI dependency change, no model download.
- Matches mock-at-consumer convention (v1.3 D-mock).
- ~20 LOC test fixture; bounded LOC delta.

**Rejected:**
- Option (a) earlier patch ordering — risk of autouse fixture side effects on non-extractor tests.
- Option (b) CI pre-download — 1.3GB bge-m3 download, slower CI, adds infra dep. Defer unless option (c) fails.

### MYPY-01: scope

**Decision:** Fix named site `config/settings.py:154` (`embedding_ensemble: list[dict] = []` → `list[dict[str, Any]] = []`) + bounded repo-wide sweep with cap of **25 violations** in Phase 30. Violations beyond cap → captured in `deferred-items.md` for v1.9.

**Rationale:**
- REQUIREMENTS.md MYPY-01 acceptance allows "additional mypy --strict violations surfaced by a full-repo scan are either fixed or explicitly silenced with `# type: ignore[error-code]` + comment justifying" — but lacks a cap, making scope unbounded.
- Cap = 25 keeps Phase 30 sized predictably. Phase 29 verification reported 40 pre-existing mypy errors (baseline as of 2026-05-17) — cap of 25 covers majority without unbounded sweep.

### MYPY-01: silencing convention

**Decision:** When fixing is infeasible (untyped third-party lib, dynamic constructs), silence with **specific error code** plus single-line `# why:` justification:

```python
result = some_untyped_lib.call()  # type: ignore[no-any-return]  # why: third-party lib lacks stubs as of 2026-05
```

**NOT allowed:**
- Bare `# type: ignore` (no error code) — too broad, hides future regressions.
- `# type: ignore[error-code]` without `# why:` — easy to forget rationale; hard to revisit.

### Plan structure

**Decision:** 4 plans, 1 per requirement. Wave grouping:

| Plan | Wave | Type | Requirement | Depends On | Files (approximate) |
|------|------|------|-------------|------------|---------------------|
| 30-00 | 1 | TDD | OAI-01 | — | tests/unit/conftest.py + 6 test files |
| 30-01 | 2 | execute | EVT-01 | — (independent surface) | tests/factories/app.py + ~14 integration test files |
| 30-02 | 2 | TDD | TEST-INFRA-01 | — (independent surface) | tests/integration/test_extractor_e2e.py + conftest |
| 30-03 | 3 | execute | MYPY-01 | [30-00, 30-01, 30-02] (mypy sweep runs LAST so it catches new violations introduced by test-fixture changes) | config/settings.py + repo-wide silence sites |

**Wave 2 parallelism note:** 30-01 and 30-02 touch `tests/integration/` — 30-01's enumerated set MAY include `test_extractor_e2e.py` which 30-02 owns. Planner enumerates sites in Plan 30-01 Task 0; if `test_extractor_e2e.py` appears in the leak set, escalate to user: either drop it from 30-01 (let 30-02 own) or sequentialize. Until enumeration runs, treat 30-01 + 30-02 as Wave 2 parallel with intra-wave files_modified overlap check at execute time.

**Rationale:**
- Per-req plan boundaries match Phase 29 cadence + v1.7 phase 27 pattern. Per-req SUMMARY for traceability.
- 30-03 runs last because mypy sweep must catch any new violations introduced by 30-00/01/02 test-fixture additions.
- Wave 1 (30-00 alone) ships first because OAI-01 unblocks CI gate per REQUIREMENTS.md ("unblocks CI gate tightening").

### TDD discipline

**Decision:** Strict TDD (RED → GREEN → REFACTOR) per project standard for plans that touch behavior (30-00 OAI-01 — tests changing means tests are the artifact; the test pass/fail IS the gate). Plans 30-01 / 30-02 / 30-03 are `type: execute` (test infra + type sweep, no behavior change) — TDD relaxed; verification = test suite passes + mypy clean.

**Rationale:**
- 30-00 fixes 32 broken tests — those tests' assertions are the contract. RED-first not applicable (tests are already in RED state); rename the discipline to "verify-broken → fix-helper → re-run-green".
- 30-01 enumerates + remediates leak sites — pure infra refactor.
- 30-02 mock fixture addition — verification = extractor_e2e passes.
- 30-03 type sweep — verification = `uv run mypy --strict` cleaner than baseline.

## Carry-Forward Decisions (still in force)

| Decision | Source | Why it matters going forward |
|----------|--------|------------------------------|
| `create_app()` factory pattern + `_SINGLETON_INVENTORY` | v1.7 Phase 27 TD-02 | EVT-01 grows inventory by +14 |
| Mock at consumer path (`services.<mod>.<dep>`) | v1.3 Phase 13+15 | OAI-01 helper + TEST-INFRA-01 mock follow |
| `diff-cover ≥ 80%` on touched files | v1.1 Phase 10 TEST-03 | All 4 plans must clear |
| Combined coverage `--fail-under=70` global floor | v1.3 Phase 15 / v1.5 Phase 22 | Must not regress |
| Narrow exception types (no bare `except`) | v1.0 ERR-01 | MYPY-01 silences MUST cite error code |
| INSERT-ONLY `audit_log` invariant | v1.0 Phase 2 | Not touched by Phase 30 |
| Pydantic V2 + mypy --strict + ruff | CLAUDE.md | MYPY-01 directly enforces; others must not regress |
| `_bulk_near_duplicate_check_raw` is the save_facts helper | v1.8 Phase 29 (A1-A) | Plans touching memory_service.py reference this name, not the legacy `_bulk_near_duplicate_check` |

## Codebase Anchors

| Asset | Path / Line | Why it matters |
|-------|-------------|----------------|
| 32 failing tests (OAI-01) | `tests/unit/test_agent_pipeline_refactor.py` (11), `test_agent_sse.py` (9), `test_pipeline_coverage.py` (10), `test_feedback_ab_forward.py` (1), `test_memory_controller.py`, `test_recall_tool.py` | All construct `openai.APIError(...)` missing `request` arg |
| Existing `tests/unit/conftest.py` | `tests/unit/conftest.py` | Helper landing site; verify it exists pre-edit (else create) |
| `create_app()` factory | `tests/factories/app.py` | Plan 30-01 grows `_SINGLETON_INVENTORY` here |
| Phase 27 TD-02 reference | `.planning/milestones/v1.7-phases/27-test-isolation-memory-reliability/27-02-SUMMARY.md` | EVT-01 pattern source |
| extractor_e2e fixture | `tests/integration/test_extractor_e2e.py` + nearest `conftest.py` | TEST-INFRA-01 patch site |
| `HuggingFaceEmbedder.__init__` | `services/vectorizer/embedder.py` | Mock target for TEST-INFRA-01 option (c) |
| `config/settings.py:154` | `config/settings.py:154` | Named MYPY-01 site (`embedding_ensemble: list[dict] = []`) |
| Phase 29 mypy baseline | 40 pre-existing errors as of 2026-05-17 (per 29-VERIFICATION.md) | MYPY-01 measures progress against this |

## Canonical Refs

- `.planning/ROADMAP.md` (Phase 30 SC-1..4 + v1.8 carry-forward gates)
- `.planning/REQUIREMENTS.md` (OAI-01 / EVT-01 / TEST-INFRA-01 / MYPY-01 acceptance bullets)
- `.planning/PROJECT.md` (v1.8 milestone goal + carried context)
- `.planning/phases/29-toctou-silent-skip-enforcement/29-VERIFICATION.md` (mypy baseline + carry-forward `_bulk_near_duplicate_check_raw` rename)
- `.planning/milestones/v1.7-phases/27-test-isolation-memory-reliability/27-02-SUMMARY.md` (EVT-01 pattern source — `create_app()` factory)
- `./CLAUDE.md` + `Claude.md` (production standards — Pydantic V2, mypy --strict, ruff, no bare except)

## Acceptance (Phase Success Criteria — from ROADMAP)

1. **OAI-01:** All 32 enumerated `openai`-SDK-drift unit tests pass with the new `APIError(request=...)` construction shape (via `make_api_error()` helper). `pytest tests/unit/ -m 'not benchmark'` on master post-fix shows green. No production-code changes unless callsite mirror found.
2. **EVT-01:** Each of the +14 enumerated leak sites (via `pytest tests/integration/ -v 2>&1 | grep "no current event loop" | sort -u`) migrates to `create_app()` factory pattern OR adds an explicit per-test loop fixture. `_SINGLETON_INVENTORY` grows from 34 to cover the +14. `@pytest.mark.uses_redis` marker rollout introduces zero regressions in integration suite.
3. **TEST-INFRA-01:** `uv run pytest tests/integration/test_extractor_e2e.py -v` passes on clean checkout. `HuggingFaceEmbedder.__init__` mock fixture path documented in `30-02-SUMMARY.md`.
4. **MYPY-01:** `uv run mypy --strict config/settings.py` returns "Success: no issues found in 1 source file". Full-repo `uv run mypy --strict` scan: up to 25 surfaced violations fixed or silenced with `# type: ignore[error-code]` + `# why:` comment; remainder captured in `deferred-items.md`.

## Constraints

- **No production-code change** in OAI-01 / TEST-INFRA-01 (test-only) unless grep surfaces callsite mirror.
- **EVT-01 must not regress** the v1.7 Phase 27 SC-1 evidence (34 inventory entries already in place).
- **TEST-INFRA-01 must not slow CI** — option (c) is mock, no model download.
- **MYPY-01 cap = 25 violations** in Phase 30; overflow deferred to v1.9.
- **Carry-forward gates** apply: diff-cover ≥ 80%, --fail-under=70, no bare except.
- **Phase 29 `_bulk_near_duplicate_check_raw` rename** — any Phase 30 touch to `services/memory/memory_service.py` (none expected) must use the post-29-00 name.

## Open Risks / Watch-outs

- **EVT-01 enumeration uncertainty:** the +14 count came from a Phase 27 surface scan; if execute-time `pytest tests/integration/` shows ≠14, executor must surface the delta to the user before remediation. Cap risk: if 30 sites surface, scope creep — defer overflow to v1.9.
- **30-01 + 30-02 file overlap:** if `test_extractor_e2e.py` appears in 30-01's enumerated leak set, sequentialize the wave (planner decides at /gsd-plan-phase 30 time).
- **MYPY-01 sweep surfaces churn:** silencing third-party-lib violations may need `mypy.ini` / `pyproject.toml [tool.mypy]` per-module overrides; allowed if narrower than blanket silence.
- **Helper-in-conftest scope:** OAI-01 `make_api_error` in `tests/unit/conftest.py` is auto-imported by all tests under `tests/unit/`. If a test outside `tests/unit/` (e.g., `tests/integration/`) needs the helper later, refactor to `tests/factories/openai_errors.py`. Out of v1.8 scope.

## Claude's Discretion (no decision needed)

- Helper module exact location (`tests/unit/conftest.py` vs `tests/factories/openai_errors.py`) — pick at execute time based on conftest size.
- Commit message convention (`feat(30-NN):` / `test(30-NN):` / `chore(30-NN):` / `docs(30-NN):`).
- Logger level for any new test-fixture diagnostics (debug).
- Whether `tests/unit/conftest.py` exists pre-edit (create if missing).

## Deferred Ideas (Noted for Later)

- **MYPY-01 overflow (>25 violations):** capture in `deferred-items.md`; v1.9 candidate.
- **bge-m3 CI pre-download (TEST-INFRA-01 option b):** revisit if option (c) doesn't pass clean checkout test on CI.
- **Centralized `tests/factories/openai_errors.py`:** if integration tests later need `make_api_error`, refactor out of `tests/unit/conftest.py`.
- **Mypy strict on a per-file basis via `[tool.mypy] strict = true` selectively** — currently the project runs `uv run mypy --strict` ad-hoc; pyproject-locked strict mode is a v1.9+ follow-up.

## Next Action

```
/clear
/gsd-plan-phase 30
```

Optional pre-plan: `/gsd-plan-phase 30 --skip-research` — surgical scope, codebase anchors above are sufficient (matches Phase 29 cadence).

Phase 29 PG-gated integration test (`tests/integration/memory/test_save_facts_toctou.py`) remains `human_needed` — independent ceremony. Run on PG-enabled host whenever convenient; does NOT block Phase 30.
