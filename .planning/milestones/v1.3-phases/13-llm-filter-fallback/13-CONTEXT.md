# Phase 13: LLM Filter Fallback - Context

**Gathered:** 2026-05-09
**Status:** Ready for planning

<domain>
## Phase Boundary

When `services/nlu/filter_extractor.py` regex extraction returns an **empty** filter dict, fall back to a Haiku LLM call to extract `page_number` / `section_id` from natural-language Chinese queries (e.g., `"关于第三章的内容"`, `"第三页讲什么"`). Cache LLM results in Redis (`cache_ttl_sec=3600`). Expose `fallback_source: "regex" | "llm" | None` so callers can trace which path produced the filter. Never propagate LLM exceptions or invalid JSON to callers — graceful degradation to "no filter."

Out of scope:
- English-language patterns (deferred per v1.1 D-03)
- Cross-document filter merging across multiple sub-questions (Phase 12 SwarmQueryPipeline territory)
- Frontend changes (Phase 14)
- Coverage floor (Phase 15)
</domain>

<decisions>
## Implementation Decisions

### Architecture
- **D-01:** Refactor regex extractor into a `FilterExtractor` class with `async def extract(query: str) -> ExtractionResult` method, exposed via `get_filter_extractor()` singleton factory. Mirrors `get_query_pipeline()` / `get_agent_pipeline()` / `get_swarm_pipeline()` precedent.
- **D-02:** Existing module-level `extract_filters(query)` function stays as a sync regex-only helper (used internally by `FilterExtractor` and importable for tests). It is NOT removed — the class composes it.

### Return Type
- **D-03:** Pragmatic interpretation of NLU-02 AC#1 (`-> QueryFilter | None`). Method returns a structured `ExtractionResult` dataclass:
  ```python
  @dataclass(frozen=True)
  class ExtractionResult:
      filters: dict[str, int | str]         # may be empty (no filter found)
      semantic_query: str                    # regex-stripped query, or original query on LLM-only path
      fallback_source: Literal["regex", "llm"] | None  # "regex" if regex hit, "llm" if LLM hit, None if both miss
  ```
  This preserves `semantic_query` for the 2/4 callsites that consume it (`pipeline.py:318`, `:479`) while satisfying AC#4 (`fallback_source` field on returned filter). Per-call structured return matches existing `FilterExtractionResult` shape; rename signals the new contract.
- **D-04:** When `filters` is empty AND `fallback_source is None`, semantically equivalent to AC#1's `None` return. Callers using truthiness (`if extraction.filters:`) work unchanged at all 4 callsites.

### Cache Layer
- **D-05:** Redis-backed cache via `utils/cache.py` infrastructure (`redis_url`, `cache_ttl_sec=3600`, `cache_enabled=True`). Multi-worker safe (gunicorn shared cache). Matches AC#2 wording "TTL matching the existing cache layer." Cache key: `nlu:filter:{sha256(query)[:16]}` (full query bytes — no normalization beyond what Python's hashing handles).
- **D-06:** Cache hit serves the cached `ExtractionResult` (filter dict + semantic_query + fallback_source="llm"). Cache miss runs the LLM call and writes the result. TTL invalidation only — no manual invalidate path. If `cache_enabled=False`, every miss hits the LLM.

### Async Interface
- **D-07:** `FilterExtractor.extract` is `async`. All 4 existing callsites in `services/pipeline.py` (lines 317, 478, 674, 1166) migrate from `extract_filters(req.query)` to `await get_filter_extractor().extract(req.query)`. Pipeline contexts are already async — change is contained to those 4 lines.
- **D-08:** Sync regex-only path (`extract_filters` function) remains synchronous for tests and any future sync callers. Class only awaits when invoking the LLM cache layer.

