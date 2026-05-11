"""
tests/unit/test_feedback_ab_forward.py

Verifies POST /api/v1/feedback auto-forwards to ABTestService when the session
has a stored A/B variant mapping in Redis.
"""
from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


def _patch_feedback_deps(monkeypatch, redis_get_returns):
    """Patch the symbols submit_feedback imports lazily. Return (ab_svc_mock, fb_svc_mock)."""
    import services.ab_test.ab_test_service as ab_mod
    import services.feedback.feedback_service as fb_mod
    import utils.cache as cache_mod

    fb_svc = MagicMock()
    fb_svc.submit = AsyncMock()
    monkeypatch.setattr(fb_mod, "get_feedback_service", lambda: fb_svc)

    ab_svc = MagicMock()
    ab_svc.record_feedback = AsyncMock()
    monkeypatch.setattr(ab_mod, "get_ab_test_service", lambda: ab_svc)

    fake_redis = MagicMock()
    fake_redis.get = AsyncMock(return_value=redis_get_returns)
    monkeypatch.setattr(cache_mod, "get_redis", AsyncMock(return_value=fake_redis))

    return ab_svc, fb_svc


@pytest.mark.asyncio
async def test_feedback_forwards_to_ab_when_session_mapped(monkeypatch):
    """Redis has ab:session:{id} → record_feedback called with experiment+variant."""
    mapping = json.dumps({"experiment_id": "exp-9", "variant_id": "B"})
    ab_svc, fb_svc = _patch_feedback_deps(monkeypatch, redis_get_returns=mapping)

    from controllers.api import submit_feedback
    from utils.models import FeedbackRequest
    req = FeedbackRequest(session_id="sess-1", feedback=1, user_id="u1", tenant_id="t1")
    resp = await submit_feedback(req)

    assert resp.success is True
    fb_svc.submit.assert_awaited_once()
    ab_svc.record_feedback.assert_awaited_once_with(
        experiment_id="exp-9", variant_id="B", session_id="sess-1", feedback=1,
    )


@pytest.mark.asyncio
async def test_feedback_does_NOT_forward_when_no_mapping(monkeypatch):
    """Redis returns None → record_feedback NOT called; main submit still runs."""
    ab_svc, fb_svc = _patch_feedback_deps(monkeypatch, redis_get_returns=None)

    from controllers.api import submit_feedback
    from utils.models import FeedbackRequest
    req = FeedbackRequest(session_id="sess-2", feedback=-1)
    resp = await submit_feedback(req)

    assert resp.success is True
    fb_svc.submit.assert_awaited_once()
    ab_svc.record_feedback.assert_not_awaited()


@pytest.mark.asyncio
async def test_negative_feedback_pushes_annotation_task(monkeypatch):
    """feedback=-1 + last_qa Redis snapshot → annotation_service.push_task_from_feedback called."""
    import services.ab_test.ab_test_service as ab_mod
    import services.annotation.annotation_service as ann_mod
    import services.feedback.feedback_service as fb_mod
    import utils.cache as cache_mod

    fb_svc = MagicMock()
    fb_svc.submit = AsyncMock()
    monkeypatch.setattr(fb_mod, "get_feedback_service", lambda: fb_svc)

    ab_svc = MagicMock()
    ab_svc.record_feedback = AsyncMock()
    monkeypatch.setattr(ab_mod, "get_ab_test_service", lambda: ab_svc)

    ann_svc = MagicMock()
    ann_svc.push_task_from_feedback = AsyncMock()
    monkeypatch.setattr(ann_mod, "get_annotation_service", lambda: ann_svc)

    qa_snapshot = json.dumps({
        "question": "Q?", "answer": "A!",
        "contexts": ["ctx1", "ctx2"], "tenant_id": "t1",
    })
    fake_redis = MagicMock()
    # /feedback queries both ab:session: and last_qa: keys
    async def fake_get(key):
        if key.startswith("last_qa:"):
            return qa_snapshot
        return None
    fake_redis.get = AsyncMock(side_effect=fake_get)
    monkeypatch.setattr(cache_mod, "get_redis", AsyncMock(return_value=fake_redis))

    from controllers.api import submit_feedback
    from utils.models import FeedbackRequest
    req = FeedbackRequest(session_id="sess-down", feedback=-1, tenant_id="t1")
    resp = await submit_feedback(req)

    assert resp.success is True
    ann_svc.push_task_from_feedback.assert_awaited_once_with(
        question="Q?", answer="A!",
        contexts=["ctx1", "ctx2"], tenant_id="t1",
    )


@pytest.mark.asyncio
async def test_positive_feedback_does_NOT_push_annotation(monkeypatch):
    """feedback=+1 → no annotation task pushed."""
    import services.ab_test.ab_test_service as ab_mod
    import services.annotation.annotation_service as ann_mod
    import services.feedback.feedback_service as fb_mod
    import utils.cache as cache_mod

    fb_svc = MagicMock(); fb_svc.submit = AsyncMock()
    monkeypatch.setattr(fb_mod, "get_feedback_service", lambda: fb_svc)
    ab_svc = MagicMock(); ab_svc.record_feedback = AsyncMock()
    monkeypatch.setattr(ab_mod, "get_ab_test_service", lambda: ab_svc)
    ann_svc = MagicMock(); ann_svc.push_task_from_feedback = AsyncMock()
    monkeypatch.setattr(ann_mod, "get_annotation_service", lambda: ann_svc)

    fake_redis = MagicMock(); fake_redis.get = AsyncMock(return_value=None)
    monkeypatch.setattr(cache_mod, "get_redis", AsyncMock(return_value=fake_redis))

    from controllers.api import submit_feedback
    from utils.models import FeedbackRequest
    req = FeedbackRequest(session_id="sess-up", feedback=1)
    await submit_feedback(req)
    ann_svc.push_task_from_feedback.assert_not_awaited()


@pytest.mark.asyncio
async def test_feedback_ab_forward_error_is_non_fatal(monkeypatch):
    """Redis ConnectionError during A/B forward: main submit still succeeds."""
    import services.ab_test.ab_test_service as ab_mod
    import services.feedback.feedback_service as fb_mod
    import utils.cache as cache_mod

    fb_svc = MagicMock()
    fb_svc.submit = AsyncMock()
    monkeypatch.setattr(fb_mod, "get_feedback_service", lambda: fb_svc)

    ab_svc = MagicMock()
    ab_svc.record_feedback = AsyncMock()
    monkeypatch.setattr(ab_mod, "get_ab_test_service", lambda: ab_svc)

    monkeypatch.setattr(
        cache_mod, "get_redis", AsyncMock(side_effect=ConnectionError("redis down")),
    )

    from controllers.api import submit_feedback
    from utils.models import FeedbackRequest
    req = FeedbackRequest(session_id="sess-3", feedback=1)
    resp = await submit_feedback(req)

    assert resp.success is True
    fb_svc.submit.assert_awaited_once()
    ab_svc.record_feedback.assert_not_awaited()
