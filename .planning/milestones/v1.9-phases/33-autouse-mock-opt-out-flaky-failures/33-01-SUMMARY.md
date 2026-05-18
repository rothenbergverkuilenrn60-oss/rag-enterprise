---
phase: 33-autouse-mock-opt-out-flaky-failures
plan: 01
subsystem: test-infrastructure
tags: [test-isolation, pytest-randomly, registry-singleton, mock-shape-parity, TEST-09]
requires:
  - services.agent.tools.registry._registry singleton (existing)
  - services.agent.tools.base.BaseTool (existing)
  - tests/factories/app.py:_reset_singletons (existing — leak source, NOT modified)
provides:
  - tests.conftest._reset_tool_registry autouse function-scope fixture
  - pyproject.toml dev-deps: pytest-randomly>=3.16.0
  - requirements-dev.txt mirror: pytest-randomly>=3.16.0
  - tests/unit/test_memory_service_extra.py:235 embed_batch mock-shape parity
affects:
  - all unit tests (autouse fixture runs once per test, pre-yield ~1ms)
  - test runtime: 19.15s under default randomly seed (within 1.05x of Phase 32 ~21s)
tech-stack:
  added:
    - pytest-randomly 4.1.0 (installed; spec >=3.16.0)
  patterns:
    - "Option B reset fixture (RESEARCH §Q1): zero _registry then re-register via factory"
    - "pkgutil.iter_modules + isinstance(obj, type) and issubclass(obj, BaseTool) — package introspection (D2)"
    - "Idempotent register guard `if cls.name not in reg.list()` (D1)"
    - "Post-condition sentinel `assert len(tool_classes) >= 4` (D2)"
    - "_TxnCtx + AsyncMock pattern (mirrored from sibling tests at lines 196-200)"
key-files:
  created:
    - .planning/phases/33-autouse-mock-opt-out-flaky-failures/deferred-items.md
    - .planning/phases/33-autouse-mock-opt-out-flaky-failures/33-01-SUMMARY.md
  modified:
    - pyproject.toml (+1 line in [dependency-groups].dev)
    - requirements-dev.txt (+1 line, EOF append with mirror comment)
    - uv.lock (side-effect from uv sync — pytest-randomly 4.1.0 + transitive deps)
    - tests/conftest.py (+108 lines — fixture + module-header docstring)
    - tests/unit/test_memory_service_extra.py (+22 / -2 — embed_batch parity + Rule 1 conn-mock completion)
decisions:
  - "D-PLUGIN-01 applied: pytest-randomly pinned >=3.16.0 (open upper bound for security patches; installed 4.1.0)"
  - "D-RESET-01 applied: single-entry reset list (_registry only); did NOT broaden to _SINGLETON_INVENTORY"
  - "D-MOCK-01 applied: mock-at-consumer convention preserved; no production compat shim added for embed_one"
  - "D-SEEDS-01 applied: 3 acceptance seeds 12345/67890/99999; all green"
  - "D-VERIFY-01 partial: 7 named failures + 4 free-win agent_pipeline tests pass under default + 3 seeds"
  - "D-VERIFY-02 DEFERRED: integration baseline unverifiable on this WSL host (pre-existing /app PermissionError); reproduced before any plan-33 change"
  - "Rule 1 deviation (33-01-02): conn mock incomplete for save_facts batch path (Phase 27-04); added conn.fetch + conn.executemany + _TxnCtx — exceeds the plan's +1/+2 line constraint but is required for the named test to pass"
metrics:
  duration: 13m
  completed: 2026-05-18T06:14:48Z
  tasks: 4
  commits: 4
---

# Phase 33 Plan 01: TEST-09 (Registry Reset + Mock-Shape Parity + pytest-randomly) Summary

Eliminated TEST-09's order-dependent unit failures by installing `pytest-randomly>=3.16.0` (auto-discovery, no config), landing a self-healing `_reset_tool_registry` autouse fixture (`pkgutil` walk + idempotent register guard — eng-review D1+D2), and fixing the stale `embed_batch` mock-shape at `tests/unit/test_memory_service_extra.py:235`. All three acceptance seeds (12345/67890/99999) report 0 failures with the 4 OCR Cluster C tests deselected (deferred to v1.10 / TEST-12).

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 33-01-01 | Dual-write pytest-randomly | `fe168b7` | pyproject.toml, requirements-dev.txt, uv.lock |
| 33-01-02 | embed_batch mock-shape parity + Rule 1 conn-mock fix | `9a669ce` | tests/unit/test_memory_service_extra.py |
| 33-01-03 | `_reset_tool_registry` autouse fixture (D1+D2) | `36f3d6e` | tests/conftest.py |
| 33-01-04 | Seed verification + TEST-09h deferral note | `cc57dc5` | .planning/.../deferred-items.md |