### LLM Model + Prompt
- **D-09:** Use `self._llm.chat(system=_FILTER_EXTRACT_SYSTEM, user=query, temperature=0.0, task_type="nlu")`. `task_type="nlu"` routes to **Haiku** per Phase 11's `_anthropic_model_for_task` / `_openai_model_for_task` (verified at `services/generator/llm_client.py:133, 317, 593`). Haiku is sufficient for structured filter extraction; ~3x cheaper than Sonnet.
- **D-10:** Prompt format: chat() + try/except json.loads pattern, NOT `chat_with_tools`. Matches Phase 12 coordinator decomposition pattern. System prompt instructs JSON-only output:
  ```json
  {"page_number": 3, "section_id": null}
  ```
  Parse via `re.search(r'\{.*\}', raw, re.DOTALL)` then `json.loads`. Wrap in `try/except (json.JSONDecodeError, AttributeError, TypeError)` per ERR-01. On any parse failure → return `ExtractionResult(filters={}, semantic_query=query, fallback_source=None)` (AC#3 — never propagate exceptions).

### Fallback Source Semantics
- **D-11:** LLM is called ONLY when regex returns empty `filters` dict (AC#1 literal: "LLM only when regex returns None (no match)"). No merge of partial regex + LLM. `fallback_source` is single-valued:
  - regex produced filters → `fallback_source = "regex"`, LLM never called
  - regex empty AND LLM produced filters → `fallback_source = "llm"`
  - regex empty AND LLM empty/failed → `fallback_source = None`, `filters = {}`
- **D-12:** `semantic_query` semantics on LLM-hit path: LLM returns only filter values (no clean-query suggestion). `semantic_query = original query` when LLM hit — no token stripping (we don't know which tokens correspond to the filter without echoing the prompt). Acceptable for embedding (Chinese natural-language queries embed fine with filter words present).

### Failure Handling
- **D-13:** ERR-01 narrow exception tuple in LLM call: `(anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError)`. Plus `(json.JSONDecodeError, AttributeError, TypeError, ValueError)` for parse path. NO bare `Exception`.
- **D-14:** All failures → `ExtractionResult(filters={}, semantic_query=query, fallback_source=None)`. Logged at WARNING level. Never raises.

### Testing
- **D-15:** Mock the LLM client at `FilterExtractor._llm.chat`. Test contracts:
  1. Regex hit → LLM never called (AC#5 #1)
  2. Regex miss → LLM hit → correct ExtractionResult, `fallback_source="llm"` (AC#5 #2)
  3. Regex miss → LLM invalid JSON → ExtractionResult with empty filters, `fallback_source=None` (AC#5 #3)
  4. Regex miss → LLM API exception → graceful degradation, no propagation
  5. Cache hit → 2nd identical query within TTL → LLM called once (AC#5 #4)
  6. Cache disabled (settings.cache_enabled=False) → every miss hits LLM
  7. Integration: live query "关于第三章的内容" → LLM extracts section_id="3" (AC#5 #6)
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirement
- `.planning/REQUIREMENTS.md` §NLU-02 (lines 33–46) — Full acceptance criteria (5 ACs)
- `.planning/ROADMAP.md` §Phase 13 — Success criteria, depends-on

### Core Codebase
- `services/nlu/filter_extractor.py` — Existing regex extractor (function `extract_filters`, dataclass `FilterExtractionResult`). REFACTORED in Phase 13: function stays, new `FilterExtractor` class added.
- `services/pipeline.py` — 4 callsites at lines 317, 478, 674, 1166 (all migrate from `extract_filters(req.query)` to `await get_filter_extractor().extract(req.query)`).
- `services/generator/llm_client.py` — `chat(system, user, temperature, task_type)` interface; `task_type="nlu"` routes to Haiku.
- `utils/cache.py` — Redis cache helpers (verify `cache_get`/`cache_set` or equivalent; researcher confirms exact API).
- `config/settings.py` — `redis_url`, `cache_ttl_sec`, `cache_enabled` already present.

### Prior Phase Context
- v1.1 Phase 8 D-03: Regex patterns frozen (`第N页`, `N.M条款`, `N.M节`). Phase 13 does NOT touch the regex; LLM is purely additive on regex-miss.
- Phase 11 task routing: `task_type="nlu"` → Haiku (Anthropic) / `gpt-4o-mini` or equivalent (OpenAI). Phase 13 reuses verbatim.
- Phase 12 D-07: `asyncio.gather(return_exceptions=True)` and ERR-01 narrow exception tuple. Phase 13 reuses ERR-01 tuple in LLM call.
- Phase 12 D-08: Audit log via `self._audit.log(AuditEvent(...))` for non-standard fields. Phase 13 does NOT add new audit fields (filter extraction is pre-pipeline; existing audit captures it via `intent`/`query` fields).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `extract_filters(query) -> FilterExtractionResult` (current sync function at `filter_extractor.py:46`). Phase 13 KEEPS this and composes it inside `FilterExtractor.extract()`.
- `_PAGE_RE`, `_CLAUSE_RE`, `_SECTION_RE` (patterns at lines 28–30). FROZEN per v1.1 D-03.
- `BaseLLMClient.chat()` async method (`llm_client.py`). Already routes by `task_type`.
- `utils/cache.py` Redis helpers — `cache_get_json`, `cache_set_json` or similar (researcher confirms).
- Singleton factory pattern at end of `services/pipeline.py`: `get_query_pipeline()`, `get_agent_pipeline()`, `get_swarm_pipeline()`. Phase 13 adds `get_filter_extractor()` to `filter_extractor.py`.

### Established Patterns
- **OPS-01 config pattern:** `settings.cache_ttl_sec`, `settings.cache_enabled` are env-var-backed (`CACHE_TTL_SEC`, `CACHE_ENABLED`). No new settings needed.
- **ERR-01 narrow exceptions:** `(anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError)` for LLM call, `(json.JSONDecodeError, AttributeError, TypeError, ValueError)` for parse.
- **Haiku via task_type:** `task_type="nlu"` is the canonical NLU task type (Phase 11). Phase 13 reuses without invention.
- **Singleton via global + getter:** `_filter_extractor = None; def get_filter_extractor(): ...`.
- **Async LLM call inside sync-named module:** `services/nlu/nlu_service.py` (read for reference) and `services/extractor/ocr_engine.py` use the same async-method-on-class pattern.

### Integration Points
- `FilterExtractor` constructor calls `get_llm_client()` (lazy import to avoid circular dep, since llm_client doesn't import nlu).
- `FilterExtractor.extract()` checks `settings.cache_enabled` before Redis lookup. If disabled, every regex-miss hits the LLM.
- Pipeline callsites (4 sites) become `await get_filter_extractor().extract(req.query)`. The 2 sites that consume `semantic_query` access `.semantic_query` field. The 4 sites that consume `filters` dict access `.filters` field.
- No changes to vector_store.search() — filters dict shape unchanged (still `{"page_number": int, "section_id": str}`).
</code_context>

<specifics>
## Specific Ideas

### LLM Prompt Schema
```
SYSTEM: 你是查询过滤器提取助手。从用户查询中提取页码（page_number）和章节号（section_id）。

要求：
1. 仅返回 JSON 对象，格式如下，不包含任何其他文字：
   {"page_number": <整数或 null>, "section_id": "<字符串或 null>"}
2. page_number: 用户提到的具体页码（如"第三页"→3，"第10页"→10）。如未提及，返回 null。
3. section_id: 用户提到的章节号（如"第三章"→"3"，"3.2节"→"3.2"，"2.1.4条款"→"2.1.4"）。如未提及，返回 null。
4. 如果两者均未提及，返回 {"page_number": null, "section_id": null}。

示例：
输入：关于第三章的内容
输出：{"page_number": null, "section_id": "3"}

输入：第10页讲什么
输出：{"page_number": 10, "section_id": null}

输入：什么是企业RAG
输出：{"page_number": null, "section_id": null}
```

### Cache Key Function
```python
def _cache_key(query: str) -> str:
    return f"nlu:filter:{hashlib.sha256(query.encode('utf-8')).hexdigest()[:16]}"
```

### File Layout (final)
```
services/nlu/
├── filter_extractor.py     # Existing function `extract_filters` (KEEP); new `FilterExtractor` class; new `get_filter_extractor()` factory; new `ExtractionResult` dataclass; new `_FILTER_EXTRACT_SYSTEM` prompt
└── nlu_service.py          # Unchanged (different concern)

tests/unit/test_filter_extractor.py  # 6 unit test contracts (existing tests for regex still pass; new tests for LLM path)
tests/integration/test_filter_extractor_llm.py  # 1 integration test (live LLM)

services/pipeline.py        # 4-line patch: 4 callsites migrate to `await get_filter_extractor().extract(...)`
```
</specifics>

<deferred>
## Deferred Ideas

- English-language pattern support (page X, chapter Y) — frozen per v1.1 D-03; explicit non-goal for v1.3.
- Multi-filter merge (regex partial + LLM partial) — D-11 explicitly forbids; future-phase concern if real users need it.
- Cache invalidation on prompt changes — TTL-only is adequate; manual flush is operational concern.
- Streaming LLM responses for filter extraction — overkill (single small JSON response).
- LLM-based semantic_query rewriting — out of scope; embedding works on natural language.
</deferred>

---

*Phase: 13-LLM-Filter-Fallback*
*Context gathered: 2026-05-09*
