"""Integration-test conftest for TEST-INFRA-01.

TEST-INFRA-01: Bypass ``FileNotFoundError`` raised by local model loads when
bge-m3 / bge-m3-rerank are absent on the host.

Root cause chain:
  AgentQueryPipeline.__init__
    → get_retriever() → Retriever.__init__
      → get_embedder() → HuggingFaceEmbedder() → SentenceTransformer(bge-m3)  ← raises
      → get_reranker() → CrossEncoderReranker() → CrossEncoder(bge-m3-rerank)  ← raises

Fix path: Option (c) per 30-CONTEXT.md — mock both model-loading ``__init__`` methods
directly at integration-conftest scope so the FileNotFoundErrors never fire.

Why NOT option (a) patch-reordering: autouse side-effect risk on non-extractor tests.
Why NOT option (b) CI pre-download: ~1.3 GB model download slows CI, adds infra dep.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_local_model_inits() -> object:
    """TEST-INFRA-01: mock HuggingFaceEmbedder.__init__ + CrossEncoderReranker.__init__.

    Minimal instance attributes provided:
      HuggingFaceEmbedder:
        self._model  — MagicMock; .encode() returns list-of-list for embed_batch
        self._device — "cpu"

      CrossEncoderReranker:
        self._model  — MagicMock; .predict() returns list for rerank

    autouse=True at tests/integration/ scope — fires for all integration tests.
    Unit tests under tests/unit/ are unaffected (different conftest tree).
    """
    from services.vectorizer import embedder as _embedder_mod
    from services.retriever import retriever as _retriever_mod

    def _noop_embedder_init(self: object, *args: object, **kwargs: object) -> None:
        mock_model = MagicMock()
        mock_model.encode.return_value = [[0.1] * 1024]
        self._model = mock_model  # type: ignore[attr-defined]
        self._device = "cpu"  # type: ignore[attr-defined]

    def _noop_reranker_init(self: object, *args: object, **kwargs: object) -> None:
        mock_model = MagicMock()
        mock_model.predict.return_value = [0.5]
        self._model = mock_model  # type: ignore[attr-defined]
        self._device = "cpu"  # type: ignore[attr-defined]

    with (
        patch.object(_embedder_mod.HuggingFaceEmbedder, "__init__", _noop_embedder_init),
        patch.object(_retriever_mod.CrossEncoderReranker, "__init__", _noop_reranker_init),
    ):
        yield
