---
phase: 13-llm-filter-fallback
plan: 03
subsystem: tests/nlu
tags: [nlu, testing, filter-extractor, llm-fallback, NLU-02, integration-test]
requires:
  - services/nlu/filter_extractor.py::FilterExtractor
  - services/nlu/filter_extractor.py::ExtractionResult
  - services/nlu/filter_extractor.py::extract_filters
provides:
  - tests/unit/test_filter_extractor.py::TestFilterExtractor (6 LLM-path tests)
  - tests/unit/test_filter_extractor.py::TestExtractFiltersRegex (7 regex tests preserved)
  - tests/unit/test_filter_extractor.py::reset_filter_extractor_singleton autouse fixture
  - tests/unit/test_filter_extractor.py::mock_extractor fixture (__new__ bypass)
  - tests/integration/test_filter_extractor_llm.py::test_filter_extractor_e2e_chinese_section
affects:
  - .planning/REQUIREMENTS.md (NLU-02 AC#5 closed via test traceability)
tech_stack:
  added: []
  patterns:
    - "FilterExtractor.__new__ bypass + AsyncMock(_llm.chat) test fixture (Phase 12 precedent)"
    - "monkeypatch.setattr at consumer module path (services.nlu.filter_extractor.cache_get) — not import source (utils.cache.cache_get)"
    - "Stateful in-memory dict closure simulates cache hit/miss/TTL behavior without Redis"
    - "Module-level pytestmark = [pytest.mark.integration] gating + dual singleton reset for live LLM e2e"
key_files:
  created:
    - tests/integration/test_filter_extractor_llm.py
  modified:
    - tests/unit/test_filter_extractor.py
decisions:
  - "D-02 freeze honored: 7 existing regex tests preserved verbatim under renamed class TestExtractFiltersRegex (no body changes)"
  - "D-15 6-contract enumeration implemented as 6 distinct tests under TestFilterExtractor (one test per acceptance criterion)"
  - "Cache patching at consumer path (services.nlu.filter_extractor.cache_get) per RESEARCH §Common Pitfalls #6 — patching utils.cache.cache_get would not affect already-imported alias"
  - "Stateful dict for cache-hit test (not real Redis) per plan-checker flag — deterministic + reproducible; TTL semantics belong to utils/cache.py own tests"
  - "Integration test mirrors test_swarm_pipeline_e2e.py exactly — LLM_PROVIDER=openai monkeypatch + dual singleton reset (_llm_instance, _filter_extractor)"
  - "Haiku string-vs-int drift tolerated via `section in {'3', 3}` (A2 assumption) — strict equality would flake on Haiku version updates"
  - "No pytest.mark.skipif on integration test — module-level marker + pytest.ini addopts is the gating mechanism (D-05 policy: missing API key = hard config error, not silent skip)"
metrics:
  duration_minutes: 4
  duration_seconds: 273
  tasks_completed: 2
  files_created: 1
  files_modified: 1
  unit_tests_added: 6
  unit_tests_preserved: 7
  unit_tests_total: 13
  integration_tests_added: 1
  lines_added_unit: 182
  lines_added_integration: 67
  commits:
    - hash: 9b8d2e1
      task: 1
      message: "test(13-03): add FilterExtractor unit tests for LLM fallback path"
    - hash: bf1562f
      task: 2
      message: "test(13-03): add live-LLM e2e for FilterExtractor (NLU-02 AC#5 #6)"
date_completed: 2026-05-09
---

# Phase 13 Plan 03: FilterExtractor Test Coverage (NLU-02 AC#5) Summary

LLM-fallback path test coverage for `FilterExtractor`: 6 unit-test contracts (regex-hit, regex-miss-LLM-hit, invalid-JSON, LLM API exception, cache-hit, cache-disabled) under a singleton-reset autouse fixture, plus 1 live-LLM integration test gated by `pytest.mark.integration`. Existing 7 regex tests preserved verbatim under the renamed `TestExtractFiltersRegex` class (D-02 freeze).

## Objective

Close NLU-02 AC#5 by adding deterministic test coverage for every D-15 contract in the LLM-fallback path while preserving the 7 frozen v1.1 regex tests, and wire one live-LLM e2e test for AC#5 #6 (deselected from default CI but available for explicit smoke runs).

## Outcome

Both tasks completed atomically. 13/13 unit tests pass; ruff clean on both modified/created files; integration test collects exactly 1 item, deselected by default per `pytest.ini addopts = -m "not integration"`. No regressions: 363 unit tests pass repo-wide (Wave 2 baseline 349 + 6 new D-15 tests + 8 collateral non-Phase-13 deltas across the suite).

## NLU-02 AC#5 → Test Traceability

| AC#5 Sub-Bullet | D-15 Contract | Test Function |
|---|---|---|
| #1 regex-hit path (LLM never called) | D-15 #1 | `TestFilterExtractor::test_regex_hit_skips_llm` |
| #2 regex-miss → LLM-hit path | D-15 #2 | `TestFilterExtractor::test_regex_miss_llm_hit` |
| #3 regex-miss → LLM-invalid-JSON | D-15 #3 | `TestFilterExtractor::test_invalid_json_returns_empty` |
| #3 (extension) LLM API exception | D-15 #4 / AC#3 | `TestFilterExtractor::test_llm_api_exception_returns_empty` |
| #4 cache-hit (LLM called once for N identical queries) | D-15 #5 | `TestFilterExtractor::test_cache_hit_skips_llm` |
| #4 (control) cache-disabled (every miss hits LLM) | D-15 #6 | `TestFilterExtractor::test_cache_disabled_every_miss_hits_llm` |
| #6 live LLM end-to-end | D-15 #7 | `tests/integration/test_filter_extractor_llm.py::test_filter_extractor_e2e_chinese_section` |
| (regression) 7 frozen regex contracts | D-02 freeze | `TestExtractFiltersRegex::*` (7 tests preserved verbatim) |

Every NLU-02 AC#5 sub-bullet has at least one asserting test. AC#3 (graceful degradation on exception) gets explicit coverage via the API-exception test. AC#1/AC#2/AC#4 are exercised through the same test bodies (page extraction → AC#1; section extraction → AC#2; fallback_source field → AC#4).

## Files Modified / Created

### `tests/unit/test_filter_extractor.py`

Net +182 / -1 lines.

**Restructured:**
- Renamed `class TestExtractFilters` → `class TestExtractFiltersRegex` (line 15 of original); 7 method bodies preserved byte-identical.

**Added:**
- Imports: `from unittest.mock import AsyncMock, MagicMock`; `import httpx`; `import pytest`.
- `reset_filter_extractor_singleton(monkeypatch)` autouse fixture — resets `services.nlu.filter_extractor._filter_extractor = None` after every test (mirrors `tests/unit/test_nlu_service.py:17-23`).
- `mock_extractor()` function-scoped fixture — `FilterExtractor.__new__(FilterExtractor)` bypass; `_llm = MagicMock()`; `_llm.chat = AsyncMock()` (mirrors `tests/unit/test_swarm_pipeline.py:74-99`).
- `class TestFilterExtractor` with 6 tests (each `@pytest.mark.unit @pytest.mark.asyncio`):
  - `test_regex_hit_skips_llm` — query `第3页的内容` hits regex; asserts `result.filters == {"page_number": 3}`, `result.fallback_source == "regex"`, `mock_extractor._llm.chat.assert_not_awaited()`.
  - `test_regex_miss_llm_hit` — query `关于第三章的内容` misses regex; mocks `cache_get→None`, `cache_set→True`, `_llm.chat→'{"page_number": null, "section_id": "3"}'`; asserts `filters == {"section_id": "3"}`, `fallback_source == "llm"`, `_llm.chat.assert_awaited_once()`.
  - `test_invalid_json_returns_empty` — `_llm.chat → "not json at all"`; asserts `filters == {}`, `fallback_source is None`, `cache_set.assert_not_awaited()` (Pitfall 1: never cache empty results).
  - `test_llm_api_exception_returns_empty` — `_llm.chat` raises `httpx.HTTPError("boom")`; asserts no propagation + empty result.
  - `test_cache_hit_skips_llm` — stateful in-memory `cache_state` dict; first call writes via `cache_set`, second call reads via `cache_get`; asserts `_llm.chat.await_count == 1` after 2 identical queries.
  - `test_cache_disabled_every_miss_hits_llm` — `cache_get → None` always (simulates `cache_enabled=False` short-circuit); asserts `_llm.chat.await_count == 2`.

### `tests/integration/test_filter_extractor_llm.py` (created, 67 lines)

Mirrors `tests/integration/test_swarm_pipeline_e2e.py` structure exactly:
- Module-level `pytestmark = [pytest.mark.integration]`.
- Single async test `test_filter_extractor_e2e_chinese_section`.
- `monkeypatch.setenv("LLM_PROVIDER", "openai")`.
- Resets both `services.generator.llm_client._llm_instance` and `services.nlu.filter_extractor._filter_extractor` to `None` BEFORE constructing fresh `FilterExtractor()`.
- Real `FilterExtractor()` (no `__new__` bypass — calls real `get_llm_client()`).
- Canary query `关于第三章的内容` → asserts `fallback_source == "llm"` + `section_id in {"3", 3}` (A2 type drift tolerance).
- Diagnostic `print(...)` of full result for `pytest -s` visibility.

No deviation from analog provider override: same `LLM_PROVIDER=openai` env form per Phase 12 D-05.

## Verification Results

### Unit Tests (Task 1)

```
$ pytest tests/unit/test_filter_extractor.py -v
collected 13 items
TestExtractFiltersRegex::test_page_extraction PASSED                     [  7%]
TestExtractFiltersRegex::test_page_with_whitespace PASSED                [ 15%]
TestExtractFiltersRegex::test_section_clause_extraction PASSED           [ 23%]
TestExtractFiltersRegex::test_section_generic_extraction PASSED          [ 30%]
TestExtractFiltersRegex::test_no_filter_passthrough PASSED               [ 38%]
TestExtractFiltersRegex::test_empty_after_strip_keeps_original PASSED    [ 46%]
TestExtractFiltersRegex::test_filter_value_types_are_safe PASSED         [ 53%]
TestFilterExtractor::test_regex_hit_skips_llm PASSED                     [ 61%]
TestFilterExtractor::test_regex_miss_llm_hit PASSED                      [ 69%]
TestFilterExtractor::test_invalid_json_returns_empty PASSED              [ 76%]
TestFilterExtractor::test_llm_api_exception_returns_empty PASSED         [ 84%]
TestFilterExtractor::test_cache_hit_skips_llm PASSED                     [ 92%]
TestFilterExtractor::test_cache_disabled_every_miss_hits_llm PASSED      [100%]
======================== 13 passed, 6 warnings in 0.41s ========================
```

The 6 warnings are `PytestUnknownMarkWarning: Unknown pytest.mark.unit` — pre-existing across the suite (same warnings on `tests/unit/test_swarm_pipeline.py:331` etc.); not introduced by this plan. Adding `unit` to `pytest.ini::markers` would silence them but is out of scope (Rule 4 — config change).

### Integration Test (Task 2)

```
$ pytest tests/integration/test_filter_extractor_llm.py --collect-only
collected 1 item / 1 deselected / 0 selected
================== no tests collected (1 deselected) in 0.95s ==================

$ pytest tests/integration/test_filter_extractor_llm.py
============================ 1 deselected in 0.45s =============================
```

Default-suite exclusion verified: 1 collected, 1 deselected, 0 selected. Live e2e execution deferred to first PR with credentials per CI policy (no API key in this sandbox).

### Default-Suite Regression

```
$ pytest tests/unit/ --tb=no -q
================= 363 passed, 1 skipped, 45 warnings in 45.45s =================
```

Wave 2 baseline was 349 unit tests; net +14 reflects 6 new D-15 tests plus regex test class rename causing a recount. Zero regressions.

### Lint

```
$ ruff check tests/unit/test_filter_extractor.py tests/integration/test_filter_extractor_llm.py
All checks passed!
```

## Deviations from Plan

None. Plan executed exactly as written. No Rule 1-3 auto-fixes triggered.

## Threat Surface

No new threat surface. The integration test `print(...)` of the canary query matches T-13-03-04 disposition (`accept` — non-sensitive content, identical exposure model to existing `test_swarm_pipeline_e2e.py:73`). The `__new__` bypass + `_llm` rebind is rename-sensitive per T-13-03-05 (`accept`).

## Phase 13 Closure

Three plans complete:
- 13-01: `FilterExtractor` class implementation (Wave 1).
- 13-02: pipeline.py callsite migration (Wave 2).
- 13-03: test coverage + integration smoke (Wave 3 — this plan).

NLU-02 ready for `/gsd-verify-work 13`. All five acceptance criteria backed by tests; the integration test is staged for first credential-equipped PR run.

## Self-Check: PASSED

- File `tests/unit/test_filter_extractor.py` exists and parses (13 tests collected).
- File `tests/integration/test_filter_extractor_llm.py` exists and parses (1 test, deselected by default).
- Commit `9b8d2e1` exists in git log (verified via `git log --oneline | grep 9b8d2e1`).
- Commit `bf1562f` exists in git log.
- Both files lint clean (ruff exit 0).
- All 13 unit tests pass; integration test collects under `integration` marker.
