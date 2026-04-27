"""Failing test stubs for POST /ingest/async and GET /ingest/status/{task_id} (Plan 05-01, RED phase).

Covers ASYNC-01 and ASYNC-02 acceptance behaviors for the async ingest API surface.
These tests MUST FAIL until Plan 05-03 creates the routes — intentional TDD scaffolding.

Fixtures use FakeAsyncRedis + monkeypatching of arq.jobs.Job to avoid coupling
to ARQ's internal msgpack serialization format.
"""
from __future__ import annotations

import time
import pytest
import pytest_asyncio
import fakeredis
from unittest.mock import MagicMock, AsyncMock, patch
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def fake_arq_redis():
    """In-process FakeAsyncRedis instance shared across tests in a session."""
    server = fakeredis.FakeServer()
    client = fakeredis.FakeAsyncRedis(server=server)
    # ARQ pools expose enqueue_job; add sentinel so monkeypatch.setattr(raising=True) works
    client.enqueue_job = AsyncMock()
    yield client
    await client.aclose()


@pytest.fixture
def fake_user_tenant_a():
    """AuthenticatedUser for tenant-A — injected via dependency override."""
    from services.auth.oidc_auth import AuthenticatedUser
    return AuthenticatedUser(user_id="u1", tenant_id="tenant-A", roles=["user"])


@pytest.fixture
def fake_user_tenant_b():
    """AuthenticatedUser for tenant-B — used to test cross-tenant access denial."""
    from services.auth.oidc_auth import AuthenticatedUser
    return AuthenticatedUser(user_id="u2", tenant_id="tenant-B", roles=["user"])


