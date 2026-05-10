---
phase: 18-sse-planner-trace-event-stream
plan: 03
subsystem: agent / pipeline
tags: [sse, agent-04, tdd, streaming, async-generator, pipeline-orchestrator]
requirements: [AGENT-04]
dependency_graph:
  requires:
    - utils/models.py::AgentEvent (plan 18-01)
    - utils/models.py::PlannerPlanEvent (plan 18-01)
    - utils/models.py::SynthesizerFinalEvent (plan 18-01)
    - utils/models.py::ToolSpanStartEvent (plan 18-01)
    - utils/models.py::ToolSpanEndEvent (plan 18-01)
    - utils/models.py::ToolSpanErrorEvent (plan 18-01)
    - services/agent/executor.py::Executor.execute_plan_streaming (plan 18-02)
  provides:
    - services/pipeline.py::AgentQueryPipeline.run_streaming
  affects:
    - controllers/api.py (plan 18-04 will consume `async for evt in pipeline.run_streaming(req)` directly)
    - docs/agent-architecture.md (plan 18-05 references the orchestrator's emit boundaries)
tech_stack:
  added: []
  patterns:
    - "async-generator orchestrator — yields AgentEvent at each lifecycle boundary; bare ToolResult / BaseException collected internally."
    - "span_id_to_step_idx pairing — flat parallel-group iteration order binds span_id on start; end/error events buffer step_idx for the next bare-result yield (preserves correctness even when as_completed surfaces results out of plan.steps order)."
    - "_pending_idx: int = -1 sentinel initialized BEFORE the executor loop — defensive against contract-violating yield order; no UnboundLocalError surface."
    - "Single shared itertools.count() seq counter threaded into Executor — guarantees strict-monotonic seq across pipeline + executor events."
    - "_persist_turn invoked AFTER yielding SynthesizerFinalEvent — audit / multi-tenant memory shape unchanged (security_gate, T-18-08)."
    - "AgentQueryPipeline.run is byte-identical (sha256 36dcb84a49789919 before and after) — additive sibling-method augmentation only."
key_files:
  created:
    - tests/unit/test_agent_sse.py
  modified:
    - services/pipeline.py
decisions:
  - "TDD task split (RED → GREEN minimal → REFACTOR) executed verbatim. RED commit lands 9 failing tests; GREEN-minimal lands run_streaming with in-order next_slot pairing (5/9 tests pass — single-step paths only); REFACTOR replaces in-order pairing with span_id_to_step_idx + flat_idx_order to handle out-of-order multi-tool parallel resolution (9/9 tests pass)."
  - "Auto-fix Rule 1 (lint hygiene): added `# noqa: F401` on ExecutorParallelEvent in the top-level utils.models import. The class is hoisted to the top per plan acceptance criteria but never isinstance-checked in pipeline.py — the executor emits it and the pipeline forwards it via the AgentEvent superclass discriminator. Three other ToolSpan*Event classes lost their noqa in Task 2b after their isinstance discriminators were added by the refactor."
  - "Two-path get_tool_registry mock (D-16 belt-and-braces): test fixture patches both `services.agent.executor.get_tool_registry` AND `services.pipeline.get_tool_registry`. The pipeline-path call site (line 837 in run_streaming) computes the planner-tools schema list, while the executor-path call site (line 248 in _dispatch_one) resolves tool classes during dispatch — both get patched so the test is deterministic regardless of internal wiring."
metrics:
  duration_minutes: ~12
  completed_date: 2026-05-09
  tasks_completed: 3
  files_changed: 2
  test_count_added: 9
  total_passing_tests_post_plan: 49  # 9 (this plan) + 7 (executor_streaming) + 6 (executor) + 16 (event_models) + 11 (agent_pipeline_refactor)
---

# Phase 18 Plan 03: AgentQueryPipeline.run_streaming — Summary

**One-liner:** Added `AgentQueryPipeline.run_streaming` async generator (sibling to existing `run`) that drives the same Planner / Executor / Synthesizer flow but yields typed `AgentEvent` instances at each lifecycle boundary — `PlannerPlanEvent` after each planner call, executor span/parallel events forwarded from `Executor.execute_plan_streaming` (plan 18-02) with span-id pairing, and exactly one terminal `SynthesizerFinalEvent` — under a TDD RED → GREEN-minimal → REFACTOR gate.

## Commits

| Gate            | Hash      | Message                                                                                          |
| --------------- | --------- | ------------------------------------------------------------------------------------------------ |
| RED             | `1a64132` | `test(18-03): RED — failing tests for AgentQueryPipeline.run_streaming`                          |
| GREEN (minimal) | `50f0e2a` | `feat(18-03): GREEN minimal — AgentQueryPipeline.run_streaming single-step body (AGENT-04)`     |
| REFACTOR        | `116fe1b` | `refactor(18-03): REFACTOR — span_id pairing for multi-tool parallel groups (AGENT-04)`         |

Branch: `worktree-agent-ac6e6615d826e22f7` (parallel-executor worktree, base = `b70fcae` plan-commit on `gsd/v1.3-milestone`).

## What Shipped

### `tests/unit/test_agent_sse.py` (+385 lines, NEW)

9 async tests covering the four ROADMAP Phase 18 success criteria scoped to this plan plus the D-11 / D-12 invariants:

| Test | Coverage |
|------|----------|
| `test_run_streaming_emits_planner_plan_first` | SC1 — first event is `PlannerPlanEvent` carrying full `ToolPlan`. |
| `test_run_streaming_smoke_sequence_d15` | SC3 — D-15 fixture (`parallel_groups=[[0],[1,2,3]]`) yields exactly 12 events: 1 planner + 4 starts + 4 ends + 2 parallel (fan_out 1, 3) + 1 final. |
| `test_run_streaming_latency_bounded_by_max_not_sum_d14_sc4` | SC4 — 4 tools × 0.5s each in one group of 4 finishes in `(450, 700) ms`, NOT `~2000ms`. |
| `test_run_streaming_redaction_args_verbatim_content_truncated_d11` | D-11 — `args` verbatim (`{"password": "secret-x", "k": 1}`) in `tool.span.start`; 500-char content truncated to exact 200-char `content_preview` in `tool.span.end`. |
| `test_run_streaming_error_event_replaces_end_d12` | D-12 — `RuntimeError("kaboom-" + 250×"x")` produces exactly one `ToolSpanErrorEvent` with `error_type == "RuntimeError"` and `len(error_message) == 200`; the failing `span_id` does NOT appear in any `ToolSpanEndEvent`; sibling tool emits a normal end event. |
| `test_run_streaming_synthesizer_final_terminal` | D-07 — last yielded event is `SynthesizerFinalEvent` with `answer` equal to the terminal plan's `rationale`. |
| `test_run_streaming_seq_monotonic_across_planner_and_executor` | D-08 — `[e.seq for e in events]` is strictly increasing AND every `seq` is unique. |
| `test_run_streaming_persist_turn_called_once` | T-18-08 mitigation — `_persist_turn` invoked exactly once after the synthesizer.final yield. |
| `test_run_streaming_does_not_break_run` | parity gate — existing `run()` non-streaming method still returns a `GenerationResponse` with the expected shape. |

Mock-at-consumer-path discipline (D-16): all six pipeline-side singletons (`get_memory_service`, `get_audit_service`, `get_tenant_service`, `get_filter_extractor`, `get_planner`, `get_executor`, `get_llm_client`, `get_retriever`) plus both `get_tool_registry` accessors (`services.pipeline.get_tool_registry` AND `services.agent.executor.get_tool_registry`) patched at the consumer side. Real `Executor` instance constructed inside the fixture so the `execute_plan_streaming` path is exercised end-to-end against a stub `ToolRegistry`.

### `services/pipeline.py` (+155 lines, −1 line)

- **Imports widened** (top-of-file edits only):
  - `import itertools` added (alphabetical position between `hashlib` and `json`).
  - `AsyncIterator` added to the existing `from typing import Any, AsyncGenerator` line.
  - 6 event classes hoisted to the top-level `from utils.models import (...)` block: `AgentEvent`, `ExecutorParallelEvent`, `PlannerPlanEvent`, `SynthesizerFinalEvent`, `ToolSpanEndEvent`, `ToolSpanErrorEvent`, `ToolSpanStartEvent`. **Zero inline method-level imports** (acceptance grep confirms).

- **New `run_streaming` method** (147 LOC, after the unchanged `run` method, before module-level `_ingest_pipeline = None`):

  ```python
  async def run_streaming(self, req: GenerationRequest) -> AsyncIterator[AgentEvent]:
      ...
      trace_id = uuid.uuid4().hex[:8]
      seq_counter = itertools.count()
      ...
      for iteration in range(MAX_ITERATIONS):
          plan = await planner.plan_from_messages(...)
          if not plan.steps:
              answer = plan.rationale or answer
              break
          yield PlannerPlanEvent(trace_id, seq=next(seq_counter), ts_ms=..., plan=plan)
          ...
          # Span-id pairing (Task 2b refactor)
          raw_outputs = [None] * len(plan.steps)
          flat_idx_order = [idx for group in plan.parallel_groups for idx in group]
          flat_pos = 0
          span_id_to_step_idx: dict[str, int] = {}
          _pending_idx: int = -1
          async for item in executor.execute_plan_streaming(plan, tf, req,
                                                            trace_id=trace_id,
                                                            seq_counter=seq_counter):
              if isinstance(item, AgentEvent):
                  yield item
                  if isinstance(item, ToolSpanStartEvent):
                      if flat_pos < len(flat_idx_order):
                          span_id_to_step_idx[item.span_id] = flat_idx_order[flat_pos]
                          flat_pos += 1
                  elif isinstance(item, (ToolSpanEndEvent, ToolSpanErrorEvent)):
                      _pending_idx = span_id_to_step_idx.get(item.span_id, -1)
              else:
                  if 0 <= _pending_idx < len(raw_outputs):
                      raw_outputs[_pending_idx] = item
                      _pending_idx = -1
          ...
      yield SynthesizerFinalEvent(trace_id, seq=next(seq_counter), ts_ms=..., answer=..., sources_count=...)
      await self._persist_turn(req, answer, all_chunks, trace_id, t0, parallelism_factors)
  ```

- **Existing `AgentQueryPipeline.run` body byte-identical.** Confirmed: extract method body via regex, sha256 baseline (`HEAD~3:services/pipeline.py`) = `36dcb84a49789919`; sha256 current = `36dcb84a49789919`. The 1-line "−1" delta in the GREEN-minimal commit is the trailing-newline change between `return await self._persist_turn(...)` and the inserted blank line that precedes `run_streaming` — the `run` method body itself is unchanged.

- **Pairing strategy (REFACTOR phase landed at `116fe1b`):** the executor (plan 18-02) emits `ToolSpanStartEvent` in flat parallel-group iteration order (across `plan.parallel_groups`), then yields `ToolSpanEndEvent` (or `ToolSpanErrorEvent`) IMMEDIATELY before each bare result. Within a group, results may surface in `as_completed` order — NOT plan.steps order. Pipeline-side, `flat_idx_order` captures the executor's start-event order; `span_id_to_step_idx` binds each span on its start; `_pending_idx` buffers the resolved step idx between an end/error event and its bare-result yield. Multi-tool group of 4 with 0.5s sleeps satisfies the latency bound deterministically (3/3 dry-runs all 500ms call-time).

## Verification

| Gate | Result |
|------|--------|
| `pytest tests/unit/test_agent_sse.py -v` (after Task 2b) | **9 passed** in 1.17s |
| `pytest tests/unit/test_executor_streaming.py tests/unit/test_executor.py tests/unit/test_agent_event_models.py tests/unit/test_agent_pipeline_refactor.py` | **40 passed** (no regressions across plans 18-01, 18-02, and earlier) |
| Combined sweep: 9 + 7 + 6 + 16 + 11 | **49 passed** in 1.25s |
| `pytest tests/unit/test_agent_sse.py --collect-only -q` | **9 tests collected** |
| `ruff check services/pipeline.py` | **All checks passed!** |
| `mypy --strict services/pipeline.py` errors total | **11** (all pre-existing in lines 465 / 753 / 796 / 956–968 / 1203 / 1246 / 1283 — unrelated; baseline matches `HEAD~3` baseline of 11) |
| `mypy --strict` errors INSIDE `run_streaming` body (lines 822–949) | **0** |
| `grep -c "async def run_streaming" services/pipeline.py` | **1** |
| `grep -cE "async def run\b" services/pipeline.py` | **4** (Ingest + Query + Agent + Swarm) |
| `grep -c "import itertools" services/pipeline.py` | **1** |
| `grep -nE "^\s+from utils\.models import" services/pipeline.py` (inline imports) | **0** (only the top-level block) |
| `grep -c "next_slot" services/pipeline.py` | **0** (Task 2a helper removed in 2b) |
| `grep -c "span_id_to_step_idx" services/pipeline.py` | **3** (declaration + bind + lookup) |
| `grep -c "flat_idx_order" services/pipeline.py` | **4** (declaration + iter + indexing + length check) |
| `grep -nE "_pending_idx\s*:\s*int\s*=\s*-1" services/pipeline.py \| wc -l` | **1** (initialized exactly once, before the loop) |
| `grep -c "last_announced_span_in_group\|group_step_iter" services/pipeline.py` | **0** (no dead variables from earlier draft) |
| `git diff HEAD~3 services/pipeline.py \| grep -E '^-\s+async def run\(' \| grep -v '^---'` | empty (no removed `async def run(` lines) |
| `AgentQueryPipeline.run` body sha256 (regex-extracted, baseline vs current) | `36dcb84a49789919` == `36dcb84a49789919` (**byte-identical**) |
| Latency-test 3-run actual `--durations` call-time (D-14 / SC4) | **0.50s, 0.50s, 0.50s** (all three runs satisfied `450 < elapsed_ms < 700` deterministically) |
| `git diff --diff-filter=D --name-only HEAD~3 HEAD` | empty (no file deletions across the three commits) |

### TDD Gate Compliance

- **RED gate (`1a64132`):** 9 failing tests committed BEFORE implementation. Initial pytest exit non-zero with `AttributeError: 'AgentQueryPipeline' object has no attribute 'run_streaming'` — confirmed expected fail-first behavior. No tests passed unexpectedly during RED (no fail-fast trip). Earlier-plan tests still passed (29 across 18-01 + 18-02 + legacy executor).
- **GREEN-minimal gate (`50f0e2a`):** Implementation lands; 5 of 9 streaming tests pass (`planner_plan_first`, `synthesizer_final_terminal`, `seq_monotonic`, `persist_turn_called_once`, `does_not_break_run`); the other 4 (smoke / latency / redaction / error path) deferred to REFACTOR per plan split. Ruff clean; mypy `--strict` 0 NEW errors; 40 regression tests pass.
- **REFACTOR gate (`116fe1b`):** In-order `next_slot` pairing replaced with `span_id_to_step_idx` + `flat_idx_order` + `_pending_idx` for multi-tool parallel correctness. All 9 streaming tests pass; ruff still clean; mypy `--strict` still 0 NEW errors; 40 regression tests still pass.

## Decisions Made

1. **TDD task split (RED → GREEN-minimal → REFACTOR) executed verbatim.** Plan-prescribed three-commit structure preserved: RED commits failing tests; GREEN-minimal commits the simplest in-order pairing that passes single-step tests; REFACTOR replaces the pairing strategy for multi-tool correctness. No commits were squashed or reordered.

2. **Two-path `get_tool_registry` mock for the test fixture (D-16 belt-and-braces).** The pipeline-path call (`services.pipeline.get_tool_registry()` line 836 inside `run_streaming` for planner-tools schema) and the executor-path call (`services.agent.executor.get_tool_registry()` line 248 inside `_dispatch_one`) are both consumer paths the test cares about. Patching only one of them would leave the other holding the real (production) registry — flaky on CI. Patching both keeps the test deterministic regardless of how internal wiring evolves.

3. **`_pending_idx: int = -1` initialized BEFORE the `async for` loop.** The plan acceptance criterion explicitly enforces this (`grep -nE "_pending_idx\s*:\s*int\s*=\s*-1" ... | wc -l == 1`). Initializing inside the conditional branches would surface as `UnboundLocalError` if the executor ever yielded a bare result before its corresponding end/error event (a contract violation, but defensive coding handles the case gracefully — drop the result, defensive `RuntimeError("missing executor result")` fallback below converts the unfilled slot into a controlled is_error tool_result that `_build_tool_results` already handles).

4. **`# noqa: F401` retained on `ExecutorParallelEvent` only.** The class is forwarded through the SSE stream via the `AgentEvent` superclass discriminator (`isinstance(item, AgentEvent)`); no isinstance check on the concrete type is needed pipeline-side. The other three `ToolSpan*Event` classes lost their `noqa` in the REFACTOR commit because Task 2b's pairing logic adds explicit `isinstance(item, ToolSpanStartEvent)` / `isinstance(item, (ToolSpanEndEvent, ToolSpanErrorEvent))` discriminators.

5. **`trace_id = uuid.uuid4().hex[:8]` (hex form), NOT `str(uuid.uuid4())[:8]`.** Per CONTEXT.md "Claude's Discretion" — Phase 18 convention adopts the `.hex[:8]` form (8 hex chars, no dashes) matching the executor span_id pattern from plan 18-02. Existing `AgentQueryPipeline.run` keeps its older `str(uuid.uuid4())[:8]` form — the parity gate (`run` byte-identical) requires this; future cleanup to unify the two could land in v1.5+.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Lint hygiene] Added `# noqa: F401` to four hoisted event-class imports in Task 2a, removed three of them in Task 2b**
- **Found during:** Task 2a verification (`ruff check services/pipeline.py` reported F401 unused-imports on `ExecutorParallelEvent`, `ToolSpanEndEvent`, `ToolSpanErrorEvent`, `ToolSpanStartEvent`)
- **Issue:** Plan acceptance for Task 2a required BOTH (a) ruff exits 0 AND (b) the top-level `from utils.models import (...)` block contains the four event class names. The four classes were hoisted in Task 2a per (b) but never referenced in Task 2a's body (only the `AgentEvent` superclass is referenced via the `isinstance` discriminator). Without `noqa`, ruff F401 would block the Task 2a commit.
- **Fix:** Added `# noqa: F401 — hoisted for Task 2b span_id pairing refactor` to the four affected lines in Task 2a's commit. Task 2b's refactor adds explicit `isinstance(item, ToolSpanStartEvent)` / `isinstance(item, (ToolSpanEndEvent, ToolSpanErrorEvent))` discriminators, making three of the noqa comments unnecessary — those three were removed in Task 2b. Only `ExecutorParallelEvent` retains the noqa (with an updated comment) because the class is forwarded through the SSE stream via the superclass discriminator and never directly isinstance-checked pipeline-side.
- **Files modified:** `services/pipeline.py` (top-level import block only)
- **Commits:** `50f0e2a` (added 4× noqa), `116fe1b` (removed 3× noqa, kept 1×)

