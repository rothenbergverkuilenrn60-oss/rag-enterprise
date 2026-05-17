"""tests/unit/test_backfill_fact_embeddings.py — Phase 24 / MEM-07 (Plan 24-06 RED).

9 unit tests covering the backfill_fact_embeddings CLI behavior:

  Test 1: dry-run makes zero embed_batch + execute calls; logs "Would embed N facts".
  Test 2: dry-run log output contains "Would embed", "tokens", "$".
  Test 3 (T4 amended): happy-path — ONE batch UPDATE via unnest (not 100 row-by-row);
          args[1] (ids list) and args[2] (vectors list) each length 100.
  Test 4: idempotent second run — zero new embed_batch, zero UPDATE executes.
  Test 5 (T5 amended): parametrized over asyncpg.PostgresError + asyncpg.InterfaceError;
          both caught by narrow `except asyncpg.Error as exc:`.
  Test 6: embedder RuntimeError → return 1, zero UPDATE attempted.
  Test 7: --resume-from-id appends "AND id > $1" to cursor SELECT SQL.
  Test 8: --batch-size respected in LIMIT clause.
  Test 9: script reuses LongTermMemory pool (no standalone asyncpg.create_pool).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import uuid
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

# ---------------------------------------------------------------------------
# Fake-pool harness (extended from test_memory_save_fact.py analog 9/11)
# ---------------------------------------------------------------------------

class _AcquireCtx:
    """Async context manager that yields the conn and tracks txn state."""

    def __init__(self, conn: MagicMock) -> None:
        self._conn = conn

    async def __aenter__(self) -> MagicMock:
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _TxnCtx:
    """Async context manager simulating conn.transaction()."""

    def __init__(self, conn: MagicMock, raises_on_exit: BaseException | None = None) -> None:
        self._conn = conn
        self._raises_on_exit = raises_on_exit
        self.entered = 0

    async def __aenter__(self) -> "_TxnCtx":
        self.entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None and self._raises_on_exit is not None:
            # Simulate asyncpg raising InterfaceError on txn exit during failure
            raise self._raises_on_exit
        return False


def _make_fake_pool(
    execute_mock: AsyncMock,
    fetch_mock: AsyncMock,
    fetchrow_mock: AsyncMock,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Return (pool, conn, txn_ctx).

    pool.acquire() yields conn.
    conn.execute = execute_mock
    conn.fetch = fetch_mock
    pool.fetchrow = fetchrow_mock  (for _count_remaining)
    conn.transaction() returns a _TxnCtx.
    """
    txn_ctx = _TxnCtx(MagicMock())
    conn = MagicMock()
    conn.execute = execute_mock
    conn.fetch = fetch_mock
    conn.transaction = MagicMock(return_value=txn_ctx)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    pool.fetchrow = fetchrow_mock
    pool.fetch = fetch_mock  # cursor SELECT called directly on pool

    return pool, conn, txn_ctx


def _make_100_rows() -> list[dict]:
    return [{"id": uuid.uuid4(), "fact": f"fact_{i}"} for i in range(100)]


# ---------------------------------------------------------------------------
# Helper: capture loguru logs in tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def loguru_caplog(caplog):
    """Propagate loguru output into pytest's caplog."""
    import logging

    from loguru import logger

    class _PropagateHandler(logging.Handler):
        def emit(self, record) -> None:
            logging.getLogger(record.name).handle(record)

    handler_id = logger.add(_PropagateHandler(), format="{message}")
    yield caplog
    logger.remove(handler_id)


# ---------------------------------------------------------------------------
# Test 1: dry-run makes zero embed_batch + execute calls
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dry_run_no_api_calls(monkeypatch, loguru_caplog):
    # Deferred import — will raise ModuleNotFoundError if script absent (RED gate).
    import scripts.backfill_fact_embeddings as bf_mod  # noqa: PLC0415
    from scripts.backfill_fact_embeddings import backfill  # noqa: PLC0415

    embed_batch = AsyncMock()
    fake_embedder = MagicMock()
    fake_embedder.embed_batch = embed_batch
    monkeypatch.setattr("scripts.backfill_fact_embeddings.get_embedder", lambda: fake_embedder)

    fetchrow_mock = AsyncMock(return_value={"n": 42})
    execute_mock = AsyncMock()
    fetch_mock = AsyncMock(return_value=[])
    pool, conn, _ = _make_fake_pool(execute_mock, fetch_mock, fetchrow_mock)

    monkeypatch.setattr(
        bf_mod.LongTermMemory,
        "_get_pool",
        AsyncMock(return_value=pool),
    )

    with loguru_caplog.at_level("INFO"):
        result = await backfill(batch_size=100, dry_run=True, resume_from_id=None)

    assert result == 0
    embed_batch.assert_not_awaited()
    assert execute_mock.await_count == 0
    # fetchrow for count IS called; fetch (cursor) is NOT
    assert fetch_mock.await_count == 0

    log_text = " ".join(loguru_caplog.messages)
    assert "Would embed" in log_text or "42" in log_text or "would" in log_text.lower()


