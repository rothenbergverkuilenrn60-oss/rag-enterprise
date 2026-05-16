# =============================================================================
# controllers/memory.py
# GDPR forget API — DELETE /api/v1/memory/forget (Phase 25 / GDPR-02 + GDPR-03)
#
# Phase 25 (Wave 2 / Plan 25-04). Implements the controller half of GDPR-02
# (forget-user endpoint) on top of the service layer landed by Plan 25-02
# (LongTermMemory.forget_user) and the audit enum landed by Plan 25-01
# (AuditAction.MEMORY_FORGET).
#
# Body order (T9 — eng-review outside voice F3, fail-closed on identity first):
#   1. role gate         -> 403 if not (admin or self-delete)
#   2. confirm-header    -> 400 if X-Confirm-Delete != "yes"
#   3. user_id format    -> 404 if empty
#   4. forget_user call  -> 500 on MemoryForgetError (sanitized detail)
#   5. audit-after-DELETE with try/except (T1) — never propagates audit failure
# =============================================================================
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from loguru import logger

from config.settings import settings
from services.audit.audit_service import (
    AuditAction,
    AuditEvent,
    AuditResult,
    get_audit_service,
)
from services.auth.oidc_auth import AuthenticatedUser, get_current_user
from services.memory.memory_service import LongTermMemory, MemoryForgetError

# T2 (eng-review A2 / plan-check W3 / outside voice F5): mirror controllers/api.py:44.
# `settings.api_prefix` resolves to "/api/v1"; the full route is
# DELETE /api/v1/memory/forget.
router = APIRouter(prefix=settings.api_prefix)


@router.delete("/memory/forget", tags=["admin", "gdpr"])
async def forget_user_memory(
    user_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),                                  # Pitfall 7: Depends FIRST
    x_confirm_delete: str | None = Header(default=None, alias="X-Confirm-Delete"),        # Pitfall 6: alias + default=None
) -> dict[str, int]:
    """Delete all long_term_facts rows for ``user_id`` in the caller's tenant.

    Auth gate (T9 — role FIRST): admin claim OR self-delete
    (``jwt.user_id == user_id``). Confirmation header ``X-Confirm-Delete: yes``
    required after the role gate passes. Scope: ``long_term_facts`` only
    (D-1.2). Returns ``{"deleted_row_count": N}`` — 200 even when N == 0
    (idempotent; D-1.3). Tenant is bound to the JWT (T3 — cross-tenant
    forget is an idempotent 0-row no-op, not a privileged escape).
    """
    # ── 1. Role gate (T9 — checked BEFORE header so non-admin probes get 403, not 400) ──
    if not (user.is_admin or user.user_id == user_id):
        raise HTTPException(
            status_code=403,
            detail="forbidden: admin role or self-delete required",
        )

    # ── 2. Confirmation header gate (D-1.4 — only reached after role check) ──
    if x_confirm_delete != "yes":
        raise HTTPException(
            status_code=400,
            detail="X-Confirm-Delete: yes header required",
        )

    # ── 3. user_id format validation (D-1.3) ──
    if not user_id:
        raise HTTPException(status_code=404, detail="user_id required")

    # Tenant resolved from JWT only — never from a query param (D-1.2 invariant).
    target_tenant_id = user.tenant_id

    # ── 4. Execute forget (sanitized 500 on DB failure — D-1.5) ──
    mem = LongTermMemory()
    try:
        deleted_row_count = await mem.forget_user(user_id, target_tenant_id)
    except MemoryForgetError as exc:
        logger.error(
            "forget_user failed",
            operation="forget_user_controller",
            target_user_id=user_id,
            target_tenant_id=target_tenant_id,
            actor_user_id=user.user_id,
            exc_info=exc,
        )
        raise HTTPException(status_code=500, detail="Memory forget failed") from exc

    # ── 5. Audit AFTER DELETE (D-2.3 / SP-6) — wrapped in try/except (T1) ──
    ip_address = request.client.host if request.client else ""
    audit_detail = {
        "target_user_id": user_id,
        "target_tenant_id": target_tenant_id,
        "deleted_row_count": deleted_row_count,
        "actor_user_id": user.user_id,
        "actor_is_admin": user.is_admin,
        "requesting_ip": ip_address,
    }
    audit_event = AuditEvent(
        user_id=user.user_id,
        tenant_id=target_tenant_id,
        action=AuditAction.MEMORY_FORGET,
        resource_id=user_id,
        ip_address=ip_address,
        result=AuditResult.SUCCESS,
        detail=audit_detail,
    )
    try:
        await get_audit_service().log(audit_event)
    # T1 eng-review (Architecture A1): audit write must not fail GDPR action.
    # This is the ONE exception to ERR-01's narrow-except rule, intentionally
    # bounded to a single call (get_audit_service().log) with full structured
    # logging on the failure path. See 25-ENG-REVIEW.md T1 for context.
    except Exception as audit_exc:  # noqa: BLE001 — T1 eng-review
        # GDPR action is already committed; surface the failure as a loud
        # structured ERROR log carrying the entire would-be detail payload
        # so operators can reconstruct the missing audit row from logs.
        logger.error(
            "audit log write failed after forget (data already deleted)",
            operation="forget_audit_log",
            audit_payload=audit_detail,
            target_user_id=user_id,
            target_tenant_id=target_tenant_id,
            deleted_row_count=deleted_row_count,
            actor_user_id=user.user_id,
            actor_is_admin=user.is_admin,
            requesting_ip=ip_address,
            exc_info=audit_exc,
        )

    return {"deleted_row_count": deleted_row_count}
