---
phase: 19-agent-first-docs-demo-release
reviewed: 2026-05-10T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - docs/agent-architecture.md
  - docs/v1.4-design.md
  - services/agent/_demo_runner.py
  - services/agent/_demo_stubs.py
  - tests/integration/test_demo_agent.py
  - tests/unit/test_demo_stubs.py
findings:
  critical: 0
  warning: 4
  info: 7
  total: 11
status: issues_found
---

# Phase 19: Code Review Report

**Reviewed:** 2026-05-10
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Phase 19 ships agent-first docs (`docs/agent-architecture.md`, frozen design copy
`docs/v1.4-design.md`) plus the `make demo-agent` primitives
(`services/agent/_demo_runner.py`, `services/agent/_demo_stubs.py`) and their
test coverage. The code is small (~225 LOC across both .py files), narrowly
scoped, and explicitly demo/fixture-only — `_demo_runner.py` carries a leading
underscore and lives next to a planner stub that is never wired in production.

Surface-level safety is solid: no hardcoded secrets, no `eval`/`exec`/`shell=True`,
no bare `except`, no blocking I/O in async paths, structured `loguru` logger is
used by the dependent `Executor`, and the demo input is verbatim-pinned from
CONTEXT.md. No CRITICAL findings — this is a demo runner with no external I/O,
no PII, no auth surface, and no production code path touches it.

WARNING-tier findings cluster around three themes:

1. **Duplication / drift risk** — the singleton-patch fixture is hand-copied
   between `_demo_runner.py` and the integration test (with `_NoMem`,
   `_NoAudit`, `_NoTenant`, `_NoFilter`, `_LLM` defined twice). Phase 19's
   own SUMMARY.md acknowledges this as a deliberate self-containment trade,
   but the two copies are not byte-identical (the runner uses `unittest.mock.patch`,
   the test uses `monkeypatch`, and the inner `_C` / `_E` helper classes use
   class-level mutable defaults).
2. **Hardcoded fan-out coupling** — `_EXPECTED_COUNTS` in `_demo_runner.py`
   hardcodes `ToolSpanStartEvent: 4` / `ToolSpanEndEvent: 4` rather than
   deriving from `len(DEMO_KB_SHARDS)`; if D-05 ever changes the shard list,
   the validator silently fails out-of-band of the constant.
3. **Latency assertion fragility** — the integration test asserts
   `450 < elapsed_ms < 700` for a 0.5s sleep × 4 parallel; on a busy CI worker
   the upper bound is realistic-but-tight, and the lower bound 450 is only
   50 ms below the floor. There is no retry / margin.

INFO-tier findings are mostly TDD-residue (`# RED: import must fail` comments
left in green-phase tests), magic numbers, and minor type-annotation hygiene.

The two .md files are documentation, not code; they're scanned for code-block
correctness and internal-link integrity. `docs/v1.4-design.md` is verbatim-frozen
office-hours output (Phase 19-07) — its prose is out-of-scope; only its embedded
`pyproject.toml` claim ("`langchain[eval]>=1.2.10` and `langchain-community>=0.3.14`")
should be cross-checked against the actual `pyproject.toml` if those constraints
matter.

## Warnings

### WR-01: Hardcoded fan-out count decoupled from DEMO_KB_SHARDS source-of-truth

**File:** `services/agent/_demo_runner.py:97-100`
**Issue:** `_EXPECTED_COUNTS` literally hardcodes `"ToolSpanStartEvent": 4` and
`"ToolSpanEndEvent": 4`. The number 4 is structurally derived from
`len(DEMO_KB_SHARDS)` (= 4) in `_demo_stubs.py:22`, but the link between them is
implicit — change one without the other and `validate_event_shape` will mis-fire
or pass a degenerate sequence. This violates DRY at the magic-number layer
between two files in the same Phase 19 module.

**Fix:**
```python
from services.agent._demo_stubs import DEMO_KB_SHARDS  # already imported transitively

_EXPECTED_COUNTS: dict[str, int] = {
    "PlannerPlanEvent": 1,
    "ToolSpanStartEvent": len(DEMO_KB_SHARDS),
    "ToolSpanEndEvent": len(DEMO_KB_SHARDS),
    "ExecutorParallelEvent": 1,
    "SynthesizerFinalEvent": 1,
}
```

### WR-02: Singleton-patch boilerplate duplicated across runner and integration test

