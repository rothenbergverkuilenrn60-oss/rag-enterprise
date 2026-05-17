---
phase: 30
plan: "02"
subsystem: test-infra
tags: [TEST-INFRA-01, embedder-mock, integration-fixtures, no-production-change]
dependency_graph:
  requires: []
  provides: [TEST-INFRA-01-fix]
  affects: [tests/integration/test_extractor_e2e.py]
tech_stack:
  added: []
  patterns: [option-c-direct-init-mock, integration-scoped-conftest, patch.object]
key_files:
  created:
    - tests/integration/conftest.py
  modified: []
decisions:
  - "Option (c): direct __init__ mock, not (a) patch-reorder or (b) CI pre-download"
  - "Created tests/integration/conftest.py (new file) as landing site"
  - "autouse=True at integration scope — fires for all integration tests safely"
  - "Also mock CrossEncoderReranker.__init__ (discovered at GREEN — not in plan template)"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-17"
  tasks_completed: 3
  files_changed: 1
---

# Phase 30 Plan 02: TEST-INFRA-01 extractor_e2e Mock Fixture Summary

One-liner: Integration conftest with `autouse=True` fixture patches `HuggingFaceEmbedder.__init__` and `CrossEncoderReranker.__init__` to bypass bge-m3/bge-m3-rerank local model loads in CI.

## Objective

Fix `tests/integration/test_extractor_e2e.py` — 2 tests failing with `FileNotFoundError: Path /tmp/embedding_models/bge-m3 not found` on any host without the 1.3 GB bge-m3 model.

## Fix Path: Option (c) — Direct `__init__` Mock

**Chosen:** Option (c) per 30-CONTEXT.md — mock `__init__` directly via `patch.object`.

**Rejected:**
- Option (a) patch-reorder: autouse fixture side-effect risk on non-extractor integration tests.
- Option (b) CI pre-download: ~1.3 GB bge-m3 download slows CI; adds infra dependency.

## Root Cause (Task 0 RED)

The error chain on a clean checkout (no bge-m3 model):

```
AgentQueryPipeline.__init__
  → get_retriever()
    → Retriever.__init__
      → get_embedder()                              # line 414
        → _make_base_embedder("huggingface")
          → HuggingFaceEmbedder()
            → SentenceTransformer(model_path)       ← FileNotFoundError: bge-m3
      → get_reranker()                              # line 417
        → CrossEncoderReranker()
          → CrossEncoder(model_path)                ← FileNotFoundError: bge-m3-rerank
```

**Why `embedder_or_mock` fixture didn't help:** That fixture patches `services.vectorizer.embedder.get_embedder` at the module level. But `services/retriever/retriever.py` imports `get_embedder` at module load time via `from services.vectorizer.embedder import get_embedder` — the monkeypatch on the module attribute doesn't affect the already-bound reference in the retriever's namespace. The mock applies too late (after `AgentQueryPipeline()` construction in the test body).

**Exact raise site:** `sentence_transformers/base/model.py:188` — `raise FileNotFoundError(f"Path {model_name_or_path} not found")` when local path doesn't exist and path contains `/` (multi-segment path).

## Conftest Landing Site

**File:** NEW `tests/integration/conftest.py` (did not exist pre-edit).

**Rationale for new file vs root `tests/conftest.py`:**
- Cleaner separation — integration-only concern.
- `autouse=True` is safe here because the scope is already limited to `tests/integration/`.
- Root `tests/conftest.py` is shared with unit tests; adding an integration-specific mock there would require marker-gating complexity.

## Fixture Scope

`autouse=True` at `tests/integration/` scope. Fires for all integration tests.

**Safety:** The `with patch.object(...)` context manager ensures the mock is active only during each test's lifecycle. It does not affect unit tests (different conftest subtree).

## Minimal Attribute Set Provided by Mock

**`HuggingFaceEmbedder` mock provides:**
- `self._model` — `MagicMock` with `.encode()` returning `[[0.1] * 1024]`
- `self._device` — `"cpu"`

**`CrossEncoderReranker` mock provides:**
- `self._model` — `MagicMock` with `.predict()` returning `[0.5]`
- `self._device` — `"cpu"`

## Pre-Fix Failure (Task 0 RED)

