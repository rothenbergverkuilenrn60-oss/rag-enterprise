---
phase: 18-sse-planner-trace-event-stream
plan: 02
subsystem: agent / executor
tags: [sse, agent-04, tdd, streaming, asyncio, parallel-fanout]
requirements: [AGENT-04]
dependency_graph:
  requires:
    - utils/models.py::AgentEvent (plan 18-01)
    - utils/models.py::ToolSpanStartEvent (plan 18-01)
    - utils/models.py::ToolSpanEndEvent (plan 18-01)
    - utils/models.py::ToolSpanErrorEvent (plan 18-01)
    - utils/models.py::ExecutorParallelEvent (plan 18-01)
    - services/agent/executor.py::Executor._dispatch_one (Phase 17)
    - services/agent/tools.get_tool_registry (Phase 17)
  provides:
    - services/agent/executor.py::Executor.execute_plan_streaming
  affects:
    - services/pipeline.py (plan 18-03 will call execute_plan_streaming and consume yielded events + results)
    - controllers/api.py (plan 18-04 will serialize the events out of run_streaming)
tech_stack:
  added: []
  patterns:
    - "asyncio.as_completed for completion-order event surfacing (replaces gather for the streaming path)."
    - "BaseException-catching wrapper coroutine ensures as_completed never raises (v1.3 D-01 isolation)."
    - "Mixed yield type — AgentEvent + ToolResult + BaseException — discriminated by isinstance(item, AgentEvent) in plan 18-03."
    - "Pre-allocated span_id_by_idx dict so all ToolSpanStartEvent emit BEFORE any await (Phase 18 D-05 ordering invariant)."
    - "ExecutorParallelEvent emitted at group END with both fan_out + group_latency_ms populated (plan 18-01 planner_decision option c)."
    - "uuid.uuid4().hex[:8] span_id pattern matches Phase 16 trace_id convention."
key_files:
  created:
    - tests/unit/test_executor_streaming.py
  modified:
    - services/agent/executor.py
decisions:
  - "Closure-based per-task wrapper (`_timed`) chosen over an outer try/except around as_completed: catching at the wrapper preserves the start-events-before-gather invariant even if the FIRST scheduled task raises immediately. Outer-loop catch would have leaked the BaseException out before sibling start events fired."
  - "args=dict(tc.arguments) shallow-copies into the frozen ToolSpanStartEvent — D-11 verbatim policy; no scrubbing at this layer (route layer handles tenant isolation via JWT + RLS in plan 18-04)."
  - "chunk_count read from ToolResult.metadata with len(res.chunks) fallback (Phase 17 D-02 convention). Wave 1 model documented this contract; Wave 2 honors it."
metrics:
  duration_minutes: ~6
  completed_date: 2026-05-09
  tasks_completed: 2
  files_changed: 2
  test_count_added: 7
  total_executor_tests_passing: 13
---

# Phase 18 Plan 02: Executor.execute_plan_streaming — Summary

**One-liner:** Added `Executor.execute_plan_streaming` async generator (sibling to `execute_plan`) that yields `ToolSpanStartEvent` before each dispatch awaits, `ToolSpanEndEvent` / `ToolSpanErrorEvent` + bare result as each future resolves via `asyncio.as_completed`, and one `ExecutorParallelEvent` per group at group END — preserving v1.3 D-01 BaseException isolation under a TDD RED→GREEN gate.

## Commits

| Gate  | Hash      | Message                                                                              |
| ----- | --------- | ------------------------------------------------------------------------------------ |
| RED   | `d1249ee` | `test(18-02): RED — failing tests for Executor.execute_plan_streaming`               |
| GREEN | `6701a97` | `feat(18-02): GREEN — Executor.execute_plan_streaming with as_completed (AGENT-04)` |

Branch: `worktree-agent-ab14395c0b707f639` (parallel-executor worktree, base = `a9ed1508` plan-commit on `gsd/v1.3-milestone`).

## What Shipped

- **`tests/unit/test_executor_streaming.py`** (+310 lines, NEW): 7 tests covering — single-step group (3-event sequence), two-group ordering (group 1 fully complete before group 2 starts), BaseException isolation with 200-char `error_message` truncation, `span_id` round-trip start ↔ end-or-error (set equality), `seq` monotonicity via threaded `itertools.count(start=10)`, empty plan emits no yields, and a parity gate asserting `execute_plan` still returns `list[ToolResult]` unchanged. Mock-at-consumer-path convention (D-16): `monkeypatch.setattr("services.agent.executor.get_tool_registry", lambda: stub_registry)`.

