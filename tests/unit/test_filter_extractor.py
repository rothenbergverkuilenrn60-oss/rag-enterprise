"""
tests/unit/test_filter_extractor.py

RED-state Wave 0 scaffold for QUERY-01 (REQ A-5 / Phase 8 SC #3).
Tests fail today; 08-02-PLAN.md (filter_extractor) makes them green.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


@pytest.fixture(autouse=True)
def reset_filter_extractor_singleton(monkeypatch):
    """Reset module-level _filter_extractor singleton after every test (Pitfall 7).

    Mirrors tests/unit/test_nlu_service.py:17-23 autouse pattern. Without this,
    a singleton created by get_filter_extractor() in one test leaks its mocked
    _llm into subsequent tests.
    """
    import services.nlu.filter_extractor as mod
    yield
    monkeypatch.setattr(mod, "_filter_extractor", None, raising=False)


class TestExtractFiltersRegex:
    """Regex-only extraction tests (preserved from v1.1 Phase 8 — D-02 freeze).

    These exercise the sync `extract_filters` function. The new `FilterExtractor`
    class composes `extract_filters` as its first branch (D-11), so these tests
    also implicitly verify the regex-first composition's deterministic path.
    """

    def test_page_extraction(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("第63页灯具的发光面")
        assert result.filters == {"page_number": 63}
        assert result.semantic_query.strip() == "灯具的发光面"

    def test_page_with_whitespace(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("第 63 页灯具的发光面")
        assert result.filters == {"page_number": 63}

    def test_section_clause_extraction(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("3.10条款中规定的内容")
        assert result.filters == {"section_id": "3.10"}
        assert "3.10" not in result.semantic_query

    def test_section_generic_extraction(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("3.10节中的内容")
        assert result.filters == {"section_id": "3.10"}
        assert "3.10" not in result.semantic_query

    def test_no_filter_passthrough(self):
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("灯具的发光面")
        assert result.filters == {}
        assert result.semantic_query == "灯具的发光面"

    def test_empty_after_strip_keeps_original(self):
        # Guard: stripping leaves empty → fallback to original (research Open Question #2)
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("3.10节")
        assert result.filters == {"section_id": "3.10"}
        assert result.semantic_query  # non-empty

    def test_filter_value_types_are_safe(self):
        # T-08-01 mitigation: page_number is int, section_id is str — never raw user text
        from services.nlu.filter_extractor import extract_filters
        result = extract_filters("第63页 SELECT * FROM x")
        assert result.filters["page_number"] == 63
        assert isinstance(result.filters["page_number"], int)
        # SQL fragments live in the semantic_query (will be embedded), never in filters
        assert "SELECT" in result.semantic_query


@pytest.fixture
def mock_extractor():
    """Build a FilterExtractor without invoking get_llm_client (Phase 12 __new__ bypass).

    Mirrors tests/unit/test_swarm_pipeline.py:74-99. _llm.chat is an AsyncMock —
    per-test bodies override return_value or side_effect.
    """
    from services.nlu.filter_extractor import FilterExtractor
    inst = FilterExtractor.__new__(FilterExtractor)
    inst._llm = MagicMock()
    inst._llm.chat = AsyncMock()
    return inst


class TestFilterExtractor:
    """Async LLM-fallback path (NLU-02 D-15 contracts 1-6)."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_regex_hit_skips_llm(self, mock_extractor):
        """D-15 #1 / AC#5 #1: regex match → LLM never called; fallback_source='regex'."""
        result = await mock_extractor.extract("第3页的内容")
        assert result.filters == {"page_number": 3}
        assert result.fallback_source == "regex"
        mock_extractor._llm.chat.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_regex_miss_llm_hit(self, mock_extractor, monkeypatch):
        """D-15 #2 / AC#5 #2: regex miss → LLM extracts section_id; fallback_source='llm'."""
        monkeypatch.setattr(
            "services.nlu.filter_extractor.cache_get",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "services.nlu.filter_extractor.cache_set",
            AsyncMock(return_value=True),
        )
        mock_extractor._llm.chat = AsyncMock(
            return_value='{"page_number": null, "section_id": "3"}'
        )
        result = await mock_extractor.extract("关于第三章的内容")
        assert result.filters == {"section_id": "3"}
        assert result.fallback_source == "llm"
        assert result.semantic_query == "关于第三章的内容"  # D-12: original query, no stripping
        mock_extractor._llm.chat.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty(self, mock_extractor, monkeypatch):
        """D-15 #3 / AC#5 #3: parse failure → empty result; no propagation; fallback_source=None."""
        monkeypatch.setattr(
            "services.nlu.filter_extractor.cache_get",
            AsyncMock(return_value=None),
        )
        cache_set_mock = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "services.nlu.filter_extractor.cache_set",
            cache_set_mock,
        )
        mock_extractor._llm.chat = AsyncMock(return_value="not json at all")
        result = await mock_extractor.extract("关于第三章的内容")
        assert result.filters == {}
        assert result.fallback_source is None
        assert result.semantic_query == "关于第三章的内容"
        # Pitfall 1: empty/failed results MUST NOT be cached
        cache_set_mock.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_llm_api_exception_returns_empty(self, mock_extractor, monkeypatch):
        """D-15 #4 / AC#3: LLM raises httpx.HTTPError → graceful degradation, no propagation."""
        monkeypatch.setattr(
            "services.nlu.filter_extractor.cache_get",
            AsyncMock(return_value=None),
        )
        mock_extractor._llm.chat = AsyncMock(side_effect=httpx.HTTPError("boom"))
        # Must NOT raise — D-14 contract.
        result = await mock_extractor.extract("关于第三章的内容")
        assert result.filters == {}
        assert result.fallback_source is None
        mock_extractor._llm.chat.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_hit_skips_llm(self, mock_extractor, monkeypatch):
        """D-15 #5 / AC#5 #4: 2 identical queries within TTL → LLM called once.

        Simulates first-call cache miss + cache_set, then second-call cache hit:
        we use a stateful cache_get that returns None on first call and the
        previously-written dict on second call.
        """
        cache_state = {"value": None}

        async def stateful_cache_get(namespace, payload):
            return cache_state["value"]

        async def stateful_cache_set(namespace, payload, value):
            cache_state["value"] = value
            return True

        monkeypatch.setattr(
            "services.nlu.filter_extractor.cache_get",
            stateful_cache_get,
        )
        monkeypatch.setattr(
            "services.nlu.filter_extractor.cache_set",
            stateful_cache_set,
        )
        mock_extractor._llm.chat = AsyncMock(
            return_value='{"page_number": null, "section_id": "3"}'
        )

        r1 = await mock_extractor.extract("关于第三章的内容")
        r2 = await mock_extractor.extract("关于第三章的内容")

        assert r1.filters == {"section_id": "3"}
        assert r2.filters == {"section_id": "3"}
        assert r1.fallback_source == "llm"
        assert r2.fallback_source == "llm"
        # AC#5 #4 contract: LLM called exactly once across both invocations
        assert mock_extractor._llm.chat.await_count == 1, (
            f"expected 1 LLM call across 2 identical queries; "
            f"got {mock_extractor._llm.chat.await_count}"
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cache_disabled_every_miss_hits_llm(self, mock_extractor, monkeypatch):
        """D-15 #6 / AC#5 cache control: cache_get always returns None
        (simulates settings.cache_enabled=False short-circuit at utils/cache.py:65-66)
        → every regex-miss invocation hits the LLM.
        """
        monkeypatch.setattr(
            "services.nlu.filter_extractor.cache_get",
            AsyncMock(return_value=None),
        )
        # cache_set returns False under cache_enabled=False — but FilterExtractor
        # ignores the return value and only conditions write on `if filters:`.
        monkeypatch.setattr(
            "services.nlu.filter_extractor.cache_set",
            AsyncMock(return_value=False),
        )
        mock_extractor._llm.chat = AsyncMock(
            return_value='{"page_number": null, "section_id": "3"}'
        )

        await mock_extractor.extract("关于第三章的内容")
        await mock_extractor.extract("关于第三章的内容")

        assert mock_extractor._llm.chat.await_count == 2, (
            f"expected 2 LLM calls when cache disabled; "
            f"got {mock_extractor._llm.chat.await_count}"
        )
