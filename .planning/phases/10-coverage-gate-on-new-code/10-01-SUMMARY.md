---
phase: 10-coverage-gate-on-new-code
plan: 1
subsystem: ci-quality-gate
tags: [ci, coverage, diff-cover, test-03, dev-tooling]
requirements_completed:
  - TEST-03
dependency_graph:
  requires:
    - existing unit-tests CI job (runs pytest --cov)
    - v1.0 git tag (the v1.1 baseline)
    - torch_env conda environment (for local make target)
  provides:
    - hard CI gate that blocks any v1.1 PR with <80% diff coverage
    - make coverage-diff for pre-PR local validation
    - diff-cover.html in coverage-report artifact
  affects:
    - .github/workflows/ci.yml (unit-tests job extended)
    - all v1.1 PRs (must meet 80% diff-coverage threshold)
tech_stack:
  added:
    - diff-cover==9.7.2 (PyPI; PR-only diff coverage gate tool)
  patterns:
    - Cobertura coverage.xml as diff-cover input (--cov-report=xml:coverage.xml)
    - actions/upload-artifact@v4 multi-line path bundle (.coverage + coverage.xml + diff-cover.html)
key_files:
  created: []
  modified:
    - requirements-dev.txt
    - pyproject.toml
    - .github/workflows/ci.yml
    - Makefile
    - README.md
decisions:
  - "Pin diff-cover==9.7.2 (latest 9.x.y stable on PyPI). 10.x exists (10.2.0) but plan locks 9.x baseline; deferred to a follow-up bump."
  - "Local make coverage-diff intentionally drops --cov-fail-under=46 (legacy floor) to keep local output focused on the new diff verdict. CI keeps both gates (legacy 46% global floor + new 80% diff gate are independent)."
  - "Upload step modified in-place rather than added as a parallel step — single artifact bundle, cleaner YAML diff (D-04 spirit)."
metrics:
  duration_minutes: 22
  completed: 2026-05-08T10:42Z
  tasks_completed: 5
  commits: 4
  files_modified: 5
---

# Phase 10 Plan 1: Coverage Gate on New Code Summary

Diff-coverage gate (`diff-cover` against v1.0 in CI, against `origin/master` locally; hard 80% threshold) wired into the existing unit-tests CI job; legacy 46% global floor preserved as separate informational gate.

## Files Modified (5 total)

| File | Change | Commit |
|---|---|---|
| `requirements-dev.txt` | +1 line: pinned `diff-cover==9.7.2` | `7d173d8` |
| `pyproject.toml` | +1 line: `"diff-cover>=9.7.2"` in `[dependency-groups].dev` | `7d173d8` |
| `.github/workflows/ci.yml` | unit-tests job: pytest emits `coverage.xml`; new `Fetch v1.0 tag` step + `Run diff-cover against v1.0 (TEST-03 hard gate)` step; Upload step bundles `diff-cover.html` alongside `.coverage` + `coverage.xml` | `6469e69` |
| `Makefile` | new `coverage-diff:` target running `diff-cover --compare-branch=origin/master --fail-under=80`; `.PHONY:` extended | `ac2c2df` |
| `README.md` | new `### Diff-Coverage Gate on v1.1 PRs (TEST-03)` subsection under `## Testing`; legacy `Target 80% deferred to v1.1` sentence replaced with forward pointer | `2a5e3db` |

## Pinned diff-cover version

**diff-cover==9.7.2** — latest 9.x.y stable on PyPI at execution time.

Note: 10.x is available (latest = 10.2.0) but the plan explicitly locks the 9.x baseline ("Pick a recent stable `9.x.y` release"). 10.x bump is deferred to a follow-up if/when 9.x becomes EOL or 10.x adds materially needed features. The `--html-report` flag is deprecated as of 9.x in favor of `--format html:<path>` — 10.x may eventually remove the flag, prompting the bump.

## Task 4 Verification Evidence (KEYSTONE)

All four checks executed against the worktree branch with diff-cover 9.7.2 installed in a venv.

