# Phase 15: Coverage Combine and 70% Floor - Context

**Gathered:** 2026-05-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Combine unit + integration coverage in CI: unit-tests job emits `.coverage.unit`, integration-tests job adds `--cov` flags and emits `.coverage.integration`, a new `coverage-combine` job downloads both artifacts, runs `coverage combine`, then `coverage report --fail-under=70` (TEST-06) and `coverage xml` for diff-cover (TEST-03 — relocated from unit job). Set global floor in `pyproject.toml [tool.coverage.report]` to `fail_under = 70` (up from 46). Identify service modules below 70% via measure-then-plan workflow inside Wave 2 and backfill primary-execution-path unit tests. diff-cover gate (≥80% on changed lines vs v1.0 baseline) keeps running but moves to combine job and consumes combined `coverage.xml`.

Out of scope:
- Raising floor above 70% (deferred to v1.4+)
- Mutation testing (TEST-07, deferred to v1.4+)
- Removing `continue-on-error` from integration-tests job (kept per D-03)
- New CI coverage badge in README — README copy updates only (badge is out-of-scope for v1.3)
- Backfill tests for non-service modules (utils/, controllers/) — only `services/` is in scope per TEST-06 AC#4 wording "service modules"
</domain>

<decisions>
## Implementation Decisions

