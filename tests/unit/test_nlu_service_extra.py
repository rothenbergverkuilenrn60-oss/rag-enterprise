"""tests/unit/test_nlu_service_extra.py — Phase 15 backfill.

Existing tests/unit/test_nlu_service.py covers rule-based intent + a basic
LLM fallback. This file adds: _llm_rewrite (tool-use + fallback + error path),
_llm_hyde, build_quad_queries, NLUService._llm_analyze (tool-use + fallback +
JSON-missing error), recommend_top_k, _summarize_context, and the singleton.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import openai
import pytest


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.nlu.nlu_service as mod
    yield
    monkeypatch.setattr(mod, "_nlu_service", None, raising=False)


# ── _llm_rewrite ────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_rewrite_tool_use_returns_variants():
    from services.nlu.nlu_service import _llm_rewrite
    llm = MagicMock()
    llm.supports_tools = True
    llm.chat_with_tools = AsyncMock(return_value={"variants": ["v1", "v2", "v3", "v4"]})
    out = await _llm_rewrite("query", llm, n=3)
    assert out == ["v1", "v2", "v3"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_rewrite_fallback_text_path():
    from services.nlu.nlu_service import _llm_rewrite
    llm = MagicMock()
    llm.supports_tools = False
    llm.chat = AsyncMock(return_value="line1\nline2\n\nline3")
    out = await _llm_rewrite("query", llm, n=2)
    assert out == ["line1", "line2"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_rewrite_handles_api_error():
    """Error path: openai.APIError → returns []."""
    from services.nlu.nlu_service import _llm_rewrite
    llm = MagicMock()
    llm.supports_tools = True
    llm.chat_with_tools = AsyncMock(side_effect=openai.APIError("boom", request=None, body={}))
    out = await _llm_rewrite("query", llm)
    assert out == []


# ── _llm_hyde ──────────────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_hyde_returns_doc():
    from services.nlu.nlu_service import _llm_hyde
    llm = MagicMock()
    llm.chat = AsyncMock(return_value="hypothetical document")
    out = await _llm_hyde("query", llm)
    assert out == "hypothetical document"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_hyde_falls_back_to_query_on_error():
    """Error path: APIError → returns original query."""
    from services.nlu.nlu_service import _llm_hyde
    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=openai.APIError("boom", request=None, body={}))
    out = await _llm_hyde("query", llm)
    assert out == "query"


# ── build_quad_queries ──────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_quad_queries_no_history():
    from services.nlu.nlu_service import build_quad_queries
    llm = MagicMock()
    llm.supports_tools = False
    llm.chat = AsyncMock(side_effect=["v1\nv2", "hyde-doc"])
    out = await build_quad_queries("q", llm)
    assert out["original"] == ["q"]
    assert out["rewrite"] == ["v1", "v2"]
    assert out["hyde"] == ["hyde-doc"]
    assert out["context"] == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_build_quad_queries_with_history():
    from services.nlu.nlu_service import build_quad_queries
    llm = MagicMock()
    llm.supports_tools = False
    llm.chat = AsyncMock(side_effect=["v1", "hyde", "context-rewrite"])
    history = [{"role": "user", "content": "prev"}, {"role": "assistant", "content": "ans"}]
    out = await build_quad_queries("q", llm, chat_history=history)
    assert out["context"] == ["context-rewrite"]


# ── NLUService._llm_analyze ────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_analyze_tool_use_returns_dict():
    from services.nlu.nlu_service import NLUService
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    llm = MagicMock()
    llm.supports_tools = True
    llm.chat_with_tools = AsyncMock(return_value={"intent": "factual", "entities": []})
    out = await svc._llm_analyze("query", "", llm)
    assert out["intent"] == "factual"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_analyze_fallback_parses_json_response():
    from services.nlu.nlu_service import NLUService
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    llm = MagicMock()
    llm.supports_tools = False
    llm.chat = AsyncMock(return_value='Here is the analysis: {"intent": "comparison"}')
    out = await svc._llm_analyze("query", "ctx", llm)
    assert out["intent"] == "comparison"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_analyze_fallback_missing_json_raises_after_retry():
    """Error path: no JSON in response → ValueError → tenacity retries → RetryError."""
    from tenacity import RetryError

    from services.nlu.nlu_service import NLUService
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    llm = MagicMock()
    llm.supports_tools = False
    llm.chat = AsyncMock(return_value="No JSON here at all")
    with pytest.raises(RetryError):
        await svc._llm_analyze("query", "", llm)


# ── recommend_top_k ────────────────────────────────────────────────────────

@pytest.mark.unit
def test_recommend_top_k_disabled_returns_default(monkeypatch):
    from services.nlu.nlu_service import NLUService, QueryIntent, settings
    monkeypatch.setattr(settings, "dynamic_top_k_enabled", False, raising=False)
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    out = svc.recommend_top_k(QueryIntent.MULTI_HOP, default=42)
    assert out == 42


@pytest.mark.unit
def test_recommend_top_k_uses_intent_mapping(monkeypatch):
    from services.nlu.nlu_service import NLUService, QueryIntent, settings
    monkeypatch.setattr(settings, "dynamic_top_k_enabled", True, raising=False)
    monkeypatch.setattr(settings, "top_k_factual", 3, raising=False)
    monkeypatch.setattr(settings, "top_k_multi_hop", 12, raising=False)
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    assert svc.recommend_top_k(QueryIntent.FACTUAL, default=99) == 3
    assert svc.recommend_top_k(QueryIntent.MULTI_HOP, default=99) == 12


@pytest.mark.unit
def test_recommend_top_k_unmapped_intent_returns_default(monkeypatch):
    from services.nlu.nlu_service import NLUService, QueryIntent, settings
    monkeypatch.setattr(settings, "dynamic_top_k_enabled", True, raising=False)
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    assert svc.recommend_top_k(QueryIntent.AMBIGUOUS, default=7) == 7


# ── _summarize_context ─────────────────────────────────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_context_too_short_returns_empty():
    from services.nlu.nlu_service import NLUService
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    out = await svc._summarize_context([{"role": "user", "content": "hi"}], MagicMock())
    assert out == ""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_context_returns_llm_summary():
    from services.nlu.nlu_service import NLUService
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    llm = MagicMock()
    llm.chat = AsyncMock(return_value="用户正在询问年假，已了解工龄")
    history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    out = await svc._summarize_context(history, llm)
    assert "年假" in out


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_context_handles_api_error():
    """Error path: APIError → empty string, no propagation."""
    from services.nlu.nlu_service import NLUService
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=openai.APIError("boom", request=None, body={}))
    history = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    out = await svc._summarize_context(history, llm)
    assert out == ""


# ── singleton ──────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_get_nlu_service_singleton():
    from services.nlu.nlu_service import get_nlu_service
    a = get_nlu_service()
    b = get_nlu_service()
    assert a is b


# ── analyze() smoke (covers chitchat short-circuit) ─────────────────────────

@pytest.mark.unit
@pytest.mark.asyncio
async def test_analyze_chitchat_short_circuits():
    from services.nlu.nlu_service import NLUService, QueryIntent
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = True
    out = await svc.analyze("你好")
    assert out.intent == QueryIntent.CHITCHAT
    assert out.rewritten_queries == ["你好"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_analyze_factual_with_llm_disabled():
    """LLM disabled → falls back to rule intent without calling LLM."""
    from services.nlu.nlu_service import NLUService, QueryIntent
    svc = NLUService.__new__(NLUService)
    svc._use_llm_nlu = False
    out = await svc.analyze("产假多少天")
    assert out.intent == QueryIntent.FACTUAL
