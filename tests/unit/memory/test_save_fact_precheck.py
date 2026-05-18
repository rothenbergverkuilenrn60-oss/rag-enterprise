"""tests/unit/memory/test_save_fact_precheck.py — Phase 29 / TEST-INFRA-02.

Rewritten (v1.8) to assert the C1 bulk-SELECT SQL shape:
  ``unnest($1::text[]) WITH ORDINALITY`` + ``vec_txt::vector`` cast.

This file replaces the legacy per-fact ``_is_near_duplicate`` singular SELECT
tests with bulk-SELECT mock shape coverage for ``_bulk_near_duplicate_check_raw``
(the live production path since Phase 27 / TD-05).

Test inventory:
  1. test_precheck_emits_audit_when_near_duplicate_and_still_inserts
       (b) single-fact dup under SK-01 unconditional silent-skip shape:
       ``executemany.call_count == 0``, ``saved_count == 0``,
       ``skipped_near_duplicates == 1`` — bulk precheck returns ``[{"zero_idx": 0}]``.
  2. test_precheck_no_audit_when_not_near_duplicate
       (a) bulk returns ``[]`` → empty dup set → executemany receives the row.
  3. test_precheck_no_audit_when_table_empty
       (a) empty table branch — bulk fetch returns ``[]`` → no dup → INSERT runs.
  4. test_precheck_adds_exactly_one_pg_rtt
       ``conn.fetch.await_count == 1`` per save_fact call (D-10 RTT contract).
  5. test_precheck_uses_per_user_tenant_filter
       SQL bind params $(2)=user_id, $(3)=tenant_id verified (D-06 / RLS).
  6. test_precheck_sql_shape_pin
       Explicit C1 SQL-shape assertion: ``unnest($1::text[]) WITH ORDINALITY``
       AND ``vec_txt::vector`` present in the SQL issued to conn.fetch.
  7. test_precheck_multi_fact_vec_literals_shape
       (c) multi-fact batch: ``vec_literals`` passed as $1 are str entries
       starting with ``[`` and ending with ``]``.
  8. test_precheck_save_facts_empty_result_counts
       (a) direct save_facts path: saved_count == 1, skipped_near_duplicates == 0.

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
# Helpers — bulk-SELECT shape (Phase 27 / TD-05 + Phase 29 / TEST-INFRA-02)
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


def _patch_embedder_batch(monkeypatch, n: int = 1) -> MagicMock:
    """Pattern C — dual-path embedder patch using embed_batch (C1 path)."""
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
    """Mock get_audit_service() so log() calls become observable AsyncMock."""
    mock_audit = MagicMock(log=AsyncMock())
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
# Test 1 — (b) SK-01 unconditional silent-skip: single-fact dup
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_emits_audit_when_near_duplicate_and_still_inserts(monkeypatch):
    """(b) Single-fact dup under SK-01 unconditional silent-skip shape.

    Case (b) per plan 29-02: bulk precheck returns [{"zero_idx": 0}] for a
    single-fact batch.  SK-01 enforcement (Plan 29-01 shipped):
      * MEMORY_NEAR_DUPLICATE_SKIPPED audit row emitted (D-09 preserved).
      * executemany.call_count == 0 (empty rows_to_insert short-circuit).
      * saved_count == 0, skipped_near_duplicates == 1.

    Phase 27 / TD-05 batch path: dedupe via bulk SELECT returning zero-based
    duplicate index set.  For the singular wrapper, the only candidate is
    index 0 — return [{"zero_idx": 0}] to trigger the audit+skip branch.
    """
    _patch_embedder_batch(monkeypatch, n=1)
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
    # Bulk SELECT does not return per-row distance (out-of-scope v1.8 follow-up).
    assert event.detail["nearest_distance"] is None

    # CRITICAL SK-01 v1.8 unconditional silent-skip shape (plan-review Q1):
    # executemany must NOT be called — empty rows_to_insert short-circuit.
    assert conn.executemany.await_count == 0, (
        "SK-01: INSERT must be skipped for near-dup (silent-skip enforcement). "
        f"Got {conn.executemany.await_count} executemany calls."
    )


# -----------------------------------------------------------------------------
# Test 1b — (b) save_facts direct: result counts confirm SK-01 shape
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_save_facts_dup_result_counts(monkeypatch):
    """(b) Direct save_facts path: saved_count == 0, skipped_near_duplicates == 1."""
    _patch_embedder_batch(monkeypatch, n=1)
    _patch_audit(monkeypatch)

    fetch = AsyncMock(return_value=[{"zero_idx": 0}])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    facts = _make_facts(1)
    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    # SK-01 unconditional shape per plan-review Q1.
    assert result.saved_count == 0
    assert result.skipped_near_duplicates == 1
    assert conn.executemany.call_count == 0, (
        "SK-01: executemany must not run when all rows are duplicates."
    )


# -----------------------------------------------------------------------------
# Test 2 — (a) happy path: not near-duplicate
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_no_audit_when_not_near_duplicate(monkeypatch):
    """(a) Bulk precheck returns [] → empty dup set → executemany receives the row."""
    _patch_embedder_batch(monkeypatch, n=1)
    audit = _patch_audit(monkeypatch)

    # Bulk dedupe returns empty → no near-dup index in batch.
    fetch = AsyncMock(return_value=[])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    await mem.save_fact(user_id="u1", tenant_id="t1", fact="distinct fact")

    assert audit.log.await_count == 0, "no audit emit when bulk SELECT returns empty"
    assert conn.executemany.await_count == 1


# -----------------------------------------------------------------------------
# Test 3 — (a) empty table branch
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_no_audit_when_table_empty(monkeypatch):
    """(a) Empty table — bulk fetch returns [] → no dup → INSERT runs."""
    _patch_embedder_batch(monkeypatch, n=1)
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

    Phase 27 / TD-05: the data query is ``conn.fetch`` (bulk dedupe SELECT,
    which works equally for a 1-element batch). The SET LOCAL pair piggybacks
    inside the bulk-dedupe transaction (same conn, same round-trip class).
    Acceptance bar: conn.fetch.await_count == 1 per save_fact call.
    """
    _patch_embedder_batch(monkeypatch, n=1)
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
    """SQL bind params $2=user_id, $3=tenant_id verified (D-06 / RLS)."""
    _patch_embedder_batch(monkeypatch, n=1)
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


