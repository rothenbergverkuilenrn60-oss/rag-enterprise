"""tests/unit/memory/test_save_fact_precheck_failure.py — Phase 27 / TD-04 / SC-3.

Covers fail-OPEN semantics for the cosine near-duplicate precheck added in
Plan 27-03:

  * asyncpg.PostgresError on the precheck SELECT must NOT raise
    MemoryFactWriteError — it must log a warning and proceed with the INSERT.
    Mirrors get_relevant_facts:353-357 ("returns [] on any failure") and
    v1.6 GDPR T1 Pattern D ("audit-write failure must NOT block").

  * Audit-write failure (RuntimeError raised by AuditService.log) is also
    non-fatal — the save still succeeds.

Parametrized PG-error matrix matches tests/unit/test_memory_save_fact.py:128-188.
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
# Helpers (mirrors test_save_fact_precheck.py)
# -----------------------------------------------------------------------------
class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool(
    execute_mock: AsyncMock, fetchrow_mock: AsyncMock,
) -> tuple[MagicMock, MagicMock]:
    conn = MagicMock(execute=execute_mock, fetchrow=fetchrow_mock)
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
    fake = MagicMock(embed_one=AsyncMock(return_value=[0.1] * 1024))
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
# Test — precheck PostgresError is fail-OPEN
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
async def test_precheck_postgres_error_is_fail_open(monkeypatch, exc_cls, caplog):
    """asyncpg error on precheck SELECT → warning logged + INSERT still runs.

    save_fact must NOT raise MemoryFactWriteError when the precheck itself
    blows up — the precheck is a "good-faith" guard. Only the actual INSERT
    raising should escalate.
    """
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch)

    # execute = AsyncMock() succeeds for SET LOCAL + INSERT (no side_effect).
    execute = AsyncMock()
    # fetchrow raises the parametrized PG error.
    fetchrow = AsyncMock(side_effect=exc_cls("precheck boom"))
    pool, conn = _make_fake_pool(execute, fetchrow)
    mem = _make_long(pool)

    # Must NOT raise — fail-OPEN.
    await mem.save_fact(user_id="u1", tenant_id="t1", fact="some fact")

    # INSERT proceeded despite precheck failure.
    insert_calls = [
        c for c in conn.execute.call_args_list
        if "INSERT INTO long_term_facts" in c.args[0]
    ]
    assert len(insert_calls) == 1, (
        "Precheck PostgresError must be fail-OPEN — INSERT must still run."
    )


# -----------------------------------------------------------------------------
# Test — audit-write failure is non-fatal (Pattern D)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_log_failure_is_non_fatal(monkeypatch):
    """get_audit_service().log raising RuntimeError must NOT prevent INSERT.

    Pattern D (v1.6 GDPR T1): audit-write boundary swallows failures and
    logs a warning so the business operation (save_fact) is unaffected.
    """
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch, log_side_effect=RuntimeError("audit table missing"))

    execute = AsyncMock()
    fetchrow = AsyncMock(return_value={"dist": 0.02})  # triggers near-dup path
    pool, conn = _make_fake_pool(execute, fetchrow)
    mem = _make_long(pool)

    # Must NOT raise even though audit.log raises.
    await mem.save_fact(user_id="u1", tenant_id="t1", fact="dup fact")

    insert_calls = [
        c for c in conn.execute.call_args_list
        if "INSERT INTO long_term_facts" in c.args[0]
    ]
    assert len(insert_calls) == 1, (
        "Audit-write failure must be non-fatal — INSERT must still run."
    )


# -----------------------------------------------------------------------------
# Sanity gate — confirm INSERT-failure path is unchanged (still raises typed)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_insert_failure_still_raises_typed_error(monkeypatch):
    """Regression bar: this plan's fail-OPEN treatment applies ONLY to the
    precheck. INSERT PostgresError must still raise MemoryFactWriteError so
    the dispatch wrapper (Plan 23-05) surfaces the failure via log_task_error.
    """
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch)

    # SET LOCAL + INSERT all fail. Precheck is fail-OPEN → swallowed.
    # The post-precheck INSERT execute then re-raises.
    execute = AsyncMock(side_effect=asyncpg.PostgresError("insert boom"))
    fetchrow = AsyncMock(return_value=None)
    pool, _ = _make_fake_pool(execute, fetchrow)
    mem = _make_long(pool)

    with pytest.raises(MemoryFactWriteError) as exc_info:
        await mem.save_fact(user_id="u1", tenant_id="t1", fact="x")
    assert isinstance(exc_info.value.__cause__, asyncpg.PostgresError)
