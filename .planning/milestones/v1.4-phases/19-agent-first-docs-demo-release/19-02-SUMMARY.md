---
phase: 19-agent-first-docs-demo-release
plan: 02
subsystem: services/agent
tags: [agent-08, tdd, demo-runner, phase-19, wave-2, sc3, sc4]
requires:
  - services.agent._demo_stubs.{DEMO_QUERY, DemoStubPlanner, build_demo_registry, make_fake_retrieve_tool}  # Phase 19 plan 19-01
  - services.pipeline.AgentQueryPipeline  # Phase 18
  - services.agent.executor.Executor  # Phase 16
  - utils.models.{AgentEvent, GenerationRequest, PlannerPlanEvent, ToolSpanStartEvent, ToolSpanEndEvent, ExecutorParallelEvent, SynthesizerFinalEvent}
provides:
  - services.agent._demo_runner.run_demo  # async, returns list[AgentEvent]
  - services.agent._demo_runner.emit_sse_frame  # SSE wire format helper
  - services.agent._demo_runner.validate_event_shape  # D-06 event-count gate
  - services.agent._demo_runner.main  # sync CLI entrypoint, rc 0|1
  - services.agent._demo_runner.__main__  # `python -m services.agent._demo_runner`
affects:
  - Makefile (consumer — plan 19-03 `make demo-agent` target invokes this runner)
  - docs/demo.cast (consumer — `make demo-agent-record` wraps this runner under asciinema)
tech-stack:
  added: []
  patterns:
    - mock-at-consumer-path (v1.3 D-16; runtime equivalent via unittest.mock.patch ExitStack)
    - SSE-wire-format (verbatim from controllers/api.py:282)
    - tdd-red-green (RED test commit before GREEN implementation commit)
key-files:
  created:
    - tests/integration/test_demo_agent.py (245 lines, 6 tests)
    - services/agent/_demo_runner.py (126 lines)
  modified: []
decisions:
  - subprocess-uses-sys-executable-not-conda: "Plan 19-01 deviation #1 inherited — this machine has no conda binary; subprocess in Test 6 uses sys.executable (the running .venv interpreter) instead of the plan-template `conda run -n torch_env python`. Same Python version (3.12.13), same dependency set, same pytest config."
  - mypy-attr-defined-ignore-on-event_type: "AgentEvent base class declares no event_type attribute — concrete subclasses each declare ClassVar[str] (utils/models.py:552-628). Adding event_type to the base would touch utils/models.py (out of scope; pre-existing baseline of 296 mypy errors). Used `# type: ignore[attr-defined]` on the single access site, with a comment naming the controllers/api.py:282 consumer that implicitly relies on the same shape."
  - integration-tests-via-explicit-path: "Project pytest.ini sets `addopts = -m 'not integration'` to exclude marker-tagged integration tests by default. The new tests/integration/test_demo_agent.py uses NO `@pytest.mark.integration` (matching the convention of every other file in tests/integration/), so it runs by default when invoked as `pytest tests/integration/test_demo_agent.py -o addopts=`. Subprocess Test 6 uses `--timeout=10` for fail-fast behavior."
metrics:
  duration_minutes: 8
  tasks_completed: 2
  commits: 2
  files_created: 2
  files_modified: 0
  tests_added: 6
  unit_suite_passed: 775
  unit_suite_skipped: 1
  integration_tests_passed: 6
  mypy_strict_new_errors: 0
  ruff_errors: 0
  runner_lines: 126
  test_lines: 245
  completed_date: 2026-05-09
---

# Phase 19 Plan 02: Demo Runner + Integration Test — Summary

**One-liner:** Build the demo correctness gate — 6 integration tests in `tests/integration/test_demo_agent.py` lock the 11-event sequence + 4-way fan-out + max-not-sum latency bound (450 < elapsed_ms < 700) — then implement `services/agent/_demo_runner.py` (126 lines) that wires the plan-19-01 stubs into `AgentQueryPipeline.run_streaming` via `unittest.mock.patch` ExitStack, prints SSE frames to stdout, and exits 0/1 on shape match (D-06).

## Tasks Executed