**File:** `services/agent/_demo_runner.py:30-55` AND `tests/integration/test_demo_agent.py:46-100`
**Issue:** The five no-op stub classes (`_NoMem`, `_NoAudit`, `_NoTenant`,
`_NoFilter`, `_LLM`) and the 9-call patch sequence are defined twice — once in
the runner using `unittest.mock.patch` + `ExitStack`, once in the test using
`pytest.MonkeyPatch`. The two lists drift: e.g. the runner uses `lambda: _NoMem()`
(captures the class once at lambda definition) while the test uses
`lambda: _NoMem()` (re-instantiates per call) — semantically the same here but a
maintenance trap. Phase 19-01 SUMMARY.md acknowledges the test's copy is
intentional for self-containment, but it does not document the runner's parallel
copy. If a new singleton is added to `services.pipeline.AgentQueryPipeline.__init__`
(e.g. tracing service), it must be patched in BOTH places independently.

**Fix:** Promote the patch list to `_demo_stubs.py` as a context-manager helper
that both consumers call:
```python
# in _demo_stubs.py
from contextlib import contextmanager
from unittest.mock import patch

@contextmanager
def patch_pipeline_singletons(planner, registry):
    """Single source of truth for AgentQueryPipeline.__init__ singleton patches."""
    patches = [
        patch("services.pipeline.get_memory_service",   lambda: _NoMem()),
        patch("services.pipeline.get_audit_service",    lambda: _NoAudit()),
        # ... etc
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield
```
Both runner and test then call `with patch_pipeline_singletons(...)`.
(If self-containment of the test is non-negotiable per Phase 19 charter, at
minimum add a comment in BOTH locations cross-referencing the other so future
edits are forced to consider the twin.)

### WR-03: Class-level mutable defaults in inner stub classes risk cross-call leakage

**File:** `services/agent/_demo_runner.py:32-33, 49-51` AND `tests/integration/test_demo_agent.py:48-49, 65-67`
**Issue:** Inner classes `_C` and `_E` declare `short_term: list[Any] = []` and
`filters: dict[str, Any] = {}` as class-level attributes. These are shared
across all instances of `_C` / `_E`. Today the consumer (pipeline code) only
reads `mem_ctx.short_term` and `extraction.filters` — but if any future
pipeline change appends to either, mutations leak across `run_demo()`
invocations within the same Python process (e.g. the integration test calls
`run_demo()` four times via Tests 1-4; a stateful append would compound).
This is exactly the Python mutable-default footgun applied at class scope.

**Fix:** Use instance attributes via `__init__` (or, since these are throwaway
fixtures, instantiate fresh dicts/lists per call):
```python
class _NoMem:
    async def load_context(self, *a, **kw):
        class _C:
            def __init__(self):
                self.short_term: list[Any] = []
        return _C()
```
Or a Pydantic-style frozen dataclass. The current pattern is correctness-by-luck.

### WR-04: Integration test latency-bound has no headroom on busy CI

**File:** `tests/integration/test_demo_agent.py:163`
**Issue:** `assert 450 < elapsed_ms < 700` for a 4-way parallel of `asyncio.sleep(0.5)`.
- Lower bound 450 ms is 50 ms below the 500 ms `sleep` floor — relies on
  `asyncio.sleep` being slightly imprecise, which it usually is, but CI workers
  with high-resolution timers can hit 499 ms and pass; a slow scheduler tick
  can hit 510 ms and pass; a *really* slow scheduler tick on group orchestration
  could push elapsed to 720 ms (event-loop overhead + 4 task creates +
  `as_completed` + 5 event yields + sub-100 ms slop). The 700 ms ceiling is the
  actual flake risk on a loaded GitHub-Actions runner.
- The test runs `await run_demo()` which builds the pipeline, runs `_build_tf`,
  loads memory context, etc. — every async hop adds non-deterministic overhead
  that is uncorrelated with the parallel-fan-out claim under test.

The assertion's *intent* is "max-not-sum" (i.e. NOT 4×500 = 2000 ms). Encode
that intent directly:

**Fix:**
```python
SLEEP_S = 0.5
NUM_TOOLS = 4
# max-not-sum: total elapsed must be closer to one tool's runtime than to
# the serial sum (proves parallelism, tolerates CI jitter).
SERIAL_MS = int(SLEEP_S * 1000) * NUM_TOOLS  # 2000
PARALLEL_MAX_MS = int(SLEEP_S * 1000) + 1000  # 1500 — generous ceiling
assert elapsed_ms < PARALLEL_MAX_MS, (
    f"expected parallel execution < {PARALLEL_MAX_MS}ms (serial would be {SERIAL_MS}ms), "
    f"got {elapsed_ms}"
)
# (drop the lower bound — it tests asyncio.sleep, not the demo)
```

## Info

