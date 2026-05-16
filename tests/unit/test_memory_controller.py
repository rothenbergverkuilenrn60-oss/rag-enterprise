"""tests/unit/test_memory_controller.py — Phase 25 / GDPR-02 + GDPR-03.

Covers DELETE /api/v1/memory/forget endpoint:
  Test  1: admin JWT + X-Confirm-Delete: yes -> 200 + {deleted_row_count: N}
  Test  2: non-admin self-delete (jwt.user_id == user_id) -> 200
  Test  3: non-admin other user -> 403
  Test  4: missing X-Confirm-Delete header -> 400 (admin caller)
  Test  5: X-Confirm-Delete: no -> 400 (admin caller)
  Test  6: MemoryForgetError from forget_user -> 500
  Test  7: audit row content (action + D-2.4 detail dict)
  Test  8: audit called after forget_user (ordering + once-only)
  Test  9 [T1]: audit_service.log raises -> still 200 + structured ERROR log
  Test 10 [T3]: admin tenant A targeting bob-in-tenantB -> 200 + deleted=0
  Test 11 [T9]: non-admin + other user_id + NO X-Confirm-Delete -> 403 (role wins)

Mock strategy (v1.3 D-13/D-15):
  - controllers.memory.LongTermMemory (patch class so forget_user is overridable)
  - controllers.memory.get_audit_service (consumer-path singleton)
  - services.auth.oidc_auth.get_auth_service (consumer-path JWT decode)
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from loguru import logger

from services.auth.oidc_auth import AuthenticatedUser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client() -> TestClient:
    """TestClient bound to the real `main.app` (verifies T2 mount)."""
    from main import app  # noqa: PLC0415 — deferred so test collection works pre-controller
    return TestClient(app)


@pytest.fixture
def loguru_records():
    """Capture full loguru records (incl. ``extra`` kwargs) for structured-log assertions.

    Loguru passes keyword args through ``record["extra"]``; the stdlib propagate
    handler used by `caplog` does NOT surface them as ``LogRecord`` attributes.
    This sink records the loguru record dict directly, so T1's assertion can
    inspect the ``operation="forget_audit_log"`` field and the audit payload.
    """
    captured: list[dict] = []

    def _sink(message) -> None:
        captured.append(dict(message.record))

    handler_id = logger.add(_sink, level="ERROR", format="{message}")
    yield captured
    logger.remove(handler_id)


def _patch_auth(monkeypatch, user: AuthenticatedUser) -> None:
    """Mock the JWT auth singleton to return `user` for any Bearer token."""
    mock_svc = MagicMock()
    mock_svc.verify_token = AsyncMock(return_value=user)
    monkeypatch.setattr("services.auth.oidc_auth.get_auth_service", lambda: mock_svc)


def _patch_memory(monkeypatch, forget_user_mock: AsyncMock) -> None:
    """Patch controllers.memory.LongTermMemory so the controller uses our mock."""
    fake_mem_instance = MagicMock()
    fake_mem_instance.forget_user = forget_user_mock

    class _FakeLTM:
        def __init__(self, *args, **kwargs):
            pass

        forget_user = forget_user_mock  # bound class attr; the *instance* attr below wins

        def __new__(cls):
            return fake_mem_instance

    monkeypatch.setattr("controllers.memory.LongTermMemory", _FakeLTM)


def _patch_audit(monkeypatch, log_mock: AsyncMock) -> MagicMock:
    """Patch controllers.memory.get_audit_service to return a MagicMock with .log."""
    fake_audit = MagicMock()
    fake_audit.log = log_mock
    monkeypatch.setattr("controllers.memory.get_audit_service", lambda: fake_audit)
    return fake_audit


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_forget_admin_jwt_200(monkeypatch, client):
    """Test 1: admin JWT + X-Confirm-Delete: yes -> 200 + {deleted_row_count: 3}."""
    admin = AuthenticatedUser(user_id="admin-1", tenant_id="tenantA", roles=["admin"])
    _patch_auth(monkeypatch, admin)
    forget_mock = AsyncMock(return_value=3)
    _patch_memory(monkeypatch, forget_mock)
    _patch_audit(monkeypatch, AsyncMock())

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "alice"},
        headers={"Authorization": "Bearer fake", "X-Confirm-Delete": "yes"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"deleted_row_count": 3}
    forget_mock.assert_awaited_once_with("alice", "tenantA")


def test_forget_self_delete_200(monkeypatch, client):
    """Test 2: non-admin JWT where jwt.user_id == target user_id -> 200."""
    user = AuthenticatedUser(user_id="alice", tenant_id="tenantA", roles=["viewer"])
    _patch_auth(monkeypatch, user)
    _patch_memory(monkeypatch, AsyncMock(return_value=1))
    _patch_audit(monkeypatch, AsyncMock())

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "alice"},
        headers={"Authorization": "Bearer fake", "X-Confirm-Delete": "yes"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"deleted_row_count": 1}


def test_forget_non_admin_other_user_403(monkeypatch, client):
    """Test 3: non-admin JWT for a different user_id (with confirm header) -> 403."""
    user = AuthenticatedUser(user_id="alice", tenant_id="tenantA", roles=["viewer"])
    _patch_auth(monkeypatch, user)
    forget_mock = AsyncMock(return_value=999)
    _patch_memory(monkeypatch, forget_mock)
    audit_mock = AsyncMock()
    _patch_audit(monkeypatch, audit_mock)

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "bob"},
        headers={"Authorization": "Bearer fake", "X-Confirm-Delete": "yes"},
    )

    assert resp.status_code == 403
    forget_mock.assert_not_awaited()
    audit_mock.assert_not_awaited()


def test_forget_missing_confirm_header_400(monkeypatch, client):
    """Test 4: admin JWT, no X-Confirm-Delete header -> 400 (not 422)."""
    admin = AuthenticatedUser(user_id="admin-1", tenant_id="tenantA", roles=["admin"])
    _patch_auth(monkeypatch, admin)
    forget_mock = AsyncMock(return_value=5)
    _patch_memory(monkeypatch, forget_mock)
    _patch_audit(monkeypatch, AsyncMock())

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "alice"},
        headers={"Authorization": "Bearer fake"},  # no X-Confirm-Delete
    )

    assert resp.status_code == 400
    forget_mock.assert_not_awaited()


def test_forget_wrong_confirm_header_400(monkeypatch, client):
    """Test 5: admin JWT + X-Confirm-Delete: no -> 400."""
    admin = AuthenticatedUser(user_id="admin-1", tenant_id="tenantA", roles=["admin"])
    _patch_auth(monkeypatch, admin)
    forget_mock = AsyncMock(return_value=5)
    _patch_memory(monkeypatch, forget_mock)
    _patch_audit(monkeypatch, AsyncMock())

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "alice"},
        headers={"Authorization": "Bearer fake", "X-Confirm-Delete": "no"},
    )

    assert resp.status_code == 400
    forget_mock.assert_not_awaited()


def test_forget_memory_forget_error_500(monkeypatch, client):
    """Test 6: forget_user raises MemoryForgetError -> 500 (sanitized detail)."""
    from services.memory.memory_service import MemoryForgetError  # noqa: PLC0415

    admin = AuthenticatedUser(user_id="admin-1", tenant_id="tenantA", roles=["admin"])
    _patch_auth(monkeypatch, admin)
    forget_mock = AsyncMock(side_effect=MemoryForgetError("forget failed"))
    _patch_memory(monkeypatch, forget_mock)
    audit_mock = AsyncMock()
    _patch_audit(monkeypatch, audit_mock)

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "alice"},
        headers={"Authorization": "Bearer fake", "X-Confirm-Delete": "yes"},
    )

    assert resp.status_code == 500
    audit_mock.assert_not_awaited()  # SP-6: audit only on success path


def test_forget_audit_row_content(monkeypatch, client):
    """Test 7: audit row has action=MEMORY_FORGET + D-2.4 detail dict fields."""
    from services.audit.audit_service import AuditAction  # noqa: PLC0415

    admin = AuthenticatedUser(user_id="admin-1", tenant_id="tenantA", roles=["admin"])
    _patch_auth(monkeypatch, admin)
    _patch_memory(monkeypatch, AsyncMock(return_value=7))
    audit_mock = AsyncMock()
    _patch_audit(monkeypatch, audit_mock)

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "alice"},
        headers={"Authorization": "Bearer fake", "X-Confirm-Delete": "yes"},
    )

    assert resp.status_code == 200
    assert audit_mock.await_count == 1
    event = audit_mock.await_args.args[0]
    assert event.action == AuditAction.MEMORY_FORGET
    assert event.resource_id == "alice"
    assert event.detail["target_user_id"] == "alice"
    assert event.detail["target_tenant_id"] == "tenantA"
    assert event.detail["deleted_row_count"] == 7
    assert event.detail["actor_user_id"] == "admin-1"
    assert event.detail["actor_is_admin"] is True


def test_forget_audit_called_after_forget_user(monkeypatch, client):
    """Test 8: audit.log called exactly once AFTER forget_user resolves."""
    call_order: list[str] = []

    async def _forget(*args, **kwargs):
        call_order.append("forget")
        return 4

    async def _audit_log(event):
        call_order.append("audit")

    admin = AuthenticatedUser(user_id="admin-1", tenant_id="tenantA", roles=["admin"])
    _patch_auth(monkeypatch, admin)
    _patch_memory(monkeypatch, AsyncMock(side_effect=_forget))
    audit_mock = AsyncMock(side_effect=_audit_log)
    _patch_audit(monkeypatch, audit_mock)

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "alice"},
        headers={"Authorization": "Bearer fake", "X-Confirm-Delete": "yes"},
    )

    assert resp.status_code == 200
    assert call_order == ["forget", "audit"]
    assert audit_mock.await_count == 1


def test_forget_audit_write_failure_returns_200(monkeypatch, client, loguru_records):
    """Test 9 [T1 — Architecture A1]: audit_service.log raises -> still 200.

    GDPR DELETE already committed; audit failure must NOT propagate to a 500.
    A structured ERROR log with operation='forget_audit_log' + the would-be
    detail payload must be emitted.
    """
    admin = AuthenticatedUser(user_id="admin-1", tenant_id="tenantA", roles=["admin"])
    _patch_auth(monkeypatch, admin)
    _patch_memory(monkeypatch, AsyncMock(return_value=3))
    audit_mock = AsyncMock(side_effect=Exception("audit pipeline down"))
    _patch_audit(monkeypatch, audit_mock)

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "alice"},
        headers={"Authorization": "Bearer fake", "X-Confirm-Delete": "yes"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"deleted_row_count": 3}
    audit_mock.assert_awaited_once()

    # Structured-log assertion: loguru's keyword args land in record["extra"].
    matched = [
        rec for rec in loguru_records
        if rec.get("extra", {}).get("operation") == "forget_audit_log"
    ]
    assert matched, (
        "Expected an ERROR-level log with operation='forget_audit_log' after audit fail; "
        f"records seen: {[(r['message'], r.get('extra', {})) for r in loguru_records]}"
    )
    rec = matched[0]
    assert rec["level"].name == "ERROR"
    extra = rec["extra"]
    # Required structured fields per T1 — convenience top-levels + the full payload
    assert extra["target_user_id"] == "alice"
    assert extra["target_tenant_id"] == "tenantA"
    assert extra["deleted_row_count"] == 3
    assert extra["actor_user_id"] == "admin-1"
    # The full would-be audit-detail payload must be carried in the log so
    # operators can reconstruct the missing audit row from logs (T1 contract).
    payload = extra["audit_payload"]
    assert payload["target_user_id"] == "alice"
    assert payload["target_tenant_id"] == "tenantA"
    assert payload["deleted_row_count"] == 3
    assert payload["actor_user_id"] == "admin-1"
    assert payload["actor_is_admin"] is True


def test_forget_cross_tenant_unreachable_returns_200_zero(monkeypatch, client):
    """Test 10 [T3 — Code Quality C1]: admin tenant A targeting bob-in-tenant-B.

    The forget_user mock returns 0 (DELETE WHERE tenant_id='tenantA' matches 0 rows
    because bob's facts live in tenant B). Endpoint must return 200/deleted=0 —
    documented idempotent no-op for JWT-scoped cross-tenant attempts.
    """
    admin = AuthenticatedUser(user_id="admin-A", tenant_id="tenantA", roles=["admin"])
    _patch_auth(monkeypatch, admin)
    forget_mock = AsyncMock(return_value=0)
    _patch_memory(monkeypatch, forget_mock)
    _patch_audit(monkeypatch, AsyncMock())

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "bob-in-tenantB"},
        headers={"Authorization": "Bearer fake", "X-Confirm-Delete": "yes"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"deleted_row_count": 0}
    # forget_user was invoked with the *JWT* tenant_id, not anything from the request
    forget_mock.assert_awaited_once_with("bob-in-tenantB", "tenantA")


def test_forget_non_admin_no_header_returns_403(monkeypatch, client):
    """Test 11 [T9 — outside voice F3]: non-admin + other user + NO header -> 403.

    Role check must run BEFORE header check. Without this ordering, a non-admin
    probing the endpoint with no header would get a 400 (header missing) and learn
    the endpoint exists. Fail-closed-on-identity-first.
    """
    user = AuthenticatedUser(user_id="alice", tenant_id="tenantA", roles=["viewer"])
    _patch_auth(monkeypatch, user)
    forget_mock = AsyncMock(return_value=999)
    _patch_memory(monkeypatch, forget_mock)
    audit_mock = AsyncMock()
    _patch_audit(monkeypatch, audit_mock)

    resp = client.delete(
        "/api/v1/memory/forget",
        params={"user_id": "bob"},
        headers={"Authorization": "Bearer fake"},  # no X-Confirm-Delete
    )

    assert resp.status_code == 403
    forget_mock.assert_not_awaited()
    audit_mock.assert_not_awaited()
