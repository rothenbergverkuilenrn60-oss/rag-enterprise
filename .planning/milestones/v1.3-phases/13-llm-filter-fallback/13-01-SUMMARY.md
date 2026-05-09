---
phase: 13-llm-filter-fallback
plan: 01
subsystem: services/nlu
tags: [nlu, llm-fallback, redis-cache, async, dataclass, singleton, NLU-02]
requires:
  - utils/cache.py::cache_get
  - utils/cache.py::cache_set
  - services/generator/llm_client.py::get_llm_client
  - services/generator/llm_client.py::BaseLLMClient.chat
provides:
  - services/nlu/filter_extractor.py::ExtractionResult
  - services/nlu/filter_extractor.py::FilterExtractor
  - services/nlu/filter_extractor.py::get_filter_extractor
  - services/nlu/filter_extractor.py::_FILTER_EXTRACT_SYSTEM
affects: []
tech_stack:
  added:
    - typing.Literal (fallback_source field validation)
    - anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError (LLM exception domain)
    - json.JSONDecodeError (parse exception domain)
    - utils.cache.cache_get / cache_set (Redis namespace 'nlu:filter')
  patterns:
    - "Regex-first composition: sync extract_filters() short-circuits LLM path on hit (D-11)"
    - "Two narrow ERR-01 exception tuples (D-13): one per try-block boundary"
    - "Lazy import of get_llm_client in __init__ avoids circular dependency (D-01)"
    - "Module-level singleton + get_*() factory mirrors services/pipeline.py pipeline factories"
    - "frozen=True dataclass + Literal[...] | None typing for trace-able fallback_source"
key_files:
  created: []
  modified:
    - services/nlu/filter_extractor.py
decisions:
  - "D-02 freeze preserved byte-identical: existing FilterExtractionResult, extract_filters, _PAGE_RE/_CLAUSE_RE/_SECTION_RE patterns unchanged"
  - "task_type='nlu' (NOT 'classify' or 'generate') — semantically correct, routes to Haiku per llm_client.py:100"
  - "chat() + manual JSON parse chosen over chat_with_tools (D-10)"
  - "Cache write gated by 'if filters:' — empty/failed extractions are NOT cached (Pitfall 1)"
  - "fallback_source='llm' iff filters non-empty after parse; None when LLM hit yielded zero filters"
  - "Suppressed one mypy union-attr false positive on m.group(0) — AttributeError is intentional control flow per D-13"
metrics:
  duration_minutes: 4
  duration_seconds: 260
  tasks_completed: 2
  files_modified: 1
  lines_added: 164
  lines_removed: 1
  commits:
    - hash: 7ef9135
      task: 1
      message: "feat(13-01): add ExtractionResult dataclass + LLM prompt + imports"
    - hash: 660023b
      task: 2
      message: "feat(13-01): add FilterExtractor class + get_filter_extractor singleton"
  completed_date: 2026-05-09T03:19:00Z
---

# Phase 13 Plan 01: LLM Filter Extractor — Class + Dataclass + Singleton Summary

`FilterExtractor` async class with regex-first composition, Redis cache, and Haiku LLM fallback added to `services/nlu/filter_extractor.py`; existing 91-line module preserved byte-identical (D-02).

## What Was Built

`services/nlu/filter_extractor.py` grew from 91 → 254 lines. Five new module-level constructs were added; all 56 existing lines (frozen regex patterns + `FilterExtractionResult` dataclass + `extract_filters` function) are byte-identical to commit `ae06fb1` (v1.1 freeze).

### Line spans (final file)

| Construct | Lines | Type |
|-----------|-------|------|
| Imports (extended) | 21–34 | additive |
| `_PAGE_RE` / `_CLAUSE_RE` / `_SECTION_RE` (frozen) | 38–40 | unchanged from v1.1 |
| `_FILTER_EXTRACT_SYSTEM` prompt constant | 43–62 | new |
| `FilterExtractionResult` dataclass (frozen) | 65–75 | unchanged from v1.1 |
| `ExtractionResult` frozen dataclass | 78–90 | new |
| `extract_filters` function (frozen) | 93–128 | unchanged from v1.1 |
| `FilterExtractor` class | 138–229 | new |
| `_filter_extractor` singleton | 231 | new |
| `get_filter_extractor()` factory | 234–245 | new |
| `__all__` (extended) | 248–254 | additive |

