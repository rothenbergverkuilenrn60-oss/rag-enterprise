# Phase 9 Deferred Items


## test_worker_startup.py::test_on_startup_tesseract_skips_paddle_warmup — flaky in full unit suite

**Found during:** 09-01 phase-level verification (post Task 4)
**Symptom:** Fails when run as part of `pytest tests/unit/`, passes in isolation.
**Cause:** Pre-existing test isolation/pollution issue — module-level state leaking between tests.
**Out of scope:** Not caused by Phase 9 UI extraction changes (no shared imports between
  worker startup logic and UI/StaticFiles mount). Verified by running the failing test
  alone: PASSES.
**Suggested fix (future):** Add `monkeypatch.delitem(sys.modules, ...)` or restructure
  the worker startup test fixture to reset Paddle warmup state.
