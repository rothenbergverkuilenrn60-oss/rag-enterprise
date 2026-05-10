---
phase: 22-per-module-70-coverage-lift
plan: "00"
subsystem: coverage-infrastructure
tags: [coverage, ci, infrastructure, baseline]
dependency_graph:
  requires: []
  provides: [per-module-ci-gates, coverage-per-module-makefile, 22-BASELINE.md]
  affects: [.github/workflows/ci.yml, Makefile]
tech_stack:
  added: []
  patterns: [coverage-report-include, set+e-run-all-then-fail, uv-run-coverage]
key_files:
  created:
    - .planning/phases/22-per-module-70-coverage-lift/22-BASELINE.md
  modified:
    - .github/workflows/ci.yml
    - Makefile
decisions:
  - "D-01/D-04: Per-module gates run on combined .coverage via `coverage report --include=` loop in coverage-combine job"
  - "D-08: warning-only (exit 0) at 22-00; plan 22-06 removes exit 0 to activate hard-fail"
  - "D-03: Makefile target uses `uv run coverage` (not conda) — only runnable toolchain on this machine"
  - "D-02: run-all-then-fail via set +e + status accumulation, single step"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-10T14:10:00Z"
  tasks_completed: 3
  tasks_total: 3
  files_created: 1
  files_modified: 2
---

# Phase 22 Plan 00: CI Gates + Baseline — Summary

Warning-only per-module coverage CI gates, local Makefile mirror, and pre-Phase-22 coverage snapshot installed so plans 22-01..22-05 have concrete backfill budgets and gate integration is verified before test work begins.

## Baseline Numbers Per Module

| Module | Stmts | Miss | Cover% | Gap to 70% |
|--------|-------|------|--------|------------|
| `services/pipeline.py` | 606 | 205 | 66.2% | ~23 stmts (close) |
| `services/generator/llm_client.py` | 364 | 171 | 53.0% | ~62 stmts |
| `services/vectorizer/vector_store.py` | 190 | 106 | 44.2% | ~49 stmts |
| `services/retriever/retriever.py` | 307 | 201 | 34.5% | ~109 stmts |
| `services/extractor/extractor.py` | 306 | 192 | 37.3% | ~94 stmts |

`pipeline.py` improved from the CONTEXT.md table (42.7% → 66.2%) due to Phases 19–21 tests.
The 5 plans 22-01..22-05 still ship their SC-prescribed branches per ROADMAP (gap size does not gate plan execution).

## CI Step Location + Warning-Only Confirmation

Added step **"Phase-22 per-module coverage floor (warning-only at 22-00; flips to hard-fail at 22-06)"** at line 176 of `.github/workflows/ci.yml`, inside the `coverage-combine` job:
- Position: AFTER `TEST-06 — Floor gate` (line 173), BEFORE `Generate coverage.xml for diff-cover` (line 207)
- Mechanism: `set +e` + bash for-loop over 5 modules + status accumulation
- Terminal `exit 0` ensures CI stays green throughout 22-01..22-05 (D-08)
- GitHub Actions `::warning::` annotations emitted for any module below 70%
- Plan 22-06 removes `exit 0` to activate hard-fail semantics

## Makefile Target Invocation

```bash
# Populate .coverage first:
uv run pytest tests/unit/ --asyncio-mode=auto --timeout=30 \
  --cov=services --cov=utils --cov-report= -q

# Then run hard-fail gate:
make coverage-per-module
```

Hard-fail: exits non-zero if any of the 5 modules misses 70%. Uses `uv run coverage` (not `conda run`) — the only runnable toolchain on this machine.

## Wave-2 Backfill Reference

Plans 22-01..22-05 reference `.planning/phases/22-per-module-70-coverage-lift/22-BASELINE.md` for the per-module Missing line ranges. The baseline was measured from combined `.coverage` (unit + integration); integration collection failed at baseline time (PermissionError on test collection) so combined = unit-only for this snapshot.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

### Deferred Items

The existing `coverage-combined` Makefile target (lines 123-137) uses `conda run -n torch_env` which is non-functional on this machine. Plan instructions explicitly defer fixing this to a follow-up note in 22-06-SUMMARY (out of scope for 22-00 to keep the PR tight).

## Known Stubs

None — this plan produces infrastructure only (ci.yml + Makefile + BASELINE.md), no application logic.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. Additions are CI configuration and local Makefile targets only. T-22-00-03 (DoS via gate steps) mitigated by `set +e` + `exit 0` per plan threat model.

## Self-Check: PASSED

- `.planning/phases/22-per-module-70-coverage-lift/22-BASELINE.md` exists: FOUND
- `.github/workflows/ci.yml` YAML valid: PASS
- `coverage-combine` job step ordering (TEST-06 → Phase-22 gate → Generate xml): PASS (lines 173/176/207)
- Makefile `coverage-per-module` target: FOUND (line 140)
- `uv run coverage` in Makefile: FOUND
- CF-01 (zero production code changes): PASS — `git diff --stat services/ utils/ config/` shows no changes
- All 5 module paths in both ci.yml and Makefile: CONFIRMED
- Commits: ffa4138 (BASELINE), 231a936 (ci.yml), f141eee (Makefile)