| Task        | Commit    | Files                                                                  | Status |
| ----------- | --------- | ---------------------------------------------------------------------- | ------ |
| T1 (RED)    | `d8f7425` | `tests/integration/test_demo_agent.py` (245 lines, 6 tests)            | RED gate satisfied — Tests 1-5 fail with `ModuleNotFoundError: services.agent._demo_runner`; Test 6 fails with subprocess `returncode=1` + `No module named services.agent._demo_runner` on stderr. |
| T2 (GREEN)  | `db232f3` | `services/agent/_demo_runner.py` (126 lines)                           | GREEN gate satisfied — 6/6 tests pass in 5.0s; `python -m services.agent._demo_runner` exits 0; ruff clean; mypy --strict 0 new errors; full unit suite 775/1 (no regression). |

## Public Exports

`services/agent/_demo_runner.py` (126 lines, ≤ 130 budget):

| Symbol                  | Kind        | Contract |
| ----------------------- | ----------- | -------- |
| `run_demo`              | async fn    | `() -> list[AgentEvent]`. Inside an `ExitStack`, installs 10 `unittest.mock.patch` context managers identical to `test_agent_sse.py::patch_pipeline_singletons` (v1.3 D-16 consumer-path discipline), instantiates `AgentQueryPipeline()`, iterates `run_streaming(req)` over `GenerationRequest(query=DEMO_QUERY, session_id="demo-session", tenant_id="demo-tenant", user_id="demo-user", top_k=5)`, returns the full event list. Patches revert on context exit — no global state mutation. |
| `emit_sse_frame`        | fn          | `(evt: AgentEvent) -> str`. Returns `f"event: {evt.event_type}\ndata: {evt.model_dump_json()}\n\n"` — byte-identical to `controllers/api.py:282` so the asciinema cast (plan 19-03+) shows the exact wire shape a real `curl --no-buffer` would see. |
| `validate_event_shape`  | fn          | `(events: list[AgentEvent]) -> None`. Counts events by `type(e).__name__` and compares to `_EXPECTED_COUNTS = {1 PlannerPlan, 4 ToolSpanStart, 4 ToolSpanEnd, 1 ExecutorParallel, 1 SynthesizerFinal}`. Raises `RuntimeError(f"Unexpected event sequence: got=... expected=...")` on mismatch — D-06 single-canonical event-count gate. |
| `main`                  | fn          | `() -> int`. Synchronous entrypoint: `asyncio.run(run_demo())` → print each event via `emit_sse_frame` to stdout → `validate_event_shape(events)` → return 0. On `RuntimeError`, prints `DEMO FAILED: <e>` to stderr and returns 1. |
| `__name__ == "__main__"`| guard       | `sys.exit(main())` — enables `python -m services.agent._demo_runner` per Makefile invocation pattern (plan 19-03). |

## Verification Results

| Check | Command | Result |
| --- | --- | --- |
| RED gate | `.venv/bin/pytest tests/integration/test_demo_agent.py -v --asyncio-mode=auto -o addopts= ` (after T1, before T2) | **6 failed** — Tests 1-5: `ModuleNotFoundError: services.agent._demo_runner`; Test 6: `subprocess.returncode=1` + matching stderr |
| GREEN gate (per-plan) | `.venv/bin/pytest tests/integration/test_demo_agent.py -v --asyncio-mode=auto -o addopts= --timeout=60` | **6 passed in 5.02s** |
| Direct invocation | `APP_MODEL_DIR=/tmp .venv/bin/python -m services.agent._demo_runner` | rc=0; stdout has 11 events + `event: synthesizer.final` |
| Regression (full unit suite) | `.venv/bin/pytest tests/unit -q` | **775 passed, 1 skipped** — byte-identical to plan 19-01 baseline. Zero failures introduced. |
| ruff (both files) | `.venv/bin/ruff check services/agent/_demo_runner.py tests/integration/test_demo_agent.py` | All checks passed |
| mypy --strict (new file) | `APP_MODEL_DIR=/tmp .venv/bin/mypy --strict services/agent/_demo_runner.py \| grep '^services/agent/_demo_runner.py:.*error:' \| wc -l` | **0** errors on the new file (296 pre-existing baseline errors in 28 other files are out of scope per Rule 3 SCOPE BOUNDARY) |
| Line budget (runner) | `wc -l services/agent/_demo_runner.py` | 126 ≤ 130 |
| Required exports | `grep -E "^def main\b\|^async def run_demo\b\|^def emit_sse_frame\b\|^def validate_event_shape\b" services/agent/_demo_runner.py` | 4 matches |
| `_demo_stubs` import | `grep -c "from services.agent._demo_stubs import" services/agent/_demo_runner.py` | 1 |
| Placeholder IDs (security gate T-19-02-02) | `grep -cE "demo-tenant\|demo-user\|demo-session" services/agent/_demo_runner.py` | 3 |
| No real-tenant leak | `grep -cE "tenant.*acme\|tenant.*production" services/agent/_demo_runner.py` | 0 |
| No FastAPI surface (T-19-02-01) | `grep -cE "dependency_overrides\|app\." services/agent/_demo_runner.py` | 0 |
| Test file count | `grep -c "^def test_\|^async def test_" tests/integration/test_demo_agent.py` | 6 |
| Test file `_demo_runner` import sites | `grep -c "from services.agent._demo_runner" tests/integration/test_demo_agent.py` | 5 (one per Tests 1-5 — Test 6 invokes via subprocess only) |
| Test file fixture re-use | `grep -c "patch_pipeline_singletons" tests/integration/test_demo_agent.py` | 4 (fixture def + decorator + 2 call sites — Test 1 only; Tests 2-6 use `run_demo()` which installs its own patches) |

