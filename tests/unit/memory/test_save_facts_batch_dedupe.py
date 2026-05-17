"""tests/unit/memory/test_save_facts_batch_dedupe.py — Phase 27 / TD-05 / C3 D-09.

Pins the D-09 audit-mode-only contract for the BATCH path: when the bulk
dedupe SELECT identifies duplicates inside a batch, audit rows fire for each
duplicate index AND the executemany INSERT runs for ALL rows (NOT filtered).
v1.7 = metric-only; v1.8 promotes to actual silent-skip. This is the same
audit-mode contract as plan 27-03's singular precheck, preserved verbatim
inside the batch path.

Also pins fail-OPEN: bulk dedupe asyncpg error → warning logged, treated as
no-dup, executemany still runs.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from services.audit.audit_service import AuditAction
from services.memory.memory_service import LongTermMemory
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
# Test 1 — C3 D-09 in-batch audit-mode (CRITICAL)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows(monkeypatch):
    """Bulk dedupe flags indices 1 and 3 as near-duplicates.

    D-09 contract (CRITICAL — v1.7 audit-mode-only):
      * audit.log.await_count == 2 (one audit row per duplicate index).
      * conn.executemany.call_count == 1.
      * len(rows passed to executemany) == 5 (ALL rows inserted; duplicates
        NOT filtered out — v1.7 is metric-only, v1.8 promotes to silent-skip).
      * result.saved_count == 5 (semantic intent: saved this batch).
      * result.skipped_near_duplicates == 2 (semantic intent: would-have-skipped
        if v1.8 enforcement were active).
    """
    _patch_embedder_batch(monkeypatch, n=5)
    audit = _patch_audit(monkeypatch)

    # Bulk dedupe says indices 1 and 3 are duplicates.
    fetch = AsyncMock(return_value=[{"zero_idx": 1}, {"zero_idx": 3}])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    facts = _make_facts(5)
    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # 2 audit rows fired — one per duplicate index.
    assert audit.log.await_count == 2, (
        f"D-09: expected 2 audit emits (one per dup), got {audit.log.await_count}"
    )
    # All audit emits carry the near-dup action.
    for call in audit.log.await_args_list:
        event = call.args[0]
        assert event.action == AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED

    # Audit fact texts came from the right indices (1, 3).
    seen_facts = {c.args[0].detail["fact_truncated"] for c in audit.log.await_args_list}
    assert seen_facts == {"dup-test fact 1", "dup-test fact 3"}

    # CRITICAL — executemany inserts ALL 5 rows (NOT filtered).
    assert conn.executemany.call_count == 1
    rows = conn.executemany.call_args.args[1]
    assert len(rows) == 5, (
        f"D-09: executemany must receive ALL {5} rows (not filtered by dups). "
        f"Got {len(rows)} rows."
    )

    # SaveFactsResult — semantic intent (v1.8 readiness).
    assert result.saved_count == 5
    assert result.skipped_near_duplicates == 2
    assert result.skipped_embed_failures == 0


# -----------------------------------------------------------------------------
# Test 2 — bulk dedupe asyncpg.PostgresError is fail-OPEN
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bulk_dedupe_fail_open_on_postgres_error(monkeypatch):
    """asyncpg error on the bulk dedupe SELECT must NOT raise — log warning,
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

    # No raise — fail-OPEN.
    # executemany still ran with all 5 rows.
    assert conn.executemany.call_count == 1
    assert len(conn.executemany.call_args.args[1]) == 5
    # No duplicates flagged (treated as empty dup set on fail-open).
    assert result.skipped_near_duplicates == 0
    assert result.saved_count == 5