# ---------------------------------------------------------------------------
# Test 2: dry-run log output format contains required substrings
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dry_run_cost_estimate_format(monkeypatch, loguru_caplog):
    import scripts.backfill_fact_embeddings as bf_mod  # noqa: PLC0415
    from scripts.backfill_fact_embeddings import backfill  # noqa: PLC0415

    fake_embedder = MagicMock()
    fake_embedder.embed_batch = AsyncMock()
    monkeypatch.setattr("scripts.backfill_fact_embeddings.get_embedder", lambda: fake_embedder)

    fetchrow_mock = AsyncMock(return_value={"n": 42})
    execute_mock = AsyncMock()
    fetch_mock = AsyncMock(return_value=[])
    pool, conn, _ = _make_fake_pool(execute_mock, fetch_mock, fetchrow_mock)

    monkeypatch.setattr(
        bf_mod.LongTermMemory,
        "_get_pool",
        AsyncMock(return_value=pool),
    )

    with loguru_caplog.at_level("INFO"):
        await backfill(batch_size=100, dry_run=True, resume_from_id=None)

    log_text = " ".join(loguru_caplog.messages)
    # Format assertions — substring match only (not exact text per analog 11 anti-pattern)
    assert "42" in log_text
    assert "tokens" in log_text
    assert "$" in log_text


# ---------------------------------------------------------------------------
# Test 3: happy-path — ONE batch UPDATE per batch (T4), args[1] and args[2] length 100
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_happy_path_batch_commit(monkeypatch):
    import scripts.backfill_fact_embeddings as bf_mod  # noqa: PLC0415
    from scripts.backfill_fact_embeddings import backfill  # noqa: PLC0415

    rows = _make_100_rows()
    fake_vectors = [[0.1] * 1024] * 100

    embed_batch = AsyncMock(return_value=fake_vectors)
    fake_embedder = MagicMock()
    fake_embedder.embed_batch = embed_batch
    monkeypatch.setattr("scripts.backfill_fact_embeddings.get_embedder", lambda: fake_embedder)

    fetchrow_mock = AsyncMock(return_value={"n": 100})
    execute_mock = AsyncMock()
    # First fetch returns 100 rows; second fetch returns [] (cursor exhausted)
    fetch_mock = AsyncMock(side_effect=[rows, []])
    pool, conn, txn_ctx = _make_fake_pool(execute_mock, fetch_mock, fetchrow_mock)

    monkeypatch.setattr(
        bf_mod.LongTermMemory,
        "_get_pool",
        AsyncMock(return_value=pool),
    )

    result = await backfill(batch_size=100, dry_run=False, resume_from_id=None)

    assert result == 0

    # T4: exactly ONE execute call per batch (not 100 row-by-row)
    assert execute_mock.await_count == 1, (
        f"Expected 1 batch UPDATE (T4), got {execute_mock.await_count} execute calls"
    )

    # Spy args: args[1] = ids list, args[2] = vectors list
    call_args = execute_mock.call_args
    ids_arg = call_args.args[1]
    vectors_arg = call_args.args[2]
    assert len(ids_arg) == 100, f"Expected 100 ids, got {len(ids_arg)}"
    assert len(vectors_arg) == 100, f"Expected 100 vectors, got {len(vectors_arg)}"

    # Transaction entered once
    assert txn_ctx.entered == 1

    # embed_batch called once
    embed_batch.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 4: idempotent second run — zero embed_batch, zero execute on second call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idempotent_second_run(monkeypatch):
    import scripts.backfill_fact_embeddings as bf_mod  # noqa: PLC0415
    from scripts.backfill_fact_embeddings import backfill  # noqa: PLC0415

    rows = _make_100_rows()
    fake_vectors = [[0.1] * 1024] * 100

    embed_batch = AsyncMock(return_value=fake_vectors)
    fake_embedder = MagicMock()
    fake_embedder.embed_batch = embed_batch
    monkeypatch.setattr("scripts.backfill_fact_embeddings.get_embedder", lambda: fake_embedder)

    execute_mock = AsyncMock()
    # First run: count=100, rows=[100 rows, []]
    # Second run: count=0, rows=[]
    fetchrow_mock = AsyncMock(side_effect=[{"n": 100}, {"n": 0}])
    fetch_mock = AsyncMock(side_effect=[rows, [], []])
    pool, conn, _ = _make_fake_pool(execute_mock, fetch_mock, fetchrow_mock)

    monkeypatch.setattr(
        bf_mod.LongTermMemory,
        "_get_pool",
        AsyncMock(return_value=pool),
    )

    # First run
    result1 = await backfill(batch_size=100, dry_run=False, resume_from_id=None)
    assert result1 == 0

    embed_count_after_first = embed_batch.await_count
    execute_count_after_first = execute_mock.await_count

    # Second run (idempotent — no rows left)
    result2 = await backfill(batch_size=100, dry_run=False, resume_from_id=None)
    assert result2 == 0

    # No new embed_batch or execute calls on second run
    assert embed_batch.await_count == embed_count_after_first
    assert execute_mock.await_count == execute_count_after_first


