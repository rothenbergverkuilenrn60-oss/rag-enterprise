# Phase 10: Coverage Gate on New Code - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a CI gate that **fails any PR leaving a v1.1-touched file under 80 % line coverage on its changed lines**, while leaving the existing global 46 % floor untouched as an informational metric. Adds:

- `diff-cover` Python tool (PyPI `diff-cover`) added to `requirements-dev.txt`.
- `Makefile` target `make coverage-diff` for local pre-PR check.
- New step in the existing `unit-tests` job in `.github/workflows/ci.yml` that runs `diff-cover` against the v1.0 tag, fails the job below 80 %, and uploads the HTML report as a GitHub Actions artifact.

**In scope:**

- diff-cover tooling install + config
- CI step append + HTML artifact upload
- Makefile local target
- Documentation update for coverage workflow

**Out of scope:**

- Raising legacy 46 % floor (v1.1 OOS — explicitly deferred indefinitely)
- Diff-coverage on integration tests (B1 lock — unit-only)
- Per-file override comments / soft-warn modes (D1 lock — hard block)
- Net-new CI workflow file (C1 lock — append to existing job)
- Migrating to `coverage-diff-action` or other tools (REQ-spec locks `diff-cover`)

</domain>

<decisions>
## Implementation Decisions

### A) Diff Baseline Ref — Split CI vs Local
- **D-01:** CI `coverage-diff` step compares against the **`v1.0` git tag** (the v1.1 milestone baseline per REQ C-1 acceptance #1).
- **D-02:** Local `make coverage-diff` compares against **`origin/master...HEAD`** (the dev-loop iteration ref per SC #2).
  - **Why split:** REQ-spec `v1.0` baseline measures the milestone delta (gates the v1.1 PR set against the published v1.0 tag — what the gate exists to enforce). SC #2's `origin/master` is the dev-loop ref (developer iterates against current main, sees only their own diff). Each ref serves the use case it was written for; forcing one ref into both lanes hurts the other lane.
  - **How agents apply:** Planner MUST produce two distinct invocation patterns: CI uses `diff-cover coverage.xml --compare-branch=v1.0`; Makefile uses `diff-cover coverage.xml --compare-branch=origin/master`. Threshold (80 %) is identical in both.

### B) Coverage Scope — Unit Tests Only
- **D-03:** `diff-cover` consumes the `coverage.xml` produced by the existing **unit-tests** job. Integration-test coverage is **NOT** included in the diff numerator.
  - **Why:** Existing `unit-tests` job already runs `pytest --cov=services --cov=utils`; integration job does not. Enabling `--cov` in integration adds redis-dependent flakiness, requires `coverage combine` round-tripping artifacts, and adds 10–15 min CI time. v1.1 milestone is small — no measurable v1.1 file is reachable only by integration tests.
  - **How agents apply:** Planner does NOT touch the `integration-tests` job. Coverage XML is generated in the existing unit-tests `pytest` step; diff-cover runs immediately after on the same job's working tree.
  - **Trade accepted:** Files exercised primarily by integration tests (some `controllers/`, some `services/pipeline.py` paths) may show artificially low diff coverage; PR author must add a unit test or restructure. This is desirable pressure, not a bug.

### C) CI Placement — Append Step to Unit-Tests Job
- **D-04:** The diff-coverage check is a new **step** appended to the existing `unit-tests` job in `.github/workflows/ci.yml`. NO new job, NO new workflow file.
  - **Why:** Reuses installed deps and the on-disk `.coverage` from the prior step. Single artifact upload (existing `coverage-report` upload changes from `path: .coverage` to also upload the HTML diff report). Simplest diff, shortest critical-path CI time.
  - **How agents apply:** Planner edits `.github/workflows/ci.yml` only; adds 2 steps after the existing `Run unit tests with coverage` step:
    1. `Run diff-cover against v1.0` — `diff-cover coverage.xml --compare-branch=v1.0 --fail-under=80 --html-report diff-cover.html`
    2. Modify the existing `Upload coverage report` step (or add a parallel one) to include `diff-cover.html`.
  - The `--cov-fail-under=46` flag on the prior step **stays as-is** (legacy informational floor, SC #4).

### D) Failure Strictness — Hard Block, No Overrides
- **D-05:** Diff-coverage threshold is a **hard CI fail**. No magic-comment overrides (e.g., `# coverage:ignore-diff`), no soft-warn mode, no per-file thresholds.
  - **Why:** REQ C-1 acceptance #3 reads strict ("Threshold-fail blocks merge"). v1.1 is small and intentional — rigour now prevents v1.0's coverage drift from repeating. Override comments add a maintenance contract that erodes silently. Soft-warn defeats the gate (v1.0 lived under no-gate and ended at 46 %).
  - **How agents apply:** Use `--fail-under=80` on `diff-cover`; non-zero exit fails the step → fails the job → blocks merge. Do NOT introduce parser hooks for ignore-comments. If a v1.1 file genuinely cannot be unit-tested (e.g., main entry point), the answer is to refactor it or accept the block — not bypass.

### Claude's Discretion (planner / executor decide HOW)

- Where exactly to place the new step in `ci.yml` (line numbers will shift)
- Whether to upload `diff-cover.html` via the existing `Upload coverage report` step (modify) or a new `Upload diff-coverage HTML` step (add) — pick whichever has cleanest YAML diff
- Exact Makefile target body (must produce same pass/fail verdict as CI; pin `coverage.xml` generation if not already there)
- Handling of `v1.0` tag absence on a fresh clone — `git fetch --tags` upfront in CI step (cheap), and Makefile target should `git fetch --tags origin v1.0` if missing
- Whether `diff-cover` is added to `requirements-dev.txt`, `pyproject.toml [dev]`, or both — match existing pattern
- README / CONTRIBUTING.md doc update wording
- Whether to set `--cov-report=xml` on the existing pytest invocation explicitly (diff-cover needs `coverage.xml`, not `.coverage` binary) — likely YES, planner verifies

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 10 spec
- `.planning/REQUIREMENTS.md` §"REQ C-1 (TEST-03)" — 5 acceptance criteria; **all** are the source of truth for this phase
- `.planning/ROADMAP.md` §"Phase 10: Coverage Gate on New Code" — 4 success criteria

### Existing CI / build (to be EXTENDED, not replaced)
- `.github/workflows/ci.yml` — `unit-tests` job (lines ~36-72) is where the new step gets appended; `--cov-fail-under=46` line stays
- `Makefile` — existing `test` / `test-unit` / `test-eval` targets show the `conda run -n torch_env pytest …` pattern; new `coverage-diff` target follows it
- `requirements.txt` + `requirements-dev.txt` + `pyproject.toml [dev]` — pinned-version dep pattern; `pytest-cov==6.0.0` already present

### Tooling docs (planner / researcher reads externally)
- `diff-cover` (PyPI) — https://github.com/Bachmann1234/diff_cover — primary tool
- GitHub Actions `actions/upload-artifact@v4` — already used in repo; pattern to copy

### v1.1 milestone OOS lines (do not violate)
- `.planning/REQUIREMENTS.md` §"Out of Scope (v1.1)" line "Reaching 80 % coverage on legacy modules (deferred indefinitely; v1.1 only gates new code)"
- `.planning/PROJECT.md` §"Current Milestone: v1.1 Retrieval Depth & Frontend"

### Predecessor phases (read for cross-phase consistency)
- `.planning/phases/07-…/07-CONTEXT.md`, `08-…/08-CONTEXT.md`, `09-…/09-CONTEXT.md` — prior locked decisions; Phase 10 must not break their CI assumptions

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `unit-tests` job in `ci.yml` already runs `pytest --cov=services --cov=utils --cov-report=term-missing --cov-fail-under=46`. Add `--cov-report=xml:coverage.xml` to that command (or as additional flag) so `diff-cover` has its input file. No other job changes needed.
- Existing `Upload coverage report` step demonstrates the `actions/upload-artifact@v4` pattern.
- `Makefile` already uses `conda run -n torch_env pytest …` — local target follows same pattern.

### Established Patterns
- Tools pinned in `requirements*.txt` AND mirrored in `pyproject.toml [dev]` (cf. `pytest-cov==6.0.0`). New dep `diff-cover==X.Y.Z` follows.
- CI jobs depend on `lint-and-type-check` then `unit-tests`. Diff-cover is co-located in unit-tests, so no `needs:` change.
- `continue-on-error: true` exists on `mypy` step but NOT on coverage — coverage failures already block. Diff-cover follows that strictness.

### Out-of-the-way patterns to NOT propagate
- Coverage was set up around `--cov-fail-under=46` for legacy reasons. Do NOT raise that number — it's the legacy informational floor (SC #4). Diff-cover's `--fail-under=80` is the new gate.
- Don't introduce `coverage combine` or merge files from multiple jobs — B1 locked unit-only.

</code_context>

## Deferred Ideas

Captured per D-01..D-05 decisions and v1.1 OOS:

1. **Integration-test coverage merging** (B2 alternative) — promote when integration suite stabilizes and a v1.2 file is reachable only by integration paths.
2. **Per-file override comments** (D2 alternative) — only if `main.py`-style boot code becomes a recurring blocker; reassess in v1.2.
3. **Soft-warn mode** (D3) — explicitly rejected; do not revisit unless the gate causes legitimate dev-loop pain.
4. **Raising the legacy 46 % global floor** — v1.1 OOS, deferred indefinitely; track as separate v1.x retrospective topic.
5. **Replacing `diff-cover` with a GitHub Action** — reassess if `diff-cover` package becomes unmaintained (currently active).
6. **Coverage on the `static/ui.html` JS** (Phase 9 deferred) — frontend test framework is itself a v1.2+ phase.
