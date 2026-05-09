"""tests/unit/test_summary_indexer.py — Phase 15 backfill.

Covers SummaryIndexer: per-level helpers (_summarize_document /
_summarize_sections / _summarize_chunk_groups), search_summaries
happy + error paths, _upsert_summaries empty + populated paths,
and singleton accessor.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from unittest.mock import AsyncMock, MagicMock

import asyncpg
import openai
import pytest


def _make_chunk(chunk_id: str, *, section: str = "", level: str = "child", content: str = "x"):
    chunk = MagicMock()
    chunk.chunk_id = chunk_id
    chunk.content = content
    chunk.metadata = MagicMock()
    chunk.metadata.section = section
    chunk.metadata.chunk_level = level
    return chunk


@pytest.fixture(autouse=True)
def reset_singleton(monkeypatch):
    import services.knowledge.summary_indexer as mod
    yield
    monkeypatch.setattr(mod, "_summary_indexer", None, raising=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_document_returns_entry():
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    llm = MagicMock()
    llm.chat = AsyncMock(return_value="doc summary")
    chunks = [_make_chunk(f"c{i}", content=f"text {i}") for i in range(3)]
    entry = await indexer._summarize_document(chunks, "doc1", "Title", llm)
    assert entry is not None
    assert entry.level == "document"
    assert entry.summary_text == "doc summary"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_document_returns_none_for_empty_chunks():
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    out = await indexer._summarize_document([], "doc1", "Title", MagicMock())
    assert out is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_document_propagates_api_error_after_retries():
    """Error path: openai.APIError exhausts retries → tenacity RetryError surfaces."""
    from tenacity import RetryError

    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=openai.APIError("rate limit", request=None, body={}))
    chunks = [_make_chunk("c1")]
    with pytest.raises(RetryError):
        await indexer._summarize_document(chunks, "doc1", "T", llm)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_sections_skips_when_single_section():
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    chunks = [_make_chunk(f"c{i}", section="default") for i in range(3)]
    out = await indexer._summarize_sections(chunks, "doc1", MagicMock())
    assert out == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_sections_groups_by_section():
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=["sumA", "sumB"])
    chunks = (
        [_make_chunk(f"a{i}", section="A") for i in range(2)]
        + [_make_chunk(f"b{i}", section="B") for i in range(2)]
    )
    out = await indexer._summarize_sections(chunks, "doc1", llm)
    assert len(out) == 2
    assert all(e.level == "section" for e in out)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_sections_swallows_individual_failures():
    """Error path: gather returns exceptions → skipped, others retained."""
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    llm = MagicMock()

    async def chat(*_a, **_kw):
        raise RuntimeError("boom")

    llm.chat = chat
    chunks = (
        [_make_chunk("a", section="A")]
        + [_make_chunk("b", section="B")]
    )
    out = await indexer._summarize_sections(chunks, "doc1", llm)
    assert out == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_chunk_groups_skipped_when_below_threshold():
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    chunks = [_make_chunk(f"c{i}") for i in range(3)]  # < CHUNK_GROUP_SIZE (5)
    out = await indexer._summarize_chunk_groups(chunks, "doc1", MagicMock())
    assert out == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_summarize_chunk_groups_emits_groups():
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    llm = MagicMock()
    llm.chat = AsyncMock(return_value="group summary")
    chunks = [_make_chunk(f"c{i}") for i in range(7)]
    out = await indexer._summarize_chunk_groups(chunks, "doc1", llm)
    assert len(out) >= 1
    assert all(e.level == "chunk_group" for e in out)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_summaries_returns_chunk_ids():
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    embedder = MagicMock()
    embedder.embed_one = AsyncMock(return_value=[0.1, 0.2])
    vstore = MagicMock()
    result_obj = MagicMock()
    result_obj.metadata = {"tags": ["summary", "document", "chunk_ids:c1,c2,c3"]}
    vstore.search = AsyncMock(return_value=[result_obj])
    out = await indexer.search_summaries("query", embedder, vstore)
    assert out == ["c1", "c2", "c3"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_summaries_handles_postgres_error():
    """Error path: PostgresError → returns []."""
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    embedder = MagicMock()
    embedder.embed_one = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
    vstore = MagicMock()
    out = await indexer.search_summaries("q", embedder, vstore)
    assert out == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_summaries_dedupes_chunk_ids():
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    embedder = MagicMock()
    embedder.embed_one = AsyncMock(return_value=[0.0])
    vstore = MagicMock()
    r1 = MagicMock()
    r1.metadata = {"tags": ["chunk_ids:c1,c2"]}
    r2 = MagicMock()
    r2.metadata = {"tags": ["chunk_ids:c2,c3"]}
    vstore.search = AsyncMock(return_value=[r1, r2])
    out = await indexer.search_summaries("q", embedder, vstore)
    assert out == ["c1", "c2", "c3"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_summaries_short_circuits_on_empty():
    from services.knowledge.summary_indexer import SummaryIndexer
    indexer = SummaryIndexer()
    embedder = MagicMock()
    vstore = MagicMock()
    vstore.upsert = AsyncMock()
    await indexer._upsert_summaries([], embedder, vstore)
    vstore.upsert.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_summaries_handles_postgres_error():
    """Error path: vector_store.upsert raises → swallowed."""
    from services.knowledge.summary_indexer import SummaryEntry, SummaryIndexer
    indexer = SummaryIndexer()
    embedder = MagicMock()
    embedder.embed_batch = AsyncMock(return_value=[[0.1]])
    vstore = MagicMock()
    vstore.create_collection = AsyncMock()
    vstore.upsert = AsyncMock(side_effect=asyncpg.PostgresError("boom"))
    entries = [SummaryEntry(
        summary_id="sid", doc_id="doc1", level="document",
        summary_text="hello", chunk_ids=["c1"],
    )]
    await indexer._upsert_summaries(entries, embedder, vstore)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upsert_summaries_writes_pseudo_chunks():
    from services.knowledge.summary_indexer import SummaryEntry, SummaryIndexer
    indexer = SummaryIndexer()
    embedder = MagicMock()
    embedder.embed_batch = AsyncMock(return_value=[[0.1, 0.2]])
    vstore = MagicMock()
    vstore.create_collection = AsyncMock()
    vstore.upsert = AsyncMock()
    entries = [SummaryEntry(
        summary_id="s1", doc_id="d1", level="document",
        summary_text="text", chunk_ids=["c1", "c2"],
    )]
    await indexer._upsert_summaries(entries, embedder, vstore)
    vstore.upsert.assert_awaited_once()


@pytest.mark.unit
def test_get_summary_indexer_singleton():
    from services.knowledge.summary_indexer import get_summary_indexer
    a = get_summary_indexer()
    b = get_summary_indexer()
    assert a is b
