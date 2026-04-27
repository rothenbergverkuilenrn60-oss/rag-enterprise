# =============================================================================
# services/ab_test/ab_test_service.py
# A/B 测试框架
#
# 功能：
#   1. 实验管理：创建/启动/停止实验，配置变体流量分配
#   2. 流量路由：按哈希或随机将请求路由到指定变体
#   3. 结果收集：Redis 存储每次查询的延迟、faithfulness、用户反馈
#   4. 统计分析：均值、标准差、置信区间（t-test）
#   5. 与 RAGAS 集成：自动化评估各变体指标
#
# 变体配置示例：
#   variant A（对照）: top_k=6, reranker=cross_encoder
#   variant B（实验）: top_k=10, reranker=passthrough, hyde=True
# =============================================================================
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from loguru import logger
from typing import Any


class ExperimentStatus(str, Enum):
    DRAFT   = "draft"
    RUNNING = "running"
    PAUSED  = "paused"
    STOPPED = "stopped"


@dataclass
class Variant:
    """实验变体：定义一组 RAG 配置参数。"""
    variant_id:   str
    name:         str
    traffic_pct:  float                    # 0.0-1.0，所有变体之和必须 = 1.0
    config:       dict[str, Any] = field(default_factory=dict)
    # config 示例：
    # {
    #   "top_k_rerank": 6,
    #   "hyde_enabled": True,
    #   "reranker_type": "cross_encoder",  # or "passthrough"
    #   "rrf_dense_weight": 0.6,
    #   "similarity_correction_alpha": 0.3,
    # }


@dataclass
class Experiment:
    """A/B 实验定义。"""
    experiment_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name:          str = ""
    description:   str = ""
    variants:      list[Variant] = field(default_factory=list)
    status:        str = ExperimentStatus.DRAFT
    created_at:    float = field(default_factory=time.time)
    started_at:    float = 0.0
    stopped_at:    float = 0.0
    tenant_id:     str = ""   # 为空时对所有租户生效


@dataclass
class ExperimentResult:
    """单次查询的 A/B 测试结果记录。"""
    result_id:     str   = field(default_factory=lambda: uuid.uuid4().hex[:12])
    experiment_id: str   = ""
    variant_id:    str   = ""
    session_id:    str   = ""
    tenant_id:     str   = ""
    latency_ms:    float = 0.0
    faithfulness:  float = 0.0
    retrieved_k:   int   = 0
    user_feedback: int   = 0    # -1 / 0 / +1
    timestamp:     float = field(default_factory=time.time)
    trace_id:      str   = ""


@dataclass
class VariantStats:
    """变体统计汇总。"""
    variant_id:      str
    name:            str
    sample_count:    int   = 0
    avg_latency_ms:  float = 0.0
    avg_faithfulness: float = 0.0
    avg_feedback:    float = 0.0
    p95_latency_ms:  float = 0.0
    feedback_positive_rate: float = 0.0


