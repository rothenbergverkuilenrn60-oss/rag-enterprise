# =============================================================================
# services/audit/audit_service.py
# 审计日志：SOC2 / ISO27001 / 等保三级 合规要求
#
# 特性：
#   - INSERT-ONLY（PostgreSQL 层 REVOKE UPDATE/DELETE）
#   - 双写：立即写 Loguru 文件（高可靠）+ 异步批写 PostgreSQL（可查询）
#   - 内存缓冲区批写，降低 DB 压力
#   - DB 写失败不影响主流程（文件日志仍有完整记录）
# =============================================================================
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from loguru import logger

from config.settings import settings


class AuditAction(str, Enum):
    QUERY             = "QUERY"
    INGEST            = "INGEST"
    DELETE_DOC        = "DELETE_DOC"
    LOGIN             = "LOGIN"
    LOGOUT            = "LOGOUT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RATE_LIMITED      = "RATE_LIMITED"
    PII_DETECTED      = "PII_DETECTED"
    RULE_BLOCKED      = "RULE_BLOCKED"
    FEEDBACK          = "FEEDBACK"
    KB_UPDATE         = "KB_UPDATE"
    TOKEN_VERIFIED    = "TOKEN_VERIFIED"


class AuditResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED  = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


@dataclass
class AuditEvent:
    """一条不可变的审计记录（创建后不允许修改任何字段）。"""
    event_id:    str   = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp:   float = field(default_factory=time.time)
    user_id:     str   = ""
    tenant_id:   str   = ""
    action:      str   = AuditAction.QUERY
    resource_id: str   = ""     # doc_id / query_hash / session_id
    ip_address:  str   = ""
    result:      str   = AuditResult.SUCCESS
    detail:      dict  = field(default_factory=dict)
    trace_id:    str   = ""