- **`services/agent/executor.py`** (+145 lines, −1 line): added `execute_plan_streaming` between existing `execute_plan` and `_dispatch_one`. Imports widened to include `uuid`, `AsyncIterator`, `Iterator`, and 4 new event classes. `execute_plan` body itself is **byte-identical** (sha256 `cf7b48ca…71e5` before and after) — additive change.

The new generator implementation:

1. **Per-group ordering invariant** — pre-allocates `span_id_by_idx: dict[int, str]` for the group, then yields ALL `ToolSpanStartEvent`s before any `await`. Closure-based `_timed(idx)` wrapper catches `BaseException` (`noqa: BLE001`, the v1.3 D-01 contract requires the broad catch since `CancelledError`/`TimeoutError` are `BaseException` subclasses). `asyncio.as_completed(tasks)` surfaces end/error events in completion order, NOT step-index order.
2. **`ExecutorParallelEvent` at group END** — emitted ONCE per group with both `fan_out=len(group)` and `group_latency_ms` populated (Phase 18 plan-01 planner_decision option (c) honored). Logger info line tagged `streaming=True` to distinguish from non-streaming path's identical-shape line.
3. **`chunk_count` read** — `res.metadata.get("chunk_count", len(res.chunks))` per Phase 17 D-02. `content_preview = res.content[:200]`. `error_message = str(res)[:200]`.
4. **`span_id`** — `uuid.uuid4().hex[:8]` per Phase 16 trace_id convention; matched between every start↔end/error pair (test 4 enforces).

## Verification

| Gate                                                                                       | Result                                                                       |
| ------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `pytest tests/unit/test_executor_streaming.py -x`                                          | **7 passed** in 0.86s (Task 1 contract)                                      |
| `pytest tests/unit/test_executor.py -x`                                                    | **6 passed** (parity preserved — pre-existing tests untouched)               |
| `pytest tests/unit/test_executor_streaming.py tests/unit/test_executor.py tests/unit/test_agent_event_models.py` | **29 passed** in 0.59s                                  |
| `pytest tests/unit/test_executor_streaming.py --collect-only -q`                           | **7 tests collected**                                                        |
| `ruff check services/agent/executor.py tests/unit/test_executor_streaming.py`              | **All checks passed!**                                                       |
| `mypy --strict services/agent/executor.py` — errors in target file                         | **0 errors** in `services/agent/executor.py` (121 unrelated errors in other files — same baseline as before) |
| `grep -c "async def execute_plan_streaming" services/agent/executor.py`                    | **1**                                                                        |
| `grep -c "async def execute_plan" services/agent/executor.py`                              | **2** (`execute_plan` + `execute_plan_streaming`)                            |
| `grep -c "asyncio.as_completed(" services/agent/executor.py`                               | **1** (the only call site)                                                   |
| `git diff` for `execute_plan` body — sha256 of method body before vs after                 | `cf7b48caf75a71e5` == `cf7b48caf75a71e5` (**byte-identical**)                |
| `git diff --diff-filter=D --name-only HEAD~1 HEAD`                                         | empty (no deletions in GREEN commit)                                         |

### TDD Gate Compliance

- **RED gate (`d1249ee`):** Tests written and committed BEFORE implementation. Initial pytest exit was non-zero with `AttributeError: 'Executor' object has no attribute 'execute_plan_streaming'`. RED test count: 7. No tests passed unexpectedly during RED — fail-fast gate not tripped.
- **GREEN gate (`6701a97`):** Implementation lands; all 7 streaming tests + 6 parity tests pass; ruff clean; mypy `--strict` introduces 0 NEW errors over baseline on the target file.
- **REFACTOR gate:** Not required — implementation matches the planned skeleton without rework.

## Decisions Made

1. **Closure-based per-task BaseException catch.** The `_timed(idx)` wrapper coroutine catches `BaseException` itself rather than relying on an outer try/except around the `as_completed` loop. This guarantees that even if the FIRST task raises immediately (before sibling start-events fire), the start-events-before-gather invariant is preserved — `as_completed` never sees an unwrapped exception. The `# noqa: BLE001` is required because v1.3 D-01 mandates the broad catch (`CancelledError`/`TimeoutError` are `BaseException` subclasses, not `Exception`); ruff's blind-except lint is suppressed inline at the single allowed site.

2. **`args=dict(tc.arguments) if tc.arguments else {}` shallow copy** at the `ToolSpanStartEvent` boundary. The frozen event model accepts the dict; the shallow copy ensures the event's bound dict is stable even if the upstream `ToolCall.arguments` is later mutated (it shouldn't be, since `ToolCall` itself is frozen, but defense-in-depth at the trust boundary is cheap). Verbatim policy preserved per D-11 — no scrubbing.

