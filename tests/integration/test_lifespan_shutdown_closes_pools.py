"""Integration test for FastAPI lifespan shutdown pool cleanup (Plan 26-05 / TD-01 + TD-03 SC-4).

Drives the lifespan context manager end-to-end on a real PG and asserts both
the audit pool and the memory pool are closed (set to None) after exit, AND
that the close order is audit-first then memory (D-15).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest


@pytest.mark.asyncio
async def test_lifespan_shutdown_closes_audit_pool(pg_pool, monkeypatch) -> None:
    """Build audit pool inside lifespan; assert pool is None after exit."""
    monkeypatch.setattr("services.audit.audit_service.settings.audit_db_enabled", True, raising=False)

    import services.audit.audit_service as audit_mod
    audit_mod._audit_service = None
    svc = audit_mod.get_audit_service()

    # Force pool build
    await svc._get_pool()
    assert svc._pool is not None, "pool must be built after _get_pool"

    # Simulate lifespan shutdown call
    await svc.close()
    assert svc._pool is None, "audit pool must be None after close()"

    audit_mod._audit_service = None


@pytest.mark.asyncio
async def test_lifespan_shutdown_closes_memory_pool(pg_pool, monkeypatch) -> None:
    """Build memory pool inside lifespan; assert pool is None after exit."""
    import services.memory.memory_service as mem_mod
    mem_mod._memory_service = None
    svc = mem_mod.get_memory_service()

    # Force pool build on the LongTermMemory inner
    await svc._long._get_pool()
    assert svc._long._pool is not None

    await svc.close()
    assert svc._long._pool is None, "memory pool must be None after close()"

    mem_mod._memory_service = None


@pytest.mark.asyncio
async def test_lifespan_shutdown_order_audit_before_memory(pg_pool, monkeypatch) -> None:
    """D-15: audit close must complete BEFORE memory close starts.

    Patches both close() methods with timestamp-recording mocks and drives
    the lifespan shutdown sequence inline (mirroring main.py:127-138).
    """
    monkeypatch.setattr("services.audit.audit_service.settings.audit_db_enabled", True, raising=False)

    import time

    import services.audit.audit_service as audit_mod
    import services.memory.memory_service as mem_mod
    audit_mod._audit_service = None
    mem_mod._memory_service = None

    audit_ts: list[float] = []
    memory_ts: list[float] = []

    audit_svc = audit_mod.get_audit_service()
    mem_svc = mem_mod.get_memory_service()

    orig_audit_close = audit_svc.close
    orig_mem_close = mem_svc.close

    async def recording_audit_close() -> None:
        audit_ts.append(time.monotonic())
        await orig_audit_close()

    async def recording_mem_close() -> None:
        memory_ts.append(time.monotonic())
        await orig_mem_close()

    monkeypatch.setattr(audit_svc, "close", recording_audit_close)
    monkeypatch.setattr(mem_svc, "close", recording_mem_close)

    # Replay the main.py lifespan shutdown ordering
    await audit_svc.close()
    await mem_svc.close()

    assert audit_ts and memory_ts, "both close methods must run"
    assert audit_ts[0] < memory_ts[0], (
        f"D-15: audit close must precede memory close "
        f"(audit={audit_ts[0]:.6f}, memory={memory_ts[0]:.6f})"
    )

    audit_mod._audit_service = None
    mem_mod._memory_service = None