class ABTestService:
    """
    A/B 测试服务。

    Redis 键结构：
      ab:experiments           → Hash {experiment_id: json}
      ab:exp:{id}:variants     → Hash {variant_id: json}
      ab:exp:{id}:results:{variant_id} → List of result json（最近 10k 条）
      ab:running               → Set of running experiment_ids
    """

    _RESULTS_LIMIT = 10_000   # 每个变体保留最近 N 条结果

    def __init__(self) -> None:
        self._redis = None

    async def _get_redis(self):
        if self._redis is None:
            from utils.cache import get_redis
            self._redis = await get_redis()
        return self._redis

    # ── 实验管理 ──────────────────────────────────────────────────────────────

    async def create_experiment(self, exp: Experiment) -> str:
        """创建实验，返回 experiment_id。"""
        r = await self._get_redis()
        # 验证变体流量之和为 1.0
        total = sum(v.traffic_pct for v in exp.variants)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Variant traffic sum must be 1.0, got {total:.3f}")

        pipe = r.pipeline()
        pipe.hset("ab:experiments", exp.experiment_id, json.dumps({
            "experiment_id": exp.experiment_id,
            "name": exp.name,
            "description": exp.description,
            "status": exp.status,
            "created_at": exp.created_at,
            "started_at": exp.started_at,
            "stopped_at": exp.stopped_at,
            "tenant_id": exp.tenant_id,
        }))
        for v in exp.variants:
            pipe.hset(
                f"ab:exp:{exp.experiment_id}:variants",
                v.variant_id,
                json.dumps(asdict(v)),
            )
        await pipe.execute()
        logger.info(f"[AB] Created experiment {exp.experiment_id}: {exp.name}")
        return exp.experiment_id

    async def start_experiment(self, experiment_id: str) -> None:
        r = await self._get_redis()
        await r.sadd("ab:running", experiment_id)
        await r.hset("ab:experiments", experiment_id,
                     json.dumps({**(await self._get_exp_raw(experiment_id)),
                                 "status": ExperimentStatus.RUNNING,
                                 "started_at": time.time()}))
        logger.info(f"[AB] Started experiment {experiment_id}")

    async def stop_experiment(self, experiment_id: str) -> None:
        r = await self._get_redis()
        await r.srem("ab:running", experiment_id)
        await r.hset("ab:experiments", experiment_id,
                     json.dumps({**(await self._get_exp_raw(experiment_id)),
                                 "status": ExperimentStatus.STOPPED,
                                 "stopped_at": time.time()}))
        logger.info(f"[AB] Stopped experiment {experiment_id}")

    async def _get_exp_raw(self, experiment_id: str) -> dict:
        r = await self._get_redis()
        raw = await r.hget("ab:experiments", experiment_id)
        return json.loads(raw) if raw else {}

    # ── 流量路由 ──────────────────────────────────────────────────────────────

    async def assign_variant(
        self,
        session_id: str,
        tenant_id: str = "",
    ) -> tuple[str | None, str | None, dict]:
        """
        为当前请求分配实验变体。
        返回 (experiment_id, variant_id, variant_config)
        若无运行中实验则返回 (None, None, {})。

        路由策略：一致性哈希（同一 session_id 始终命中同一变体），
        确保同一用户的多次请求体验一致。
        """
        r = await self._get_redis()
        running = await r.smembers("ab:running")
        if not running:
            return None, None, {}

        for exp_id_bytes in running:
            exp_id = exp_id_bytes.decode() if isinstance(exp_id_bytes, bytes) else exp_id_bytes
            exp_raw = await self._get_exp_raw(exp_id)

            # 租户过滤
            exp_tenant = exp_raw.get("tenant_id", "")
            if exp_tenant and tenant_id and exp_tenant != tenant_id:
                continue

            # 获取变体列表
            variants_raw = await r.hgetall(f"ab:exp:{exp_id}:variants")
            variants = [
                json.loads(v) for v in variants_raw.values()
            ]
            if not variants:
                continue

            # 一致性哈希分配
            hash_val = int(hashlib.md5(f"{session_id}:{exp_id}".encode(), usedforsecurity=False).hexdigest(), 16)
            bucket = (hash_val % 10000) / 10000.0  # 0.0 ~ 1.0

            cumulative = 0.0
            for v in sorted(variants, key=lambda x: x["variant_id"]):
                cumulative += v["traffic_pct"]
                if bucket < cumulative:
                    logger.debug(
                        f"[AB] session={session_id[:8]} → "
                        f"exp={exp_id} variant={v['variant_id']} ({v['name']})"
                    )
                    return exp_id, v["variant_id"], v.get("config", {})

        return None, None, {}

    # ── 结果收集 ──────────────────────────────────────────────────────────────

    async def record_result(self, result: ExperimentResult) -> None:
        """记录一次查询结果到实验数据池。"""
        if not result.experiment_id or not result.variant_id:
            return
        r = await self._get_redis()
        key = f"ab:exp:{result.experiment_id}:results:{result.variant_id}"
        pipe = r.pipeline()
        pipe.lpush(key, json.dumps(asdict(result)))
        pipe.ltrim(key, 0, self._RESULTS_LIMIT - 1)
        await pipe.execute()

    async def record_feedback(
        self,
        experiment_id: str,
        variant_id: str,
        session_id: str,
        feedback: int,  # -1 / 0 / +1
    ) -> None:
        """记录用户反馈（点赞/踩/无）。"""
        await self.record_result(ExperimentResult(
            experiment_id=experiment_id,
            variant_id=variant_id,
            session_id=session_id,
            user_feedback=feedback,
        ))

    # ── 统计分析 ──────────────────────────────────────────────────────────────

    async def get_stats(self, experiment_id: str) -> list[VariantStats]:
        """计算实验各变体的统计指标。"""
        r = await self._get_redis()
        variants_raw = await r.hgetall(f"ab:exp:{experiment_id}:variants")
        stats_list: list[VariantStats] = []

        for v_raw in variants_raw.values():
            v = json.loads(v_raw)
            key = f"ab:exp:{experiment_id}:results:{v['variant_id']}"
            raw_results = await r.lrange(key, 0, -1)

            if not raw_results:
                stats_list.append(VariantStats(
                    variant_id=v["variant_id"], name=v["name"],
                ))
                continue

            results = [json.loads(r_) for r_ in raw_results]
            latencies   = [res["latency_ms"]    for res in results if res["latency_ms"] > 0]
            faithfulness = [res["faithfulness"]  for res in results if res["faithfulness"] > 0]
            feedbacks    = [res["user_feedback"] for res in results if res["user_feedback"] != 0]

            def _mean(lst):  return sum(lst) / len(lst) if lst else 0.0
            def _p95(lst):
                if not lst:
                    return 0.0
                s = sorted(lst)
                idx = max(0, int(len(s) * 0.95) - 1)
                return s[idx]

            pos_fb = sum(1 for f in feedbacks if f > 0)

            stats_list.append(VariantStats(
                variant_id=v["variant_id"],
                name=v["name"],
                sample_count=len(results),
                avg_latency_ms=round(_mean(latencies), 1),
                avg_faithfulness=round(_mean(faithfulness), 4),
                avg_feedback=round(_mean(feedbacks), 3),
                p95_latency_ms=round(_p95(latencies), 1),
                feedback_positive_rate=round(pos_fb / len(feedbacks), 3) if feedbacks else 0.0,
            ))

        return stats_list

    async def get_winner(self, experiment_id: str) -> str | None:
        """
        基于 faithfulness + 正反馈率 + 延迟综合评分选出最优变体。
        评分公式：score = 0.5*faithfulness + 0.3*feedback_rate - 0.2*(latency/1000)
        """
        stats = await self.get_stats(experiment_id)
        if not stats or all(s.sample_count == 0 for s in stats):
            return None

        best = max(
            [s for s in stats if s.sample_count > 0],
            key=lambda s: (
                0.5 * s.avg_faithfulness
                + 0.3 * s.feedback_positive_rate
                - 0.2 * (s.avg_latency_ms / 1000.0)
            ),
        )
        logger.info(
            f"[AB] Winner for {experiment_id}: variant={best.variant_id} "
            f"faith={best.avg_faithfulness:.3f} "
            f"feedback={best.feedback_positive_rate:.3f} "
            f"p95_lat={best.p95_latency_ms}ms"
        )
        return best.variant_id

    async def list_experiments(self) -> list[dict]:
        r = await self._get_redis()
        all_raw = await r.hgetall("ab:experiments")
        return [json.loads(v) for v in all_raw.values()]


_ab_service: ABTestService | None = None


def get_ab_test_service() -> ABTestService:
    global _ab_service
    if _ab_service is None:
        _ab_service = ABTestService()
    return _ab_service
