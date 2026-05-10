---
phase: 13-llm-filter-fallback
verified: 2026-05-09T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 13 Verification

**Verdict:** PASS
**Status:** passed

## AC Coverage (NLU-02)

| AC | Description | Status | Evidence |
|----|-------------|--------|----------|
| #1 | LLM only on regex miss | PASS | `services/nlu/filter_extractor.py:166-174` short-circuits when `regex_result.filters` truthy, returns `fallback_source="regex"` before any `_llm.chat` call. Test `tests/unit/test_filter_extractor.py:106-111 test_regex_hit_skips_llm` asserts `_llm.chat.assert_not_awaited()`. PASSED. |
| #2 | Cache w/ TTL, single LLM call per identical query | PASS | `cache_get/cache_set` from `utils/cache.py` used at `filter_extractor.py:177` and `:218-221`. Test `test_cache_hit_skips_llm:172-211` asserts `_llm.chat.await_count == 1` over 2 identical queries. PASSED. |
| #3 | Invalid JSON / API exceptions → no propagation | PASS | Two narrow tuples: LLM domain `(anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError)` at `:193`; parse domain `(json.JSONDecodeError, AttributeError, TypeError, ValueError)` at `:212`. Both return `ExtractionResult(filters={}, semantic_query=query, fallback_source=None)`. No bare `except`. Tests `test_invalid_json_returns_empty:136` AND `test_llm_api_exception_returns_empty:157` PASSED. |
| #4 | `fallback_source` field exposed | PASS | `ExtractionResult` dataclass at `:78-90` has `fallback_source: Literal["regex", "llm"] \| None`. Single-valued per D-11. |
| #5 | 5 unit + 1 integration tests | PASS | 6 unit tests in `TestFilterExtractor` class (`tests/unit/test_filter_extractor.py:101-240`): regex-hit, LLM-hit, invalid-JSON, API-exception, cache-hit, cache-disabled. 1 integration `tests/integration/test_filter_extractor_llm.py:21 pytestmark=[pytest.mark.integration]`, 1 selected via `--collect-only -m integration`. |

## Cross-cutting Constraints

| Constraint | Status | Evidence |
|-----------|--------|----------|
| D-02: `extract_filters` + `FilterExtractionResult` byte-identical to baseline `ae06fb1` | PASS | AST extraction + diff: both `=== IDENTICAL ===`. |
| D-07: 4 callsites migrated | PASS | `grep -c 'await get_filter_extractor().extract(req.query)' services/pipeline.py == 4` (lines 317, 478, 674, 1166); `grep -c 'extract_filters(req.query)' == 0`. |
| D-09: `task_type="nlu"` only | PASS | `services/nlu/filter_extractor.py:191 task_type="nlu"`; no `"generate"` literal. |
| D-10: `chat()` not `chat_with_tools` | PASS | `grep -c 'chat_with_tools' services/nlu/filter_extractor.py == 0`; uses `_llm.chat(...)` at `:187`. |
| `utils/cache.py` reuse (no hand-rolled hash) | PASS | `grep -c 'hashlib' services/nlu/filter_extractor.py == 0`; imports `cache_get, cache_set` at `:34`. |
| D-12: `semantic_query=query` on LLM hit (no stripping) | PASS | `filter_extractor.py:226` returns `semantic_query=query`; test `test_regex_miss_llm_hit:131` asserts `result.semantic_query == "关于第三章的内容"`. |
| D-13/D-14: graceful degradation, no propagation | PASS | Both try blocks at `:186-195` and `:198-214` return empty `ExtractionResult` on raise; `test_llm_api_exception_returns_empty` confirms `httpx.HTTPError` swallowed. |
| Pitfall 1: never cache empty/failed | PASS | `:217 if filters:` guard before `cache_set`; `test_invalid_json_returns_empty` asserts `cache_set_mock.assert_not_awaited()`. |

## Test Results

- `pytest tests/unit/test_filter_extractor.py -x`: **13/13 passed** (7 regex preserved + 6 new LLM-path) in 0.78s.
- `pytest tests/integration/test_filter_extractor_llm.py --collect-only -m integration`: **1 test collected** (`test_filter_extractor_e2e_chinese_section`).
- Phase 12 regression `pytest tests/unit/test_swarm_pipeline.py tests/unit/test_agent_pipeline_refactor.py -x`: **19 passed** in 37.98s.
- `ruff check services/nlu/filter_extractor.py services/pipeline.py tests/unit/test_filter_extractor.py tests/integration/test_filter_extractor_llm.py`: **All checks passed**.
- `mypy --strict services/nlu/filter_extractor.py`: **0 errors in filter_extractor.py** (76 pre-existing baseline errors in `llm_client.py` etc., none new). `mypy --strict services/pipeline.py`: 11 pre-existing errors (untyped factory funcs, GenerationResponse Any returns, MemoryService.save_turn intent=None — none introduced by Phase 13 callsite migration).

## Findings

**BLOCKERS:** None.

**FLAGS:** None.

**OK:**
- All 5 NLU-02 acceptance criteria satisfied with evidence on the code, not plan claims.
- D-02 freeze contract preserved exactly (AST byte-identical for `extract_filters` + `FilterExtractionResult`).
- 4/4 pipeline callsites migrated; zero residual sync `extract_filters(req.query)` calls.
- Narrow ERR-01 exception tuples per project standard; no bare `except Exception:`.
- `utils/cache.py` reused (no hand-rolled MD5/Redis logic).
- Phase 12 swarm/agent regression: 19/19 still pass post-Wave-2 callsite migration.
- Integration test correctly module-marked `pytestmark=[pytest.mark.integration]`; excluded from default run by `pytest.ini addopts="-m 'not integration'"`.
- Singleton reset autouse fixture mirrors Phase 12 pattern (Pitfall 7 mitigated).

**Behavioral spot-checks (Step 7b):**
- Unit test suite: 13/13 PASS — verifies regex-hit, LLM-hit, parse-fail, API-fail, cache-hit, cache-disabled paths produce expected `ExtractionResult` shapes.
- Integration collection: 1/1 PASS — confirms live-LLM smoke test wired and discoverable under `-m integration`. Live execution skipped (requires `OPENAI_API_KEY` + network; per D-05 contract this is run on demand, not in CI).

## Recommendation

**PASS → ready for `/gsd-ship`.**

All 5 NLU-02 acceptance criteria + all 9 cross-cutting D-contract constraints verified directly against the code. Test suite green; no regressions; no new lint or type errors.