@pytest.fixture
def auth_headers():
    """Bearer token header for authenticated requests."""
    return {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# Test 1 — POST /ingest/async returns 202 + task_id within 200ms (ASYNC-01)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_async_ingest_returns_task_id(
    fake_arq_redis, fake_user_tenant_a, auth_headers, monkeypatch
) -> None:
    """POST /ingest/async returns 202 + non-empty task_id in under 200ms."""
    from main import app
    from services.auth.oidc_auth import get_current_user

    mock_job = MagicMock()
    mock_job.job_id = "test-task-id-1234"
    monkeypatch.setattr(fake_arq_redis, "enqueue_job", AsyncMock(return_value=mock_job))
    app.state.arq_redis = fake_arq_redis

    async def _fake_user():
        return fake_user_tenant_a

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        client = TestClient(app)
        start = time.perf_counter()
        resp = client.post(
            "/api/v1/ingest/async",
            json={"doc_id": "d1", "content": "hello", "tenant_id": "tenant-A"},
            headers=auth_headers,
        )
        elapsed = time.perf_counter() - start

        assert resp.status_code == 202
        data = resp.json()["data"]
        assert data["task_id"] == "test-task-id-1234"
        assert data["status"] == "queued"
        assert elapsed < 0.2, f"Latency {elapsed * 1000:.0f}ms exceeds 200ms"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Test 2 — POST /ingest/async enqueues job with correct args
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_async_ingest_enqueues_job(
    fake_arq_redis, fake_user_tenant_a, auth_headers, monkeypatch
) -> None:
    """POST /ingest/async calls arq_redis.enqueue_job('ingest_task', req payload)."""
    from main import app
    from services.auth.oidc_auth import get_current_user

    mock_job = MagicMock()
    mock_job.job_id = "job-abc"
    enqueue_mock = AsyncMock(return_value=mock_job)
    monkeypatch.setattr(fake_arq_redis, "enqueue_job", enqueue_mock)
    app.state.arq_redis = fake_arq_redis

    async def _fake_user():
        return fake_user_tenant_a

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        client = TestClient(app)
        payload = {"doc_id": "d2", "content": "text", "tenant_id": "tenant-A"}
        client.post("/api/v1/ingest/async", json=payload, headers=auth_headers)

        enqueue_mock.assert_awaited_once()
        call_args = enqueue_mock.call_args
        assert call_args[0][0] == "ingest_task"
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Test 3 — POST /ingest/async requires auth (401 without Bearer)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_async_ingest_requires_auth(fake_arq_redis) -> None:
    """POST /ingest/async without Authorization header returns 401."""
    from main import app
    app.state.arq_redis = fake_arq_redis
    client = TestClient(app)
    resp = client.post(
        "/api/v1/ingest/async",
        json={"doc_id": "d3", "content": "test", "tenant_id": "tenant-A"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 4 — GET /ingest/status/{id}: pending for queued (not yet complete) job
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_status_pending_for_queued_job(
    fake_arq_redis, fake_user_tenant_a, auth_headers, monkeypatch
) -> None:
    """GET /ingest/status/{id} returns 200 + status='pending' when job is queued but not finished."""
    from main import app
    from services.auth.oidc_auth import get_current_user

    task_id = "pending-task-001"
    app.state.arq_redis = fake_arq_redis

    mock_job_info = MagicMock()
    mock_job_info.status = "queued"
    mock_job_info.result = None
    mock_job_info.tenant_id = "tenant-A"

    with patch("arq.jobs.Job.info", new=AsyncMock(return_value=mock_job_info)):
        with patch("arq.jobs.Job.status", new=AsyncMock(return_value="queued")):
            async def _fake_user():
                return fake_user_tenant_a

            app.dependency_overrides[get_current_user] = _fake_user
            try:
                client = TestClient(app)
                resp = client.get(f"/api/v1/ingest/status/{task_id}", headers=auth_headers)
                assert resp.status_code == 200
                assert resp.json()["data"]["status"] == "pending"
            finally:
                app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Test 5 — GET /ingest/status/{id}: complete with doc_id
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_status_complete_with_doc_id(
    fake_arq_redis, fake_user_tenant_a, auth_headers, monkeypatch
) -> None:
    """GET /ingest/status/{id} returns 200 + status='complete' + error=None for finished job."""
    from main import app
    from services.auth.oidc_auth import get_current_user

    task_id = "complete-task-001"
    app.state.arq_redis = fake_arq_redis

    mock_job_info = MagicMock()
    mock_job_info.result = {"doc_id": "doc-xyz", "success": True, "error": None, "tenant_id": "tenant-A"}
    mock_job_info.success = True

    with patch("arq.jobs.Job.info", new=AsyncMock(return_value=mock_job_info)):
        with patch("arq.jobs.Job.status", new=AsyncMock(return_value="complete")):
            async def _fake_user():
                return fake_user_tenant_a

            app.dependency_overrides[get_current_user] = _fake_user
            try:
                client = TestClient(app)
                resp = client.get(f"/api/v1/ingest/status/{task_id}", headers=auth_headers)
                assert resp.status_code == 200
                data = resp.json()["data"]
                assert data["status"] == "complete"
                assert data["error"] is None
            finally:
                app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Test 6 — GET /ingest/status/{id}: failed with error detail
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_status_failed_with_error_detail(
    fake_arq_redis, fake_user_tenant_a, auth_headers, monkeypatch
) -> None:
    """GET /ingest/status/{id} returns 200 + status='failed' + error detail for failed job."""
    from main import app
    from services.auth.oidc_auth import get_current_user

    task_id = "failed-task-001"
    app.state.arq_redis = fake_arq_redis

    mock_job_info = MagicMock()
    mock_job_info.result = {"doc_id": None, "success": False, "error": "pipeline boom", "tenant_id": "tenant-A"}
    mock_job_info.success = False

    with patch("arq.jobs.Job.info", new=AsyncMock(return_value=mock_job_info)):
        with patch("arq.jobs.Job.status", new=AsyncMock(return_value="complete")):
            async def _fake_user():
                return fake_user_tenant_a

            app.dependency_overrides[get_current_user] = _fake_user
            try:
                client = TestClient(app)
                resp = client.get(f"/api/v1/ingest/status/{task_id}", headers=auth_headers)
                assert resp.status_code == 200
                data = resp.json()["data"]
                assert data["status"] == "failed"
                assert data["error"] == "pipeline boom"
            finally:
                app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Test 7 — GET /ingest/status/{id}: 404 when task_id unknown
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_status_404_when_key_absent(
    fake_arq_redis, fake_user_tenant_a, auth_headers
) -> None:
    """GET /ingest/status/{id} returns 404 when task_id has no result (unknown or expired)."""
    from main import app
    from services.auth.oidc_auth import get_current_user

    app.state.arq_redis = fake_arq_redis

    with patch("arq.jobs.Job.info", new=AsyncMock(return_value=None)):
        with patch("arq.jobs.Job.status", new=AsyncMock(return_value=None)):
            async def _fake_user():
                return fake_user_tenant_a

            app.dependency_overrides[get_current_user] = _fake_user
            try:
                client = TestClient(app)
                resp = client.get("/api/v1/ingest/status/nonexistent-task-id", headers=auth_headers)
                assert resp.status_code == 404
            finally:
                app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Test 8 — GET /ingest/status/{id}: 404 (NOT 403) for cross-tenant access
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_status_404_when_cross_tenant_access(
    fake_arq_redis, fake_user_tenant_b, auth_headers
) -> None:
    """Tenant-B token trying to read tenant-A's task_id gets 404, not 403 (IDOR prevention)."""
    from main import app
    from services.auth.oidc_auth import get_current_user

    task_id = "tenant-a-task-001"
    app.state.arq_redis = fake_arq_redis

    mock_job_info = MagicMock()
    mock_job_info.result = {"doc_id": "doc-a", "success": True, "error": None, "tenant_id": "tenant-A"}

    with patch("arq.jobs.Job.info", new=AsyncMock(return_value=mock_job_info)):
        with patch("arq.jobs.Job.status", new=AsyncMock(return_value="complete")):
            async def _fake_user_b():
                return fake_user_tenant_b

            app.dependency_overrides[get_current_user] = _fake_user_b
            try:
                client = TestClient(app)
                resp = client.get(f"/api/v1/ingest/status/{task_id}", headers=auth_headers)
                assert resp.status_code == 404, (
                    f"Cross-tenant access must return 404 (not 403) to prevent IDOR; got {resp.status_code}"
                )
            finally:
                app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Test 9 — GET /ingest/status/{id}: 400 for malformed task_id
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_status_400_on_invalid_task_id_format(
    fake_arq_redis, fake_user_tenant_a, auth_headers
) -> None:
    """GET /ingest/status/{id} returns 400 when task_id contains invalid characters."""
    from main import app
    from services.auth.oidc_auth import get_current_user

    app.state.arq_redis = fake_arq_redis

    async def _fake_user():
        return fake_user_tenant_a

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        client = TestClient(app)
        resp = client.get(
            "/api/v1/ingest/status/'; DROP TABLE jobs--",
            headers=auth_headers,
        )
        assert resp.status_code == 400
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# Test 10 — GET /ingest/status/{id}: 401 without Authorization header
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_status_requires_auth(fake_arq_redis) -> None:
    """GET /ingest/status/{id} without Authorization header returns 401."""
    from main import app
    app.state.arq_redis = fake_arq_redis
    client = TestClient(app)
    resp = client.get("/api/v1/ingest/status/some-task-id")
    assert resp.status_code == 401
