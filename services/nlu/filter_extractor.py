"""
services/nlu/filter_extractor.py

Regex-first query filter extraction (Chinese-only, v1.1) — REQ A-5 / QUERY-01.

Lifts page/section number tokens out of a user query into a structured metadata
filter so downstream vector_store.search() can apply a JSONB-filtered HNSW search.

Pattern priority (LOCKED by CONTEXT.md D-03):
    1. 第N页              → filters["page_number"] = int(N)
    2. N.M条款            → filters["section_id"]  = "N.M"  (clause variant)
    3. N.M节  or  N.M     → filters["section_id"]  = "N.M"  (generic)

Extracted tokens are stripped from `semantic_query` so the embedded text does
not carry numeric noise. If stripping leaves an empty string, the original
query is preserved as `semantic_query` (still applying the filter — guard
against zero-vector embedding).

LLM-based extractor is explicitly OUT OF SCOPE for v1.1 (REQ A-5 acceptance #5).
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Literal

import anthropic
import httpx
import openai
from loguru import logger

from utils.cache import cache_get, cache_set

# Frozen patterns — D-03 in CONTEXT.md. DO NOT extend with English patterns
# (deferred to v1.2). DO NOT relax to optional 节/页 — separation must be explicit.
_PAGE_RE    = re.compile(r"第\s*(\d+)\s*页")
_CLAUSE_RE  = re.compile(r"(\d+(?:\.\d+)+)条款")
_SECTION_RE = re.compile(r"(\d+(?:\.\d+)+)\s*节?")


_FILTER_EXTRACT_SYSTEM: str = """\
你是查询过滤器提取助手。从用户查询中提取页码（page_number）和章节号（section_id）。

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
"""


@dataclass
class FilterExtractionResult:
    """Result of regex-first filter extraction.

    `filters` carries typed values (page_number: int, section_id: str) ready
    for vector_store.search(filters=…). `semantic_query` is the user query
    with filter tokens removed; falls back to the original query if stripping
    produced an empty string.
    """
    filters:        dict[str, int | str] = field(default_factory=dict)
    semantic_query: str                  = ""


@dataclass(frozen=True)
class ExtractionResult:
    """Wrapper exposing fallback_source for regex-vs-LLM tracing (NLU-02 AC#4).

    Returned from `FilterExtractor.extract()`. The `filters` and `semantic_query`
    fields mirror `FilterExtractionResult` for callsite backward compatibility
    (truthiness on `.filters` works unchanged at all 4 pipeline callsites — D-04).
    `fallback_source` distinguishes regex hits from LLM-fallback hits and from
    no-match results.
    """
    filters:         dict[str, int | str]
    semantic_query:  str
    fallback_source: Literal["regex", "llm"] | None = None


def extract_filters(query: str) -> FilterExtractionResult:
    """Extract page_number / section_id filters from a Chinese user query.

    Priority order: page > clause-section > generic-section. Each pattern is
    matched at most once (count=1 in re.sub) so a query like "第63页 第64页…"
    extracts only the first page reference; later occurrences remain in the
    semantic query and become embedding tokens.

    Args:
        query: The raw user query string (Chinese, v1.1 corpus).

    Returns:
        FilterExtractionResult with typed `filters` and stripped `semantic_query`.
        On empty-after-strip, `semantic_query == query` (safe fallback).
    """
    filters: dict[str, int | str] = {}
    stripped = query

    # 1. 第N页 — highest priority
    m = _PAGE_RE.search(stripped)
    if m:
        filters["page_number"] = int(m.group(1))
        stripped = _PAGE_RE.sub("", stripped, count=1).strip()

    # 2. N.M条款 — clause variant (matched before generic to avoid eating "条款" suffix)
    m = _CLAUSE_RE.search(stripped)
    if m:
        filters["section_id"] = m.group(1)
        stripped = _CLAUSE_RE.sub("", stripped, count=1).strip()
    else:
        # 3. N.M节 or bare N.M — generic
        m = _SECTION_RE.search(stripped)
        if m:
            filters["section_id"] = m.group(1)
            stripped = _SECTION_RE.sub("", stripped, count=1).strip()

    # Guard: if the strip left no embeddable text, keep the original query so
    # the embedder does not receive an empty string (which would yield a
    # zero-or-noise vector). Filter still applies.
    if not stripped:
        stripped = query

    return FilterExtractionResult(filters=filters, semantic_query=stripped)


class FilterExtractor:
    """Async filter extractor with regex-first composition and LLM fallback (NLU-02).

    Flow:
      1. Run sync ``extract_filters(query)`` (frozen v1.1 regex patterns).
         If filters non-empty → return immediately (``fallback_source='regex'``); LLM never called (D-11).
      2. Empty regex result → ``cache_get('nlu:filter', query)`` lookup.
         Cache hit → restore cached ExtractionResult (``fallback_source='llm'``); LLM not called (D-06).
      3. Cache miss → Haiku call via ``self._llm.chat(..., task_type='nlu')`` (D-09).
         Wrapped in narrow ERR-01 tuple (anthropic.APIError, openai.APIError,
         httpx.HTTPError, asyncio.TimeoutError); on raise → empty result, no propagation (D-13, D-14).
      4. ``re.search(r'\\{.*\\}', raw, re.DOTALL)`` + ``json.loads`` + type coercion.
         Wrapped in narrow ERR-01 tuple (json.JSONDecodeError, AttributeError,
         TypeError, ValueError); on raise → empty result (D-13, D-14).
      5. Build filters dict (only non-null, type-validated entries).
      6. Successful non-empty filters → ``cache_set('nlu:filter', query, {filters, semantic_query})`` (Pitfall 1: never cache empty/failed).
      7. Return ExtractionResult with ``fallback_source='llm'`` if filters non-empty, else ``fallback_source=None``.

    Mirrors the singleton + ``__init__`` pattern of pipeline classes
    (services/pipeline.py:890-910). Tests use ``FilterExtractor.__new__(FilterExtractor)``
    to bypass ``__init__`` and attach a mock ``_llm`` (Phase 12 fixture pattern).
    """

    def __init__(self) -> None:
        # Lazy import to avoid circular dependency: llm_client does not import services.nlu.
        from services.generator.llm_client import get_llm_client
        self._llm = get_llm_client()

    async def extract(self, query: str) -> ExtractionResult:
        # 1. Regex-first (D-11) — zero-cost when patterns match
        regex_result = extract_filters(query)
        if regex_result.filters:
            return ExtractionResult(
                filters=regex_result.filters,
                semantic_query=regex_result.semantic_query,
                fallback_source="regex",
            )

        # 2. Cache lookup — utils/cache.py handles MD5 keying, JSON, cache_enabled short-circuit
        cached = await cache_get("nlu:filter", query)
        if cached is not None and isinstance(cached, dict) and "filters" in cached:
            return ExtractionResult(
                filters=cached["filters"],
                semantic_query=cached.get("semantic_query", query),
                fallback_source="llm",
            )

        # 3. LLM call — narrow ERR-01 tuple #1 (D-13)
        try:
            raw: str = await self._llm.chat(
                system=_FILTER_EXTRACT_SYSTEM,
                user=query,
                temperature=0.0,
                task_type="nlu",   # → Haiku (llm_client.py:100)
            )
        except (anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError) as exc:
            logger.warning(f"[FilterExtractor] LLM call failed: {exc!r}; falling back to no-filter")
            return ExtractionResult(filters={}, semantic_query=query, fallback_source=None)

        # 4. Parse + type coerce — narrow ERR-01 tuple #2 (D-13)
        try:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            parsed = json.loads(m.group(0))   # type: ignore[union-attr]  # AttributeError if m is None — caught below (D-13)
            if not isinstance(parsed, dict):
                raise TypeError(f"expected dict, got {type(parsed).__name__}")

            # 5. Build filters dict — only non-null, type-validated entries (Pitfall 2)
            filters: dict[str, int | str] = {}
            page = parsed.get("page_number")
            if page is not None:
                filters["page_number"] = int(page)   # ValueError on non-numeric string
            section = parsed.get("section_id")
            if isinstance(section, str) and section:
                filters["section_id"] = section
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            logger.warning(f"[FilterExtractor] JSON parse failed: {exc!r}; raw={raw[:200]!r}")
            return ExtractionResult(filters={}, semantic_query=query, fallback_source=None)

        # 6. Cache successful non-empty result (Pitfall 1)
        if filters:
            await cache_set("nlu:filter", query, {
                "filters": filters,
                "semantic_query": query,
            })

        # 7. Build result — fallback_source='llm' iff filters non-empty (D-11, D-12)
        return ExtractionResult(
            filters=filters,
            semantic_query=query,
            fallback_source="llm" if filters else None,
        )


_filter_extractor: FilterExtractor | None = None


def get_filter_extractor() -> FilterExtractor:
    """Return the module-level FilterExtractor singleton (lazy-init on first call).

    Mirrors get_query_pipeline / get_agent_pipeline / get_swarm_pipeline at
    services/pipeline.py:890-910, 1259-1264. Tests reset by setting
    services.nlu.filter_extractor._filter_extractor = None (mirrors
    tests/unit/test_nlu_service.py:17-23 autouse fixture pattern).
    """
    global _filter_extractor
    if _filter_extractor is None:
        _filter_extractor = FilterExtractor()
    return _filter_extractor


__all__ = [
    "ExtractionResult",
    "FilterExtractionResult",
    "FilterExtractor",
    "extract_filters",
    "get_filter_extractor",
]
