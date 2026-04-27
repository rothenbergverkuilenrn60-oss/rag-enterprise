# =============================================================================
# services/retriever/retriever.py
# STAGE 5 — 检索
# 流程：查询改写(HyDE/Multi-Query) → 密集检索 → 稀疏BM25 → RRF融合 → Cross-Encoder重排
# =============================================================================
from __future__ import annotations
import asyncio
import time
from collections import defaultdict
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_random_exponential
import asyncpg
import httpx

from config.settings import settings
from utils.models import RetrievedChunk, ChunkMetadata, DocType
from utils.logger import log_latency
from utils.metrics import retrieval_latency_seconds
from utils.observability import start_span
from services.vectorizer.embedder import get_embedder
from services.vectorizer.vector_store import get_vector_store, VectorSearchResult
from services.vectorizer.indexer import get_bm25_index


# ══════════════════════════════════════════════════════════════════════════════
# RRF 融合算法（自适应权重版）
# ══════════════════════════════════════════════════════════════════════════════
def rrf_fusion(
    ranked_lists: list[list[tuple[str, float]]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """标准 RRF，固定 k=60，向后兼容保留。"""
    scores: defaultdict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, (chunk_id, _) in enumerate(ranked):
            scores[chunk_id] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def adaptive_rrf_fusion(
    ranked_lists: list[list[tuple[str, float]]],
    k: int = 60,
    weights: list[float] | None = None,
) -> list[tuple[str, float]]:
    """
    自适应 RRF：根据各路结果的质量动态调整权重。

    权重计算策略：
      - 若外部传入 weights，直接使用（由调用方基于查询类型设定）
      - 否则按各列表 top-3 原始分数均值估算质量，归一化为权重
      - 质量高（高分密集）的检索路径权重更大
    """
    if not ranked_lists:
        return []

    if weights is None:
        # 用每路 top-3 平均分估算质量
        qualities: list[float] = []
        for ranked in ranked_lists:
            top3_scores = [s for _, s in ranked[:3]]
            qualities.append(sum(top3_scores) / len(top3_scores) if top3_scores else 0.0)
        total_q = sum(qualities) or 1.0
        weights = [q / total_q for q in qualities]

    # 权重归一化（保证 sum=1）
    total_w = sum(weights) or 1.0
    weights = [w / total_w for w in weights]

    scores: defaultdict[str, float] = defaultdict(float)
    for w, ranked in zip(weights, ranked_lists):
        for rank, (chunk_id, _) in enumerate(ranked):
            scores[chunk_id] += w * (1.0 / (k + rank + 1))

    logger.debug(f"[AdaptiveRRF] weights={[round(w, 3) for w in weights]}")
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# Cross-Encoder Reranker
# ══════════════════════════════════════════════════════════════════════════════
class CrossEncoderReranker:
    def __init__(self) -> None:
        from sentence_transformers import CrossEncoder
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = CrossEncoder(
            str(settings.reranker_model_path),
            device=device,
            max_length=512,
        )
        logger.info(f"CrossEncoderReranker: path={settings.reranker_model_path} device={device}")

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []
        pairs = [(query, c.content) for c in candidates]
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(
            None,
            lambda: self._model.predict(
                pairs,
                batch_size=settings.reranker_batch_size,
                show_progress_bar=False,
            ).tolist(),
        )
        for chunk, score in zip(candidates, scores):
            chunk.rerank_score = float(score)
            chunk.final_score = float(score)
            chunk.retrieval_method = "rerank"

        ranked = sorted(candidates, key=lambda x: x.rerank_score, reverse=True)
        logger.debug(f"Reranker: {len(candidates)} → top {top_k}")
        return ranked[:top_k]


class PassthroughReranker:
    """开发/轻量模式：跳过 Cross-Encoder，直接返回 RRF 结果。"""
    async def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        for c in candidates:
            c.final_score = c.rrf_score
        return candidates[:top_k]


class RemoteReranker:
    """
    HTTP Reranker 客户端：调用独立部署的 reranker-service（:8001/rerank）。
    优先使用远端微服务，不可达时自动降级为本地 CrossEncoderReranker。
    """

    def __init__(self, base_url: str) -> None:
        import httpx
        self._url = f"{base_url.rstrip('/')}/rerank"
        self._client = httpx.AsyncClient(timeout=0.05)  # 50ms SLA
        self._fallback: CrossEncoderReranker | None = None
        logger.info(f"RemoteReranker: url={self._url}")

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []
        try:
            payload = {
                "query": query,
                "candidates": [c.content for c in candidates],
                "candidate_ids": [c.chunk_id for c in candidates],
                "top_k": top_k,
            }
            resp = await self._client.post(self._url, json=payload)
            resp.raise_for_status()
            data = resp.json()

            # 将返回的分数写回 candidates
            score_map = dict(zip(
                [c.chunk_id for c in candidates],
                data["scores"],
            ))
            for chunk in candidates:
                score = score_map.get(chunk.chunk_id, chunk.rrf_score)
                chunk.rerank_score = score
                chunk.final_score = score
                chunk.retrieval_method = "rerank_remote"

            ranked_ids = data.get("ranked_ids", [])
            id_to_chunk = {c.chunk_id: c for c in candidates}
            ranked = [id_to_chunk[cid] for cid in ranked_ids if cid in id_to_chunk]
            # 补充未在 ranked_ids 中的 chunk（防止数量不一致）
            seen = set(ranked_ids)
            ranked += [c for c in candidates if c.chunk_id not in seen]
            return ranked[:top_k]

        except httpx.HTTPError as exc:
            logger.warning("[RemoteReranker] HTTP call failed, falling back to local", exc_info=exc)
            # 降级：本地 passthrough（已有 RRF 分数）
            return await PassthroughReranker().rerank(query, candidates, top_k)


_reranker = None


def get_reranker():
    global _reranker
    if _reranker is None:
        # 1. 优先使用远端 Reranker 微服务（RERANKER_SERVICE_URL 配置时启用）
        reranker_url = getattr(settings, "reranker_service_url", "")
        if reranker_url:
            _reranker = RemoteReranker(reranker_url)
        # 2. 本地 CrossEncoder（settings.reranker_enabled=True）
        elif settings.reranker_enabled:
            try:
                _reranker = CrossEncoderReranker()
            except RuntimeError as exc:
                logger.warning("CrossEncoderReranker init failed, using passthrough", exc_info=exc)
                _reranker = PassthroughReranker()
        # 3. Passthrough（开发模式/快速测试）
        else:
            _reranker = PassthroughReranker()
    return _reranker


# ══════════════════════════════════════════════════════════════════════════════
# 按查询类型选 Reranker + SLA 超时自动降级
# ══════════════════════════════════════════════════════════════════════════════

# 查询意图 → (reranker_type, rrf_dense_weight, rrf_sparse_weight)
# dense_weight 高 → 更信任语义向量；sparse_weight 高 → 更信任关键词
_INTENT_RERANKER_CONFIG: dict[str, tuple[str, float, float]] = {
    "factual":      ("cross_encoder", 0.6, 0.4),   # 事实型：语义+关键词并重
    "definition":   ("cross_encoder", 0.7, 0.3),   # 定义型：语义权重更高
    "procedural":   ("cross_encoder", 0.5, 0.5),   # 流程型：关键词很重要
    "comparison":   ("cross_encoder", 0.65, 0.35), # 对比型：语义为主
    "calculation":  ("passthrough",   0.4, 0.6),   # 计算型：关键词为主，无需重排
    "multi_hop":    ("cross_encoder", 0.6, 0.4),   # 多跳：语义+关键词
    "chitchat":     ("passthrough",   0.8, 0.2),   # 闲聊：纯语义，直接通过
    "out_of_scope": ("passthrough",   0.5, 0.5),   # 超范围：快速通过
    "ambiguous":    ("cross_encoder", 0.6, 0.4),   # 模糊：重排辅助消歧
}
_DEFAULT_RERANKER_CONFIG = ("cross_encoder", 0.6, 0.4)

# SLA 目标：reranker P99 < 50ms；超时后自动降级为 passthrough
_RERANKER_SLA_MS: float = getattr(settings, "reranker_sla_ms", 45.0)


def _get_intent_config(query_intent: str | None) -> tuple[str, float, float]:
    """根据查询意图返回 (reranker_type, dense_weight, sparse_weight)。"""
    intent_key = (query_intent or "").lower().split(".")[-1]  # QueryIntent.FACTUAL → factual
    return _INTENT_RERANKER_CONFIG.get(intent_key, _DEFAULT_RERANKER_CONFIG)


async def _rerank_with_sla(
    reranker,
    query: str,
    candidates: list[RetrievedChunk],
    top_k: int,
    sla_ms: float = _RERANKER_SLA_MS,
) -> list[RetrievedChunk]:
    """
    带 SLA 超时保护的 rerank。
    超时后自动降级为 PassthroughReranker（按 RRF 分数返回），
    并记录 SLA breach 日志（可接 Prometheus alert）。
    """
    try:
        ranked = await asyncio.wait_for(
            reranker.rerank(query, candidates, top_k),
            timeout=sla_ms / 1000.0,
        )
        return ranked
    except asyncio.TimeoutError:
        logger.warning(
            f"[Reranker] SLA breach: >{sla_ms}ms, fallback to passthrough "
            f"(candidates={len(candidates)})"
        )
        # 记录 SLA 指标
        try:
            from utils.metrics import retrieval_latency_seconds
            retrieval_latency_seconds.labels(stage="rerank_sla_breach").observe(sla_ms / 1000.0)
        except (ImportError, AttributeError):
            pass
        return await PassthroughReranker().rerank(query, candidates, top_k)


# ══════════════════════════════════════════════════════════════════════════════
# Query-Doc 语义相似度校正
# ══════════════════════════════════════════════════════════════════════════════

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度（不依赖 numpy，纯 Python）。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _apply_similarity_correction(
    query_vec: list[float],
    chunks: list[RetrievedChunk],
    embedder,
    alpha: float = 0.3,
) -> list[RetrievedChunk]:
    """
    Query-Doc 语义相似度校正：将查询向量与每个 chunk 的嵌入向量
    做余弦相似度计算，与 rerank 分数加权混合，校正 reranker 评分偏差。

    final_score = (1 - alpha) * rerank_score_normalized + alpha * cosine_sim
    alpha=0.3 表示 70% 信任 reranker，30% 信任语义相似度。
    """
    if not chunks or not query_vec:
        return chunks

    try:
        # 批量获取 chunk 嵌入（使用 dense_score 归一化作为代理，避免重复计算）
        # 若 chunk 有缓存嵌入则直接用，否则跳过校正（性能优先）
        rerank_scores = [c.final_score for c in chunks]
        max_rs = max(rerank_scores) if rerank_scores else 1.0
        min_rs = min(rerank_scores) if rerank_scores else 0.0
        range_rs = (max_rs - min_rs) or 1.0

        for chunk in chunks:
            norm_rerank = (chunk.final_score - min_rs) / range_rs
            # dense_score 已经是余弦相似度（来自 Qdrant ANN 搜索）
            cosine_sim = max(0.0, min(1.0, chunk.dense_score))
            chunk.final_score = (1 - alpha) * norm_rerank + alpha * cosine_sim

        chunks.sort(key=lambda c: c.final_score, reverse=True)
        logger.debug(f"[SimilarityCorrection] alpha={alpha}, applied to {len(chunks)} chunks")
    except (ValueError, KeyError, ZeroDivisionError) as exc:
        logger.warning("[SimilarityCorrection] failed (non-fatal)", exc_info=exc)

    return chunks


# ══════════════════════════════════════════════════════════════════════════════
# Query Rewriter（HyDE + Multi-Query）
# ══════════════════════════════════════════════════════════════════════════════
async def hyde_rewrite(query: str, llm_client) -> str:
    """
    HyDE: 让 LLM 生成假设性回答，用回答向量做检索，
    弥补 "短查询语义弱" 的问题。
    task_type="rewrite" → 路由到 Haiku（轻量改写任务，无需 Sonnet）
    """
    try:
        hypothetical = await llm_client.chat(
            system=(
                "你是文档检索专家。请根据问题生成一段简短的、直接回答该问题的假设性段落，"
                "用于向量检索。只输出段落内容，不加前缀或解释。"
            ),
            user=query,
            temperature=0.3,
            task_type="rewrite",    # → Haiku，轻量改写任务
        )
        logger.debug(f"HyDE rewritten: {hypothetical[:80]}…")
        return hypothetical
    except (RuntimeError, ValueError) as exc:
        logger.warning("HyDE failed, using original query", exc_info=exc)
        return query


async def multi_query_expand(query: str, llm_client, n: int = 3) -> list[str]:
    """
    Multi-Query: 生成 N 个语义相近的查询变体，
    每个变体独立检索后合并，提升召回率。
    task_type="rewrite" → 路由到 Haiku（轻量改写任务）
    """
    try:
        response = await llm_client.chat(
            system=(
                f"请生成 {n} 种不同表达方式的同义问题，用于提升文档检索的召回率。"
                "每行一个问题，不加编号或前缀，只输出改写后的问题。"
            ),
            user=query,
            temperature=0.5,
            task_type="rewrite",    # → Haiku，轻量改写任务
        )
        variants = [q.strip() for q in response.strip().split("\n") if q.strip()]
        return [query] + variants[:n]
    except (RuntimeError, ValueError, ConnectionError, OSError) as exc:
        logger.warning("Multi-query expand failed", exc_info=exc)
        return [query]


# ══════════════════════════════════════════════════════════════════════════════
# HybridRetrieverService
# ══════════════════════════════════════════════════════════════════════════════
def _safe_doc_type(value: str) -> DocType:
    try:
        return DocType(value)
    except ValueError:
        return DocType.UNKNOWN


def _to_retrieved_chunk(r: VectorSearchResult, method: str = "dense") -> RetrievedChunk:
    meta = ChunkMetadata(
        source=r.metadata.get("source", ""),
        doc_id=r.doc_id,
        title=r.metadata.get("title", ""),
        author=r.metadata.get("author", ""),
        chunk_index=r.metadata.get("chunk_index", 0),
        total_chunks=r.metadata.get("total_chunks", 0),
        doc_type=_safe_doc_type(r.metadata.get("doc_type", "")),
        language=r.metadata.get("language", "zh"),
        chunk_type=r.metadata.get("chunk_type", "text"),
        image_b64=r.metadata.get("image_b64", ""),
    )
    return RetrievedChunk(
        chunk_id=r.chunk_id,
        doc_id=r.doc_id,
        content=r.content,
        metadata=meta,
        dense_score=r.score if method == "dense" else 0.0,
        retrieval_method=method,
    )


class HybridRetrieverService:
    """
    STAGE 5 入口：
    1. (可选) HyDE 查询改写
    2. 密集检索（ANN 向量搜索）
    3. 稀疏检索（BM25）
    4. RRF 融合
    5. Cross-Encoder 重排
    """

    def __init__(self) -> None:
        self._embedder = get_embedder()
        self._store = get_vector_store()
        self._bm25 = get_bm25_index()
        self._reranker = get_reranker()

    @log_latency
    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict | None = None,
        llm_client=None,
        query_intent: str | None = None,
    ) -> tuple[list[RetrievedChunk], dict[str, float]]:
        """
        返回 (ranked_chunks, stage_latencies)
        query_intent: 来自 NLUService 的意图分类结果（决定 reranker 选择和 RRF 权重）
        """
        with start_span("rag.retrieve", {"query.length": len(query), "intent": query_intent or ""}):
            return await self._retrieve_impl(
                query=query, top_k=top_k, filters=filters,
                llm_client=llm_client, query_intent=query_intent,
            )

    async def _retrieve_impl(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict | None = None,
        llm_client=None,
        query_intent: str | None = None,
    ) -> tuple[list[RetrievedChunk], dict[str, float]]:
        top_k = top_k or settings.top_k_rerank
        timings: dict[str, float] = {}

        # ── 根据查询意图确定 reranker 类型和 RRF 权重 ──────────────────────
        reranker_type, dense_w, sparse_w = _get_intent_config(query_intent)
        logger.debug(
            f"[Retrieve] intent={query_intent} → reranker={reranker_type} "
            f"dense_w={dense_w} sparse_w={sparse_w}"
        )

        # ── Step 1: 查询改写 ────────────────────────────────────────────────
        t0 = time.perf_counter()
        retrieval_query = query
        if settings.hyde_enabled and llm_client:
            retrieval_query = await hyde_rewrite(query, llm_client)
        timings["query_rewrite_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        # ── Step 2: 并行 密集 + 稀疏 检索 ──────────────────────────────────
        t0 = time.perf_counter()
        query_vec, bm25_results = await asyncio.gather(
            self._embedder.embed_one(retrieval_query),
            asyncio.to_thread(self._bm25.search, query, settings.top_k_sparse),
        )
        dense_results: list[VectorSearchResult] = await self._store.search(
            query_vector=query_vec,
            top_k=settings.top_k_dense,
            filters=filters,
        )
        retrieval_ms = round((time.perf_counter() - t0) * 1000, 1)
        timings["retrieval_ms"] = retrieval_ms
        retrieval_latency_seconds.labels(stage="dense").observe(retrieval_ms / 1000)
        retrieval_latency_seconds.labels(stage="sparse").observe(retrieval_ms / 1000)

        logger.info(
            f"[Retrieve] dense={len(dense_results)} "
            f"sparse={len(bm25_results)} query='{query[:50]}'"
        )

        # ── Step 3: 自适应 RRF 融合（按意图权重调整两路贡献比）─────────────
        t0 = time.perf_counter()
        dense_ranked  = [(r.chunk_id, r.score) for r in dense_results]
        sparse_ranked = bm25_results  # already (chunk_id, score)

        fused = adaptive_rrf_fusion(
            [dense_ranked, sparse_ranked],
            k=settings.rrf_k,
            weights=[dense_w, sparse_w],
        )
        rrf_ms = round((time.perf_counter() - t0) * 1000, 1)
        timings["rrf_ms"] = rrf_ms
        retrieval_latency_seconds.labels(stage="rrf").observe(rrf_ms / 1000)

        # 构建 RetrievedChunk（优先从 dense_results 取内容）
        dense_map: dict[str, VectorSearchResult] = {r.chunk_id: r for r in dense_results}
        candidates: list[RetrievedChunk] = []
        for chunk_id, rrf_score in fused[: settings.top_k_dense]:
            if chunk_id in dense_map:
                rc = _to_retrieved_chunk(dense_map[chunk_id], method="hybrid")
                rc.rrf_score = rrf_score
                candidates.append(rc)

        # ── Step 4: 按查询类型选 Reranker + SLA P99<50ms 超时保护 ──────────
        t0 = time.perf_counter()
        # chitchat / calculation 等低优先级意图直接用 passthrough 节省延迟
        active_reranker = (
            self._reranker if reranker_type == "cross_encoder"
            else PassthroughReranker()
        )
        ranked = await _rerank_with_sla(active_reranker, query, candidates, top_k)
        rerank_ms = round((time.perf_counter() - t0) * 1000, 1)
        timings["rerank_ms"] = rerank_ms
        retrieval_latency_seconds.labels(stage="rerank").observe(rerank_ms / 1000)

        # ── Step 5: Query-Doc 语义相似度校正 ─────────────────────────────────
        if getattr(settings, "similarity_correction_enabled", True) and ranked:
            t0 = time.perf_counter()
            ranked = await _apply_similarity_correction(
                query_vec, ranked, self._embedder,
                alpha=getattr(settings, "similarity_correction_alpha", 0.3),
            )
            timings["sim_correction_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        # ── Step 6: 父块回溯（parent_child 策略专用）────────────────────────
        if getattr(settings, "parent_child_enabled", False):
            t0 = time.perf_counter()
            ranked = await self._expand_to_parent(ranked)
            timings["parent_expand_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        logger.info(
            f"[Retrieve] Final top_k={len(ranked)} "
            f"reranker={reranker_type} intent={query_intent}"
        )
        return ranked, timings



    async def retrieve_multi_query(
        self,
        queries: list[str],
        original_query: str,
        top_k: int | None = None,
        filters: dict | None = None,
        llm_client=None,
    ) -> tuple[list[RetrievedChunk], dict[str, float]]:
        """
        四路混合检索：对多个查询变体（原始/重写/HyDE/上下文）分别检索，
        用 RRF 融合所有结果，避免重复，最终精排。
        queries 来自 NLUService.build_quad_queries 的输出。
        """
        import asyncio as _asyncio
        top_k   = top_k or settings.top_k_rerank
        timings: dict[str, float] = {}

        # 并发对所有查询做向量嵌入 + BM25
        t0 = time.perf_counter()
        embed_tasks   = [self._embedder.embed_one(q) for q in queries]
        query_vectors = await _asyncio.gather(*embed_tasks, return_exceptions=True)

        all_dense:         list[list[tuple[str, float]]] = []
        all_sparse:        list[list[tuple[str, float]]] = []
        all_dense_results: list[VectorSearchResult]      = []  # 收集所有路原始结果，避免额外 embedding 调用

        for i, (q, vec) in enumerate(zip(queries, query_vectors)):
            if isinstance(vec, Exception):
                logger.warning(f"[MultiQuery] embed failed for query[{i}]: {vec}")
                continue
            # 密集检索
            dense = await self._store.search(
                query_vector=vec,
                top_k=settings.top_k_dense,
                filters=filters,
            )
            all_dense.append([(r.chunk_id, r.score) for r in dense])
            all_dense_results.extend(dense)   # 保留原始结果用于 payload 回查
            # 稀疏检索（只对前 N 个查询做，避免过多噪声）
            if i < settings.sparse_query_limit:
                sparse = await _asyncio.to_thread(
                    self._bm25.search, q, settings.top_k_sparse
                )
                all_sparse.append(sparse)

        multi_retrieval_ms = round((time.perf_counter() - t0) * 1000, 1)
        timings["multi_retrieval_ms"] = multi_retrieval_ms
        retrieval_latency_seconds.labels(stage="dense").observe(multi_retrieval_ms / 1000)
        retrieval_latency_seconds.labels(stage="sparse").observe(multi_retrieval_ms / 1000)

        # RRF 融合所有路的结果
        t0 = time.perf_counter()
        fused = rrf_fusion(all_dense + all_sparse, k=settings.rrf_k)
        rrf_ms = round((time.perf_counter() - t0) * 1000, 1)
        timings["rrf_ms"] = rrf_ms
        retrieval_latency_seconds.labels(stage="rrf").observe(rrf_ms / 1000)

        # 直接从已收集结果中构建 dense_map，无需额外 embedding + 搜索
        dense_map = {r.chunk_id: r for r in all_dense_results}

        candidates: list[RetrievedChunk] = []
        for chunk_id, rrf_score in fused[:settings.top_k_dense]:
            if chunk_id in dense_map:
                rc = _to_retrieved_chunk(dense_map[chunk_id], method="hybrid")
                rc.rrf_score = rrf_score
                candidates.append(rc)

        # Cross-Encoder 精排
        t0 = time.perf_counter()
        ranked = await self._reranker.rerank(original_query, candidates, top_k=top_k)
        rerank_ms = round((time.perf_counter() - t0) * 1000, 1)
        timings["rerank_ms"] = rerank_ms
        retrieval_latency_seconds.labels(stage="rerank").observe(rerank_ms / 1000)

        # 父块回溯
        if getattr(settings, "parent_child_enabled", False):
            t0 = time.perf_counter()
            ranked = await self._expand_to_parent(ranked)
            timings["parent_expand_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        logger.info(f"[MultiQuery] {len(queries)} queries -> {len(ranked)} final chunks")
        return ranked, timings

    async def _expand_to_parent(
        self,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """
        父块回溯：找出有 parent_chunk_id 的子块，批量拉取对应父块内容，
        把父块内容写入 chunk.parent_content，Generator 构建 Prompt 时优先使用父块内容。
        子块 content 仍保留（用于来源标注和忠实度评估）。
        """
        # 收集需要回溯的父块 ID
        parent_ids = list({
            c.metadata.parent_chunk_id
            for c in chunks
            if c.metadata.parent_chunk_id
        })
        if not parent_ids:
            return chunks

        parent_col = (
            getattr(settings, "qdrant_parent_collection", "") or
            settings.qdrant_collection + "_parent"
        )
        try:
            parent_map: dict[str, str] = await self._store.fetch_parent_chunks(
                parent_ids, parent_col
            )
            for chunk in chunks:
                pid = chunk.metadata.parent_chunk_id
                if pid and pid in parent_map:
                    chunk.parent_content = parent_map[pid]
                    logger.debug(
                        f"[ParentExpand] chunk={chunk.chunk_id[:12]} "
                        f"parent_tokens≈{len(parent_map[pid])//4}"
                    )
        except asyncpg.PostgresError as exc:
            logger.warning("[ParentExpand] DB fetch failed (non-fatal)", exc_info=exc)

        return chunks


    @property
    def embedder(self):
        """公开访问 embedder（供 summary_indexer 等复用）。"""
        return self._embedder

    @property
    def vector_store(self):
        """公开访问 vector_store（供 summary_indexer 等复用）。"""
        return self._store


_retriever: HybridRetrieverService | None = None


def get_retriever() -> HybridRetrieverService:
    global _retriever
    if _retriever is None:
        _retriever = HybridRetrieverService()
    return _retriever
