"""TEST-08 canary — opt-out of autouse mock loads real bge-m3 + bge-m3-rerank.

Marker ``@pytest.mark.real_embedder`` triggers the early-return in
``tests/integration/conftest.py::_mock_local_model_inits`` (D-OPTOUT-01),
exposing the real ``HuggingFaceEmbedder.__init__`` +
``CrossEncoderReranker.__init__`` paths.

Default CI: skipped via ``pytest.mark.skipif`` when bge-m3 / bge-m3-rerank
files are absent at ``$APP_MODEL_DIR``. Skip status is mandatory (Assumption
A6, D-VERIFY-02) — without it a raised ``FileNotFoundError`` would dirty the
integration error count.

Run with:

    uv run pytest tests/integration/test_real_embedder_canary.py -m real_embedder
"""
from __future__ import annotations

import pytest

from config.settings import resolve_embedding_model_path


def _models_present() -> bool:
    """Return True iff both bge-m3 + bge-m3-rerank resolve to existing dirs."""
    return (
        resolve_embedding_model_path("bge-m3").exists()
        and resolve_embedding_model_path("bge-m3-rerank").exists()
    )


pytestmark = [
    pytest.mark.integration,
    pytest.mark.real_embedder,
    pytest.mark.skipif(
        not _models_present(),
        reason="bge-m3 / bge-m3-rerank not present at $APP_MODEL_DIR; see docs/RUNBOOK.md test infra section",
    ),
]


async def test_real_embedder_models_load_and_encode() -> None:
    """Smoke-load bge-m3 + bge-m3-rerank and verify embedding/score shapes.

    Lazy imports inside the test body defer module-level side-effects past
    the skip-check so collection stays clean on hosts without model files.
    """
    from services.retriever.retriever import CrossEncoderReranker
    from services.vectorizer.embedder import HuggingFaceEmbedder

    embedder = HuggingFaceEmbedder()
    vectors = await embedder.embed_batch(["hello"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024  # bge-m3 native dim

    reranker = CrossEncoderReranker()
    scores = reranker._model.predict([("q", "d")])
    assert len(scores) == 1
    assert isinstance(float(scores[0]), float)
