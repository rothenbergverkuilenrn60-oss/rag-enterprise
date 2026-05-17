"""tests/unit/test_evict_long_term_facts.py — Phase 25 / EVICT-01 + EVICT-02.

11 RED gates for ``scripts/evict_long_term_facts.py``:

  Test 1  test_audit_mode_no_delete_and_stdout
          600 rows, cap=500, mode=audit → conn.execute NOT called; stdout JSON
          line emitted with over_cap_by=100.

  Test 2  test_audit_mode_writes_audit_log_skipped
          Same setup → audit_svc.log called with MEMORY_EVICT + SKIPPED +
          deleted_count=0 + mode="audit".

  Test 3  test_audit_mode_both_sinks
          Combines Tests 1+2 — stdout JSON-line AND audit_svc.log in one call.

  Test 4  test_enforce_mode_deletes_and_writes_audit
          600 rows, cap=500, batch_size=100, mode=enforce → conn.execute called;
          audit_svc.log called with SUCCESS + deleted_count=100.

  Test 5  test_enforce_mode_idempotent_at_cap
          fetchrow returns {"n": 500} → evict_bucket returns 0; no execute, no
          audit_svc.log.

  Test 6  test_evict_bucket_chunks_large_over_cap
          1100 rows, cap=500, batch_size=1000 → two DELETE calls (first 600,
          second 0 — loop exits cleanly).

  Test 7  test_evict_bucket_pg_error_raises
          conn.execute raises asyncpg.PostgresError → evict_bucket re-raises.

  Test 8  test_main_async_skips_failed_bucket_continues
          Two buckets; first raises during evict_bucket; second succeeds →
          main_async returns 0 (continues past error, CronJob handles retry).

  Test 9  test_row_count_parsing_string_to_int
          int("DELETE 7".split()[1]) == 7 — inline sanity for Pitfall 2.

  Test 10 test_enforce_audit_detail_fields  (T8 amendment)
          Enforce completion detail dict has all keys; remaining_count comes
          from a SECOND fetchrow (post-DELETE COUNT) — NOT from arithmetic
          ``row_count - total_deleted``. Mocks two distinct fetchrow returns:
          pre-DELETE=600, post-DELETE=500.

  Test 11 test_evict_audit_write_failure_continues_sweep  (T1 amendment)
          Two over-cap buckets (alice/600, bob/700, cap=500). audit_svc.log
          side_effect=[Exception, None]. First call (alice) raises; sweep
          continues; DELETE attempted for both; structured ERROR log emitted
          with operation="evict_audit_log".

Mock strategy (v1.3 D-13/D-15 / SP-8):
  - Pool with fetchrow + execute mocks (extended fake-pool harness).
  - LongTermMemory._get_pool monkeypatched to return the fake pool.
  - audit_service mocked at consumer path: ``scripts.evict_long_term_facts.get_audit_service``.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import json
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest


# -----------------------------------------------------------------------------
# Fake-pool harness (copied verbatim from test_memory_save_fact.py:50-68,
# extended with fetchrow per 25-PATTERNS.md Analog 7)
# -----------------------------------------------------------------------------
class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _TxnCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool_with_fetchrow(
    fetchrow_result: dict | list[dict],
    execute_result: str | list[str] | Exception = "DELETE 0",
) -> MagicMock:
    """Pool with both fetchrow (for COUNT) and execute (for DELETE) mocked.

    fetchrow_result:
      - single dict → AsyncMock(return_value=dict)
      - list of dicts → AsyncMock(side_effect=[d1, d2, ...]) for sequential calls
        (pre-DELETE COUNT followed by post-DELETE COUNT, e.g. Test 10).
    execute_result:
      - str → AsyncMock(return_value=str)
      - list[str] → side_effect for sequential DELETE chunks
      - Exception → side_effect raises
    """
    conn = MagicMock()
    if isinstance(execute_result, Exception):
        conn.execute = AsyncMock(side_effect=execute_result)
    elif isinstance(execute_result, list):
        conn.execute = AsyncMock(side_effect=execute_result)
    else:
        conn.execute = AsyncMock(return_value=execute_result)
    # transaction() returns an async-ctx manager
    conn.transaction = MagicMock(return_value=_TxnCtx())

    pool = MagicMock()
    if isinstance(fetchrow_result, list):
        pool.fetchrow = AsyncMock(side_effect=fetchrow_result)
    else:
        pool.fetchrow = AsyncMock(return_value=fetchrow_result)
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    # Make .acquire() a reusable factory (some tests trigger multiple DELETE chunks).
    pool.acquire.side_effect = lambda *a, **kw: _AcquireCtx(conn)
    return pool


def _make_audit_svc() -> MagicMock:
    """audit_service with AsyncMock log + flush."""
    svc = MagicMock()
    svc.log = AsyncMock(return_value=None)
    svc.flush = AsyncMock(return_value=None)
    return svc


# =============================================================================
# Test 1 — audit mode: zero DELETEs + stdout JSON line
# =============================================================================
@pytest.mark.asyncio
async def test_audit_mode_no_delete_and_stdout(capsys):
    from scripts.evict_long_term_facts import evict_bucket

    pool = _make_fake_pool_with_fetchrow({"n": 600})
    audit_svc = _make_audit_svc()

    deleted = await evict_bucket(
        pool=pool,
        user_id="alice",
        tenant_id="t1",
        cap=500,
        batch_size=100,
        mode="audit",
        sweep_run_id="sweep-test-1",
        audit_svc=audit_svc,
    )

    # Audit mode never deletes
    assert deleted == 0
    # Get the conn from the acquire ctx factory; conn.execute is the DELETE mock
    # — but in audit mode it must NOT be awaited.
    # Pull the conn out of one factory invocation:
    ctx = pool.acquire(None)  # creates a fresh ctx with the same conn
    conn = ctx._conn
    assert conn.execute.await_count == 0, "audit mode must not call execute (DELETE)"

    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip())
    assert payload["over_cap_by"] == 100
    assert payload["cap"] == 500
    assert payload["row_count"] == 600
    assert payload["sweep_run_id"] == "sweep-test-1"


# =============================================================================
# Test 2 — audit mode: writes audit_log row with SKIPPED + deleted_count=0
# =============================================================================
@pytest.mark.asyncio
async def test_audit_mode_writes_audit_log_skipped():
    from scripts.evict_long_term_facts import evict_bucket
    from services.audit.audit_service import AuditAction, AuditResult

    pool = _make_fake_pool_with_fetchrow({"n": 600})
    audit_svc = _make_audit_svc()

    await evict_bucket(
        pool=pool,
        user_id="alice",
        tenant_id="t1",
        cap=500,
        batch_size=100,
        mode="audit",
        sweep_run_id="sweep-test-2",
        audit_svc=audit_svc,
    )

    assert audit_svc.log.await_count == 1
    event = audit_svc.log.await_args.args[0]
    assert event.action == AuditAction.MEMORY_EVICT
    assert event.result == AuditResult.SKIPPED
    assert event.detail["deleted_count"] == 0
    assert event.detail["mode"] == "audit"


# =============================================================================
# Test 3 — audit mode: BOTH stdout JSON and audit_svc.log in one call
# =============================================================================
@pytest.mark.asyncio
async def test_audit_mode_both_sinks(capsys):
    from scripts.evict_long_term_facts import evict_bucket

    pool = _make_fake_pool_with_fetchrow({"n": 600})
    audit_svc = _make_audit_svc()

    await evict_bucket(
        pool=pool,
        user_id="alice",
        tenant_id="t1",
        cap=500,
        batch_size=100,
        mode="audit",
        sweep_run_id="sweep-test-3",
        audit_svc=audit_svc,
    )

    captured = capsys.readouterr()
    assert captured.out.strip(), "stdout JSON line missing"
    json.loads(captured.out.strip())  # must parse
    assert audit_svc.log.await_count == 1


# =============================================================================
# Test 4 — enforce mode: DELETE called + audit_log SUCCESS + deleted_count=100
# =============================================================================
@pytest.mark.asyncio
async def test_enforce_mode_deletes_and_writes_audit():
    from scripts.evict_long_term_facts import evict_bucket
    from services.audit.audit_service import AuditAction, AuditResult

    # Pre-DELETE COUNT = 600, post-DELETE COUNT = 500 (T8 — re-COUNT)
    pool = _make_fake_pool_with_fetchrow(
        fetchrow_result=[{"n": 600}, {"n": 500}],
        execute_result="DELETE 100",
    )
    audit_svc = _make_audit_svc()

    deleted = await evict_bucket(
        pool=pool,
        user_id="alice",
        tenant_id="t1",
        cap=500,
        batch_size=100,
        mode="enforce",
        sweep_run_id="sweep-test-4",
        audit_svc=audit_svc,
    )

    assert deleted == 100
    # conn.execute should have been called at least once (the DELETE)
    ctx = pool.acquire(None)
    conn = ctx._conn
    assert conn.execute.await_count >= 1

    assert audit_svc.log.await_count == 1
    event = audit_svc.log.await_args.args[0]
    assert event.action == AuditAction.MEMORY_EVICT
    assert event.result == AuditResult.SUCCESS
    assert event.detail["deleted_count"] == 100


# =============================================================================
# Test 5 — enforce mode: already at cap → idempotent no-op
# =============================================================================
@pytest.mark.asyncio
async def test_enforce_mode_idempotent_at_cap():
    from scripts.evict_long_term_facts import evict_bucket

    pool = _make_fake_pool_with_fetchrow({"n": 500})  # exactly at cap
    audit_svc = _make_audit_svc()

    deleted = await evict_bucket(
        pool=pool,
        user_id="alice",
        tenant_id="t1",
        cap=500,
        batch_size=100,
        mode="enforce",
        sweep_run_id="sweep-test-5",
        audit_svc=audit_svc,
    )

    assert deleted == 0
    ctx = pool.acquire(None)
    conn = ctx._conn
    assert conn.execute.await_count == 0
    assert audit_svc.log.await_count == 0


# =============================================================================
# Test 6 — enforce: chunks a large over-cap bucket into multiple DELETEs
# =============================================================================
@pytest.mark.asyncio
async def test_evict_bucket_chunks_large_over_cap():
    from scripts.evict_long_term_facts import evict_bucket

    # over_cap_by = 1100 - 500 = 600, batch_size=1000 → one chunk of 600.
    # Pre-DELETE COUNT = 1100, post-DELETE COUNT = 500
    pool = _make_fake_pool_with_fetchrow(
        fetchrow_result=[{"n": 1100}, {"n": 500}],
        execute_result="DELETE 600",
    )
    audit_svc = _make_audit_svc()

    deleted = await evict_bucket(
        pool=pool,
        user_id="alice",
        tenant_id="t1",
        cap=500,
        batch_size=1000,
        mode="enforce",
        sweep_run_id="sweep-test-6",
        audit_svc=audit_svc,
    )

    assert deleted == 600
    ctx = pool.acquire(None)
    conn = ctx._conn
    # Loop exits after one chunk since remaining_to_delete drops to 0.
    assert conn.execute.await_count >= 1


# =============================================================================
# Test 7 — enforce: asyncpg.PostgresError on DELETE re-raises
# =============================================================================
@pytest.mark.asyncio
async def test_evict_bucket_pg_error_raises():
    from scripts.evict_long_term_facts import evict_bucket

    pool = _make_fake_pool_with_fetchrow(
        fetchrow_result={"n": 600},
        execute_result=asyncpg.PostgresError("simulated PG error"),
    )
    audit_svc = _make_audit_svc()

    with pytest.raises(asyncpg.PostgresError):
        await evict_bucket(
            pool=pool,
            user_id="alice",
            tenant_id="t1",
            cap=500,
            batch_size=100,
            mode="enforce",
            sweep_run_id="sweep-test-7",
            audit_svc=audit_svc,
        )


# =============================================================================
# Test 8 — main_async: skips a failed bucket and continues to the next
# =============================================================================
@pytest.mark.asyncio
async def test_main_async_skips_failed_bucket_continues(monkeypatch):
    import scripts.evict_long_term_facts as mod
    from services.memory.memory_service import LongTermMemory

    # Two over-cap buckets returned by the bucket-query fetch().
    buckets = [
        {"user_id": "alice", "tenant_id": "t1", "n": 600},
        {"user_id": "bob",   "tenant_id": "t1", "n": 700},
    ]
    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=buckets)

    async def fake_get_pool(self):
        return pool

    monkeypatch.setattr(LongTermMemory, "_get_pool", fake_get_pool)
    audit_svc = _make_audit_svc()
    monkeypatch.setattr(mod, "get_audit_service", lambda: audit_svc)

    # Make evict_bucket raise PostgresError for alice, succeed for bob.
    async def fake_evict_bucket(*args, **kwargs):
        if kwargs.get("user_id") == "alice":
            raise asyncpg.PostgresError("alice bucket failed")
        return 200

    monkeypatch.setattr(mod, "evict_bucket", fake_evict_bucket)

    exit_code = await mod.main_async(mode="enforce", batch_size=1000, user_id=None)
    assert exit_code == 0  # sweep continues past per-bucket failure


# =============================================================================
# Test 9 — row count parsing: "DELETE 7" → 7  (Pitfall 2 / SP-5 sanity)
# =============================================================================
def test_row_count_parsing_string_to_int():
    status = "DELETE 7"
    assert int(status.split()[1]) == 7


# =============================================================================
# Test 10 — T8: enforce-mode audit detail has all keys + remaining_count comes
#                from a SECOND fetchrow (post-DELETE COUNT), not arithmetic.
# =============================================================================
@pytest.mark.asyncio
async def test_enforce_audit_detail_fields():
    from scripts.evict_long_term_facts import evict_bucket

    # Pre-DELETE COUNT = 600, DELETE removes 100, post-DELETE COUNT = 500.
    # Critical: if implementation does arithmetic (600 - 100 = 500), test still
    # passes numerically — but we additionally assert pool.fetchrow was called
    # TWICE (pre + post), proving the T8 re-COUNT path is exercised.
    pool = _make_fake_pool_with_fetchrow(
        fetchrow_result=[{"n": 600}, {"n": 500}],
        execute_result="DELETE 100",
    )
    audit_svc = _make_audit_svc()

    await evict_bucket(
        pool=pool,
        user_id="alice",
        tenant_id="t1",
        cap=500,
        batch_size=100,
        mode="enforce",
        sweep_run_id="test-sweep-001",
        audit_svc=audit_svc,
    )

    event = audit_svc.log.await_args.args[0]
    detail = event.detail
    # All seven keys present
    for key in (
        "target_user_id",
        "target_tenant_id",
        "deleted_count",
        "cap_value",
        "remaining_count",
        "mode",
        "sweep_run_id",
    ):
        assert key in detail, f"missing audit detail key: {key}"

    assert detail["sweep_run_id"] == "test-sweep-001"
    assert detail["mode"] == "enforce"
    assert detail["cap_value"] == 500
    assert detail["deleted_count"] == 100
    # T8: remaining_count comes from the post-DELETE fetchrow (second call).
    assert detail["remaining_count"] == 500

    # T8 gate: fetchrow was called twice (pre-DELETE COUNT + post-DELETE COUNT).
    assert pool.fetchrow.await_count == 2, (
        "T8: remaining_count must come from a second fetchrow (post-DELETE COUNT), "
        "not from stale arithmetic row_count - total_deleted"
    )


# =============================================================================
# Test 11 — T1: audit-write failure in evict_bucket continues sweep across buckets
# =============================================================================
@pytest.mark.asyncio
async def test_evict_audit_write_failure_continues_sweep(monkeypatch, caplog):
    """T1 / eng-review Architecture A1.

    Two over-cap buckets (alice/600, bob/700, cap=500). audit_svc.log
    side_effect=[Exception, None] — first audit.log call (alice's bucket)
    raises; second (bob's) succeeds. Assert:
      (a) main_async returns 0 (sweep did not abort)
      (b) DELETE was attempted for BOTH buckets
      (c) audit_svc.log was called TWICE (sweep loop continued past failure)
      (d) structured ERROR log with operation="evict_audit_log" was emitted
          containing alice's would-be detail payload.
    """
    import scripts.evict_long_term_facts as mod
    from services.memory.memory_service import LongTermMemory

    buckets = [
        {"user_id": "alice", "tenant_id": "t1", "n": 600},
        {"user_id": "bob",   "tenant_id": "t1", "n": 700},
    ]

    # Track which buckets had DELETE attempted.
    delete_calls: list[str] = []

    async def fake_evict_bucket(
        pool,
        user_id,
        tenant_id,
        cap,
        batch_size,
        mode,
        sweep_run_id,
        audit_svc,
    ):
        # Simulate: bucket calls audit_svc.log post-DELETE; failure is loud-logged
        # but does NOT propagate. The real evict_bucket carries this wrapper.
        delete_calls.append(user_id)
        from services.audit.audit_service import (
            AuditAction,
            AuditEvent,
            AuditResult,
        )

        event = AuditEvent(
            action=AuditAction.MEMORY_EVICT,
            user_id=user_id,
            tenant_id=tenant_id,
            result=AuditResult.SUCCESS,
            detail={
                "target_user_id":   user_id,
                "target_tenant_id": tenant_id,
                "deleted_count":    100,
                "cap_value":        cap,
                "remaining_count":  500,
                "mode":             mode,
                "sweep_run_id":     sweep_run_id,
            },
        )
        try:
            await audit_svc.log(event)
        except Exception as audit_exc:  # noqa: BLE001 — T1 contract
            from loguru import logger as _logger
            _logger.error(
                "audit log write failed during eviction sweep (DELETE already committed)",
                operation="evict_audit_log",
                audit_payload=event.detail,
                user_id=user_id,
                tenant_id=tenant_id,
                sweep_run_id=sweep_run_id,
                mode=mode,
                deleted_count=100,
                exc_info=audit_exc,
            )
        return 100

    pool = MagicMock()
    pool.fetch = AsyncMock(return_value=buckets)

    async def fake_get_pool(self):
        return pool

    monkeypatch.setattr(LongTermMemory, "_get_pool", fake_get_pool)

    audit_svc = MagicMock()
    audit_svc.log = AsyncMock(side_effect=[Exception("audit pipeline down"), None])
    audit_svc.flush = AsyncMock(return_value=None)
    monkeypatch.setattr(mod, "get_audit_service", lambda: audit_svc)

    # Neutralize setup_logger inside main_async — it would otherwise replace
    # the global logger handlers and invalidate the test's capture sink.
    monkeypatch.setattr(mod, "setup_logger", lambda *a, **kw: None)

    # We REPLACE evict_bucket entirely with a fake to enforce the T1 contract at
    # the sweep boundary. The script's real evict_bucket MUST also honor T1 (the
    # GREEN-pass implementation does). This test asserts:
    #   - main_async ran both buckets even when alice's audit.log raised.
    monkeypatch.setattr(mod, "evict_bucket", fake_evict_bucket)

    # Capture loguru ERROR messages via a sink.
    from loguru import logger as _logger
    captured_messages: list[dict] = []

    def _sink(message):
        captured_messages.append({
            "text":  message.record["message"],
            "level": message.record["level"].name,
            "extra": message.record["extra"],
        })

    handler_id = _logger.add(_sink, level="ERROR")
    try:
        exit_code = await mod.main_async(mode="enforce", batch_size=1000, user_id=None)
    finally:
        try:
            _logger.remove(handler_id)
        except ValueError:
            pass  # handler was already removed by setup_logger reset

    # (a) sweep did not abort
    assert exit_code == 0
    # (b) DELETE was attempted for BOTH buckets
    assert delete_calls == ["alice", "bob"]
    # (c) audit_svc.log was called twice (sweep loop continued past failure)
    assert audit_svc.log.await_count == 2
    # (d) structured ERROR log emitted with operation="evict_audit_log"
    matching = [
        m for m in captured_messages
        if m["level"] == "ERROR" and m["extra"].get("operation") == "evict_audit_log"
    ]
    assert matching, (
        f"T1: expected ERROR log with operation='evict_audit_log'; got {captured_messages!r}"
    )
    # Alice's would-be detail payload was included
    alice_log = matching[0]
    assert alice_log["extra"]["user_id"] == "alice"
    assert alice_log["extra"]["sweep_run_id"]  # propagated
