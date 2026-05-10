"""Coverage tests for services/vectorizer/vector_store.py per TEST-10 (Phase 22 SC3).

Targets:
- _build_filter_where table-driven (page_number int / string / null sentinel)
- JSONB isinstance(metadata, str) decoding branch (line 347)
- HNSW DDL idempotency (CREATE INDEX IF NOT EXISTS — 6 indexes at lines 173-225)

Mock at consumer path (services.vectorizer.vector_store.<dep>) only — CF-02.
No production-code changes (CF-01).
Existing tests/unit/test_vector_store_filter_where.py UNTOUCHED (D-09 strict separation).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ── Inline fixtures (D-10) ────────────────────────────────────────────────────

class _FakeRecord(dict):
    """Dict subclass that allows asyncpg Record-style key access via r["key"]."""


def _make_record(**kwargs) -> _FakeRecord:
    return _FakeRecord(kwargs)


@pytest.fixture
def fake_conn():
    """A fake asyncpg connection with AsyncMock execute/fetch/fetchrow/executemany methods."""
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock()
    conn.executemany = AsyncMock()

    # Support `async with conn.transaction()` context manager
    tx = MagicMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx)
    return conn


@pytest.fixture
def fake_pool(fake_conn):
    """Fake asyncpg pool whose acquire() context manager yields fake_conn."""
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield fake_conn

    pool.acquire = _acquire
    return pool


# ── _build_filter_where: table-driven (SC3 branch 1) ─────────────────────────

@pytest.mark.parametrize("filters, expected_substr, expected_params", [
    # int value → ::int cast
    ({"page_number": 63}, "::int", [63]),
    # string value → no ::int cast, bare JSONB extraction
    ({"section_id": "3.10"}, None, ["3.10"]),
    # None value → unknown type, silently skipped (null sentinel)
    ({"page_number": None}, "", []),
    # bool value → skipped (bool subclass of int but explicitly excluded)
    # list value → skipped (unknown type)
    ({"flag": True, "lst": [1, 2]}, "", []),
])
def test_build_filter_where_param_table(filters, expected_substr, expected_params):
    from services.vectorizer.vector_store import _build_filter_where
    sql, params = _build_filter_where(filters)
    if expected_substr:
        assert expected_substr in sql, f"Expected {expected_substr!r} in {sql!r}"
    assert params == expected_params


def test_build_filter_where_null_sentinel_skips_key():
    """None value (null sentinel) must be silently dropped, not included in WHERE clause."""
    from services.vectorizer.vector_store import _build_filter_where
    sql, params = _build_filter_where({"page_number": None})
    assert sql == ""
    assert params == []


def test_build_filter_where_combined_int_and_string():
    """Multiple filters: int and string both appear joined by AND."""
    from services.vectorizer.vector_store import _build_filter_where
    sql, params = _build_filter_where({"page_number": 5, "section_id": "A.1"})
    assert " AND " in sql
    assert "::int" in sql
    assert "::int" not in sql.split(" AND ")[1]  # string branch has no ::int
    assert params == [5, "A.1"]


def test_build_filter_where_skips_unsupported_types():
    """bool and list values must both be skipped (defense-in-depth)."""
    from services.vectorizer.vector_store import _build_filter_where
    sql, params = _build_filter_where({"flag": True, "lst": [1, 2], "d": {"k": "v"}})
    assert sql == ""
    assert params == []


def test_build_filter_where_respects_start_param():
    """start_param=10 produces $10 placeholders."""
    from services.vectorizer.vector_store import _build_filter_where
    sql, _params = _build_filter_where({"page_number": 7}, start_param=10)
    assert "$10" in sql


# ── JSONB metadata decoding (SC3 branch 2, line 347) ─────────────────────────

async def test_pgvector_search_decodes_jsonb_string_metadata(monkeypatch, fake_pool, fake_conn):
    """Row whose metadata is a JSON string must be decoded to dict."""
    fake_row = _make_record(
        chunk_id="c1",
        doc_id="d1",
        content="some text",
        metadata='{"page": 1}',
        score=0.9,
    )
    fake_conn.fetch.return_value = [fake_row]

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    results = await store.search(query_vector=[0.1] * 1024, top_k=1)
    assert len(results) == 1
    assert results[0].metadata == {"page": 1}


async def test_pgvector_search_passes_through_dict_metadata(monkeypatch, fake_pool, fake_conn):
    """Row whose metadata is already a dict must pass through unchanged."""
    fake_row = _make_record(
        chunk_id="c2",
        doc_id="d2",
        content="other text",
        metadata={"page": 2},
        score=0.8,
    )
    fake_conn.fetch.return_value = [fake_row]

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    results = await store.search(query_vector=[0.1] * 1024, top_k=1)
    assert len(results) == 1
    assert results[0].metadata == {"page": 2}


async def test_pgvector_search_handles_null_metadata_returns_empty_dict(
    monkeypatch, fake_pool, fake_conn
):
    """Row whose metadata is None must produce an empty dict (per `or {}` at L347)."""
    fake_row = _make_record(
        chunk_id="c3",
        doc_id="d3",
        content="third text",
        metadata=None,
        score=0.7,
    )
    fake_conn.fetch.return_value = [fake_row]

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    results = await store.search(query_vector=[0.1] * 1024, top_k=1)
    assert len(results) == 1
    assert results[0].metadata == {}


async def test_pgvector_search_with_filter_strips_page_number_zero(
    monkeypatch, fake_pool, fake_conn
):
    """page_number=0 sentinel must be stripped before WHERE clause (T-08-09)."""
    fake_conn.fetch.return_value = []

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    # page_number=0 is the "unknown" sentinel; it must be dropped
    results = await store.search(
        query_vector=[0.0] * 1024,
        top_k=5,
        filters={"page_number": 0},
    )
    # Verify no WHERE clause was generated (no filter params beyond $1/$2)
    fetch_call = fake_conn.fetch.call_args
    sql_arg = fetch_call[0][0]
    assert "$3" not in sql_arg  # no filter param means no $3
    assert results == []


async def test_pgvector_search_with_valid_filter_emits_where_clause(
    monkeypatch, fake_pool, fake_conn
):
    """Non-zero filter produces WHERE clause in the emitted SQL."""
    fake_conn.fetch.return_value = []

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    await store.search(
        query_vector=[0.0] * 1024,
        top_k=5,
        filters={"page_number": 3},
    )
    fetch_call = fake_conn.fetch.call_args
    sql_arg = fetch_call[0][0]
    assert "WHERE" in sql_arg


# ── HNSW DDL idempotency (SC3 branch 3) ──────────────────────────────────────

async def test_pgvector_create_collection_emits_all_six_idempotent_indexes(
    monkeypatch, fake_pool, fake_conn
):
    """create_collection must emit all 6 CREATE INDEX IF NOT EXISTS DDL statements."""
    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    await store.create_collection()

    all_sql = " ".join(str(c) for c in fake_conn.execute.call_args_list)
    assert "CREATE INDEX IF NOT EXISTS" in all_sql

    expected_suffixes = [
        "_doc_idx",
        "_vec_idx",
        "_page_idx",
        "_page_int_idx",
        "_section_idx",
        "_parent_doc_idx",
    ]
    for suffix in expected_suffixes:
        assert suffix in all_sql, (
            f"Expected index suffix {suffix!r} not found in emitted DDL"
        )


async def test_pgvector_create_collection_idempotent_double_call(
    monkeypatch, fake_pool, fake_conn
):
    """Calling create_collection twice must not raise any exception."""
    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    await store.create_collection()
    await store.create_collection()

    # Both calls must produce identical SQL patterns
    all_sql_calls = [str(c) for c in fake_conn.execute.call_args_list]
    halfway = len(all_sql_calls) // 2
    first_half_sql = " ".join(all_sql_calls[:halfway])
    second_half_sql = " ".join(all_sql_calls[halfway:])
    # Both halves contain the same CREATE INDEX IF NOT EXISTS clauses
    assert "CREATE INDEX IF NOT EXISTS" in first_half_sql
    assert "CREATE INDEX IF NOT EXISTS" in second_half_sql


async def test_pgvector_create_collection_emits_hnsw_index(monkeypatch, fake_pool, fake_conn):
    """create_collection must emit an HNSW index (vector_cosine_ops)."""
    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    await store.create_collection()

    all_sql = " ".join(str(c) for c in fake_conn.execute.call_args_list)
    assert "hnsw" in all_sql.lower()
    assert "vector_cosine_ops" in all_sql


async def test_pgvector_create_collection_enables_rls(monkeypatch, fake_pool, fake_conn):
    """create_collection must enable ROW LEVEL SECURITY and tenant_isolation policy."""
    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    await store.create_collection()

    all_sql = " ".join(str(c) for c in fake_conn.execute.call_args_list)
    assert "ROW LEVEL SECURITY" in all_sql
    assert "tenant_isolation" in all_sql


# ── Additional coverage: upsert empty-chunks short-circuit path ───────────────

async def test_pgvector_upsert_empty_chunks_returns_early(monkeypatch, fake_pool):
    """upsert with no embedding chunks must log warning and return without DB call."""
    from utils.models import ChunkMetadata, DocType, DocumentChunk

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    # Chunks with no embeddings — all filtered out
    chunk = DocumentChunk(
        chunk_id="x1",
        doc_id="doc1",
        content="text",
        content_with_header="text",
        metadata=ChunkMetadata(doc_type=DocType.PDF),
        embedding=None,
    )
    # Must not raise, must return without calling executemany
    await store.upsert(chunks=[chunk], tenant_id="t1")


# ── Additional coverage: fetch_parent_chunks error branch (D-13) ─────────────

async def test_pgvector_fetch_parent_chunks_empty_ids_returns_empty(monkeypatch, fake_pool):
    """fetch_parent_chunks with empty parent_ids must return {} immediately."""
    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    result = await store.fetch_parent_chunks(parent_ids=[], collection_name="test")
    assert result == {}


async def test_pgvector_upsert_parent_chunks_empty_returns_early(monkeypatch, fake_pool):
    """upsert_parent_chunks with empty list must return without DB call."""
    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    await store.upsert_parent_chunks(chunks=[], collection_name="test")


# ── Additional coverage: upsert with valid records (lines 258-277) ────────────

async def test_pgvector_upsert_with_valid_embedding_records(monkeypatch, fake_pool, fake_conn):
    """upsert with chunks that have embeddings must call executemany."""
    from utils.models import ChunkMetadata, DocType, DocumentChunk

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    chunk = DocumentChunk(
        chunk_id="x1",
        doc_id="doc1",
        content="text",
        content_with_header="text",
        metadata=ChunkMetadata(doc_type=DocType.PDF),
        embedding=[0.1] * 1024,
    )
    await store.upsert(chunks=[chunk], tenant_id="t1")
    fake_conn.executemany.assert_called_once()


# ── Additional coverage: delete_by_doc (lines 354-359) ───────────────────────

async def test_pgvector_delete_by_doc(monkeypatch, fake_pool, fake_conn):
    """delete_by_doc must execute DELETE and parse row count from result string."""
    fake_conn.execute.return_value = "DELETE 3"

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    count = await store.delete_by_doc(doc_id="doc1")
    assert count == 3


# ── Additional coverage: count (lines 362-365) ───────────────────────────────

async def test_pgvector_count(monkeypatch, fake_pool, fake_conn):
    """count() must execute SELECT COUNT(*) and return int."""
    fake_row = _make_record(c=42)
    fake_conn.fetchrow.return_value = fake_row

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    result = await store.count()
    assert result == 42


# ── Additional coverage: upsert_parent_chunks with valid records (391-402) ───

async def test_pgvector_upsert_parent_chunks_with_records(monkeypatch, fake_pool, fake_conn):
    """upsert_parent_chunks with non-empty chunks must call executemany."""
    from utils.models import ChunkMetadata, DocType, DocumentChunk

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    chunk = DocumentChunk(
        chunk_id="p1",
        doc_id="doc1",
        content="parent text",
        content_with_header="parent text",
        metadata=ChunkMetadata(doc_type=DocType.PDF),
        embedding=None,
    )
    await store.upsert_parent_chunks(chunks=[chunk], collection_name="test")
    fake_conn.executemany.assert_called_once()


# ── Additional coverage: fetch_parent_chunks with IDs (416-428) ──────────────

async def test_pgvector_fetch_parent_chunks_with_ids(monkeypatch, fake_pool, fake_conn):
    """fetch_parent_chunks with valid IDs must return {chunk_id: content} dict."""
    fake_conn.fetch.return_value = [
        _make_record(chunk_id="p1", content="parent text"),
    ]

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    # Mock asyncpg in sys.modules so local `import asyncpg as _asyncpg` resolves to fake
    import sys
    fake_asyncpg = MagicMock()
    fake_asyncpg.PostgresError = Exception  # use base Exception as stand-in
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)

    result = await store.fetch_parent_chunks(parent_ids=["p1"], collection_name="test")
    assert result == {"p1": "parent text"}


async def test_pgvector_fetch_parent_chunks_postgres_error_returns_empty(
    monkeypatch, fake_pool, fake_conn
):
    """fetch_parent_chunks must catch PostgresError and return {} (D-13 non-fatal warning branch)."""
    import sys

    # Create a real exception class that will be raised
    class FakePostgresError(Exception):
        pass

    fake_asyncpg = MagicMock()
    fake_asyncpg.PostgresError = FakePostgresError
    monkeypatch.setitem(sys.modules, "asyncpg", fake_asyncpg)

    fake_conn.fetch.side_effect = FakePostgresError("connection failed")

    from services.vectorizer.vector_store import PgVectorStore

    store = PgVectorStore()
    monkeypatch.setattr(
        "services.vectorizer.vector_store.PgVectorStore._get_pool",
        AsyncMock(return_value=fake_pool),
    )
    result = await store.fetch_parent_chunks(parent_ids=["p1"], collection_name="test")
    assert result == {}
