# Phase 31 — Event-Loop Leak Sweep — Context

**Phase:** 31
**Milestone:** v1.9 Hardening Round 3
**Requirements:** EVT-02
**Status:** Discussed 2026-05-18 — ready for `/gsd-plan-phase 31`

## Phase Goal (from ROADMAP)

Eliminate residual module-level singleton-bound-to-import-time-loop failures so the PG-host integration suite reports zero "different loop" errors and `_SINGLETON_INVENTORY` reaches authoritative coverage. Zero new user-facing capabilities — pure test infra polish closing Phase 30 EVT-01 partial/superseded work.

## Decisions Captured

### D-01: Enumeration discovery pattern

**Decision:** Broader regex catching all 3 known asyncio event-loop error shapes — not just Phase 30's narrow shape.

```bash
uv run pytest -m integration --uses-redis -v 2>&1 \
  | grep -E "(no current event loop|attached to a different loop|got Future.*attached)" \
  | sort -u > /tmp/31-00-leak-sites.txt
wc -l /tmp/31-00-leak-sites.txt
```

**Three error shapes caught:**
1. `RuntimeError: no current event loop` — Phase 30 baseline; surfaces when `asyncio.get_event_loop()` runs with no running loop
2. `RuntimeError: ... attached to a different loop` — asyncpg / aiohttp resource created on Loop A, accessed on Loop B
3. `got Future <Future ...> attached to a different loop` — `asyncio.gather` / `wait` mixing futures across loops

**Rationale:**
- Phase 30 EVT-01 used shape 1 only → ~4 sites surfaced + Plan 30-01 was superseded. Shapes 2+3 are more common with asyncpg-backed services (memory, audit, knowledge), which are the primary residual leak surface.
- Broader regex aligns enumeration with the underlying root cause (any loop-binding violation), not a single error-message variant.
- Acceptance gate (D-02) is zero-error not "+N sites" — broader regex risks finding more sites, but D-02 makes that descriptive not prescriptive.

**Rejected:**
- Phase 30 baseline-only (shape 1) — known to undercount; led to Plan 30-01 supersession.
- `grep RuntimeError` catch-all — noisier; catches unrelated `RuntimeError` (already-closed pool, etc.).

### D-02: Acceptance gate priority

**Decision:** Zero-error gate dominates the +14-site heuristic. Site count is descriptive, not prescriptive.

**Pass criteria:**
1. **HARD (must hold):** `uv run pytest -m integration --uses-redis -v` on PG host reports zero matches against the D-01 regex (filtered against the pre-existing failure list from D-04 — only event-loop errors count).
2. **DESCRIPTIVE (no minimum):** `_SINGLETON_INVENTORY` grows from 34 to `34 + N` where N = actual leak count surfaced. Could be 5, 14, or 20 — whatever the truth is.
3. **DESCRIPTIVE:** `_SINGLETON_INVENTORY` lint (`tests/unit/test_singleton_inventory_complete.py`) passes with the new count.

**Rationale:**
- Phase 30 set precedent: "execute-time enumeration is truth; estimate is just a starting point." If enumeration shows ≠ estimate, the estimate is wrong, not the gate.
- A hard count gate risks padding (adding speculative entries to hit 48) or scope creep (chasing every RuntimeError to hit count).
- Zero-error gate is observable, falsifiable, and matches REQUIREMENTS.md EVT-02 acceptance bullet #1.

**Rejected:**
- Site-count gate (hard +14) — rigid; risks scope creep or padding.
- Intersection (zero-errors AND count ≥ 48) — strictest; may force speculative entries if real leaks are fewer.

### D-03: Plan structure

**Decision:** Single plan 31-00. All steps in one plan: enumerate → triage → migrate factory sites → write per-test fixtures for outliers → re-run → verify zero-error.

| Plan | Wave | Type | Requirement | Files (approximate) |
|------|------|------|-------------|---------------------|
| 31-00 | 1 | execute | EVT-02 | `tests/factories/app.py` (extend `_SINGLETON_INVENTORY`) + ~N integration test files (per-test event_loop fixtures for non-factory sites) |