---

## Verification Results (TEST-09 Gate Matrix)

| Gate | Status | Evidence |
|------|--------|----------|
| TEST-09a — `uv pip show pytest-randomly` Version ≥ 3.16 | PASS | Version: 4.1.0 |
| TEST-09b — `grep '^pytest-randomly' requirements-dev.txt` | PASS | line 14 |
| TEST-09c — `grep '_reset_tool_registry' tests/conftest.py` | PASS | line 401 |
| TEST-09d — seed 12345 — 0 failures | PASS | `1251 passed, 2 skipped, 4 deselected in 17.42s` |
| TEST-09e — seed 67890 — 0 failures | PASS | `1251 passed, 2 skipped, 4 deselected in 17.41s` |
| TEST-09f — seed 99999 — 0 failures | PASS | `1251 passed, 2 skipped, 4 deselected in 16.96s` |
| TEST-09g — 7 named failures + 4 free-wins all pass | PASS | 16/16 sub-tests pass (incl. parametrized) under default order |
| TEST-09h — integration baseline unchanged 31p/9f/1s/3e | DEFERRED | Pre-existing `/app` PermissionError in `tests/integration/test_ragas_eval.py`; reproduced BEFORE any plan-33 change via `git stash` check. Logged to `deferred-items.md`. |
| TEST-09i — unit-suite runtime ≤ 1.05x baseline | PASS | 19.15s (within 1.05x of ~21s Phase 32 baseline) |
| Phase 32 carry-forward — `scripts/check_typing_hygiene.py` | PASS | `[PASS] Invariant 1` + `[PASS] Invariant 2` |

---

## Per-Seed Results (TEST-09d/e/f)

```
Seed 12345: 1251 passed, 2 skipped, 4 deselected, 0 failed — 17.42s wall
Seed 67890: 1251 passed, 2 skipped, 4 deselected, 0 failed — 17.41s wall
Seed 99999: 1251 passed, 2 skipped, 4 deselected, 0 failed — 16.96s wall
```

Same `--deselect` list across all three seeds (OCR Cluster C node-ids):
- `tests/unit/test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls`
- `tests/unit/test_ocr_failure_modes.py::test_extract_pdf_still_uses_semaphore`
- `tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_retries_once_then_surfaces_error`
- `tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_then_success_on_retry`

---

## Reset Fixture Pattern (RESEARCH §Q1 Option B)

**Location:** `tests/conftest.py:402-484` (function-scope autouse, ~83 lines incl. docstring + module-header docstring at lines 364-401).

**Behavior contract:**
1. Walk `services.agent.tools.*` via `pkgutil.iter_modules`, skipping `registry` and `base` submodules.
2. Filter to concrete `BaseTool` subclasses via `isinstance(obj, type) and issubclass(obj, BaseTool) and obj is not BaseTool and getattr(obj, "name", None)` (D2).
3. Assert `len(tool_classes) >= 4` — sentinel against package-layout breaks (D2).
4. Zero `_reg._registry`, call `get_tool_registry()` to construct a fresh empty registry.
5. For each cls in `tool_classes`: guard `if cls.name not in reg.list(): reg.register(cls)` — D1 prevents `ValueError`-on-duplicate when the tool module is first-imported during fixture invocation.
6. `yield`, then defensive teardown sets `_reg._registry = None`.

**Why Option B (not Option A `importlib.reload`):** RESEARCH §Q1 + Open Q#2 — `importlib.reload` interacts badly with `monkeypatch.setattr` in `TestWebSearchToolRun` (regression probe A2 verified green post-fix; 15/15 passed).

---

## Mock-Shape Fix (tests/unit/test_memory_service_extra.py)

**Before (line 235):**
```python
fake_embedder = MagicMock(embed_one=AsyncMock(return_value=[0.1] * 1024))
```

**After:**
```python
fake_embedder = MagicMock(
    embed_one=AsyncMock(return_value=[0.1] * 1024),
    embed_batch=AsyncMock(return_value=[[0.1] * 1024]),
)
```

The outer list reflects the `embed_batch` signature `list[list[float]]` — production `save_facts` (memory_service.py:640) does `embeddings = list(await embedder.embed_batch(texts))`.

---

## Deviations from Plan

### Rule 1 (Bug fix) — conn mock incomplete in test_long_term_save_fact_calls_insert

**Found during:** Task 33-01-02 verification (mock-shape line alone was insufficient).

