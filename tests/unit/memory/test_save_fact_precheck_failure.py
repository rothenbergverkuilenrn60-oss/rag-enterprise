"""tests/unit/memory/test_save_fact_precheck_failure.py — Phase 27 / TD-04 / SC-3.

Covers fail-OPEN semantics for the cosine near-duplicate dedupe wired into
``LongTermMemory.save_fact`` via the D-12 ``save_facts`` wrapper (plan 27-04).

  * asyncpg error on the bulk dedupe SELECT must NOT raise
    MemoryFactWriteError — it must log a warning and proceed with the INSERT.
    Mirrors get_relevant_facts:353-357 ("returns [] on any failure") and
    v1.6 GDPR T1 Pattern D ("audit-write failure must NOT block").

  * Audit-write failure (RuntimeError raised by AuditService.log) is also
    non-fatal — the save still succeeds.

Phase 27 / TD-05 internal shape change: the bulk dedupe SELECT goes through
``conn.fetch`` (was ``conn.fetchrow`` in plan 27-03). The fail-OPEN contract
is identical: a PG-error on the dedupe step does NOT escalate to the caller.
The INSERT path now lands via ``conn.executemany`` (was ``conn.execute``).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from services.memory.memory_service import LongTermMemory, MemoryFactWriteError


# -----------------------------------------------------------------------------
# Pattern B — autouse singleton reset
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


# -----------------------------------------------------------------------------
# Helpers (mirrors test_save_fact_precheck.py — 27-04 batch path)
# -----------------------------------------------------------------------------
class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool(
    *,
    fetch_mock: AsyncMock | None = None,
    execute_mock: AsyncMock | None = None,
    executemany_mock: AsyncMock | None = None,
) -> tuple[MagicMock, MagicMock]:
    if fetch_mock is None:
        fetch_mock = AsyncMock(return_value=[])
    if execute_mock is None:
        execute_mock = AsyncMock()
    if executemany_mock is None:
        executemany_mock = AsyncMock()
    conn = MagicMock(
        execute=execute_mock,
        executemany=executemany_mock,
        fetch=fetch_mock,
    )
    conn.transaction = MagicMock(return_value=_AcquireCtx(conn))
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool, conn


def _make_long(pool: MagicMock) -> LongTermMemory:
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool

    async def _get_pool():
        return pool

    lt._get_pool = _get_pool
    return lt


def _patch_embedder(monkeypatch) -> MagicMock:
    fake = MagicMock(
        embed_batch=AsyncMock(return_value=[[0.1] * 1024]),
        embed_one=AsyncMock(return_value=[0.1] * 1024),
    )
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder", lambda: fake,
    )
    monkeypatch.setattr(
        "services.memory.memory_service.get_embedder",
        lambda: fake,
        raising=False,
    )
    return fake


def _patch_audit(monkeypatch, log_side_effect=None) -> MagicMock:
    log_mock = AsyncMock(side_effect=log_side_effect)
    mock_audit = MagicMock(log=log_mock)
    monkeypatch.setattr(
        "services.audit.audit_service.get_audit_service",
        lambda: mock_audit,
    )
    return mock_audit


# -----------------------------------------------------------------------------
# Test — bulk dedupe PostgresError is fail-OPEN
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "exc_cls",
    [
        asyncpg.PostgresError,
        asyncpg.ConnectionDoesNotExistError,
        asyncpg.InterfaceError,
    ],
)
@pytest.mark.asyncio
async def test_precheck_postgres_error_is_fail_open(monkeypatch, exc_cls):
    """asyncpg error on the bulk dedupe SELECT → warning logged + INSERT runs.

    save_fact must NOT raise MemoryFactWriteError when the dedupe step itself
    blows up — the dedupe is a "good-faith" guard. Only the actual INSERT
    raising should escalate.
    """
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch)

    # bulk dedupe SELECT raises the parametrized PG error.
    fetch = AsyncMock(side_effect=exc_cls("dedupe boom"))
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    # Must NOT raise — fail-OPEN.
    await mem.save_fact(user_id="u1", tenant_id="t1", fact="some fact")

    # INSERT proceeded via executemany despite dedupe failure.
    assert conn.executemany.await_count == 1, (
        "Bulk dedupe PostgresError must be fail-OPEN — INSERT must still run."
    )


# -----------------------------------------------------------------------------
# Test — audit-write failure is non-fatal (Pattern D)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_log_failure_is_non_fatal(monkeypatch):
    """get_audit_service().log raising RuntimeError must NOT prevent INSERT.

    Pattern D (v1.6 GDPR T1): audit-write boundary swallows failures and
    logs a warning so the business operation (save_fact) is unaffected.

    Phase 27 / TD-05 also wraps the audit emits in
    ``gather(return_exceptions=True)`` inside save_facts, so a raise from
    AuditService.log surfaces as a gather-captured BaseException and is
    swallowed by the gather rather than propagating.
    """
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch, log_side_effect=RuntimeError("audit table missing"))

    # Trigger near-dup path so audit.log is invoked.
    fetch = AsyncMock(return_value=[{"zero_idx": 0}])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    # Must NOT raise even though audit.log raises.
    await mem.save_fact(user_id="u1", tenant_id="t1", fact="dup fact")

    assert conn.executemany.await_count == 1, (
        "Audit-write failure must be non-fatal — INSERT must still run."
    )


# -----------------------------------------------------------------------------
# Sanity gate — confirm INSERT-failure path is unchanged (still raises typed)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_insert_failure_still_raises_typed_error(monkeypatch):
    """Regression bar: fail-OPEN treatment applies ONLY to the dedupe.
    INSERT PostgresError (now via executemany) must still raise
    MemoryFactWriteError so the dispatch wrapper surfaces the failure via
    log_task_error.
    """
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch)

    # Dedupe succeeds, executemany INSERT fails.
    executemany_mock = AsyncMock(side_effect=asyncpg.PostgresError("insert boom"))
    pool, _ = _make_fake_pool(executemany_mock=executemany_mock)
    mem = _make_long(pool)

    with pytest.raises(MemoryFactWriteError) as exc_info:
        await mem.save_fact(user_id="u1", tenant_id="t1", fact="x")
    assert isinstance(exc_info.value.__cause__, asyncpg.PostgresError)