**Rationale:**
- Matches Phase 30 single-plan cadence for EVT-class work.
- Site count (~10 estimated, could be 5–20 per D-02) is below the threshold that warrants wave-splitting.
- Single SUMMARY captures full traceability without inter-plan handoff overhead.
- Audit trail preserved via atomic git commits within the plan (one commit per inventory addition or fixture insertion).

**Rejected:**
- Two-plan split (enumerate + remediate) — handoff overhead exceeds value for site count this small; Phase 30 had identical decision.
- Three-plan split (enumerate + remediate + verify) — overkill.

### D-04: Enumeration failure handling

**Decision:** Filter-then-enumerate. Run full PG-host integration suite; grep ONLY for event-loop error shapes (D-01 regex); pre-existing failures stay in test output but enumeration regex filters them out at parse time. Pre-existing failures noted in `31-00-SUMMARY.md` as known but NOT blocking Phase 31.

**Known pre-existing failures inherited from v1.8 close** (9 failed / 3 errors / 1 skipped triaged 2026-05-17):

| Category | Failure surface | Routed to |
|---|---|---|
| Real-LLM tests | `test_*real_llm*` | Out of scope (env-dependent) |
| Perf benchmarks | `test_*benchmark*` | Out of scope (perf suite) |
| UI sentinel drift | `test_ui_static::test_ui_static_serves_html` | Phase 34 (TEST-11) |
| Schema drift | `test_pipeline_load_context_audit::test_no_v1_5_regression` | Phase 34 (TEST-10) |
| Real-embedder requirements | autouse-mock-incompatible tests | Phase 33 (TEST-08 opt-out marker) |

**Rationale:**
- Triage-first would block Phase 31 on Phase 33+34 work — scope inversion.
- Exclude-list deselect is fragile (rots as test names drift).
- Filter-at-parse is robust: even if a pre-existing failure regresses, the enumeration regex stays targeted on event-loop signal.
- The 9+3 failures don't emit event-loop error messages (they emit ValidationError, FileNotFoundError, AssertionError on title sentinel, etc.) — they're invisible to D-01 regex by construction.

**Rejected:**
- Triage-first — scope creep into Phase 33+34.
- `pytest --deselect <list>` — deselect rot; fragile.

## Carry-Forward Decisions (still in force)

| Decision | Source | Why it matters going forward |
|----------|--------|------------------------------|
| `create_app()` factory pattern + `_SINGLETON_INVENTORY` lint | v1.7 Phase 27 TD-02 | EVT-02 grows inventory; lint must pass post-grow |
| Factory-default; outliers get per-test `event_loop` fixture | v1.8 Phase 30 30-CONTEXT D-EVT-01 | Same convention; per-site choice documented in 31-00-SUMMARY |
| Enumeration is execute-time, NOT context-time | v1.8 Phase 30 D-EVT-01 | This CONTEXT.md does NOT enumerate; Plan 31-00 Task 0 does |
| TDD relaxed for `type: execute` (no behavior change) | v1.8 Phase 30 30-CONTEXT D-TDD | Verification = suite green + lint pass + zero-error grep |
| Mock at consumer path (`services.<mod>.<dep>`) not source | v1.3 Phase 13+15 | Any new mock/fixture in Phase 31 follows |
| `diff-cover ≥ 80%` on touched files | v1.1 Phase 10 TEST-03 | Phase 31 touched files must clear |
| Combined coverage `--fail-under=70` global floor | v1.3 Phase 15 / v1.5 Phase 22 | Must not regress |
| `# type: ignore[code]  # why:` silence convention; 25 violations cap | v1.8 Phase 30-03 / v1.9 Phase 32 | If Phase 31 fixtures introduce silences, they count against Phase 32's drain — keep zero introductions if possible |
| `uses_redis` marker active | v1.7 Phase 27 TD-06 | Enumeration runs `pytest -m integration --uses-redis` |
| `tests/integration/conftest.py` autouse mocks embedder + reranker | v1.8 Phase 30-02 | Plan 31-00 must NOT regress this; opt-out marker is Phase 33 TEST-08 |
| INSERT-ONLY `audit_log` invariant | v1.0 Phase 2 | Not touched |
| `BaseTool` ABC + `AGENT_TOOL_ALLOWLIST` constant | v1.4 Phase 17 | Not touched |

