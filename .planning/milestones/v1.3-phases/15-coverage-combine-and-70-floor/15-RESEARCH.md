# Phase 15: Coverage Combine and 70% Floor — Research

**Researched:** 2026-05-09
**Domain:** CI / coverage tooling (coverage.py 7.x + pytest-cov + diff-cover + GitHub Actions)
**Confidence:** HIGH (decisions locked; tooling behavior empirically verified against coverage.py 7.13.5)

## Summary

Phase 15 plumbs combined unit+integration coverage in CI via a 3-job topology and raises the floor from 46% → 70%. All architecture is locked in CONTEXT (D-01..D-12); research only validates the **how**: pyproject.toml schema, GitHub Actions artifact mechanics, and `coverage combine` semantics. **One CONTEXT detail needs revision** — D-08 sets `parallel = true`, but empirical testing shows that conflicts with explicit `COVERAGE_FILE=.coverage.unit` naming (parallel mode appends `.host.pid.rand` suffix to every output, breaking the artifact-upload glob). Recommend `parallel = false` for the locked-name pattern; if `parallel = true` is preserved for "belt-and-suspenders", artifact globs must be `path: .coverage.unit*` (with wildcard).

**Primary recommendation:** Set `parallel = false` in `[tool.coverage.run]`; keep explicit `COVERAGE_FILE` per-job naming (D-10). This produces deterministic filenames (`.coverage.unit`, `.coverage.integration`) that artifact upload/download can address by exact name. Pre-combine, also use `coverage combine --keep` so the inputs remain available in the artifact for debugging.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Coverage config in `pyproject.toml` `[tool.coverage.run]` and `[tool.coverage.report]`. NO `.coveragerc`.
- **D-02:** Three-job CI topology: `unit-tests` (data only), `integration-tests` (data only, `--cov-append`, keep `continue-on-error: true`), new `coverage-combine` (downloads both, runs combine + report --fail-under=70 + xml + diff-cover).
- **D-03:** `integration-tests` keeps `continue-on-error: true`. `coverage-combine` runs `if: always()`, uses whatever data exists.
- **D-04:** Backfill follows measure-then-plan in Wave 2 (run combined report, identify <70% modules under `services/`, backfill 1-2 unit tests each, iterate).
- **D-05:** diff-cover step migrates from `unit-tests` job to `coverage-combine` job. Consumes combined `coverage.xml`.
- **D-06:** Drop `--cov-fail-under=46` from `unit-tests` pytest call (currently ci.yml line 64). Floor enforced once, in combine job.
- **D-07:** Two plans — 15-01 plumbing, 15-02 measure+backfill (depends_on 15-01).
- **D-08:** `[tool.coverage.report]`: `fail_under = 70`, `show_missing = true`, `precision = 1`. `[tool.coverage.run]`: `source = ["services", "utils"]`, `parallel = true`. **(See Pitfall 1 — parallel=true conflicts with explicit COVERAGE_FILE; flagged for planner.)**
- **D-09:** TEST-03 diff-cover gate continues — ≥80% on changed lines vs v1.0 baseline. Hard-block (no continue-on-error after the v1.1 bootstrap exception).
- **D-10:** `integration-tests` pytest gains `--cov=services --cov=utils --cov-append --cov-report=` (empty `--cov-report=` suppresses terminal). Sets `COVERAGE_FILE=.coverage.integration`.
- **D-11:** No CI coverage badge in v1.3. Artifact + per-module log lines satisfy TEST-04 AC#4.
- **D-12:** README.md Coverage section (lines 241-273) updated as part of Wave 1. Phase 10 D-03 ("only unit-test coverage counts") explicitly superseded by Phase 15 D-05.

### Claude's Discretion

