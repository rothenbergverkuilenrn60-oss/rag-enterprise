# =============================================================================
# services/vectorizer/embedder.py
# STAGE 4a — 向量化（嵌入）
# 支持：Ollama BGE-M3 / OpenAI text-embedding-3 / HuggingFace 本地
# =============================================================================
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from loguru import logger
from tenacity import (
    retry, stop_after_attempt, wait_random_exponential,
    retry_if_exception_type,
)
import httpx

from config.settings import settings
from utils.logger import log_latency


# ══════════════════════════════════════════════════════════════════════════════
# Abstract Base
# ══════════════════════════════════════════════════════════════════════════════
class BaseEmbedder(ABC):
    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入，返回向量列表。"""

    async def embed_one(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]


# ══════════════════════════════════════════════════════════════════════════════
# Ollama Embedder — 本地部署，WSL2 localhost 直通
# ══════════════════════════════════════════════════════════════════════════════
class OllamaEmbedder(BaseEmbedder):
    def __init__(self) -> None:
        # WSL2 镜像模式：Windows 侧 Ollama 通过 localhost 互通
        self._base_url = settings.ollama_base_url
        self._model = settings.embedding_model
        self._client = httpx.AsyncClient(timeout=60.0)
        logger.info(f"OllamaEmbedder: model={self._model} url={self._base_url}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=1, max=8),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    )
    async def _embed_single(self, text: str) -> list[float]:
        resp = await self._client.post(
            f"{self._base_url}/api/embeddings",
            json={"model": self._model, "prompt": text},
        )
        resp.raise_for_status()
        return resp.json()["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        tasks = [self._embed_single(t) for t in texts]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        embeddings: list[list[float]] = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(f"Embed failed idx={i}: {r}")
                raise RuntimeError(f"Embedding failed for text[{i}]") from r
            embeddings.append(r)
        return embeddings


# ══════════════════════════════════════════════════════════════════════════════
# OpenAI Embedder
# ══════════════════════════════════════════════════════════════════════════════
class OpenAIEmbedder(BaseEmbedder):
    def __init__(self) -> None:
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        # 优先读取 settings.embedding_model，回退到 OpenAI 推荐的高维模型
        self._model = settings.embedding_model or "text-embedding-3-large"
        logger.info(f"OpenAIEmbedder: model={self._model}")

    @retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=10))
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # OpenAI 支持最多 2048 条/批次
        resp = await self._client.embeddings.create(
            model=self._model,
            input=texts,
            encoding_format="float",
        )
        return [item.embedding for item in resp.data]


# ══════════════════════════════════════════════════════════════════════════════
# HuggingFace 本地 Embedder (SentenceTransformer, /mnt/f/ 路径)
# ══════════════════════════════════════════════════════════════════════════════
class HuggingFaceEmbedder(BaseEmbedder):
    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_path = str(settings.embedding_model_path)
        self._model = SentenceTransformer(model_path, device=device)
        self._device = device
        logger.info(f"HuggingFaceEmbedder: path={model_path} device={device}")

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._model.encode(
                texts,
                batch_size=settings.embedding_batch_size,
                normalize_embeddings=settings.embedding_normalize,
                show_progress_bar=False,
            ).tolist(),
        )
        return result


# ══════════════════════════════════════════════════════════════════════════════
# Batched Embedder Wrapper（控制并发，防止 OOM）
# ══════════════════════════════════════════════════════════════════════════════
class BatchedEmbedder:
    """
    将大批量 texts 按 batch_size 拆分，串行调用底层 embedder，
    防止一次性大请求导致 OOM 或超时。
    """

    def __init__(self, base: BaseEmbedder, batch_size: int = settings.embedding_batch_size) -> None:
        self._base = base
        self._batch_size = batch_size

    @log_latency
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i: i + self._batch_size]
            logger.debug(f"[Embed] batch {i//self._batch_size + 1}: {len(batch)} texts")
            embeddings = await self._base.embed_batch(batch)
            all_embeddings.extend(embeddings)
        return all_embeddings

    async def embed_one(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]


# ══════════════════════════════════════════════════════════════════════════════
# 多模型 Ensemble Embedder
# ══════════════════════════════════════════════════════════════════════════════

class EnsembleEmbedder(BaseEmbedder):
    """
    多模型 Ensemble：将多个 Embedder 的输出向量拼接或加权平均，
    提升语义覆盖度和跨语言/跨领域的检索质量。

    融合策略（ensemble_strategy）：
      - "concat"  : 直接拼接向量（维度相加，向量存储需支持更高维度）
      - "average" : 加权平均（维度不变，推荐用于同维度模型）

    配置示例（settings.embedding_ensemble）：
      [
        {"provider": "ollama",    "weight": 0.6},
        {"provider": "openai",    "weight": 0.4},
      ]
    """

    def __init__(
        self,
        embedders: list[BaseEmbedder],
        weights: list[float] | None = None,
        strategy: str = "average",
    ) -> None:
        self._embedders = embedders
        total_w = sum(weights or []) or 1.0
        self._weights = [w / total_w for w in (weights or [1.0] * len(embedders))]
        self._strategy = strategy
        logger.info(
            f"EnsembleEmbedder: models={len(embedders)} "
            f"strategy={strategy} weights={[round(w, 3) for w in self._weights]}"
        )

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # 并行调用所有 embedder
        import asyncio
        all_results: list[list[list[float]]] = await asyncio.gather(
            *[emb.embed_batch(texts) for emb in self._embedders]
        )

        merged: list[list[float]] = []
        for i in range(len(texts)):
            vecs = [all_results[j][i] for j in range(len(self._embedders))]
            if self._strategy == "concat":
                # 拼接：[v1_dim0, v1_dim1, ..., v2_dim0, v2_dim1, ...]
                merged.append([x for v in vecs for x in v])
            else:
                # 加权平均
                dim = len(vecs[0])
                avg = [0.0] * dim
                for w, v in zip(self._weights, vecs):
                    for d in range(min(dim, len(v))):
                        avg[d] += w * v[d]
                # L2 归一化
                norm = sum(x * x for x in avg) ** 0.5 or 1.0
                merged.append([x / norm for x in avg])

        return merged

    async def embed_one(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]


def _make_base_embedder(provider: str) -> BaseEmbedder:
    if provider == "ollama":
        return OllamaEmbedder()
    if provider == "openai":
        return OpenAIEmbedder()
    if provider == "huggingface":
        return HuggingFaceEmbedder()
    raise ValueError(f"Unknown embedding provider: {provider}")


# ══════════════════════════════════════════════════════════════════════════════
# Factory
# ══════════════════════════════════════════════════════════════════════════════
_embedder_instance: BatchedEmbedder | EnsembleEmbedder | None = None


def get_embedder():
    global _embedder_instance
    if _embedder_instance is None:
        # Ensemble 模式（settings.embedding_ensemble 非空时启用）
        ensemble_cfg = getattr(settings, "embedding_ensemble", [])
        if ensemble_cfg:
            embedders = [_make_base_embedder(c["provider"]) for c in ensemble_cfg]
            weights   = [c.get("weight", 1.0) for c in ensemble_cfg]
            strategy  = getattr(settings, "embedding_ensemble_strategy", "average")
            _embedder_instance = EnsembleEmbedder(embedders, weights, strategy)
        else:
            # 单模型模式（向后兼容）
            base = _make_base_embedder(settings.embedding_provider)
            _embedder_instance = BatchedEmbedder(base)
            logger.info(f"Embedder factory: provider={settings.embedding_provider}")
    return _embedder_instance
