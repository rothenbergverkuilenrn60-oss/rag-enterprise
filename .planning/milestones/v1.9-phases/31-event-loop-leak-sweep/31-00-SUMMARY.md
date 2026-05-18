---
phase: 31-event-loop-leak-sweep
plan: "00"
subsystem: testing
tags: [asyncio, event-loop, pytest, singleton, pgvector, redis, fakeredis]

requires:
  - phase: 30-test-infra-mypy-hardening
    provides: "_SINGLETON_INVENTORY (34 entries), autouse embedder/reranker mock, v1.8 baseline"

provides:
  - "EVT-02 closeout: D-01 broader-regex returns zero matches on PG-host integration suite"
  - "Investigation evidence confirming N=0 is real (not false-positive)"
  - "Documented triage of 2 broader-regex hits as non-fatal cache warning, not loop isolation bugs"
  - "_SINGLETON_INVENTORY remains at 34 (no surfaced factory-fit leak sites)"
  - "Singleton inventory lint green; Phase 30-02 autouse mock unregressed"

affects:
  - phase-32-mypy-drain
  - phase-33-test-coverage
  - phase-34-ui-schema-drift

tech-stack:
  added: []
  patterns:
    - "D-01 enumeration: correct invocation is -m 'integration and not real_llm and not benchmark' (plan's --uses-redis flag is an unrecognized pytest argument)"
    - "Event loop is closed in cache_get is non-fatal by design (broad except block + explicit warning log)"

key-files:
  created: []
  modified: []

key-decisions:
  - "N=0 confirmed: zero D-01 asyncio isolation failures on PG-host integration suite"
  - "Two broader-regex hits ('Event loop is closed') are non-fatal cache.py warning logs during pre-existing failing tests — not loop isolation bugs, not in Phase 31 scope"
  - "--uses-redis is an unrecognized pytest CLI argument (errors out); no integration tests carry uses_redis marker; correct enumeration command omits it"
  - "Tasks 3, 4 skipped (N_A=0, N_B=0 — no factory-fit or factory-unfit leak sites surfaced)"

patterns-established:
  - "EVT-02 zero-error gate: verify PG+Redis container health before accepting N=0 (ARCH-02)"
  - "Broader regex sweep required alongside narrow D-01 regex to avoid false-negative confirmation"

requirements-completed:
  - EVT-02

duration: 25min
completed: 2026-05-18
---

# Phase 31 Plan 00: Event-Loop Leak Sweep Summary

**EVT-02 closed: PG-host integration suite reports zero asyncio loop-isolation errors; _SINGLETON_INVENTORY stays at 34 (no new leak sites surfaced after full investigation)**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-18T10:45:00Z
- **Completed:** 2026-05-18T11:10:00Z
- **Tasks:** 0 (investigation), 1 (enumeration + investigation), 2 (triage), 5 (zero-error gate), 6 (regression check), 7 (SUMMARY) — Tasks 3 and 4 skipped (N_A=0, N_B=0)
- **Files modified:** 0 production/test files (no loop-fix changes needed)

## Accomplishments

- Confirmed PG (rag-postgres) and Redis (rag-redis) containers healthy throughout enumeration
- Ran full D-01 enumeration with both narrow and broad regex; N=0 against all three D-01 patterns
- Investigated 2 broader-regex hits ("Event loop is closed") and triaged them as non-fatal cache layer warnings, not loop-isolation failures
- Verified all 34 `_SINGLETON_INVENTORY` entries resolve via importlib + hasattr
- Confirmed Phase 30-02 autouse embedder/reranker mock unregressed
- Confirmed lint passes (`test_singleton_inventory_complete.py` green)
- Documented that plan's `--uses-redis` flag is an unrecognized pytest argument; correct enumeration command established

## Task Commits

No production/test-infra code changed — no per-task commits generated (Tasks 3, 4 skipped; N=0 throughout). SUMMARY commit is the only commit for this plan.

## Investigation Evidence

### 1. Container Health

| Container | Status | Ports |
|-----------|--------|-------|
| rag-postgres | Up 2 hours (healthy) | 0.0.0.0:5432->5432/tcp |
| rag-redis | Up 2 hours (healthy) | 0.0.0.0:6379->6379/tcp |

Both containers healthy before and throughout enumeration (ARCH-02 requirement satisfied).

### 2. `--uses-redis` Flag Analysis

The plan's verbatim command `uv run pytest -m integration --uses-redis -v` **errors out** with:
```
pytest: error: unrecognized arguments: --uses-redis
```

`--uses-redis` is not a recognized pytest CLI option. The `uses_redis` marker exists (registered in `tests/conftest.py` for auto-attaching `redis_mock` fixture), but **zero integration tests carry that marker** — it is unit-test-only. Correct enumeration command:

```bash
uv run pytest tests/integration/ --ignore=tests/integration/test_ragas_eval.py \
  -m 'integration and not real_llm and not benchmark' -v 2>&1 \
  | grep -E "(no current event loop|attached to a different loop|got Future.*attached)" \
  | sort -u > /tmp/31-00-leak-sites.txt
```

### 3. Collect-Only Count

```
45/68 tests collected (23 deselected, 1 collection error for test_ragas_eval.py — PermissionError /app)
```

Tests genuinely ran: 10 failed / 31 passed / 1 skipped / 3 errors — not all-skipped due to fixture failure.

### 4. Narrow D-01 Regex (Plan's Three Patterns)

```bash
grep -E "(no current event loop|attached to a different loop|got Future.*attached)" \
  /tmp/31-00-full-pytest.log | sort -u | wc -l
```
Result: **0** — confirmed zero matches.

### 5. Broader Regex Sweep

Broader regex including `Event loop is closed`, `RuntimeError.*loop`, `asyncio.exceptions`, `_GatheringFuture`, `loop_at_init`, `There is no current event loop`:

**2 matches found**, both identical:
```
WARNING | utils.cache:cache_get:79 | [Cache] GET failed (non-fatal): Event loop is closed
```

**Triage of these 2 matches:**

| # | Pattern | Source | Test context | Classification |
|---|---------|--------|-------------|----------------|
| 1 | `Event loop is closed` | `utils/cache.py:cache_get:79` | `test_filter_extractor_e2e_chinese_section` (HTTP 403 from dashscope — pre-existing failure) | Non-fatal cache warning; secondary side-effect of pre-existing failing test; NOT D-01 |
| 2 | `Event loop is closed` | `utils/cache.py:cache_get:79` | `test_no_v1_5_regression` / `test_pipeline_load_context_audit` area (HTTP 403 from dashscope) | Non-fatal cache warning; secondary side-effect of pre-existing failing test; NOT D-01 |

`cache_get` deliberately catches all exceptions with a broad `except Exception as exc` and logs `[Cache] GET failed (non-fatal): {exc}`, returning `None`. The "Event loop is closed" message is the Redis aioredis client hitting a closed loop during teardown of an already-failing test. This is a design-intentional degradation path, not a D-01 event-loop isolation failure.

**Conclusion: N=0 for D-01 purposes. The two broader-regex hits are excluded because:**
1. They are logged warnings from a deliberate exception handler, not pytest ERROR/FAILED output
2. They are secondary effects of tests failing for unrelated reasons (HTTP 403 external service)
3. The `cache_get` non-fatal handling means no test is actually broken by them
4. They do not match any of the three D-01 target shapes (attached to a different loop / no current event loop / got Future.*attached)

### 6. _SINGLETON_INVENTORY Reachability

```bash
APP_MODEL_DIR=/tmp uv run python -c "
import importlib
from tests.factories.app import _SINGLETON_INVENTORY
# ... importlib.import_module + hasattr check for each of 34 entries
"
```
Result: **All 34 inventory entries resolve OK** — no stale or broken entries.

### 7. Lint Pass

```
tests/unit/test_singleton_inventory_complete.py::test_singleton_inventory_covers_all_module_globals PASSED
1 passed in 0.16s
```

### 8. Phase 30-02 Autouse Mock

AST scan confirms `_mock_local_model_inits` fixture is present in `tests/integration/conftest.py` and `autouse=True` — Phase 30-02 carry-forward unregressed.

## Per-Site Triage (D-01 Enumeration)

| Site | Error Shape | Source | In Failing Test | Classification | Action |
|------|-------------|--------|-----------------|----------------|--------|
| — | `Event loop is closed` (WARNING) | `utils.cache.cache_get` | yes (HTTP 403 pre-existing) | Non-D-01 cache warning | No action; D-04 pre-existing |
| — | `Event loop is closed` (WARNING) | `utils.cache.cache_get` | yes (HTTP 403 pre-existing) | Non-D-01 cache warning | No action; D-04 pre-existing |

**Wave A (factory-fit): N_A = 0** — Task 3 skipped.
**Wave B (factory-unfit): N_B = 0** — Task 4 skipped.

## D-01 Zero-Error Gate (D-02 HARD)

```bash
wc -l /tmp/31-00-leak-sites.txt   # narrow D-01 patterns
# Output: 0
```

Gate: **PASSED** — zero D-01 matches post-enumeration.

## D-04 Regression Check vs v1.8 Close Baseline

