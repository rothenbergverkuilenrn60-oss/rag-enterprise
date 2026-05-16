"""Integration tests for Plan 25-05 / SC-1 + SC-2 — eviction CLI e2e.

Covers ROADMAP success criteria:
    SC-1 — audit-mode produces stdout JSON + zero deletes; enforce drops
           600-row bucket to exactly cap=500; small (100-row) bucket untouched.
    SC-2 — tie-break correctness with cap=2, 3 seeded rows (importance ASC,
           created_at ASC): the oldest low-importance row is removed; the
           newer low-importance row + the high-importance row survive.

Drives ``scripts/evict_long_term_facts.main_async`` directly via
``await main_async(mode=..., batch_size=..., user_id=None)`` against the
live pgvector pool (Pitfall 1 — pool obtained via LongTermMemory()._get_pool
inside the script so register_vector codec is inherited).

T4 (eng-review amendment): every seeded row carries
``embedding=[0.0] * 1024`` (dummy 1024-dim zero vector). Eviction reads
only ``importance`` + ``created_at`` + ``id`` so the value is irrelevant;
the non-NULL seed future-proofs the suite against any subsequent migration
that tightens the ``embedding`` column to NOT NULL.

Skip-gated on ``PG_AVAILABLE`` so the suite collects + skips gracefully
on CI hosts without a live PostgreSQL + pgvector instance.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import io
import json
import sys
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.skipif(not PG_AVAILABLE, reason="PostgreSQL + pgvector not available — skipping eviction e2e tests"),
]

# Stable test-identity constants — scoped DELETE in clean_long_term_facts.
_USER_BIG = "test-evict-u-big"        # 600-row bucket (over cap=500)
_USER_SMALL = "test-evict-u-small"    # 100-row bucket (under cap=500)
_TENANT = "test-evict-t"
_CAP = 500


async def _seed_facts(
    pool: asyncpg.Pool,
    user_id: str,
    tenant_id: str,
    count: int,
    base_importance: float = 0.5,
) -> None:
    """Seed ``count`` rows into ``long_term_facts`` for ``(user_id, tenant_id)``.

    Each row carries a distinct ``created_at`` (now + i seconds) so the
    eviction ORDER BY (importance ASC, created_at ASC) has a deterministic
    tie-break.

    T4: ``embedding=[0.0] * 1024`` (dummy 1024-dim zero vector) on every
    INSERT — eviction never reads this column, but the non-NULL seed
    future-proofs against schema tightening to NOT NULL.
    """
    base_ts = datetime.now(timezone.utc)
    rows = [
        (
            user_id,
            tenant_id,
            f"seed-fact-{i}",
            base_importance,
            base_ts + timedelta(seconds=i),
            [0.0] * 1024,
        )
        for i in range(count)
    ]
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO long_term_facts
                (user_id, tenant_id, fact, importance, created_at, embedding)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            rows,
        )


@pytest.mark.asyncio
async def test_audit_mode_no_deletes(
    pgvector_pool: asyncpg.Pool,
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-1 audit half: audit-mode emits stdout JSON-line for the over-cap
    bucket and performs ZERO deletes (row count unchanged for both buckets).
    """
    from scripts import evict_long_term_facts as evict_mod

    await _seed_facts(pgvector_pool, _USER_BIG, _TENANT, count=600)
    await _seed_facts(pgvector_pool, _USER_SMALL, _TENANT, count=100)

    monkeypatch.setattr(evict_mod.settings, "memory_facts_cap_per_user", _CAP)

    # Capture stdout JSON-lines emitted by audit-mode (D-3.1).
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        rc = await evict_mod.main_async(mode="audit", batch_size=1000, user_id=None)
    finally:
        sys.stdout = old_stdout
    assert rc == 0, "main_async must return 0 on completion"

    # Parse JSON-lines from captured stdout; find the over-cap bucket entry.
    captured_lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    big_entries = []
    for line in captured_lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("bucket", {}).get("user_id") == _USER_BIG:
            big_entries.append(obj)
    assert len(big_entries) >= 1, (
        f"audit-mode must emit a stdout JSON-line for {_USER_BIG}; "
        f"captured: {captured_lines!r}"
    )
    assert big_entries[0]["over_cap_by"] == 100, (
        f"over_cap_by must be 100 (600 - 500); got {big_entries[0]}"
    )

    # SC-1 audit half: NO deletes — both buckets retain their seed counts.
    big_count = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        _USER_BIG, _TENANT,
    )
    assert big_count == 600, f"audit mode must not delete; got {big_count} rows"
    small_count = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        _USER_SMALL, _TENANT,
    )
    assert small_count == 100, f"small bucket untouched in audit mode; got {small_count}"


