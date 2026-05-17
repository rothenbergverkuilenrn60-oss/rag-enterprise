"""SC-1 memory-side coverage — memory integration suite migrated to ``app_factory``.

Phase 27 / Plan 27-04 Task 3.

Mirrors the audit-side SC-1 migration test at
tests/integration/audit/test_audit_suite_factory_migrated.py: add ≥1 new
test that DOES go through the ``app_factory()`` fixture (not a rewrite of
existing memory integration tests, which CONTEXT D-05 explicitly preserves).

Tests:
  1. test_save_facts_5_via_factory_real_pg_round_trip — end-to-end save_facts
     against live PostgreSQL, asserts 5 rows landed + SaveFactsResult shape.
  2. test_save_facts_with_near_duplicate_emits_audit_and_still_inserts_real_pg
     — pins C3 D-09 audit-mode-only at the integration layer: near-duplicate
     in the bulk SELECT triggers MEMORY_NEAR_DUPLICATE_SKIPPED audit row AND
     INSERT still runs (BOTH rows persisted).

Skip-gated on PG_AVAILABLE (Pattern E). If the live embedder model isn't
available, falls back to the monkeypatched embedder via the existing
``embedder_or_mock`` fixture (tests/conftest.py:132-174).
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")
os.environ.setdefault("APP_AUDIT_DB_ENABLED", "true")

from collections.abc import Callable
from typing import Any

import pytest

from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not PG_AVAILABLE, reason="needs live PostgreSQL"),
    pytest.mark.pgvector,
]


# -----------------------------------------------------------------------------
# Test 1 — happy path: 5 facts → 5 rows via app_factory + live PG
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_facts_5_via_factory_real_pg_round_trip(
    pg_pool: Any,
    app_factory: Callable[..., Any],
    clean_long_term_facts: None,  # noqa: ARG001 — truncates LTF before test
    embedder_or_mock: Any,  # noqa: ARG001 — provides real or mock embedder
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Memory-side SC-1: end-to-end save_facts via the factory and live PG.

    1. Build isolated app via app_factory() — resets memory singleton.
    2. Acquire memory service through canonical accessor.
    3. Pin _long._pool to the shared session pool (the LongTermMemory built
       by get_memory_service() owns its own pool; pinning avoids spinning a
       second pool for the integration test).
    4. Ensure long_term_facts schema exists (forces _create_tables on the
       pinned pool — idempotent).
    5. Call save_facts([5 distinct facts]).
    6. SELECT COUNT(*) — assert 5 rows landed for the test user/tenant.
    7. Assert SaveFactsResult shape.
    """
    # 1. Build an isolated app — resets memory singleton (and 33 others).
    app = app_factory()
    assert app is not None

    # 2. Acquire memory service.
    from services.memory.memory_service import (
        SaveFactsResult,
        get_memory_service,
    )
    from utils.models import ExtractedFact

    mem = get_memory_service()
    ltm = mem._long

    # 3. Pin LongTermMemory's pool to the shared session pool.
    ltm._pool = pg_pool
    # 4. Ensure schema exists on the pinned pool (idempotent CREATE IF NOT EXISTS).
    await ltm._create_tables()

    # 5. Build 5 distinct facts and persist them.
    facts = [
        ExtractedFact(
            fact=f"u_e2e_test27 fact {i} unique seed",
            category="recurring_topics",
            importance=0.5,
        )
        for i in range(5)
    ]
    result = await ltm.save_facts(
        facts,
        user_id="u_e2e_test27",
        tenant_id="t_e2e_test27",
        source_doc="phase27-test",
    )

    # 6. Verify row count via direct SELECT.
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COUNT(*) AS n FROM long_term_facts
               WHERE user_id = $1 AND tenant_id = $2""",
            "u_e2e_test27", "t_e2e_test27",
        )
    assert row["n"] == 5, f"Expected 5 rows in long_term_facts, got {row['n']}"

    # 7. SaveFactsResult shape.
    # Note: skipped_near_duplicates may be > 0 if the embedder produces very
    # similar vectors for the test strings. We assert the saved_count (the
    # invariant we control) and that the result type matches.
    assert isinstance(result, SaveFactsResult)
    assert result.saved_count == 5, (
        f"saved_count should be N=5 regardless of near-dup count "
        f"(D-09 audit-mode-only). Got {result.saved_count}."
    )
    assert result.skipped_embed_failures == 0


# -----------------------------------------------------------------------------
# Test 2 — SK-01 at integration layer: near-dup audit + silent-skip
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_save_facts_with_near_duplicate_emits_audit_and_skips_silently_real_pg(
    pg_pool: Any,
    app_factory: Callable[..., Any],
    clean_long_term_facts: None,  # noqa: ARG001 — truncates LTF before test
    embedder_or_mock: Any,  # noqa: ARG001 — provides real or mock embedder
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SK-01 silent-skip + audit at the integration layer.

    Insert one fact, then call save_facts with the SAME text. The embedder
    produces identical vectors (mock returns the same 1024-dim vector; real
    embedder produces cosine distance ~0 for identical strings) → dist 0 <
    0.05 threshold → MEMORY_NEAR_DUPLICATE_SKIPPED audit row emitted AND the
    duplicate is filtered out of rows_to_insert before executemany (SK-01,
    Plan 29-01). Final long_term_facts count must equal 1 (seed only;
    duplicate skipped).

    Requires audit_db_enabled=True so the audit_log row actually lands in PG.
    """
    # Enable DB-bound audit writes for this test.
    monkeypatch.setattr(
        "services.audit.audit_service.settings.audit_db_enabled",
        True,
        raising=False,
    )
    # Reset audit singleton so the audit_db_enabled flip takes effect.
    import services.audit.audit_service as audit_mod
    monkeypatch.setattr(audit_mod, "_audit_service", None, raising=False)

    # Drop audit_log so the Phase 26 TD-01 auto-create path fires fresh.
    async with pg_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS audit_log CASCADE;")

    # Build isolated app — resets memory + audit singletons.
    app = app_factory()
    assert app is not None

    from services.memory.memory_service import get_memory_service
    from utils.models import ExtractedFact

    mem = get_memory_service()
    ltm = mem._long
    ltm._pool = pg_pool
    await ltm._create_tables()

    # Step 1 — insert the seed fact (no near-dup possible on empty table).
    seed = ExtractedFact(
        fact="user prefers React over Vue",
        category="stable_preferences",
        importance=0.8,
    )
    await ltm.save_facts(
        [seed],
        user_id="u_d9_test", tenant_id="t_d9_test",
    )

    # Step 2 — re-insert the SAME fact text. Embedder produces an identical
    # vector → distance 0 < 0.05 threshold → near-dup hit on index 0.
    duplicate = ExtractedFact(
        fact="user prefers React over Vue",
        category="stable_preferences",
        importance=0.8,
    )
    result = await ltm.save_facts(
        [duplicate],
        user_id="u_d9_test", tenant_id="t_d9_test",
    )

    # Force the audit buffer to land in PG.
    svc = audit_mod.get_audit_service()
    await svc.flush()

    # Assert: long_term_facts has 1 row (SK-01 — duplicate skipped silently).
    async with pg_pool.acquire() as conn:
        ltf_count = await conn.fetchval(
            """SELECT COUNT(*) FROM long_term_facts
               WHERE user_id = $1 AND tenant_id = $2""",
            "u_d9_test", "t_d9_test",
        )
    assert ltf_count == 1, (
        f"SK-01 silent-skip at integration layer: duplicate must be filtered "
        f"out of rows_to_insert. Got {ltf_count} rows."
    )

    # Assert: SaveFactsResult flagged the duplicate (saved_count==0 for the
    # second call — only the duplicate was submitted and it was skipped).
    assert result.saved_count == 0, (
        f"SK-01: second save_facts inserted 0 rows (only the duplicate was "
        f"submitted, and it was filtered). Got {result.saved_count}."
    )
    assert result.skipped_near_duplicates == 1, (
        f"SK-01 metric: expected 1 near-dup flag, got {result.skipped_near_duplicates}"
    )

    # Assert: audit_log has at least 1 MEMORY_NEAR_DUPLICATE_SKIPPED row.
    async with pg_pool.acquire() as conn:
        audit_rows = await conn.fetch(
            """SELECT user_id, action FROM audit_log
               WHERE user_id = $1 AND tenant_id = $2
                 AND action = $3""",
            "u_d9_test", "t_d9_test", "MEMORY_NEAR_DUPLICATE_SKIPPED",
        )
    assert len(audit_rows) >= 1, (
        f"SK-01: expected ≥1 MEMORY_NEAR_DUPLICATE_SKIPPED row "
        f"for u_d9_test/t_d9_test, got {len(audit_rows)}."
    )