# ---------------------------------------------------------------------------
# Test 5 (T5 amended): batch rollback — parametrized over asyncpg.PostgresError + InterfaceError
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("exc_instance", [
    asyncpg.PostgresError("simulated_postgres"),
    asyncpg.InterfaceError("simulated_iface"),
])
@pytest.mark.asyncio
async def test_batch_rollback_on_failure(monkeypatch, exc_instance):
    """Both subclasses of asyncpg.Error are caught by narrow `except asyncpg.Error`."""
    import scripts.backfill_fact_embeddings as bf_mod  # noqa: PLC0415
    from scripts.backfill_fact_embeddings import backfill  # noqa: PLC0415

    rows = _make_100_rows()
    fake_vectors = [[0.1] * 1024] * 100

    embed_batch = AsyncMock(return_value=fake_vectors)
    fake_embedder = MagicMock()
    fake_embedder.embed_batch = embed_batch
    monkeypatch.setattr("scripts.backfill_fact_embeddings.get_embedder", lambda: fake_embedder)

    fetchrow_mock = AsyncMock(return_value={"n": 100})
    # T4: single execute per batch raises the asyncpg error on first call
    execute_mock = AsyncMock(side_effect=exc_instance)
    fetch_mock = AsyncMock(side_effect=[rows, []])
    pool, conn, txn_ctx = _make_fake_pool(execute_mock, fetch_mock, fetchrow_mock)

    monkeypatch.setattr(
        bf_mod.LongTermMemory,
        "_get_pool",
        AsyncMock(return_value=pool),
    )

    result = await backfill(batch_size=100, dry_run=False, resume_from_id=None)

    # T5: narrow except asyncpg.Error catches both PostgresError and InterfaceError
    assert result == 1, f"Expected exit code 1 on {type(exc_instance).__name__}, got {result}"

    # Txn was entered (then rolled back)
    assert txn_ctx.entered == 1


# ---------------------------------------------------------------------------
# Test 6: embedder RuntimeError → return 1, zero UPDATE
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_embedder_failure_exit_1(monkeypatch, loguru_caplog):
    import scripts.backfill_fact_embeddings as bf_mod  # noqa: PLC0415
    from scripts.backfill_fact_embeddings import backfill  # noqa: PLC0415

    rows = _make_100_rows()

    embed_batch = AsyncMock(side_effect=RuntimeError("ollama down"))
    fake_embedder = MagicMock()
    fake_embedder.embed_batch = embed_batch
    monkeypatch.setattr("scripts.backfill_fact_embeddings.get_embedder", lambda: fake_embedder)

    fetchrow_mock = AsyncMock(return_value={"n": 100})
    execute_mock = AsyncMock()
    fetch_mock = AsyncMock(side_effect=[rows, []])
    pool, conn, _ = _make_fake_pool(execute_mock, fetch_mock, fetchrow_mock)

    monkeypatch.setattr(
        bf_mod.LongTermMemory,
        "_get_pool",
        AsyncMock(return_value=pool),
    )

    with loguru_caplog.at_level("ERROR"):
        result = await backfill(batch_size=100, dry_run=False, resume_from_id=None)

    assert result == 1
    # No UPDATE attempted on embedder failure
    assert execute_mock.await_count == 0

    log_text = " ".join(loguru_caplog.messages)
    assert "embedder failed" in log_text or "embed" in log_text.lower()