@pytest.mark.asyncio
async def test_enforce_mode_caps_bucket(
    pgvector_pool: asyncpg.Pool,
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-1 enforce half: enforce-mode drops 600-row bucket to exactly cap=500.

    The 100-row small bucket is below cap and must remain untouched.
    """
    from scripts import evict_long_term_facts as evict_mod

    await _seed_facts(pgvector_pool, _USER_BIG, _TENANT, count=600)
    await _seed_facts(pgvector_pool, _USER_SMALL, _TENANT, count=100)

    monkeypatch.setattr(evict_mod.settings, "memory_facts_cap_per_user", _CAP)

    rc = await evict_mod.main_async(mode="enforce", batch_size=1000, user_id=None)
    assert rc == 0

    big_count = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        _USER_BIG, _TENANT,
    )
    assert big_count == _CAP, (
        f"enforce mode must cap 600-row bucket at {_CAP}; got {big_count}"
    )

    small_count = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        _USER_SMALL, _TENANT,
    )
    assert small_count == 100, (
        f"small bucket below cap must be untouched; got {small_count}"
    )


@pytest.mark.asyncio
async def test_enforce_mode_small_bucket_untouched(
    pgvector_pool: asyncpg.Pool,
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-1 corollary: a bucket below cap is never queried for DELETE.

    Standalone variant of the small-bucket assertion in
    :func:`test_enforce_mode_caps_bucket` — kept separate so a regression that
    inadvertently sweeps under-cap buckets fails fast with a focused signal.
    """
    from scripts import evict_long_term_facts as evict_mod

    await _seed_facts(pgvector_pool, _USER_SMALL, _TENANT, count=100)
    monkeypatch.setattr(evict_mod.settings, "memory_facts_cap_per_user", _CAP)

    rc = await evict_mod.main_async(mode="enforce", batch_size=1000, user_id=None)
    assert rc == 0

    small_count = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        _USER_SMALL, _TENANT,
    )
    assert small_count == 100, (
        f"under-cap bucket must never lose rows; got {small_count}"
    )


@pytest.mark.asyncio
async def test_eviction_tiebreak_correctness(
    pgvector_pool: asyncpg.Pool,
    clean_long_term_facts: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SC-2: ORDER BY importance ASC, created_at ASC — oldest among the
    lowest-importance rows is the eviction victim.

    Seed three rows in one bucket with cap=2:
        A: importance=0.2, created_at=T0    (oldest low-importance — VICTIM)
        B: importance=0.2, created_at=T1    (middle low-importance — survives)
        C: importance=0.8, created_at=T2    (newest high-importance — survives)

    After enforce, only A must be gone; B + C remain (exactly at cap=2).
    """
    from scripts import evict_long_term_facts as evict_mod

    user_id = "test-evict-u-tiebreak"
    base_ts = datetime.now(timezone.utc)
    rows = [
        (user_id, _TENANT, "row-A", 0.2, base_ts + timedelta(seconds=0), [0.0] * 1024),
        (user_id, _TENANT, "row-B", 0.2, base_ts + timedelta(seconds=1), [0.0] * 1024),
        (user_id, _TENANT, "row-C", 0.8, base_ts + timedelta(seconds=2), [0.0] * 1024),
    ]
    async with pgvector_pool.acquire() as conn:
        ids = []
        for row in rows:
            inserted = await conn.fetchrow(
                """
                INSERT INTO long_term_facts
                    (user_id, tenant_id, fact, importance, created_at, embedding)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                *row,
            )
            ids.append(inserted["id"])
    a_id, b_id, c_id = ids

    monkeypatch.setattr(evict_mod.settings, "memory_facts_cap_per_user", 2)

    rc = await evict_mod.main_async(mode="enforce", batch_size=1000, user_id=None)
    assert rc == 0

    # Row A (lowest importance + oldest) must be deleted.
    a_remaining = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE id=$1", a_id,
    )
    assert a_remaining == 0, (
        "tie-break victim must be the oldest among lowest-importance rows; "
        f"row A (importance=0.2, oldest) still present"
    )

    # Row B (same importance as A but newer) must survive.
    b_remaining = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE id=$1", b_id,
    )
    assert b_remaining == 1, "row B (importance=0.2, newer than A) must survive"

    # Row C (highest importance) must survive.
    c_remaining = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE id=$1", c_id,
    )
    assert c_remaining == 1, "row C (importance=0.8) must survive"

    # Bucket is exactly at cap.
    total = await pgvector_pool.fetchval(
        "SELECT count(*) FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2",
        user_id, _TENANT,
    )
    assert total == 2, f"bucket must be exactly at cap=2 after enforce; got {total}"
