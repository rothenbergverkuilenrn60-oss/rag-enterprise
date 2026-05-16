"""tests/unit/test_openai_embedder.py — Phase 23 / A1 regression (Plan 23-02 Task 3).

Verifies that ``OpenAIEmbedder.embed_batch`` requests the configured
``settings.embedding_dim`` from the OpenAI API by passing the ``dimensions``
kwarg to ``embeddings.create``.

Closes RESEARCH §Pitfall 2: ``text-embedding-3-large`` returns native 3072-dim
vectors unless the API call explicitly opts into a smaller width. The
``long_term_facts.embedding`` column from Plan 01 is ``VECTOR(settings.
embedding_dim)`` (= 1024 in the default config), so without the kwarg every
``save_fact`` call routed via the OpenAI provider would raise pgvector
dim-mismatch and be silently swallowed by the background task's
``log_task_error`` done-callback — a prod-only silent-failure mode invisible
to the HuggingFace-default test suite.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_openai_embedder_passes_dimensions_kwarg(monkeypatch):
    from config.settings import settings

    # Stub the openai.AsyncOpenAI constructor so OpenAIEmbedder.__init__ does
    # not require a real API key. The stub captures the constructed client so
    # we can assert on embeddings.create kwargs.
    captured_client = MagicMock()
    create_mock = AsyncMock(
        return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 1024)])
    )
    captured_client.embeddings.create = create_mock

    def _fake_async_openai(*args, **kwargs):  # noqa: ARG001
        return captured_client

    # Patch the symbol inside the openai package — OpenAIEmbedder.__init__ does
    # `from openai import AsyncOpenAI` lazily, so patching the source attr
    # intercepts the binding.
    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", _fake_async_openai)

    from services.vectorizer.embedder import OpenAIEmbedder

    embedder = OpenAIEmbedder()
    out = await embedder.embed_batch(["fact"])

    # Returned shape preserved (1 text → 1 vector → 1024 dims).
    assert len(out) == 1
    assert len(out[0]) == 1024

    # embeddings.create called exactly once with dimensions kwarg.
    create_mock.assert_awaited_once()
    kwargs = create_mock.await_args.kwargs
    assert kwargs.get("dimensions") == settings.embedding_dim
    assert kwargs.get("dimensions") == 1024
    assert kwargs.get("model") == (settings.embedding_model or "text-embedding-3-large")
    assert kwargs.get("input") == ["fact"]
    assert kwargs.get("encoding_format") == "float"
