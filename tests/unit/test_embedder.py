"""
tests/unit/test_embedder.py
Unit tests for OllamaEmbedder.embed_batch (no real HTTP calls).

NOTE: OllamaEmbedder.__init__ takes no arguments — it reads settings.ollama_base_url
and settings.embedding_model at construction time, then stores a persistent
httpx.AsyncClient in self._client. Tests monkeypatch self._client directly
(after construction) to intercept all HTTP calls.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock


def _make_mock_client(embedding: list[float]) -> AsyncMock:
    """Return a mock httpx.AsyncClient whose .post() returns the given embedding."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"embedding": embedding})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_ollama_embedder_embed_batch_returns_vectors(monkeypatch):
    """embed_batch(['hello']) returns [[0.1, 0.2, 0.3]] when HTTP mock returns that embedding."""
    from services.vectorizer.embedder import OllamaEmbedder

    embedder = OllamaEmbedder()
    mock_client = _make_mock_client([0.1, 0.2, 0.3])
    monkeypatch.setattr(embedder, "_client", mock_client)

    result = await embedder.embed_batch(["hello world"])
    assert result == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_ollama_embedder_embed_batch_multiple(monkeypatch):
    """3 input strings → 3 vectors returned (one HTTP call per text)."""
    from services.vectorizer.embedder import OllamaEmbedder

    embedder = OllamaEmbedder()
    mock_client = _make_mock_client([0.1, 0.2, 0.3])
    monkeypatch.setattr(embedder, "_client", mock_client)

    result = await embedder.embed_batch(["text1", "text2", "text3"])
    assert len(result) == 3
    assert all(isinstance(v, list) for v in result)
    assert all(len(v) == 3 for v in result)


@pytest.mark.asyncio
async def test_ollama_embedder_raises_on_http_error(monkeypatch):
    """When HTTP post raises ConnectError, tenacity retries (3 attempts) then embed_batch raises RuntimeError."""
    from services.vectorizer.embedder import OllamaEmbedder

    embedder = OllamaEmbedder()

    call_count = 0

    async def _failing_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("connection refused")

    mock_client = AsyncMock()
    mock_client.post = _failing_post
    monkeypatch.setattr(embedder, "_client", mock_client)

    with pytest.raises(RuntimeError):
        await embedder.embed_batch(["hello"])

    # tenacity @retry(stop=stop_after_attempt(3)) → 3 attempts total
    assert call_count == 3, f"Expected 3 retry attempts, got {call_count}"


@pytest.mark.asyncio
async def test_ollama_embedder_passes_model_name(monkeypatch):
    """The JSON payload sent to httpx.post must contain the configured model name."""
    from services.vectorizer.embedder import OllamaEmbedder
    from config.settings import settings

    embedder = OllamaEmbedder()
    mock_client = _make_mock_client([0.5, 0.6])
    monkeypatch.setattr(embedder, "_client", mock_client)

    await embedder.embed_batch(["test text"])

    assert mock_client.post.await_count >= 1
    call_kwargs = mock_client.post.await_args.kwargs
    payload = call_kwargs.get("json", {})
    assert "model" in payload
    assert payload["model"] == settings.embedding_model
