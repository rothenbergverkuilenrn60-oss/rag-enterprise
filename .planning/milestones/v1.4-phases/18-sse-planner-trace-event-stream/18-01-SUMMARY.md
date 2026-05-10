---
phase: 18-sse-planner-trace-event-stream
plan: 01
subsystem: agent / models
tags: [sse, pydantic-v2, tdd, agent-04]
requirements: [AGENT-04]
dependency_graph:
  requires:
    - utils/models.py::ToolPlan (Phase 16)
    - utils/models.py::ToolCall (Phase 16)
    - utils/models.py::ToolResult (Phase 17)
  provides:
    - utils/models.py::AgentEvent (base)
    - utils/models.py::PlannerPlanEvent
    - utils/models.py::ToolSpanStartEvent
    - utils/models.py::ToolSpanEndEvent
    - utils/models.py::ToolSpanErrorEvent
    - utils/models.py::ExecutorParallelEvent
    - utils/models.py::SynthesizerFinalEvent
  affects:
    - services/agent/executor.py (plan 18-02 will yield ToolSpan*Event / ExecutorParallelEvent)
    - services/pipeline.py (plan 18-03 will yield PlannerPlanEvent + SynthesizerFinalEvent)
    - controllers/api.py (plan 18-04 will serialize via event.model_dump_json())
    - docs/agent-architecture.md (plan 18-05 references field names verbatim)
tech_stack:
  added: []
  patterns:
    - "Frozen Pydantic V2 model + ClassVar[str] discriminator (matches ToolResult/ToolCall/ToolPlan precedent)."
    - "model_config re-declared on every concrete subclass — Pydantic V2 does not auto-inherit."
    - "ClassVar fields excluded from model_dump() automatically (Pydantic V2 default)."
key_files:
  created:
    - tests/unit/test_agent_event_models.py
  modified:
    - utils/models.py
decisions:
  - "D-09 / D-15 ordering reconciliation: ExecutorParallelEvent emitted at group END (option c). Plan 18-03 smoke-test expected sequence will reflect this — executor.parallel comes AFTER the group's tool.span.end events."
  - "Removed unused `# type: ignore[misc]` comments on frozen-assignment test lines — Pydantic V2 stubs do not require them; mypy --strict reports unused-ignore otherwise. Kept as Rule 1 auto-fix to maintain mypy --strict cleanliness on the new test file."
  - "AgentEvent base does not declare event_type — it is abstract-by-convention. Each concrete subclass owns its canonical wire-name."
metrics:
  duration_minutes: ~10
  completed_date: 2026-05-09
  tasks_completed: 2
  files_changed: 2
  test_count: 16
---

# Phase 18 Plan 01: AgentEvent + 6 SSE Subclasses — Summary

**One-liner:** Locked the Phase 18 SSE event-class contract by adding a frozen Pydantic V2 `AgentEvent` ABC plus 6 concrete subclasses (`PlannerPlanEvent`, `ToolSpan{Start,End,Error}Event`, `ExecutorParallelEvent`, `SynthesizerFinalEvent`) to `utils/models.py` under a TDD RED→GREEN gate.

## Commits

| Gate | Hash | Message |
|------|------|---------|
| RED   | `6c0ac78` | `test(18-01): RED — add failing tests for AgentEvent + 6 subclasses` |
| GREEN | `e6267c8` | `feat(18-01): GREEN — add AgentEvent + 6 SSE event classes (AGENT-04)` |

Branch: `worktree-agent-a531142033f12a56f` (parallel-executor worktree, base = `77c1697` plan-commit).

## What Shipped

- **`utils/models.py`** (+112 lines): new `STAGE 7 — SSE Trace Events` banner; `AgentEvent` base with shared `trace_id` / `seq` / `ts_ms` fields; 6 frozen subclasses each declaring `event_type: ClassVar[str]` per D-09. `PlannerPlanEvent.plan` typed as `ToolPlan` (no `Any`) so nested validation is preserved through `model_validate_json`. Existing `from typing import Any, Literal` extended to `Any, ClassVar, Literal` (single-line edit, no new import lines added).

- **`tests/unit/test_agent_event_models.py`** (+163 lines, NEW): 16 tests covering — D-09 ClassVar values, frozen enforcement on every subclass (assignment raises `ValidationError`), `model_dump_json()` ↔ `model_validate_json()` round-trip, ClassVar exclusion from `model_dump()`, verbatim args carry-through (D-11 — model performs no scrubbing), `AgentEvent` base does not declare `event_type` (abstract-by-convention guard).

## Verification

