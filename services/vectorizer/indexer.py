# =============================================================================
# services/vectorizer/indexer.py
# STAGE 4 — 向量化存储入口（Embed + BM25 Index + Upsert）
# =============================================================================
from __future__ import annotations
import time
from loguru import logger
import asyncpg

from config.settings import settings
from utils.models import DocumentChunk, VectorizeResult
from utils.logger import log_latency
from services.vectorizer.embedder import get_embedder
from services.vectorizer.vector_store import get_vector_store


# ── BM25 内存索引（生产可替换 Elasticsearch）─────────────────────────────────
class BM25Index:
    """进程内 BM25 稀疏索引。"""

    def __init__(self) -> None:
        self._corpus: list[str] = []
        self._ids: list[str] = []
        self._model = None

    def build(self, texts: list[str], ids: list[str]) -> None:
        try:
            from rank_bm25 import BM25Okapi
            self._corpus = texts
            self._ids = ids
            self._model = BM25Okapi([t.lower().split() for t in texts])
            logger.info(f"BM25 index built: {len(texts)} docs")
        except ImportError:
            logger.warning("rank-bm25 not installed — BM25 retrieval disabled")

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        if self._model is None:
            return []
        scores = self._model.get_scores(query.lower().split())
        top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [(self._ids[i], float(scores[i])) for i in top_idx if scores[i] > 0]

    def add(self, texts: list[str], ids: list[str]) -> None:
        """增量追加（重建索引）。"""
        self.build(self._corpus + texts, self._ids + ids)


_bm25_index = BM25Index()


def get_bm25_index() -> BM25Index:
    return _bm25_index


# ══════════════════════════════════════════════════════════════════════════════
# VectorizerService
# ══════════════════════════════════════════════════════════════════════════════
class VectorizerService:
    """
    STAGE 4 入口：
    DocumentChunk 列表 → 批量嵌入 → BM25 增量索引 → 向量存储 upsert
    """

    def __init__(self) -> None:
        self._embedder = get_embedder()
        self._store = get_vector_store()
        self._bm25 = get_bm25_index()

    async def ensure_collection(self) -> None:
        """公开接口：确保向量 collection 已创建（替代直接访问 _store）。"""
        await self._store.create_collection()

    @property
    def embedder(self):
        """公开访问 embedder（供 summary_indexer 等复用）。"""
        return self._embedder

    @property
    def vector_store(self):
        """公开访问 vector_store（供 summary_indexer 等复用）。"""
        return self._store

    @log_latency
    async def vectorize_and_store(
        self,
        chunks: list[DocumentChunk],
        doc_id: str,
    ) -> VectorizeResult:
        """
        父子块策略时，chunks 中同时包含 child（chunk_level="child"）
        和 parent（chunk_level="parent"）两种块。
        - child 块：嵌入 + BM25 + 存入主 collection（用于检索）
        - parent 块：仅存入父块 collection，不嵌入，不进 BM25
          （检索后通过 parent_chunk_id 查找，直接取 content 送给 LLM）
        """
        start = time.perf_counter()
        logger.info(f"[Vectorize] START doc_id={doc_id} chunks={len(chunks)}")

        if not chunks:
            return VectorizeResult(
                doc_id=doc_id,
                total_chunks=0,
                embedded_chunks=0,
                vector_store=settings.vector_store,
                collection=settings.qdrant_collection,
            )

        # ── 分离子块和父块 ────────────────────────────────────────────────────
        parent_chunks = [c for c in chunks if c.metadata.chunk_level == "parent"]
        child_chunks  = [c for c in chunks if c.metadata.chunk_level != "parent"]

        # ── 1. 嵌入子块（用带上下文头的内容，语义质量更高）─────────────────────
        texts_to_embed = [
            c.content_with_header if c.content_with_header else c.content
            for c in child_chunks
        ]
        embeddings = await self._embedder.embed_batch(texts_to_embed)
        for chunk, emb in zip(child_chunks, embeddings):
            chunk.embedding = emb

        # ── 2. BM25 增量索引（只索引子块，父块不参与关键词检索）────────────────
        if settings.sparse_enabled and child_chunks:
            self._bm25.add(
                texts=[c.content for c in child_chunks],
                ids=[c.chunk_id for c in child_chunks],
            )

        # ── 3. 子块存入主 collection ────────────────────────────────────────────
        await self._store.upsert(child_chunks)

        # ── 4. 父块存入独立 collection（无需嵌入，只存 payload）──────────────────
        if parent_chunks:
            parent_col = (
                getattr(settings, "qdrant_parent_collection", "") or
                settings.qdrant_collection + "_parent"
            )
            try:
                await self._store.upsert_parent_chunks(parent_chunks, parent_col)
                logger.info(
                    f"[Vectorize] parent chunks stored: "
                    f"count={len(parent_chunks)} collection={parent_col}"
                )
            except asyncpg.PostgresError as exc:
                logger.warning(
                    "[Vectorize] parent upsert failed (non-fatal)",
                    tenant_id="",
                    chunk_count=len(parent_chunks),
                    exc_info=exc,
                )

        elapsed_ms = (time.perf_counter() - start) * 1000
        result = VectorizeResult(
            doc_id=doc_id,
            total_chunks=len(child_chunks),
            embedded_chunks=len(child_chunks),
            vector_store=settings.vector_store,
            collection=settings.qdrant_collection,
            elapsed_ms=round(elapsed_ms, 1),
        )
        logger.info(
            f"[Vectorize] DONE doc_id={doc_id} "
            f"child={len(child_chunks)} parent={len(parent_chunks)} "
            f"store={settings.vector_store} elapsed={elapsed_ms:.0f}ms"
        )
        return result


_vectorizer: VectorizerService | None = None


def get_vectorizer() -> VectorizerService:
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = VectorizerService()
    return _vectorizer