### Per-test detail (GREEN run)

| # | Test | Asserts | Status |
| - | ---- | ------- | ------ |
| 1 | `test_demo_runner_emits_expected_event_sequence_in_process` | 11-event sequence (1+4+4+1+1) via both monkeypatch+pipeline AND `run_demo()` | PASSED |
| 2 | `test_demo_runner_latency_bounded_by_max_not_sum`           | `450 < elapsed_ms < 700` for 4×0.5s parallel (D-05 / Phase 18 SC4) | PASSED |
| 3 | `test_demo_runner_executor_parallel_fan_out_is_four`        | 1 ExecutorParallelEvent with `fan_out == 4` and `group_latency_ms < 700` | PASSED |
| 4 | `test_demo_runner_synthesizer_final_answer_non_empty`       | terminal SynthesizerFinalEvent has non-empty `answer` string | PASSED |
| 5 | `test_demo_runner_main_writes_sse_frames_to_stdout`         | `main()` rc=0; stdout has ≥ 11 `event: ` + ≥ 11 `data: ` lines + 5 distinct event_type values | PASSED |
| 6 | `test_demo_runner_exit_code_zero_on_success`                | subprocess `python -m services.agent._demo_runner` rc=0 within 10s; stdout contains `event: synthesizer.final` | PASSED |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `conda run -n torch_env` → `.venv/bin/<tool>` and `sys.executable`**
- **Found during:** Task 1 verify step.
- **Issue:** Plan `<verify>` and Test 6 specify `conda run -n torch_env pytest` and `["conda", "run", "-n", "torch_env", "python", ...]`. This machine has no `conda` binary; project uses `.venv/` (uv-managed, Python 3.12.13). Same situation plan 19-01 hit (Deviation #1 in 19-01-SUMMARY.md). The user's prompt explicitly noted this and instructed `[sys.executable, "-m", ...]`.
- **Fix:** Used `sys.executable` for the subprocess invocation in Test 6 (always the running interpreter — never None on a working Python). Skip-on-missing kept as `pytest.skip` if `shutil.which(sys.executable)` is None (defensive — never triggers in practice). All `pytest`/`ruff`/`mypy` invocations use `.venv/bin/<tool>` directly.
- **Files modified:** `tests/integration/test_demo_agent.py` (Test 6 implementation).
- **Commit:** Folded into RED commit `d8f7425`.

**2. [Rule 3 - Blocking] Override pytest `addopts = -m "not integration"` for the integration test invocation**
- **Found during:** Task 1 verify step — initial RED gate ran but `pytest tests/integration/test_demo_agent.py` collected 0 tests.
- **Issue:** `pytest.ini` has `addopts = -m "not integration"` which excludes any test inside `tests/integration/` from default collection — but only if marked `@pytest.mark.integration`. The new file uses NO marker (matching every other file in `tests/integration/`, e.g., `test_pipeline.py`), but the pytest filter expression is path-agnostic and was still applied. The fix is to override `addopts` at invocation time.
- **Fix:** All explicit pytest invocations of this test file use `-o addopts= ` to override the marker filter. Documented in the SUMMARY's `<key-decisions>` section as `integration-tests-via-explicit-path`. The full unit-suite regression check (`pytest tests/unit`) still uses default args — no integration tests touched.
- **Files modified:** None (this is a runtime invocation pattern, not a code change). The plan's `<verify>` block was followed with the `-o addopts= ` flag added.
- **Commit:** N/A (verification-time only).

**3. [Rule 1 - Bug] Trim `services/agent/_demo_runner.py` to fit ≤ 130-line budget**
- **Found during:** Task 2 first GREEN-attempt — 144 lines, then 138, then 133.
- **Issue:** Initial implementation had verbose section banners (`# ── public API ──`), per-class blank-line padding, and a 5-key `counts = {...}` dict literal in `validate_event_shape` mirroring an `expected = {...}` dict literal. Plan acceptance requires `wc -l` ≤ 130.
- **Fix:**
  - Hoisted `_EXPECTED_COUNTS` to module level + replaced 5-line per-event-type `sum(...)` comprehensions with a single `for e in events: counts[type(e).__name__] += 1` loop (saved ~10 lines).
  - Trimmed unused `PlannerPlanEvent`/`ToolSpanStartEvent`/`ToolSpanEndEvent`/`ExecutorParallelEvent`/`SynthesizerFinalEvent` imports (no longer needed since validation switched to type-name strings).
  - Collapsed double blank lines between `_NoMem`/`_NoAudit`/`_NoTenant`/`_NoFilter`/`_LLM` to single blanks.
  - Removed redundant section banners (`# ── public API ──`).
- **Files modified:** `services/agent/_demo_runner.py`.
- **Commit:** Folded into GREEN commit `db232f3` before that commit landed. Final size: 126 lines (≤ 130 budget, with 4 lines of headroom).

**4. [Rule 1 - Bug] mypy `attr-defined` error on `evt.event_type`**
- **Found during:** Task 2 first GREEN attempt — `services/agent/_demo_runner.py:98: error: "AgentEvent" has no attribute "event_type" [attr-defined]`.
- **Issue:** `utils/models.py:537` declares `class AgentEvent(BaseModel)` with no `event_type` attribute (intentional — abstract-by-convention; line 540: "Concrete subclasses each declare a unique `event_type: ClassVar[str]` discriminator"). The list `events: list[AgentEvent]` returned by `run_streaming` is heterogeneous — each element is a concrete subclass — but mypy resolves `evt.event_type` against the `AgentEvent` static type, which lacks the attribute.
- **Fix:** Added `# type: ignore[attr-defined]` on the single access site with a 2-line comment naming the consumer at `controllers/api.py:282` which uses the exact same shape (and which mypy doesn't flag because `controllers/api.py` has its own pre-existing baseline of errors that mask attr-defined inference).
- **Why NOT fix `utils/models.py`:** Adding `event_type: ClassVar[str]` to `AgentEvent` base class would touch an out-of-scope file (Rule 3 SCOPE BOUNDARY — only auto-fix issues directly caused by current task changes). The pre-existing convention is documented at `utils/models.py:540` and is a deliberate design decision (Phase 18). Future v1.5+ may add a typed `Protocol` or a `Literal` discriminator union, but that's out of scope for plan 19-02.
- **Files modified:** `services/agent/_demo_runner.py:98` (added type-ignore + 2-line explanatory comment).
- **Commit:** Folded into GREEN commit `db232f3` before that commit landed.

**5. [Rule 3 - Blocking] Trim ruff F401 unused imports in test file**
- **Found during:** Task 1 RED-gate verification — 5 ruff F401 errors on `tests/integration/test_demo_agent.py` for imports listed verbatim in the plan body but not actually referenced.
- **Issue:** Plan `<action>` listed `(AgentEvent, ExecutorParallelEvent, PlannerPlanEvent, SynthesizerFinalEvent, ToolSpanEndEvent, ToolSpanStartEvent)` from `utils.models`. Tests 1's event-type counts use `type(e).__name__` string comparison (not `isinstance(e, ...)`), so `PlannerPlanEvent` / `ToolSpanStartEvent` / `ToolSpanEndEvent` are never referenced at runtime. Same for `ToolRegistry` (replaced by direct `build_demo_registry` call) and `asyncio` (subprocess path uses `subprocess`, not `asyncio`).
- **Fix:** Trimmed imports to only the symbols actually used: `AgentEvent`, `ExecutorParallelEvent`, `GenerationRequest`, `SynthesizerFinalEvent`. Verified all acceptance grep counts still pass after trim.
- **Files modified:** `tests/integration/test_demo_agent.py:7-30` (import block).
- **Commit:** Folded into RED commit `d8f7425` before that commit landed.

### Auth gates / Architectural questions (Rule 4)

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries.

Threat register from the plan was satisfied:

| Threat ID | Disposition | Verification |
| --------- | ----------- | ------------ |
| T-19-02-01 (Auth-bypass leakage from demo runner into production) | mitigate | `grep -cE "dependency_overrides\|app\." services/agent/_demo_runner.py` returns 0. All patches scoped to `ExitStack` — revert on context exit. Patches never touch FastAPI app routing. |
| T-19-02-02 (Real tenant IDs / JWT samples in fixture)            | mitigate | `grep -cE "demo-tenant\|demo-user\|demo-session" services/agent/_demo_runner.py` returns 3 (one each). `grep -cE "tenant.*acme\|tenant.*production" services/agent/_demo_runner.py` returns 0. Auth services are stubbed via `_NoAudit`/`_NoTenant` no-op classes — no JWT path traversed. |
| T-19-02-03 (Subprocess env-var leak in Test 6)                   | accept   | Test 6 `subprocess.run` inherits parent env. `capture_output=True` captures stdout/stderr; assert verifies SSE marker, doesn't print env. Documented in Test 6 docstring. |
| T-19-02-04 (`run_demo` hangs on stuck event loop)                | mitigate | pytest `--timeout=60` ceiling + Test 6 `subprocess.run timeout=10`. Real elapsed bounded by 0.5s + ~50ms overhead = ~570ms (verified by Test 2's `< 700` upper bound). |

## Known Stubs

The runner module IS the demo's stub-runtime entrypoint (CONTEXT.md D-05 / D-06). It consumes the plan-19-01 stubs (`DemoStubPlanner`, `make_fake_retrieve_tool`, `build_demo_registry`) and adds 5 thin no-op singleton stubs (`_NoMem`, `_NoAudit`, `_NoTenant`, `_NoFilter`, `_LLM`) — the runtime equivalents of the pytest fixture's inline classes. These are intentional demo-only fixtures, not regressive stubs against future production code; they are scoped to `run_demo()`'s `ExitStack` and do not leak.

No regressive stubs introduced. The data flow from `DEMO_QUERY` → `DemoStubPlanner.plan_from_messages` → 4 `_Fake` retrieve tools → `Executor.execute_plan_streaming` → `SynthesizerFinalEvent(answer=DemoStubPlanner._terminal_plan.rationale)` is end-to-end functional with no unwired components.

## TDD Gate Compliance

| Gate     | Commit                              | Status |
| -------- | ----------------------------------- | ------ |
| RED      | `d8f7425 test(19-02-T1)`            | All 6 tests fail before implementation: Tests 1-5 with `ModuleNotFoundError`, Test 6 with subprocess `returncode=1` and matching `No module named services.agent._demo_runner` on stderr. The fail-fast rule (per executor §"Plan-Level TDD Gate Enforcement") was not tripped — no test passed unexpectedly during RED. |
| GREEN    | `db232f3 feat(19-02-T2)`            | All 6 tests pass in 5.0s. ruff + mypy --strict clean on the new file. Full unit suite remains 775 passed / 1 skipped (no regression). Direct `python -m services.agent._demo_runner` invocation exits 0 with valid SSE output. |
| REFACTOR | (none)                              | Not required — implementation is already minimal (126 lines, no duplication). The two iterations (line-budget trim, mypy attr-defined ignore) happened pre-commit; the GREEN commit IS the post-refactor state. |

## Self-Check: PASSED

- File `tests/integration/test_demo_agent.py` exists ✓
- File `services/agent/_demo_runner.py` exists ✓
- File `.planning/phases/19-agent-first-docs-demo-release/19-02-SUMMARY.md` exists ✓
- Commit `d8f7425` exists in `git log` ✓
- Commit `db232f3` exists in `git log` ✓
- 6/6 integration tests pass ✓
- ruff clean on both new files ✓
- mypy --strict: 0 new errors on `services/agent/_demo_runner.py` ✓
- Full unit suite: 775 passed / 1 skipped (no regression vs plan 19-01 baseline) ✓
- Line budget: 126 ≤ 130 (runner) ✓
- Direct `python -m services.agent._demo_runner` exits 0 with `event: synthesizer.final` on stdout ✓
- Placeholder IDs only (3 occurrences of demo-tenant/demo-user/demo-session, 0 occurrences of acme/production) ✓
