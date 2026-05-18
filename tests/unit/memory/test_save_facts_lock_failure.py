"""tests/unit/memory/test_save_facts_lock_failure.py — Plan 29-00 T1.

Regression pin for the narrow ``asyncpg.PostgresError`` handler around the
``pg_advisory_xact_lock`` call in ``save_facts`` (plan-review finding T1).

If lock acquisition raises ``asyncpg.PostgresError``, ``save_facts`` MUST:
  1. Raise ``MemoryFactWriteError("lock acquisition failed")``.
  2. NOT proceed to ``conn.executemany`` (INSERT must not run on lock failure).
  3. NOT emit any audit rows (lock failure precedes the audit-emit block).

Uses the same helper patterns as ``test_save_facts_batch_dedupe.py``
(``_make_fake_pool``, ``_AcquireCtx``, ``_patch_embedder_batch``, ``_make_long``).

TOC-01 v1.8 / ERR-01 (no bare except) / 29-CONTEXT Open Risks.
"""
from __future__ import annotations

import os
from collections.abc import Generator

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from services.memory.memory_service import LongTermMemory, MemoryFactWriteError
from utils.models import ExtractedFact


# -----------------------------------------------------------------------------
# Pattern B — autouse singleton reset
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


# -----------------------------------------------------------------------------
# Helpers (carry-forward from test_save_facts_batch_dedupe.py)
# -----------------------------------------------------------------------------
class _AcquireCtx:
    def __init__(self, conn: MagicMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> MagicMock:
        return self._conn

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class _TxnCtx:
    """Context manager simulating conn.transaction() — propagates exceptions."""

    def __init__(self, conn: MagicMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> MagicMock:
        return self._conn

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False  # do NOT suppress — let MemoryFactWriteError propagate


def _make_fake_pool(
    *,
    execute_mock: AsyncMock | None = None,
    executemany_mock: AsyncMock | None = None,
    fetch_mock: AsyncMock | None = None,
) -> tuple[MagicMock, MagicMock]:
    if execute_mock is None:
        execute_mock = AsyncMock()
    if executemany_mock is None:
        executemany_mock = AsyncMock()
    if fetch_mock is None:
        fetch_mock = AsyncMock(return_value=[])
    conn = MagicMock(
        execute=execute_mock,
        executemany=executemany_mock,
        fetch=fetch_mock,
    )
    conn.transaction = MagicMock(return_value=_TxnCtx(conn))
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool, conn


def _make_long(pool: MagicMock) -> LongTermMemory:
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool  # type: ignore[assignment]

    async def _get_pool() -> MagicMock:
        return pool

    lt._get_pool = _get_pool  # type: ignore[method-assign]
    return lt


def _patch_embedder_batch(monkeypatch: pytest.MonkeyPatch, n: int = 1) -> MagicMock:
    fake = MagicMock(
        embed_batch=AsyncMock(return_value=[[0.1] * 1024 for _ in range(n)]),
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


def _patch_audit(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock_audit = MagicMock(log=AsyncMock())
    monkeypatch.setattr(
        "services.audit.audit_service.get_audit_service",
        lambda: mock_audit,
    )
    return mock_audit


# -----------------------------------------------------------------------------
# T1 — lock-acquisition failure raises MemoryFactWriteError
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_facts_lock_acquisition_failure_raises_memory_fact_write_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T1 (plan-review): ``asyncpg.PostgresError`` on pg_advisory_xact_lock call
    → ``MemoryFactWriteError("lock acquisition failed")`` raised.

    Verifies:
    1. MemoryFactWriteError is raised with message containing "lock acquisition failed".
    2. conn.executemany NEVER called (INSERT does not run on lock failure).
    3. No audit emits fired (lock failure precedes the audit-emit block).

    Uses a side-effect on ``conn.execute`` that raises only for SQL containing
    ``pg_advisory_xact_lock`` — all other execute calls (SET LOCAL etc.) behave normally.

    TOC-01 v1.8 / ERR-01 (narrow asyncpg.PostgresError, no bare except).
    """
    _patch_embedder_batch(monkeypatch, n=1)
    audit = _patch_audit(monkeypatch)

    def _execute_side_effect(sql: str, *args: object, **kwargs: object) -> object:
        """Raise PostgresError when SQL contains pg_advisory_xact_lock."""
        if "pg_advisory_xact_lock" in sql:
            raise asyncpg.PostgresError("lock acquire failed: simulated")
        # All other execute calls (SET LOCAL etc.) succeed — return a coroutine.
        return AsyncMock()()

    execute_mock = MagicMock(side_effect=_execute_side_effect)
    executemany_mock = AsyncMock()

    pool, conn = _make_fake_pool(
        execute_mock=execute_mock,
        executemany_mock=executemany_mock,
    )
    mem = _make_long(pool)

    fact = ExtractedFact(
        fact="lock-failure-test-fact",
        category="recurring_topics",
        importance=0.5,
    )

    # T1-1: save_facts MUST raise MemoryFactWriteError on lock failure.
    with pytest.raises(MemoryFactWriteError, match="lock acquisition failed"):
        await mem.save_facts([fact], user_id="u-lock", tenant_id="t-lock")

    # T1-2: executemany MUST NOT be called (INSERT not reached on lock failure).
    assert conn.executemany.call_count == 0, (
        f"T1 FAILED: conn.executemany was called {conn.executemany.call_count} time(s) "
        f"after a lock-acquisition failure — INSERT must not run."
    )

    # T1-3: no audit emits (lock failure precedes audit-emit block).
    assert audit.log.await_count == 0, (
        f"T1 FAILED: audit.log called {audit.log.await_count} time(s) "
        f"on lock failure — audit-emit block must not be reached."
    )