### Coverage Configuration
- **D-01:** Coverage config lives in `pyproject.toml` `[tool.coverage.run]` and `[tool.coverage.report]` blocks. NO `.coveragerc` file (would conflict precedence). Matches uv-managed project pattern; one config file for everything.
- **D-08:** `[tool.coverage.report]` sets `fail_under = 70` (up from 46). `show_missing = true` and `precision = 1` for per-module breakdown (TEST-06 AC#5). `[tool.coverage.run]` sets `source = ["services", "utils"]` and `parallel = true` to make `combine` work cleanly across multiple `.coverage.*` data files.

### CI Job Topology
- **D-02:** Three jobs in ci.yml:
  1. `unit-tests` — runs `pytest tests/unit/ --cov=services --cov=utils --cov-report=xml --cov-report=term-missing`. NO `--cov-fail-under` flag (D-06). Uploads `.coverage.unit` and `coverage.xml` (the unit-only one) as artifacts.
  2. `integration-tests` — runs `pytest tests/integration/ --cov=services --cov=utils --cov-append`. Saves `.coverage` data file. Uploads `.coverage.integration` artifact. Keeps `continue-on-error: true` (D-03).
  3. `coverage-combine` (NEW) — `needs: [unit-tests, integration-tests]`. Downloads both artifacts. Runs `coverage combine .coverage.unit .coverage.integration`. Then `coverage report --fail-under=70` (TEST-06 AC#2 hard gate). Then `coverage xml -o coverage.xml`. Then runs diff-cover against combined coverage.xml (TEST-03, ≥80% on v1.0 baseline). Uploads final `coverage-report` artifact (combined `.coverage`, `coverage.xml`, `diff-cover.html`).
- **D-05:** diff-cover step moves from `unit-tests` job to `coverage-combine` job. Uses combined `coverage.xml` per TEST-04 AC#3 (combined report = source of truth).
- **D-06:** Drop `--cov-fail-under=46` from `unit-tests` pytest call (currently ci.yml line 64). Floor check happens once, in `coverage-combine` job, on combined data. Unit job collects data only.
- **D-10:** `integration-tests` pytest invocation gains `--cov=services --cov=utils --cov-append --cov-report=` (no terminal report — combine job emits the report). `--cov-append` appends to any pre-existing `.coverage` file in the working directory. Job sets `COVERAGE_FILE=.coverage.integration` env var so the file is named correctly for the artifact upload.

### Failure Policy
- **D-03:** `integration-tests` keeps `continue-on-error: true` (currently ci.yml line 130). Pragma: integration tests are flaky (Redis/pgvector/network deps); blocking PRs on flakes is unacceptable. The `coverage-combine` job uses whatever `.coverage.integration` data was produced (may be empty if integration crashed). The combined floor check runs against whatever is available; if integration produced no data, combined coverage equals unit-only coverage and may fall below 70%. That failure is the correct signal — integration crashing is a real problem worth blocking on (transitive via combine-job floor failure).
- **D-09:** TEST-03 diff-cover gate continues independently — ≥80% line coverage on changed lines vs v1.0 baseline. Hard-block (no continue-on-error after the v1.1 bootstrap exception). Not affected by floor change.

### Backfill Workflow (TEST-06 AC#4)
- **D-04:** Backfill follows a measure-then-plan workflow inside Wave 2 (Plan 15-02):
  1. Run `coverage combine .coverage.unit .coverage.integration && coverage report --skip-covered=false` locally to identify all modules under `services/` with line coverage <70%.
  2. Sort by impact (lowest coverage * highest LOC = biggest gap).
  3. Write 1-2 unit tests per identified module covering primary execution paths (happy path + at least one error path). Goal: raise combined floor to ≥70%.
  4. Re-run combined report after each batch; stop when `coverage report --fail-under=70` exits 0.
- **D-12:** README.md `## Coverage` section (lines 241-273) is updated as part of Wave 1 to reflect the new 70% floor and combined-report behavior. Phase 10 Decision D-03 ("only unit-test coverage counts") is explicitly superseded — note this in the README + cite Phase 15 D-05 as the supersession source.

### Wave Structure
- **D-07:** Two plans:
  - **15-01 (Wave 1) — Plumbing:** pyproject.toml `[tool.coverage.*]` blocks; ci.yml topology refactor (3 jobs + artifact wiring + diff-cover migration); integration-tests gains --cov flags; README.md coverage section update. NO new test files.
  - **15-02 (Wave 2) — Backfill:** depends_on 15-01. Measure → identify → write unit tests for service modules <70%. Floor must be ≥70% post-backfill (CI green).

### Out-of-Scope Reaffirmations
- **D-11:** No CI coverage badge added in v1.3. README documents combined coverage but does not add a shields.io / codecov badge. (TEST-04 AC#4 satisfied via the combined `coverage-report` artifact and the per-module breakdown in CI logs — interpretation: artifact + log line is "PR comment surface" already in place.)
</decisions>

<canonical_refs>
## Canonical References

### Requirements
- `.planning/REQUIREMENTS.md` §TEST-04 (lines 72-86) — 5 acceptance criteria
- `.planning/REQUIREMENTS.md` §TEST-06 (lines 87-100) — 5 acceptance criteria
- `.planning/ROADMAP.md` §Phase 15

### Core Codebase
- `pyproject.toml` (project root) — currently lacks any `[tool.coverage.*]` block; Phase 15 ADDS them. Existing `[dependency-groups] dev` already includes `pytest-cov`, `diff-cover`, `pytest-timeout` (lines 78-87).
- `.github/workflows/ci.yml` (215 lines) — current 3-job structure (unit-tests + integration-tests + security-scan + docker-build). Phase 15 adds 4th job `coverage-combine` and modifies unit-tests + integration-tests.
- `pytest.ini` — keep as-is; `addopts = -m "not integration"` is the unit/integration split convention.
- `README.md` lines 241-273 — Coverage section. Update copy to reflect combined report + 70% floor.

### Prior Phase Context
- v1.1 Phase 10 TEST-03 (`.planning/phases/10-coverage-gate-on-new-code/10-CONTEXT.md`): diff-cover ≥80% on changed lines vs v1.0 baseline. Phase 15 PRESERVES this gate, but moves it from unit-tests job to coverage-combine job (consumes combined coverage.xml).
- v1.1 Phase 10 D-03: "Only unit-test coverage counts" — Phase 15 EXPLICITLY SUPERSEDES via D-05 (combined coverage is source of truth).
- v1.0 Phase 1 D-XX: 46% floor as bootstrap guard. Phase 15 raises to 70%.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pytest-cov==6.0.0` — already in `[dependency-groups] dev`. Provides `--cov` and `--cov-append` flags.
- `diff-cover>=9.7.2` — already in `[dependency-groups] dev`. Currently invoked at ci.yml:79.
- GitHub Actions `actions/upload-artifact@v4` and `actions/download-artifact@v4` — already used in ci.yml:84-92 for coverage-report artifact.

### Established Patterns
- **OPS-01 config-via-pyproject.toml:** Project consolidates config in pyproject.toml (uv-managed). Phase 15 follows.
- **CI job dependencies:** ci.yml already uses `needs: unit-tests` (line 97) for integration-tests. Phase 15 uses `needs: [unit-tests, integration-tests]` for combine job.
- **Artifact upload-then-download:** Standard GitHub Actions pattern. ci.yml currently uploads from one job; Phase 15 adds upload from integration + download in combine.

### Integration Points
- `unit-tests` job → uploads `.coverage.unit` artifact
- `integration-tests` job → uploads `.coverage.integration` artifact (set `COVERAGE_FILE` env var to control name)
- `coverage-combine` job → downloads both → `coverage combine` → `coverage report --fail-under=70` → `coverage xml` → `diff-cover ... --fail-under=80`
- `pyproject.toml [tool.coverage.run]` `parallel = true` makes coverage data files unique per process (suffix with hostname.pid.uuid) so combine doesn't conflict — but in our case we're explicitly naming them via `COVERAGE_FILE`, so `parallel = true` is belt-and-suspenders.

### Verified Module-Below-Floor Identification
- Will be done at Wave 2 plan-time. Not pre-scoped per D-04 (measure-then-plan).
</code_context>

<specifics>
## Specific Ideas

### pyproject.toml additions (Wave 1)
```toml
[tool.coverage.run]
source = ["services", "utils"]
parallel = true
branch = false  # line coverage only; branch coverage is v1.4+ candidate
omit = [
    "*/__init__.py",
    "*/migrations/*",
    "*/tests/*",
]

[tool.coverage.report]
fail_under = 70
show_missing = true
precision = 1
skip_covered = false  # show all modules including covered ones for visibility
exclude_lines = [
    "pragma: no cover",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
```

### ci.yml `coverage-combine` job sketch (Wave 1)
```yaml
coverage-combine:
  name: Coverage Combine and Floor
  runs-on: ubuntu-latest
  needs: [unit-tests, integration-tests]
  if: always()  # run even if integration-tests failed (per D-03)
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0  # diff-cover needs full history

    - uses: actions/setup-python@v5
      with:
        python-version: "3.11"
        cache: pip

    - name: Install dependencies
      run: pip install -r requirements.txt -r requirements-dev.txt

    - name: Download unit coverage
      uses: actions/download-artifact@v4
      with:
        name: coverage-unit
        path: .

    - name: Download integration coverage
      uses: actions/download-artifact@v4
      with:
        name: coverage-integration
        path: .
      continue-on-error: true  # integration may have produced no artifact

    - name: Combine coverage
      run: |
        ls -la .coverage.* 2>&1 || true
        coverage combine .coverage.unit .coverage.integration 2>&1 || coverage combine .coverage.unit
        coverage report --skip-covered=false
        coverage xml -o coverage.xml

    - name: TEST-06 floor gate (combined coverage ≥70%)
      run: coverage report --fail-under=70

    - name: Fetch v1.0 tag for diff-cover baseline
      run: git fetch origin tag v1.0 --no-tags

    - name: TEST-03 diff-cover gate (≥80% on changed lines)
      run: |
        diff-cover coverage.xml \
          --compare-branch=v1.0 \
          --fail-under=80 \
          --format html:diff-cover.html

    - name: Upload final coverage artifacts
      uses: actions/upload-artifact@v4
      if: always()
      with:
        name: coverage-report
        path: |
          .coverage
          coverage.xml
          diff-cover.html
```

### unit-tests job changes (Wave 1)
- Drop `--cov-fail-under=46` from pytest call (D-06).
- Add `COVERAGE_FILE=.coverage.unit` env var.
- Replace `Upload coverage report` step with: upload `.coverage.unit` and `coverage.xml` (the unit-only one) as artifact named `coverage-unit`.
- Remove the `Run diff-cover against v1.0 (TEST-03 hard gate)` step (moves to combine job per D-05).

### integration-tests job changes (Wave 1)
- Add `COVERAGE_FILE=.coverage.integration` env var.
- pytest call adds `--cov=services --cov=utils --cov-append --cov-report=` (empty `--cov-report=` suppresses terminal output; data only).
- Add `Upload integration coverage` step uploading `.coverage.integration` as artifact named `coverage-integration`.

### README.md update (Wave 1)
Replace lines 241-273 to:
- Document combined-report behavior: "CI combines unit + integration coverage via `coverage combine`. Floor: 70% (raised from 46% in v1.3)."
- Update local make target description if applicable (`make coverage-diff`).
- Cite Phase 15 D-05 as supersession of Phase 10 D-03.

### Backfill workflow (Wave 2)
1. Run locally: `coverage erase && pytest tests/unit/ --cov=services --cov=utils && pytest tests/integration/ --cov-append && coverage report > /tmp/coverage-report.txt`
2. Parse `/tmp/coverage-report.txt` for modules with `<70%` line coverage.
3. Sort by `(missing_lines * total_lines)` to prioritize high-impact gaps.
4. For each module (typically 5-10 candidates): write 1-2 unit tests covering happy path + 1 error path. Use existing test patterns (mock_pipeline `__new__` fixture from Phase 12 / 13).
5. Re-run combined report after each batch. Stop when `coverage report --fail-under=70` exits 0.
6. Commit batches as `test(15-02): cover services/<module>.py to 70%+`.
</specifics>

<deferred>
## Deferred Ideas

- Branch coverage (`branch = true`) — line coverage is sufficient for v1.3. Branch coverage adds noise to diff-cover and may require test rewrites. v1.4+ candidate.
- CI coverage badge (shields.io / codecov.io) — TEST-04 AC#4 satisfied via existing artifact upload + per-module log lines. Badge is operational nice-to-have.
- Mutation testing (TEST-07) — deferred to v1.4+.
- Raising floor above 70% — 70% is v1.3 ceiling. v1.4 may raise to 75-80% as backfill matures.
- Backfill tests for `utils/` and `controllers/` — TEST-06 AC#4 wording is "service modules"; non-service backfill is opportunistic only.
- `continue-on-error` removal on integration-tests — keep as-is per D-03; flaky integration is an operational concern, not a coverage concern.
</deferred>

---

*Phase: 15-Coverage-Combine-and-70-Floor*
*Context gathered: 2026-05-09*
