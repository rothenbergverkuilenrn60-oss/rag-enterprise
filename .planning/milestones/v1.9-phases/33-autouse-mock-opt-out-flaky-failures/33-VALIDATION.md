---
phase: 33
slug: autouse-mock-opt-out-flaky-failures
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-18
updated: 2026-05-18
---

# Phase 33 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: 33-RESEARCH.md §Validation Architecture (Nyquist gates).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + pytest-asyncio 1.3.0 (+ pytest-randomly 3.16+ via TEST-09 Wave 0) |
| **Config file** | `pytest.ini` (markers + addopts) |
| **Quick run command** | `uv run pytest tests/unit/<touched_file>.py -q` |
| **Full suite command** | `uv run pytest tests/unit/ -m 'not integration' -q` |
| **Estimated runtime** | ~20 seconds (unit suite, Phase 32 baseline) |

---

## Sampling Rate

- **After every task commit:** Run quick run command for the touched test file (~1-3 sec)
- **After every plan wave:** Run full suite command (~20 sec)
- **Before `/gsd:verify-work`:** TEST-08a-f + TEST-09a-i all green; integration baseline matches Phase 32 close (31 passed / 9 failed / 1 skipped / 3 errors under `-m 'integration and not real_llm and not real_embedder and not benchmark'`).
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

> Maps each PLAN task to one or more gate IDs. Each row's `<automated>` block in the corresponding task is the implementation; gate IDs below are the single-source-of-truth label.

### 33-00 (TEST-08 — real_embedder marker + canary)

| Task ID | Gates Covered | Type | Automated Command | File Exists | Status |
|---------|---------------|------|-------------------|-------------|--------|
| 33-00-01 | TEST-08a | smoke | `grep -q 'real_embedder:' pytest.ini && uv run pytest --markers \| grep -q '@pytest.mark.real_embedder'` | ❌ W0 (edit pytest.ini) | ⬜ pending |
| 33-00-02 | TEST-08b, TEST-08f | unit + regression | `grep -q 'get_closest_marker("real_embedder")' tests/integration/conftest.py && uv run pytest -m 'integration and not real_llm and not real_embedder and not benchmark' --tb=no -q` → 31p/9f/1s/3e | ❌ W0 (edit conftest) / ✅ existing | ⬜ pending |
| 33-00-03 | TEST-08c, TEST-08d | smoke + integration | `test -f tests/integration/test_real_embedder_canary.py && uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder -q` → 1 skipped OR 1 passed | ❌ W0 (new file) | ⬜ pending |
| 33-00-04 | TEST-08e | smoke | `grep -q '^## Test Infrastructure' docs/RUNBOOK.md && grep -q '^### Real-embedder opt-out' docs/RUNBOOK.md` | ❌ W0 (edit RUNBOOK) | ⬜ pending |

**Gate matrix (33-00):**

| Gate ID | Requirement | Test Type | Authoritative Command | Source Task |
|---------|-------------|-----------|------------------------|-------------|
| TEST-08a | `real_embedder` marker registered | smoke | `grep -q 'real_embedder:' pytest.ini` | 33-00-01 |
| TEST-08b | Autouse fixture honors marker | unit | `grep -q 'get_closest_marker("real_embedder")' tests/integration/conftest.py` | 33-00-02 |
| TEST-08c | Canary file exists + structured | smoke | `test -f tests/integration/test_real_embedder_canary.py` | 33-00-03 |
| TEST-08d | Canary skips/passes cleanly | integration | `uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder -q` → 1 skipped OR 1 passed | 33-00-03 |
| TEST-08e | Docs section exists | smoke | `grep -q '^## Test Infrastructure' docs/RUNBOOK.md` | 33-00-04 |
| TEST-08f | Integration baseline unchanged | regression | `uv run pytest -m 'integration and not real_llm and not real_embedder and not benchmark' --tb=no -q` → 31p/9f/1s/3e | 33-00-02 (post-edit sentinel) |

### 33-01 (TEST-09 — registry reset + mock-shape + pytest-randomly)

| Task ID | Gates Covered | Type | Automated Command | File Exists | Status |
|---------|---------------|------|-------------------|-------------|--------|
| 33-01-01 | TEST-09a, TEST-09b | smoke + dep install | `grep -q '"pytest-randomly>=3.16.0"' pyproject.toml && grep -q '^pytest-randomly' requirements-dev.txt && uv sync && uv pip show pytest-randomly` → Version ≥ 3.16 | ❌ W0 (dep install) | ⬜ pending |
| 33-01-02 | (Cluster B fix; supports TEST-09g) | unit | `grep -n 'embed_batch=AsyncMock' tests/unit/test_memory_service_extra.py && uv run pytest tests/unit/test_memory_service_extra.py::test_long_term_save_fact_calls_insert -q` → 1 passed | ❌ W0 (edit test) | ⬜ pending |
| 33-01-03 | TEST-09c, TEST-09g | smoke + unit | `grep -q '_reset_tool_registry' tests/conftest.py && uv run pytest <7 named node-ids> -q` → 0 failed | ❌ W0 (new fixture) | ⬜ pending |
| 33-01-04 | TEST-09d, TEST-09e, TEST-09f, TEST-09h, TEST-09i | unit suite + regression + perf | three seed runs with OCR Cluster C deselect + integration baseline + runtime ceiling | ✅ via plugin (after 33-01-01) | ⬜ pending |