### Module exports (post-Wave-1)

```python
__all__ = [
    "ExtractionResult",          # NEW — frozen dataclass with fallback_source
    "FilterExtractionResult",    # preserved (D-02)
    "FilterExtractor",           # NEW — async LLM-fallback extractor class
    "extract_filters",           # preserved (D-02)
    "get_filter_extractor",      # NEW — module-level singleton factory
]
```

## Verification

| Check | Result |
|-------|--------|
| 7 existing regex tests `tests/unit/test_filter_extractor.py::TestExtractFilters` | PASS (no regression) |
| Full unit suite (357 tests excluding pgvector integration) | 357 passed, 1 skipped, 0 failed |
| `ruff check services/nlu/filter_extractor.py` | All checks passed |
| `mypy --strict services/nlu/filter_extractor.py` | 0 new errors (pre-existing baseline in cache.py / llm_client.py / settings.py — out of scope per SCOPE BOUNDARY rule) |
| `python -c "from services.nlu.filter_extractor import FilterExtractor, ExtractionResult, get_filter_extractor; assert get_filter_extractor() is get_filter_extractor()"` | exit 0 |
| Inline async smoke (regex hit, LLM hit, invalid JSON, API exception, wrong type) | All 5 scenarios pass |
| D-02 freeze: lines for `_PAGE_RE..._SECTION_RE`, `FilterExtractionResult`, `extract_filters` byte-identical vs `ae06fb1` | Confirmed — `diff` reports `Files are identical` for all 3 frozen blocks |

### Acceptance criteria grep matrix (all 22 pass)

| # | Check | Expected | Actual |
|---|-------|----------|--------|
| 1 | `^@dataclass\(frozen=True\)` | =1 | 1 |
| 2 | `^class ExtractionResult:` | =1 | 1 |
| 3 | `^class FilterExtractionResult:` | =1 | 1 |
| 4 | `^_FILTER_EXTRACT_SYSTEM:.*str.*=` | =1 | 1 |
| 5 | `^from utils.cache import cache_get, cache_set` | =1 | 1 |
| 6 | `^import anthropic` | =1 | 1 |
| 7 | `^from typing import Literal` | =1 | 1 |
| 8 | `^class FilterExtractor:` | =1 | 1 |
| 9 | `async def extract` | =1 | 1 |
| 10 | `^_filter_extractor:\s*FilterExtractor` | =1 | 1 |
| 11 | `^def get_filter_extractor` | =1 | 1 |
| 12 | `task_type="nlu"` | =1 | 1 |
| 13 | `task_type="generate"` | =0 | 0 |
| 14 | `chat_with_tools` | =0 | 0 |
| 15 | `except Exception` | =0 | 0 |
| 16 | LLM exception tuple `anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError` | =1 | 1 |
| 17 | Parse exception tuple `json.JSONDecodeError, AttributeError, TypeError, ValueError` | =1 | 1 |
| 18 | `cache_get("nlu:filter"` | =1 | 1 |
| 19 | `cache_set("nlu:filter"` | =1 | 1 |
| 20 | `hashlib` | =0 | 0 |
| 21 | `cache_set` gated by `if filters:` | ≥1 | 1 |
| 22 | Lazy import in `__init__` | ≥1 | 1 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — mypy false positive] Suppress `union-attr` on `m.group(0)`**
- **Found during:** Task 2 (post-implementation mypy run)
- **Issue:** `mypy --strict` reported `services/nlu/filter_extractor.py:200: Item "None" of "Match[str] | None" has no attribute "group"  [union-attr]`
- **Why it's a false positive:** The plan deliberately uses `re.search(...) → m.group(0)` to raise `AttributeError` when `m is None`, caught by the parse-domain narrow tuple `(json.JSONDecodeError, AttributeError, TypeError, ValueError)` (D-13). mypy doesn't follow try/except control flow; the runtime behavior is correct.
- **Fix:** Added inline `# type: ignore[union-attr]  # AttributeError if m is None — caught below (D-13)` comment, matching the project's existing `# type: ignore` convention at `services/generator/llm_client.py:615`.
- **Files modified:** `services/nlu/filter_extractor.py:200`
- **Commit:** `660023b`

