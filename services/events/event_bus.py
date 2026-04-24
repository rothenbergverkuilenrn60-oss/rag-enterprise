# =============================================================================
# services/events/event_bus.py
# 事件驱动架构：Kafka 生产者/消费者 + 内存事件总线（Kafka 未安装时降级）
# 覆盖：文档入库事件 / 查询完成事件 / 反馈事件 / 知识库更新触发
# =============================================================================
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Awaitable

from loguru import logger

from utils.tasks import log_task_error


# ══════════════════════════════════════════════════════════════════════════════
# 事件定义
# ══════════════════════════════════════════════════════════════════════════════
class EventType(str, Enum):
    # 知识库事件
    DOC_INGESTED        = "doc.ingested"         # 文档入库成功
    DOC_UPDATED         = "doc.updated"           # 文档增量更新
    DOC_DELETED         = "doc.deleted"           # 文档删除
    DOC_QUALITY_FAILED  = "doc.quality_failed"   # 文档质量校验失败

    # 查询事件
    QUERY_RECEIVED      = "query.received"        # 收到查询
    QUERY_COMPLETED     = "query.completed"       # 查询完成
    QUERY_FAILED        = "query.failed"          # 查询失败

    # 反馈事件
    FEEDBACK_POSITIVE   = "feedback.positive"     # 用户正向反馈
    FEEDBACK_NEGATIVE   = "feedback.negative"     # 用户负向反馈

    # 系统事件
    KNOWLEDGE_UPDATE_REQUESTED = "knowledge.update_requested"
    REINDEX_REQUESTED   = "reindex.requested"


@dataclass
class Event:
    event_type:  str
    payload:     dict[str, Any]
    event_id:    str   = field(default_factory=lambda: uuid.uuid4().hex[:16])
    tenant_id:   str   = ""
    user_id:     str   = ""
    timestamp:   float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "Event":
        data = json.loads(raw)
        return cls(**data)


# ══════════════════════════════════════════════════════════════════════════════
# Kafka 后端
# ══════════════════════════════════════════════════════════════════════════════
class KafkaEventBackend:
    """
    基于 aiokafka 的异步 Kafka 后端。
    Topic 命名规范：{tenant_id}.{event_type} 或 rag.{event_type}
    """

    def __init__(self, bootstrap_servers: str, topic_prefix: str = "rag") -> None:
        self._servers = bootstrap_servers
        self._prefix  = topic_prefix
        self._producer = None
        self._consumers: dict[str, Any] = {}

    async def start_producer(self) -> None:
        try:
            from aiokafka import AIOKafkaProducer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self._servers,
                value_serializer=lambda v: v.encode("utf-8"),
                compression_type="gzip",
            )
            await self._producer.start()
            logger.info(f"[Kafka] Producer started: {self._servers}")
        except ImportError:
            logger.warning("[Kafka] aiokafka not installed, falling back to memory bus")
            self._producer = None
        except Exception as exc:
            logger.warning(f"[Kafka] Producer start failed: {exc}")
            self._producer = None

    async def publish(self, event: Event) -> None:
        if self._producer is None:
            return
        topic = f"{self._prefix}.{event.event_type.replace('.', '_')}"
        try:
            await self._producer.send_and_wait(topic, event.to_json())
            logger.debug(f"[Kafka] Published: topic={topic} event_id={event.event_id}")
        except Exception as exc:
            logger.warning(f"[Kafka] Publish failed: {exc}")

    async def subscribe(
        self,
        event_type: str,
        handler: Callable[[Event], Awaitable[None]],
        group_id: str = "rag-consumer",
    ) -> None:
        try:
            from aiokafka import AIOKafkaConsumer
            topic = f"{self._prefix}.{event_type.replace('.', '_')}"
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=self._servers,
                group_id=group_id,
                value_deserializer=lambda v: v.decode("utf-8"),
                auto_offset_reset="latest",
            )
            await consumer.start()
            self._consumers[event_type] = consumer

            async def _consume():
                async for msg in consumer:
                    try:
                        event = Event.from_json(msg.value)
                        await handler(event)
                    except Exception as exc:
                        logger.error(f"[Kafka] Handler error: {exc}")

            _dispatch_task = asyncio.create_task(_consume(), name="event-dispatch")
            _dispatch_task.add_done_callback(log_task_error)
            logger.info(f"[Kafka] Subscribed: topic={topic} group={group_id}")
        except ImportError:
            logger.warning("[Kafka] aiokafka not installed, subscription skipped")
        except Exception as exc:
            logger.warning(f"[Kafka] Subscribe failed: {exc}")

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
        for consumer in self._consumers.values():
            await consumer.stop()


