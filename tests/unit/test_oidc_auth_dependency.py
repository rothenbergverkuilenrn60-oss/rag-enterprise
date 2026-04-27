from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


@pytest.mark.asyncio
async def test_get_current_user_returns_user_for_valid_token(monkeypatch):
    """Given valid bearer credentials, get_current_user returns AuthenticatedUser."""
    from services.auth.oidc_auth import AuthenticatedUser
    fake_user = AuthenticatedUser(user_id="u1", tenant_id="t1", roles=["user"])
    mock_svc = MagicMock()
    mock_svc.verify_token = AsyncMock(return_value=fake_user)
    monkeypatch.setattr("services.auth.oidc_auth.get_auth_service", lambda: mock_svc)

    from services.auth.oidc_auth import get_current_user
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")
    user = await get_current_user(credentials=creds)

    assert user.user_id == "u1"
    assert user.tenant_id == "t1"
    mock_svc.verify_token.assert_awaited_once_with("valid-token")


@pytest.mark.asyncio
async def test_get_current_user_raises_401_when_no_credentials():
    """Given credentials=None, get_current_user raises HTTPException(401)."""
    from services.auth.oidc_auth import get_current_user
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Authorization required"


@pytest.mark.asyncio
async def test_get_current_user_raises_401_when_verify_returns_none(monkeypatch):
    """Given verify_token returns None, get_current_user raises HTTPException(401)."""
    mock_svc = MagicMock()
    mock_svc.verify_token = AsyncMock(return_value=None)
    monkeypatch.setattr("services.auth.oidc_auth.get_auth_service", lambda: mock_svc)

    from services.auth.oidc_auth import get_current_user
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad-token")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(credentials=creds)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired token"


@pytest.mark.asyncio
async def test_get_current_user_uses_singleton_auth_service(monkeypatch):
    """get_current_user must call get_auth_service() — not OIDCAuthService() directly."""
    call_count = {"n": 0}
    mock_svc = MagicMock()
    mock_svc.verify_token = AsyncMock(return_value=None)
    def fake_get():
        call_count["n"] += 1
        return mock_svc
    monkeypatch.setattr("services.auth.oidc_auth.get_auth_service", fake_get)

    from services.auth.oidc_auth import get_current_user
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")
    with pytest.raises(HTTPException):
        await get_current_user(credentials=creds)
    assert call_count["n"] == 1, "get_auth_service must be invoked exactly once"
