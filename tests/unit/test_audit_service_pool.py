"""Unit tests for AuditService pool migration + _create_tables + close()
(Plan 26-04 / TD-01 + TD-03).

Mocks at consumer path (`services.audit.audit_service.*`) per v1.3 Phase 13
discipline. 10 tests total: 7 baseline + A2 lock + P1 partial-init + T1 R1 race.
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest


def _build_audit_service(monkeypatch) -> object:
    """Construct AuditService with mocked asyncpg + prepare_dsn."""
    from services.audit.audit_service import AuditService

    monkeypatch.setattr(
        "services.audit.audit_service.prepare_dsn",
        MagicMock(return_value=("postgresql://stub", {})),
    )
    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()
    create_pool_mock = AsyncMock(return_value=fake_pool)
    monkeypatch.setattr(
        "services.audit.audit_service.asyncpg.create_pool", create_pool_mock
    )
    return AuditService(), fake_pool, create_pool_mock


@pytest.mark.asyncio
async def test_get_pool_lazy_init(monkeypatch) -> None:
    svc, fake_pool, create_pool_mock = _build_audit_service(monkeypatch)
    monkeypatch.setattr(svc, "_create_tables", AsyncMock())

    await svc._get_pool()
    await svc._get_pool()

    assert create_pool_mock.await_count == 1, "pool should be built exactly once"


@pytest.mark.asyncio
async def test_get_pool_calls_prepare_dsn(monkeypatch) -> None:
    svc, _, _ = _build_audit_service(monkeypatch)
    from services.audit.audit_service import prepare_dsn  # the mock

    monkeypatch.setattr(svc, "_create_tables", AsyncMock())
    await svc._get_pool()
    assert prepare_dsn.called


@pytest.mark.asyncio
async def test_get_pool_runs_create_tables_once(monkeypatch) -> None:
    svc, _, _ = _build_audit_service(monkeypatch)
    create_tables_mock = AsyncMock()
    monkeypatch.setattr(svc, "_create_tables", create_tables_mock)

    await svc._get_pool()
    await svc._get_pool()

    assert create_tables_mock.await_count == 1


@pytest.mark.asyncio
async def test_get_pool_no_register_vector_init(monkeypatch) -> None:
    """D-06: audit has no vector columns; init= kwarg must NOT include register_vector."""
    svc, _, create_pool_mock = _build_audit_service(monkeypatch)
    monkeypatch.setattr(svc, "_create_tables", AsyncMock())

    await svc._get_pool()

    # Inspect the create_pool call kwargs
    call_kwargs = create_pool_mock.call_args.kwargs
    init_callback = call_kwargs.get("init")
    if init_callback is not None:
        # If an init callback is somehow passed, it must not call register_vector
        import inspect
        src = inspect.getsource(init_callback) if callable(init_callback) else ""
        assert "register_vector" not in src


@pytest.mark.asyncio
async def test_close_drains_buffer_first(monkeypatch) -> None:
    from services.audit.audit_service import AuditEvent

    svc, fake_pool, _ = _build_audit_service(monkeypatch)
    monkeypatch.setattr(svc, "_create_tables", AsyncMock())
    monkeypatch.setattr("services.audit.audit_service.settings.audit_db_enabled", True, raising=False)

    flush_mock = AsyncMock()
    monkeypatch.setattr(svc, "_flush_to_db", flush_mock)

    svc._buffer.append(AuditEvent(action="TEST_ACTION"))
    svc._pool = fake_pool  # simulate previously-built pool

    await svc.close()

    assert flush_mock.await_count == 1, "buffer must be drained before pool close"
    assert fake_pool.close.await_count == 1


@pytest.mark.asyncio
async def test_close_idempotent(monkeypatch) -> None:
    svc, fake_pool, _ = _build_audit_service(monkeypatch)
    svc._pool = fake_pool

    await svc.close()
    await svc.close()

    assert fake_pool.close.await_count == 1, "second close must be no-op"
    assert svc._pool is None


@pytest.mark.asyncio
async def test_audit_db_disabled_no_pool_built(monkeypatch) -> None:
    svc, _, create_pool_mock = _build_audit_service(monkeypatch)
    monkeypatch.setattr("services.audit.audit_service.settings.audit_db_enabled", False, raising=False)

    await svc.flush()  # public manual flush

    assert create_pool_mock.await_count == 0, "pool must NOT be built when audit_db_enabled is False"
    assert svc._pool is None


# ------ A2 (eng-review): close() acquires self._lock ------
@pytest.mark.asyncio
async def test_close_acquires_lock_during_drain(monkeypatch) -> None:
    """A2: close() must serialize with the buffer-overflow flush path via
    self._lock. Strategy: hold the lock before calling close(); close() must
    block waiting for it (cannot drain). If we then release the lock, close()
    completes. This proves close()'s drain is gated by the lock.
    """
    from services.audit.audit_service import AuditEvent

    svc, fake_pool, _ = _build_audit_service(monkeypatch)
    monkeypatch.setattr("services.audit.audit_service.settings.audit_db_enabled", True, raising=False)
    flush_mock = AsyncMock()
    monkeypatch.setattr(svc, "_flush_to_db", flush_mock)
    svc._buffer.append(AuditEvent(action="TEST"))
    svc._pool = fake_pool

    # Acquire the lock first — close() must block on it
    await svc._lock.acquire()
    try:
        close_task = asyncio.create_task(svc.close())
        await asyncio.sleep(0.05)
        # close() should be blocked — _flush_to_db not yet called
        assert flush_mock.await_count == 0, (
            "close() drained without acquiring self._lock — A2 fix missing"
        )
    finally:
        svc._lock.release()

    await close_task
    assert flush_mock.await_count == 1, "after lock release, close() must drain"


# ------ P1 (eng-review): _create_tables failure resets _pool ------
@pytest.mark.asyncio
async def test_create_tables_failure_resets_pool(monkeypatch) -> None:
    """P1 fix: if _create_tables raises after pool construction, _pool must reset
    to None so next call retries clean instead of returning a broken cached pool.
    """
    import asyncpg

    svc, fake_pool, _ = _build_audit_service(monkeypatch)
    monkeypatch.setattr(
        svc,
        "_create_tables",
        AsyncMock(side_effect=asyncpg.PostgresError("simulated DDL failure")),
    )

    with pytest.raises(asyncpg.PostgresError):
        await svc._get_pool()

    assert svc._pool is None, "P1: _pool must reset on _create_tables failure"
    assert fake_pool.close.await_count == 1, "pool must be torn down on partial init"


# ------ T1 R1 (eng-review IRON RULE): regression test for close-vs-overflow race ------
@pytest.mark.asyncio
async def test_close_vs_overflow_flush_no_event_loss(monkeypatch) -> None:
    """A2 fix proven: under concurrent close() + buffer-overflow flush, lock
    serializes both paths so no events are lost or double-written.
    """
    from services.audit.audit_service import AuditEvent

    svc, fake_pool, _ = _build_audit_service(monkeypatch)
    monkeypatch.setattr("services.audit.audit_service.settings.audit_db_enabled", True, raising=False)

    drained_batches: list[list[AuditEvent]] = []

    async def fake_flush() -> None:
        # Mimic the real _flush_to_db: snapshot buffer, clear, "write"
        if not svc._buffer:
            return
        batch = svc._buffer.copy()
        svc._buffer.clear()
        drained_batches.append(batch)

    monkeypatch.setattr(svc, "_flush_to_db", fake_flush)
    svc._pool = fake_pool

    # Pre-populate buffer
    for i in range(50):
        svc._buffer.append(AuditEvent(action=f"EVT_{i}"))

    async def overflow_flush() -> None:
        # Simulates the log() buffer-overflow branch — acquires lock then flushes
        async with svc._lock:
            await svc._flush_to_db()

    # Race: overflow flush + close concurrently
    await asyncio.gather(overflow_flush(), svc.close())

    total_drained = sum(len(b) for b in drained_batches)
    assert total_drained == 50, f"all 50 events must be drained exactly once (got {total_drained})"
    # No event_id should appear twice
    all_ids = [e.event_id for b in drained_batches for e in b]
    assert len(all_ids) == len(set(all_ids)), "events must not be duplicated"
