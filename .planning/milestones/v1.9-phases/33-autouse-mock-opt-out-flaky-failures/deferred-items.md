# Phase 33 Deferred Items

## TEST-09h verification — pre-existing environment-specific collection error

**Discovered during:** Task 33-01-04 (integration baseline check)

**Issue:** `tests/integration/test_ragas_eval.py` fails at collection time with
`PermissionError: [Errno 13] Permission denied: '/app'` because
`eval/models.py:36-37` declares `EvalSettings.ragas_eval_dataset = Path("/app/eval/datasets/qa_pairs.json")`
and `ragas_report_dir = Path("/app/eval_reports")`, and `eval/models.py:55`
attempts `p.mkdir(parents=True, exist_ok=True)` at module import time.

**Root cause:** Docker container paths (`/app/...`) are hard-coded as defaults
in `EvalSettings`. On a WSL host (or any non-Docker dev environment), `/app`
either doesn't exist or isn't writable for the test runner.

**Verified pre-existing:** Reproduced before plan-33-01 changes were applied
(via `git stash` then `pytest` — both showed identical collection error). NOT
caused by:
- `pytest-randomly` (it's a unit-suite plugin and the failure happens before
  pytest selects tests by marker)
- `_reset_tool_registry` autouse fixture (the failure is at MODULE-IMPORT time
  in `eval/models.py`, before pytest even reads `tests/conftest.py`)
- `embed_batch` mock-shape fix (unrelated module)

**Scope decision:** OUT OF SCOPE for plan 33-01 per the deviation rules'
SCOPE BOUNDARY ("Only auto-fix issues DIRECTLY caused by the current task's
changes"). The plan's TEST-09h gate cannot be machine-verified on this host;
its 31p/9f/1s/3e baseline was likely computed in a Docker environment.

**Recommended fix (future):**
- Change `EvalSettings.ragas_eval_dataset` and `ragas_report_dir` defaults to
  env-var-driven (e.g. `Path(os.environ.get("RAGAS_REPORT_DIR", "/app/eval_reports"))`)
  with a CWD-relative fallback for dev environments.
- Or: gate the `p.mkdir(...)` at line 55 behind a check `if not p.parent.exists()
  or not os.access(p.parent, os.W_OK): return p` so the mkdir doesn't crash
  collection.

**Recommendation:** File as a v1.10 cleanup item alongside TEST-12 (OCR cluster).

---

## TEST-12 (proposed v1.10 requirement) — OCR Cluster C flaky tests

**Discovered during:** Phase 31 EVT-02 (carry-forward from plan 33-01 / Q2 guardrail).

**Cluster:** 4 tests deferred from random-order verification:
- `tests/unit/test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls`
- `tests/unit/test_ocr_failure_modes.py::test_extract_pdf_still_uses_semaphore`
- `tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_retries_once_then_surfaces_error`
- `tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_then_success_on_retry`

**Treatment in plan 33-01:** Deselected via 4 explicit `--deselect` flags during
all three seed-verification runs (RESEARCH §Q2 + VALIDATION TEST-09d/e/f).

**Recommendation:** Append a TEST-12 candidate row to
`.planning/REQUIREMENTS.md` for the v1.10 backlog. Do NOT add the requirement
in plan 33-01 — surface only.
