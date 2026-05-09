"""tests/unit/test_version_service.py — Phase 15 backfill.

Covers VersionService Redis-backed CRUD: record_version (first + subsequent),
get_versions, get_version, get_current, rollback success/failure paths,
delete_versions, and Redis-error fallbacks.
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
    import services.knowledge.version_service as mod
    yield
    monkeypatch.setattr(mod, "_version_service", None, raising=False)


def _make_svc(redis_mock):
    from services.knowledge.version_service import VersionService
    svc = VersionService.__new__(VersionService)

    async def _r():
        return redis_mock

    svc._get_redis = _r
    return svc


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_version_first_version_is_one():
    r = MagicMock()
    r.zrevrange = AsyncMock(return_value=[])
    r.zadd = AsyncMock()
    r.zcard = AsyncMock(return_value=1)
    r.expire = AsyncMock()
    svc = _make_svc(r)
    v = await svc.record_version(
        doc_id="d1", checksum="abc", file_path="/p/x.pdf", chunk_count=10,
    )
    assert v.version == 1
    assert v.is_current is True
    r.zadd.assert_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_version_increments_existing_version():
    import json as _json

    from utils.models import DocumentVersion
    prev = DocumentVersion(doc_id="d1", version=3, file_path="/p/x.pdf")
    r = MagicMock()
    r.zrevrange = AsyncMock(return_value=[(_json.dumps(prev.model_dump()), 3)])
    r.zadd = AsyncMock()
    r.zcard = AsyncMock(return_value=4)
    r.expire = AsyncMock()
    svc = _make_svc(r)
    v = await svc.record_version(
        doc_id="d1", checksum="def", file_path="/p/x.pdf", chunk_count=20,
    )
    assert v.version == 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_version_redis_error_returns_fallback():
    """Error path: Redis fails → returns minimal DocumentVersion(version=1)."""
    r = MagicMock()
    r.zrevrange = AsyncMock(side_effect=redis_async.RedisError("down"))
    svc = _make_svc(r)
    v = await svc.record_version(
        doc_id="d1", checksum="abc", file_path="/p", chunk_count=5,
    )
    assert v.version == 1
    assert v.checksum == "abc"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_record_version_trims_when_max_exceeded():
    r = MagicMock()
    r.zrevrange = AsyncMock(return_value=[])
    r.zadd = AsyncMock()
    r.zcard = AsyncMock(return_value=60)
    r.zremrangebyrank = AsyncMock()
    r.expire = AsyncMock()
    svc = _make_svc(r)
    await svc.record_version(doc_id="d1", checksum="x", file_path="/p", chunk_count=1)
    r.zremrangebyrank.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_versions_returns_parsed_list():
    from utils.models import DocumentVersion
    v1 = DocumentVersion(doc_id="d1", version=1, file_path="/p")
    v2 = DocumentVersion(doc_id="d1", version=2, file_path="/p")
    r = MagicMock()
    r.zrevrange = AsyncMock(return_value=[
        (v2.model_dump_json(), 2),
        (v1.model_dump_json(), 1),
    ])
    svc = _make_svc(r)
    out = await svc.get_versions("d1")
    assert out.total == 2
    assert out.versions[0].version == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_versions_redis_error_returns_empty():
    r = MagicMock()
    r.zrevrange = AsyncMock(side_effect=redis_async.RedisError("boom"))
    svc = _make_svc(r)
    out = await svc.get_versions("d1")
    assert out.total == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_version_returns_match():
    from utils.models import DocumentVersion
    v = DocumentVersion(doc_id="d1", version=2, file_path="/p")
    r = MagicMock()
    r.zrangebyscore = AsyncMock(return_value=[v.model_dump_json()])
    svc = _make_svc(r)
    out = await svc.get_version("d1", 2)
    assert out is not None
    assert out.version == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_version_redis_error_returns_none():
    """Error path: Redis fails → None."""
    r = MagicMock()
    r.zrangebyscore = AsyncMock(side_effect=redis_async.RedisError("boom"))
    svc = _make_svc(r)
    out = await svc.get_version("d1", 1)
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_current_returns_first_version():
    from utils.models import DocumentVersion
    v_recent = DocumentVersion(doc_id="d1", version=5, file_path="/p")
    r = MagicMock()
    r.zrevrange = AsyncMock(return_value=[(v_recent.model_dump_json(), 5)])
    svc = _make_svc(r)
    out = await svc.get_current("d1")
    assert out is not None
    assert out.version == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_current_returns_none_when_no_versions():
    r = MagicMock()
    r.zrevrange = AsyncMock(return_value=[])
    svc = _make_svc(r)
    out = await svc.get_current("missing")
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rollback_target_not_found_returns_false():
    """Error path: target version missing → (False, message)."""
    r = MagicMock()
    r.zrangebyscore = AsyncMock(return_value=[])
    svc = _make_svc(r)
    ok, msg = await svc.rollback("d1", 99)
    assert ok is False
    assert "not found" in msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rollback_no_file_path_returns_false():
    from utils.models import DocumentVersion
    v = DocumentVersion(doc_id="d1", version=2, file_path="")
    r = MagicMock()
    r.zrangebyscore = AsyncMock(return_value=[v.model_dump_json()])
    svc = _make_svc(r)
    ok, msg = await svc.rollback("d1", 2)
    assert ok is False
    assert "file_path" in msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rollback_happy_path(monkeypatch):
    from utils.models import DocumentVersion
    v = DocumentVersion(doc_id="d1", version=2, file_path="/p/x.pdf")
    r = MagicMock()
    r.zrangebyscore = AsyncMock(return_value=[v.model_dump_json()])
    r.zrevrange = AsyncMock(return_value=[])
    r.zadd = AsyncMock()
    r.zcard = AsyncMock(return_value=1)
    r.expire = AsyncMock()
    svc = _make_svc(r)

    fake_pipeline = MagicMock()
    fake_result = MagicMock(success=True, total_chunks=12, error="")
    fake_pipeline.run = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(
        "services.pipeline.get_ingest_pipeline", lambda: fake_pipeline, raising=False,
    )

    ok, msg = await svc.rollback("d1", 2, user_id="u1")
    assert ok is True
    assert "version 2" in msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_versions_calls_redis_delete():
    r = MagicMock()
    r.delete = AsyncMock(return_value=1)
    svc = _make_svc(r)
    out = await svc.delete_versions("d1")
    assert out == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_versions_redis_error_returns_zero():
    """Error path: Redis fails → 0."""
    r = MagicMock()
    r.delete = AsyncMock(side_effect=redis_async.RedisError("boom"))
    svc = _make_svc(r)
    out = await svc.delete_versions("d1")
    assert out == 0


@pytest.mark.unit
def test_get_version_service_singleton():
    from services.knowledge.version_service import get_version_service
    a = get_version_service()
    b = get_version_service()
    assert a is b
