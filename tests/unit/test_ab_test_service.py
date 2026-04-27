"""
tests/unit/test_ab_test_service.py
Unit tests for ABTestService routing determinism using fakeredis (no real Redis required).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
import pytest_asyncio
import fakeredis
from unittest.mock import AsyncMock, MagicMock


@pytest_asyncio.fixture
async def fake_redis():
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def reset_ab_singleton(monkeypatch):
    import services.ab_test.ab_test_service as mod
    yield
    monkeypatch.setattr(mod, "_ab_service", None, raising=False)


async def _setup_running_experiment(svc, experiment_id: str = "exp-001") -> str:
    """Helper: create a 2-variant experiment, start it, return experiment_id."""
    from services.ab_test.ab_test_service import Experiment, Variant

    exp = Experiment(
        experiment_id=experiment_id,
        name="Test Experiment",
        variants=[
            Variant(variant_id="A", name="Control", traffic_pct=0.5, config={"top_k": 6}),
            Variant(variant_id="B", name="Treatment", traffic_pct=0.5, config={"top_k": 10}),
        ],
    )
    await svc.create_experiment(exp)
    await svc.start_experiment(experiment_id)
    return experiment_id


@pytest.mark.asyncio
async def test_get_variant_determinism(fake_redis, monkeypatch):
    """Same session_id + experiment returns the same variant on two calls."""
    from services.ab_test.ab_test_service import ABTestService

    svc = ABTestService()
    monkeypatch.setattr(svc, "_redis", fake_redis)

    await _setup_running_experiment(svc)

    exp_id1, variant_id1, _ = await svc.assign_variant("user-session-abc", "")
    exp_id2, variant_id2, _ = await svc.assign_variant("user-session-abc", "")

    assert variant_id1 == variant_id2
    assert exp_id1 == exp_id2


@pytest.mark.asyncio
async def test_get_variant_different_users_can_differ(fake_redis, monkeypatch):
    """Different user IDs should not all land on the same variant (distribution check)."""
    from services.ab_test.ab_test_service import ABTestService

    svc = ABTestService()
    monkeypatch.setattr(svc, "_redis", fake_redis)

    await _setup_running_experiment(svc)

    variants_seen = set()
    for i in range(1, 21):
        _, variant_id, _ = await svc.assign_variant(f"user-{i}", "")
        if variant_id is not None:
            variants_seen.add(variant_id)

    # With 20 users and 50/50 split, at least two different variants should be assigned
    assert len(variants_seen) >= 2, (
        f"Expected at least 2 distinct variants across 20 users, got: {variants_seen}"
    )


@pytest.mark.asyncio
async def test_get_variant_caches_in_redis(fake_redis, monkeypatch):
    """After creating and starting an experiment, Redis contains the expected keys."""
    from services.ab_test.ab_test_service import ABTestService

    svc = ABTestService()
    monkeypatch.setattr(svc, "_redis", fake_redis)

    exp_id = await _setup_running_experiment(svc, "exp-cache-test")

    # Trigger a variant assignment to ensure the experiment is active
    await svc.assign_variant("user-check", "")

    keys = await fake_redis.keys("*")
    key_strings = [k if isinstance(k, str) else k.decode() for k in keys]

    # The experiment should be stored and running set should have the exp_id
    assert any("ab:experiments" in k for k in key_strings)
    assert any("ab:running" in k for k in key_strings)
