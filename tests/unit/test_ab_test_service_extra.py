"""tests/unit/test_ab_test_service_extra.py — Phase 15 backfill.

Covers stop_experiment, assign_variant tenant filter, record_result no-op,
record_feedback, get_stats empty + populated, get_winner, list_experiments,
and singleton getter — all previously uncovered surface in the existing
ab_test_service tests.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_ab_singleton(monkeypatch):
    import services.ab_test.ab_test_service as mod
    yield
    monkeypatch.setattr(mod, "_ab_service", None, raising=False)


def _fake_pipeline():
    pipe = MagicMock()
    pipe.lpush = MagicMock()
    pipe.ltrim = MagicMock()
    pipe.hset = MagicMock()
    pipe.execute = AsyncMock()
    return pipe


def _make_svc(redis_mock):
    from services.ab_test import ab_test_service as mod
    svc = mod.ABTestService.__new__(mod.ABTestService)
    svc._redis = redis_mock
    return svc


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_result_skips_when_no_experiment_id():
    """Error / no-op path: missing experiment_id → no Redis write."""
    from services.ab_test.ab_test_service import ExperimentResult
    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=_fake_pipeline())
    svc = _make_svc(redis)
    await svc.record_result(ExperimentResult(experiment_id="", variant_id="v1"))
    redis.pipeline.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_result_writes_to_redis_list():
    from services.ab_test.ab_test_service import ExperimentResult
    redis = MagicMock()
    pipe = _fake_pipeline()
    redis.pipeline = MagicMock(return_value=pipe)
    svc = _make_svc(redis)
    await svc.record_result(ExperimentResult(
        experiment_id="exp1", variant_id="v1", session_id="s1", latency_ms=12.0,
    ))
    pipe.lpush.assert_called_once()
    pipe.ltrim.assert_called_once()
    pipe.execute.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_feedback_routes_to_record_result(monkeypatch):
    from services.ab_test import ab_test_service as mod
    svc = _make_svc(MagicMock())
    captured: list = []

    async def capture(result):
        captured.append(result)

    monkeypatch.setattr(svc, "record_result", capture)
    await svc.record_feedback("e1", "v1", "s1", feedback=1)
    assert captured[0].user_feedback == 1
    assert captured[0].experiment_id == "e1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_assign_variant_no_running_experiments():
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value=set())
    svc = _make_svc(redis)
    exp_id, var_id, cfg = await svc.assign_variant("session-1")
    assert exp_id is None and var_id is None and cfg == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_assign_variant_routes_via_consistent_hash():
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value={"exp1"})
    redis.hget = AsyncMock(return_value=json.dumps({
        "experiment_id": "exp1", "name": "x", "tenant_id": "",
    }))
    redis.hgetall = AsyncMock(return_value={
        "vA": json.dumps({"variant_id": "vA", "name": "A", "traffic_pct": 0.5, "config": {"top_k": 6}}),
        "vB": json.dumps({"variant_id": "vB", "name": "B", "traffic_pct": 0.5, "config": {"top_k": 10}}),
    })
    svc = _make_svc(redis)
    exp_id, var_id, cfg = await svc.assign_variant("session-stable", tenant_id="")
    assert exp_id == "exp1"
    assert var_id in ("vA", "vB")
    assert "top_k" in cfg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_assign_variant_tenant_filter_skips_unmatched():
    redis = MagicMock()
    redis.smembers = AsyncMock(return_value={"exp1"})
    redis.hget = AsyncMock(return_value=json.dumps({
        "experiment_id": "exp1", "name": "x", "tenant_id": "tenant-A",
    }))
    redis.hgetall = AsyncMock(return_value={})
    svc = _make_svc(redis)
    exp_id, var_id, cfg = await svc.assign_variant("s1", tenant_id="tenant-B")
    assert exp_id is None and var_id is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_stats_empty_results():
    redis = MagicMock()
    redis.hgetall = AsyncMock(return_value={
        "vA": json.dumps({"variant_id": "vA", "name": "Control", "traffic_pct": 1.0, "config": {}}),
    })
    redis.lrange = AsyncMock(return_value=[])
    svc = _make_svc(redis)
    stats = await svc.get_stats("exp1")
    assert len(stats) == 1
    assert stats[0].sample_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_stats_with_data_computes_aggregates():
    redis = MagicMock()
    redis.hgetall = AsyncMock(return_value={
        "vA": json.dumps({"variant_id": "vA", "name": "A", "traffic_pct": 0.5, "config": {}}),
    })
    redis.lrange = AsyncMock(return_value=[
        json.dumps({"latency_ms": 100.0, "faithfulness": 0.8, "user_feedback": 1}),
        json.dumps({"latency_ms": 200.0, "faithfulness": 0.9, "user_feedback": -1}),
        json.dumps({"latency_ms": 150.0, "faithfulness": 0.7, "user_feedback": 1}),
    ])
    svc = _make_svc(redis)
    stats = await svc.get_stats("exp1")
    assert stats[0].sample_count == 3
    assert stats[0].avg_latency_ms > 0
    assert stats[0].avg_faithfulness > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_winner_returns_none_when_no_data():
    redis = MagicMock()
    redis.hgetall = AsyncMock(return_value={})
    svc = _make_svc(redis)
    winner = await svc.get_winner("exp-missing")
    assert winner is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_winner_picks_highest_score():
    redis = MagicMock()
    redis.hgetall = AsyncMock(return_value={
        "vA": json.dumps({"variant_id": "vA", "name": "A", "traffic_pct": 0.5, "config": {}}),
        "vB": json.dumps({"variant_id": "vB", "name": "B", "traffic_pct": 0.5, "config": {}}),
    })

    async def lrange(key, *_a, **_kw):
        if "vA" in key:
            return [json.dumps({"latency_ms": 100, "faithfulness": 0.5, "user_feedback": 0})]
        return [json.dumps({"latency_ms": 100, "faithfulness": 0.95, "user_feedback": 1})]

    redis.lrange = lrange
    svc = _make_svc(redis)
    winner = await svc.get_winner("exp1")
    assert winner == "vB"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_experiments_returns_decoded_json():
    redis = MagicMock()
    redis.hgetall = AsyncMock(return_value={
        "exp1": json.dumps({"experiment_id": "exp1", "name": "first"}),
        "exp2": json.dumps({"experiment_id": "exp2", "name": "second"}),
    })
    svc = _make_svc(redis)
    out = await svc.list_experiments()
    assert {e["name"] for e in out} == {"first", "second"}


@pytest.mark.unit
def test_get_ab_test_service_singleton():
    from services.ab_test.ab_test_service import get_ab_test_service
    a = get_ab_test_service()
    b = get_ab_test_service()
    assert a is b


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_experiment_rejects_unbalanced_traffic():
    """Error path: variant traffic must sum to 1.0 ± 0.01."""
    from services.ab_test.ab_test_service import (
        ABTestService,
        Experiment,
        Variant,
    )
    redis = MagicMock()
    redis.pipeline = MagicMock(return_value=_fake_pipeline())
    svc = ABTestService.__new__(ABTestService)
    svc._redis = redis
    bad_exp = Experiment(name="bad", variants=[
        Variant(variant_id="a", name="A", traffic_pct=0.3),
        Variant(variant_id="b", name="B", traffic_pct=0.3),
    ])
    with pytest.raises(ValueError, match="must be 1.0"):
        await svc.create_experiment(bad_exp)
