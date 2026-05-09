"""tests/unit/test_mcp_server.py — Phase 15 backfill.

Covers _tool_search, _tool_ingest, _tool_stats success and error paths
in services/mcp_server.py. Stubs the optional `mcp` SDK so tests run
without the real dependency.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import json
import sys
import types as _types
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def stub_mcp(monkeypatch):
    """Provide an in-memory `mcp.types` module so import inside _tool_* succeeds."""
    fake = _types.ModuleType("mcp")
    fake_types = _types.ModuleType("mcp.types")

    class TextContent:
        def __init__(self, type: str, text: str) -> None:
            self.type = type
            self.text = text

    fake_types.TextContent = TextContent
    fake.types = fake_types
    monkeypatch.setitem(sys.modules, "mcp", fake)
    monkeypatch.setitem(sys.modules, "mcp.types", fake_types)
    yield


def _make_chunk(rank: int):
    chunk = MagicMock()
    chunk.doc_id = f"doc-{rank}"
    chunk.content = f"content {rank}"
    chunk.final_score = 0.9 - rank * 0.1
    chunk.metadata = MagicMock()
    chunk.metadata.title = f"Title {rank}"
    chunk.metadata.source = f"src-{rank}"
    chunk.metadata.page_number = rank
    return chunk


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_search_returns_ranked_results(monkeypatch):
    from services import mcp_server

    fake_retriever = MagicMock()
    fake_retriever.retrieve = AsyncMock(return_value=([_make_chunk(1), _make_chunk(2)], {"total_ms": 12}))
    monkeypatch.setattr(
        "services.retriever.retriever.get_retriever", lambda: fake_retriever, raising=False,
    )
    monkeypatch.setattr(
        "services.generator.llm_client.get_llm_client", lambda: MagicMock(), raising=False,
    )

    out = await mcp_server._tool_search({"query": "find x", "top_k": 5})
    assert len(out) == 1
    payload = json.loads(out[0].text)
    assert payload["total"] == 2
    assert payload["results"][0]["rank"] == 1
    assert payload["timings"]["total_ms"] == 12


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_search_handles_retriever_error(monkeypatch):
    """Error path: retriever raises ValueError → friendly error JSON."""
    from services import mcp_server

    fake_retriever = MagicMock()
    fake_retriever.retrieve = AsyncMock(side_effect=ValueError("bad query"))
    monkeypatch.setattr(
        "services.retriever.retriever.get_retriever", lambda: fake_retriever, raising=False,
    )
    monkeypatch.setattr(
        "services.generator.llm_client.get_llm_client", lambda: MagicMock(), raising=False,
    )

    out = await mcp_server._tool_search({"query": "boom"})
    payload = json.loads(out[0].text)
    assert "error" in payload


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_search_clamps_top_k_at_20(monkeypatch):
    from services import mcp_server

    captured: dict = {}

    async def fake_retrieve(*, query, top_k, filters, llm_client):
        captured["top_k"] = top_k
        return [], {}

    fake_retriever = MagicMock()
    fake_retriever.retrieve = fake_retrieve
    monkeypatch.setattr(
        "services.retriever.retriever.get_retriever", lambda: fake_retriever, raising=False,
    )
    monkeypatch.setattr(
        "services.generator.llm_client.get_llm_client", lambda: MagicMock(), raising=False,
    )

    await mcp_server._tool_search({"query": "x", "top_k": 999})
    assert captured["top_k"] == 20


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_ingest_missing_file_returns_error():
    from services import mcp_server
    out = await mcp_server._tool_ingest({"file_path": "/nonexistent/path/zzz.pdf"})
    payload = json.loads(out[0].text)
    assert "File not found" in payload["error"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_ingest_happy_path(tmp_path, monkeypatch):
    from services import mcp_server

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")

    fake_pipeline = MagicMock()
    fake_result = MagicMock()
    fake_result.success = True
    fake_result.doc_id = "doc-1"
    fake_result.total_chunks = 7
    fake_result.elapsed_ms = 100.0
    fake_result.error = ""
    fake_pipeline.run = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(
        "services.pipeline.get_ingest_pipeline", lambda: fake_pipeline, raising=False,
    )

    out = await mcp_server._tool_ingest({"file_path": str(file_path), "title": "T"})
    payload = json.loads(out[0].text)
    assert payload["success"] is True
    assert payload["doc_id"] == "doc-1"
    assert payload["total_chunks"] == 7


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_ingest_handles_pipeline_error(tmp_path, monkeypatch):
    """Error path: pipeline.run raises ValueError → error JSON."""
    from services import mcp_server

    file_path = tmp_path / "doc.txt"
    file_path.write_text("hello", encoding="utf-8")

    fake_pipeline = MagicMock()
    fake_pipeline.run = AsyncMock(side_effect=ValueError("invalid format"))
    monkeypatch.setattr(
        "services.pipeline.get_ingest_pipeline", lambda: fake_pipeline, raising=False,
    )

    out = await mcp_server._tool_ingest({"file_path": str(file_path)})
    payload = json.loads(out[0].text)
    assert "error" in payload


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_stats_returns_collection_info(monkeypatch):
    from services import mcp_server

    fake_store = MagicMock()
    fake_store.count = AsyncMock(return_value=42)
    monkeypatch.setattr(
        "services.vectorizer.vector_store.get_vector_store",
        lambda: fake_store, raising=False,
    )

    out = await mcp_server._tool_stats()
    payload = json.loads(out[0].text)
    assert payload["vector_count"] == 42
    assert "collection" in payload
    assert "embedding_model" in payload


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_stats_handles_postgres_error(monkeypatch):
    """Error path: count() raises asyncpg.PostgresError → error JSON."""
    import asyncpg

    from services import mcp_server

    fake_store = MagicMock()
    fake_store.count = AsyncMock(side_effect=asyncpg.PostgresError("unreachable"))
    monkeypatch.setattr(
        "services.vectorizer.vector_store.get_vector_store",
        lambda: fake_store, raising=False,
    )

    out = await mcp_server._tool_stats()
    payload = json.loads(out[0].text)
    assert "error" in payload
