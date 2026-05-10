# Phase 22: Per-Module 70% Coverage Lift - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-10
**Phase:** 22-per-module-70-coverage-lift
**Areas discussed:** Per-module enforcement mechanism, pipeline.py scope (Open Q#5), Test file organization, Wire-fixture extension for failure paths

---

## Per-module Enforcement Mechanism

### Q1: How should per-module ≥70% be enforced in CI?

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit per-module gates | 5 separate `coverage report --include=services/<mod>.py --fail-under=70` invocations in `coverage-combine` job. ~10 lines added to ci.yml. | ✓ |
| Single global fail-under=70 only | Rely on existing global `coverage report --fail-under=70` on combined data. No per-module CLI gate. | |
| Custom Python script | `scripts/check_per_module_coverage.py` parses `coverage json`, asserts each module ≥70%, exits non-zero. | |
| Config-based per-file thresholds | Native per-file `fail_under` (not in coverage.py 7.13). | |

**User's choice:** Explicit per-module gates
**Notes:** Locks D-01. Each module gates independently — no averaging mask.

### Q2: When per-module gates fail, what's the failure semantics in CI?

| Option | Description | Selected |
|--------|-------------|----------|
| Run all 5, fail at end | Bash loop with accumulated status OR `continue-on-error: true` + final assertion step. Dev sees all failing modules in one CI run. | ✓ |
| Fail-fast on first module | Each step is its own GA step; first non-zero stops the job. | |
| Report all modules in single coverage call | One `coverage report --include='<5 paths>' --fail-under=70` — but then `fail_under` checks aggregate. | |

**User's choice:** Run all 5, fail at end
**Notes:** Locks D-02. Avoids the alphabetically-first-failing-module-only feedback loop.

### Q3: Where does the per-module enforcement logic live?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline in ci.yml + Makefile target | 5 `coverage report` lines in CI; mirrored as `make coverage-per-module` for local dev. | ✓ |
| Inline in ci.yml only | CI only; devs read CI logs. | |
| Standalone Python script invoked from both | `scripts/check_per_module_coverage.py` reused. | |

**User's choice:** Inline in ci.yml + Makefile target
**Notes:** Locks D-03. Single source of truth + local reproducibility.

### Q4: Per-module gates run on which coverage data?

| Option | Description | Selected |
|--------|-------------|----------|
| Combined data only — in coverage-combine job | Carries forward Phase 15 D-05/D-06: gates against combined `.coverage`. | ✓ |
| Both unit-only + combined | Non-blocking warning in unit-tests job + authoritative gate in combine. | |
| Unit-only authoritative | Fastest; breaks Phase 15 'combined is single source of truth'. | |

**User's choice:** Combined data only — in coverage-combine job
**Notes:** Locks D-04. Carries CF-08 forward.

---

## pipeline.py Scope (Open Q#5)

### Q1: What's the pipeline.py coverage scope — whole file or partitioned?

| Option | Description | Selected |
|--------|-------------|----------|
| Whole-file ≥70% | Literal ROADMAP interpretation. All classes contribute to the same denominator. | ✓ |
| Whole-file ≥70% with IngestionPipeline excluded via `omit` | Tighter focus on v1.5 surface; subtle D-04 violation via comment-only edits. | |
| Per-class ≥70% | Each class independently; not natively supported by coverage.py. | |
| Whole-file ≥70%, IngestionPipeline tests added only if needed | Measure-then-plan for IngestionPipeline specifically. | |

**User's choice:** Whole-file ≥70%
**Notes:** Locks D-05. Closes STATE Q#5. No exclusions, no per-class breakdown.

### Q2: After SC1's prescribed targets land, how do we fill the remaining gap to 70%?

| Option | Description | Selected |
|--------|-------------|----------|
| Measure-then-add: cover Missing lines from `coverage report` | Wave 1 SC1; Wave 2 highest-impact Missing lines. Phase 15 D-04 precedent. | ✓ |
| Front-load IngestionPipeline error-branch tests | Pre-allocate Wave 2 for IngestionPipeline + QueryPipeline. | |
| Strict SC1-only — deepen SC1 branches if gap remains | No new targets; deepen existing ones. | |

**User's choice:** Measure-then-add
**Notes:** Locks D-06. Data-driven; matches Phase 15 D-04.

### Q3: How should pipeline.py work relate to the other 4 modules at plan-decomposition time?

| Option | Description | Selected |
|--------|-------------|----------|
| Own plan; other 4 each own plan = 5 parallel plans + setup | 22-00 setup, 22-01..22-05 modules, 22-06 finalize = 7 plans. | ✓ |
| Single plan covering all 5 modules | One PR; huge diff. | |
| Grouped: pipeline.py alone + remaining 4 | Wave-1 pipeline + Wave-2 four. | |
| You decide | Defer to gsd-planner. | |

**User's choice:** 5 parallel plans + setup/finalize plans
**Notes:** Locks D-07. 7 plans total.

### Q4: When does the per-module CI gate flip to fail-on-red?

| Option | Description | Selected |
|--------|-------------|----------|
| Last plan flips gates to hard-fail | 22-00 warning-only; 22-06 final flip in single locked-down PR. | ✓ |
| First plan flips gates to hard-fail (TDD-style) | 22-00 hard-fails immediately; CI red until each module ships. | |
| Hybrid — per-module incremental flip on each plan ship | Each module's plan flips its own gate. | |

**User's choice:** Last plan flips gates to hard-fail; 22-00 installs warning-only
**Notes:** Locks D-08. Avoids merge-order conflicts on ci.yml; CI stays green during the milestone window.

---

## Test File Organization

### Q1: Where do the new tests live — new files per module, or extend existing?

| Option | Description | Selected |
|--------|-------------|----------|
| Strict new file per module | 5 new `tests/unit/test_<mod>_coverage.py` files. Matches ROADMAP canonical-refs literal. | ✓ |
| Extend existing helper files | Add to existing `test_<mod>_helpers.py` etc. | |
| Hybrid — new file + extend existing only when natural overlap | Per-test judgment call. | |

**User's choice:** Strict new file per module
**Notes:** Locks D-09. Clean diff per plan, clean PR-to-requirement mapping.

### Q2: Where do shared mocks/fixtures live?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline per test file | Each `test_<mod>_coverage.py` defines its own `@pytest.fixture` stubs. | ✓ |
| Module-scoped conftest at `tests/unit/conftest.py` | Shared fixtures in top-level conftest. | |
| Per-module conftest at `tests/unit/coverage/conftest.py` + new subdir | New `tests/unit/coverage/` subdir. | |

**User's choice:** Inline per test file
**Notes:** Locks D-10. Zero coupling between coverage plans.

### Q3: Test function naming/organization convention within each new file?

| Option | Description | Selected |
|--------|-------------|----------|
| Function-style with grouping comments + parametrize for tables | `def test_<branch>` + `# --- group ---` + `@pytest.mark.parametrize`. | ✓ |
| Class-based grouping (one TestX class per source-class or feature) | `class TestX: def test_y(self):`. | |
| Strict 1-test-per-source-line-range with descriptive names | `test_pipeline_lines_469_527_swarm_synthesis_path()`. | |

**User's choice:** Function-style + grouping comments + parametrize for tables
**Notes:** Locks D-11. Matches existing project style.

### Q4: Should each new file declare its requirement traceability at the top?

| Option | Description | Selected |
|--------|-------------|----------|
| Module docstring with TEST-XX + SC reference | `"""Coverage tests for services/<mod>.py per TEST-XX (Phase 22 SC<N>). Targets: ...."""`. | ✓ |
| No file-level traceability — commit + plan file is enough | Implicit traceability via git history. | |

**User's choice:** Module docstring with TEST-XX + SC reference
**Notes:** Locks D-12. Cheap traceability.

---

## Wire-fixture Extension for Failure Paths

### Q1: How are LLM failure-path exceptions simulated in tests?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline `side_effect` raising the SDK exception | `monkeypatch.setattr` + raise `anthropic.RateLimitError(...)` etc. No new JSON fixtures. | ✓ |
| New failure-response JSON fixtures alongside happy-path | `rate_limit_429.json`, `overloaded.json`, `connection_error.json`. | |
| Hybrid — exceptions inline; JSON fixtures only for retry-then-success transcript | One `retry_then_success.json` for the happy retry path. | |

**User's choice:** Inline `side_effect` raising the SDK exception
**Notes:** Locks D-13. v1.2 happy-path fixtures stay reserved for happy-path only.

### Q2: How are 4 exception types × 2 clients factored?

| Option | Description | Selected |
|--------|-------------|----------|
| Parametrize over (client, exception_factory) pairs | ~6 parametrized tests per behavior dimension. | ✓ |
| Explicit one test per (client, exception) combination | 16 explicit tests. | |
| Per-client class with shared private helper | Class-based grouping with `_assert_retry_then_succeed` helper. | |

**User's choice:** Parametrize over (client_factory, exception_class) pairs
**Notes:** Locks D-14. Parametrize IDs use `(client, exception)` form for readable failure output.

### Q3: How are tenacity retry waits handled in failure-path tests?

| Option | Description | Selected |
|--------|-------------|----------|
| Monkeypatch tenacity wait to `wait_none()` per test | Real retry logic exercised; tests <1s. | ✓ |
| Patch `asyncio.sleep` / `time.sleep` at module level | Universal but fragile. | |
| Set `retry_count` / wait via test-only env vars | Requires PRODUCTION code change → violates D-04. | |

**User's choice:** Monkeypatch tenacity wait to `wait_none()` per test
**Notes:** Locks D-15. NO production-code env-var hooks.

### Q4: Same fixture pattern for the other 4 modules?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — inline side_effect uniformly across all 5 modules | Uniform pattern; no binary fixtures. | ✓ |
| Mostly yes, but extractor needs sample PDFs | Add small text_native.pdf + scanned.pdf binary fixtures. | |
| Defer fixture-vs-mock decision per-module to gsd-planner | Lock LLM-client D-13; let planner decide rest. | |

**User's choice:** Yes — inline side_effect uniformly across all 5 modules
**Notes:** Locks D-16. `is_scanned_pdf` 3-page heuristic mocked at PyMuPDF `doc.load_page(i).get_text()` seam; no real PDF binaries.

---

## Claude's Discretion

- Specific `httpx.Response` mock construction shape for SDK exception constructors — match SDK constructor requirements; planner consults Anthropic SDK source.
- Order of plans 22-02..22-05 within the parallel wave (alphabetical / smallest-gap-first / largest-gap-first) — no functional difference; planner picks.
- Specific `@pytest.fixture` names within each new file (e.g., `stub_planner` vs `mock_planner` vs `fake_planner`) — match house style observed in existing helper files.
- Whether 22-00 baseline measurement output goes to `22-BASELINE.md` (markdown) or `22-baseline-coverage.txt` (raw `coverage report` output) — markdown preferred; planner picks.
- Format of accumulated-status loop in CI (bash `set +e` + status array vs separate `continue-on-error` steps + final assert) — both satisfy D-02; planner picks based on ci.yml YAML clarity.
- Whether to add a `coverage report --include=services/<mod>.py --show-missing` log line per gate (verbose, useful in warning-only) or strict pass/fail only after 22-06 flip.
- Whether to keep existing `tests/unit/test_vector_store_filter_where.py` parametrize table after SC3's new table lands in `test_vector_store_coverage.py` (defense-in-depth vs deduplication) — recommend keep.

## Deferred Ideas

### To v1.6+
- Branch coverage activation (`branch = true`) — Phase 15 D-08 line-only carry-forward
- Mutation testing (`mutmut` / `cosmic-ray`) — TEST-07 deferred
- Coverage shields.io / codecov badge in README — Phase 15 D-11 out-of-scope
- Per-class coverage breakdown for pipeline.py — D-05 rejected; refactor split = future v1.6+ option
- Floor raise above 70% (e.g., 80%) — Phase 15 D-11 out-of-scope
- diff-cover threshold raise (≥80% → ≥90%)
- Coverage tracking dashboard

### Cross-cutting (not Phase 22)
- `.planning/codebase/TESTING.md` refresh — belongs in `/gsd-map-codebase`
- PyMuPDF AGPL license resolution — orthogonal carry-forward todo
