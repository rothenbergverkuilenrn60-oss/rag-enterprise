from __future__ import annotations

import sys
import pytest
import asyncpg

# Import availability flag from conftest
from tests.conftest import PG_AVAILABLE

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE,
    reason="PostgreSQL + pgvector not available — skipping RLS integration tests"
)


# ── PG-03: RLS cross-tenant isolation ────────────────────────────────────────

async def test_cross_tenant_isolation(pg_pool: asyncpg.Pool):
    """Documents ingested for tenant-a must NOT be visible when querying as tenant-b.

    This test exercises the full RLS enforcement path:
    1. Insert a vector row with tenant_id='tenant-a' in metadata
    2. Set app.current_tenant='tenant-b' on the connection
    3. Query the table directly — expect 0 rows returned (RLS blocks)
    """
    from services.vectorizer.vector_store import PgVectorStore
    import services.vectorizer.vector_store as vs_module
    vs_module._store_instance = None
    store = PgVectorStore()
    await store.create_collection()

    table = store._table
    dim = store._dim

    # Insert a test row as tenant-a (bypass RLS by inserting as superuser or
    # using direct pool access which has FORCE RLS via policy)
    async with pg_pool.acquire() as conn:
        await conn.execute(
            f"""
            INSERT INTO {table}(chunk_id, doc_id, content, metadata, embedding, tenant_id)
            VALUES ($1, $2, $3, $4::jsonb, $5::vector, $6)
            ON CONFLICT(chunk_id) DO NOTHING
            """,
            "rls-test-chunk-001",
            "rls-test-doc",
            "Sensitive content for tenant-a",
            '{"tenant_id": "tenant-a"}',
            [0.1] * dim,
            "tenant-a",
        )

    # Query as tenant-b: RLS must block access
    async with pg_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, true)", "tenant-b"
            )
            rows = await conn.fetch(
                f"SELECT chunk_id FROM {table} WHERE chunk_id = $1",
                "rls-test-chunk-001",
            )
    assert len(rows) == 0, (
        f"RLS FAILED: tenant-b retrieved {len(rows)} row(s) belonging to tenant-a"
    )


async def test_same_tenant_can_read_own_data(pg_pool: asyncpg.Pool):
    """Documents ingested for tenant-a ARE visible when querying as tenant-a."""
    from services.vectorizer.vector_store import PgVectorStore
    import services.vectorizer.vector_store as vs_module
    vs_module._store_instance = None
    store = PgVectorStore()

    table = store._table

    async with pg_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_tenant', $1, true)", "tenant-a"
            )
            rows = await conn.fetch(
                f"SELECT chunk_id FROM {table} WHERE chunk_id = $1",
                "rls-test-chunk-001",
            )
    assert len(rows) == 1, (
        f"Expected tenant-a to see own data, got {len(rows)} rows"
    )


# ── PG-01: No Qdrant import at runtime ───────────────────────────────────────

def test_qdrant_client_not_imported_at_runtime(monkeypatch):
    """When vector_store='pgvector', qdrant_client must not be imported (PG-01)."""
    import services.vectorizer.vector_store as vs_module
    vs_module._store_instance = None
    monkeypatch.setattr("config.settings.settings.vector_store", "pgvector")
    # Remove qdrant_client from sys.modules if already loaded
    qdrant_mods = [k for k in sys.modules if "qdrant" in k]
    for k in qdrant_mods:
        sys.modules.pop(k, None)

    _ = vs_module.get_vector_store()
    qdrant_imported = any("qdrant_client" in k for k in sys.modules)
    assert not qdrant_imported, (
        "qdrant_client was imported at runtime when using pgvector backend"
    )
    vs_module._store_instance = None