### IN-01: Stale `# RED: import must fail` comments left in green-phase tests

**File:** `tests/integration/test_demo_agent.py:122, 158, 173, 187, 200`
**Issue:** Five `from services.agent._demo_runner import ... # RED: import must fail`
comments remain in tests that are now passing (the module exists). These were
TDD red-phase markers and now misrepresent the test state to a future reader.
**Fix:** Delete the `# RED:` portion of each comment (or move the imports to
the module top now that they all succeed).

### IN-02: TDD red-state comment in unit test docstring

**File:** `tests/unit/test_demo_stubs.py:12-14`
**Issue:** Module docstring still says
"RED state: ALL imports from `services.agent._demo_stubs` fail with
`ModuleNotFoundError` until Task 2 ships the module." Task 2 has shipped.
**Fix:** Either delete the RED-state paragraph or convert it to a historical
note referencing 19-01-SUMMARY.md.

### IN-03: `# noqa: E402` annotation no longer applicable

**File:** `tests/unit/test_demo_stubs.py:24`
**Issue:** The `# noqa: E402  (RED — module does not exist yet)` was needed when
the import order around `from __future__ import annotations` was being negotiated
during red-phase. With the module shipped and the import at the top of the
import block, E402 (module-level import not at top of file) cannot trigger here.
**Fix:** Drop the noqa.

### IN-04: `noqa: F401` annotation hides genuine unused-import

**File:** `tests/unit/test_demo_stubs.py:33`
**Issue:** `ToolCall, # noqa: F401  — required import per plan 19-01 Task 1
acceptance criteria` — the import is genuinely unused inside the test body.
"Acceptance criteria require this import" is a process artifact, not a runtime
constraint. Either the test should *use* `ToolCall` (e.g.
`assert all(isinstance(s, ToolCall) for s in plan.steps)`) or the import should
go; carrying a F401-suppressed import as a "required" stamp invites future
lint-config drift.
**Fix:** Add a real assertion using `ToolCall`, or remove both the import and
the comment.

### IN-05: Magic numbers in fake-tool factory

**File:** `services/agent/_demo_stubs.py:85`
**Issue:** `chunk_count: 3` is hardcoded with a comment "per D-06" — but 3 has
no semantic relationship to anything else in the module (it's not the number of
shards, not the parallelism factor). It's a CONTEXT.md decision frozen as a
literal. Fine to keep, but extract as a module-level constant for self-document:
**Fix:**
```python
DEMO_FAKE_CHUNK_COUNT: Final[int] = 3  # D-06: visible chunk count on SSE events
...
metadata={"latency_ms": int(sleep_s * 1000), "chunk_count": DEMO_FAKE_CHUNK_COUNT}
```

### IN-06: `int(sleep_s * 1000)` floors with no guard against negative values

**File:** `services/agent/_demo_stubs.py:80, 85`
**Issue:** `if sleep_s > 0: await asyncio.sleep(sleep_s)` followed by
`metadata={"latency_ms": int(sleep_s * 1000), ...}`. If `sleep_s` is negative
(degenerate caller), the sleep is skipped (correct) but `latency_ms` becomes
negative (probably wrong; SSE consumers will downstream-misrender). Fixture-only
code, so impact is nil — but the asymmetry is a hint of incomplete invariant.
**Fix:**
```python
metadata={"latency_ms": max(0, int(sleep_s * 1000)), "chunk_count": 3}
```

### IN-07: `_demo_runner.main()` swallows non-RuntimeError into uncaught traceback

**File:** `services/agent/_demo_runner.py:114-122`
**Issue:** `try: ... except RuntimeError as e:` — `validate_event_shape` raises
`RuntimeError` (caught), but `asyncio.run(run_demo())` can raise a wider set:
`pydantic.ValidationError` (if `GenerationRequest` rejects fields),
`ImportError` (if a singleton accessor changes), `OSError` etc. None are caught.
The result is a Python traceback to stderr with a non-zero exit code — which
is *correct* shell behavior, just not matching the docstring promise of
"Exit 0 on success; non-zero on shape mismatch (CONTEXT.md D-06)" — the
implication is that NON-shape-mismatch failures get the tidy `DEMO FAILED:`
prefix, which they don't.
**Fix:** Either widen the catch:
```python
except (RuntimeError, Exception) as e:  # demo runner — show context, never traceback
    print(f"DEMO FAILED: {e!r}", file=sys.stderr)
    return 1
```
Or update the docstring to match: "Exit 0 on success; non-zero (with traceback)
on any error; 1 (with `DEMO FAILED:` prefix) on shape mismatch."

---

_Reviewed: 2026-05-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