## Codebase Anchors

| Asset | Path / Line | Why it matters |
|-------|-------------|----------------|
| `_SINGLETON_INVENTORY` (34 entries) | `tests/factories/app.py:31-66` | Phase 31 extends this tuple |
| `_reset_singletons()` | `tests/factories/app.py:69-79` | Per-test reset mechanism; idempotent via `hasattr` guard |
| `create_app()` factory | `tests/factories/app.py:82+` | Factory landing for new singleton-bound services |
| Inventory lint test | `tests/unit/test_singleton_inventory_complete.py` | Lint pass = acceptance bullet #3 |
| Phase 27 TD-02 reference | `.planning/milestones/v1.7-phases/27-test-isolation-memory-reliability/27-02-SUMMARY.md` | Original 34-entry inventory + factory rationale |
| Phase 30 EVT-01 supersession record | `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/30-VERIFICATION.md` | Plan 30-01 supersession; ~10 sites deferred to EVT-02 |
| Phase 30 30-CONTEXT carry-forward | `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/30-CONTEXT.md` | D-EVT-01 decisions (factory-default, execute-time enumeration) |
| `tests/integration/conftest.py` (autouse embedder/reranker mock) | `tests/integration/conftest.py` | Phase 30-02 — must not regress; opt-out is Phase 33 |
| `tests/conftest.py` (14.5K) | `tests/conftest.py` | Global fixtures, registry resets |
| `_SINGLETON_INVENTORY` carry-forward count | 34 entries | Baseline; Phase 31 grows to `34 + N` where N = actual leak count |
| PG host | `docker rag-postgres pgvector/pgvector:pg16` (healthy as of 2026-05-18 session start) | Enumeration command runs against this |

## Canonical Refs

- `.planning/ROADMAP.md` (Phase 31 SC-1..4 + v1.9 carry-forward gates) — full relative path: `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md` (EVT-02 acceptance bullets) — `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/.planning/REQUIREMENTS.md`
- `.planning/PROJECT.md` (v1.9 milestone goal + carry-forward gates + Phase 30 EVT-01 partial/accepted-override record) — `/home/ubuntu/workspace/project_pytorch/project/rag_enterprise/.planning/PROJECT.md`
- `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/30-CONTEXT.md` — Phase 30 EVT-01 carry-forward decisions (factory-default, execute-time enumeration)
- `.planning/milestones/v1.8-phases/30-test-infra-mypy-hardening/30-VERIFICATION.md` — Plan 30-01 supersession record (Phase 31 inherits the deferred ~10 sites)
- `.planning/milestones/v1.8-MILESTONE-AUDIT.md` — tech-debt block entry for EVT-01 residual → EVT-02 routing
- `.planning/milestones/v1.7-phases/27-test-isolation-memory-reliability/27-02-SUMMARY.md` — original `_SINGLETON_INVENTORY` rationale + factory pattern source
- `.planning/codebase/CONCERNS.md` (singleton lifecycle concern @ lines 47, 139) — confirms event-loop fragility is a known codebase concern
- `./CLAUDE.md` + `Claude.md` (production standards — Pydantic V2, mypy --strict, ruff, no bare except)

## Acceptance (Phase Success Criteria — from ROADMAP)

1. **Zero-error gate:** `uv run pytest -m integration --uses-redis -v 2>&1 | grep -E "(no current event loop|attached to a different loop|got Future.*attached)"` returns empty on PG host post-fix. (D-01 + D-02 combined.)
2. **Inventory grows:** `_SINGLETON_INVENTORY` in `tests/factories/app.py` grows from 34 to `34 + N` where N = actual count from D-01 enumeration; each new entry traces to a real surfaced leak (no padding entries).
3. **Lint passes:** `tests/unit/test_singleton_inventory_complete.py` passes with the new count.
4. **No regression:** Integration-suite green count does not regress vs v1.8 close baseline (9 failed / 32 passed / 1 skipped / 3 errors — pre-existing failures stay pre-existing; D-04). Any newly surfaced unrelated failures must be triaged + documented in `31-00-SUMMARY.md`, not silently absorbed.

