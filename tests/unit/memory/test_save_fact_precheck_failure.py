"""tests/unit/memory/test_save_fact_precheck_failure.py — Phase 29 / TEST-INFRA-02.

Rewritten (v1.8) to assert the C1 bulk-SELECT SQL shape for failure paths and
the ``nearest_distance=None`` / empty-table branch.

Covers fail-OPEN semantics for ``_bulk_near_duplicate_check_raw`` wired into
``LongTermMemory.save_facts`` (and via D-12 wrapper ``save_fact``).

  * asyncpg error on the bulk dedupe SELECT must NOT raise
    MemoryFactWriteError — it must log a warning and proceed with the INSERT.
    Mirrors get_relevant_facts:353-357 ("returns [] on any failure") and
    v1.6 GDPR T1 Pattern D ("audit-write failure must NOT block").

  * Audit-write failure (RuntimeError raised by AuditService.log) is also
    non-fatal — the save still succeeds.

  * Empty-table branch (``conn.fetch`` returns ``[]`` for a 3-fact batch):
    dup_zero_idxs == set(), executemany called with 3 rows,
    skipped_near_duplicates == 0. This is the nearest_distance=None /
    empty-table branch per TEST-INFRA-02 req acceptance.

Phase 27 / TD-05 internal shape: the bulk dedupe SELECT goes through
``conn.fetch`` (not the legacy singular SELECT). The fail-OPEN contract
is identical: a PG-error on the dedupe step does NOT escalate to the caller.

Test inventory:
  (i)  test_precheck_postgres_error_is_fail_open
         asyncpg.PostgresError on conn.fetch → warning logged + INSERT runs.
  (ii) test_precheck_interface_error_is_fail_open
         asyncpg.InterfaceError on conn.fetch → same fail-OPEN behavior.
  (iii) test_precheck_empty_table_nearest_distance_none_branch
         conn.fetch returns [] for 3-fact batch (empty table, no existing rows).
         TEST-INFRA-02 nearest_distance=None branch coverage.
  (iv) test_audit_log_failure_is_non_fatal
         AuditService.log raises RuntimeError → save_fact succeeds; SK-01
         dup-filtered so executemany == 0.
  (v)  test_insert_failure_still_raises_typed_error
         Regression bar: executemany INSERT PostgresError still raises
         MemoryFactWriteError (fail-OPEN applies ONLY to the dedupe step).
"""
from __future__ import annotations

import os

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


def _patch_embedder_batch(monkeypatch, n: int = 1) -> MagicMock:
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


def _patch_audit(monkeypatch, log_side_effect=None) -> MagicMock:
    log_mock = AsyncMock(side_effect=log_side_effect)
    mock_audit = MagicMock(log=log_mock)
    monkeypatch.setattr(
        "services.audit.audit_service.get_audit_service",
        lambda: mock_audit,
    )
    return mock_audit


def _make_facts(n: int) -> list[ExtractedFact]:
    return [
        ExtractedFact(fact=f"test fact {i}", category="recurring_topics", importance=0.5)
        for i in range(n)
    ]


# -----------------------------------------------------------------------------
# (i) asyncpg.PostgresError on bulk dedupe SELECT → fail-OPEN
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_postgres_error_is_fail_open(monkeypatch):
    """(i) asyncpg.PostgresError on conn.fetch → warning logged + INSERT runs.

    save_fact must NOT raise MemoryFactWriteError when the dedupe step raises
    asyncpg.PostgresError — the dedupe is a "good-faith" guard. Only an actual
    INSERT failure should escalate (covered by test (v) below).
    """
    _patch_embedder_batch(monkeypatch, n=1)
    _patch_audit(monkeypatch)

    fetch = AsyncMock(side_effect=asyncpg.PostgresError("conn lost"))
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    # Must NOT raise — fail-OPEN.
    await mem.save_fact(user_id="u1", tenant_id="t1", fact="some fact")

    # INSERT proceeded via executemany despite dedupe failure.
    assert conn.executemany.await_count == 1, (
        "asyncpg.PostgresError on bulk dedupe must be fail-OPEN — INSERT must still run. "
        f"Got {conn.executemany.await_count} executemany calls."
    )


# -----------------------------------------------------------------------------
# (ii) asyncpg.InterfaceError on bulk dedupe SELECT → fail-OPEN
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_interface_error_is_fail_open(monkeypatch):
    """(ii) asyncpg.InterfaceError on conn.fetch → same fail-OPEN behavior.

    Covered by ``except (asyncpg.PostgresError, asyncpg.InterfaceError)`` in
    save_facts Step 3. Both narrow exception types must be handled.
    """
    _patch_embedder_batch(monkeypatch, n=1)
    _patch_audit(monkeypatch)

    fetch = AsyncMock(side_effect=asyncpg.InterfaceError("pool closed"))
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    # Must NOT raise — fail-OPEN applies to InterfaceError too.
    await mem.save_fact(user_id="u1", tenant_id="t1", fact="some fact")

    assert conn.executemany.await_count == 1, (
        "asyncpg.InterfaceError on bulk dedupe must be fail-OPEN — INSERT must still run. "
        f"Got {conn.executemany.await_count} executemany calls."
    )


