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


__all__ = [
    "ExtractionResult",
    "FilterExtractionResult",
    "FilterExtractor",
    "extract_filters",
    "get_filter_extractor",
]
