# =============================================================================
# services/annotation/annotation_service.py
# 人工标注服务：构建 RAGAS 评估 → 人工标注 → 黄金数据集 的闭环
#
# 工作流程：
#   1. RAGAS 自动评估发现低分答案（faithfulness < 0.6）
#      → ragas_runner.py 调用 annotation_service.push_task() 创建标注任务
#   2. 标注员通过 GET /annotation/tasks/next 领取任务
#   3. 标注员通过 POST /annotation/tasks/{id}/result 提交评分 + 纠正答案
#   4. 高质量标注结果自动写入 RAGAS 黄金数据集（eval/datasets/qa_pairs.json）
#      → 下次评估时使用更准确的 ground_truth，形成数据飞轮
#
# 存储：
#   - 任务队列：Redis Sorted Set（score = 优先级，负反馈触发的任务 priority 高）
#   - 标注结果：Redis Hash（key = annotation:{task_id}）
#   - 黄金数据集：本地 JSON 文件（eval/datasets/qa_pairs.json）
# =============================================================================
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import redis.asyncio
from loguru import logger

from utils.models import AnnotationTask, AnnotationResult, AnnotationStats


_QUEUE_KEY   = "annotation:queue"        # Redis Sorted Set：任务队列（score=priority）
_TASK_PREFIX = "annotation:task:"        # Redis Hash：任务详情
_RESULT_PREFIX = "annotation:result:"    # Redis Hash：标注结果
_DONE_SET    = "annotation:done"         # Redis Set：已完成任务 ID
_SKIP_SET    = "annotation:skip"         # Redis Set：已跳过任务 ID

# 自动写入黄金数据集的阈值
_QUALITY_THRESHOLD = 0.7    # 标注员评分 >= 此值才写入黄金集
_GOLDEN_DATASET_PATH = Path(__file__).parent.parent.parent / "eval" / "datasets" / "qa_pairs.json"