# ---------------------------------------------------------------------------
# Test 7: --resume-from-id appends "AND id > $1" to cursor SELECT
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resume_from_id_uses_cursor_filter(monkeypatch):
    import scripts.backfill_fact_embeddings as bf_mod  # noqa: PLC0415
    from scripts.backfill_fact_embeddings import backfill  # noqa: PLC0415

    rows = _make_100_rows()
    fake_vectors = [[0.1] * 1024] * 100

    embed_batch = AsyncMock(return_value=fake_vectors)
    fake_embedder = MagicMock()
    fake_embedder.embed_batch = embed_batch
    monkeypatch.setattr("scripts.backfill_fact_embeddings.get_embedder", lambda: fake_embedder)

    resume_id = "abc-uuid-1234"
    fetchrow_mock = AsyncMock(return_value={"n": 100})
    execute_mock = AsyncMock()
    fetch_mock = AsyncMock(side_effect=[rows, []])
    pool, conn, _ = _make_fake_pool(execute_mock, fetch_mock, fetchrow_mock)

    monkeypatch.setattr(
        bf_mod.LongTermMemory,
        "_get_pool",
        AsyncMock(return_value=pool),
    )

    await backfill(batch_size=100, dry_run=False, resume_from_id=resume_id)

    # Inspect the fetch call args — should contain "AND id > " filter
    assert fetch_mock.await_count >= 1
    first_fetch_call = fetch_mock.call_args_list[0]
    fetch_sql = first_fetch_call.args[0]
    assert "id >" in fetch_sql or "AND id >" in fetch_sql, (
        f"Expected 'AND id >' in cursor SELECT, got SQL: {fetch_sql!r}"
    )
    # Resume ID should be passed as a parameter
    fetch_args = first_fetch_call.args
    assert resume_id in fetch_args, (
        f"Expected resume_from_id={resume_id!r} in fetch args, got {fetch_args}"
    )


# ---------------------------------------------------------------------------
# Test 8: --batch-size respected as LIMIT in SELECT
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_batch_size_parameter_respected(monkeypatch):
    import scripts.backfill_fact_embeddings as bf_mod  # noqa: PLC0415
    from scripts.backfill_fact_embeddings import backfill  # noqa: PLC0415

    rows = [{"id": uuid.uuid4(), "fact": f"fact_{i}"} for i in range(50)]
    fake_vectors = [[0.1] * 1024] * 50

    embed_batch = AsyncMock(return_value=fake_vectors)
    fake_embedder = MagicMock()
    fake_embedder.embed_batch = embed_batch
    monkeypatch.setattr("scripts.backfill_fact_embeddings.get_embedder", lambda: fake_embedder)

    fetchrow_mock = AsyncMock(return_value={"n": 50})
    execute_mock = AsyncMock()
    fetch_mock = AsyncMock(side_effect=[rows, []])
    pool, conn, _ = _make_fake_pool(execute_mock, fetch_mock, fetchrow_mock)

    monkeypatch.setattr(
        bf_mod.LongTermMemory,
        "_get_pool",
        AsyncMock(return_value=pool),
    )

    await backfill(batch_size=50, dry_run=False, resume_from_id=None)

    assert fetch_mock.await_count >= 1
    first_fetch_call = fetch_mock.call_args_list[0]
    fetch_args = first_fetch_call.args
    # batch_size=50 should appear as LIMIT param
    assert 50 in fetch_args, (
        f"Expected LIMIT=50 in fetch args, got {fetch_args}"
    )


# ---------------------------------------------------------------------------
# Test 9: script reuses LongTermMemory pool — no standalone asyncpg.create_pool
# ---------------------------------------------------------------------------
def test_reuses_long_term_memory_pool():
    """Pitfall 1 mitigation: script uses LongTermMemory._get_pool, not create_pool."""
    import inspect

    # Import the script module
    import scripts.backfill_fact_embeddings as bf_mod  # noqa: PLC0415

    # LongTermMemory must be imported from services.memory.memory_service
    from services.memory.memory_service import LongTermMemory  # noqa: PLC0415

    assert bf_mod.LongTermMemory is LongTermMemory, (
        "Script must import LongTermMemory from services.memory.memory_service"
    )

    # asyncpg.create_pool must NOT appear in the script source (non-comment lines)
    source = inspect.getsource(bf_mod)
    non_comment_lines = [
        line for line in source.splitlines()
        if not line.strip().startswith("#")
    ]
    for line in non_comment_lines:
        assert "asyncpg.create_pool" not in line, (
            f"Pitfall 1: script must not call asyncpg.create_pool. Found in: {line!r}"
        )
