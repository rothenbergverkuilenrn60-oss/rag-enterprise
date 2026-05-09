# Phase 15: Coverage Combine and 70% Floor - Discussion Log

**Date:** 2026-05-09
**Phase:** 15 (TEST-04 + TEST-06)

## Gray Areas Selected

User selected ALL 4 gray areas:
- Coverage config location
- CI job topology for combine
- integration continue-on-error reconciliation
- Backfill scope (TEST-06 AC#4)

Plus 3 follow-up questions on diff-cover location, unit-step floor flag, and wave structure.

## Q&A Trail

### Round 1: Primary architecture

**Q1: Coverage config location?**
- A: pyproject.toml [tool.coverage.report] ← **Selected**
- B: .coveragerc

**Decision (D-01, D-08):** pyproject.toml. Matches uv-managed project pattern. One config file.
**Reason:** Existing `[dependency-groups] dev` already in pyproject.toml. No reason to add a second config file.

---

**Q2: CI job topology?**
- A: Artifact upload/download + new combine job ← **Selected**
- B: Single job with --cov-append
- C: Combine inline in integration-tests job

**Decision (D-02):** 3 jobs (unit + integration + new coverage-combine). Combine job needs both, downloads artifacts, runs combine + report + xml + diff-cover.
**Reason:** Cleanest separation. Explicit dependency graph. Preserves parallelism between unit and integration. Matches GitHub Actions idioms.

---

**Q3: integration continue-on-error vs floor gate?**
- A: Drop continue-on-error
- B: Keep continue-on-error; combine uses what's available ← **Selected**
- C: Tier with explicit fallback handling

**Decision (D-03):** Keep continue-on-error: true. Combine job runs `if: always()` and uses whatever .coverage.integration exists. If integration produces no data, combined coverage equals unit-only and may fail floor check — that's the correct signal.
**Reason:** Integration tests are flaky (Redis/pgvector/network deps); blocking PRs on infra flakes is unacceptable. Floor failure transitively signals integration crashes.

---

**Q4: Backfill scope (TEST-06 AC#4)?**
- A: Measure-then-plan in executor ← **Selected**
- B: Pre-scope modules in CONTEXT.md
- C: Bulk smoke tests for all service/

**Decision (D-04):** Wave 2 plan includes a measure-then-plan workflow: run combined coverage, identify modules <70%, sort by impact, backfill 1-2 unit tests each, iterate until floor passes.
**Reason:** Pre-scoping risks staleness (Phase 12/13/14 added new modules; baseline shifts). Bulk smoke tests don't guarantee 70% on complex-branch modules. Measure-driven backfill is precise and adaptive.

---

### Round 2: Follow-ups

**Q5: diff-cover gate location after combine?**
- A: Move to combine job (uses combined coverage.xml) ← **Selected**
- B: Keep in unit-tests job (unit-only diff-cover)

**Decision (D-05):** diff-cover migrates from unit-tests job to coverage-combine job. Consumes combined coverage.xml.
**Reason:** TEST-04 AC#3 says "Combined coverage report is the source of truth used by ... the diff-cover gate." Single source of truth. New code paths exercised only by integration tests now count toward diff-cover.

---

**Q6: Unit-step --cov-fail-under=46 flag?**
- A: Drop — floor only on combined ← **Selected**
- B: Keep as defensive guard

**Decision (D-06):** Drop --cov-fail-under from unit-tests pytest call. Floor check happens once, in coverage-combine job, on combined data.
**Reason:** Two gates with different thresholds (unit 46% + combined 70%) is misleading. Combined gate supersedes. Unit job is data-collection only.

---

**Q7: Wave structure?**
- A: 2 waves (plumbing → measure+backfill) ← **Selected**
- B: 3 waves (plumbing → measure → backfill)
- C: 1 wave (everything)

**Decision (D-07):** 2 plans:
- 15-01: Plumbing (pyproject.toml + ci.yml + integration --cov + diff-cover migration + README update)
- 15-02: Measure+backfill (depends_on 15-01)

**Reason:** Plumbing is mechanical and verifiable independent of backfill. Measure+backfill is iterative within one plan. 3 waves adds overhead without separation benefit.

---

## All 12 Decisions Locked (D-01 through D-12)

See `15-CONTEXT.md` `<decisions>` block. Categories:
- Coverage Configuration (D-01, D-08)
- CI Job Topology (D-02, D-05, D-06, D-10)
- Failure Policy (D-03, D-09)
- Backfill Workflow (D-04, D-12)
- Wave Structure (D-07)
- Out-of-Scope Reaffirmations (D-11)

## Out of Scope (Deferred)

- Branch coverage (line coverage only in v1.3)
- CI coverage badge (artifact + log lines satisfy AC#4)
- Mutation testing (TEST-07, v1.4+)
- Raising floor above 70%
- Backfill for utils/ and controllers/ (services/ only per AC#4 wording)
- Removing integration-tests continue-on-error

## Next Action

Run `/gsd-plan-phase 15` to research + plan Phase 15.