3. **`asyncio.as_completed` chosen over `asyncio.wait(FIRST_COMPLETED)` loop.** Both satisfy D-05; `as_completed` is the simpler idiom, returns futures in completion order, and matches the natural reading order of "yield each event as the corresponding task finishes." The plan's "Claude's Discretion" section permitted any of the 3 candidate approaches; option (a) was the cleanest fit.

4. **`raw_assistant_msg` and `stop_reason` populated in test plans.** Plan 18-01's `ToolPlan` validator does not require these to be non-default, but populating them in test fixtures (`raw_assistant_msg={"role": "assistant", "content": "x"}`, `stop_reason="tool_use"`) mirrors the realistic shape that plan 18-03 will pass at runtime — keeps the test surface representative of production input.

## Deviations from Plan

**None.** Plan executed exactly as written. The `<action>` skeleton in 18-02-PLAN.md was followed line-by-line (with one cosmetic adjustment: minor docstring formatting for line-length, no semantic change). No Rule 1/2/3 auto-fixes triggered. No checkpoints encountered (plan was fully autonomous). No authentication gates.

The `mypy --strict services/agent/executor.py` run reports 121 errors total, but **all 121 are in unrelated files** (mostly `services/retriever/retriever.py`); the target file `services/agent/executor.py` itself has **0 errors**, which matches the pre-plan baseline.

## Wired Outputs (downstream plan compatibility)

- ✅ Plan 18-03 can `from services.agent.executor import Executor` and call `executor.execute_plan_streaming(plan, tf, req, trace_id="…", seq_counter=itertools.count())` with the documented keyword-only signature.
- ✅ Mixed yield type means plan 18-03's orchestrator can do `if isinstance(item, AgentEvent): yield_to_sse(item) else: collect_result(item)` for clean event-vs-result discrimination.
- ✅ `ExecutorParallelEvent.fan_out` lights up the latency assertion (D-14, ROADMAP SC4) — plan 18-03's smoke test will assert `executor.parallel.fan_out == 4` for the 4-tool latency proof.
- ✅ Plan 18-04 SSE serialization uses `event.model_dump_json()` exactly — no shape changes needed at the route layer beyond what plan 18-01 already gave it.

## Threat Surface Scan

No new trust boundaries introduced. No new I/O surface (no network, no DB writes, no filesystem touches). The streaming method is a pure orchestration sibling of `execute_plan` reusing the same `_dispatch_one` and `get_tool_registry` consumer contracts.

Threat-register status from plan 18-02:
- **T-18-03** (info disclosure via `error_message`): **mitigated** — emitter truncates to `str(exc)[:200]`; test 3 enforces `len(error_message) == 200` exactly. Full traceback stays in `logger.error` server-side only.
- **T-18-04** (info disclosure via `args`): **accepted** — verbatim per D-11; route-layer JWT+RLS isolation preserved (plan 18-04 territory).
- **T-18-05** (long-running tool blocks `as_completed`): **accepted** — existing tool-level Tenacity timeouts carry forward unchanged.
- **T-18-06** (mutation after emit): **mitigated** — all event classes frozen (asserted in plan 18-01).

No new threat flags. No new security-relevant surface introduced beyond what plan 18-01 already locked.

## Known Stubs

None. `execute_plan_streaming` is fully wired:
- Real `_dispatch_one` invocation (no placeholder).
- Real per-task `time.perf_counter()` latency measurement.
- Real `get_tool_registry()` consumer-path indirection (mocked only at test boundary).
- Real `BaseException` capture and event emission.

The non-streaming `execute_plan` is unchanged and continues to serve the legacy `/query?agent_mode=true` non-streaming path.

## Self-Check: PASSED

- ✅ `tests/unit/test_executor_streaming.py` exists with 7 `async def test_execute_plan_streaming_*` functions (verified via `grep -c`).
- ✅ `services/agent/executor.py::Executor.execute_plan_streaming` exists (verified via `grep -c "async def execute_plan_streaming"` == 1).
- ✅ `services/agent/executor.py::Executor.execute_plan` still exists alongside (verified via `grep -c "async def execute_plan"` == 2).
- ✅ Commit `d1249ee` (RED) FOUND in `git log --all`.
- ✅ Commit `6701a97` (GREEN) FOUND in `git log --all`.
- ✅ RED commit is parent of GREEN commit (TDD gate sequence valid; verified via `git log --oneline -3`).
- ✅ `execute_plan` body sha256 unchanged (`cf7b48caf75a71e5` matches pre-plan baseline `a9ed1508`).
- ✅ Working tree clean after GREEN commit (`git status --short` returned empty).
- ✅ No file deletions in GREEN commit (`git diff --diff-filter=D --name-only HEAD~1 HEAD` empty).
- ✅ No modifications to `STATE.md` or `ROADMAP.md` (parallel-executor convention honored — orchestrator owns those writes).
