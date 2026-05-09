---
phase: 19-agent-first-docs-demo-release
plan: 01
subsystem: services/agent
tags: [agent-08, tdd, demo-stubs, phase-19, wave-1]
requires:
  - services.agent.tools.base.BaseTool       # Phase 17
  - services.agent.tools.registry.ToolRegistry  # Phase 17
  - utils.models.{ToolCall, ToolPlan, ToolResult, ToolContext, GenerationRequest}
provides:
  - services.agent._demo_stubs.DEMO_QUERY
  - services.agent._demo_stubs.DEMO_KB_SHARDS
  - services.agent._demo_stubs.DemoStubPlanner
  - services.agent._demo_stubs.make_fake_retrieve_tool
  - services.agent._demo_stubs.build_demo_registry
affects:
  - services/agent/_demo_runner.py (consumer — plan 19-03)
  - tests/integration/test_demo_agent.py (consumer — plan 19-04)
tech-stack:
  added: []
  patterns:
    - frozen-pydantic-v2-models (utils/models.py convention)
    - test-fixture-promoted-to-runtime-artifact (Phase 19 first instance)
    - mock-at-consumer-path (v1.3 D-16; honored by NOT mutating get_tool_registry singleton)
key-files:
  created:
    - services/agent/_demo_stubs.py (97 lines)
    - tests/unit/test_demo_stubs.py (162 lines, 7 tests)
  modified: []
decisions:
  - rebind-name-parameter-to-tool_name: "Python class-scope LEGB blocks `name: ClassVar[str] = name` self-reference inside the class body. Inherited from Phase 18 fixture pattern (_make_fake_tool used `tool_name`)."
  - chunk_count-3-not-0: "Per D-06, demo SSE events must show non-zero chunk counts (the WHOA in the asciinema cast). Diverges from Phase 18 fixture where chunk_count=0."
metrics:
  duration_minutes: 12
  tasks_completed: 2
  commits: 2
  files_created: 2
  files_modified: 0
  tests_added: 7
  unit_suite_passed: 775
  unit_suite_skipped: 1
  mypy_strict_new_errors: 0
  ruff_errors: 0
  completed_date: 2026-05-09
---

# Phase 19 Plan 01: Demo-Stub Runtime Primitives — Summary

**One-liner:** Promote Phase 18 SSE test fixtures (`_StubPlanner`, `_make_fake_tool`, `_stub_registry`) from `tests/unit/test_agent_sse.py` into a runtime module `services/agent/_demo_stubs.py` that `make demo-agent` (plan 19-03) and the demo integration test (plan 19-04) both consume — single source of truth for the 4-tool 0.5s parallel-fan-out fixture (CONTEXT.md D-05 / D-06).

## Tasks Executed

| Task | Commit  | Files                                | Status |
| ---- | ------- | ------------------------------------ | ------ |
| T1 (RED)   | `33aa014` | `tests/unit/test_demo_stubs.py` (162 lines, 7 tests) | RED gate satisfied — all 7 tests fail with `ModuleNotFoundError: No module named 'services.agent._demo_stubs'` at collection time. |
| T2 (GREEN) | `9dde2de` | `services/agent/_demo_stubs.py` (97 lines)        | GREEN gate satisfied — 7/7 tests pass, ruff clean, mypy --strict clean (0 new errors on this file). |

## Public Exports

`services/agent/_demo_stubs.py` (97 lines, ≤ 100 budget):

| Symbol                    | Kind      | Contract |
| ------------------------- | --------- | -------- |
| `DEMO_QUERY`              | `Final[str]` | Byte-identical to CONTEXT.md `<specifics>` verbatim string: `"Across our compliance, finance, engineering, and HR knowledge bases, where do we mention 'data retention'?"` |
| `DEMO_KB_SHARDS`          | `Final[tuple[str, ...]]` | `("compliance", "finance", "engineering", "hr")` — 4 shard names matching the 4 tools. |
| `DemoStubPlanner`         | class     | Constructor takes no args. `async plan_from_messages(messages, tools, system) -> ToolPlan`. Call#1 returns 4-tool parallel plan (`parallel_groups=[[0,1,2,3]]`, `stop_reason="tool_use"`). Call#2+ returns terminal plan (`steps=[]`, `stop_reason="text_only"`, `rationale=` canned answer). |
| `make_fake_retrieve_tool` | factory   | `(name="search_knowledge_base", sleep_s=0.5, content="[fixture chunk]") -> type[BaseTool]`. The returned class's `run` sleeps `sleep_s` then returns `ToolResult(content, chunks=[], metadata={"latency_ms": int(sleep_s*1000), "chunk_count": 3})`. |
| `build_demo_registry`     | factory   | `(*tool_classes: type[BaseTool]) -> ToolRegistry`. Returns a fresh `ToolRegistry()` per call — does NOT mutate the global `get_tool_registry()` singleton (T-19-01-02 mitigation). |

## Verification Results

