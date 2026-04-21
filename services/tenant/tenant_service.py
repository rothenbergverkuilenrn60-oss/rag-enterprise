# =============================================================================
# services/tenant/tenant_service.py
# 多租户支持：租户隔离 / 配置覆盖 / 权限校验
# =============================================================================
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import asyncpg
from loguru import logger


@dataclass
class TenantConfig:
    """租户级别的配置，可覆盖全局 settings。"""
    tenant_id:        str
    name:             str             = ""
    qdrant_collection: str            = ""    # 空=用全局+租户后缀
    allowed_doc_types: list[str]      = field(default_factory=list)
    max_tokens:       int             = 2048
    llm_provider:     str             = ""    # 空=用全局配置
    allowed_users:    list[str]       = field(default_factory=list)  # 空=所有用户
    rate_limit_rpm:   int             = 60
    metadata:         dict[str, Any]  = field(default_factory=dict)
    active:           bool            = True


class TenantService:
    """
    多租户管理：
    - 每个租户有独立的 Qdrant collection（物理隔离）
    - 租户级别的配置覆盖（LLM / 速率限制 / 允许用户）
    - 路由查询时自动注入 tenant filter 到 Qdrant 查询
    """

    def __init__(self) -> None:
        # 生产环境应从数据库加载，这里用内存字典作为示例
        self._configs: dict[str, TenantConfig] = {}

    def register(self, config: TenantConfig) -> None:
        self._configs[config.tenant_id] = config
        logger.info(f"[Tenant] Registered: {config.tenant_id}")

    def get(self, tenant_id: str) -> TenantConfig:
        return self._configs.get(
            tenant_id,
            TenantConfig(tenant_id=tenant_id),  # 默认空配置（全局设置）
        )

    def get_collection(self, tenant_id: str) -> str:
        """获取租户对应的 Qdrant collection 名。"""
        from config.settings import settings
        cfg = self.get(tenant_id)
        if cfg.qdrant_collection:
            return cfg.qdrant_collection
        if tenant_id:
            return f"{settings.qdrant_collection}_{tenant_id}"
        return settings.qdrant_collection

    def get_tenant_filter(self, tenant_id: str) -> dict | None:
        """Return metadata filter dict for tenant isolation.

        Returns None for empty tenant_id (admin/system operations).
        When RLS is active, this dict cooperates with the DB-level policy.
        """
        if not tenant_id:
            return None
        return {"tenant_id": tenant_id}

    # Backward-compat alias — remove in Phase 2 cleanup
    get_qdrant_filter = get_tenant_filter

    async def set_tenant_context(
        self,
        conn: asyncpg.Connection,
        tenant_id: str,
    ) -> None:
        """Set RLS session variable for the current connection transaction.

        Must be called inside an active transaction block so the setting is
        transaction-local (is_local=true resets at transaction end).
        Pass empty string for admin/system operations — RLS returns 0 rows (safe fail).
        """
        try:
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, true)", tenant_id
            )
        except asyncpg.PostgresError as exc:
            logger.warning(
                f"[Tenant] set_tenant_context failed tenant_id={tenant_id!r}: {exc}"
            )
            raise RuntimeError(f"Failed to set tenant context: {exc}") from exc

    def check_permission(self, tenant_id: str, user_id: str) -> bool:
        cfg = self.get(tenant_id)
        if not cfg.active:
            return False
        if not cfg.allowed_users:
            return True
        return user_id in cfg.allowed_users


_tenant_service: TenantService | None = None

def get_tenant_service() -> TenantService:
    global _tenant_service
    if _tenant_service is None:
        _tenant_service = TenantService()
    return _tenant_service