# -----------------------------------------------------------------------------
# Test 6 — C1 SQL-shape pin (TEST-INFRA-02 acceptance criterion)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_sql_shape_pin(monkeypatch):
    """C1 SQL-shape assertion: unnest($1::text[]) WITH ORDINALITY + vec_txt::vector.

    Extracts the SQL string from conn.fetch.call_args and asserts both
    required C1 tokens are present.  Prevents silent regression to the legacy
    per-fact singular SELECT shape.
    """
    _patch_embedder_batch(monkeypatch, n=1)
    _patch_audit(monkeypatch)

    pool, conn = _make_fake_pool()
    mem = _make_long(pool)

    await mem.save_fact(user_id="u1", tenant_id="t1", fact="shape pin fact")

    sql = conn.fetch.call_args.args[0]
    assert "unnest($1::text[]) WITH ORDINALITY" in sql, (
        f"C1 SQL shape missing 'unnest($1::text[]) WITH ORDINALITY'. SQL: {sql!r}"
    )
    assert "vec_txt::vector" in sql, (
        f"C1 SQL shape missing 'vec_txt::vector' cast. SQL: {sql!r}"
    )


# -----------------------------------------------------------------------------
# Test 7 — (c) multi-fact vec_literals shape
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_multi_fact_vec_literals_shape(monkeypatch):
    """(c) Multi-fact batch: $1 vec_literals are str '[float,float,...]' entries.

    Verifies that each entry in the first positional arg to conn.fetch is a
    string starting with '[' and ending with ']', containing comma-separated
    float values — i.e., pgvector text literals passed as $1::text[].
    """
    n = 3
    _patch_embedder_batch(monkeypatch, n=n)
    _patch_audit(monkeypatch)

    fetch = AsyncMock(return_value=[])
    pool, conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    facts = _make_facts(n)
    await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    call = conn.fetch.call_args
    vec_literals = call.args[1]  # $1 positional arg
    assert len(vec_literals) == n, (
        f"Expected {n} vec_literals, got {len(vec_literals)}"
    )
    for i, lit in enumerate(vec_literals):
        assert isinstance(lit, str), f"vec_literals[{i}] must be str, got {type(lit)}"
        assert lit.startswith("[") and lit.endswith("]"), (
            f"vec_literals[{i}]={lit!r} must be a pgvector text literal '[...]'"
        )
        # Confirm it contains comma-separated floats (not empty).
        inner = lit[1:-1]
        assert inner, f"vec_literals[{i}] is empty '[]'"
        parts = inner.split(",")
        assert all(p.strip() for p in parts), f"vec_literals[{i}] has empty parts"


# -----------------------------------------------------------------------------
# Test 8 — (a) save_facts direct: saved_count + skipped counts on no-dup
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_precheck_save_facts_empty_result_counts(monkeypatch):
    """(a) Direct save_facts: saved_count == 1, skipped_near_duplicates == 0."""
    _patch_embedder_batch(monkeypatch, n=1)
    _patch_audit(monkeypatch)

    fetch = AsyncMock(return_value=[])
    pool, _conn = _make_fake_pool(fetch_mock=fetch)
    mem = _make_long(pool)

    facts = _make_facts(1)
    result = await mem.save_facts(facts, user_id="u1", tenant_id="t1")

    assert result.saved_count == 1
    assert result.skipped_near_duplicates == 0
    assert result.skipped_embed_failures == 0
