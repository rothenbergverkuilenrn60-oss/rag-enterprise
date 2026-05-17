---
phase: "30"
plan: "00"
subsystem: tests
tags: [oai-01, test-infra, event-loop, redis-isolation, make-api-error]
dependency_graph:
  requires: []
  provides: [tests/factories/openai_errors.py::make_api_error]
  affects: [tests/unit/test_agent_pipeline_refactor.py, tests/unit/test_agent_sse.py, tests/unit/test_pipeline_coverage.py, tests/unit/test_feedback_ab_forward.py]
tech_stack:
  added: [fakeredis==2.35.1]
  patterns: [make_api_error factory helper, Redis isolation via monkeypatch, asyncio event-loop contamination prevention]
key_files:
  created:
    - tests/factories/__init__.py
    - tests/factories/openai_errors.py
    - tests/unit/test_make_api_error_helper.py
  modified:
    - tests/unit/test_agent_pipeline_refactor.py
    - tests/unit/test_agent_sse.py
    - tests/unit/test_pipeline_coverage.py
    - tests/unit/test_feedback_ab_forward.py
    - pyproject.toml (fakeredis dev dep)
    - uv.lock
decisions:
  - "Helper located at tests/factories/openai_errors.py per plan-review A1 (importable from integration tests too)"
  - "Mocked _ab_assign_and_map, _store_last_qa, dispatch_extraction in fixtures to prevent event-loop contamination"
  - "Added fakeredis to dev deps (3 test files failed collection without it — pre-existing on this branch)"
metrics:
  duration_minutes: 20
  completed_date: "2026-05-17"
  tasks_completed: 2
  tasks_total: 3
  files_modified: 8
---

# Phase 30 Plan 00: OAI-01 make_api_error Helper + Test Suite Green Summary

**One-liner:** Introduced `make_api_error()` factory helper in `tests/factories/openai_errors.py` and fixed 16 event-loop contamination failures across 4 unit test files by isolating Redis dependencies in test fixtures.

## What Was Built

### Task 0 — RED: Helper infrastructure + baseline

- **`tests/factories/__init__.py`** — new Python package to make the factory importable repo-wide
- **`tests/factories/openai_errors.py`** — `make_api_error(message, *, status_code, request) -> APIError` helper with v1.x SDK signature; `mypy --strict` clean; `ruff` clean
- **`tests/unit/test_make_api_error_helper.py`** — 4 passing tests (import, default construction, status_code forwarding, .request attribute, explicit request override)
- `/tmp/30-00-mypy-baseline.txt` — captured 32 pre-existing errors
- Production grep gate: `grep -rn "APIError(" services/ controllers/ utils/` → 0 hits

### Task 1 — GREEN: Unit suite green

**Root cause discovery (deviation from plan):** The 32 failures referenced in OAI-01 are NOT inline `openai.APIError(...)` construction errors on this branch. The worktree is at Phase 26 state; the 6 target test files have event-loop contamination failures instead. Root cause: `AgentQueryPipeline.run()` calls `_ab_assign_and_map()` and `_store_last_qa()` which create Redis connections bound to test event loops. When the test loop closes, the pending Redis futures from `redis.asyncio` remain attached to the closed loop, causing "Future attached to a different loop" in subsequent tests. Additionally, `dispatch_extraction()` creates `asyncio.create_task()` calls that also leak across loops.

**Fixes applied:**

| File | Fix |
|------|-----|
| `test_agent_pipeline_refactor.py` | `mock_pipeline` fixture: patched `_ab_assign_and_map`, `_store_last_qa`, `dispatch_extraction` |
| `test_agent_sse.py` | `patch_pipeline_singletons` fixture: patched same 3 symbols |
| `test_pipeline_coverage.py` | `_patch_pipeline_infra` and `_patch_query_pipeline_infra`: patched same 3 symbols |
| `test_feedback_ab_forward.py` | Updated `push_task_from_feedback` assertion to include `user_comment=''` (production added kwarg since test was written) |
| `pyproject.toml` + `uv.lock` | Added `fakeredis` to dev deps (3 test files failed collection; pre-existing issue) |

**Result:** `uv run pytest tests/unit/ -m 'not benchmark'` → **1200 passed, 0 failed** (from 16 failures before)

### Task 2 — REFACTOR: No-op

- No `httpx.Request(...)` manual constructions related to APIError exist in tests (no callsites to consolidate)
- `diff-cover` shows "No lines with coverage information in this diff" (only test files modified, which are not in `[tool.coverage.run] source`)
- Combined coverage: 81.74% (well above 70% floor)
- REFACTOR task noted as no-op in plan