| Check | Command | Result |
| --- | --- | --- |
| RED gate | `.venv/bin/pytest tests/unit/test_demo_stubs.py` (before T2) | Collection-stage `ModuleNotFoundError` covers all 7 tests — exit non-zero. |
| GREEN gate (per-plan) | `.venv/bin/pytest tests/unit/test_demo_stubs.py -v` | **7 passed in 0.66s** |
| Regression | `.venv/bin/pytest tests/unit -q` | **775 passed, 1 skipped** (Phase 18 baseline 729 + 7 new T1 tests + ~39 from concurrent Wave-1 work). Zero failures. |
| ruff | `.venv/bin/ruff check services/agent/_demo_stubs.py tests/unit/test_demo_stubs.py` | All checks passed |
| mypy --strict (new file) | `APP_MODEL_DIR=/tmp .venv/bin/mypy --strict services/agent/_demo_stubs.py \| grep '^services/agent/_demo_stubs.py'` | 0 errors on the new file (other files have pre-existing baseline errors out of scope). |
| Line budget | `wc -l services/agent/_demo_stubs.py` | 97 ≤ 100 |
| No self-import | `grep -c 'from services.agent._demo_stubs import' services/agent/_demo_stubs.py` | 0 |
| Required exports | `grep -E '^class DemoStubPlanner\|^def make_fake_retrieve_tool\|^def build_demo_registry\|^DEMO_QUERY' services/agent/_demo_stubs.py` | 4 matches (1 each) |
| DEMO_QUERY verbatim | `grep -c 'Across our compliance, finance, engineering, and HR knowledge bases' services/agent/_demo_stubs.py` | 1 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Adapted `conda run -n torch_env pytest` to `.venv/bin/pytest`**
- **Found during:** Task 1 RED-gate verification.
- **Issue:** The plan's `<verify><automated>` and `<action>` blocks invoke pytest via `conda run -n torch_env pytest`. This machine has no `conda` binary; the project's actual Python environment is `.venv/` (uv-managed, Python 3.12.13).
- **Fix:** Used `.venv/bin/pytest` (and `.venv/bin/ruff`, `.venv/bin/mypy`) in place of the conda invocation. Same Python interpreter version, same dependency set, identical pytest configuration (`pytest.ini`).
- **Files modified:** None (this is a runtime-environment adaptation, not a code change).
- **Commit:** N/A.

**2. [Rule 1 - Bug] Rebind `name` parameter to `tool_name` inside `make_fake_retrieve_tool`**
- **Found during:** Task 2 first GREEN-attempt — 3 tests failed with `NameError: name 'name' is not defined` at the class-body annotation `name: ClassVar[str] = name`.
- **Issue:** Python class-scope LEGB resolution: when an annotation defines a class variable also named `name`, the right-hand-side lookup of `name` becomes a forward-reference to the (not-yet-bound) class attribute itself, NOT the enclosing function parameter. Class scope does not inherit from enclosing function scope for plain assignment statements (only method bodies see the enclosing scope).
- **Fix:** Rebind `tool_name = name` in the function body before the class definition; the class body then references the unambiguous `tool_name` local. Same pattern Phase 18 used (`_make_fake_tool` named its parameter `tool_name` from the start to avoid this).
- **Files modified:** `services/agent/_demo_stubs.py` (line ~85).
- **Commit:** Folded into GREEN commit `9dde2de` before that commit landed.

**3. [Rule 1 - Bug] Trim docstrings to fit ≤ 100-line budget**
- **Found during:** Task 2 second GREEN-attempt — 111 lines, over the ≤ 100 acceptance-criterion budget.
- **Issue:** Initial implementation had verbose multi-paragraph docstrings on every function/class. The plan's `<acceptance_criteria>` requires `wc -l` to return ≤ 100.
- **Fix:** Trimmed module docstring + per-function docstrings to one-liners that still cite D-05 / D-06 / T-19-01-02 for traceability. No code-logic change; only comment density.
- **Files modified:** `services/agent/_demo_stubs.py`.
- **Commit:** Folded into GREEN commit `9dde2de` before that commit landed.

### Auth gates / Architectural questions (Rule 4)

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries. Module is internal stub-runtime; T-19-01-02 (Tampering — stale registry) explicitly mitigated by `build_demo_registry` returning a fresh `ToolRegistry()` per call (verified by `test_build_demo_registry_registers_all_tools`).

## Known Stubs

This entire module is intentionally a stub-runtime for the demo (CONTEXT.md D-05 / D-06). No regressive stubs introduced — the stubs replace nothing; they are first-class demo fixtures. Future plans 19-03 (`_demo_runner.py`) and 19-04 (`tests/integration/test_demo_agent.py`) consume these primitives without further stubbing.

## TDD Gate Compliance

| Gate | Commit | Status |
| --- | --- | --- |
| RED  | `33aa014 test(19-01-T1)` | All 7 tests fail with `ModuleNotFoundError` before implementation. Failed-test types are collection-stage `ImportError` (per plan acceptance criterion: "collection-stage error or per-test ImportError"). |
| GREEN | `9dde2de feat(19-01-T2)` | All 7 tests pass. ruff + mypy --strict clean on the new file. Full unit suite remains green. |
| REFACTOR | (none) | Not required — implementation is already minimal (~97 lines, no duplication, no rough edges). The two iterations on docstring length and `name`-shadowing happened pre-commit; the GREEN commit IS the post-refactor state. |

## Self-Check: PASSED

- File `tests/unit/test_demo_stubs.py` exists ✓
- File `services/agent/_demo_stubs.py` exists ✓
- File `.planning/phases/19-agent-first-docs-demo-release/19-01-SUMMARY.md` exists ✓
- Commit `33aa014` exists in `git log` ✓
- Commit `9dde2de` exists in `git log` ✓
- 7/7 tests pass ✓
- ruff clean ✓
- mypy --strict: 0 errors on the new module ✓
- 775 / 1 unit-suite total — zero regressions ✓