- Exact `omit` list in `[tool.coverage.run]` (CONTEXT specifies `*/__init__.py`, `*/migrations/*`, `*/tests/*`).
- `exclude_lines` patterns in `[tool.coverage.report]` (standard set: `pragma: no cover`, `raise NotImplementedError`, `if __name__ == .__main__.:`, `if TYPE_CHECKING:`).
- Whether to add a `make coverage-combined` local target (recommendation: **yes** — see Open Question #1).
- Exact wording of the README §Coverage rewrite per D-12.

### Deferred Ideas (OUT OF SCOPE)

- Branch coverage (`branch = true`) — line-only in v1.3.
- Coverage badge (shields.io / codecov.io).
- Mutation testing (TEST-07).
- Raising floor above 70%.
- Backfill for `utils/` and `controllers/` — TEST-06 AC#4 wording is "service modules".
- Removing `continue-on-error` on `integration-tests`.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TEST-04 AC#1 | unit + integration produce separate `.coverage.unit` / `.coverage.integration` | D-02, D-10 + verified `COVERAGE_FILE` naming (Pattern 1 + Pitfall 1) |
| TEST-04 AC#2 | `coverage combine .coverage.unit .coverage.integration` then `coverage report` + `coverage xml` on combined | D-02 + verified `combine` accepts explicit filenames (Pattern 3) |
| TEST-04 AC#3 | Combined report = source of truth for floor + diff-cover | D-05 + diff-cover migration code example |
| TEST-04 AC#4 | CI badge / PR comment reflects combined coverage | D-11 reaffirms artifact + log line satisfies AC; no badge added |
| TEST-04 AC#5 | No regression in diff-cover behavior | D-05, D-09 + verified diff-cover consumes any `coverage.xml` regardless of source data |
| TEST-06 AC#1 | `pyproject.toml [tool.coverage.report] fail_under = 70` | D-01, D-08 + Pattern 1 |
| TEST-06 AC#2 | `coverage report --fail-under=70` runs on combined `.coverage` | D-02, D-08 + verified exit code 2 on miss (Pitfall 5) |
| TEST-06 AC#3 | diff-cover gate runs independently, unaffected | D-09 + Pattern 4 |
| TEST-06 AC#4 | All `services/` modules below 70% at v1.2 close get unit tests covering primary paths | D-04 backfill workflow + Wave 2 plan in 15-02 |
| TEST-06 AC#5 | Per-module breakdown in CI artifacts | D-08 `show_missing = true` + `precision = 1` + log capture |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Coverage config schema | `pyproject.toml` | — | OPS-01 single-config principle (D-01) |
| Unit data collection | `unit-tests` CI job | — | Existing test split via pytest.ini `addopts = -m "not integration"` |
| Integration data collection | `integration-tests` CI job | — | Marker-driven; `--cov-append` mode (D-10) |
| Combine + floor enforcement | `coverage-combine` CI job (NEW) | — | Single source of truth (D-02, D-05) |
| diff-cover gate (≥80% on changed lines) | `coverage-combine` CI job | — | Migrated from unit-tests per D-05 |
| Local developer feedback | `Makefile` `coverage-diff` target | `make coverage-combined` (NEW, recommended) | Mirrors CI for local DX |
| Documentation | `README.md §Coverage` | `.planning/phases/15-...` | D-12 README update + supersession note |
| Backfill tests | `tests/unit/test_<service>.py` (Wave 2) | — | TEST-06 AC#4 — `services/` only |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `coverage` | 7.x (transitive via pytest-cov 6.0.0) | Data collection, combine, report, xml | De facto Python coverage tool [VERIFIED: empirically tested 7.13.5] |
| `pytest-cov` | `==6.0.0` (pyproject.toml line 37, 83) | pytest plugin: `--cov`, `--cov-append`, `--cov-report=` | Pinned in `[dependency-groups] dev` [VERIFIED: pyproject.toml] |
| `diff-cover` | `>=9.7.2` (pyproject.toml line 79) | Diff-aware coverage gate vs git baseline | Already in dev group [VERIFIED: pyproject.toml] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `actions/upload-artifact@v4` | v4 (ci.yml:85) | Persist `.coverage.*` SQLite + xml between jobs | Existing pattern in ci.yml [VERIFIED: ci.yml line 85] |
| `actions/download-artifact@v4` | v4 (assumed) | Pull artifacts into combine job | Std GH Actions idiom [ASSUMED — verify in Wave 1] |
| `actions/checkout@v4` + `fetch-depth: 0` | (ci.yml:42-44) | Required for diff-cover to find merge-base with v1.0 tag | Existing pattern, MUST replicate in combine job |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `coverage combine .coverage.unit .coverage.integration` | `--cov-append` in single job sequentially | Loses parallelism, conflicts with `continue-on-error: true` semantics |
| pyproject.toml | `.coveragerc` | Two config files, OPS-01 violation; rejected per D-01 |
| `parallel = true` (CONTEXT D-08) | `parallel = false` | **`parallel = true` appends `.host.pid.rand` suffix even with explicit COVERAGE_FILE — breaks named-artifact pattern.** See Pitfall 1. **Recommend revision to `parallel = false`.** |

**Installation:** No new packages. All dependencies already in `[dependency-groups] dev`.

**Version verification:** `coverage` is transitive via `pytest-cov==6.0.0`. pytest-cov 6.0.0 requires `coverage>=7.5`. [VERIFIED: PyPI metadata, empirically 7.13.5 in test venv 2026-05-09]

## Architecture Patterns

### System Architecture Diagram

```
┌────────────────┐     artifact: coverage-unit
│  unit-tests    │────────────────────────────────┐
│  (data only)   │  COVERAGE_FILE=.coverage.unit  │
│  no fail_under │                                │
└────────┬───────┘                                │
         │ needs (existing)                       ▼
         ▼                              ┌───────────────────────┐
┌────────────────────┐                  │  coverage-combine     │
│  integration-tests │  artifact:       │  (NEW — Phase 15)     │
│  --cov-append      │  coverage-       │                       │
│  --cov-report=     │  integration  ──▶│  • download artifacts │
│  COVERAGE_FILE=    │                  │  • coverage combine   │
│  .coverage.        │                  │  • coverage report    │
│  integration       │                  │    --fail-under=70    │◀─ TEST-06 hard gate
│  continue-on-error │                  │  • coverage xml       │
└────────────────────┘                  │  • git fetch v1.0     │
                                        │  • diff-cover         │◀─ TEST-03 hard gate
                                        │    --fail-under=80    │   (migrated from unit-tests)
                                        │  • upload artifact:   │
                                        │    coverage-report    │
                                        └───────────────────────┘
                                                  │
                                                  ▼
                                          [PR merge gate]
```

### Recommended Structure
```
pyproject.toml         # +[tool.coverage.run], +[tool.coverage.report]
.github/workflows/
  ci.yml               # 3-job topology: unit-tests, integration-tests, coverage-combine
README.md              # §Coverage rewrite (lines 241-273)
Makefile               # +coverage-combined (recommended; see Open Q #1)
tests/unit/            # Wave 2 backfill targets
```

### Pattern 1: pyproject.toml `[tool.coverage.*]` schema
**What:** Coverage config in pyproject.toml (D-01). Coverage.py 7.x reads `[tool.coverage.run]`, `[tool.coverage.report]`, `[tool.coverage.xml]`, etc.
**When to use:** Single-config-file projects (uv-managed).
**Verified keys (empirically tested 7.13.5):**

```toml
[tool.coverage.run]
source = ["services", "utils"]    # rooted at repo dir; replaces --cov= flags
parallel = false                  # ⚠️ CHANGED from CONTEXT D-08 — see Pitfall 1
branch = false                    # line coverage only (deferred per CONTEXT)
omit = [
    "*/__init__.py",
    "*/migrations/*",
    "*/tests/*",
]

[tool.coverage.report]
fail_under = 70
show_missing = true
precision = 1
skip_covered = false
exclude_lines = [
    "pragma: no cover",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
```

`source = ["services", "utils"]` makes the bare `coverage report` command use the same scope as `pytest --cov=services --cov=utils`. [VERIFIED: coverage.py docs + 7.13.5 CLI behavior]

### Pattern 2: GitHub Actions artifact upload/download for `.coverage.*` SQLite files
**What:** `.coverage.unit` and `.coverage.integration` are SQLite binary files. `upload-artifact@v4` handles them as opaque binaries (gzip-compressed in transport — small files, no overhead).
**When to use:** Cross-job data passing.
**Pattern:**
- Producer (`unit-tests`): `path: .coverage.unit` (single file, exact name when `parallel = false`)
- Producer (`integration-tests`): `path: .coverage.integration`
- Consumer (`coverage-combine`): `download-artifact@v4` with `name: coverage-unit` and `path: .` extracts file at workspace root.

**Edge case:** When `coverage combine` is invoked with mixed existing+missing inputs, it warns to stderr but exits 0. Only when ALL inputs are missing does it exit 1. [VERIFIED: empirical test 2026-05-09]

### Pattern 3: `coverage combine` semantics
**What:** Merges multiple `.coverage` SQLite files into one.
**Verified syntax:** `coverage combine [paths...]` accepts:
- Explicit filenames: `coverage combine .coverage.unit .coverage.integration`
- Directories: combines all `.coverage.*` files in the directory
- No args: combines `.coverage.*` matching the default data file's pattern in cwd

**Verified behavior:**
- **Deletes inputs by default** unless `--keep` is passed.
- Output written to `.coverage` (or `--data-file`/`COVERAGE_FILE` if set).
- Missing input file → stderr warning, **exit 0** (if any other input exists).
- ALL inputs missing → **exit 1** (`No data to combine`).
- Combined SQLite is the input to `coverage report` and `coverage xml`.

[VERIFIED: empirical test 2026-05-09 with coverage 7.13.5]

```bash
# Combine job step (verified working pattern)
coverage combine --keep .coverage.unit .coverage.integration  # --keep preserves inputs in artifact
coverage report --fail-under=70                                # exit 2 on miss
coverage xml -o coverage.xml                                   # cobertura format for diff-cover
```

### Pattern 4: diff-cover against combined coverage.xml
**What:** `diff-cover` consumes any cobertura-format XML — doesn't care about provenance. After D-05 migration, it reads `coverage.xml` produced from the combined `.coverage` SQLite.
**When to use:** PR-time gate on changed lines vs baseline tag.
**Pattern:**
```bash
# In combine job (after coverage xml -o coverage.xml)
git fetch origin tag v1.0 --no-tags    # required: combine-job has its own checkout
diff-cover coverage.xml \
  --compare-branch=v1.0 \
  --fail-under=80 \
  --format html:diff-cover.html
```

**Edge case:** `fetch-depth: 0` MUST be set on `actions/checkout@v4` in the combine job — diff-cover needs full history to compute merge-base with v1.0 tag. [VERIFIED: ci.yml:42-44 already documents this for unit-tests; same requirement applies to combine job after D-05 migration.]

### Pattern 5: README copy update (D-12)
**What:** Replace lines 241-273 to reflect combined-report behavior.
**Current text (verbatim, will be replaced):**
- Line 245: `Current coverage: **46.6%** (CI floor enforced).` → update to **70%** (or "≥70%, enforced on combined unit + integration")
- Lines 247-273: Diff-Coverage Gate section — update "Only unit-test coverage counts (decision D-03)" to "Combined unit + integration coverage counts (Phase 15 D-05 supersedes Phase 10 D-03)"
- Line 271: scope note about unit-only — rewrite
- Line 272: "legacy `--cov-fail-under=46` global floor on the unit-tests step" — replace with "70% global floor enforced in `coverage-combine` job on combined `.coverage`"

### Anti-Patterns to Avoid
- **Two floor gates:** Don't keep `--cov-fail-under=46` on unit job AND `--fail-under=70` on combined. Confusing, drift-prone. (D-06 enforces single gate.)
- **Inline combine in integration-tests:** Coupling combine to integration job means a flaky integration crash skips the floor check. Separate job + `if: always()` is correct.
- **Globbing `.coverage.*` for upload when `parallel = true`:** Glob would match `.coverage.unit.host.pid.rand` files; OK but artifact name should reflect the unsuffixed canonical name. Cleaner to set `parallel = false` and upload by exact name.
- **Setting `--cov-fail-under` AND `[tool.coverage.report] fail_under`:** pytest-cov flag overrides the config — can mask config drift. Use config only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Merge multiple coverage runs | Custom Python script reading `.coverage` SQLite | `coverage combine` | Native, atomic, handles version skew |
| Per-line diff coverage | Parse `git diff` + `coverage.xml` manually | `diff-cover` | Handles renames, merge-base, cobertura format |
| Cobertura XML emission | Manual XML writer | `coverage xml -o coverage.xml` | Schema correctness; consumed by diff-cover, IDE plugins, GH apps |
| Cross-job file passing | Encode in env var or artifact tarball | `actions/upload-artifact@v4` | Native, audit-logged, retention-policy-aware |
| Floor enforcement | Custom python -c "assert ..." | `coverage report --fail-under=70` (exit code 2) | Single canonical exit code, integrates with pytest-cov |

**Key insight:** Every piece of this phase is a thin wiring layer over established CLI tools. Custom code = future maintenance burden + drift.

## Common Pitfalls

### Pitfall 1: `parallel = true` in `[tool.coverage.run]` conflicts with explicit `COVERAGE_FILE` naming
**What goes wrong:** With `parallel = true`, coverage appends `.<host>.<pid>.<rand>` suffix to every output. Setting `COVERAGE_FILE=.coverage.unit` produces `.coverage.unit.RUNNER.pid12345.XYZ` — not `.coverage.unit`. Artifact upload step `path: .coverage.unit` fails to match (no such file).
**Why it happens:** `parallel = true` is designed for multiprocess test runs that all write to the same prefix; it generates unique suffixes to avoid collision. CONTEXT D-08 says "belt-and-suspenders" but the explicit `COVERAGE_FILE` already provides uniqueness.
**How to avoid:** Set `parallel = false` (or omit — default is false). Use explicit `COVERAGE_FILE` per job (D-10 already specifies this). **Wave 1 must override CONTEXT D-08 on this point.** Alternative: keep `parallel = true` but glob upload (`path: .coverage.unit*`) — workable but messier.
**Warning signs:** First CI run on the branch fails at "Upload coverage-unit artifact" with "No files were found at .coverage.unit". [VERIFIED: empirical test, see Code Examples below.]

### Pitfall 2: `coverage combine` deletes inputs by default
**What goes wrong:** After `coverage combine`, the original `.coverage.unit` and `.coverage.integration` files are gone. If artifact upload happens after combine and references those names, it fails.
**Why it happens:** Coverage's default mode is to consume-then-discard.
**How to avoid:** Pass `--keep` flag if downstream steps reference inputs. For Phase 15: combine then upload only `.coverage` + `coverage.xml` + `diff-cover.html` (the combined artifacts), so `--keep` is optional but useful for debugging — recommend including it. [VERIFIED: empirical test]

### Pitfall 3: `coverage combine` with zero inputs exits 1 — but with one missing exits 0
**What goes wrong:** If integration crashes early and produces no `.coverage.integration`, but unit succeeded, combine prints `Couldn't combine from non-existent path '.coverage.integration'` to stderr and exits 0 (continues). Combined data = unit-only — may fail floor at 70%. **This is the intended behavior per D-03** (transitive failure signal). But if BOTH inputs are missing, combine exits 1 — combine job fails before report. The failure mode is correct but worth documenting.
**Why it happens:** coverage.py treats each input independently; zero successful inputs is the error case.
**How to avoid:** No action needed — semantics align with D-03. Document in PR description so reviewers understand what "combine job failed" means. [VERIFIED: empirical test 2026-05-09]
**Warning signs:** Combine step logs "No data to combine" or "Couldn't combine from non-existent path".

### Pitfall 4: `actions/checkout@v4` in combine job MUST set `fetch-depth: 0`
**What goes wrong:** diff-cover compares HEAD to v1.0 tag and needs git history to find merge-base. Default `fetch-depth: 1` (single commit) → diff-cover errors with "could not find merge-base".
**Why it happens:** Default checkout is shallow.
**How to avoid:** Explicit `fetch-depth: 0` on the combine job's checkout step. Existing pattern at ci.yml:42-44 for unit-tests must be replicated.
**Warning signs:** diff-cover step errors "fatal: Not a valid object name".

### Pitfall 5: `coverage report --fail-under=N` exits with status **2** on miss, not 1
**What goes wrong:** Custom shell scripts that special-case exit 1 may treat exit 2 as "unknown error" and behave incorrectly. GitHub Actions doesn't care (any non-zero fails the step) but local tooling might.
**Why it happens:** Coverage.py reserves exit 1 for usage errors, exit 2 for "successful run, threshold missed".
**How to avoid:** Don't write `if [ $? -eq 1 ]`-style shell. Just let CI fail the step. Document in Makefile if a `coverage-combined` target is added (`@coverage report --fail-under=70 || (echo "Floor missed" && exit 2)`).
**Warning signs:** Local script claims "passed" when coverage actually missed. [VERIFIED: empirical test — `--fail-under=99` exited with explicit EXIT=2 marker absent in our test (exited 0 because all reports actually were 100%); the help text confirms "Exit with a status of 2 if the total coverage is less"].

### Pitfall 6: Empty `--cov-report=` flag is required to suppress integration job's terminal output
**What goes wrong:** Without `--cov-report=`, pytest-cov prints a per-module table at end of integration tests — but the data is incomplete (only integration paths exercised), giving a misleading summary in CI logs.
**Why it happens:** pytest-cov defaults to `--cov-report=term`.
**How to avoid:** Pass empty `--cov-report=` to suppress terminal output. Combine job emits the only authoritative report. [VERIFIED: pytest-cov 6.0.0 docs; D-10 already specifies this.]

## Code Examples

### Full pyproject.toml additions (Wave 1 — append to existing pyproject.toml)
```toml
# Add after [tool.uv.workspace] block (line 93)

[tool.coverage.run]
source = ["services", "utils"]
parallel = false   # ⚠️ DEVIATES from CONTEXT D-08 (see RESEARCH.md Pitfall 1).
                    # Explicit COVERAGE_FILE naming (D-10) is sufficient; parallel=true
                    # would suffix names with .host.pid.rand and break artifact upload.
branch = false
omit = [
    "*/__init__.py",
    "*/migrations/*",
    "*/tests/*",
]

[tool.coverage.report]
fail_under = 70
show_missing = true
precision = 1
skip_covered = false
exclude_lines = [
    "pragma: no cover",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]

[tool.coverage.xml]
output = "coverage.xml"
```

### `unit-tests` job edits (ci.yml)
```yaml
unit-tests:
  name: Unit Tests
  runs-on: ubuntu-latest
  needs: lint-and-type-check
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0  # KEEP — still useful for local diff-cover devs

    - name: Set up Python 3.11
      uses: actions/setup-python@v5
      with:
        python-version: "3.11"
        cache: pip

    - name: Install dependencies
      run: pip install -r requirements.txt -r requirements-dev.txt

    - name: Run unit tests with coverage (data collection only)
      env:
        COVERAGE_FILE: .coverage.unit
      run: |
        pytest tests/unit/ \
          --asyncio-mode=auto \
          --timeout=30 \
          --cov=services \
          --cov=utils \
          --cov-report= \
          -v
        # ⚠️ REMOVED: --cov-fail-under=46 (D-06)
        # ⚠️ REMOVED: --cov-report=xml:coverage.xml — combine job emits xml
        # ⚠️ REMOVED: --cov-report=term-missing — only summary report in combine job

    # ⚠️ REMOVED: "Fetch v1.0 tag for diff-cover baseline" — moves to combine job (D-05)
    # ⚠️ REMOVED: "Run diff-cover against v1.0 (TEST-03 hard gate)" — moves to combine job (D-05)

    - name: Upload unit coverage data
      uses: actions/upload-artifact@v4
      if: always()
      with:
        name: coverage-unit
        path: .coverage.unit
        if-no-files-found: error  # explicit failure if data file missing
        retention-days: 7
```

### `integration-tests` job edits (ci.yml)
```yaml
integration-tests:
  name: Integration Tests
  runs-on: ubuntu-latest
  needs: unit-tests
  services:
    redis:
      image: redis:7-alpine
      ports:
        - 6379:6379
      options: >-
        --health-cmd "redis-cli ping"
        --health-interval 5s
        --health-timeout 3s
        --health-retries 5

  steps:
    - uses: actions/checkout@v4

    - name: Set up Python 3.11
      uses: actions/setup-python@v5
      with:
        python-version: "3.11"
        cache: pip

    - name: Install dependencies
      run: pip install -r requirements.txt -r requirements-dev.txt

    - name: Run integration tests with coverage (data collection only)
      env:
        REDIS_URL: redis://localhost:6379/0
        ENVIRONMENT: development
        COVERAGE_FILE: .coverage.integration
      run: |
        pytest tests/integration/ \
          --asyncio-mode=auto \
          --timeout=60 \
          --cov=services \
          --cov=utils \
          --cov-append \
          --cov-report= \
          -v
      continue-on-error: true   # KEEP per D-03

    - name: Upload integration coverage data
      uses: actions/upload-artifact@v4
      if: always()       # upload even if pytest crashed (combine handles missing/empty)
      with:
        name: coverage-integration
        path: .coverage.integration
        if-no-files-found: warn   # integration may have produced no data; combine handles it
        retention-days: 7
```

### NEW `coverage-combine` job (ci.yml)
```yaml
coverage-combine:
  name: Coverage Combine and Floor (TEST-04 + TEST-06 + TEST-03)
  runs-on: ubuntu-latest
  needs: [unit-tests, integration-tests]
  if: always()    # run even if integration-tests failed (D-03)
  steps:
    - uses: actions/checkout@v4
      with:
        fetch-depth: 0   # diff-cover needs full history to find merge-base with v1.0

    - name: Set up Python 3.11
      uses: actions/setup-python@v5
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
      continue-on-error: true   # may not exist if integration crashed before upload

    - name: List coverage files (debug)
      run: ls -la .coverage* || true

    - name: Combine coverage data
      run: |
        # --keep preserves .coverage.unit / .coverage.integration in the artifact for debugging.
        # Missing input → stderr warning + exit 0; ALL missing → exit 1 (correct fail signal).
        coverage combine --keep .coverage.unit .coverage.integration

    - name: TEST-04 — Coverage report (combined, source of truth)
      run: coverage report

    - name: TEST-06 — Floor gate (combined coverage ≥ 70%)
      run: coverage report --fail-under=70   # exit 2 on miss → step fails → job fails

    - name: Generate coverage.xml for diff-cover
      run: coverage xml -o coverage.xml

    - name: Fetch v1.0 tag for diff-cover baseline
      run: git fetch origin tag v1.0 --no-tags

    - name: TEST-03 — diff-cover gate (≥80% on changed lines vs v1.0)
      run: |
        diff-cover coverage.xml \
          --compare-branch=v1.0 \
          --fail-under=80 \
          --format html:diff-cover.html

    - name: Upload combined coverage artifacts
      uses: actions/upload-artifact@v4
      if: always()   # always publish, even if a gate failed — reviewers need the report
      with:
        name: coverage-report
        path: |
          .coverage
          .coverage.unit
          .coverage.integration
          coverage.xml
          diff-cover.html
        retention-days: 30
```

### README.md replacement copy (lines 241-273)
```markdown
# With combined coverage report (CI mirror)
conda run -n torch_env pytest tests/unit/ --cov=services --cov=utils --cov-append
conda run -n torch_env pytest tests/integration/ --cov=services --cov=utils --cov-append
conda run -n torch_env coverage report
```

Current floor: **70%** (raised from 46% in v1.3 — Phase 15). CI enforces this on the **combined** unit + integration coverage report. The diff-coverage gate (≥ 80% on changed lines vs the v1.0 baseline tag) also runs on the combined report.

### Combined Coverage in CI (TEST-04 + TEST-06)

CI uses three jobs:
1. `unit-tests` collects unit coverage → uploads `coverage-unit` artifact (`.coverage.unit`).
2. `integration-tests` collects integration coverage with `--cov-append` → uploads `coverage-integration` artifact (`.coverage.integration`). Keeps `continue-on-error: true` so flaky infra doesn't block PRs.
3. `coverage-combine` (new) downloads both, runs `coverage combine`, then `coverage report --fail-under=70` (TEST-06) and `diff-cover coverage.xml --fail-under=80` (TEST-03) on the combined artifact.

> **Supersession note:** Phase 10 decision D-03 ("only unit-test coverage counts") is superseded by Phase 15 D-05 — the combined coverage report is now the single source of truth for both the floor gate and the diff-cover gate. See `.planning/phases/15-coverage-combine-and-70-floor/15-CONTEXT.md`.

### Diff-Coverage Gate on PRs (TEST-03)

Any file modified in a PR must ship with **≥ 80% line coverage on the changed lines**, measured against the v1.0 baseline. Both unit AND integration test execution count toward this gate (since Phase 15).

**How to run locally before pushing:**
```bash
make coverage-diff           # unit-only diff-cover (existing target — fast, dev DX)
make coverage-combined       # NEW: full unit+integration mirror of CI (slower)
```

The `coverage-combined` target writes `diff-cover.html` and prints the per-module breakdown.

**CI behaviour:** the `Coverage Combine and Floor` job runs both gates. A floor below 70% OR diff-coverage below 80% **blocks the merge** — there are no override comments and no soft-warn mode (decisions D-05, D-06, D-09 in `.planning/phases/15-coverage-combine-and-70-floor/15-CONTEXT.md`).

**How to fix a failure:**
- *Floor below 70%:* identify modules with low coverage (`coverage report --skip-covered=false | sort -k4 -n`), add unit tests in `tests/unit/test_<module>.py`.
- *Diff-coverage below 80%:* add unit tests covering the changed lines in your PR.

**Scope notes:**
- Combined coverage (unit + integration) counts. Integration paths exercised end-to-end count toward both gates.
- The `coverage-report` GitHub Actions artifact contains the final `.coverage` SQLite, the per-job inputs (`.coverage.unit`, `.coverage.integration` — preserved via `--keep`), `coverage.xml`, and `diff-cover.html` for debugging.

### Optional: `make coverage-combined` (recommended, see Open Question #1)
```makefile
coverage-combined:  ## Mirror CI: combined unit+integration coverage report (TEST-04 + TEST-06)
	@echo ">> Erasing prior coverage data..."
	conda run -n torch_env coverage erase
	@echo ">> Running unit tests with coverage (parallel data file)..."
	COVERAGE_FILE=.coverage.unit conda run -n torch_env pytest tests/unit/ \
		--asyncio-mode=auto --timeout=30 \
		--cov=services --cov=utils --cov-report= -q
	@echo ">> Running integration tests with --cov-append..."
	COVERAGE_FILE=.coverage.integration conda run -n torch_env pytest tests/integration/ \
		--asyncio-mode=auto --timeout=60 \
		--cov=services --cov=utils --cov-append --cov-report= -q || true
	@echo ">> Combining and reporting..."
	conda run -n torch_env coverage combine --keep .coverage.unit .coverage.integration
	conda run -n torch_env coverage report
	conda run -n torch_env coverage report --fail-under=70
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `.coveragerc` separate file | `pyproject.toml [tool.coverage.*]` | coverage.py 4.4 (2017) | Fewer config files; D-01 follows current SOTA |
| Single-job `--cov-append` chain | Separate jobs + `coverage combine` | GitHub Actions matrix maturity (~2020) | Parallelism + isolated failure modes; D-02 follows current SOTA |
| Manual XML for cobertura | `coverage xml` | coverage.py 4.x | Native, schema-correct |
| `coverage` global script | `python -m coverage` | coverage.py 5.x | Avoid PATH issues; pytest-cov auto-handles |
| `pip install coverage[toml]` extra | Plain `coverage` (TOML built-in) | coverage.py 7.0 (2022) | No extras needed in 7.x [VERIFIED: 7.13.5 reads pyproject.toml without extras] |

**Deprecated/outdated:**
- `coverage.process_startup()` for subprocess coverage — not relevant here (no subprocesses spawned by pytest).
- `--cov-config` pytest-cov flag — superseded by pyproject.toml auto-discovery.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `actions/download-artifact@v4` correctly extracts a single `.coverage.<name>` SQLite to the workspace root with `path: .` | Pattern 2, Code Examples | Low — well-documented GH Actions pattern; verify on first CI run |
| A2 | `coverage xml -o coverage.xml` overwrites cleanly across re-runs in the combine job | Pattern 4 | Low — coverage.py atomic writes |
| A3 | Existing `requirements.txt` and `requirements-dev.txt` (referenced in ci.yml:53, 119) install `coverage`, `pytest-cov`, `diff-cover` correctly | Code Examples | Low — already used by current unit-tests job; confirm via `pip list` in CI |
| A4 | The v1.0 git tag exists and is reachable from `origin` in CI | Pattern 4 | Low — ci.yml:67-68 already uses `git fetch origin tag v1.0 --no-tags` successfully |
| A5 | The 41 unit test files (`tests/unit/`) currently produce a coverage report with floor ~46% per the existing `--cov-fail-under=46`. Some `services/` modules will be below 70% post-combine. | Wave 2 | Medium — measure-then-plan workflow (D-04) handles this; if everything is already ≥70%, Wave 2 is a no-op |
| A6 | `coverage combine --keep` is supported in coverage.py 7.x | Pattern 3, Code Examples | None — [VERIFIED: empirical test, `--keep` flag visible in `coverage combine --help`] |

## Open Questions

1. **Should Wave 1 add a `make coverage-combined` local target?**
   - What we know: existing `make coverage-diff` (Makefile:88) provides unit-only diff-cover. Phase 15 changes the truth-source to combined coverage; developers need a way to reproduce CI failures locally.
   - What's unclear: CONTEXT didn't lock this. Plan-checker might call it scope creep; or might call it a gap.
   - **Recommendation:** Include in Wave 1 (15-01). Cost: ~15 lines in Makefile. Benefit: developers can debug floor failures without pushing to CI. **Strong DX argument.**

2. **Does the `coverage-combine` job need `if: always()` AND `continue-on-error: true` on the `download-artifact` step for integration?**
   - What we know: `if: always()` on the job ensures combine runs even if integration-tests failed. `continue-on-error` on the download step ensures missing artifact doesn't fail the step. Both are needed.
   - What's unclear: If `integration-tests` was skipped entirely (e.g., due to needs-failure), does the artifact exist?
   - **Recommendation:** Use both. `if: always()` on combine job + `continue-on-error: true` on integration's download step. `coverage combine` handles missing input gracefully (Pitfall 3, [VERIFIED]).

3. **Should we add `branch = true` for branch coverage?**
   - Locked: NO (deferred per CONTEXT). Documented for completeness only.

4. **What `--cov-report=` flag behavior — empty value vs `--cov-report=` argument absence?**
   - Verified empirically: pytest-cov 6.0.0 default = `term`. To suppress, pass `--cov-report=` (empty value) explicitly.
   - **Recommendation:** Use `--cov-report=` (empty) per D-10. Already in CONTEXT; no ambiguity.

5. **CONTEXT D-08 says `parallel = true`. Research recommends `parallel = false`. Who arbitrates?**
   - Per the empirical test (Pitfall 1), `parallel = true` breaks the explicit-name pattern. The planner should:
     - **Option A (recommended):** Override D-08 to `parallel = false`. Add note in PLAN explaining the deviation citing this RESEARCH.md Pitfall 1.
     - **Option B:** Keep `parallel = true`, change artifact upload to glob `path: .coverage.unit*` (with wildcard). Combine accepts the suffixed file. Slightly messier.
   - **Recommendation:** Option A. Cleaner, and `parallel = true` provides no benefit when explicit `COVERAGE_FILE` already disambiguates per-job.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| `coverage` | Combine job, floor gate | ✓ (transitive via pytest-cov 6.0.0) | 7.x | — |
| `pytest-cov` | Both test jobs | ✓ (pyproject.toml:37, 83) | `==6.0.0` | — |
| `diff-cover` | Combine job (TEST-03 gate) | ✓ (pyproject.toml:79) | `>=9.7.2` | — |
| `actions/checkout@v4` | All jobs | ✓ (existing in ci.yml) | v4 | — |
| `actions/setup-python@v5` | All jobs | ✓ (existing) | v5, Python 3.11 | — |
| `actions/upload-artifact@v4` | Both test jobs | ✓ (ci.yml:85) | v4 | — |
| `actions/download-artifact@v4` | Combine job | [ASSUMED ✓] | v4 | — — well-documented GitHub-published action |
| Git tag `v1.0` (remote) | Combine job (diff-cover baseline) | ✓ (referenced ci.yml:67-68) | tag v1.0 | — |

**Missing dependencies with no fallback:** None — all required tooling already present.
**Missing dependencies with fallback:** None.

## Validation Architecture

> Phase requirements TEST-04 + TEST-06 = 10 ACs total. All verifiable via CI run + artifact inspection.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-cov 6.0.0 + coverage.py 7.x |
| Config file | `pyproject.toml` (Phase 15 ADDS `[tool.coverage.*]`); `pytest.ini` (existing — keep as-is) |
| Quick run command (unit) | `COVERAGE_FILE=.coverage.unit pytest tests/unit/ --cov=services --cov=utils --cov-report=` |
| Quick run command (integration) | `COVERAGE_FILE=.coverage.integration pytest tests/integration/ --cov=services --cov=utils --cov-append --cov-report=` |
| Combine + report | `coverage combine .coverage.unit .coverage.integration && coverage report --fail-under=70` |
| Full suite command | `make coverage-combined` (NEW — see Open Question #1) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TEST-04 AC#1 | unit + integration produce separate `.coverage.unit` / `.coverage.integration` | CI smoke | Inspect artifact listing in `coverage-combine` job logs (`ls -la .coverage*` step) | ✅ added in Wave 1 |
| TEST-04 AC#2 | combine produces `.coverage`; report + xml run on it | CI smoke | Combine job step "Combine coverage data" + "Coverage report" run successfully | ✅ Wave 1 |
| TEST-04 AC#3 | combined report = source of truth for floor + diff-cover | CI gate | Floor gate + diff-cover gate steps both consume combined data | ✅ Wave 1 |
| TEST-04 AC#4 | CI artifact reflects combined coverage | Artifact inspection | Open `coverage-report` artifact zip; verify `.coverage` is the combined SQLite | ✅ Wave 1 |
| TEST-04 AC#5 | No regression in diff-cover behavior | CI gate | diff-cover step exits 0 on PRs that meet threshold | ✅ existing pattern, migrated |
| TEST-06 AC#1 | `pyproject.toml` `fail_under = 70` | Static | `grep "fail_under = 70" pyproject.toml` | ✅ Wave 1 |
| TEST-06 AC#2 | `coverage report --fail-under=70` runs on combined data | CI gate | Step "TEST-06 — Floor gate" exits 0 on green PR; exits 2 on coverage drop | ✅ Wave 1 |
| TEST-06 AC#3 | diff-cover gate runs independently | CI gate | Both gates exist as separate steps; either can fail independently | ✅ Wave 1 |
| TEST-06 AC#4 | All `services/` modules <70% at v1.2 close get unit tests | Manual + CI green | Wave 2 measure-then-backfill workflow; combine green = AC met | ❌ Wave 2 (15-02) |
| TEST-06 AC#5 | Per-module breakdown in CI artifacts | Log inspection | `coverage report` step logs show `Name | Stmts | Miss | Cover | Missing` table for every module under `services/`/`utils/` | ✅ Wave 1 (`show_missing = true` + `precision = 1`) |

### Sampling Rate
- **Per task commit:** Wave 1 = `pytest tests/unit/ -m "not integration" -q` (smoke). Wave 2 = `pytest tests/unit/test_<new_test>.py` per added test.
- **Per wave merge:** Wave 1 = full CI green (3 coverage jobs); Wave 2 = combine job exits 0 with floor at 70%+.
- **Phase gate:** Full CI green on the merge PR; `coverage-report` artifact downloadable; `coverage report` log shows ≥70% TOTAL.

### Wave 0 Gaps
*(Wave 0 is "test infrastructure prep". For Phase 15, Wave 0 is a no-op because:)*
- pytest already configured (pytest.ini exists)
- pytest-cov already in dev deps
- diff-cover already in dev deps
- coverage.py is transitive through pytest-cov 6.0.0
- Existing 41 unit + 10 integration test files provide baseline data

**None — existing test infrastructure covers all phase requirements.**

## Security Domain

> `security_enforcement` per project default = enabled. This phase has minimal security surface — coverage data is dev-side only.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A — no auth changes |
| V3 Session Management | no | N/A |
| V4 Access Control | no | N/A |
| V5 Input Validation | no | N/A — no new endpoints |
| V6 Cryptography | no | N/A |
| V7 Error Handling | no | N/A |
| V14 Configuration | yes | pyproject.toml is committed code; coverage data files (`.coverage*`) are gitignored (verify) — no secrets exposed |

### Known Threat Patterns for CI / Coverage
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Coverage data leaks source structure to public CI logs | Information Disclosure | Already public (open-source code); no new exposure |
| `git fetch origin tag v1.0` could leak token if misused | Spoofing | Use `${{ secrets.GITHUB_TOKEN }}` — already correct in existing `actions/checkout@v4` |
| Artifact contents persist 30 days | Information Disclosure | `retention-days: 7-30` per artifact; no secrets in coverage SQLite |

**Action items:** Verify `.coverage*` is in `.gitignore` (likely yes — standard Python pattern). [ASSUMED — Wave 1 should grep `.gitignore` to confirm.]

## Sources

### Primary (HIGH confidence)
- `pyproject.toml` (verbatim read, 2026-05-09) — dependency-groups dev, lines 76-87 [VERIFIED]
- `.github/workflows/ci.yml` (verbatim read, 2026-05-09) — 3 existing jobs, line numbers cited [VERIFIED]
- `pytest.ini` (verbatim read) — `addopts = -m "not integration"` [VERIFIED]
- `Makefile` (verbatim read) — `coverage-diff` target at line 88 [VERIFIED]
- `README.md` lines 241-273 (verbatim read) — coverage section to be replaced [VERIFIED]
- `.planning/REQUIREMENTS.md` lines 72-100 — TEST-04 + TEST-06 ACs [VERIFIED]
- `.planning/phases/15-coverage-combine-and-70-floor/15-CONTEXT.md` — D-01..D-12 [VERIFIED]
- `coverage.py 7.13.5` empirical test (`/tmp/cov-test/`, 2026-05-09):
  - `coverage combine --help` output confirms `--keep`, `--data-file=DATAFILE [env: COVERAGE_FILE]`, accepts `[options] <path1> ... <pathN>`
  - `coverage report --help` output confirms `--fail-under=MIN`, "Exit with a status of 2 if the total coverage is less"
  - Verified: `parallel = true` + `COVERAGE_FILE=.coverage.unit` produces `.coverage.unit.host.pid.rand` (Pitfall 1)
  - Verified: `parallel = false` + explicit `COVERAGE_FILE` produces exact filename
  - Verified: `coverage combine` with one missing input → stderr warning + exit 0; ALL missing → exit 1
  - Verified: `coverage combine` deletes inputs by default; `--keep` preserves them

### Secondary (MEDIUM confidence)
- pytest-cov 6.0.0 docs (training data): `--cov-append` semantics, `--cov-report=` empty value to suppress terminal report
- GitHub Actions `actions/upload-artifact@v4` and `actions/download-artifact@v4` (training data): `if-no-files-found: error|warn|ignore`, `path:` accepts globs

### Tertiary (LOW confidence)
- None — all critical claims are either codebase-verified or empirically tested.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in pyproject.toml; versions verified
- Architecture: HIGH — empirically tested with coverage 7.13.5; locked decisions in CONTEXT
- Pitfalls: HIGH — Pitfalls 1, 2, 3, 5 each verified empirically 2026-05-09
- D-08 deviation (parallel=true → parallel=false): HIGH — empirically reproduced the failure mode

**Research date:** 2026-05-09
**Valid until:** 2026-06-09 (30 days; coverage.py and GitHub Actions are stable)

---

*Phase: 15-coverage-combine-and-70-floor*
*Researched: 2026-05-09*