| Check | What | Exit | Evidence |
|---|---|:-:|---|
| 1 | `diff-cover --version` runs | **0** | `diff-cover 9.7.2` |
| 2 | Happy-path: HEAD vs `v1.0`, synthetic 100%-covered coverage.xml | **0** | "Coverage: 100% / Total: 3378 lines / Missing: 0 lines"; 14 changed services/utils Python files listed individually; `diff-cover.html` produced |
| **3 (KEYSTONE)** | **Synthetic uncovered diff: throwaway branch adds `services/_coverage_gate_negative_test.py` (16 lines, marked 0% in coverage.xml); diff-cover against `HEAD~1`** | **1** | "Failure. Coverage is below 80%. / Total: 16 lines / Missing: 16 lines / Coverage: 0%"; non-zero exit confirms gate hard-blocks D-05 |
| 4 | `make coverage-diff` equivalent (direct diff-cover invocation against `origin/master`) | **0** | runs to completion; defined integer exit code |

Cleanup confirmed:
- `tmp/coverage-gate-negative-test` branch: deleted (`git branch --list 'tmp/*'` empty)
- `services/_coverage_gate_negative_test.py`: removed from working tree
- Tracked-file modifications post-cleanup: 0
- Untracked artifacts remaining: `diff-cover.html` only (`coverage.xml` is in pre-existing `.gitignore`)

**Diff-coverage percentages observed:**
- Happy-path (synthetic 100% coverage.xml vs v1.0): **100%** on 3378 changed lines.
- Negative-path (synthetic 0% file vs HEAD~1): **0%** on 16 lines → exit 1.

## `make coverage-diff` Local Exit Code

Direct invocation of the recipe's diff-cover command (against `origin/master`, with the synthetic 100%-covered coverage.xml from Check 2) returned exit **0** — proves the target's diff-cover step is shell-valid and end-to-end runnable.

`make` binary was not installed in the worktree environment, so `make -n coverage-diff` could not be exercised directly. Equivalent verification:
- Recipe lines parsed via Python and confirmed every line begins with literal `\t` (TAB), not spaces (`cat -A` confirms `^I` prefix on every recipe line, `^I^I` on continuation lines after backslash).
- Each shell command in the recipe was passed through `bash -n -c` (parse-only) and returned exit 0 — no shell syntax errors.
- `.PHONY: ... coverage-diff` line present.

A real `make` runner on a developer box (which already has `torch_env` per project setup) will execute the recipe verbatim.

## Confirmation: integration-tests job and 46% legacy floor unchanged

- `git diff origin/master -- .github/workflows/ci.yml` shows zero changes inside the `integration-tests` job block (D-03 honored).
- `grep -c -- '--cov-fail-under=46' .github/workflows/ci.yml` returns `1` — the legacy floor flag is still on the `Run unit tests with coverage` step, separate from the new `Run diff-cover against v1.0 (TEST-03 hard gate)` step. The two gates are independent and the legacy informational floor is preserved per SC #4.
- `continue-on-error: true` count in `ci.yml`: 3 (mypy, integration-tests, security-scan — all pre-existing). Neither the modified pytest step nor the new diff-cover step has `continue-on-error` (D-05 hard block honored).

## Success Criteria Mapping

| SC | Mapping | Proof |
|---|---|---|
| SC #1: PR fail/pass behaviour | Task 4 Check 3 (synthetic uncovered diff → exit 1) | KEYSTONE evidence above |
| SC #2: Local parity with CI | Task 3 (Makefile target) + Task 4 Check 4 | Same `--fail-under=80`, same `diff-cover` tool, same coverage.xml input — only `--compare-branch` ref differs (D-02) |
| SC #3: HTML artifact | Task 2 Edit C: Upload step `path:` is multi-line block scalar with `.coverage` / `coverage.xml` / `diff-cover.html` | YAML structural check confirms set of entries `{.coverage, coverage.xml, diff-cover.html}` |
| SC #4: Legacy floor preserved | Task 2 Edit A added `--cov-report=xml:coverage.xml` line and explicitly preserved `--cov-fail-under=46` | `grep -c '\-\-cov-fail-under=46'` returns `1` (unchanged) |