No Rule 4 architectural deviations. No checkpoints encountered (plan was fully autonomous). No authentication gates.

## Wired Outputs (downstream plan compatibility)

- ✅ Plan 18-04 can `pipeline = get_agent_pipeline()` and consume `async for evt in pipeline.run_streaming(req): yield f"event: {evt.event_type}\ndata: {evt.model_dump_json()}\n\n"` directly inside the FastAPI `/agent/v1/run/stream` route handler. No additional adapter required.
- ✅ Plan 18-05 docs can describe the orchestrator's emit boundaries verbatim: `PlannerPlanEvent` after planner success, span events forwarded from executor, `SynthesizerFinalEvent` exactly once at stream end. Field names + types stable from plan 18-01.
- ✅ The `_persist_turn` audit/memory call site continues to fire on every `run_streaming` invocation — multi-tenant audit shape preserved (T-18-08 mitigation in place; Test 8 enforces).
- ✅ Span-id-to-step-idx pairing strategy landed: `flat_idx_order` (4 grep occurrences) + `span_id_to_step_idx` (3 grep occurrences) confirmed in `services/pipeline.py`. This unlocks plan 18-04's confidence that multi-group multi-tool plans surface correct tool_results back into the message history regardless of `as_completed` resolution order.

## Threat Surface Scan

