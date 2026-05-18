# =============================================================================
# tests/integration/test_filter_extractor_llm.py
# Phase 13-03 Task 2 — End-to-end live LLM smoke for FilterExtractor (NLU-02 AC#5 #6).
#
# Excluded from default pytest run by pytest.ini `addopts = -m "not integration"`.
# Run explicitly:
#   pytest tests/integration/test_filter_extractor_llm.py -m integration
#
# Per CONTEXT.md D-05 (mirrors test_swarm_pipeline_e2e.py): the live OpenAI
# test runs UNCONDITIONALLY via the OneAPI gateway — missing OPENAI_API_KEY is a
# CONFIGURATION ERROR and surfaces as a hard test failure, NOT a `pytest.skip`.
# =============================================================================
"""End-to-end integration test for FilterExtractor LLM fallback (NLU-02)."""
from __future__ import annotations

import pytest

from services.nlu.filter_extractor import ExtractionResult, FilterExtractor

# Module-level marker: integration tier; real_llm tier (live external API call).
pytestmark = [pytest.mark.integration, pytest.mark.real_llm]


@pytest.mark.asyncio
async def test_filter_extractor_e2e_chinese_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live Chinese natural-language section query → LLM fallback → section_id extracted.

    Canary query: "关于第三章的内容". The frozen v1.1 regex (`第N章` is NOT in the
    pattern set — only `第N页` and `N.M节`/`N.M条款`) MUST miss this; the LLM
    fallback MUST recover `section_id`.

    Asserts:
      - result.fallback_source == "llm" (regex miss confirmed, LLM hit confirmed)
      - result.filters["section_id"] in {"3", 3} (Haiku type drift tolerance per
        13-RESEARCH.md Assumptions Log A2)
    """
    # Force OpenAI provider (project default; assert explicitly to mirror analog).
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    # Reset both singletons so the env override takes effect against a fresh client.
    import services.generator.llm_client as llm_mod
    import services.nlu.filter_extractor as fx_mod
    llm_mod._llm_instance = None
    fx_mod._filter_extractor = None

    extractor = FilterExtractor()

    result: ExtractionResult = await extractor.extract("关于第三章的内容")

    assert isinstance(result, ExtractionResult)
    assert result.fallback_source == "llm", (
        f"expected fallback_source='llm' (regex misses on this query); "
        f"got {result.fallback_source!r}; full result={result!r}"
    )
    section = result.filters.get("section_id")
    assert section in {"3", 3}, (
        f"expected section_id in {{'3', 3}} (tolerating Haiku string-vs-int drift "
        f"per A2); got {section!r}; full filters={result.filters!r}"
    )

    # Diagnostic log (non-asserting) — visible under `pytest -s`.
    print(
        f"[filter-e2e] query='关于第三章的内容' "
        f"filters={result.filters!r} "
        f"fallback_source={result.fallback_source!r} "
        f"semantic_query={result.semantic_query!r}"
    )