**Gate matrix (33-01):**

| Gate ID | Requirement | Test Type | Authoritative Command | Source Task |
|---------|-------------|-----------|------------------------|-------------|
| TEST-09a | pytest-randomly installed (pyproject) | smoke | `uv pip show pytest-randomly` → Version ≥ 3.16 | 33-01-01 |
| TEST-09b | pytest-randomly in requirements-dev.txt | smoke | `grep -q '^pytest-randomly' requirements-dev.txt` | 33-01-01 |
| TEST-09c | Reset fixture lands in tests/conftest.py | smoke | `grep -q '_reset_tool_registry' tests/conftest.py` | 33-01-03 |
| TEST-09d | Seed 12345 green (OCR cluster deselected) | unit suite | `uv run pytest tests/unit/ -m 'not integration' -p randomly --randomly-seed=12345 --deselect <OCR cluster: 4 node-ids> -q` → 0 failed | 33-01-04 |
| TEST-09e | Seed 67890 green (OCR cluster deselected) | unit suite | same with `--randomly-seed=67890` | 33-01-04 |
| TEST-09f | Seed 99999 green (OCR cluster deselected) | unit suite | same with `--randomly-seed=99999` | 33-01-04 |
| TEST-09g | 7 named failures (RESEARCH §Q1) resolved | unit | `uv run pytest tests/unit/test_memory_service_extra.py::test_long_term_save_fact_calls_insert tests/unit/test_pipeline_tool_schema_regression.py::test_registry_anthropic_shape_satisfies_call_agentic_turn tests/unit/test_recall_tool.py::test_recall_tool_registered_once tests/unit/test_retrieve_tool.py::TestRetrieveToolRegistration tests/unit/test_retrieve_tool.py::TestSchemasForParity tests/unit/test_web_search_tool.py::TestWebSearchToolRegistration -q` → all green | 33-01-03 (covers all 7 once fixture lands; 33-01-02 lands the Cluster B half) |
| TEST-09h | Integration baseline unchanged | regression | same as TEST-08f (per D-VERIFY-02) | 33-01-04 |
| TEST-09i | Unit-suite runtime non-regression | perf | full suite < 1.05× Phase 32 baseline (~21 sec ceiling) | 33-01-04 |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## OCR Cluster C — Authoritative Deselect List

These 4 node-ids are deselected from TEST-09d/e/f gates (Phase 31 EVT-02 residue, deferred to v1.10 / TEST-12 candidate — RESEARCH §Q2 + §Q8):

```
tests/unit/test_ocr_engine.py::test_semaphore_serialises_concurrent_extract_pdf_calls
tests/unit/test_ocr_failure_modes.py::test_extract_pdf_still_uses_semaphore
tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_retries_once_then_surfaces_error
tests/unit/test_ocr_failure_modes.py::test_extract_pdf_timeout_then_success_on_retry
```

---

## Wave 0 Requirements

### 33-00 (TEST-08)
- [ ] `tests/integration/test_real_embedder_canary.py` — new file (~30 LOC) — 33-00-03
- [ ] `docs/RUNBOOK.md` — new `## Test Infrastructure` section — 33-00-04
- [ ] `tests/integration/conftest.py` — edit fixture signature + add opt-out branch — 33-00-02
- [ ] `pytest.ini` — append `real_embedder:` marker entry — 33-00-01

### 33-01 (TEST-09)
- [ ] `tests/conftest.py` — add `_reset_tool_registry` autouse fixture (single-entry list per RESEARCH §Q1) — 33-01-03
- [ ] `tests/unit/test_memory_service_extra.py:235` — mock-shape patch (Cluster B fix per RESEARCH §Q3) — 33-01-02
- [ ] `pyproject.toml [dependency-groups].dev` + `requirements-dev.txt` — pytest-randomly dual-write — 33-01-01
- [ ] Framework install: `uv add --dev "pytest-randomly>=3.16.0"` — 33-01-01

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real bge-m3 model load + encode | TEST-08 canary pass (not skip) | Requires `$APP_MODEL_DIR/bge-m3` + `bge-m3-rerank` on PG host; CI host lacks files | On PG host with model dir set: `uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder -q` → 1 passed |

---

## Out-of-Scope (OCR Cluster — RESEARCH §Q2)

The 4 OCR `asyncio.Semaphore`-loop-binding failures (random-order-only) trace to Phase 31 EVT-02 residue, not TEST-08/TEST-09. They are `--deselect`'d from seed gates (TEST-09d/e/f) and documented as v1.10 candidate (TEST-12). NOT a regression introduced by this phase. 33-01-04's SUMMARY surfaces the deferral; no production code under `services/extractor/` is modified in this phase.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (all 8 tasks have automated gates)
- [x] Wave 0 covers all MISSING references (4 entries for 33-00; 4 entries for 33-01)
- [x] No watch-mode flags
- [x] Feedback latency < 20s for unit gates, < 90s for integration baseline gate
- [x] `nyquist_compliant: true` set in frontmatter (planner pass — pending plan-checker)

**Approval:** planner-complete (pending plan-checker)
</content>
</invoke>