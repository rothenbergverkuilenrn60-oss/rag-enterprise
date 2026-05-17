from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import asyncio

import asyncpg
import pytest

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


@pytest.fixture
async def pg_pool():
    """Function-scoped asyncpg pool with pgvector codec registered on every connection.

    Previously session-scoped; flipped to function-scope to match pytest-asyncio 1.x
    default function-scoped test event loop. Session-scoped pool + function-scoped
    test loop produced `InterfaceError: cannot perform operation: another operation
    is in progress` on every PG-gated integration test.

    Per-test pool overhead is ~50ms on a local pgvector instance — acceptable trade
    for correctness across all PG-gated integration suites.
    """
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


# ──────────────────────────────────────────────────────────────────────────────
# Phase 23 / Plan 23-06 — fixtures for the new extractor + LTF integration tests.
# REUSES the existing ``pg_pool`` session fixture above for the asyncpg pool;
# adds extractor-LLM mock + embedder mock + per-test fact table cleanup that
# the new integration tests under tests/integration/test_long_term_facts_schema.py
# + test_extractor_e2e.py + test_swarm_pipeline_extractor_e2e.py rely on.
#
# All fixtures defer the actual DB connect to the underlying ``pg_pool`` so they
# inherit its skip-if-PG-unavailable behavior — keeping CI green on hosts
# without PostgreSQL.
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(name="pgvector_pool")
async def pgvector_pool_fixture(pg_pool):
    """Alias to ``pg_pool`` under the name the Plan 23-06 tests reference.

    Phase 1 named the fixture ``pg_pool``; Plan 23-06 PLAN.md prescribes
    ``pgvector_pool``. Both names point to the same session-scoped asyncpg
    pool with pgvector codec registered (see ``pg_pool`` above).
    """
    yield pg_pool


@pytest.fixture
def extractor_llm_mock(monkeypatch):
    """Function-scoped: patch ``get_llm_client`` at the extractor's consumer
    path + reset the module-level ``_extractor`` singleton so every test sees
    a fresh client.

    Returns the MagicMock so tests can chain:
        extractor_llm_mock.call_agentic_turn.return_value = AgenticTurn(...)
    """
    from unittest.mock import AsyncMock, MagicMock

    import services.agent.extractor as extractor_mod

    mock_client = MagicMock()
    mock_client.call_agentic_turn = AsyncMock()
    monkeypatch.setattr(
        "services.agent.extractor.get_llm_client", lambda: mock_client
    )
    # Reset cached extractor singleton — otherwise a prior test's mock leaks in.
    monkeypatch.setattr(extractor_mod, "_extractor", None, raising=False)
    # Pin extractor_enabled = True so kill-switch never short-circuits.
    monkeypatch.setattr(
        extractor_mod.settings, "extractor_enabled", True, raising=False
    )
    return mock_client


@pytest.fixture
def embedder_or_mock(monkeypatch):
    """Function-scoped: if ``MODEL_DIR`` (or ``APP_MODEL_DIR``) points to a
    real bge-m3 model directory, return the real ``HuggingFaceEmbedder``;
    otherwise patch ``services.vectorizer.embedder.get_embedder`` to return
    a MagicMock yielding a deterministic 1024-dim vector — avoids requiring
    a 2GB model download for CI.

    The mock is monkey-patched at BOTH the embedder module and at the consumer
    path inside ``services.memory.memory_service`` (which lazy-imports it
    inside ``save_fact``). The lazy import means ``monkeypatch.setattr`` on
    the ``embedder`` module is the correct injection point.
    """
    import os as _os
    from unittest.mock import AsyncMock, MagicMock

    model_dir = _os.environ.get("MODEL_DIR") or _os.environ.get("APP_MODEL_DIR")
    # Plan 26-02 / TD-07: delegate to the multi-layout resolver so the fixture
    # also honors `BAAI/bge-m3` (HF flat) + `models--BAAI--bge-m3/snapshots/*`
    # (HF hub cache) layouts, not just legacy `embedding_models/bge-m3`.
    real_bge = False
    if model_dir:
        from config.settings import resolve_embedding_model_path
        real_bge = resolve_embedding_model_path("bge-m3").exists()

    if real_bge:
        # Real embedder path — return the singleton factory's result.
        import services.vectorizer.embedder as emb_mod

        # Force factory reset so we instantiate fresh under test env.
        emb_mod._embedder_instance = None
        return emb_mod.get_embedder()

    mock_emb = MagicMock()
    mock_emb.embed_one = AsyncMock(return_value=[0.1] * 1024)
    mock_emb.embed_batch = AsyncMock(return_value=[[0.1] * 1024])
    monkeypatch.setattr(
        "services.vectorizer.embedder.get_embedder", lambda: mock_emb
    )
    # Reset the module-level singleton so the patch above wins on next call.
    import services.vectorizer.embedder as emb_mod
    monkeypatch.setattr(emb_mod, "_embedder_instance", None, raising=False)
    return mock_emb


@pytest.fixture
async def clean_long_term_facts(pgvector_pool):
    """Function-scoped: truncate ``long_term_facts`` before each test so the
    user_id/tenant_id row counts assertions are deterministic.

    Runs BEFORE the test body. Does not truncate after — leaving rows visible
    if a failing test needs post-mortem inspection.

    Depends on ``pgvector_pool`` (which skips when PG unavailable), so this
    fixture inherits the same skip behavior.
    """
    async with pgvector_pool.acquire() as conn:
        # Best-effort: table may not exist yet on a first-call test that
        # itself invokes _create_tables. Swallow the missing-table error.
        try:
            await conn.execute("DELETE FROM long_term_facts;")
        except Exception:  # noqa: BLE001 — table may not exist on first call
            pass
    yield