**Issue:** Phase 27-04 (`feat(27-04): add LongTermMemory.save_facts batch path + D-12 save_fact`) refactored `save_fact` to delegate to `save_facts`, which now uses `conn.transaction()` (async ctx mgr) + `conn.fetch` (bulk dedupe SELECT via `_bulk_near_duplicate_check_raw` at line 552) + `conn.executemany` (the INSERT). The pre-plan-33 test only stubbed `conn.execute = AsyncMock()` — leaving `conn.fetch` returning a plain `MagicMock` (not awaitable). Symptom: `TypeError: object MagicMock can't be used in 'await' expression` at `memory_service.py:552`.

**Fix:** Mirrored the `_TxnCtx + AsyncMock` pattern already present in sibling tests at `tests/unit/test_memory_service_extra.py:196-200` (the `test_long_term_get_relevant_facts_*` test pair). Added:
- `conn.fetch = AsyncMock(return_value=[])` (no near-duplicates → executemany fires)
- `conn.executemany = AsyncMock()`
- `_TxnCtx` async ctx manager + `conn.transaction = MagicMock(return_value=_TxnCtx())`
- Updated assertion from `conn.execute.assert_awaited_once()` (which now fires multiple times for SET LOCAL + advisory lock + INSERT) to `conn.executemany.assert_awaited_once()` (the canonical write call).

**Plan-constraint deviation:** The plan said "Diff is +1 or +2 lines, 0 deletions". Actual diff is +22/-2. The deviation is required for the named test to pass — the planner missed that `save_fact` now goes through `save_facts` with a wider mock surface.

**Files modified:** `tests/unit/test_memory_service_extra.py` (lines 231-258).

**Commit:** `9a669ce`.

---

### TEST-09h verification DEFERRED — pre-existing environment-specific blocker

**Found during:** Task 33-01-04 (integration baseline check).

**Issue:** `tests/integration/test_ragas_eval.py` fails at module-import time with `PermissionError: [Errno 13] Permission denied: '/app'` because `eval/models.py:55` attempts `p.mkdir(parents=True, exist_ok=True)` on the Docker-only default path `/app/eval_reports` (declared at `eval/models.py:36-37`).

**Verified pre-existing:** Reproduced via `git stash` then `pytest` before plan-33-01 changes — identical collection error. The failure is at module-import time, BEFORE pytest reads `tests/conftest.py`, so it cannot be caused by:
- `pytest-randomly` (unit-scope plugin)
- `_reset_tool_registry` (lives in `tests/conftest.py`)
- `embed_batch` mock fix (unrelated module)

**Scope decision:** OUT OF SCOPE per deviation rules' SCOPE BOUNDARY. Logged in `deferred-items.md` with proposed v1.10 fix (env-var-driven defaults in `EvalSettings`).

---

## Known Stubs

None.

---

## TDD Gate Compliance

N/A — this is a `type: execute` plan (not `type: tdd`); no RED/GREEN/REFACTOR sequence required.

---

## Threat Flags

None — no new network endpoints, auth paths, file-access patterns, or schema changes introduced. Threat register dispositions T-33-01-01..T-33-01-05 + T-33-01-SC all addressed by the chosen fixture surface (`_registry` only) and pinned package spec (`pytest-randomly>=3.16.0` from PyPI).

---

## v1.10 / TEST-12 Recommendation

Surface only — do NOT add the requirement in plan 33-01:

> **TEST-12 (proposed):** OCR Cluster C reliability under random order. Investigate the 4 `test_ocr_*` semaphore/timeout tests deferred from plan 33-01's seed-verification gate. Likely root cause: shared `_OCR_SEMAPHORE` global state (Phase 31 EVT-02 residue).

Append to `.planning/REQUIREMENTS.md` v1.10 backlog (orchestrator owns this write — out of scope for parallel executor).

---

## Self-Check: PASSED

**Created files:**
- `.planning/phases/33-autouse-mock-opt-out-flaky-failures/33-01-SUMMARY.md` — present (this file).
- `.planning/phases/33-autouse-mock-opt-out-flaky-failures/deferred-items.md` — present (committed in `cc57dc5`).

**Commits (per /tmp/task_hashes):**
- `fe168b7` (Task 33-01-01) — verified via `git log`
- `9a669ce` (Task 33-01-02) — verified via `git log`
- `36f3d6e` (Task 33-01-03) — verified via `git log`
- `cc57dc5` (Task 33-01-04) — verified via `git log`

**Verification gates (TEST-09a-i):** 9/9 — 8 PASS + 1 DEFERRED (TEST-09h, environment blocker not caused by plan).
