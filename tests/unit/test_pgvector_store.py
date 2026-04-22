from __future__ import annotations

import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from utils.models import DocumentChunk, ChunkMetadata, DocType


# ── PG-05: ABC interface ──────────────────────────────────────────────────────

def test_abc_interface():
    """BaseVectorStore ABC must declare upsert_parent_chunks and fetch_parent_chunks
    as abstract methods (PG-05)."""
    from services.vectorizer.vector_store import BaseVectorStore
    abstract_methods = {
        name for name, val in inspect.getmembers(BaseVectorStore)
        if getattr(val, "__isabstractmethod__", False)
    }
    assert "upsert_parent_chunks" in abstract_methods, (
        "BaseVectorStore missing abstract method: upsert_parent_chunks"
    )
    assert "fetch_parent_chunks" in abstract_methods, (
        "BaseVectorStore missing abstract method: fetch_parent_chunks"
    )


# ── PG-01: Factory ───────────────────────────────────────────────────────────

def test_factory_returns_pgvector(monkeypatch):
    """get_vector_store() returns PgVectorStore when settings.vector_store='pgvector' (PG-01)."""
    import services.vectorizer.vector_store as vs_module
    from services.vectorizer.vector_store import PgVectorStore
    vs_module._store_instance = None
    monkeypatch.setattr("config.settings.vector_store", "pgvector")
    store = vs_module.get_vector_store()
    assert isinstance(store, PgVectorStore), (
        f"Expected PgVectorStore, got {type(store).__name__}"
    )
    vs_module._store_instance = None


# ── PG-02: HNSW index ────────────────────────────────────────────────────────

def test_hnsw_index_ddl_pattern():
    """create_collection source must contain HNSW DDL and must NOT contain ivfflat (PG-02)."""
    from services.vectorizer.vector_store import PgVectorStore
    src = inspect.getsource(PgVectorStore.create_collection)
    assert "hnsw" in src.lower(), "create_collection must create HNSW index"
    assert "ivfflat" not in src.lower(), "create_collection must NOT use IVFFlat"
    assert "work_mem" in src, "create_collection must SET work_mem = '256MB'"


def test_hnsw_rls_ddl_pattern():
    """create_collection source must contain RLS DDL (PG-03 prerequisite)."""
    from services.vectorizer.vector_store import PgVectorStore
    src = inspect.getsource(PgVectorStore.create_collection)
    assert "ROW LEVEL SECURITY" in src, "create_collection must enable RLS"
    assert "tenant_isolation" in src, "create_collection must create tenant_isolation policy"
    assert "app.current_tenant" in src, "RLS policy must reference app.current_tenant"


# ── PG-04: Parent chunk round-trip (method existence check) ──────────────────

@pytest.fixture
def sample_chunks() -> list[DocumentChunk]:
    meta = ChunkMetadata(
        source="test.pdf",
        doc_type=DocType.PDF,
        chunk_index=0,
        total_chunks=2,
        title="Test Doc",
    )
    return [
        DocumentChunk(
            chunk_id=f"parent-{i}",
            doc_id="doc-001",
            content=f"Parent content {i}",
            content_with_header=f"[Test Doc] Parent content {i}",
            metadata=meta,
            embedding=None,
        )
        for i in range(2)
    ]


async def test_parent_chunk_roundtrip_methods_exist(sample_chunks):
    """PgVectorStore must have upsert_parent_chunks and fetch_parent_chunks (PG-04)."""
    from services.vectorizer.vector_store import PgVectorStore
    store = PgVectorStore()
    assert hasattr(store, "upsert_parent_chunks"), "PgVectorStore missing upsert_parent_chunks"
    assert hasattr(store, "fetch_parent_chunks"), "PgVectorStore missing fetch_parent_chunks"
    assert callable(store.upsert_parent_chunks)
    assert callable(store.fetch_parent_chunks)


async def test_parent_chunk_fetch_empty_returns_empty():
    """fetch_parent_chunks([]) must return {} without hitting database."""
    from services.vectorizer.vector_store import PgVectorStore
    store = PgVectorStore()
    # Must return empty dict for empty input without needing a DB connection
    result = await store.fetch_parent_chunks([], "test_parent")
    assert result == {}


# ── Retry decorator presence ──────────────────────────────────────────────────

def test_retry_decorator_on_upsert():
    """PgVectorStore.upsert must have tenacity @retry applied."""
    from services.vectorizer.vector_store import PgVectorStore
    upsert_fn = PgVectorStore.upsert
    # tenacity wraps the function; __wrapped__ attribute present when decorated
    assert hasattr(upsert_fn, "__wrapped__") or hasattr(upsert_fn, "retry"), (
        "PgVectorStore.upsert missing @retry decorator"
    )


def test_retry_decorator_on_search():
    """PgVectorStore.search must have tenacity @retry applied."""
    from services.vectorizer.vector_store import PgVectorStore
    search_fn = PgVectorStore.search
    assert hasattr(search_fn, "__wrapped__") or hasattr(search_fn, "retry"), (
        "PgVectorStore.search missing @retry decorator"
    )
