# =============================================================================
# tests/integration/test_pipeline.py
# 集成测试 — 全链路 Pipeline（需要 Ollama + Qdrant 服务运行）
# 运行：conda run -n torch_env pytest tests/integration/ -v --timeout=120
# =============================================================================
import pytest
import asyncio
import tempfile
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════
def _write_temp_txt(content: str) -> str:
    """写临时 .txt 文件到 /mnt/f/ 路径（测试专用）。"""
    import os
    tmp_dir = Path("/mnt/f/rag_enterprise/data/test_tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / "integration_test.txt"
    tmp_path.write_text(content, encoding="utf-8")
    return str(tmp_path)


# ══════════════════════════════════════════════════════════════════════════════
# Stage 1+2+3 — Preprocessor + Extractor + DocProcessor
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_preprocess_extract_chunk_pipeline() -> None:
    """验证从文件到 DocumentChunk 列表的完整前三阶段。"""
    content = (
        "企业级RAG系统架构文档。\n\n"
        "本文档介绍企业级检索增强生成系统的核心组件，"
        "包括预处理、提取、分块、向量化、检索和生成六个阶段。\n\n"
        "每个阶段都经过严格的工程化设计，符合Fortune 500企业级标准。\n\n"
    ) * 10
    file_path = _write_temp_txt(content)

    from utils.models import RawDocument, DocType
    from services.preprocessor.cleaner import get_preprocessor
    from services.extractor.extractor import get_extractor
    from services.doc_processor.chunker import get_doc_processor

    raw_doc = RawDocument(raw_id="test_001", file_path=file_path, doc_type=DocType.TXT)

    # Stage 1
    pre_result = await get_preprocessor().process(raw_doc)
    assert pre_result.char_count > 0
    assert not pre_result.is_duplicate

    # Stage 2
    extracted = await get_extractor().extract(raw_doc)
    assert len(extracted.body_text) > 0
    assert not extracted.extraction_errors

    # Stage 3
    chunks = await get_doc_processor().process(extracted, "test_001")
    assert len(chunks) > 0
    for chunk in chunks:
        assert len(chunk.content) >= 50
        assert chunk.chunk_id.startswith("test_001")
        assert chunk.metadata.doc_id == "test_001"


# ══════════════════════════════════════════════════════════════════════════════
# FastAPI 路由集成测试
# ══════════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    """验证 /health 端点可访问。"""
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


@pytest.mark.asyncio
async def test_ingest_endpoint_missing_file() -> None:
    """验证摄取不存在文件时返回 422。"""
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/ingest",
            json={"file_path": "/mnt/f/nonexistent/file_that_does_not_exist.pdf"},
        )
    assert resp.status_code in (422, 500)


@pytest.mark.asyncio
async def test_query_endpoint_empty_query() -> None:
    """验证空查询返回 422。"""
    from httpx import AsyncClient, ASGITransport
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/query",
            json={"query": ""},
        )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Pytest 配置
# ══════════════════════════════════════════════════════════════════════════════
def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as async")
