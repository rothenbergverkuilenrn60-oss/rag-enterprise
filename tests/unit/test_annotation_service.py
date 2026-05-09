"""tests/unit/test_annotation_service.py — Phase 15 backfill.

Covers AnnotationService: push_task / pop_task / submit_result happy paths
and Redis-error paths, skip_task, get_stats with empty + populated state,
and singleton accessor.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import pytest
import redis.asyncio as redis_async


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.annotation.annotation_service as mod
    yield
    monkeypatch.setattr(mod, "_annotation_service", None, raising=False)


def _fake_pipeline():
    pipe = MagicMock()
    pipe.set = MagicMock()
    pipe.zadd = MagicMock()
    pipe.sadd = MagicMock()
    pipe.execute = AsyncMock()
    return pipe


def _make_redis_mock():
    r = MagicMock()
    r.pipeline = MagicMock(return_value=_fake_pipeline())
    return r


def _attach_redis(svc, r):
    async def _redis():
        return r
    svc._redis = _redis


def _make_svc():
    from services.annotation.annotation_service import AnnotationService
    return AnnotationService.__new__(AnnotationService)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_push_task_writes_to_redis_pipeline():
    from utils.models import AnnotationTask
    r = _make_redis_mock()
    svc = _make_svc()
    _attach_redis(svc, r)
    task = AnnotationTask(question="q", answer="a", priority=5)
    await svc.push_task(task)
    r.pipeline.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_push_task_redis_error_swallowed():
    """Error path: RedisError logged, no propagation."""
    from utils.models import AnnotationTask
    r = MagicMock()

    def boom_pipeline():
        raise redis_async.RedisError("connection lost")

    r.pipeline = MagicMock(side_effect=redis_async.RedisError("boom"))
    svc = _make_svc()
    _attach_redis(svc, r)
    await svc.push_task(AnnotationTask(question="q", answer="a"))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_push_task_from_ragas_high_priority_for_low_score():
    captured: list = []
    svc = _make_svc()

    async def capture(task):
        captured.append(task)

    svc.push_task = capture
    await svc.push_task_from_ragas(
        question="q", answer="a", contexts=["c1"], ragas_score=0.2,
    )
    assert captured[0].priority == 10
    assert captured[0].source == "ragas"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_push_task_from_feedback_uses_max_priority():
    captured: list = []
    svc = _make_svc()

    async def capture(task):
        captured.append(task)

    svc.push_task = capture
    await svc.push_task_from_feedback(
        question="q", answer="a", contexts=["c1"], tenant_id="t1",
    )
    assert captured[0].priority == 20
    assert captured[0].source == "feedback"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pop_task_returns_none_when_queue_empty():
    r = MagicMock()
    r.zpopmax = AsyncMock(return_value=[])
    svc = _make_svc()
    _attach_redis(svc, r)
    out = await svc.pop_task()
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pop_task_happy_path():
    from utils.models import AnnotationTask
    task = AnnotationTask(question="q", answer="a", task_id="t1")
    r = MagicMock()
    r.zpopmax = AsyncMock(return_value=[("t1", 100)])
    r.get = AsyncMock(return_value=task.model_dump_json())
    r.set = AsyncMock()
    svc = _make_svc()
    _attach_redis(svc, r)
    out = await svc.pop_task()
    assert out is not None
    assert out.task_id == "t1"
    assert out.status == "annotating"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pop_task_returns_none_when_task_missing():
    r = MagicMock()
    r.zpopmax = AsyncMock(return_value=[("missing", 100)])
    r.get = AsyncMock(return_value=None)
    svc = _make_svc()
    _attach_redis(svc, r)
    out = await svc.pop_task()
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pop_task_redis_error_returns_none():
    """Error path: RedisError on zpopmax → returns None, no propagation."""
    r = MagicMock()
    r.zpopmax = AsyncMock(side_effect=redis_async.RedisError("boom"))
    svc = _make_svc()
    _attach_redis(svc, r)
    out = await svc.pop_task()
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_result_low_quality_skips_golden(monkeypatch):
    from utils.models import AnnotationResult, AnnotationTask
    task = AnnotationTask(question="q", answer="a", task_id="t1")
    r = MagicMock()
    r.pipeline = MagicMock(return_value=_fake_pipeline())
    r.get = AsyncMock(return_value=task.model_dump_json())
    svc = _make_svc()
    _attach_redis(svc, r)
    update_mock = AsyncMock()
    monkeypatch.setattr(svc, "_update_golden_dataset", update_mock)
    res = AnnotationResult(
        task_id="t1", annotator_id="ann1",
        faithfulness=0.4, answer_quality=0.4,
    )
    await svc.submit_result(res)
    update_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_submit_result_high_quality_calls_golden_update(monkeypatch):
    from utils.models import AnnotationResult, AnnotationTask
    task = AnnotationTask(question="q", answer="a", task_id="t1")
    r = MagicMock()
    r.pipeline = MagicMock(return_value=_fake_pipeline())
    r.get = AsyncMock(return_value=task.model_dump_json())
    svc = _make_svc()
    _attach_redis(svc, r)
    update_mock = AsyncMock()
    monkeypatch.setattr(svc, "_update_golden_dataset", update_mock)
    res = AnnotationResult(
        task_id="t1", annotator_id="ann1",
        faithfulness=0.9, answer_quality=0.9,
    )
    await svc.submit_result(res)
    update_mock.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skip_task_writes_to_skip_set():
    r = MagicMock()
    r.pipeline = MagicMock(return_value=_fake_pipeline())
    r.get = AsyncMock(return_value=None)
    svc = _make_svc()
    _attach_redis(svc, r)
    await svc.skip_task("t1")
    r.pipeline.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_stats_empty():
    r = MagicMock()
    r.zcard = AsyncMock(return_value=0)
    r.scard = AsyncMock(return_value=0)
    r.keys = AsyncMock(return_value=[])
    svc = _make_svc()
    _attach_redis(svc, r)
    stats = await svc.get_stats()
    assert stats.total_tasks == 0
    assert stats.avg_faithfulness is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_stats_with_data():
    from utils.models import AnnotationResult
    res = AnnotationResult(task_id="t1", annotator_id="a", faithfulness=0.8, answer_quality=0.7)
    r = MagicMock()
    r.zcard = AsyncMock(return_value=2)
    r.scard = AsyncMock(side_effect=[3, 1])
    r.keys = AsyncMock(return_value=["annotation:result:t1"])
    r.get = AsyncMock(return_value=res.model_dump_json())
    svc = _make_svc()
    _attach_redis(svc, r)
    stats = await svc.get_stats()
    assert stats.total_tasks == 6
    assert stats.avg_faithfulness == 0.8
    assert stats.avg_answer_quality == 0.7


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_stats_redis_error_returns_empty_stats():
    """Error path: RedisError → empty AnnotationStats, no propagation."""
    r = MagicMock()
    r.zcard = AsyncMock(side_effect=redis_async.RedisError("boom"))
    svc = _make_svc()
    _attach_redis(svc, r)
    stats = await svc.get_stats()
    assert stats.total_tasks == 0


@pytest.mark.unit
def test_get_annotation_service_singleton():
    from services.annotation.annotation_service import get_annotation_service
    a = get_annotation_service()
    b = get_annotation_service()
    assert a is b


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_golden_dataset_writes_new_pair(tmp_path, monkeypatch):
    from utils.models import AnnotationResult, AnnotationTask
    target = tmp_path / "qa_pairs.json"
    monkeypatch.setattr(
        "services.annotation.annotation_service._GOLDEN_DATASET_PATH", target,
    )
    svc = _make_svc()
    task = AnnotationTask(question="Q1", answer="A1", task_id="t1")
    result = AnnotationResult(
        task_id="t1", annotator_id="ann1",
        faithfulness=0.9, answer_quality=0.9,
        corrected_answer="A1-corrected",
    )
    await svc._update_golden_dataset(task, result)
    assert target.exists()
    import json as _json
    data = _json.loads(target.read_text(encoding="utf-8"))
    assert any(p["question"] == "Q1" for p in data["pairs"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_golden_dataset_skips_duplicate_question(tmp_path, monkeypatch):
    import json as _json

    from utils.models import AnnotationResult, AnnotationTask
    target = tmp_path / "qa_pairs.json"
    target.write_text(_json.dumps({"name": "x", "pairs": [{"question": "Q1"}]}), encoding="utf-8")
    monkeypatch.setattr(
        "services.annotation.annotation_service._GOLDEN_DATASET_PATH", target,
    )
    svc = _make_svc()
    task = AnnotationTask(question="Q1", answer="A1", task_id="t-dup")
    result = AnnotationResult(
        task_id="t-dup", annotator_id="ann1",
        faithfulness=0.9, answer_quality=0.9,
    )
    await svc._update_golden_dataset(task, result)
    data = _json.loads(target.read_text(encoding="utf-8"))
    assert len(data["pairs"]) == 1
