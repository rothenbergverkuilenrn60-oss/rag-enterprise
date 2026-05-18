"""
tests/unit/test_short_term_memory_get_redis.py

Phase 27 / Plan 27-02 / Task 1 — proves ShortTermMemory._get_client
delegates to utils.cache.get_redis (closes the only remaining Redis bypass
in services/, enabling single-target mocking; RESEARCH §6 D-19 follow-on).

The `redis_mock` fixture (auto-applied via the `@pytest.mark.uses_redis`
marker hook from plan 27-00) patches `utils.cache.get_redis` to return a
fakeredis client. After the Task 1 refactor, ShortTermMemory._get_client
must call `get_redis()` rather than `redis.asyncio.from_url`, so the fake
flows through to the cached `_client`.

Env-var setdefault block mirrors tests/unit/test_memory_save_fact.py:27-28.
Autouse singleton-reset fixture mirrors test_memory_save_fact.py:43-47.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from pathlib import Path

import pytest

# File-level marker — every test in this module exercises the Redis path,
# so redis_mock is auto-attached via the pytest_collection_modifyitems hook
# (tests/conftest.py:228-245). asyncio mark is applied per-test (not at file
# level) because Test 4 is a sync static-source guard.
pytestmark = pytest.mark.uses_redis


@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch: pytest.MonkeyPatch):
    """Reset module-level _memory_service singleton between tests so
    fresh ShortTermMemory instances do not leak the prior test's _client
    cache. Pattern mirrors tests/unit/test_memory_save_fact.py:43-47."""
    import services.memory.memory_service as mod

    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


# -----------------------------------------------------------------------------
# Test 1 — _get_client delegates to utils.cache.get_redis
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_client_returns_redis_mock_via_get_redis(redis_mock) -> None:
    """After the bonus refactor, ShortTermMemory._get_client must call
    utils.cache.get_redis (which the redis_mock fixture has patched to
    return the fakeredis instance). The client returned must be literally
    the same fakeredis object the fixture yielded."""
    from services.memory.memory_service import ShortTermMemory

    stm = ShortTermMemory()
    client = await stm._get_client()
    assert client is redis_mock, (
        "ShortTermMemory._get_client must delegate to utils.cache.get_redis "
        "(which redis_mock has patched). If `client is not redis_mock`, the "
        "method is still bypassing get_redis via direct from_url import."
    )


# -----------------------------------------------------------------------------
# Test 2 — _client cache is honored (singleton-per-instance)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_client_caches_after_first_call(redis_mock) -> None:
    """Second _get_client() call returns the cached instance, not a fresh
    get_redis() invocation. Preserves the v1.0 self._client caching contract."""
    from services.memory.memory_service import ShortTermMemory

    stm = ShortTermMemory()
    first = await stm._get_client()
    second = await stm._get_client()
    assert first is second, (
        "_get_client should cache the first client on self._client and "
        "return the same instance on subsequent calls."
    )


# -----------------------------------------------------------------------------
# Test 3 — End-to-end RPUSH/LRANGE round-trip via fakeredis backing
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_append_and_get_history_round_trip_via_fake(redis_mock) -> None:
    """Regression gate: after the refactor, ShortTermMemory.append +
    get_history still produce the expected list semantics against the
    fakeredis-backed client (RPUSH on append, LRANGE on get_history)."""
    from services.memory.memory_service import ConversationTurn, ShortTermMemory

    stm = ShortTermMemory()
    turn = ConversationTurn(role="user", content="hello-27-02")
    await stm.append("sess-27-02", turn)

    history = await stm.get_history("sess-27-02", max_turns=10)
    assert len(history) == 1
    assert history[0].role == "user"
    assert history[0].content == "hello-27-02"


# -----------------------------------------------------------------------------
# Test 4 — Static assertion: services/memory/memory_service.py no longer
# imports redis.asyncio.from_url anywhere (file-level or lazy in ShortTermMemory).
# -----------------------------------------------------------------------------
def test_memory_service_module_no_longer_imports_from_url() -> None:
    """Source-level guard: after the refactor, the file must not contain
    `from redis.asyncio import from_url` (lazy or top-level). The only
    remaining Redis-access path inside ShortTermMemory must be the lazy
    `from utils.cache import get_redis` import."""
    src = Path("services/memory/memory_service.py").read_text(encoding="utf-8")
    # Strip comment lines to avoid matching commented-out historical references.
    non_comment_lines = [
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    ]
    body = "\n".join(non_comment_lines)
    assert "from redis.asyncio import from_url" not in body, (
        "ShortTermMemory._get_client must no longer import "
        "`from_url` from redis.asyncio (use utils.cache.get_redis instead). "
        "Found a non-comment reference — refactor incomplete."
    )
    assert "from utils.cache import get_redis" in body, (
        "ShortTermMemory._get_client must import get_redis from utils.cache "
        "(lazy import inside method body)."
    )