No new trust boundaries introduced. No new I/O surface (no network, no DB writes, no filesystem touches beyond the existing `_persist_turn` audit path). The streaming method is a pure orchestration sibling of `run` reusing the same `_build_tf` / `_build_initial_messages` / `_build_tool_results` / `_dedup_chunks` / `_persist_turn` helpers verbatim.

Threat-register status from plan 18-03:

- **T-18-07** (cross-tenant leak via SSE event payload): **mitigated** — `tenant_id` from JWT threads through `_build_tf` → `req.tenant_id` → executor → tool dispatch unchanged. RLS enforced at tool's DB call site (Phase 17 D-02 untouched here). Test `_persist_turn_called_once` ensures audit log fires per tenant.
- **T-18-08** (skipped audit on streaming path): **mitigated** — `_persist_turn` is unconditional; `test_run_streaming_persist_turn_called_once` asserts call count == 1.
- **T-18-09** (verbose `args` carrying secrets in `tool.span.start`): **accept** (per D-11) — `test_run_streaming_redaction_args_verbatim_content_truncated_d11` confirms verbatim policy is intentional and locked at this layer.
- **T-18-10** (long-running stream consumes connection budget): **mitigated at route layer** (plan 18-04 will add `@_limiter.limit(rate_limit_query_rpm/minute)`). MAX_ITERATIONS=5 already caps total work pipeline-side.
- **T-18-11** (mutating `messages` list mid-stream): **accept** — `messages` is method-local; no concurrent mutation risk. Frozen events themselves cannot be tampered (plan 18-01 + 18-02 gate).