# -----------------------------------------------------------------------------
# (iii) nearest_distance=None / empty-table branch — TEST-INFRA-02
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_empty_table_nearest_distance_none_branch(monkeypatch):
    """(iii) conn.fetch returns [] for a 3-fact batch — empty-table branch.

    TEST-INFRA-02 nearest_distance=None branch coverage.

    When no existing rows match the EXISTS clause for any candidate (empty
    table or simply no near-duplicates), conn.fetch returns []. This maps to
    dup_zero_idxs == set() — all rows pass to executemany.

    Assertions:
      * dup_zero_idxs == set() (implicit: executemany called with 3 rows).
      * executemany called exactly once with 3 rows (all passed through).
      * result.skipped_near_duplicates == 0.
      * result.saved_count == 3.
      * C1 SQL shape present: unnest($1::text[]) WITH ORDINALITY in SQL issued
        to conn.fetch.
    """
    n = 3
    _patch_embedder_batch(monkeypatch, n=n)
    _patch_audit(monkeypatch)

    # Empty-table branch: no rows match the EXISTS clause → bulk SELECT returns [].
    fetch = AsyncMock(return_value=[])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    facts = _make_facts(n)
    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # Empty result → all 3 rows passed to executemany.
    assert conn.executemany.await_count == 1, (
        "Empty-table branch: executemany must run with all rows."
    )
    rows = conn.executemany.call_args.args[1]
    assert len(rows) == 3, (
        f"nearest_distance=None branch: expected 3 rows to executemany, got {len(rows)}"
    )
    assert result.skipped_near_duplicates == 0
    assert result.saved_count == 3

    # C1 SQL-shape assertion for the empty-table path.
    sql = conn.fetch.call_args.args[0]
    assert "unnest($1::text[]) WITH ORDINALITY" in sql, (
        f"C1 SQL shape missing 'unnest($1::text[]) WITH ORDINALITY'. SQL: {sql!r}"
    )


# -----------------------------------------------------------------------------
# (iv) Audit-write failure is non-fatal (Pattern D)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_log_failure_is_non_fatal(monkeypatch):
    """get_audit_service().log raising RuntimeError must NOT cause save_fact to raise.

    Pattern D (v1.6 GDPR T1): audit-write boundary swallows failures and
    logs a warning so the business operation (save_fact) is unaffected.

    SK-01 v1.8: when index 0 is a near-dup, the skip-INSERT short-circuits
    (rows_to_insert is empty -- no executemany call). Audit-write failure must
    still not propagate. executemany.await_count == 0 (dup filtered, not error).
    """
    _patch_embedder_batch(monkeypatch, n=1)
    _patch_audit(monkeypatch, log_side_effect=RuntimeError("audit table missing"))

    # Trigger near-dup path so audit.log is invoked.
    fetch = AsyncMock(return_value=[{"zero_idx": 0}])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    # Must NOT raise even though audit.log raises.
    await mem.save_fact(user_id="u1", tenant_id="t1", fact="dup fact")

    # SK-01: dup filtered => executemany skipped (not 1); audit failure non-fatal.
    assert conn.executemany.await_count == 0, (
        "SK-01: near-dup row must be silently skipped; audit-write failure must not raise. "
        f"Got {conn.executemany.await_count} executemany calls."
    )


# -----------------------------------------------------------------------------
# (v) Sanity gate — INSERT failure path unchanged (still raises typed error)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_insert_failure_still_raises_typed_error(monkeypatch):
    """Regression bar: fail-OPEN applies ONLY to the dedupe step.

    INSERT PostgresError (via executemany) must still raise MemoryFactWriteError
    so the dispatch wrapper surfaces the failure via log_task_error.
    """
    _patch_embedder_batch(monkeypatch, n=1)
    _patch_audit(monkeypatch)

    # Dedupe succeeds (returns []), executemany INSERT fails.
    executemany_mock = AsyncMock(side_effect=asyncpg.PostgresError("insert boom"))
    pool, _ = _make_fake_pool(executemany_mock=executemany_mock)
    mem = _make_long(pool)

    with pytest.raises(MemoryFactWriteError) as exc_info:
        await mem.save_fact(user_id="u1", tenant_id="t1", fact="x")
    assert isinstance(exc_info.value.__cause__, asyncpg.PostgresError)
