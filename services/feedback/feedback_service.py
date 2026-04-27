# =============================================================================
# services/feedback/feedback_service.py
# 闭环反馈机制：用户反馈 → 质量统计 → 自动触发知识库更新
# =============================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class FeedbackRecord:
    session_id:  str
    query:       str
    answer:      str
    feedback:    int          # 1=positive, -1=negative, 0=none
    user_id:     str    = ""
    tenant_id:   str    = ""
    comment:     str    = ""  # 用户填写的文字反馈
    doc_ids:     list[str] = field(default_factory=list)   # 引用的文档
    timestamp:   float  = field(default_factory=time.time)


class FeedbackService:
    """
    闭环反馈服务：
    1. 收集用户对回答的评分（+1/-1）
    2. 更新用户画像（通过 MemoryService）
    3. 发布反馈事件（通过 EventBus）
    4. 当同一文档负面反馈累积到阈值时，自动触发重新入库
    5. 统计整体指标供监控使用
    """

    def __init__(self) -> None:
        self._records: list[FeedbackRecord] = []
        # doc_id → 负面反馈次数
        self._negative_counts: dict[str, int] = {}
        self._reindex_threshold = 3   # 连续 3 次负面反馈触发重新索引

    async def submit(self, record: FeedbackRecord) -> None:
        self._records.append(record)

        # 更新内存统计
        if record.feedback < 0:
            for doc_id in record.doc_ids:
                self._negative_counts[doc_id] = (
                    self._negative_counts.get(doc_id, 0) + 1
                )

        # 发布事件
        from services.events.event_bus import get_event_bus
        bus = get_event_bus()
        await bus.emit_feedback(
            positive=record.feedback > 0,
            session_id=record.session_id,
            tenant_id=record.tenant_id,
            user_id=record.user_id,
        )

        # 更新用户记忆
        from services.memory.memory_service import get_memory_service
        await get_memory_service().save_feedback(
            user_id=record.user_id,
            session_id=record.session_id,
            feedback=record.feedback,
        )

        # 检查是否触发重新索引
        await self._check_reindex_trigger(record)

        logger.info(
            f"[Feedback] session={record.session_id} "
            f"feedback={record.feedback} user={record.user_id}"
        )

    async def _check_reindex_trigger(self, record: FeedbackRecord) -> None:
        """当某文档负面反馈超阈值时，触发知识库更新事件。"""
        from services.events.event_bus import get_event_bus, Event, EventType
        bus = get_event_bus()
        for doc_id in record.doc_ids:
            count = self._negative_counts.get(doc_id, 0)
            if count >= self._reindex_threshold:
                logger.warning(
                    f"[Feedback] doc_id={doc_id} negative_count={count}, "
                    f"triggering reindex"
                )
                await bus.publish(Event(
                    event_type=EventType.REINDEX_REQUESTED,
                    payload={"doc_id": doc_id, "reason": "negative_feedback_threshold"},
                    tenant_id=record.tenant_id,
                ))
                self._negative_counts[doc_id] = 0   # 重置计数

    def get_stats(self) -> dict[str, Any]:
        """返回反馈统计数据。"""
        if not self._records:
            return {"total": 0, "positive": 0, "negative": 0, "satisfaction_rate": None}
        positive = sum(1 for r in self._records if r.feedback > 0)
        negative = sum(1 for r in self._records if r.feedback < 0)
        total    = len(self._records)
        return {
            "total":             total,
            "positive":          positive,
            "negative":          negative,
            "satisfaction_rate": round(positive / total, 3) if total else 0,
            "top_negative_docs": sorted(
                self._negative_counts.items(), key=lambda x: x[1], reverse=True
            )[:5],
        }


_feedback_service: FeedbackService | None = None

def get_feedback_service() -> FeedbackService:
    global _feedback_service
    if _feedback_service is None:
        _feedback_service = FeedbackService()
    return _feedback_service
