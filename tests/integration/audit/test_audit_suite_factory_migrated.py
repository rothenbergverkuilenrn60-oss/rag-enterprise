"""SC-1 audit-side coverage — audit integration suite migrated to `app_factory`.

Plan 27-01 Task 3.

Phase 23 / Phase 26 audit integration tests use the manual-reset pattern:

    import services.audit.audit_service as audit_mod
    audit_mod._audit_service = None
    svc = audit_mod.get_audit_service()

This file ports that pattern to the brute-force factory:

    app = app_factory()  # resets all 34 singletons including _audit_service
    svc = audit_mod.get_audit_service()  # fresh service

Per CONTEXT D-05 the existing `test_audit_log_auto_create.py` is NOT modified —
the migration directive in CONTEXT SC-1 ("audit + memory integration suites
construct an isolated app per test through this factory") is interpreted per
RESEARCH §Theme 1 lines 503-512 as "add ≥1 new test per suite that DOES go
through the factory," NOT "rewrite existing tests."

Tests skip cleanly when PostgreSQL is unavailable (Pattern E pytestmark
skip-gate).
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")
os.environ.setdefault("APP_AUDIT_DB_ENABLED", "true")

from collections.abc import Callable
from typing import Any

import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not PG_AVAILABLE, reason="needs live PostgreSQL"),
]


@pytest.mark.asyncio
async def test_audit_log_write_via_factory(
    pg_pool: Any,
    app_factory: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construct an isolated app via app_factory, force-create audit_log via the
    Phase 26 TD-01 auto-create path, write an event, assert the row landed.

    This is the migration of the `test_audit_log_auto_create.py:17-61` pattern
    off `audit_mod._audit_service = None` onto `app_factory()` — which resets
    every singleton (not just `_audit_service`) and so makes the test
    self-contained from any prior test's mutation.
    """
    # 1. Drop audit_log so the next access exercises the TD-01 auto-create path.
    async with pg_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS audit_log CASCADE;")

    # 2. Enable DB-bound audit writes for this test (defaults to False).
    monkeypatch.setattr(
        "services.audit.audit_service.settings.audit_db_enabled",
        True,
        raising=False,
    )

    # 3. Build an isolated app — resets _audit_service (and 33 other singletons).
    app = app_factory()
    assert app is not None

    # 4. Acquire a fresh service through the canonical accessor.
    import services.audit.audit_service as audit_mod
    from services.audit.audit_service import AuditAction, AuditEvent

    svc = audit_mod.get_audit_service()

    # 5. Push one event + flush (mirrors test_audit_log_auto_create.py:35-41).
    event = AuditEvent(
        user_id="factory-migrated-user",
        tenant_id="factory-migrated-tenant",
        action=AuditAction.QUERY,
        resource_id="factory-migrated-resource",
    )
    svc._buffer.append(event)
    await svc.flush()

    # 6. Assert the row landed.
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, action, resource_id FROM audit_log "
            "WHERE resource_id = $1",
            "factory-migrated-resource",
        )
    assert len(rows) == 1, f"expected exactly 1 row, got {len(rows)}"
    assert rows[0]["user_id"] == "factory-migrated-user"
    assert rows[0]["action"] == "QUERY"

    # 7. Clean shutdown — close service pool so the next test starts clean.
    await svc.close()


@pytest.mark.asyncio
async def test_audit_factory_resets_service_singleton(
    pg_pool: Any,
    app_factory: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two `app_factory()` calls must surface two distinct `AuditService`
    instances — proves the factory's brute-force `_reset_singletons()` covers
    `services.audit.audit_service._audit_service`.

    This is the assertion that "audit suite is migrated to the factory" in a
    structural sense: the factory replaces the prior manual reset.
    """
    monkeypatch.setattr(
        "services.audit.audit_service.settings.audit_db_enabled",
        True,
        raising=False,
    )

    import services.audit.audit_service as audit_mod

    # First app + first audit service.
    _app_a = app_factory()
    svc_a = audit_mod.get_audit_service()

    # Second app — factory resets _audit_service to None.
    _app_b = app_factory()
    svc_b = audit_mod.get_audit_service()

    assert svc_a is not svc_b, (
        "app_factory() did not reset _audit_service; "
        "two factory calls returned the same AuditService instance, "
        "which means cross-test audit state would leak"
    )

    # Best-effort teardown (a fresh service may not have an open pool).
    try:
        await svc_b.close()
    except Exception:  # noqa: BLE001 — teardown best-effort
        pass
