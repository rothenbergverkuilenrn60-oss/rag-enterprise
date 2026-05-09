"""tests/unit/test_audit_service_helpers.py — Phase 15 backfill.

Covers AuditService helper methods (log_query, log_ingest, log_permission_denied,
log_pii_detected, log_rule_blocked), explicit flush(), and _flush_to_db()
success + error paths. Existing tests/unit/test_audit_service.py covers
log() core branching; this file targets the previously-uncovered surface.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import asyncio
from unittest.mock import AsyncMock

import pytest


@pytest.fixture(autouse=True)
def reset_audit_singleton(monkeypatch):
    import services.audit.audit_service as mod
    yield
    monkeypatch.setattr(mod, "_audit_service", None, raising=False)


def _make_service():
    import services.audit.audit_service as audit_mod
    svc = audit_mod.AuditService.__new__(audit_mod.AuditService)
    svc._buffer = []
    svc._last_flush = 0.0
    svc._lock = asyncio.Lock()
    return svc


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_query_emits_query_event(monkeypatch):
    import services.audit.audit_service as mod
    monkeypatch.setattr(mod.settings, "audit_enabled", True)
    monkeypatch.setattr(mod.settings, "audit_db_enabled", False)

    svc = _make_service()
    captured: list = []

    async def capture(event):
        captured.append(event)

    monkeypatch.setattr(svc, "log", capture)
    await svc.log_query(
        user_id="u1", tenant_id="t1", query="hello world",
        trace_id="trace-abc", latency_ms=12.3, sources_count=3, intent="ASK",
    )
    assert len(captured) == 1
    ev = captured[0]
    assert ev.action == mod.AuditAction.QUERY
    assert ev.user_id == "u1"
    assert ev.detail["latency_ms"] == 12.3
    assert ev.detail["intent"] == "ASK"
    assert ev.detail["query_len"] == len("hello world")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_ingest_emits_ingest_event(monkeypatch):
    import services.audit.audit_service as mod
    svc = _make_service()
    captured: list = []

    async def capture(event):
        captured.append(event)

    monkeypatch.setattr(svc, "log", capture)
    await svc.log_ingest(
        user_id="u1", tenant_id="t1", doc_id="doc-1",
        file_name="x.pdf", chunk_count=5, pii_detected=True,
    )
    ev = captured[0]
    assert ev.action == mod.AuditAction.INGEST
    assert ev.detail["pii_detected"] is True
    assert ev.detail["chunk_count"] == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_permission_denied_marks_blocked(monkeypatch):
    import services.audit.audit_service as mod
    svc = _make_service()
    captured: list = []

    async def capture(event):
        captured.append(event)

    monkeypatch.setattr(svc, "log", capture)
    await svc.log_permission_denied(
        user_id="u1", tenant_id="t1", trace_id="trace-1",
        ip_address="10.0.0.1", reason="missing scope",
    )
    ev = captured[0]
    assert ev.action == mod.AuditAction.PERMISSION_DENIED
    assert ev.result == mod.AuditResult.BLOCKED
    assert ev.detail["reason"] == "missing scope"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_pii_detected_counts_default_to_len(monkeypatch):
    import services.audit.audit_service as mod
    svc = _make_service()
    captured: list = []

    async def capture(event):
        captured.append(event)

    monkeypatch.setattr(svc, "log", capture)
    await svc.log_pii_detected(
        user_id="u1", tenant_id="t1", doc_id="d1",
        pii_types=["EMAIL", "PHONE"],
    )
    ev = captured[0]
    assert ev.action == mod.AuditAction.PII_DETECTED
    assert ev.detail["count"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_log_rule_blocked_truncates_message(monkeypatch):
    import services.audit.audit_service as mod
    svc = _make_service()
    captured: list = []

    async def capture(event):
        captured.append(event)

    monkeypatch.setattr(svc, "log", capture)
    long_msg = "x" * 500
    await svc.log_rule_blocked(
        user_id="u1", tenant_id="t1", trace_id="t",
        stage="generate", message=long_msg,
    )
    ev = captured[0]
    assert ev.action == mod.AuditAction.RULE_BLOCKED
    assert len(ev.detail["message"]) == 200


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_no_op_when_db_disabled(monkeypatch):
    import services.audit.audit_service as mod
    monkeypatch.setattr(mod.settings, "audit_db_enabled", False)
    svc = _make_service()
    flush_mock = AsyncMock()
    monkeypatch.setattr(svc, "_flush_to_db", flush_mock)
    await svc.flush()
    flush_mock.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_calls_flush_to_db_when_db_enabled(monkeypatch):
    import services.audit.audit_service as mod
    monkeypatch.setattr(mod.settings, "audit_db_enabled", True)
    svc = _make_service()
    flush_mock = AsyncMock()
    monkeypatch.setattr(svc, "_flush_to_db", flush_mock)
    await svc.flush()
    flush_mock.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_to_db_empty_buffer_returns_immediately():
    """No-op: empty buffer short-circuits before any DB import."""
    svc = _make_service()
    svc._buffer = []
    await svc._flush_to_db()
    assert svc._buffer == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flush_to_db_db_failure_requeues_events(monkeypatch):
    """Error path: DB write failure must NOT propagate; events re-enter buffer."""
    import sys

    import services.audit.audit_service as mod
    monkeypatch.setattr(mod.settings, "pg_dsn", "postgresql://invalid:5432/x")

    fake_asyncpg = type("FakeAsyncpg", (), {})()

    async def boom(*_a, **_kw):
        raise RuntimeError("connect refused")

    fake_asyncpg.connect = boom
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)

    svc = _make_service()
    svc._buffer = [
        mod.AuditEvent(user_id="u1", tenant_id="t1", action="QUERY"),
        mod.AuditEvent(user_id="u2", tenant_id="t1", action="QUERY"),
    ]
    await svc._flush_to_db()
    assert len(svc._buffer) == 2