## Constraints

- **No production-code change.** Phase 31 is test infra refactor (factory migrations + per-test fixtures). Services under test stay untouched.
- **Must not regress `tests/integration/conftest.py` autouse mock** (Phase 30-02 ship gate). Opt-out marker is Phase 33 TEST-08 — out of Phase 31 scope.
- **Diff-cover ≥ 80% on touched files** (carry-forward gate). Test-infra files are touched; new factory entries trivially covered by the lint test.
- **`--fail-under=70` combined coverage** must not regress.
- **No new mypy silences** unless unavoidable; each one counts against Phase 32 MYPY-02 drain target.
- **Pre-existing 9+3 failures from v1.8 close** are filtered (D-04), not fixed — Phase 33+34 own those.

## Open Risks / Watch-outs

- **Enumeration count uncertainty (range 5–25+):** Broader D-01 regex may surface fewer or more than the +14 estimate. D-02 makes the count descriptive — but executor must surface the actual N to the user before bulk remediation (checkpoint at Task 0 enumeration complete).
- **Factory-fit assessment per site:** Some leak sites may not fit `create_app()` (e.g., services imported outside FastAPI lifecycle, module-level singletons in scripts/). Each site needs a fit-or-fixture decision; Plan 31-00 documents per-site choice in SUMMARY.
- **Pre-existing failures regression risk:** If one of the 9+3 failures regresses during Phase 31 work, D-04 filter still excludes it from event-loop enumeration — but it counts against acceptance bullet #4 ("integration suite green count does not regress"). Executor must triage any new green→red transitions.
- **`tests/integration/conftest.py` autouse mock interaction:** Phase 30-02's autouse fixture mocks `HuggingFaceEmbedder.__init__` + `CrossEncoderReranker.__init__`. If Phase 31 fixtures interact with embedder/reranker state, mock scope may collide. Watch for fixture-order issues.
- **`_SINGLETON_INVENTORY` lint scope:** Lint currently asserts inventory completeness against a fixed set. If Phase 31 adds entries the lint isn't aware of, the lint may need updating (lint test code, not just data). Plan 31-00 documents whether lint needs a code patch.
- **PG host stability across enumeration runs:** Multiple enumeration runs may be needed if first run is noisy. `docker rag-postgres` should remain healthy throughout; if it restarts mid-enumeration, state leak between runs is possible.

## Claude's Discretion (no decision needed)

- Per-site factory-vs-fixture choice (decided at execute time per site).
- Commit message convention (`chore(31-00):` / `test(31-00):`).
- Whether to add new fixtures inline in `tests/integration/conftest.py` or per-test-file conftest.
- Logger level for any new test diagnostics (debug).
- Order of remediation across sites (alphabetical, by service area, by error shape — executor's call).
- Whether to add a new helper in `tests/factories/app.py` for per-test event_loop creation (only if outlier count ≥ 3; otherwise inline per fixture).

## Deferred Ideas (Noted for Later)

- **`_SINGLETON_INVENTORY` schema migration** (e.g., add `category: str` field per entry to enable per-area lint) — v1.10+ test-infra polish, not Phase 31 scope.
- **Static-import-time analysis** (AST scan that flags new module-level singletons proactively) — v1.10+ tooling; out of scope.
- **`event_loop` fixture promotion to `tests/conftest.py`** (instead of per-test) — only if outlier count surfaces a consistent pattern post-enumeration; deferred decision to executor.
- **Phase 26-04 P1 backport to `LongTermMemory._get_pool`** — listed in STATE.md carry-forward; same partial-init class of bug but different surface (pool state, not loop binding); v1.10+.

## Next Action

```
/clear
/gsd-plan-phase 31
```

Optional pre-plan: `/gsd-plan-phase 31 --skip-research` — codebase anchors above are sufficient (Phase 30 cadence already established the pattern; Phase 31 is the closeout).

Phase 31 expected duration: ~half-day on PG host once enumeration command runs.
