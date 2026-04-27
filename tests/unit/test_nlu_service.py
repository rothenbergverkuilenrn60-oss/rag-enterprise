"""
tests/unit/test_nlu_service.py
Unit tests for NLU rule-based intent classification and entity extraction.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture(autouse=True)
def reset_nlu_singleton(monkeypatch):
    import services.nlu.nlu_service as mod
    yield
    for attr in ("_nlu_service", "_service"):
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, None, raising=False)


class TestNLURuleBased:
    def test_rule_based_intent_chitchat(self):
        from services.nlu.nlu_service import _rule_based_intent, QueryIntent

        result = _rule_based_intent("你好")
        assert result == QueryIntent.CHITCHAT

    def test_rule_based_intent_procedural(self):
        from services.nlu.nlu_service import _rule_based_intent, QueryIntent

        result = _rule_based_intent("怎么申请年假")
        assert result == QueryIntent.PROCEDURAL

    def test_extract_entities_number(self):
        from services.nlu.nlu_service import _extract_entities_rule

        entities = _extract_entities_rule("请假3天")
        entity_types = [e.entity_type for e in entities]
        assert "number" in entity_types

    def test_rule_based_intent_unknown_falls_back(self):
        # NOTE: _rule_based_intent returns None when no rule matches (not a default intent).
        # This is the contract defined in the source: return None for unknown.
        from services.nlu.nlu_service import _rule_based_intent

        result = _rule_based_intent("xyzzy nonsense that matches no rule")
        assert result is None

    async def test_analyze_with_llm_fallback(self, monkeypatch):
        from services.nlu.nlu_service import NLUService, QueryIntent

        svc = NLUService()

        # Monkeypatch NLUService._llm_analyze which is the actual LLM call site
        mock_llm_analyze = AsyncMock(return_value={
            "intent": "factual",
            "entities": [],
            "sub_queries": [],
            "needs_clarification": False,
            "clarification_hint": "",
            "rewrite": [],
        })
        monkeypatch.setattr(svc, "_llm_analyze", mock_llm_analyze)

        # Also patch build_quad_queries to avoid real LLM calls for rewriting
        import services.nlu.nlu_service as mod
        monkeypatch.setattr(
            mod, "build_quad_queries",
            AsyncMock(return_value={"original": ["query"], "rewrite": [], "hyde": [], "context": []})
        )

        mock_llm_client = MagicMock()
        mock_llm_client.supports_tools = False
        # NLU analyze will call _llm_analyze when rule_intent is None and llm_client provided
        result = await svc.analyze(
            query="xyzzy nonsense that matches no rule",
            llm_client=mock_llm_client,
        )
        mock_llm_analyze.assert_awaited_once()
        assert result.intent == QueryIntent.FACTUAL

    def test_rule_based_intent_comparison(self):
        from services.nlu.nlu_service import _rule_based_intent, QueryIntent

        result = _rule_based_intent("年假和病假有什么区别")
        assert result == QueryIntent.COMPARISON

    def test_extract_entities_policy_term(self):
        from services.nlu.nlu_service import _extract_entities_rule

        entities = _extract_entities_rule("申请产假需要多少天")
        entity_types = [e.entity_type for e in entities]
        assert "policy_term" in entity_types