class AnnotationService:
    """
    人工标注服务。

    与 RAGAS 的集成点：
      - push_task_from_ragas()：RAGAS 评估后自动推送低分任务
      - submit_result()：标注完成后自动更新黄金数据集
    """

    async def _redis(self):
        from utils.cache import get_redis
        return await get_redis()

    # ── 任务管理 ─────────────────────────────────────────────────────────────

    async def push_task(self, task: AnnotationTask) -> None:
        """推送标注任务到队列。priority 越高越先被领取。"""
        try:
            r = await self._redis()
            pipe = r.pipeline()
            # 存储任务详情
            pipe.set(
                f"{_TASK_PREFIX}{task.task_id}",
                task.model_dump_json(),
                ex=30 * 86400,    # 30 天自动过期
            )
            # 加入优先级队列（score = priority * 1000 + timestamp 保证同优先级 FIFO）
            score = task.priority * 1000 + time.time()
            pipe.zadd(_QUEUE_KEY, {task.task_id: score})
            await pipe.execute()
            logger.info(
                f"[Annotation] Task pushed: task_id={task.task_id} "
                f"priority={task.priority} source={task.source}"
            )
        except redis.asyncio.RedisError as exc:
            logger.error("annotation service failure", operation="push_task", annotation_id=task.task_id, exc_info=exc)

    async def push_task_from_ragas(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        ragas_score: float,
        ground_truth: str = "",
        tenant_id: str = "",
    ) -> None:
        """
        RAGAS 低分结果自动触发标注任务。
        ragas_score < 0.6 时被调用，优先级高于手动创建的任务。
        """
        priority = 10 if ragas_score < 0.4 else 5   # 极低分更紧急
        task = AnnotationTask(
            question=question,
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
            source="ragas",
            ragas_score=ragas_score,
            tenant_id=tenant_id,
            priority=priority,
        )
        await self.push_task(task)

    async def push_task_from_feedback(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        tenant_id: str = "",
    ) -> None:
        """
        负面反馈触发标注任务（最高优先级，需要人工确认问题所在）。
        由 FeedbackService._check_reindex_trigger() 调用。
        """
        task = AnnotationTask(
            question=question,
            answer=answer,
            contexts=contexts,
            source="feedback",
            tenant_id=tenant_id,
            priority=20,    # 最高优先级
        )
        await self.push_task(task)

    async def pop_task(self, tenant_id: str = "") -> AnnotationTask | None:
        """
        领取优先级最高的待标注任务（原子操作）。
        ZPOPMAX 取分数最高的任务 ID，再从 Hash 读取详情。
        """
        try:
            r = await self._redis()
            # 取优先级最高（score 最大）的任务
            items = await r.zpopmax(_QUEUE_KEY, count=1)
            if not items:
                return None
            task_id, _ = items[0]
            raw = await r.get(f"{_TASK_PREFIX}{task_id}")
            if not raw:
                return None
            task = AnnotationTask.model_validate_json(raw)
            # 过滤租户（如有需要）
            if tenant_id and task.tenant_id and task.tenant_id != tenant_id:
                # 不属于此租户，放回队列
                await r.zadd(_QUEUE_KEY, {task_id: time.time()})
                return None
            # 更新任务状态为 annotating
            task.status = "annotating"
            await r.set(
                f"{_TASK_PREFIX}{task_id}",
                task.model_dump_json(),
                ex=30 * 86400,
            )
            logger.info(f"[Annotation] Task popped: task_id={task_id}")
            return task
        except redis.asyncio.RedisError as exc:
            logger.error("annotation service failure", operation="pop_task", exc_info=exc)
            return None

    async def submit_result(self, result: AnnotationResult) -> None:
        """
        提交标注结果。
        高质量结果（评分 >= 阈值）自动写入黄金数据集。
        """
        try:
            r = await self._redis()
            pipe = r.pipeline()
            # 存储标注结果
            pipe.set(
                f"{_RESULT_PREFIX}{result.task_id}",
                result.model_dump_json(),
                ex=90 * 86400,
            )
            # 将任务标记为已完成
            pipe.sadd(_DONE_SET, result.task_id)
            # 更新任务状态
            raw = await r.get(f"{_TASK_PREFIX}{result.task_id}")
            if raw:
                task = AnnotationTask.model_validate_json(raw)
                task.status = "done"
                pipe.set(f"{_TASK_PREFIX}{result.task_id}", task.model_dump_json(), ex=90 * 86400)
            await pipe.execute()

            logger.info(
                f"[Annotation] Result submitted: task_id={result.task_id} "
                f"annotator={result.annotator_id} "
                f"faithfulness={result.faithfulness:.2f} "
                f"quality={result.answer_quality:.2f}"
            )

            # 高质量标注自动写入黄金数据集
            avg_score = (result.faithfulness + result.answer_quality) / 2
            if avg_score >= _QUALITY_THRESHOLD and raw:
                await self._update_golden_dataset(task, result)

        except redis.asyncio.RedisError as exc:
            logger.error("annotation service failure", operation="submit_result", annotation_id=result.task_id, exc_info=exc)

    async def skip_task(self, task_id: str) -> None:
        """跳过任务（放回队列末尾，降低优先级）。"""
        try:
            r = await self._redis()
            pipe = r.pipeline()
            # 以最低分放回队列（排在末尾）
            pipe.zadd(_QUEUE_KEY, {task_id: 0})
            pipe.sadd(_SKIP_SET, task_id)
            # 更新状态
            raw = await r.get(f"{_TASK_PREFIX}{task_id}")
            if raw:
                task = AnnotationTask.model_validate_json(raw)
                task.status = "pending"
                task.priority = 0
                pipe.set(f"{_TASK_PREFIX}{task_id}", task.model_dump_json(), ex=30 * 86400)
            await pipe.execute()
        except redis.asyncio.RedisError as exc:
            logger.error("annotation service failure", operation="skip_task", annotation_id=task_id, exc_info=exc)

    # ── 黄金数据集更新 ────────────────────────────────────────────────────────

    async def _update_golden_dataset(
        self,
        task: AnnotationTask,
        result: AnnotationResult,
    ) -> None:
        """
        将高质量标注写入 RAGAS 黄金数据集（eval/datasets/qa_pairs.json）。
        下次 RAGAS 评估会使用更准确的 ground_truth 计算 context_recall 等指标。
        """
        try:
            _GOLDEN_DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)

            # 读取现有数据集
            if _GOLDEN_DATASET_PATH.exists():
                existing = json.loads(_GOLDEN_DATASET_PATH.read_text(encoding="utf-8"))
            else:
                existing = {"name": "RAG Golden Dataset", "pairs": []}

            # 构建新 QA 对（使用标注员的纠正答案或原始答案）
            new_pair = {
                "question":     task.question,
                "ground_truth": result.corrected_answer or task.ground_truth or task.answer,
                "contexts":     task.contexts[:3],   # 保留最多3条上下文
                "metadata": {
                    "source":         task.source,
                    "annotator_id":   result.annotator_id,
                    "faithfulness":   result.faithfulness,
                    "answer_quality": result.answer_quality,
                    "annotated_at":   result.annotated_at,
                    "task_id":        task.task_id,
                },
            }

            # 避免重复写入相同问题
            existing_questions = {p["question"] for p in existing.get("pairs", [])}
            if task.question not in existing_questions:
                existing.setdefault("pairs", []).append(new_pair)
                _GOLDEN_DATASET_PATH.write_text(
                    json.dumps(existing, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(
                    f"[Annotation] Golden dataset updated: task_id={task.task_id} "
                    f"total_pairs={len(existing['pairs'])}"
                )
        except (OSError, ValueError, KeyError) as exc:
            logger.error("annotation service failure", operation="update_golden_dataset", annotation_id=task.task_id, exc_info=exc)

    # ── 统计 ─────────────────────────────────────────────────────────────────

    async def get_stats(self) -> AnnotationStats:
        """返回标注进度和质量统计。"""
        try:
            r = await self._redis()
            queue_size  = await r.zcard(_QUEUE_KEY)
            done_count  = await r.scard(_DONE_SET)
            skip_count  = await r.scard(_SKIP_SET)

            # 读取所有结果计算平均分
            result_keys = await r.keys(f"{_RESULT_PREFIX}*")
            faithfulness_scores: list[float] = []
            quality_scores: list[float] = []
            for key in result_keys[:200]:    # 最多读 200 条
                raw = await r.get(key)
                if raw:
                    try:
                        res = AnnotationResult.model_validate_json(raw)
                        faithfulness_scores.append(res.faithfulness)
                        quality_scores.append(res.answer_quality)
                    except (ValueError, KeyError) as exc:
                        logger.error("annotation service failure", operation="parse_result_entry", exc_info=exc)

            return AnnotationStats(
                total_tasks=queue_size + done_count + skip_count,
                pending=queue_size,
                done=done_count,
                skipped=skip_count,
                avg_faithfulness=round(statistics.mean(faithfulness_scores), 3)
                    if faithfulness_scores else None,
                avg_answer_quality=round(statistics.mean(quality_scores), 3)
                    if quality_scores else None,
            )
        except redis.asyncio.RedisError as exc:
            logger.error("annotation service failure", operation="get_stats", exc_info=exc)
            return AnnotationStats()


_annotation_service: AnnotationService | None = None


def get_annotation_service() -> AnnotationService:
    global _annotation_service
    if _annotation_service is None:
        _annotation_service = AnnotationService()
    return _annotation_service
