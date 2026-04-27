# =============================================================================
# tests/unit/test_retriever.py
# 单元测试 — STAGE 5 检索（RRF 融合 + 忠实度评估）
# =============================================================================
import pytest
from services.retriever.retriever import rrf_fusion, _to_retrieved_chunk
from services.generator.generator import estimate_faithfulness
from services.vectorizer.vector_store import VectorSearchResult
from utils.models import RetrievedChunk, ChunkMetadata, DocType


# ══════════════════════════════════════════════════════════════════════════════
# RRF Fusion
# ══════════════════════════════════════════════════════════════════════════════
class TestRRFFusion:

    def test_single_list_preserves_order(self) -> None:
        ranked = [("A", 0.9), ("B", 0.8), ("C", 0.7)]
        result = rrf_fusion([ranked])
        ids = [r[0] for r in result]
        assert ids == ["A", "B", "C"]

    def test_two_lists_boosts_common_items(self) -> None:
        list1 = [("A", 0.9), ("B", 0.8), ("C", 0.7)]
        list2 = [("B", 0.95), ("D", 0.85), ("A", 0.6)]
        result = rrf_fusion([list1, list2])
        # A and B appear in both lists → both should occupy the top 2 positions
        top2 = {r[0] for r in result[:2]}
        assert top2 == {"A", "B"}

    def test_empty_lists(self) -> None:
        result = rrf_fusion([[], []])
        assert result == []

    def test_scores_are_positive(self) -> None:
        ranked = [("X", 1.0), ("Y", 0.5)]
        result = rrf_fusion([ranked])
        for _, score in result:
            assert score > 0

    def test_k_parameter_affects_score(self) -> None:
        ranked = [("A", 1.0)]
        score_k60 = rrf_fusion([ranked], k=60)[0][1]
        score_k1 = rrf_fusion([ranked], k=1)[0][1]
        # 较小的k应该产生更高分数
        assert score_k1 > score_k60

    def test_deduplicates_across_lists(self) -> None:
        list1 = [("A", 0.9), ("B", 0.8)]
        list2 = [("A", 0.95), ("C", 0.7)]
        result = rrf_fusion([list1, list2])
        ids = [r[0] for r in result]
        assert len(ids) == len(set(ids)), "结果中不应有重复 chunk_id"


# ══════════════════════════════════════════════════════════════════════════════
# Faithfulness Estimation
# ══════════════════════════════════════════════════════════════════════════════
def _make_chunk(content: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="test_001",
        doc_id="doc_001",
        content=content,
        metadata=ChunkMetadata(
            source="/mnt/f/test.pdf",
            doc_id="doc_001",
            doc_type=DocType.PDF,
        ),
    )


class TestFaithfulness:

    @pytest.mark.asyncio
    async def test_answer_matching_context_high_score(self) -> None:
        chunk = _make_chunk("企业RAG系统支持PDF文档解析和向量化存储功能。")
        answer = "企业RAG系统支持PDF文档解析和向量化存储。"
        score = await estimate_faithfulness(answer, [chunk])
        assert score >= 0.5

    @pytest.mark.asyncio
    async def test_unrelated_answer_lower_score(self) -> None:
        chunk = _make_chunk("苹果公司发布了最新款iPhone产品。")
        answer = "量子计算机将改变未来的密码学体系。"
        score = await estimate_faithfulness(answer, [chunk])
        # 不相关答案分数应相对低
        assert score < 0.8

    @pytest.mark.asyncio
    async def test_empty_answer_returns_zero(self) -> None:
        chunk = _make_chunk("任意上下文内容。")
        score = await estimate_faithfulness("", [chunk])
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_zero(self) -> None:
        score = await estimate_faithfulness("有内容的回答", [])
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_between_0_and_1(self) -> None:
        chunk = _make_chunk("测试内容用于验证分数范围的正确性。")
        score = await estimate_faithfulness("测试回答内容", [chunk])
        assert 0.0 <= score <= 1.0


def _make_vector_search_result(metadata: dict) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id="chunk_img_001",
        doc_id="doc_001",
        content="caption text",
        metadata=metadata,
        score=0.95,
    )


# ══════════════════════════════════════════════════════════════════════════════
# _to_retrieved_chunk — image field round-trip (IMG-03)
# ══════════════════════════════════════════════════════════════════════════════
class TestToRetrievedChunkImageFields:

    def test_image_chunk_fields_round_trip(self) -> None:
        r = _make_vector_search_result({
            "chunk_type": "image",
            "image_b64": "abc123base64==",
            "doc_type": "pdf",
            "language": "en",
        })
        chunk = _to_retrieved_chunk(r)
        assert chunk.metadata.chunk_type == "image"
        assert chunk.metadata.image_b64 == "abc123base64=="

    def test_text_chunk_defaults_unchanged(self) -> None:
        r = _make_vector_search_result({"doc_type": "pdf", "language": "en"})
        chunk = _to_retrieved_chunk(r)
        assert chunk.metadata.chunk_type == "text"
        assert chunk.metadata.image_b64 == ""

    def test_unknown_doc_type_does_not_raise(self) -> None:
        r = _make_vector_search_result({"doc_type": "jpeg", "language": "en"})
        chunk = _to_retrieved_chunk(r)
        assert chunk.metadata.doc_type == DocType.UNKNOWN
