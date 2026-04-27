# =============================================================================
# services/auth/oidc_auth.py
# 企业级身份认证：支持本地 JWT / OIDC / Azure AD / Okta / 飞书 / 企业微信
#
# 配置方式（.env）：
#   OIDC_ENABLED=true
#   OIDC_ISSUER=https://login.microsoftonline.com/{tenant_id}/v2.0
#   OIDC_CLIENT_ID=your-app-client-id
#   OIDC_AUDIENCE=api://your-app-id
#
# 不配置 OIDC 时，自动降级为本地 HS256 JWT（settings.secret_key 签名）
# =============================================================================
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from loguru import logger
import httpx
from jose import JWTError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config.settings import settings


@dataclass
class AuthenticatedUser:
    """认证成功后的用户上下文，贯穿整个请求生命周期。"""
    user_id:      str
    tenant_id:    str
    email:        str         = ""
    display_name: str         = ""
    roles:        list[str]   = field(default_factory=list)   # ["admin","editor","viewer"]
    groups:       list[str]   = field(default_factory=list)   # AD 组/飞书部门
    provider:     str         = "jwt"    # jwt | oidc | azure_ad | feishu | wework
    expires_at:   float       = 0.0
    raw_claims:   dict[str, Any] = field(default_factory=dict)

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def is_editor(self) -> bool:
        return "editor" in self.roles or self.is_admin

    def has_permission(self, action: str) -> bool:
        """
        细粒度权限检查。
        action: "read" | "write" | "delete" | "admin"
        """
        _PERM_MAP = {
            "read":   {"viewer", "editor", "admin"},
            "write":  {"editor", "admin"},
            "delete": {"admin"},
            "admin":  {"admin"},
        }
        required = _PERM_MAP.get(action, set())
        return bool(set(self.roles) & required)


