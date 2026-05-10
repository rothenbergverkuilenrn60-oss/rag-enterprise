"""tests/unit/test_vector_store_filter_where.py — Phase 15 backfill.

Existing tests/unit/test_pgvector_store.py is gated on a live Postgres.
This file covers the pure-function `_build_filter_where` helper and a
constructor smoke test for PgVectorStore (no pool created until
`_get_pool()` is awaited).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest


@pytest.mark.unit
def test_build_filter_where_empty_returns_no_clause():
    from services.vectorizer.vector_store import _build_filter_where
    sql, params = _build_filter_where({})
    assert sql == ""
    assert params == []


@pytest.mark.unit
def test_build_filter_where_int_value_uses_jsonb_cast():
    from services.vectorizer.vector_store import _build_filter_where
    sql, params = _build_filter_where({"page_number": 63})
    assert "::int" in sql
    assert "$3" in sql
    assert params == [63]


@pytest.mark.unit
def test_build_filter_where_string_value_no_cast():
    from services.vectorizer.vector_store import _build_filter_where
    sql, params = _build_filter_where({"section_id": "3.10"})
    assert "::int" not in sql
    assert "$3" in sql
    assert params == ["3.10"]


@pytest.mark.unit
def test_build_filter_where_skips_unknown_value_types():
    """Defense-in-depth: dict values of unsupported types must be dropped."""
    from services.vectorizer.vector_store import _build_filter_where
    sql, params = _build_filter_where({"flag": True, "lst": [1, 2]})
    # Both bool (subclass of int but excluded explicitly) and list are skipped.
    assert sql == ""
    assert params == []


@pytest.mark.unit
def test_build_filter_where_combines_multiple_clauses_with_and():
    from services.vectorizer.vector_store import _build_filter_where
    sql, params = _build_filter_where({"page_number": 1, "section_id": "x"})
    assert " AND " in sql
    assert params == [1, "x"]


@pytest.mark.unit
def test_build_filter_where_respects_start_param():
    from services.vectorizer.vector_store import _build_filter_where
    sql, _params = _build_filter_where({"page_number": 7}, start_param=10)
    assert "$10" in sql


@pytest.mark.unit
def test_pgvector_store_constructor_does_not_open_pool():
    """Constructor must be lazy: pool stays None until _get_pool()."""
    from services.vectorizer.vector_store import PgVectorStore
    store = PgVectorStore()
    assert store._pool is None


@pytest.mark.unit
def test_vector_search_result_dataclass_roundtrip():
    from services.vectorizer.vector_store import VectorSearchResult
    r = VectorSearchResult(
        chunk_id="c1", doc_id="d1", content="text",
        metadata={"k": "v"}, score=0.9,
    )
    assert r.chunk_id == "c1"
    assert r.metadata["k"] == "v"
    assert r.score == 0.9