No other deviations. Both task implementations match the plan spec exactly.

### Authentication Gates

None.

## Threat-Model Alignment

The plan listed 7 STRIDE threats (T-13-01-01 .. T-13-01-07). All 5 with `mitigate` disposition are honored by the as-built code:

| Threat ID | Disposition | Mitigation in code |
|-----------|-------------|---------------------|
| T-13-01-01 (prompt injection → coerced JSON) | mitigate | `temperature=0.0` + strict JSON-only prompt (`仅返回 JSON 对象`); `int(page)` coercion + `isinstance(section, str)` guard reject malformed types |
| T-13-01-02 (hostile string `section_id`) | mitigate | `isinstance(section, str) and section` guard; downstream `vector_store.search` parameterized JSONB filter |
| T-13-01-05 (log leakage of LLM output) | mitigate | `raw[:200]!r` truncation; `!r` repr escapes control chars |
| T-13-01-07 (greedy regex over multi-JSON prose) | mitigate | Prompt constraint + temperature=0.0; greedy-match failure → `json.JSONDecodeError` caught by parse-domain tuple → empty result |

`accept`-disposition threats (T-13-01-03 multi-tenant Redis exposure, T-13-01-04 cache-busting DoS, T-13-01-06 audit log) require no Wave 1 code changes — Wave 2 callsite migration retains discretion to add `extraction.fallback_source` to pipeline audit fields.

## Key Decisions Made During Execution

1. **Mypy `type: ignore` placement** — Used inline comment on the offending line (matches `llm_client.py:615` precedent) rather than `# mypy: ignore-errors` file-level pragma (would mask future bugs).
2. **No deviation on prompt text** — Prompt copied verbatim from `13-CONTEXT.md <specifics>` section; D-09 rationale (Haiku via `task_type='nlu'`) preserved unchanged.
3. **Frozen-block verification method** — Used three independent `awk` boundary extractions (regex patterns / dataclass / function body) compared against `git show ae06fb1:services/nlu/filter_extractor.py` rather than line-number-based slicing. Result: all 3 blocks `Files are identical`.
4. **Skipped wider integration smoke** — Did not run `tests/unit/test_pgvector_service.py` (requires live PostgreSQL); pre-existing pgvector integration tests are excluded from default suite per Phase 12 SUMMARY notes.

## Self-Check: PASSED

- File created: `.planning/phases/13-llm-filter-fallback/13-01-SUMMARY.md` — verified post-Write
- Commit `7ef9135` (Task 1) found in `git log` — verified
- Commit `660023b` (Task 2) found in `git log` — verified
- `services/nlu/filter_extractor.py` exists and contains `FilterExtractor`, `ExtractionResult`, `get_filter_extractor` — verified via `grep`

## Wave 2 / Wave 3 Readiness

Plan 13-02 (pipeline migration, 4 callsites in `services/pipeline.py`) and Plan 13-03 (test coverage extension) can both proceed in parallel. The Wave 1 module shape is stable:

- Public exports: `ExtractionResult`, `FilterExtractor`, `get_filter_extractor`
- Test reset pattern: `services.nlu.filter_extractor._filter_extractor = None`
- Test bypass pattern: `inst = FilterExtractor.__new__(FilterExtractor); inst._llm = AsyncMock()`
- Cache namespace: `"nlu:filter"` (literal — Wave 3 monkeypatches `services.nlu.filter_extractor.cache_get` / `cache_set` at module binding level, NOT `utils.cache.*`)