| Metric | v1.8 Close Baseline | Phase 31 Post | Delta | Verdict |
|--------|---------------------|---------------|-------|---------|
| passed | 32 | 31 | -1 | See note |
| failed | 9 | 10 | +1 | Environmental |
| skipped | 1 | 1 | 0 | OK |
| errors | 3 | 3 | 0 | OK |

**Note on -1 green count:** `test_filter_extractor_e2e_chinese_section` regressed from pass to fail between v1.8 close and current run due to HTTP 403 from dashscope.aliyuncs.com (external API rate limit / key expiry). This is an environmental failure, not a Phase 31 regression. It falls under D-04 pre-existing category (real-LLM / real-API dependency) and is owned by Phase 33 (TEST-08). Phase 31 introduced zero production or test-infra changes, so cannot be the cause.

Per must_have #4: "Integration-suite green count does NOT regress vs v1.8 close baseline." The -1 delta is environmental (external HTTP 403), not caused by Phase 31. Accepted per D-04 filter.

## Acceptance Bullets

1. **HARD — Zero-error gate (D-01 + D-02):** VERIFIED — 0 matches against narrow regex; 2 broader-regex hits triaged as non-D-01 non-fatal cache warnings.

2. **DESCRIPTIVE — Inventory grew authentically:** VERIFIED — N_A=0, inventory stays at 34. No padding entries. Each existing entry resolves via importlib.

3. **HARD — Lint passes:** VERIFIED — `test_singleton_inventory_complete.py` passes (1 passed in 0.16s).

4. **HARD — No regression vs v1.8 baseline:** VERIFIED with caveat — passed count is 31 vs 32 baseline; the -1 is environmental (HTTP 403 from dashscope.aliyuncs.com), not caused by Phase 31. Phase 31 made zero code changes.

5. **HARD — Phase 30-02 autouse mock not regressed:** VERIFIED — `_mock_local_model_inits` present and `autouse=True` (AST scan confirmed).

6. **HARD — No new mypy --strict silences:** VERIFIED — Phase 31 introduced zero code changes; no new `# type: ignore` annotations possible.

## Files Created/Modified

None — Phase 31 Plan 00 produced zero code changes. The investigation confirmed N=0 with full evidence.

## Decisions Made

- **N=0 accepted with evidence:** Narrow D-01 regex returns zero. Two broader-regex hits triaged and excluded as non-fatal cache warnings during pre-existing failing tests.
- **`--uses-redis` documented as broken plan flag:** The plan's verbatim command errors out; correct command omits this flag. No integration tests carry `uses_redis` marker.
- **Tasks 3, 4 skipped:** N_A=0, N_B=0 — no factory-fit or factory-unfit leak sites to fix.

## Deviations from Plan

**1. [Rule 3 - Blocking] Plan's `--uses-redis` flag causes pytest to error**
- **Found during:** Investigation (Task 1 verification)
- **Issue:** `pytest --uses-redis` is an unrecognized argument; pytest exits with error before running any tests
- **Fix:** Substituted correct command: `-m 'integration and not real_llm and not benchmark'` with `--ignore=tests/integration/test_ragas_eval.py` (ragas_eval has a collection-time PermissionError for /app unrelated to event loops)
- **Files modified:** None (command substitution only; plan file not edited)
- **Verification:** Full suite ran: 10 failed / 31 passed / 1 skipped / 3 errors

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking: unrecognized pytest flag)
**Impact on plan:** Necessary substitution to obtain enumeration results. Correct enumeration surface confirmed (same tests that would have run with any correctly-formed `-m integration` command).

## Issues Encountered

- `test_ragas_eval.py` collection-time PermissionError (`/app` directory missing) — excluded via `--ignore` as in prior agent run. Pre-existing.
- `chinese_section` and `planner_picks_web_search` / `pipeline_load_context` tests fail due to HTTP 403 from dashscope.aliyuncs.com — external API credential/rate issue. Pre-existing D-04 category.

## Deferred Items

- **Pre-existing 9+3 v1.8 failures** owned by Phase 33+34 — NOT closed in Phase 31. Categories: real-LLM API key expiry (TEST-08/Phase 33), UI sentinel drift (TEST-11/Phase 34), schema drift (TEST-10/Phase 34), perf-bench (benchmark/Phase 33).
- **`cache_get` broad `except Exception`:** The bare-except in `utils/cache.py:cache_get` is a separate code quality concern (ERR-01 — narrow exception types). Not in Phase 31 scope; logged for Phase 32 or Phase 33.

## Next Phase Readiness

- EVT-02 closed. Phase 31 is complete.
- Phase 32 (mypy drain) can proceed — zero new mypy silences introduced.
- Phase 33 (test coverage) can proceed — test infra baseline unchanged.

---

*Phase: 31-event-loop-leak-sweep*
*Completed: 2026-05-18*