class OIDCAuthService:
    """
    OIDC / JWT 认证服务。

    两种运行模式自动切换：
      - 本地 JWT（默认）：settings.oidc_enabled = False
        使用 settings.secret_key 进行 HS256 签名验证，适合开发/单体部署
      - OIDC 远端验证：settings.oidc_enabled = True
        通过 /.well-known/openid-configuration 获取 JWKS 公钥，
        验证 Azure AD / Okta / Keycloak 等 Provider 签发的 JWT
    """

    _JWKS_TTL = 3600.0   # JWKS 公钥缓存时长（秒）

    def __init__(self) -> None:
        self._oidc_enabled:   bool  = getattr(settings, "oidc_enabled", False)
        self._oidc_issuer:    str   = getattr(settings, "oidc_issuer", "")
        self._oidc_client_id: str   = getattr(settings, "oidc_client_id", "")
        self._oidc_audience:  str   = getattr(settings, "oidc_audience", "")
        self._jwks_cache:     dict  = {}
        self._jwks_fetched_at: float = 0.0

    async def verify_token(self, token: str) -> AuthenticatedUser | None:
        """
        验证 Bearer Token，返回认证用户或 None（验证失败/已过期）。
        """
        if not token:
            return None
        token = token.removeprefix("Bearer ").strip()
        if not token:
            return None

        if self._oidc_enabled and self._oidc_issuer:
            return await self._verify_oidc(token)
        return self._verify_local_jwt(token)

    def _verify_local_jwt(self, token: str) -> AuthenticatedUser | None:
        """验证本地签发的 HS256 JWT。"""
        try:
            from jose import jwt as jose_jwt
            payload = jose_jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.jwt_algorithm],
                options={"verify_exp": True},
            )
            user_id = payload.get("sub", "")
            if not user_id:
                return None
            return AuthenticatedUser(
                user_id=user_id,
                tenant_id=payload.get("tenant_id", ""),
                email=payload.get("email", ""),
                display_name=payload.get("name", ""),
                roles=payload.get("roles", ["viewer"]),
                provider="jwt",
                expires_at=float(payload.get("exp", 0)),
                raw_claims=payload,
            )
        except JWTError as exc:
            logger.error(
                "JWT verification failed",
                reason=type(exc).__name__,
                exc_info=exc,
            )
            return None

    async def _verify_oidc(self, token: str) -> AuthenticatedUser | None:
        """验证 OIDC Provider 签发的 JWT（支持 RS256 / ES256）。"""
        try:
            jwks = await self._get_jwks()
        except httpx.HTTPError as exc:
            logger.error(
                "JWKS fetch failed",
                issuer=self._oidc_issuer,
                exc_info=exc,
            )
            return None

        try:
            from jose import jwt as jose_jwt
            payload = jose_jwt.decode(
                token,
                jwks,
                algorithms=["RS256", "ES256", "RS384", "RS512"],
                audience=self._oidc_audience or None,
                issuer=self._oidc_issuer or None,
            )
            # Azure AD claims 映射（其他 Provider 通常兼容）
            user_id = (
                payload.get("oid")      # Azure AD 对象 ID（唯一且不可变）
                or payload.get("sub", "")
            )
            tenant_id = payload.get("tid", "")

            # 角色：优先用 app roles，其次用 scp（scope）
            roles: list[str] = payload.get("roles", [])
            if not roles:
                scp = payload.get("scp", "")
                roles = [s.strip() for s in scp.split() if s.strip()] if scp else ["viewer"]

            return AuthenticatedUser(
                user_id=user_id,
                tenant_id=tenant_id,
                email=payload.get("email") or payload.get("upn", ""),
                display_name=payload.get("name", ""),
                roles=roles,
                groups=payload.get("groups", []),
                provider="oidc",
                expires_at=float(payload.get("exp", 0)),
                raw_claims=payload,
            )
        except JWTError as exc:
            logger.error(
                "OIDC JWT verification failed",
                reason=type(exc).__name__,
                exc_info=exc,
            )
            return None

    async def _get_jwks(self) -> dict:
        """
        获取并缓存 OIDC Provider 的 JWKS 公钥。
        每 _JWKS_TTL 秒自动刷新（防止 Provider 轮转密钥后验证失败）。
        """
        now = time.time()
        if self._jwks_cache and now - self._jwks_fetched_at < self._JWKS_TTL:
            return self._jwks_cache

        import httpx
        oidc_config_url = f"{self._oidc_issuer}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=10.0) as client:
            cfg_resp = await client.get(oidc_config_url)
            cfg_resp.raise_for_status()
            jwks_uri = cfg_resp.json()["jwks_uri"]

            jwks_resp = await client.get(jwks_uri)
            jwks_resp.raise_for_status()
            self._jwks_cache = jwks_resp.json()

        self._jwks_fetched_at = now
        logger.info(f"[Auth] JWKS refreshed from {self._oidc_issuer}")
        return self._jwks_cache

    def create_local_token(
        self,
        user_id: str,
        tenant_id: str,
        email: str = "",
        roles: list[str] | None = None,
        expire_minutes: int | None = None,
    ) -> str:
        """
        为本地 JWT 模式签发 Token。
        仅用于开发/测试；生产环境 Token 由 OIDC Provider 签发。
        """
        from jose import jwt as jose_jwt
        expire = expire_minutes or settings.jwt_expire_minutes
        now = int(time.time())
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "roles": roles or ["viewer"],
            "iat": now,
            "exp": now + expire * 60,
        }
        return jose_jwt.encode(
            payload,
            settings.secret_key,
            algorithm=settings.jwt_algorithm,
        )


_auth_service: OIDCAuthService | None = None


def get_auth_service() -> OIDCAuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = OIDCAuthService()
    return _auth_service


_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """FastAPI dependency: extract + verify JWT Bearer token.

    Returns the authenticated user, or raises 401 with a sanitized detail.
    Used by Phase 5 routes (POST /ingest/async, GET /ingest/status/{task_id})
    per ASVS V2 (Authentication) and V4 (Access Control) requirements.

    SECURITY: auto_error=False prevents FastAPI's default 403 on missing
    Authorization header — we explicitly raise 401 to match standard
    "Authorization required" semantics. Error messages are static (no
    token contents echoed back) to prevent token-shape leakage.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authorization required")
    user = await get_auth_service().verify_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user
