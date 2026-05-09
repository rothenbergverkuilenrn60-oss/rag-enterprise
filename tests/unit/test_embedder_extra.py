"""tests/unit/test_embedder_extra.py — Phase 15 backfill.

Existing tests/unit/test_embedder.py covers a subset of the Ollama path.
This file adds coverage for BatchedEmbedder splitting, EnsembleEmbedder
average + concat strategies, _make_base_embedder factory branches and
errors, and the singleton accessor.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.vectorizer.embedder as mod
    yield
    monkeypatch.setattr(mod, "_embedder_instance", None, raising=False)


class _StubEmbedder:
    def __init__(self, vec):
        self._vec = vec
        self.calls = 0

    async def embed_batch(self, texts):
        self.calls += 1
        return [list(self._vec) for _ in texts]

    async def embed_one(self, text):
        out = await self.embed_batch([text])
        return out[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_batched_embedder_splits_into_batches():
    from services.vectorizer.embedder import BatchedEmbedder
    base = _StubEmbedder([0.1, 0.2])
    be = BatchedEmbedder(base, batch_size=2)
    out = await be.embed_batch(["a", "b", "c", "d", "e"])
    assert len(out) == 5
    assert base.calls == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_batched_embedder_embed_one_returns_first():
    from services.vectorizer.embedder import BatchedEmbedder
    be = BatchedEmbedder(_StubEmbedder([1.0, 2.0]), batch_size=4)
    out = await be.embed_one("hello")
    assert out == [1.0, 2.0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensemble_average_strategy_normalizes():
    from services.vectorizer.embedder import EnsembleEmbedder
    e1 = _StubEmbedder([1.0, 0.0, 0.0])
    e2 = _StubEmbedder([0.0, 1.0, 0.0])
    ens = EnsembleEmbedder([e1, e2], weights=[1.0, 1.0], strategy="average")
    out = await ens.embed_batch(["x"])
    assert len(out) == 1
    norm = sum(v * v for v in out[0]) ** 0.5
    assert abs(norm - 1.0) < 1e-6


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensemble_concat_strategy_concatenates_dims():
    from services.vectorizer.embedder import EnsembleEmbedder
    e1 = _StubEmbedder([0.5, 0.5])
    e2 = _StubEmbedder([0.1, 0.2, 0.3])
    ens = EnsembleEmbedder([e1, e2], weights=[1.0, 1.0], strategy="concat")
    out = await ens.embed_batch(["x"])
    assert len(out[0]) == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensemble_embed_one():
    from services.vectorizer.embedder import EnsembleEmbedder
    e1 = _StubEmbedder([1.0, 0.0])
    ens = EnsembleEmbedder([e1], weights=[1.0], strategy="average")
    out = await ens.embed_one("y")
    assert len(out) == 2


@pytest.mark.unit
def test_make_base_embedder_unknown_provider_raises():
    """Error path: invalid provider → ValueError."""
    from services.vectorizer.embedder import _make_base_embedder
    with pytest.raises(ValueError, match="Unknown"):
        _make_base_embedder("not-a-provider")


@pytest.mark.unit
def test_get_embedder_returns_batched_for_single_provider(monkeypatch):
    """Default factory branch: no embedding_ensemble → BatchedEmbedder."""
    from services.vectorizer import embedder as mod

    stub = _StubEmbedder([1.0])
    monkeypatch.setattr(mod, "_make_base_embedder", lambda _p: stub)
    monkeypatch.setattr(mod.settings, "embedding_ensemble", [], raising=False)
    monkeypatch.setattr(mod.settings, "embedding_provider", "ollama", raising=False)
    out = mod.get_embedder()
    assert isinstance(out, mod.BatchedEmbedder)
    assert mod.get_embedder() is out


@pytest.mark.unit
def test_get_embedder_returns_ensemble_when_configured(monkeypatch):
    """Cover the ensemble-config branch of get_embedder."""
    from services.vectorizer import embedder as mod

    monkeypatch.setattr(mod, "_embedder_instance", None, raising=False)
    stubs = [_StubEmbedder([1.0]), _StubEmbedder([2.0])]
    iter_stubs = iter(stubs)
    monkeypatch.setattr(mod, "_make_base_embedder", lambda _p: next(iter_stubs))
    cfg = [{"provider": "ollama", "weight": 0.5}, {"provider": "openai", "weight": 0.5}]
    original_ensemble = getattr(mod.settings, "embedding_ensemble", [])
    original_strategy = getattr(mod.settings, "embedding_ensemble_strategy", "average")
    object.__setattr__(mod.settings, "embedding_ensemble", cfg)
    object.__setattr__(mod.settings, "embedding_ensemble_strategy", "concat")
    try:
        out = mod.get_embedder()
        assert isinstance(out, mod.EnsembleEmbedder)
    finally:
        object.__setattr__(mod.settings, "embedding_ensemble", original_ensemble)
        object.__setattr__(mod.settings, "embedding_ensemble_strategy", original_strategy)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_base_embedder_embed_one_routes_through_batch():
    """Cover the BaseEmbedder default embed_one implementation via subclass."""
    from services.vectorizer.embedder import BaseEmbedder

    class Dummy(BaseEmbedder):
        async def embed_batch(self, texts):
            return [[float(len(t))] for t in texts]

    d = Dummy()
    out = await d.embed_one("abc")
    assert out == [3.0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ollama_embedder_embed_batch_propagates_failure(monkeypatch):
    """Error path: Ollama _embed_single raises → embed_batch raises RuntimeError."""
    from services.vectorizer.embedder import OllamaEmbedder
    inst = OllamaEmbedder.__new__(OllamaEmbedder)

    async def boom(_self, text):
        raise RuntimeError("connect refused")

    inst._embed_single = boom.__get__(inst)  # type: ignore[method-assign]
    inst._client = AsyncMock()
    inst._base_url = "http://localhost"
    inst._model = "stub"
    with pytest.raises(RuntimeError):
        await inst.embed_batch(["a", "b"])
