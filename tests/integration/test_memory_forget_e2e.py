"""Integration tests for Plan 25-04 / SC-3 + SC-4 — GDPR forget API e2e.

Covers ROADMAP success criteria:
    SC-3 — DELETE /api/v1/memory/forget?user_id=alice with admin JWT
           returns 200 + deleted_row_count; re-call returns 0 (idempotent);
           a non-admin JWT for a DIFFERENT target user_id returns 403.
    SC-4 — MEMORY_FORGET audit_log row retrievable from the audit_log
           table with the correct detail fields (target_user_id,
           target_tenant_id, deleted_row_count, actor_user_id).

Drives the FastAPI app via TestClient (DELETE /api/v1/memory/forget) against
the live pgvector pool. Auth is mocked at the singleton-factory boundary
(`services.auth.oidc_auth.get_auth_service`) per the unit-test pattern.

Pitfall 3 (25-RESEARCH.md): SC-4 requires the audit DB writer to be enabled
— ``settings.audit_db_enabled`` defaults to ``False``. Test 4 patches it to
``True`` AND awaits ``get_audit_service().flush()`` so the buffered event is
forced to the audit_log table before the SELECT count(*) assertion fires.

T4 (eng-review amendment): ``_seed_facts`` inserts ``embedding=[0.0] * 1024``
on every row — mirror the eviction-e2e seed helper shape so a future
``NOT NULL`` migration on the ``embedding`` column does not silently break
this suite.

Skip-gated on ``PG_AVAILABLE`` so the suite collects + skips gracefully
on CI hosts without a live PostgreSQL + pgvector instance.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.skipif(not PG_AVAILABLE, reason="PostgreSQL + pgvector not available — skipping GDPR forget e2e tests"),
]

# Stable test-identity constants — scoped DELETE in clean_long_term_facts.
_USER_ID = "test-gdpr25-alice"
_OTHER_USER = "test-gdpr25-bob"
_TENANT = "test-gdpr25-t"
_FORGET_URL = "/api/v1/memory/forget"
_AUTH_HEADERS = {"Authorization": "Bearer fake", "X-Confirm-Delete": "yes"}


def _fake_admin():
    from services.auth.oidc_auth import AuthenticatedUser
    return AuthenticatedUser(user_id="admin-user", tenant_id=_TENANT, roles=["admin"])


def _fake_self():
    from services.auth.oidc_auth import AuthenticatedUser
    return AuthenticatedUser(user_id=_USER_ID, tenant_id=_TENANT, roles=["viewer"])


def _fake_other():
    """Non-admin user whose user_id differs from the forget target — 403 path."""
    from services.auth.oidc_auth import AuthenticatedUser
    return AuthenticatedUser(user_id=_OTHER_USER, tenant_id=_TENANT, roles=["viewer"])


def _install_auth_mock(monkeypatch: pytest.MonkeyPatch, return_user) -> MagicMock:
    """Patch the get_auth_service singleton-factory so verify_token returns
    ``return_user`` for every request the TestClient issues. Returns the
    MagicMock so the test can re-arm verify_token mid-flight if needed.
    """
    mock_svc = MagicMock()
    mock_svc.verify_token = AsyncMock(return_value=return_user)
    monkeypatch.setattr(
        "services.auth.oidc_auth.get_auth_service", lambda: mock_svc
    )
    return mock_svc


async def _seed_facts(
    pool: asyncpg.Pool,
    user_id: str,
    tenant_id: str,
    count: int = 5,
) -> None:
    """Seed ``count`` rows into ``long_term_facts`` for ``(user_id, tenant_id)``.

    T4: ``embedding=[0.0] * 1024`` (dummy 1024-dim zero vector) on every
    INSERT. The forget endpoint never reads embeddings either, but mirroring
    the eviction-e2e seed helper keeps the helper consistent across files
    and future-proofs against schema tightening to NOT NULL.
    """
    rows = [
        (user_id, tenant_id, f"forget-seed-{i}", 0.5, [0.0] * 1024)
        for i in range(count)
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO long_term_facts
                (user_id, tenant_id, fact, importance, embedding)
            VALUES ($1, $2, $3, $4, $5)
            """,
            rows,
        )


