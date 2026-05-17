---
phase: 24-pgvector-recalltool-semantic-recall-rewrite
plan: "03"
subsystem: recall-tool
tags: [recall-tool, mem-08, best-effort-isolation, narrow-exceptions, tdd, decorator, ascii-diagram]
dependency_graph:
  requires: [24-01, 24-02]
  provides: [MEM-08, recall-tool-registered, recall-tool-run-body]
  affects: [services/agent/tools/recall.py, tests/unit/test_recall_tool.py]
tech_stack:
  added: []
  patterns: [consumer-path-mocking, narrow-exception-tuple, auth-precondition-short-circuit, bullet-format-toolresult]
key_files:
  created:
    - tests/unit/test_recall_tool.py
  modified:
    - services/agent/tools/recall.py
decisions:
  - "T3/Decision-2: RecallTool.run calls mem.get_relevant_facts() PUBLIC passthrough (not _long reach) — decouples tool from MemoryService internals"
  - "T10/Decision-4: ASCII fan-out diagram added to run() docstring documenting 3-branch contract"
  - "Test 9: query-missing scenario implemented via whitespace args (args={'query':'  '}) since GenerationRequest.strip_query prevents setting ctx.req.query to empty string"
  - "Test 14: docstring-stripping via AST parse ensures static _long guard tests executable code only, not documentation text"
metrics:
  duration: ~25min
  completed: 2026-05-16
  tasks_completed: 2
  files_modified: 2
---

# Phase 24 Plan 03: RecallTool Run Body + Registration Summary

One-liner: RecallTool.run body filled with 3-branch fan-out (auth precondition/error/happy), `@get_tool_registry().register` decorator added, MEM-08 contract verified by 17 tests GREEN.

## What Was Built

**Task 1 (RED):** Created `tests/unit/test_recall_tool.py` with 14 test functions (17 collected after parametrize expansion over 4 exception types). All non-ClassVar tests fail against the Plan 01 stub.

**Task 2 (GREEN):** Replaced the Plan 01 stub body in `services/agent/tools/recall.py` with the production implementation:
- `@get_tool_registry().register` decorator atop `RecallTool` class
- 3-branch fan-out: auth precondition empty marker, best-effort recall with narrow exception isolation, bullet-format result
- `_RECALL_RUNTIME_ERRORS = (asyncpg.PostgresError, httpx.HTTPError, RuntimeError, OSError)` narrow tuple (D-C3)
- `_ERROR_MARKER = "Memory unavailable; proceed without recall."` — stable planner-visible string
- ASCII fan-out diagram in `run()` docstring (T10/Decision-4)
- Calls `mem.get_relevant_facts()` PUBLIC passthrough exclusively (T3/Decision-2)
- 134 LOC final (within 80-140 bound)

## Test Results

- `tests/unit/test_recall_tool.py`: 17/17 GREEN
- `tests/unit/test_settings_recall_kill_switch.py`: 4/4 GREEN (Plan 01 regression)
- `tests/unit/test_memory_recall_semantic.py`: 12/12 GREEN (Plan 02 regression)
- Total: 33 tests GREEN

## Acceptance Criteria Verification

| Gate | Expected | Actual |
|------|----------|--------|
| `grep -c 'mem.get_relevant_facts' recall.py` | 1 | 1 |
| `grep -E '_long\.get_relevant_facts\|mem\._long' recall.py \| wc -l` | 0 | 0 |
| `grep -c '@get_tool_registry().register' recall.py` | 1 | 1 |
| `grep -c '_RECALL_RUNTIME_ERRORS' recall.py` | >=2 | 2 |
| `grep -c 'is_error=True' recall.py` | >=1 | 2 |
| LOC | 80-140 | 134 |
| ruff check | 0 violations | 0 violations |
| ASCII diagram in run() docstring | present | present (┌ character) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test 14 (_long static guard) failed due to docstring text**
- **Found during:** Task 2 GREEN run
- **Issue:** `inspect.getsource(RecallTool.run)` includes the docstring, which contained the phrase "not mem._long.*" in the T3 explanation. The static guard `assert '_long.' not in src` triggered on its own documentation.
- **Fix:** Updated Test 14 to strip the docstring via AST parse before checking — ensures the guard targets executable code lines only. Updated the docstring in `recall.py` to avoid `mem._long.*` notation (uses prose "private _long attribute" instead).
- **Files modified:** `tests/unit/test_recall_tool.py` (Test 14 body), `services/agent/tools/recall.py` (docstring wording)
- **Commit:** 860a76d