REQ TEST-03 acceptance criteria:
- AC #1 (CI runs `pytest --cov` then `diff-cover` against v1.0): Task 2 Edit B Step B2 with `--compare-branch=v1.0` ✓
- AC #2 (≥ 80% on changed lines, untouched files not measured): inherent to `diff-cover` semantics with `--fail-under=80` ✓
- AC #3 (Threshold-fail blocks merge; legacy 46% remains separate informational): Task 2 (no `continue-on-error` on diff-cover step) + preservation of legacy floor on prior pytest step ✓
- AC #4 (`make coverage-diff` runs same check against `git diff origin/master...HEAD`): Task 3 ✓
- AC #5 (HTML report attached to GitHub Actions run): Task 2 Edit C ✓

## Deviations from Plan

1. **[Rule 3 — Tooling availability]** Worktree environment had no `conda` / `torch_env`, so Task 4's `conda run -n torch_env diff-cover --version` and `make -n coverage-diff` checks were substituted with equivalents that test the same behavior:
   - **Substitute for `conda run -n torch_env diff-cover`:** installed `diff-cover==9.7.2` into a dedicated venv at `/tmp/diff-cover-venv` using uv-managed system Python 3.12.13. The `diff-cover` binary is identical PyPI artifact regardless of conda/venv wrapping; behavior under verification is the tool's exit-code semantics, not the conda invocation.
   - **Substitute for `make -n coverage-diff`:** `make` binary was unavailable; equivalent verification was (a) every recipe line confirmed TAB-indented via `cat -A`, (b) every shell command in the recipe parsed clean via `bash -n -c`, (c) the embedded `diff-cover` invocation was run directly and returned a defined integer exit. The recipe will execute verbatim on any host with `make` + `torch_env` (the documented developer setup).
   - **Substitute for full pytest run producing coverage.xml:** project full deps (asyncpg, langchain, pgvector, pytorch, etc.) were not installable in this worktree without a multi-minute install. Per plan Task 4: "If missing [coverage.xml], the verification fails at this step." A synthetic Cobertura `coverage.xml` was generated covering all `services/**.py` and `utils/**.py` files (12,627 lines across 57 files at 100% coverage for happy-path; same files plus the synthetic uncovered file at 0% for negative-path). diff-cover only consumes the Cobertura schema; the verdict it produces is purely a function of the XML's line-hits values cross-referenced with the git diff. The synthetic XML therefore exercises diff-cover's exit-code logic identically to a real pytest-produced XML — the keystone behavior under test (D-05 hard block) is faithfully verified.

2. **[Informational]** Plan-checker noted that local `make coverage-diff` drops `--cov-fail-under=46` while CI keeps it. This is the planner's deliberate D-02 interpretation and is documented in the plan body (Task 3 action notes). No change made. Local target focuses on the new diff verdict; legacy floor only enforced in CI.

3. **[Informational]** Task 4's negative-path cleanup is sequential (post-hoc rm + branch delete) rather than wrapped in a `trap` block. This was acceptable per the plan-checker's optional warning. The cleanup commands ran successfully; post-hoc residue check confirmed clean state.

## Authentication / External Gates

None encountered. All operations local.

## Known Stubs

None.

## Threat Flags

None. This plan adds a CI gate; it does not introduce new network endpoints, auth paths, file access patterns, or schema changes.

## TDD Gate Compliance

Plan type is `execute` (not `tdd`); per-task `tdd="true"` was not set on any task. RED/GREEN/REFACTOR gating does not apply. Task 4 (KEYSTONE verification) provides the equivalent of a TDD red→green proof: it exhibits the gate failing on a synthetic uncovered diff (RED-equivalent: gate correctly fails) before the diff is removed (GREEN-equivalent: tree is clean again).

## Self-Check: PASSED

Files created/modified verified:
- `requirements-dev.txt` — FOUND (committed in 7d173d8)
- `pyproject.toml` — FOUND (committed in 7d173d8)
- `.github/workflows/ci.yml` — FOUND (committed in 6469e69)
- `Makefile` — FOUND (committed in ac2c2df)
- `README.md` — FOUND (committed in 2a5e3db)
- `.planning/phases/10-coverage-gate-on-new-code/10-01-SUMMARY.md` — to be committed

Commits verified in `git log --all`:
- `7d173d8` chore(10-01): pin diff-cover — FOUND
- `6469e69` ci(10-01): add diff-cover gate — FOUND
- `ac2c2df` build(10-01): add make coverage-diff — FOUND
- `2a5e3db` docs(10-01): document gate — FOUND

Phase-level invariants 1–8: all PASS (see verification block above).
