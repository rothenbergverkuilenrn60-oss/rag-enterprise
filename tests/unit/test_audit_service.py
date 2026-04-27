from __future__ import annotations
import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Autouse fixture: reset singleton between tests (T-06-06)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_audit_singleton(monkeypatch):
    import services.audit.audit_service as mod
    yield
    monkeypatch.setattr(mod, "_audit_service", None, raising=False)


# ---------------------------------------------------------------------------
# Helper: build a bare AuditService bypassing __init__ side effects
# ---------------------------------------------------------------------------
def _make_service():
    import services.audit.audit_service as audit_mod
    svc = audit_mod.AuditService.__new__(audit_mod.AuditService)
    svc._buffer = []
    svc._last_flush = 0.0
    svc._lock = asyncio.Lock()
    return svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_log_no_db_when_disabled(monkeypatch):
    """With audit_db_enabled=False, log() writes file but never flushes to DB."""
    import services.audit.audit_service as audit_mod
    monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", False)
    monkeypatch.setattr(audit_mod.settings, "audit_enabled", True)

    svc = _make_service()
    flush_mock = AsyncMock()
    monkeypatch.setattr(svc, "_flush_to_db", flush_mock)

    event = audit_mod.AuditEvent(user_id="u1", tenant_id="t1", action="QUERY")
    await svc.log(event)

    # Buffer stays empty because audit_db_enabled=False
    assert len(svc._buffer) == 0
    flush_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_audit_log_disabled_overall_is_noop(monkeypatch):
    """With audit_enabled=False, log() returns immediately; _buffer stays empty."""
    import services.audit.audit_service as audit_mod
    monkeypatch.setattr(audit_mod.settings, "audit_enabled", False)
    monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", False)

    svc = _make_service()
    event = audit_mod.AuditEvent(user_id="u2", tenant_id="t2", action="INGEST")
    await svc.log(event)

    assert len(svc._buffer) == 0


@pytest.mark.asyncio
async def test_audit_buffer_grows_until_flush(monkeypatch):
    """With audit_db_enabled=True but buffer below threshold, buffer grows."""
    import services.audit.audit_service as audit_mod
    import time as _time
    monkeypatch.setattr(audit_mod.settings, "audit_enabled", True)
    monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", True)

    svc = _make_service()
    # Set _last_flush to now so flush timer doesn't trigger
    svc._last_flush = _time.time()

    # Stub _flush_to_db so no real DB call is made
    flush_mock = AsyncMock()
    monkeypatch.setattr(svc, "_flush_to_db", flush_mock)

    for i in range(3):
        event = audit_mod.AuditEvent(user_id=f"u{i}", tenant_id="t1", action="QUERY")
        await svc.log(event)

    assert len(svc._buffer) == 3


@pytest.mark.asyncio
async def test_audit_flush_to_db_called_when_time_threshold_exceeded(monkeypatch):
    """When time since last flush exceeds _FLUSH_SEC, _flush_to_db is called."""
    import services.audit.audit_service as audit_mod
    monkeypatch.setattr(audit_mod.settings, "audit_enabled", True)
    monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", True)

    svc = _make_service()
    # Set _last_flush far in the past so time threshold is exceeded
    svc._last_flush = 0.0

    flush_mock = AsyncMock()
    monkeypatch.setattr(svc, "_flush_to_db", flush_mock)

    event = audit_mod.AuditEvent(user_id="u1", tenant_id="t1", action="QUERY")
    await svc.log(event)

    flush_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_audit_flush_to_db_called_when_buffer_full(monkeypatch):
    """When buffer reaches _BUFFER_SIZE, _flush_to_db is called."""
    import services.audit.audit_service as audit_mod
    import time as _time
    monkeypatch.setattr(audit_mod.settings, "audit_enabled", True)
    monkeypatch.setattr(audit_mod.settings, "audit_db_enabled", True)

    svc = _make_service()
    svc._last_flush = _time.time()  # suppress time-based trigger

    flush_mock = AsyncMock()
    monkeypatch.setattr(svc, "_flush_to_db", flush_mock)

    # Prefill buffer to BUFFER_SIZE - 1
    svc._buffer = [
        audit_mod.AuditEvent(user_id=f"u{i}", tenant_id="t1", action="QUERY")
        for i in range(svc._BUFFER_SIZE - 1)
    ]

    # One more event should push it to exactly _BUFFER_SIZE and trigger flush
    event = audit_mod.AuditEvent(user_id="trigger", tenant_id="t1", action="QUERY")
    await svc.log(event)

    flush_mock.assert_awaited_once()


def test_audit_singleton_get_audit_service():
    """get_audit_service() returns the same instance on repeated calls."""
    import services.audit.audit_service as mod
    # Patch _setup_audit_logger to avoid creating real log files
    with patch.object(mod.AuditService, "_setup_audit_logger", return_value=None):
        svc1 = mod.get_audit_service()
        svc2 = mod.get_audit_service()
        assert svc1 is svc2
