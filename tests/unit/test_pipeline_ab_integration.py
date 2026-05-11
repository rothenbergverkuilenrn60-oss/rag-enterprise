"""
tests/unit/test_pipeline_ab_integration.py

Verifies QueryPipeline._run_query wiring to ABTestService:
  1. assign_variant called with session_id + tenant_id
  2. record_result called with experiment_id, variant_id, latency, faithfulness when variant assigned
  3. record_result NOT called when no running experiment (assign_variant returns None)
  4. assign_variant ConnectionError is swallowed (non-fatal — query still completes)
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


def _setup_query_mocks(monkeypatch: pytest.MonkeyPatch, ab_assign_return, ab_assign_raises=None):
    """Patch QueryPipeline collaborators. Return the ABTestService mock."""
    import services.pipeline as pm

    ab = MagicMock()
    if ab_assign_raises is not None:
        ab.assign_variant = AsyncMock(side_effect=ab_assign_raises)
    else:
        ab.assign_variant = AsyncMock(return_value=ab_assign_return)
    ab.record_result = AsyncMock()
    monkeypatch.setattr(pm, "get_ab_test_service", lambda: ab)

    tenant_svc = MagicMock()
    tenant_svc.check_permission = MagicMock(return_value=True)
    tenant_svc.get_tenant_filter = MagicMock(return_value={})
    monkeypatch.setattr(pm, "get_tenant_service", lambda: tenant_svc)

    audit = AsyncMock()
    monkeypatch.setattr(pm, "get_audit_service", lambda: audit)

    rules = MagicMock()
    rule_result = MagicMock()
    rule_result.action = "OTHER"
    rule_result.message = ""
    rules.run = MagicMock(return_value=rule_result)
    monkeypatch.setattr(pm, "get_rules_engine", lambda: rules)

    memory = MagicMock()
    mem_ctx = MagicMock()
    mem_ctx.short_term = []
    mem_ctx.long_term_facts = []
    mem_ctx.user_profile = None
    memory.load_context = AsyncMock(return_value=mem_ctx)
    memory.save_turn = AsyncMock()
    monkeypatch.setattr(pm, "get_memory_service", lambda: memory)

    extractor = MagicMock()
    extraction = MagicMock()
    extraction.semantic_query = "q"
    extraction.filters = {}
    extractor.extract = AsyncMock(return_value=extraction)
    monkeypatch.setattr(pm, "get_filter_extractor", lambda: extractor)

    nlu = MagicMock()
    nlu_result = MagicMock()
    nlu_result.intent = "general"
    nlu_result.needs_clarification = False
    nlu_result.entities = []
    nlu_result.rewritten_queries = ["q"]
    nlu.analyze = AsyncMock(return_value=nlu_result)
    nlu.recommend_top_k = MagicMock(return_value=6)
    monkeypatch.setattr(pm, "get_nlu_service", lambda: nlu)

    llm = MagicMock()
    monkeypatch.setattr(pm, "get_llm_client", lambda: llm)

    retriever = MagicMock()
    retriever.embedder = MagicMock()
    retriever.vector_store = MagicMock()
    retriever.retrieve_multi_query = AsyncMock(return_value=([], {}))
    monkeypatch.setattr(pm, "get_retriever", lambda: retriever)

    response = MagicMock()
    response.answer = "ans"
    response.sources = []
    response.faithfulness_score = 0.85
    response.stage_latencies = {}
    response.latency_ms = 0
    response.trace_id = ""
    generator = MagicMock()
    generator.generate = AsyncMock(return_value=response)
    monkeypatch.setattr(pm, "get_generator", lambda: generator)

    summary_indexer = MagicMock()
    summary_indexer.search_summaries = AsyncMock(return_value=[])
    monkeypatch.setattr(pm, "get_summary_indexer", lambda: summary_indexer)

    event_bus = AsyncMock()
    monkeypatch.setattr(pm, "get_event_bus", lambda: event_bus)

    counter = MagicMock()
    counter.labels.return_value = counter
    for name in ("query_total", "query_latency_seconds", "faithfulness_histogram",
                 "retrieval_chunks_histogram", "rule_trigger_total", "cache_hit_total"):
        monkeypatch.setattr(pm, name, counter)

    monkeypatch.setattr(pm, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(pm, "cache_set", AsyncMock())

    # session→variant Redis mapping (used after assign_variant succeeds)
    fake_redis = MagicMock()
    fake_redis.set = AsyncMock()
    fake_redis.get = AsyncMock(return_value=None)
    import utils.cache as cache_mod
    monkeypatch.setattr(cache_mod, "get_redis", AsyncMock(return_value=fake_redis))
    ab.fake_redis = fake_redis

    return ab


def _make_req():
    from utils.models import GenerationRequest
    return GenerationRequest(
        query="hello",
        session_id="sess-1",
        user_id="u1",
        tenant_id="t1",
        top_k=5,
        filters={},
    )


@pytest.mark.asyncio
async def test_assign_variant_called_with_session_and_tenant(monkeypatch):
    ab = _setup_query_mocks(monkeypatch, ab_assign_return=(None, None, {}))
    from services.pipeline import QueryPipeline
    await QueryPipeline()._run_query(_make_req())
    ab.assign_variant.assert_awaited_once_with(session_id="sess-1", tenant_id="t1")


@pytest.mark.asyncio
async def test_record_result_called_when_variant_assigned(monkeypatch):
    ab = _setup_query_mocks(
        monkeypatch,
        ab_assign_return=("exp-x", "A", {"top_k_rerank": 6}),
    )
    from services.pipeline import QueryPipeline
    await QueryPipeline()._run_query(_make_req())

    ab.record_result.assert_awaited_once()
    call_args = ab.record_result.await_args
    result = call_args.args[0]
    assert result.experiment_id == "exp-x"
    assert result.variant_id == "A"
    assert result.session_id == "sess-1"
    assert result.tenant_id == "t1"
    assert result.faithfulness == 0.85
    assert result.latency_ms > 0


@pytest.mark.asyncio
async def test_record_result_NOT_called_when_no_running_experiment(monkeypatch):
    ab = _setup_query_mocks(monkeypatch, ab_assign_return=(None, None, {}))
    from services.pipeline import QueryPipeline
    await QueryPipeline()._run_query(_make_req())
    ab.record_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_variant_mapping_stored_in_redis(monkeypatch):
    """When variant assigned, pipeline stores session→variant mapping in Redis with TTL."""
    ab = _setup_query_mocks(
        monkeypatch,
        ab_assign_return=("exp-x", "B", {}),
    )
    from services.pipeline import QueryPipeline
    await QueryPipeline()._run_query(_make_req())

    # 现在 pipeline 调 set 两次: ab:session 映射 + last_qa 快照
    assert ab.fake_redis.set.await_count >= 1
    ab_call = next(
        c for c in ab.fake_redis.set.await_args_list
        if c.args[0].startswith("ab:session:")
    )
    assert ab_call.args[0] == "ab:session:sess-1"
    assert '"experiment_id": "exp-x"' in ab_call.args[1]
    assert '"variant_id": "B"' in ab_call.args[1]
    assert ab_call.kwargs.get("ex") == 3600


@pytest.mark.asyncio
async def test_session_mapping_NOT_stored_when_no_variant(monkeypatch):
    """No running experiment → no ab:session mapping write (last_qa snapshot may still write)."""
    ab = _setup_query_mocks(monkeypatch, ab_assign_return=(None, None, {}))
    from services.pipeline import QueryPipeline
    await QueryPipeline()._run_query(_make_req())
    ab_writes = [
        c for c in ab.fake_redis.set.await_args_list
        if c.args[0].startswith("ab:session:")
    ]
    assert ab_writes == []


@pytest.mark.asyncio
async def test_last_qa_snapshot_stored_in_redis(monkeypatch):
    """After successful query, last_qa:{session_id} written for /feedback forward."""
    ab = _setup_query_mocks(monkeypatch, ab_assign_return=(None, None, {}))
    from services.pipeline import QueryPipeline
    await QueryPipeline()._run_query(_make_req())
    qa_writes = [
        c for c in ab.fake_redis.set.await_args_list
        if c.args[0].startswith("last_qa:")
    ]
    assert len(qa_writes) == 1
    assert qa_writes[0].args[0] == "last_qa:sess-1"
    assert qa_writes[0].kwargs.get("ex") == 3600


@pytest.mark.asyncio
async def test_variant_config_overrides_req_top_k(monkeypatch):
    """variant.config['top_k_rerank']=10 → req.top_k mutated to 10 before retrieval."""
    _setup_query_mocks(
        monkeypatch,
        ab_assign_return=("exp-x", "B", {"top_k_rerank": 10}),
    )
    from services.pipeline import QueryPipeline
    req = _make_req()
    assert req.top_k == 5  # baseline
    await QueryPipeline()._run_query(req)
    assert req.top_k == 10, f"variant config did not override req.top_k: got {req.top_k}"


@pytest.mark.asyncio
async def test_variant_config_without_top_k_does_not_change_req(monkeypatch):
    """variant.config without top_k_rerank → req.top_k unchanged."""
    _setup_query_mocks(
        monkeypatch,
        ab_assign_return=("exp-x", "A", {"reranker_type": "cross_encoder"}),
    )
    from services.pipeline import QueryPipeline
    req = _make_req()
    await QueryPipeline()._run_query(req)
    assert req.top_k == 5


@pytest.mark.asyncio
async def test_assign_variant_connection_error_is_non_fatal(monkeypatch):
    """Redis down during assign_variant: query still completes, no record_result."""
    ab = _setup_query_mocks(
        monkeypatch,
        ab_assign_return=None,
        ab_assign_raises=ConnectionError("redis down"),
    )
    from services.pipeline import QueryPipeline
    response = await QueryPipeline()._run_query(_make_req())
    assert response.answer == "ans"
    ab.record_result.assert_not_awaited()