No new threat flags. No new security-relevant surface introduced beyond what plans 18-01 and 18-02 already locked.

## Known Stubs

None. `run_streaming` is fully wired:

- Real `_build_tf` invocation (delegates to `_filter_extractor.extract` + `_tenant_svc.get_tenant_filter`).
- Real `_memory.load_context` invocation.
- Real `Planner.plan_from_messages` invocation (mocked only at the test boundary via `_StubPlanner`).
- Real `Executor.execute_plan_streaming` invocation (mocked only at the registry boundary per D-16).
- Real `_build_tool_results` + `_dedup_chunks` invocation.
- Real `_persist_turn` invocation (audit log + memory turn save).

The legacy non-streaming `AgentQueryPipeline.run` is unchanged (sha256 verified) and continues to serve `/query?agent_mode=true`.

## Self-Check: PASSED

- ✅ `tests/unit/test_agent_sse.py` exists with 9 `async def test_run_streaming_*` functions (verified via `grep -c "^async def test_" tests/unit/test_agent_sse.py` == 9).
- ✅ `services/pipeline.py::AgentQueryPipeline.run_streaming` exists (verified via `grep -c "async def run_streaming" services/pipeline.py` == 1).
- ✅ `services/pipeline.py::AgentQueryPipeline.run` body byte-identical (sha256 `36dcb84a49789919` matches HEAD~3 baseline).
- ✅ Commit `1a64132` (RED) FOUND in `git log --all`.
- ✅ Commit `50f0e2a` (GREEN minimal) FOUND in `git log --all`.
- ✅ Commit `116fe1b` (REFACTOR) FOUND in `git log --all`.
- ✅ RED → GREEN-minimal → REFACTOR chain is linear (verified via `git log --oneline -3`).
- ✅ All 9 tests pass after REFACTOR; all 40 regression tests pass; combined 49 passed in 1.25s.
- ✅ Working tree clean after REFACTOR commit (`git status --short` returned empty).
- ✅ No file deletions across the three commits (`git diff --diff-filter=D --name-only HEAD~3 HEAD` empty).
- ✅ No modifications to `STATE.md` or `ROADMAP.md` (parallel-executor convention honored — orchestrator owns those writes).
- ✅ No `last_announced_span_in_group` or `group_step_iter` dead variables present (acceptance grep == 0).
- ✅ `_pending_idx: int = -1` initialized exactly once before the executor `async for` loop (acceptance grep == 1).
- ✅ Event-class imports at top-level only — zero inline method-level `from utils.models import ...` matches.
