"""
tests/unit/test_filter_extractor.py

RED-state Wave 0 scaffold for QUERY-01 (REQ A-5 / Phase 8 SC #3).
Tests fail today; 08-02-PLAN.md (filter_extractor) makes them green.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")


class TestExtractFilters:
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
