"""Self-tests for the redis_mock + app_factory + isolated_* fixtures.

Plan 27-00 task 2 — TD-06 (D-18, D-19, D-20 override) scaffolding.

All tests use `@pytest.mark.uses_redis` to exercise the marker-auto-apply hook
(`pytest_collection_modifyitems` in `tests/conftest.py`). The marker fires the
`redis_mock` fixture even when not declared as a test argument — Test 2 below
proves the hook works.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import pytest

pytestmark = [pytest.mark.asyncio]


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: marker is registered (no PytestUnknownMarkWarning).
# Implemented via the acceptance-criteria grep `uv run pytest --markers | grep`.
# Here we add an inline sanity assertion that the marker is recognized on a
# decorated test (a real PytestUnknownMarkWarning would fail Test 2 below).
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.uses_redis
async def test_marker_auto_applies_fixture(request: pytest.FixtureRequest) -> None:
    """Test 2: pytest_collection_modifyitems auto-attaches redis_mock when
    only the marker is declared (no explicit fixture arg)."""
    assert "redis_mock" in request.fixturenames


@pytest.mark.uses_redis
async def test_redis_mock_get_set(redis_mock) -> None:  # type: ignore[no-untyped-def]
    """Test 3: string GET/SET round-trip via fakeredis."""
    await redis_mock.set("k1", "v1")
    assert await redis_mock.get("k1") == "v1"


@pytest.mark.uses_redis
async def test_redis_mock_rpush_lrange(redis_mock) -> None:  # type: ignore[no-untyped-def]
    """Test 4: list RPUSH/LRANGE (used by ShortTermMemory)."""
    await redis_mock.rpush("mylist", "a", "b")
    items = await redis_mock.lrange("mylist", 0, -1)
    assert items == ["a", "b"]


@pytest.mark.uses_redis
async def test_redis_mock_zadd_zcount(redis_mock) -> None:  # type: ignore[no-untyped-def]
    """Test 5: sorted-set ZADD/ZCOUNT (used by main.py rate-limiter)."""
    await redis_mock.zadd("rate", {"req1": 1.0})
    assert await redis_mock.zcount("rate", 0, 10) == 1


@pytest.mark.uses_redis
async def test_redis_mock_expire_and_pipeline(redis_mock) -> None:  # type: ignore[no-untyped-def]
    """Test 6: EXPIRE + pipeline (used by entity_disambiguator / ab_test)."""
    await redis_mock.set("k", "v")
    assert await redis_mock.expire("k", 60) is True
    pipe = redis_mock.pipeline()
    pipe.set("a", "1")
    pipe.set("b", "2")
    results = await pipe.execute()
    assert results == [True, True]
    assert await redis_mock.get("a") == "1"
    assert await redis_mock.get("b") == "2"


# T-G1 conditional from /plan-eng-review: hash ops ARE used in services/
# (entity_disambiguator.py + ab_test_service.py confirmed via plan-time grep).
# Therefore include the hash-ops test.
@pytest.mark.uses_redis
async def test_redis_mock_hash_ops(redis_mock) -> None:  # type: ignore[no-untyped-def]
    """Test 6b (T-G1): hash HGET/HSET/HGETALL round-trip.

    Required because services/nlu/entity_disambiguator.py + services/ab_test/ab_test_service.py
    use HSET/HGET/HGETALL/HDEL against Redis. fakeredis natively supports these — this
    test pins that support.
    """
    await redis_mock.hset("h", "f1", "v1")
    await redis_mock.hset("h", "f2", "v2")
    assert await redis_mock.hget("h", "f1") == "v1"
    full = await redis_mock.hgetall("h")
    assert full == {"f1": "v1", "f2": "v2"}
    await redis_mock.hdel("h", "f1")
    assert await redis_mock.hget("h", "f1") is None


@pytest.mark.uses_redis
async def test_utils_cache_get_redis_returns_mock(redis_mock) -> None:  # type: ignore[no-untyped-def]
    """Test 7: utils.cache.get_redis() returns the same fakeredis instance."""
    from utils.cache import get_redis

    client = await get_redis()
    assert client is redis_mock


@pytest.mark.uses_redis
async def test_redis_asyncio_from_url_returns_mock(redis_mock) -> None:  # type: ignore[no-untyped-def]
    """Test 8: redis.asyncio.from_url(...) is also patched — covers Pitfall 6
    (ShortTermMemory._get_client bypass)."""
    from redis.asyncio import from_url

    client = await from_url("redis://ignored:6379")
    assert client is redis_mock


async def test_app_factory_yields_callable(app_factory) -> None:  # type: ignore[no-untyped-def]
    """Test 9: app_factory fixture yields a callable; calling it invokes create_app().

    Gated via importorskip on main._configure_app — skips cleanly until plan 27-01.
    """
    pytest.importorskip("main")
    import main

    if getattr(main, "_configure_app", None) is None:
        pytest.skip("needs main._configure_app from plan 27-01")
    app = app_factory()
    from fastapi import FastAPI

    assert isinstance(app, FastAPI)
