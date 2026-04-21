from __future__ import annotations

import asyncio
import pytest
import asyncpg

PG_DSN = "postgresql://rag:rag@localhost:5432/ragdb"


def _pg_available() -> bool:
    """Check if PostgreSQL is reachable. Used at collection time."""
    try:
        async def _check() -> bool:
            try:
                conn = await asyncio.wait_for(
                    asyncpg.connect(PG_DSN), timeout=2.0
                )
                await conn.close()
                return True
            except Exception:
                return False
        return asyncio.run(_check())
    except Exception:
        return False


PG_AVAILABLE = _pg_available()


@pytest.fixture(scope="session")
async def pg_pool():
    """Session-scoped asyncpg pool with pgvector codec registered on every connection."""
    if not PG_AVAILABLE:
        pytest.skip("PostgreSQL + pgvector not available")
    from pgvector.asyncpg import register_vector

    async def _init_conn(conn: asyncpg.Connection) -> None:
        await register_vector(conn)

    pool = await asyncpg.create_pool(
        PG_DSN,
        min_size=1,
        max_size=5,
        init=_init_conn,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def pg_store():
    """Function-scoped PgVectorStore with reset singleton."""
    import services.vectorizer.vector_store as vs_module
    vs_module._store_instance = None
    from services.vectorizer.vector_store import PgVectorStore
    store = PgVectorStore()
    yield store
    vs_module._store_instance = None


@pytest.fixture(scope="module")
def pg_available() -> bool:
    """Module-scoped availability flag."""
    return PG_AVAILABLE