## Deviations from Plan

### [Rule 1 - Bug] Actual failures are event-loop contamination, not APIError construction

**Found during:** Task 0 enumeration

**Issue:** The plan targets 32 `openai.APIError(...)` construction sites missing the `request=` arg. On this worktree branch (Phase 26 state), those callsites do not exist — the 4 test files where they would appear already have `request=None` or use `anthropic.APIStatusError`. The actual failures in the 6 target files are "RuntimeError: Future attached to a different loop" caused by Redis connections created in `_ab_assign_and_map` and `_store_last_qa`, plus background tasks from `dispatch_extraction`.

**Fix:** Mocked the 3 Redis-dependent symbols in each test fixture.

**Files modified:** `tests/unit/test_agent_pipeline_refactor.py`, `tests/unit/test_agent_sse.py`, `tests/unit/test_pipeline_coverage.py`, `tests/unit/test_feedback_ab_forward.py`

**Commits:** `030d774` (RED), `0c28ae9` (GREEN)

### [Rule 3 - Blocking] Missing `fakeredis` package blocked collection of 3 test files

**Found during:** Task 1 full suite run

**Issue:** `test_ab_test_service.py`, `test_ingest_status.py`, `test_memory_service.py` import `fakeredis` at module level. `fakeredis` was not in `pyproject.toml`. Collection failed with `ModuleNotFoundError: No module named 'fakeredis'`. This is a pre-existing issue on this branch (created before Phase 27 added the dependency on master).

**Fix:** Added `fakeredis>=2.35.1` to `[dependency-groups] dev` in `pyproject.toml`.

**Commit:** `0c28ae9`

### Callsite count deviation

**Expected per plan:** 32 `openai.APIError(...)` construction callsites across 6 files

**Actual:** 0 unconverted callsites in the 6 target files (the existing 4 callsites in `test_summary_indexer.py` and `test_nlu_service_extra.py` already pass `request=None` — they are NOT in the OAI-01 target list and were not modified)

**Impact:** The `make_api_error()` helper is created as planned but no callsite conversions were needed. The helper is available for future use when those tests need to be updated (e.g., if the `request=None` pattern also needs to change).

## Verification Results

| Check | Result |
|-------|--------|
| `uv run pytest tests/unit/ -m 'not benchmark'` | 1200 passed, 0 failed |
| `uv run mypy --strict tests/factories/openai_errors.py` | Success: no issues found |
| `uv run mypy --strict .` | 32 errors (same as baseline — no increase) |
| `uv run ruff check` on all touched files | Clean |
| `git diff --name-only services/ controllers/ utils/` | Empty (production code untouched) |
| Coverage floor `--fail-under=70` | 81.74% — passes |
| No bare `except` introduced | Confirmed |
| INSERT-ONLY `audit_log` invariant preserved | Confirmed (no audit_log edits) |
| `_bulk_near_duplicate_check_raw` preserved | Confirmed (no memory_service.py edits) |

## Conversion Count (OAI-01 tracking)

| File | Expected callsites (plan) | Actual callsites found | Converted |
|------|--------------------------|----------------------|-----------|
| test_agent_pipeline_refactor.py | 11 | 0 | 0 |
| test_agent_sse.py | 9 | 0 | 0 |
| test_pipeline_coverage.py | 10 | 0 | 0 |
| test_feedback_ab_forward.py | 1 | 0 | 0 |
| test_memory_controller.py | unknown | 0 | 0 |
| test_recall_tool.py | unknown | 0 | 0 |
| **Total** | **32** | **0** | **0** |

The 4 existing `openai.APIError(...)` calls in `test_summary_indexer.py` and `test_nlu_service_extra.py` already pass `request=None` and are not in the OAI-01 target list — they were not modified.

## Helper Landing Location

`tests/factories/openai_errors.py` — created new (per plan-review A1 relocation; importable repo-wide, not confined to `tests/unit/`)

## Known Stubs

None — all code is fully wired.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. All changes are test-only.

## Self-Check: PASSED

- `tests/factories/openai_errors.py` exists and contains `def make_api_error`
- `tests/factories/__init__.py` exists
- `tests/unit/test_make_api_error_helper.py` exists with 4 passing tests
- Commit `030d774` exists (Task 0)
- Commit `0c28ae9` exists (Task 1)
- mypy baseline unchanged (32 errors)
- Production code untouched (git diff services/ controllers/ utils/ = empty)
