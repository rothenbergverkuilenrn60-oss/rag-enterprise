# =============================================================================
# services/reranker_service/app.py
# Reranker 独立微服务
#
# 职责：接收 (query, candidates) → 返回排序后的分数列表
# 部署：独立容器，监听 8001 端口
# 扩展：可挂载 GPU，独立扩缩容，不影响主 API 服务
#
# 接口：
#   POST /rerank          → 重排序
#   GET  /health          → 健康检查
#   GET  /metrics         → Prometheus 指标
# =============================================================================
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response as FastAPIResponse
from loguru import logger
from pydantic import BaseModel, Field

# ── 请求/响应模型 ───────────────────────────────────────────────────────────

class RerankRequest(BaseModel):
    query:      str
    candidates: list[str]           # chunk 文本列表（顺序对应 candidate_ids）
    candidate_ids: list[str] = Field(default_factory=list)
    top_k:      int = 6
    model:      str = "default"     # 支持按 model 字段选择不同模型


class RerankResponse(BaseModel):
    scores:        list[float]      # 与 candidates 顺序一一对应的分数
    ranked_ids:    list[str]        # 按分数降序排列的 candidate_id
    ranked_scores: list[float]      # 对应 ranked_ids 的分数
    latency_ms:    float
    model_used:    str


# ── 模型管理 ─────────────────────────────────────────────────────────────────

class RerankerModel:
    """CrossEncoder 模型包装，支持多模型并存。"""

    def __init__(self, model_path: str, device: str = "cpu") -> None:
        self.model_path = model_path
        self.device = device
        self._model = None
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        try:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_path, device=self.device, max_length=512)
            self._loaded = True
            logger.info(f"[RerankerService] Model loaded: {self.model_path} on {self.device}")
        except Exception as exc:
            logger.warning(f"[RerankerService] Model load failed: {exc}, using fallback scores")
            self._loaded = False

    def predict(self, query: str, candidates: list[str], batch_size: int = 32) -> list[float]:
        if not self._loaded or self._model is None:
            # Fallback：按字符串重叠度给假分数
            return [
                len(set(query.split()) & set(c.split())) / max(len(query.split()), 1)
                for c in candidates
            ]
        pairs = [(query, c) for c in candidates]
        scores = self._model.predict(pairs, batch_size=batch_size, show_progress_bar=False)
        return [float(s) for s in scores]


# 模型注册表（key=model名称）
_models: dict[str, RerankerModel] = {}
_default_model_path = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _init_models() -> None:
    import os
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    default_path = os.environ.get("RERANKER_MODEL_PATH", _default_model_path)

    _models["default"] = RerankerModel(default_path, device)
    _models["default"].load()

    # 可选：多语言重排器（中文场景）
    cn_path = os.environ.get("RERANKER_CN_MODEL_PATH", "")
    if cn_path:
        _models["chinese"] = RerankerModel(cn_path, device)
        _models["chinese"].load()


# ── FastAPI 应用 ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("[RerankerService] Starting up…")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _init_models)
    logger.info("[RerankerService] Models ready")
    yield
    logger.info("[RerankerService] Shutting down…")


app = FastAPI(
    title="RAG Reranker Service",
    version="1.0.0",
    description="独立 Cross-Encoder 重排微服务",
    docs_url="/docs",
    lifespan=lifespan,
)


@app.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest) -> RerankResponse:
    """
    重排序接口。

    - 选择 req.model 指定的模型（默认 "default"）
    - 批量预测 (query, candidate) 相关性分数
    - 返回 top_k 个最高分结果
    """
    if not req.candidates:
        raise HTTPException(status_code=422, detail="candidates must not be empty")

    model = _models.get(req.model) or _models.get("default")
    if model is None:
        raise HTTPException(status_code=503, detail="No reranker model available")

    start = time.perf_counter()

    # 在线程池中执行 CPU 密集型推理，不阻塞事件循环
    loop = asyncio.get_event_loop()
    scores: list[float] = await loop.run_in_executor(
        None,
        lambda: model.predict(req.query, req.candidates),
    )

    latency_ms = round((time.perf_counter() - start) * 1000, 1)

    # 构建 candidate_ids（若未提供则用索引）
    ids = req.candidate_ids or [str(i) for i in range(len(req.candidates))]

    # 排序
    indexed = sorted(
        zip(ids, scores),
        key=lambda x: x[1],
        reverse=True,
    )
    ranked_ids    = [cid for cid, _ in indexed[:req.top_k]]
    ranked_scores = [s   for _,   s in indexed[:req.top_k]]

    logger.debug(
        f"[Rerank] query_len={len(req.query)} candidates={len(req.candidates)} "
        f"top_k={req.top_k} latency={latency_ms}ms model={req.model}"
    )

    return RerankResponse(
        scores=scores,
        ranked_ids=ranked_ids,
        ranked_scores=ranked_scores,
        latency_ms=latency_ms,
        model_used=model.model_path,
    )


@app.get("/health")
async def health() -> dict:
    loaded = {name: m._loaded for name, m in _models.items()}
    return {"status": "ok", "models": loaded}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> FastAPIResponse:
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return FastAPIResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return FastAPIResponse(content=b"# prometheus_client not installed\n",
                               media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8001, workers=2, loop="uvloop")
