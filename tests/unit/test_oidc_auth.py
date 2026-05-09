"""tests/unit/test_oidc_auth.py — Phase 15 backfill.

Existing tests/unit/test_oidc_auth_dependency.py covers FastAPI dependency
basics. This file adds OIDCAuthService verify_token branches (local JWT,
OIDC, JWKS error path), token creation, AuthenticatedUser permissions, and
get_auth_service singleton.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from jose import JWTError


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.auth.oidc_auth as mod
    yield
    monkeypatch.setattr(mod, "_auth_service", None, raising=False)


def _make_svc():
    from services.auth.oidc_auth import OIDCAuthService
    svc = OIDCAuthService.__new__(OIDCAuthService)
    svc._oidc_enabled = False
    svc._oidc_issuer = ""
    svc._oidc_client_id = ""
    svc._oidc_audience = ""
    svc._jwks_cache = {}
    svc._jwks_fetched_at = 0.0
    return svc


@pytest.mark.unit
def test_authenticated_user_admin_property():
    from services.auth.oidc_auth import AuthenticatedUser
    u = AuthenticatedUser(user_id="u1", tenant_id="t1", roles=["admin"])
    assert u.is_admin is True
    assert u.is_editor is True


@pytest.mark.unit
def test_authenticated_user_editor_property():
    from services.auth.oidc_auth import AuthenticatedUser
    u = AuthenticatedUser(user_id="u1", tenant_id="t1", roles=["editor"])
    assert u.is_admin is False
    assert u.is_editor is True


@pytest.mark.unit
def test_authenticated_user_has_permission_matrix():
    from services.auth.oidc_auth import AuthenticatedUser
    viewer = AuthenticatedUser(user_id="u", tenant_id="", roles=["viewer"])
    editor = AuthenticatedUser(user_id="u", tenant_id="", roles=["editor"])
    admin = AuthenticatedUser(user_id="u", tenant_id="", roles=["admin"])
    assert viewer.has_permission("read") is True
    assert viewer.has_permission("write") is False
    assert editor.has_permission("write") is True
    assert editor.has_permission("delete") is False
    assert admin.has_permission("delete") is True
    assert viewer.has_permission("nonexistent") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_token_empty_returns_none():
    """Error path: empty / whitespace token → None."""
    svc = _make_svc()
    assert await svc.verify_token("") is None
    assert await svc.verify_token("Bearer  ") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_token_strips_bearer_prefix(monkeypatch):
    svc = _make_svc()
    captured: list = []

    def stub_local(token):
        captured.append(token)
        from services.auth.oidc_auth import AuthenticatedUser
        return AuthenticatedUser(user_id="u1", tenant_id="t1")

    svc._verify_local_jwt = stub_local
    out = await svc.verify_token("Bearer some.jwt.token")
    assert out.user_id == "u1"
    assert captured[0] == "some.jwt.token"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_token_oidc_path_when_enabled():
    svc = _make_svc()
    svc._oidc_enabled = True
    svc._oidc_issuer = "https://issuer.example"
    svc._verify_oidc = AsyncMock(return_value=None)
    await svc.verify_token("xyz")
    svc._verify_oidc.assert_awaited_once()


@pytest.mark.unit
def test_verify_local_jwt_round_trip():
    """Happy path: encode token via create_local_token, decode via verify."""
    svc = _make_svc()
    token = svc.create_local_token("u1", "t1", roles=["editor"])
    user = svc._verify_local_jwt(token)
    assert user is not None
    assert user.user_id == "u1"
    assert user.tenant_id == "t1"
    assert "editor" in user.roles


@pytest.mark.unit
def test_verify_local_jwt_invalid_returns_none():
    """Error path: malformed JWT → None (JWTError caught)."""
    svc = _make_svc()
    out = svc._verify_local_jwt("not-a-real-jwt")
    assert out is None


@pytest.mark.unit
def test_verify_local_jwt_missing_sub_returns_none(monkeypatch):
    """Error path: payload without sub → None."""
    svc = _make_svc()
    from jose import jwt as jose_jwt
    from config.settings import settings as real_settings
    token = jose_jwt.encode(
        {"exp": int(time.time()) + 3600},
        real_settings.secret_key,
        algorithm=real_settings.jwt_algorithm,
    )
    out = svc._verify_local_jwt(token)
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_oidc_jwks_fetch_failure_returns_none(monkeypatch):
    """Error path: JWKS HTTP failure → None."""
    svc = _make_svc()
    svc._oidc_enabled = True
    svc._oidc_issuer = "https://issuer.example"
    svc._get_jwks = AsyncMock(side_effect=httpx.HTTPError("network down"))
    out = await svc._verify_oidc("x.y.z")
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_oidc_jwt_decode_failure_returns_none(monkeypatch):
    """Error path: JWT decode failure → None."""
    svc = _make_svc()
    svc._oidc_enabled = True
    svc._oidc_issuer = "https://issuer.example"
    svc._get_jwks = AsyncMock(return_value={"keys": []})

    def boom(*_a, **_kw):
        raise JWTError("invalid")

    monkeypatch.setattr("jose.jwt.decode", boom)
    out = await svc._verify_oidc("x.y.z")
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_oidc_extracts_oid_and_roles(monkeypatch):
    """Happy path: payload with oid + roles → AuthenticatedUser populated."""
    svc = _make_svc()
    svc._oidc_enabled = True
    svc._oidc_issuer = "https://issuer.example"
    svc._oidc_audience = "api://app"
    svc._get_jwks = AsyncMock(return_value={"keys": []})
    monkeypatch.setattr("jose.jwt.decode", lambda *a, **k: {
        "oid": "azure-oid-1",
        "tid": "tenant-x",
        "email": "user@example.com",
        "roles": ["editor"],
        "exp": int(time.time()) + 3600,
    })
    out = await svc._verify_oidc("x.y.z")
    assert out is not None
    assert out.user_id == "azure-oid-1"
    assert out.tenant_id == "tenant-x"
    assert out.provider == "oidc"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verify_oidc_falls_back_to_scp_for_roles(monkeypatch):
    """Branch: no `roles` claim → derive from `scp` scopes."""
    svc = _make_svc()
    svc._oidc_enabled = True
    svc._oidc_issuer = "https://issuer.example"
    svc._get_jwks = AsyncMock(return_value={"keys": []})
    monkeypatch.setattr("jose.jwt.decode", lambda *a, **k: {
        "sub": "u1",
        "scp": "read write",
        "exp": int(time.time()) + 3600,
    })
    out = await svc._verify_oidc("x.y.z")
    assert out is not None
    assert "read" in out.roles
    assert "write" in out.roles


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_jwks_returns_cached_when_fresh():
    svc = _make_svc()
    svc._jwks_cache = {"keys": [1, 2]}
    svc._jwks_fetched_at = time.time()
    out = await svc._get_jwks()
    assert out == {"keys": [1, 2]}


@pytest.mark.unit
def test_create_local_token_round_trip_via_verify():
    svc = _make_svc()
    token = svc.create_local_token("u-x", "t-x", email="x@y", expire_minutes=60)
    out = svc._verify_local_jwt(token)
    assert out is not None
    assert out.email == "x@y"


@pytest.mark.unit
def test_get_auth_service_singleton():
    from services.auth.oidc_auth import get_auth_service
    a = get_auth_service()
    b = get_auth_service()
    assert a is b
