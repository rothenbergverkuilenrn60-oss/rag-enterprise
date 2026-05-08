# Phase 10: Coverage Gate on New Code - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 10-coverage-gate-on-new-code
**Areas discussed:** Diff baseline ref, Coverage scope, CI placement, Failure strictness

---

## Area A — Diff Baseline Ref (REQ vs SC #2 conflict)

| Option | Description | Selected |
|--------|-------------|----------|
| A1) Split: CI vs `v1.0` tag, local vs `origin/master` | Honors REQ C-1 acceptance #1 (CI compares vs v1.0) AND SC #2 (local vs origin/master); each ref serves its use case | ✓ |
| A2) Both vs `v1.0` tag | Single source of truth; but local dev sees noise from already-merged v1.1 PRs since v1.0 | |
| A3) Both vs `origin/master` | Simpler mental model; but loses v1.1-milestone-delta precision once master receives v1.1 fixes | |

**User's choice:** A1
**Notes:** REQ acceptance #1 explicitly says "diff-cover against the v1.0 tag (`v1.0`)"; SC #2 explicitly says local uses "`git diff origin/master...HEAD`". The two refs are intentional, not contradictory — they target different use cases (milestone gate vs dev loop).

---

## Area B — Coverage Scope (which tests count)

| Option | Description | Selected |
|--------|-------------|----------|
| B1) Unit-only (existing pattern) | `unit-tests` job already runs `--cov`; append diff-cover to same job; integration job untouched | ✓ |
| B2) Merge unit + integration via `coverage combine` | Truer coverage for pipelines/controllers; cost: enable `--cov` in integration (+10-15min CI), artifact round-trip | |

**User's choice:** B1
**Notes:** v1.1 milestone is small; no v1.1 file is reachable only via integration tests. Trade accepted: integration-only-tested files show artificially low diff coverage and pressure the author to add unit tests — this is desirable, not a bug.

---

## Area C — CI Placement

| Option | Description | Selected |
|--------|-------------|----------|
| C1) Append step to existing `unit-tests` job | Reuses installed deps + on-disk `.coverage`; minimal YAML diff; shortest critical path | ✓ |
| C2) New `coverage-diff` job, depends on unit-tests | Cleaner step boundary; cost: artifact upload/download round-trip | |
| C3) New top-level workflow `coverage-diff.yml` | Most isolation; overkill for one gate | |

**User's choice:** C1
**Notes:** Adds 1-2 steps after the existing `Run unit tests with coverage` step. Modify (or extend) the existing `Upload coverage report` to include the HTML diff report.

---

## Area D — Failure Strictness

| Option | Description | Selected |
|--------|-------------|----------|
| D1) Hard block, no overrides | `--fail-under=80` blocks merge; no escape hatches | ✓ |
| D2) Hard block + per-file `# coverage:ignore-diff` override | Escape valve for genuinely-untestable files; cost: another contract to maintain | |
| D3) Soft warn (informational only) | Defeats the gate purpose; v1.0 already drifted under no-gate | |

**User's choice:** D1
**Notes:** REQ acceptance #3 reads strict ("Threshold-fail blocks merge"). v1.1 is small; rigour is cheap. If a v1.1 file genuinely cannot be unit-tested, refactor or accept the block.

---

## Claude's Discretion

- Exact line placement of the new step in `ci.yml`
- Modify existing `Upload coverage report` step vs add separate `Upload diff-coverage HTML` (planner picks cleanest YAML diff)
- Makefile target body — must match CI verdict; pin `coverage.xml` generation
- `git fetch --tags` handling in both CI and Makefile (v1.0 tag absence on fresh clones)
- Whether `diff-cover` lands in `requirements-dev.txt`, `pyproject.toml [dev]`, or both (match existing `pytest-cov` pattern)
- README / CONTRIBUTING.md doc update wording
- Adding `--cov-report=xml:coverage.xml` to the existing pytest invocation — likely required (diff-cover consumes XML, not `.coverage` binary)

## Deferred Ideas

1. Integration-test coverage merging (B2)
2. Per-file override comments (D2)
3. Soft-warn mode (D3) — explicitly rejected
4. Raising legacy 46 % global floor — v1.1 OOS
5. Replacing `diff-cover` with a GitHub Action — only if package becomes unmaintained
6. Coverage on `static/ui.html` JS (from Phase 9 deferred) — needs frontend test framework first, v1.2+
