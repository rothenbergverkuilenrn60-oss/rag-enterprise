"""tests/unit/memory/test_save_fact_precheck.py — Phase 27 / TD-04 / SC-3.

Covers the cosine near-duplicate audit-mode contract exercised by the
``LongTermMemory.save_fact`` D-12 wrapper.

D-09 audit-mode-only semantics (the SC-3 vs ROADMAP override):
  * When the precheck distance is < threshold, the MEMORY_NEAR_DUPLICATE_SKIPPED
    audit row is emitted, AND the INSERT STILL RUNS. v1.7 ships metric-only;
    v1.8 promotes to actual silent-skip. These tests pin the metric+INSERT
    contract so a future v1.8 PR can't silently regress v1.7 audit-mode
    behavior without flipping this assertion.

Phase 27 / TD-05 (plan 27-04) internal change:
  ``save_fact`` now delegates to ``save_facts([ExtractedFact(...)])`` (D-12).
  The dedupe path uses ``conn.fetch`` (bulk SELECT returning duplicate index
  set) instead of ``conn.fetchrow`` (singular precheck). The audit-mode
  contract (emit-AND-INSERT) is identical regardless of singular vs. bulk
  internals — what matters here is the OUTSIDE contract.

Test inventory:
  1. test_precheck_emits_audit_when_near_duplicate_and_still_inserts
     — CRITICAL D-09 — duplicate detected by bulk SELECT triggers audit + INSERT.
  2. test_precheck_no_audit_when_not_near_duplicate — bulk SELECT empty; no audit; INSERT.
  3. test_precheck_no_audit_when_table_empty — bulk SELECT empty; no audit; INSERT.
  4. test_precheck_adds_exactly_one_pg_rtt — conn.fetch.await_count == 1 (the bulk SELECT).
  5. test_precheck_uses_per_user_tenant_filter — SQL string + params verified.

Patterns A+B+C from PATTERNS.md §"Shared Patterns":
  A — env-var setdefault at module top (before any services.* import)
  B — autouse singleton-reset fixture
  C — dual-path embedder monkeypatch (source + consumer); patches embed_batch
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
# Reusable helpers — extended for 27-04 batch path (conn.fetch + executemany).
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
    """Return (pool, conn) wired for the 27-04 batch path.

    fetch_mock controls the bulk dedupe SELECT: empty list → no duplicates;
    list of {"zero_idx": i} dicts → those indices flagged as dups.
    """
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
    """Pattern C — dual-path embedder patch (27-04: patches embed_batch)."""
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

    Phase 27 / TD-05: dedupe now happens via bulk SELECT (returning the set of
    duplicate zero-based indices). For the singular wrapper, the only candidate
    is index 0 — return ``[{"zero_idx": 0}]`` to trigger the audit-mode branch.
    """
    _patch_embedder(monkeypatch)
    audit = _patch_audit(monkeypatch)

    # Bulk dedupe says index 0 is a near-duplicate.
    fetch = AsyncMock(return_value=[{"zero_idx": 0}])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
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
    assert event.detail["fact_truncated"] == "user prefers React"
    # Phase 27 / TD-05 batch path: nearest_distance is not surfaced from the
    # bulk SELECT (out-of-scope; v1.8 follow-up — see SUMMARY).
    assert event.detail["nearest_distance"] is None

    # CRITICAL D-09 — INSERT STILL RAN even though precheck hit.
    assert conn.executemany.await_count == 1, (
        "D-09: INSERT must run even on near-dup hit (audit-mode-only). "
        f"Got {conn.executemany.await_count} executemany calls."
    )


# -----------------------------------------------------------------------------
# Test 2 — happy path: not near-duplicate
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_no_audit_when_not_near_duplicate(monkeypatch):
    _patch_embedder(monkeypatch)
    audit = _patch_audit(monkeypatch)

    # Bulk dedupe returns empty → no near-dup index in batch.
    fetch = AsyncMock(return_value=[])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    await mem.save_fact(user_id="u1", tenant_id="t1", fact="distinct fact")

    assert audit.log.await_count == 0, "no audit emit when bulk SELECT returns empty"
    assert conn.executemany.await_count == 1


# -----------------------------------------------------------------------------
# Test 3 — empty table
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_no_audit_when_table_empty(monkeypatch):
    _patch_embedder(monkeypatch)
    audit = _patch_audit(monkeypatch)

    fetch = AsyncMock(return_value=[])  # empty table → bulk SELECT returns empty
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    await mem.save_fact(user_id="u1", tenant_id="t1", fact="first ever fact")

    assert audit.log.await_count == 0
    assert conn.executemany.await_count == 1


# -----------------------------------------------------------------------------
# Test 4 — RTT bound: dedupe issues exactly +1 bulk SELECT per save_fact
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_adds_exactly_one_pg_rtt(monkeypatch):
    """The +1 RTT contract (D-10) for the singular wrapper.

    Phase 27 / TD-05: the data query is now ``conn.fetch`` (bulk dedupe SELECT,
    which works equally for a 1-element batch). The SET LOCAL pair piggybacks
    inside the bulk-dedupe transaction (same conn, same round-trip class).
    Acceptance bar: conn.fetch.await_count == 1 per save_fact call.
    """
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch)

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)

    await mem.save_fact(user_id="u1", tenant_id="t1", fact="x")

    assert conn.fetch.await_count == 1, (
        f"Expected exactly 1 bulk dedupe SELECT, got {conn.fetch.await_count}"
    )


# -----------------------------------------------------------------------------
# Test 5 — per-(user,tenant) filter enforced in dedupe SQL (D-06 / RLS)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_uses_per_user_tenant_filter(monkeypatch):
    _patch_embedder(monkeypatch)
    _patch_audit(monkeypatch)

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)

    await mem.save_fact(
        user_id="alice", tenant_id="acme", fact="some fact",
    )

    # Phase 27 / TD-05 bulk dedupe SQL contract:
    #   user_id  -> $2 positional bind
    #   tenant_id -> $3 positional bind
    #   threshold -> $4 positional bind
    # The C1 corrected unnest($1::text[]) WITH ORDINALITY pattern reserves $1
    # for the vector-literal text[]. The EXISTS subquery filters on
    # (user_id, tenant_id) BEFORE the cosine comparison.
    call = conn.fetch.call_args
    sql = call.args[0]
    assert "user_id = $2" in sql and "tenant_id = $3" in sql, (
        f"Bulk dedupe must filter on (user_id, tenant_id) BEFORE HNSW. SQL: {sql!r}"
    )
    # Positional bind order: vec_literals=$1, user_id=$2, tenant_id=$3, threshold=$4.
    assert call.args[2] == "alice"
    assert call.args[3] == "acme"