| Gate | Result |
|------|--------|
| `pytest tests/unit/test_agent_event_models.py` | **16 passed** in 0.05s |
| `ruff check utils/models.py tests/unit/test_agent_event_models.py` | **All checks passed** |
| `mypy --strict utils/models.py tests/unit/test_agent_event_models.py` | **0 NEW errors** introduced; 1 pre-existing error at `utils/models.py:92` (`list[dict]` type-arg, unrelated `ExtractedDocument.tables` field — left untouched per surgical-changes rule) |
| `grep -c "class.*Event(AgentEvent):" utils/models.py` | **6** (expected 6) |
| `grep -E '^\s*event_type:\s*ClassVar\[str\]' utils/models.py \| wc -l` | **6** (expected 6) |
| `grep "STAGE 7 — SSE Trace Events" utils/models.py` | **1 match** |
| Frozen ConfigDict count delta | **+7** (1 base + 6 subclasses; baseline 4 → after 11) |
| Test collection (`pytest --collect-only`) | **16 tests collected** |

### TDD Gate Compliance

- **RED gate (`6c0ac78`):** Tests written and committed BEFORE implementation. Initial `pytest` exit was non-zero with `ImportError: cannot import name 'AgentEvent' from 'utils.models'` — confirmed expected fail-first behavior. No tests passed unexpectedly during RED (no fail-fast trip).
- **GREEN gate (`e6267c8`):** Implementation lands; all 16 tests pass; ruff + mypy clean over baseline.
- **REFACTOR gate:** None required — implementation is minimal and matches the planned skeleton verbatim.

## Decisions Made

1. **D-09 / D-15 ordering reconciliation — option (c) confirmed.** `ExecutorParallelEvent` is emitted ONCE per parallel group at group **END**, with both `fan_out` and `group_latency_ms` populated. This locks the schema (one event per group, fully-populated `group_latency_ms`) and mandates plan 18-03's smoke-test expected sequence to place `executor.parallel` AFTER the group's `tool.span.end` events. The class docstring documents this contract for downstream plan readers.

2. **Auto-fix (Rule 1 deviation): unused `# type: ignore[misc]`** — the plan-supplied test skeleton included `# type: ignore[misc]` on frozen-assignment lines, but Pydantic V2's installed type stubs do not flag those assignments at the type-check level. With those comments present, `mypy --strict` reports `[unused-ignore]` errors. Removed all 6 occurrences in the GREEN commit so the new test file is mypy-clean. This does NOT weaken any test — `pytest.raises(ValidationError)` still asserts the runtime frozen-enforcement.

3. **`AgentEvent` base is abstract-by-convention.** It declares no `event_type` so concrete subclasses each own their canonical wire-name. Asserted by `test_agent_event_base_has_no_event_type` (one of the 16 tests).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Test-tooling] Removed unused `# type: ignore[misc]` comments on frozen-assignment test lines**
- **Found during:** Task 2 (GREEN verification — `mypy --strict tests/unit/test_agent_event_models.py`)
- **Issue:** 6 unused-ignore mypy errors from comments inherited verbatim from the plan skeleton. Pydantic V2 stubs accept the assignment at type-check time; runtime enforcement (frozen) is what `pytest.raises(ValidationError)` covers — the type:ignore was unnecessary.
- **Fix:** Stripped the `# type: ignore[misc]` suffix from 6 frozen-assignment lines (one per subclass test). Tests still pass; mypy now clean on the test file.
- **Files modified:** `tests/unit/test_agent_event_models.py`
- **Commit:** `e6267c8` (folded into GREEN)

No architectural deviations. Auth gates: none (this plan is pure model definitions, no I/O).

## Wired Outputs (downstream plan compatibility)

- ✅ Plan 18-02 can now `from utils.models import ToolSpanStartEvent, ToolSpanEndEvent, ToolSpanErrorEvent, ExecutorParallelEvent, AgentEvent` without `ImportError`.
- ✅ Plan 18-03 can now `from utils.models import PlannerPlanEvent, SynthesizerFinalEvent`.
- ✅ Plan 18-04 can serialize via `event.model_dump_json()`; named-event SSE form is field-shape stable.
- ✅ Plan 18-05 docs can reference field names from these classes verbatim (field tables in `## Event Schema Reference`).

## Threat Surface Scan

No new trust boundaries introduced. Only Pydantic model definitions; no I/O, no network, no DB writes. Threat register T-18-01 (info disclosure via `args` carrying secrets) remains **accepted** in this plan — verbatim policy locked at D-11; redaction is route-layer responsibility (plan 18-04 inherits via JWT + RLS). T-18-02 (tampering after emit) is **mitigated** — every subclass is frozen and tested.

## Known Stubs

None. Every class has its full set of payload fields wired and validated.

## Self-Check: PASSED

- ✅ `utils/models.py` exists; `STAGE 7` banner at line 524; 6 subclasses present; `ClassVar` import added at line 11.
- ✅ `tests/unit/test_agent_event_models.py` exists; 16 tests collected; all pass.
- ✅ Commit `6c0ac78` (RED) FOUND in `git log`.
- ✅ Commit `e6267c8` (GREEN) FOUND in `git log`.
- ✅ RED commit is parent of GREEN commit (TDD gate sequence valid).
- ✅ No modifications to `STATE.md` or `ROADMAP.md` (orchestrator owns those writes; worktree mode honored).