@pytest.mark.asyncio
async def test_forget_api_e2e_admin_200(
    pgvector_pool: asyncpg.Pool,
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-3 admin path: admin JWT + X-Confirm-Delete returns 200 with
    deleted_row_count matching the seeded row count; PG rows are gone.
    """
    from fastapi.testclient import TestClient

    from main import app

    _install_auth_mock(monkeypatch, _fake_admin())
    await _seed_facts(pgvector_pool, _USER_ID, _TENANT, count=5)

    with TestClient(app) as client:
        resp = client.delete(
            _FORGET_URL,
            params={"user_id": _USER_ID},
            headers=_AUTH_HEADERS,
        )

    assert resp.status_code == 200, f"expected 200; got {resp.status_code} {resp.text}"
    body = resp.json()
    assert body["deleted_row_count"] == 5, (
        f"deleted_row_count must equal seeded count (5); got {body}"
    )

    remaining = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        _USER_ID, _TENANT,
    )
    assert remaining == 0, f"forget must remove every row; {remaining} survive"


@pytest.mark.asyncio
async def test_forget_api_e2e_idempotent(
    pgvector_pool: asyncpg.Pool,
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-3 idempotent path: second forget call on the same (user_id, tenant_id)
    returns 200 with ``deleted_row_count=0`` — never 404, never 500.
    """
    from fastapi.testclient import TestClient

    from main import app

    _install_auth_mock(monkeypatch, _fake_admin())
    await _seed_facts(pgvector_pool, _USER_ID, _TENANT, count=5)

    with TestClient(app) as client:
        first = client.delete(
            _FORGET_URL, params={"user_id": _USER_ID}, headers=_AUTH_HEADERS,
        )
        assert first.status_code == 200
        assert first.json()["deleted_row_count"] == 5

        second = client.delete(
            _FORGET_URL, params={"user_id": _USER_ID}, headers=_AUTH_HEADERS,
        )

    assert second.status_code == 200, f"idempotent re-call must be 200; got {second.status_code}"
    assert second.json()["deleted_row_count"] == 0, (
        f"idempotent re-call must return deleted_row_count=0; got {second.json()}"
    )


def test_forget_api_e2e_non_admin_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-3 auth gate: non-admin JWT whose ``user_id`` differs from the
    forget target receives 403 (role check fires BEFORE the header check
    per controller body order T9).

    Sync test — no DB seed needed; the 403 must be returned before any
    pool acquisition, so this exercises the role gate in isolation.
    """
    from fastapi.testclient import TestClient

    from main import app

    _install_auth_mock(monkeypatch, _fake_other())

    with TestClient(app) as client:
        resp = client.delete(
            _FORGET_URL,
            params={"user_id": _USER_ID},  # Bob asks to delete Alice's data
            headers=_AUTH_HEADERS,
        )

    assert resp.status_code == 403, (
        f"non-admin attempting cross-user forget must get 403; got {resp.status_code} {resp.text}"
    )


@pytest.mark.asyncio
async def test_forget_api_audit_log_row(
    pgvector_pool: asyncpg.Pool,
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-4: MEMORY_FORGET audit_log row retrievable with correct detail fields.

    Pitfall 3 mitigation:
      1. Patch ``settings.audit_db_enabled = True`` so the audit buffer is
         actually flushed to PG (default False would emit file-only logs).
      2. Await ``get_audit_service().flush()`` AFTER the forget call so the
         buffered event is written to ``audit_log`` before the SELECT.

    Also wipes any prior MEMORY_FORGET rows for ``_USER_ID`` so the assertion
    counts only this test's audit row (audit_log is INSERT-ONLY at the app
    layer, but tests need a deterministic count).
    """
    from fastapi.testclient import TestClient

    import services.audit.audit_service as audit_mod
    from services.audit.audit_service import get_audit_service

    from main import app

    # Pitfall 3: enable DB writer for this test only.
    monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", True)

    # Reset audit singleton + buffer so this test owns its flush window.
    monkeypatch.setattr(audit_mod, "_audit_service", None, raising=False)

    # Best-effort: scope-purge any pre-existing audit_log rows for this user
    # so the count(*) assertion below is deterministic. audit_log may not
    # exist on a fresh DB — schema is created lazily on first flush — so
    # swallow undefined-table errors.
    async with pgvector_pool.acquire() as conn:
        try:
            await conn.execute(
                "DELETE FROM audit_log WHERE action=$1 AND resource_id=$2",
                "MEMORY_FORGET", _USER_ID,
            )
        except asyncpg.UndefinedTableError:
            pass

    _install_auth_mock(monkeypatch, _fake_admin())
    await _seed_facts(pgvector_pool, _USER_ID, _TENANT, count=3)

    with TestClient(app) as client:
        resp = client.delete(
            _FORGET_URL, params={"user_id": _USER_ID}, headers=_AUTH_HEADERS,
        )
    assert resp.status_code == 200
    assert resp.json()["deleted_row_count"] == 3

    # Pitfall 3: force-flush buffered audit events to PG before assertion.
    await get_audit_service().flush()

    rows = await pgvector_pool.fetch(
        """SELECT user_id, tenant_id, action, resource_id, result, detail
           FROM audit_log
           WHERE action=$1 AND resource_id=$2""",
        "MEMORY_FORGET", _USER_ID,
    )
    assert len(rows) == 1, (
        f"expected exactly one MEMORY_FORGET row for {_USER_ID}; got {len(rows)}"
    )
    row = rows[0]
    assert row["action"] == "MEMORY_FORGET"
    assert row["resource_id"] == _USER_ID

    # detail is JSONB — asyncpg returns it as a JSON string; parse it.
    import json
    detail_raw = row["detail"]
    detail = json.loads(detail_raw) if isinstance(detail_raw, str) else detail_raw
    assert detail["target_user_id"] == _USER_ID
    assert detail["target_tenant_id"] == _TENANT
    assert detail["deleted_row_count"] == 3
    assert "actor_user_id" in detail, "audit detail must include actor_user_id"
    assert detail["actor_user_id"] == "admin-user"