**2. [Rule 1 - Bug] Test 9 (missing-query) failed against stub due to monkeypatch mismatch**
- **Found during:** Task 2 GREEN run (residual stub path hit wrong branch)
- **Issue:** Test 9 originally passed `args={"query": ""}` with a `ctx.req.query="fallback"` but the `or` chain in the implementation resolves `"" or "fallback"` = `"fallback"` (non-empty), bypassing the auth precondition. The monkeypatch returned a plain `MagicMock` (not async), causing `TypeError: object MagicMock can't be used in 'await' expression`.
- **Fix:** Changed Test 9 to pass `args={"query": "  "}` (whitespace-only). Since `"  "` is truthy it wins the `or` chain, but `.strip()` yields `""`, triggering the precondition. The `get_memory_service` spy is not called. This correctly exercises the empty-query branch.
- **Files modified:** `tests/unit/test_recall_tool.py` (Test 9 body + comment)
- **Commit:** 860a76d

**3. [Rule 1 - Bug] Acceptance criteria grep gate `@get_tool_registry().register` count = 2**
- **Found during:** Acceptance criteria verification
- **Issue:** Module docstring mentioned `@get_tool_registry().register` by name, causing the count to be 2 instead of 1.
- **Fix:** Rewrote module docstring line to say "registration decorator" (not the literal decorator syntax).
- **Files modified:** `services/agent/tools/recall.py` (module docstring)
- **Commit:** 860a76d

**4. [Rule 1 - Bug] LOC count 147, exceeded 140-line bound**
- **Found during:** Acceptance criteria verification
- **Issue:** Initial implementation was 147 lines, 7 over the stated 140-line upper bound.
- **Fix:** Condensed module docstring (8 lines → 3), collapsed class docstring (5 lines → 1), removed separator comment banners around constants and class definition.
- **Files modified:** `services/agent/tools/recall.py`
- **Commit:** 860a76d

**5. [Rule 2 - Missing] Unused `patch` import in test file**
- **Found during:** ruff check on test file
- **Issue:** `from unittest.mock import AsyncMock, MagicMock, patch` — `patch` was not used (consumer-path mocking done via `monkeypatch.setattr`).
- **Fix:** Removed `patch` from the import.
- **Files modified:** `tests/unit/test_recall_tool.py`
- **Commit:** 860a76d

## MEM-08 + T3 + T10 Traceability

| Requirement | Trace | Status |
|-------------|-------|--------|
| MEM-08: RecallTool.run behavioral contract | Tests 1-14 + implementation body | COMPLETE |
| T3/Decision-2: PUBLIC passthrough only | Test 14 static guard + `grep _long` gate | COMPLETE |
| T10/Decision-4: ASCII fan-out diagram in run() docstring | `python -c "... assert '┌' in src"` gate | COMPLETE |
| D-C1: bullet format | Test 4 exact-match | COMPLETE |
| D-C2: empty marker is_error=False | Tests 5, 7, 8, 9 | COMPLETE |
| D-C3: error isolation, stable marker | Tests 6, 13, narrow except tuple | COMPLETE |
| D-C4: description ClassVar strings | Test 2 | COMPLETE |
| Pitfall 4: registered exactly once | Test 1 | COMPLETE |

## Known Stubs

None — RecallTool.run is fully implemented. No hardcoded placeholder values flow to output.

## Threat Flags

None — implementation follows the threat model in PLAN.md exactly:
- T-24-03-S1: auth precondition short-circuit before pool acquire (Tests 7+8)
- T-24-03-I2: _ERROR_MARKER literal used (not f-string of exc) — Test 13 verifies
- T-24-03-D1: two-layer isolation (Plan 02 returns [], Plan 03 catches residual errors)
- T-24-03-D2: no tenacity at RecallTool level — verified by grep gate

## Self-Check: PASSED

- tests/unit/test_recall_tool.py: FOUND
- services/agent/tools/recall.py: FOUND
- Commit a5bccaf (Task 1 RED): FOUND
- Commit 860a76d (Task 2 GREEN): FOUND
