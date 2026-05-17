"""tests/unit/memory/test_save_fact_precheck.py — Phase 27 / TD-04 / SC-3.

Covers the cosine near-duplicate precheck wired into
``LongTermMemory.save_fact`` per Plan 27-03.

D-09 audit-mode-only semantics (the SC-3 vs ROADMAP override):
  * When the precheck distance is < threshold, the MEMORY_NEAR_DUPLICATE_SKIPPED
    audit row is emitted, AND the INSERT STILL RUNS. v1.7 ships metric-only;
    v1.8 promotes to actual silent-skip. These tests pin the metric+INSERT
    contract so a future v1.8 PR can't silently regress v1.7 audit-mode
    behavior without flipping this assertion.

Test inventory:
  1. test_precheck_emits_audit_when_near_duplicate_and_still_inserts
     — CRITICAL D-09 — dist=0.02 triggers audit + INSERT.
  2. test_precheck_no_audit_when_not_near_duplicate — dist=0.5; no audit; INSERT.
  3. test_precheck_no_audit_when_table_empty — fetchrow=None; no audit; INSERT.
  4. test_precheck_adds_exactly_one_pg_rtt — fetchrow.await_count == 1.
  5. test_precheck_uses_per_user_tenant_filter — SQL string + params verified.

Patterns A+B+C from PATTERNS.md §"Shared Patterns":
  A — env-var setdefault at module top (before any services.* import)
  B — autouse singleton-reset fixture
  C — dual-path embedder monkeypatch (source + consumer)
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.audit.audit_service import AuditAction
from services.memory.memory_service import LongTermMemory


# -----------------------------------------------------------------------------
# Pattern B — autouse singleton reset
# -----------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


# -----------------------------------------------------------------------------
# Reusable helpers — verbatim from tests/unit/test_memory_save_fact.py:50-80
# extended with fetchrow + transaction() per PATTERNS.md line 280.
# -----------------------------------------------------------------------------
class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool(
    execute_mock: AsyncMock,
    fetchrow_mock: AsyncMock,
) -> tuple[MagicMock, MagicMock]:
    """Return (pool, conn). conn has execute + fetchrow + transaction()."""
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
    """Pattern C — dual-path embedder patch."""
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


def _patch_audit(monkeypatch) -> MagicMock:
    """Mock get_audit_service() so log() calls become observable AsyncMock."""
    mock_audit = MagicMock(log=AsyncMock())
    monkeypatch.setattr(
        "services.audit.audit_service.get_audit_service",
        lambda: mock_audit,
    )
    return mock_audit


# -----------------------------------------------------------------------------
# Test 1 — D-09 audit-mode-only — CRITICAL
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_emits_audit_when_near_duplicate_and_still_inserts(monkeypatch):
    """D-09 contract: near-dup hit emits MEMORY_NEAR_DUPLICATE_SKIPPED AND INSERT runs.

    NOT asserting 'save was skipped' — v1.7 is OPPOSITE of ROADMAP SC-3 wording.
    v1.8 will promote to actual silent-skip; this test pins v1.7 audit-mode
    semantics so a future change can't quietly regress without flipping the
    explicit "INSERT-still-ran" assertion below.
    """
    _patch_embedder(monkeypatch)
    audit = _patch_audit(monkeypatch)

    execute = AsyncMock()
    fetchrow = AsyncMock(return_value={"dist": 0.02})  # below 0.05 threshold
    pool, conn = _make_fake_pool(execute, fetchrow)
    mem = _make_long(pool)

    await mem.save_fact(
        user_id="u1", tenant_id="t1", fact="user prefers React", importance=0.8,
    )

    # Audit row emitted exactly once with the near-dup action.
    assert audit.log.await_count == 1, (
        f"Expected 1 audit emit, got {audit.log.await_count}"
    )
    event = audit.log.call_args.args[0]
    assert event.action == AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED
    assert event.detail["nearest_distance"] == pytest.approx(0.02)
    assert event.detail["fact_truncated"] == "user prefers React"

    # CRITICAL D-09 — INSERT STILL RAN even though precheck hit.
    # Execute calls: 2× SET LOCAL inside precheck + 1× INSERT.
    insert_calls = [
        c for c in conn.execute.call_args_list
        if "INSERT INTO long_term_facts" in c.args[0]
    ]
    assert len(insert_calls) == 1, (
        "D-09: INSERT must run even on near-dup hit (audit-mode-only). "
        f"Got {len(insert_calls)} INSERT calls."
    )


# -----------------------------------------------------------------------------
# Test 2 — happy path: not near-duplicate
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_no_audit_when_not_near_duplicate(monkeypatch):
    _patch_embedder(monkeypatch)
    audit = _patch_audit(monkeypatch)

    execute = AsyncMock()
    fetchrow = AsyncMock(return_value={"dist": 0.5})  # above 0.05 threshold
    pool, conn = _make_fake_pool(execute, fetchrow)
    mem = _make_long(pool)

    await mem.save_fact(user_id="u1", tenant_id="t1", fact="distinct fact")

    assert audit.log.await_count == 0, "no audit emit when dist >= threshold"
    insert_calls = [
        c for c in conn.execute.call_args_list
        if "INSERT INTO long_term_facts" in c.args[0]
    ]
    assert len(insert_calls) == 1


# -----------------------------------------------------------------------------
# Test 3 — empty table
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_no_audit_when_table_empty(monkeypatch):
    _patch_embedder(monkeypatch)
    audit = _patch_audit(monkeypatch)

    execute = AsyncMock()
    fetchrow = AsyncMock(return_value=None)  # empty table
    pool, conn = _make_fake_pool(execute, fetchrow)
    mem = _make_long(pool)

    await mem.save_fact(user_id="u1", tenant_id="t1", fact="first ever fact")

    assert audit.log.await_count == 0
    insert_calls = [
        c for c in conn.execute.call_args_list
        if "INSERT INTO long_term_facts" in c.args[0]
    ]
    assert len(insert_calls) == 1


# -----------------------------------------------------------------------------
# Test 4 — RTT bound: precheck adds exactly +1 PG round-trip (fetchrow)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_adds_exactly_one_pg_rtt(monkeypatch):
    """The +1 RTT contract (D-10) is about the data query (fetchrow). The
    SET LOCAL pair piggybacks inside the precheck transaction (same conn,
    same round-trip class), and the INSERT is the same execute call as before.
    Acceptance bar: conn.fetchrow.await_count == 1 per save_fact call.
    """
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch)

    execute = AsyncMock()
    fetchrow = AsyncMock(return_value=None)
    pool, conn = _make_fake_pool(execute, fetchrow)
    mem = _make_long(pool)

    await mem.save_fact(user_id="u1", tenant_id="t1", fact="x")

    assert conn.fetchrow.await_count == 1, (
        f"Expected exactly 1 precheck SELECT, got {conn.fetchrow.await_count}"
    )


# -----------------------------------------------------------------------------
# Test 5 — per-(user,tenant) filter enforced in precheck SQL (D-06 / RLS)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_uses_per_user_tenant_filter(monkeypatch):
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch)

    execute = AsyncMock()
    fetchrow = AsyncMock(return_value=None)
    pool, conn = _make_fake_pool(execute, fetchrow)
    mem = _make_long(pool)

    await mem.save_fact(
        user_id="alice", tenant_id="acme", fact="some fact",
    )

    # Precheck SQL must contain the per-(user,tenant) filter and the test ids
    # must arrive as parameters $1/$2 (positional asyncpg binding).
    call = conn.fetchrow.call_args
    sql = call.args[0]
    assert "user_id=$1 AND tenant_id=$2" in sql, (
        f"Precheck must filter on (user_id, tenant_id) BEFORE HNSW. SQL: {sql!r}"
    )
    assert call.args[1] == "alice"
    assert call.args[2] == "acme"