# ══════════════════════════════════════════════════════════════════════════════
# 内存事件总线（Kafka 降级）
# ══════════════════════════════════════════════════════════════════════════════
class InMemoryEventBus:
    """
    进程内事件总线，用于 Kafka 不可用时的降级，
    或单机开发/测试环境。
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._running = False

    def subscribe(self, event_type: str, handler: Callable) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def publish(self, event: Event) -> None:
        await self._queue.put(event)

    async def start(self) -> None:
        self._running = True
        _handler_task = asyncio.create_task(self._dispatch_loop(), name="event-handler")
        _handler_task.add_done_callback(log_task_error)
        logger.info("[EventBus] In-memory bus started")

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                event: Event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                handlers = self._handlers.get(event.event_type, [])
                await asyncio.gather(
                    *[h(event) for h in handlers],
                    return_exceptions=True,
                )
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.error(f"[EventBus] Dispatch error: {exc}")

    def stop(self) -> None:
        self._running = False


# ══════════════════════════════════════════════════════════════════════════════
# 统一事件总线入口
# ══════════════════════════════════════════════════════════════════════════════
class EventBus:
    """
    统一事件总线：优先使用 Kafka，不可用时降级到内存总线。
    对外接口统一，业务代码无感知。
    """

    def __init__(self) -> None:
        from config.settings import settings
        kafka_servers = getattr(settings, "kafka_bootstrap_servers", "")
        if kafka_servers:
            self._kafka   = KafkaEventBackend(kafka_servers)
            self._memory  = InMemoryEventBus()
            self._use_kafka = True
        else:
            self._kafka   = None
            self._memory  = InMemoryEventBus()
            self._use_kafka = False

    async def start(self) -> None:
        if self._use_kafka and self._kafka:
            await self._kafka.start_producer()
        await self._memory.start()

    async def publish(self, event: Event) -> None:
        """发布事件到 Kafka（如可用）+ 内存总线（本地 handler）。"""
        if self._use_kafka and self._kafka:
            await self._kafka.publish(event)
        await self._memory.publish(event)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        """订阅事件（内存总线，适合进程内 handler）。"""
        self._memory.subscribe(event_type, handler)

    async def subscribe_kafka(
        self,
        event_type: str,
        handler: Callable[[Event], Awaitable[None]],
        group_id: str = "rag-consumer",
    ) -> None:
        """订阅 Kafka 事件（适合跨服务 handler）。"""
        if self._use_kafka and self._kafka:
            await self._kafka.subscribe(event_type, handler, group_id)

    async def stop(self) -> None:
        if self._use_kafka and self._kafka:
            await self._kafka.stop()
        self._memory.stop()

    # ── 便捷发布方法 ──────────────────────────────────────────────────────────
    async def emit_doc_ingested(
        self, doc_id: str, chunk_count: int, tenant_id: str = ""
    ) -> None:
        await self.publish(Event(
            event_type=EventType.DOC_INGESTED,
            payload={"doc_id": doc_id, "chunk_count": chunk_count},
            tenant_id=tenant_id,
        ))

    async def emit_query_completed(
        self, query: str, answer_len: int,
        latency_ms: float, faithfulness: float,
        tenant_id: str = "", user_id: str = "",
    ) -> None:
        await self.publish(Event(
            event_type=EventType.QUERY_COMPLETED,
            payload={
                "query_preview": query[:80],
                "answer_len":    answer_len,
                "latency_ms":    latency_ms,
                "faithfulness":  faithfulness,
            },
            tenant_id=tenant_id,
            user_id=user_id,
        ))

    async def emit_feedback(
        self, positive: bool, session_id: str,
        tenant_id: str = "", user_id: str = "",
    ) -> None:
        etype = EventType.FEEDBACK_POSITIVE if positive else EventType.FEEDBACK_NEGATIVE
        await self.publish(Event(
            event_type=etype,
            payload={"session_id": session_id},
            tenant_id=tenant_id,
            user_id=user_id,
        ))


_event_bus: EventBus | None = None

def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
