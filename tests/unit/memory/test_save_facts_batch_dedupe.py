"""tests/unit/memory/test_save_facts_batch_dedupe.py -- Phase 29 / SK-01 silent-skip enforcement.

SK-01 silent-skip enforcement (v1.8 promotion of D-09 audit-mode): when the
bulk dedupe SELECT identifies duplicates inside a batch, audit rows fire for
each duplicate index AND the executemany INSERT runs for only the NON-duplicate
rows (duplicates filtered from rows_to_insert before executemany).

D-09 carry-forward: audit emit semantics preserved -- MEMORY_NEAR_DUPLICATE_SKIPPED
still fires per dup for ops dashboard visibility.

Also pins fail-OPEN: bulk dedupe asyncpg error -> warning logged, treated as
no-dup, executemany still runs with all rows.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from services.audit.audit_service import AuditAction
from services.memory.memory_service import LongTermMemory
from utils.models import ExtractedFact


# -----------------------------------------------------------------------------
# Pattern B -- autouse singleton reset
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


# -----------------------------------------------------------------------------
# Helpers
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


def _patch_embedder_batch(monkeypatch, n: int = 5) -> MagicMock:
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


def _patch_audit(monkeypatch) -> MagicMock:
    mock_audit = MagicMock(log=AsyncMock())
    monkeypatch.setattr(
        "services.audit.audit_service.get_audit_service",
        lambda: mock_audit,
    )
    return mock_audit


def _make_facts(n: int) -> list[ExtractedFact]:
    return [
        ExtractedFact(
            fact=f"dup-test fact {i}",
            category="recurring_topics",
            importance=0.5,
        )
        for i in range(n)
    ]


# -----------------------------------------------------------------------------
# Test 1 -- SK-01 silent-skip enforcement (CRITICAL)
# Renamed from: test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dedupe_in_batch_fires_audit_AND_executemany_inserts_non_dup_rows_only(monkeypatch):
    """Bulk dedupe flags indices 1 and 3 as near-duplicates.

    SK-01 silent-skip enforcement (v1.8 promotion of D-09 audit-mode):
      * audit.log.await_count == 2 (one audit row per duplicate index).
      * conn.executemany.call_count == 1.
      * len(rows passed to executemany) == 3 (ONLY non-duplicate rows inserted;
        duplicates at original indices 1 and 3 are filtered out).
      * row content: {row[2] for row in rows} == {"dup-test fact 0",
        "dup-test fact 2", "dup-test fact 4"} (indices 0, 2, 4 only).
      * result.saved_count == 3 (non-dup rows actually INSERTed).
      * result.skipped_near_duplicates == 2 (count of skipped duplicates).
      * result.skipped_embed_failures == 0.
    """
    _patch_embedder_batch(monkeypatch, n=5)
    audit = _patch_audit(monkeypatch)

    # Bulk dedupe says indices 1 and 3 are duplicates.
    fetch = AsyncMock(return_value=[{"zero_idx": 1}, {"zero_idx": 3}])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    facts = _make_facts(5)
    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # 2 audit rows fired -- one per duplicate index.
    assert audit.log.await_count == 2, (
        f"SK-01: expected 2 audit emits (one per dup), got {audit.log.await_count}"
    )
    # All audit emits carry the near-dup action.
    for call in audit.log.await_args_list:
        event = call.args[0]
        assert event.action == AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED

    # Audit fact texts came from the right indices (1, 3).
    seen_facts = {c.args[0].detail["fact_truncated"] for c in audit.log.await_args_list}
    assert seen_facts == {"dup-test fact 1", "dup-test fact 3"}

    # CRITICAL -- executemany inserts only the 3 NON-duplicate rows.
    assert conn.executemany.call_count == 1
    rows = conn.executemany.call_args.args[1]
    assert len(rows) == 3, (
        f"SK-01: executemany must receive only 3 non-dup rows (not 5). "
        f"Got {len(rows)} rows."
    )
    # Row content check: fact texts at positions 0, 2, 4 only.
    inserted_facts = {row[2] for row in rows}
    assert inserted_facts == {"dup-test fact 0", "dup-test fact 2", "dup-test fact 4"}

    # SaveFactsResult -- silent-skip enforcement counts.
    assert result.saved_count == 3
    assert result.skipped_near_duplicates == 2
    assert result.skipped_embed_failures == 0


# -----------------------------------------------------------------------------
# Test 2 -- bulk dedupe asyncpg.PostgresError is fail-OPEN (UNCHANGED)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bulk_dedupe_fail_open_on_postgres_error(monkeypatch):
    """asyncpg error on the bulk dedupe SELECT must NOT raise -- log warning,
    treat as no-dup, executemany still runs with all rows.

    Mirrors the fail-OPEN contract from save_fact precheck (plan 27-03 /
    test_save_fact_precheck_failure.py).
    """
    _patch_embedder_batch(monkeypatch, n=5)
    _patch_audit(monkeypatch)

    fetch = AsyncMock(side_effect=asyncpg.PostgresError("conn lost"))
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    facts = _make_facts(5)
    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # No raise -- fail-OPEN.
    # executemany still ran with all 5 rows.
    assert conn.executemany.call_count == 1
    assert len(conn.executemany.call_args.args[1]) == 5
    # No duplicates flagged (treated as empty dup set on fail-open).
    assert result.skipped_near_duplicates == 0
    assert result.saved_count == 5


# -----------------------------------------------------------------------------
# Test 3 -- audit-write failure does NOT block skip-INSERT (Open Risks #4)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_write_failure_does_not_block_skip_insert(monkeypatch):
    """v1.6 T1 carry-forward: audit-write failure is non-fatal.

    When _fire_near_duplicate_audit raises (e.g. audit DB down), executemany
    still receives the non-dup rows and the skip-INSERT proceeds normally.

    Setup: indices 1 and 3 are near-duplicates; _fire_near_duplicate_audit
    raises RuntimeError("audit DB down") for each dup. Assert:
      * conn.executemany.call_count == 1 (INSERT still runs).
      * len(rows) == 3 (only non-dup rows: indices 0, 2, 4).
      * result.saved_count == 3.
      * result.skipped_near_duplicates == 2.
    """
    _patch_embedder_batch(monkeypatch, n=5)

    # Make _fire_near_duplicate_audit raise so audit emit fails.
    async def _failing_audit(*args, **kwargs):
        raise RuntimeError("audit DB down")

    monkeypatch.setattr(
        "services.memory.memory_service.LongTermMemory._fire_near_duplicate_audit",
        _failing_audit,
    )

    # Bulk dedupe says indices 1 and 3 are duplicates.
    fetch = AsyncMock(return_value=[{"zero_idx": 1}, {"zero_idx": 3}])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    facts = _make_facts(5)
    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # executemany still ran despite audit failures -- non-fatal discipline.
    assert conn.executemany.call_count == 1
    rows = conn.executemany.call_args.args[1]
    assert len(rows) == 3, (
        f"Audit failure must not block skip-INSERT: expected 3 rows, got {len(rows)}"
    )
    assert result.saved_count == 3
    assert result.skipped_near_duplicates == 2


# -----------------------------------------------------------------------------
# Test 4 -- all duplicates short-circuits executemany (plan-review T3)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_all_duplicates_short_circuits_executemany(monkeypatch):
    """When every fact in the batch is a near-duplicate, executemany is NOT called.

    Pins the if-not-rows_to_insert short-circuit branch (SK-01 empty-batch guard).

    Setup: 5-fact batch; bulk dedupe returns all 5 indices as duplicates.
    Assert:
      * conn.executemany.call_count == 0 (no INSERT -- empty rows_to_insert skipped).
      * result.saved_count == 0.
      * result.skipped_near_duplicates == 5.
      * result.skipped_embed_failures == 0.
      * audit emit count == 5 (one per dup, fire-and-forget).
    """
    _patch_embedder_batch(monkeypatch, n=5)
    audit = _patch_audit(monkeypatch)

    # All 5 indices flagged as duplicates.
    fetch = AsyncMock(
        return_value=[
            {"zero_idx": 0},
            {"zero_idx": 1},
            {"zero_idx": 2},
            {"zero_idx": 3},
            {"zero_idx": 4},
        ]
    )
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    facts = _make_facts(5)
    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # executemany must NOT be called when rows_to_insert is empty.
    assert conn.executemany.call_count == 0, (
        f"SK-01 T3: executemany must not be called for all-dup batch, "
        f"got call_count={conn.executemany.call_count}"
    )
    assert result.saved_count == 0
    assert result.skipped_near_duplicates == 5
    assert result.skipped_embed_failures == 0
    # 5 audit emits -- one per duplicate.
    assert audit.log.await_count == 5