```
FAILED tests/integration/test_extractor_e2e.py::test_user_turn_writes_user_side_fact_within_2s
FAILED tests/integration/test_extractor_e2e.py::test_extractor_exception_isolated_pipeline_returns_normally

FileNotFoundError: Path /tmp/embedding_models/bge-m3 not found
  sentence_transformers/base/model.py:188
```

## Post-Fix Test Result (Task 1 GREEN)

```
tests/integration/test_extractor_e2e.py::test_user_turn_writes_user_side_fact_within_2s PASSED
tests/integration/test_extractor_e2e.py::test_extractor_exception_isolated_pipeline_returns_normally PASSED
2 passed in 3.00s
```

## Scope Tightening (Task 2 REFACTOR)

No changes needed. The fixture was correctly scoped at Task 1:
- `autouse=True` at `tests/integration/conftest.py` scope is correct.
- All integration tests benefit from the mock (no host has bge-m3 in CI).
- Unit tests confirmed unaffected (separate conftest tree).

Integration suite with mock applied: 8 failed / 29 passed — same counts as pre-fix baseline (failures are pre-existing: real-LLM tests, PG-gated tests, UI endpoint test, not caused by the mock).

## Coverage Gates

- **diff-cover:** N/A — test infra only. `tests/integration/conftest.py` is not a source file; no coverage lines in `coverage.xml`. Result: `No lines with coverage information in this diff.`
- **Combined coverage `--fail-under=70`:** 76.2% TOTAL — above floor. Preserved.

## Mypy Baseline (Plan-Review Q1)

- Baseline captured: `Found 32 errors in 20 files` → `/tmp/30-02-mypy-baseline.txt`
- Post-fix: `Found 32 errors in 20 files` — **no increase**. Q1 gate: PASS.

## Production Code Gate

```
git diff --name-only services/ controllers/ utils/  # empty
```

Zero edits under `services/`, `controllers/`, `utils/`. Test-only fix. TEST-INFRA-01 acceptance satisfied.

## Carry-Forward Preserved

- No bare `except` introduced (conftest has no exception handlers).
- INSERT-ONLY `audit_log` invariant: not touched.
- `_bulk_near_duplicate_check_raw`: not touched (`services/memory/memory_service.py` untouched).

## Deviations from Plan

### Auto-added: CrossEncoderReranker mock

**Rule 1 - Bug / Rule 2 - Missing functionality:** After applying the `HuggingFaceEmbedder.__init__` mock (as specified in the plan), tests still failed with `FileNotFoundError: Path /tmp/embedding_models/bge-m3-rerank not found`. Investigation found `Retriever.__init__` also calls `get_reranker()` → `CrossEncoderReranker()` → `CrossEncoder(reranker_model_path)` which raises for the same reason.

**Fix:** Added `CrossEncoderReranker.__init__` mock to the same fixture. The plan template only mentioned `HuggingFaceEmbedder` because the `bge-m3-rerank` path was not visible in the embedder.py analysis — it lives in `retriever.py`. The fix is minimal (5 extra lines) and stays within the ~30 LOC allowance.

**Files modified:** `tests/integration/conftest.py` (only)
**Commit:** 4cbb4e0

## Commits

| Task | Type | Hash | Description |
|------|------|------|-------------|
| Task 0 RED | (verification only) | — | No commit — failure reproduced; no file change |
| Task 1 GREEN | feat | 4cbb4e0 | TEST-INFRA-01 mock fixture + extractor_e2e passes |
| Task 2 REFACTOR | (no-change) | — | Scope confirmed correct; no diff |

## Self-Check

- [x] `tests/integration/conftest.py` exists: FOUND
- [x] Commit 4cbb4e0 exists: FOUND
- [x] `uv run pytest tests/integration/test_extractor_e2e.py -v -m integration` exits 0: PASSED (2 tests)
- [x] `git diff --name-only services/ controllers/ utils/` empty: CONFIRMED
- [x] Mypy count unchanged (32 = 32): CONFIRMED
- [x] Coverage 76.2% ≥ 70%: CONFIRMED
- [x] bge-m3 not downloaded (`/tmp/embedding_models/bge-m3` does not exist): CONFIRMED
