"""
tests/unit/test_rate_limiting.py
TDD RED: Per-route slowapi rate limiting for ingest and query routes (SEC-02)

Tests verify:
  - POST /api/v1/ingest is limited to rate_limit_ingest_rpm (10/minute)
  - POST /api/v1/query is limited to rate_limit_query_rpm (30/minute)
  - A single request is not rate-limited
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

# Must import before patch() resolves "controllers.api.*" attribute lookups
import controllers.api  # noqa: E402

_INGEST_URL = "/api/v1/ingest"
_INGEST_BODY = {"file_path": "/tmp/test.txt", "metadata": {"tenant_id": "t1", "user_id": "u1"}}
_QUERY_URL = "/api/v1/query"
_QUERY_BODY = {"query": "What is the leave policy?", "tenant_id": "t1"}


def _make_mock_ingest_pipeline():
    pipeline = AsyncMock()
    resp = MagicMock()
    resp.success = True
    resp.error = None
    resp.doc_id = "test-doc"
    resp.total_chunks = 1
    resp.model_dump = lambda **kw: {"doc_id": "test-doc", "success": True, "total_chunks": 1}
    pipeline.run.return_value = resp
    return pipeline


def _make_mock_query_pipeline():
    pipeline = AsyncMock()
    resp = MagicMock()
    resp.success = True
    resp.answer = "test answer"
    resp.trace_id = "trace-1"
    resp.model_dump = lambda **kw: {"answer": "test answer", "trace_id": "trace-1"}
    pipeline.run.return_value = resp
    pipeline.stream = AsyncMock()
    return pipeline


@pytest.fixture(autouse=True)
def reset_limiter():
    """Reset slowapi in-memory rate limit counters before/after each test."""
    def _reset():
        try:
            from controllers.api import limiter as _lim
            storage = _lim._storage
            if hasattr(storage, "reset"):
                storage.reset()
            elif hasattr(storage, "_data"):
                storage._data.clear()
        except Exception:
            pass
    _reset()
    yield
    _reset()


class TestRateLimiting:
    def test_ingest_rate_limited_after_10_requests(self):
        """11th POST /api/v1/ingest from same IP returns 429."""
        from fastapi.testclient import TestClient

        mock_pipeline = _make_mock_ingest_pipeline()
        with patch("controllers.api.get_ingest_pipeline", return_value=mock_pipeline):
            from main import app
            client = TestClient(app, raise_server_exceptions=False)

            statuses = []
            for _ in range(11):
                r = client.post(_INGEST_URL, json=_INGEST_BODY)
                statuses.append(r.status_code)

        assert statuses[-1] == 429, (
            f"Expected 429 on 11th request, got statuses: {statuses}"
        )

    def test_ingest_single_request_not_rate_limited(self):
        """Single POST /api/v1/ingest is not blocked by the rate limiter."""
        from fastapi.testclient import TestClient

        mock_pipeline = _make_mock_ingest_pipeline()
        with patch("controllers.api.get_ingest_pipeline", return_value=mock_pipeline):
            from main import app
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post(_INGEST_URL, json=_INGEST_BODY)

        assert r.status_code != 429, (
            f"Single request should not be rate-limited, got {r.status_code}"
        )

    def test_query_rate_limited_after_30_requests(self):
        """31st POST /api/v1/query from same IP returns 429."""
        from fastapi.testclient import TestClient

        mock_pipeline = _make_mock_query_pipeline()
        with patch("controllers.api.get_query_pipeline", return_value=mock_pipeline), \
             patch("controllers.api.get_agent_pipeline", return_value=mock_pipeline):
            from main import app
            client = TestClient(app, raise_server_exceptions=False)

            statuses = []
            for _ in range(31):
                r = client.post(_QUERY_URL, json=_QUERY_BODY)
                statuses.append(r.status_code)

        assert statuses[-1] == 429, (
            f"Expected 429 on 31st query request, got statuses: {statuses}"
        )
