"""tests/unit/test_retriever_helpers.py — Phase 15 backfill.

Existing tests/unit/test_retriever.py covers HybridRetrieverService partial
flows. This file adds: rrf_fusion / adaptive_rrf_fusion math, _cosine_similarity,
_safe_doc_type fallback, _to_retrieved_chunk conversion, _get_intent_config
mapping, and PassthroughReranker passthrough behavior.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest


@pytest.mark.unit
def test_rrf_fusion_combines_ranked_lists():
    from services.retriever.retriever import rrf_fusion
    out = rrf_fusion([
        [("a", 1.0), ("b", 0.5)],
        [("b", 0.9), ("a", 0.1)],
    ])
    chunk_ids = [cid for cid, _ in out]
    assert "a" in chunk_ids
    assert "b" in chunk_ids
    assert chunk_ids[0] in {"a", "b"}


@pytest.mark.unit
def test_rrf_fusion_handles_single_list():
    from services.retriever.retriever import rrf_fusion
    out = rrf_fusion([[("a", 1.0)]])
    assert out[0][0] == "a"


@pytest.mark.unit
def test_adaptive_rrf_fusion_empty_returns_empty():
    """Edge path: no input lists → empty result."""
    from services.retriever.retriever import adaptive_rrf_fusion
    assert adaptive_rrf_fusion([]) == []


@pytest.mark.unit
def test_adaptive_rrf_fusion_uses_provided_weights():
    from services.retriever.retriever import adaptive_rrf_fusion
    out = adaptive_rrf_fusion(
        [
            [("a", 1.0)],
            [("b", 1.0)],
        ],
        weights=[0.9, 0.1],
    )
    assert out[0][0] == "a"


@pytest.mark.unit
def test_adaptive_rrf_fusion_auto_quality_weights():
    """Auto-weight branch: high-scored list dominates fusion."""
    from services.retriever.retriever import adaptive_rrf_fusion
    out = adaptive_rrf_fusion(
        [
            [("a", 0.9), ("c", 0.8), ("d", 0.7)],
            [("b", 0.05)],
        ],
    )
    assert out[0][0] == "a"


@pytest.mark.unit
def test_cosine_similarity_orthogonal_vectors():
    from services.retriever.retriever import _cosine_similarity
    assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9


@pytest.mark.unit
def test_cosine_similarity_identical_vectors():
    from services.retriever.retriever import _cosine_similarity
    assert abs(_cosine_similarity([1.0, 1.0], [1.0, 1.0]) - 1.0) < 1e-9


@pytest.mark.unit
def test_cosine_similarity_zero_vector_returns_zero():
    """Edge path: zero-magnitude vector → 0.0 (no division-by-zero crash)."""
    from services.retriever.retriever import _cosine_similarity
    assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


@pytest.mark.unit
def test_safe_doc_type_known_value():
    from services.retriever.retriever import _safe_doc_type
    from utils.models import DocType
    assert _safe_doc_type("pdf") == DocType.PDF


@pytest.mark.unit
def test_safe_doc_type_unknown_falls_back():
    """Error path: invalid doc_type string → DocType.UNKNOWN."""
    from services.retriever.retriever import _safe_doc_type
    from utils.models import DocType
    assert _safe_doc_type("not-a-real-type") == DocType.UNKNOWN
    assert _safe_doc_type("") == DocType.UNKNOWN


@pytest.mark.unit
def test_to_retrieved_chunk_converts_metadata():
    from services.retriever.retriever import _to_retrieved_chunk
    from services.vectorizer.vector_store import VectorSearchResult
    vsr = VectorSearchResult(
        chunk_id="c1", doc_id="d1", content="hello",
        metadata={"title": "T", "section": "S", "source": "/p", "doc_type": "pdf"},
        score=0.85,
    )
    chunk = _to_retrieved_chunk(vsr, method="dense")
    assert chunk.chunk_id == "c1"
    assert chunk.dense_score == 0.85
    assert chunk.retrieval_method == "dense"


@pytest.mark.unit
def test_get_intent_config_returns_tuple():
    from services.retriever.retriever import _get_intent_config
    out = _get_intent_config("factual")
    assert isinstance(out, tuple)
    assert len(out) == 3
    assert isinstance(out[0], str)


@pytest.mark.unit
def test_get_intent_config_unknown_intent():
    """Edge path: unknown intent → returns default tuple, no crash."""
    from services.retriever.retriever import _get_intent_config
    out = _get_intent_config(None)
    assert isinstance(out, tuple)
    assert len(out) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_passthrough_reranker_returns_top_k_unchanged():
    from services.retriever.retriever import PassthroughReranker
    from utils.models import ChunkMetadata, RetrievedChunk
    candidates = [
        RetrievedChunk(
            chunk_id=f"c{i}", doc_id=f"d{i}", content=f"text {i}",
            metadata=ChunkMetadata(), final_score=1.0 - i * 0.1,
        )
        for i in range(5)
    ]
    out = await PassthroughReranker().rerank("q", candidates, top_k=3)
    assert len(out) == 3
    assert out[0].chunk_id == "c0"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_passthrough_reranker_empty_candidates():
    """Error/edge path: empty candidates → empty result."""
    from services.retriever.retriever import PassthroughReranker
    out = await PassthroughReranker().rerank("q", [], top_k=5)
    assert out == []
