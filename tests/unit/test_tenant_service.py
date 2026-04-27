"""
tests/unit/test_tenant_service.py
Unit tests for TenantService and TenantConfig (multi-tenant isolation).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
from unittest.mock import AsyncMock, MagicMock


class TestTenantService:
    def test_register_and_get(self):
        from services.tenant.tenant_service import TenantService, TenantConfig

        svc = TenantService()
        cfg = TenantConfig(tenant_id="t1", name="Tenant One")
        svc.register(cfg)
        result = svc.get("t1")
        assert result.name == "Tenant One"

    def test_get_unknown_returns_default(self):
        from services.tenant.tenant_service import TenantService

        svc = TenantService()
        result = svc.get("unknown")
        assert result.tenant_id == "unknown"

    def test_check_permission_open_tenant(self):
        from services.tenant.tenant_service import TenantService, TenantConfig

        svc = TenantService()
        svc.register(TenantConfig(tenant_id="open", name="Open", allowed_users=[]))
        assert svc.check_permission("open", "any_user") is True
        assert svc.check_permission("open", "another_user") is True

    def test_check_permission_restricted_tenant(self):
        from services.tenant.tenant_service import TenantService, TenantConfig

        svc = TenantService()
        svc.register(TenantConfig(tenant_id="t", name="Restricted", allowed_users=["alice"]))
        assert svc.check_permission("t", "alice") is True
        assert svc.check_permission("t", "bob") is False

    async def test_set_tenant_context_calls_set_config(self):
        from services.tenant.tenant_service import TenantService

        svc = TenantService()
        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        await svc.set_tenant_context(mock_conn, "tenant-42")
        assert mock_conn.execute.await_count == 1
        call_sql = mock_conn.execute.await_args.args[0]
        assert "app.current_tenant" in call_sql

    def test_get_tenant_filter_empty_tenant_id(self):
        from services.tenant.tenant_service import TenantService

        svc = TenantService()
        assert svc.get_tenant_filter("") is None

    def test_get_tenant_filter_returns_dict(self):
        from services.tenant.tenant_service import TenantService

        svc = TenantService()
        result = svc.get_tenant_filter("t1")
        assert result == {"tenant_id": "t1"}