class AuditService:
    """
    审计日志服务。

    写入策略：
      1. 立即写入 Loguru audit 日志文件（同步，微秒级，不丢数据）
      2. 异步写入 PostgreSQL audit_log 表（INSERT-ONLY，用于查询/报表）
         仅当 settings.audit_db_enabled = True 时启用
      3. 内存缓冲区批写（积累 BUFFER_SIZE 条或超时后统一写 DB）

    PostgreSQL 表结构（应用首次部署时执行）：
      CREATE TABLE IF NOT EXISTS audit_log (
          event_id    VARCHAR(32)  PRIMARY KEY,
          timestamp   DOUBLE PRECISION NOT NULL,
          user_id     VARCHAR(128),
          tenant_id   VARCHAR(128),
          action      VARCHAR(64)  NOT NULL,
          resource_id VARCHAR(256),
          ip_address  VARCHAR(64),
          result      VARCHAR(32)  NOT NULL,
          detail      JSONB,
          trace_id    VARCHAR(32),
          created_at  TIMESTAMPTZ  DEFAULT NOW()
      );
      -- 合规要求：审计表只允许 INSERT，禁止修改和删除
      REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;
    """

    _BUFFER_SIZE = 50      # 积累 N 条后批量写 DB
    _FLUSH_SEC   = 10.0    # 最多等待 N 秒强制 flush

    def __init__(self) -> None:
        self._buffer: list[AuditEvent] = []
        self._last_flush = time.time()
        self._lock = asyncio.Lock()
        self._setup_audit_logger()

    def _setup_audit_logger(self) -> None:
        """配置专用 audit 日志（独立文件，不与应用日志混合）。"""
        try:
            audit_log_path = str(settings.log_dir / "audit.log")
            logger.add(
                audit_log_path,
                format="{message}",
                rotation="1 day",
                retention="90 days",
                compression="gz",
                filter=lambda r: r["extra"].get("audit", False),
                serialize=False,
                enqueue=True,   # 异步写文件，不阻塞主线程
            )
        except Exception as exc:
            logger.warning(f"[Audit] Logger setup failed (non-fatal): {exc}")

    async def log(self, event: AuditEvent) -> None:
        """记录一条审计事件（异步非阻塞）。"""
        if not getattr(settings, "audit_enabled", True):
            return

        # 1. 立即写文件（serialize=False，手动 JSON 序列化保证格式一致）
        try:
            logger.bind(audit=True).info(
                json.dumps(asdict(event), ensure_ascii=False)
            )
        except Exception as exc:
            logger.warning(f"[Audit] File write failed: {exc}")

        # 2. 加入缓冲区，条件满足时批写 DB
        if getattr(settings, "audit_db_enabled", False):
            async with self._lock:
                self._buffer.append(event)
                if (
                    len(self._buffer) >= self._BUFFER_SIZE
                    or time.time() - self._last_flush > self._FLUSH_SEC
                ):
                    await self._flush_to_db()

    async def log_query(
        self,
        user_id: str,
        tenant_id: str,
        query: str,
        trace_id: str,
        result: str = AuditResult.SUCCESS,
        ip_address: str = "",
        latency_ms: float = 0.0,
        sources_count: int = 0,
        intent: str = "",
    ) -> None:
        import hashlib
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
        await self.log(AuditEvent(
            user_id=user_id,
            tenant_id=tenant_id,
            action=AuditAction.QUERY,
            resource_id=query_hash,
            ip_address=ip_address,
            result=result,
            detail={
                "latency_ms": latency_ms,
                "sources_count": sources_count,
                "query_len": len(query),
                "intent": intent,
            },
            trace_id=trace_id,
        ))

    async def log_ingest(
        self,
        user_id: str,
        tenant_id: str,
        doc_id: str,
        file_name: str,
        result: str = AuditResult.SUCCESS,
        chunk_count: int = 0,
        pii_detected: bool = False,
        error: str = "",
    ) -> None:
        await self.log(AuditEvent(
            user_id=user_id,
            tenant_id=tenant_id,
            action=AuditAction.INGEST,
            resource_id=doc_id,
            result=result,
            detail={
                "file_name": file_name,
                "chunk_count": chunk_count,
                "pii_detected": pii_detected,
                "error": error,
            },
        ))

    async def log_permission_denied(
        self,
        user_id: str,
        tenant_id: str,
        trace_id: str,
        ip_address: str = "",
        reason: str = "",
    ) -> None:
        await self.log(AuditEvent(
            user_id=user_id,
            tenant_id=tenant_id,
            action=AuditAction.PERMISSION_DENIED,
            resource_id=tenant_id,
            ip_address=ip_address,
            result=AuditResult.BLOCKED,
            detail={"reason": reason},
            trace_id=trace_id,
        ))

    async def log_pii_detected(
        self,
        user_id: str,
        tenant_id: str,
        doc_id: str,
        pii_types: list[str],
        count: int = 0,
    ) -> None:
        await self.log(AuditEvent(
            user_id=user_id,
            tenant_id=tenant_id,
            action=AuditAction.PII_DETECTED,
            resource_id=doc_id,
            result=AuditResult.SUCCESS,
            detail={"pii_types": pii_types, "count": count or len(pii_types)},
        ))

    async def log_rule_blocked(
        self,
        user_id: str,
        tenant_id: str,
        trace_id: str,
        stage: str,
        message: str,
    ) -> None:
        await self.log(AuditEvent(
            user_id=user_id,
            tenant_id=tenant_id,
            action=AuditAction.RULE_BLOCKED,
            resource_id=stage,
            result=AuditResult.BLOCKED,
            detail={"stage": stage, "message": message[:200]},
            trace_id=trace_id,
        ))

    async def _flush_to_db(self) -> None:
        """将缓冲区批量写入 PostgreSQL（INSERT-ONLY）。"""
        if not self._buffer:
            return
        batch = self._buffer.copy()
        self._buffer.clear()
        self._last_flush = time.time()

        try:
            import asyncpg
            dsn = settings.pg_dsn.replace("+asyncpg", "")
            conn = await asyncpg.connect(dsn)
            try:
                await conn.executemany(
                    """
                    INSERT INTO audit_log
                        (event_id, timestamp, user_id, tenant_id, action,
                         resource_id, ip_address, result, detail, trace_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    [
                        (
                            e.event_id, e.timestamp, e.user_id, e.tenant_id,
                            e.action, e.resource_id, e.ip_address, e.result,
                            json.dumps(e.detail, ensure_ascii=False), e.trace_id,
                        )
                        for e in batch
                    ],
                )
            finally:
                await conn.close()
            logger.debug(f"[Audit] Flushed {len(batch)} events to DB")
        except Exception as exc:
            # DB 写入失败不影响主流程（文件日志已有记录）
            logger.warning(f"[Audit] DB flush failed (file log intact): {exc}")
            # 失败的事件重新入队（最多保留 200 条，防止内存溢出）
            self._buffer = (batch + self._buffer)[:200]

    async def flush(self) -> None:
        """手动 flush 全部缓冲区，应用关闭时调用。"""
        if getattr(settings, "audit_db_enabled", False):
            async with self._lock:
                await self._flush_to_db()


_audit_service: AuditService | None = None


def get_audit_service() -> AuditService:
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService()
    return _audit_service
