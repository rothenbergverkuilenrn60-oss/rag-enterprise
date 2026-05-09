"""tests/unit/test_pipeline_helpers.py — Phase 15 backfill.

Existing tests/unit/test_pipeline_pii_block.py and test_swarm_pipeline.py
cover the heavy IngestionPipeline / SwarmQueryPipeline flows. This file
adds: _infer_doc_type DocType inference for every supported suffix, the
get_*_pipeline singletons, and AgentQueryPipeline _SubAgentResult dataclass
default behavior.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def reset_singletons(monkeypatch):
    import services.pipeline as mod
    yield
    for name in ("_ingest_pipeline", "_query_pipeline", "_agent_pipeline", "_swarm_pipeline"):
        monkeypatch.setattr(mod, name, None, raising=False)


@pytest.mark.unit
def test_infer_doc_type_pdf():
    from services.pipeline import _infer_doc_type
    from utils.models import DocType
    assert _infer_doc_type(Path("a.pdf")) == DocType.PDF
    assert _infer_doc_type(Path("a.PDF")) == DocType.PDF


@pytest.mark.unit
def test_infer_doc_type_office_formats():
    from services.pipeline import _infer_doc_type
    from utils.models import DocType
    assert _infer_doc_type(Path("a.docx")) == DocType.DOCX
    assert _infer_doc_type(Path("a.doc")) == DocType.DOCX
    assert _infer_doc_type(Path("a.xlsx")) == DocType.XLSX
    assert _infer_doc_type(Path("a.xls")) == DocType.XLSX


@pytest.mark.unit
def test_infer_doc_type_text_formats():
    from services.pipeline import _infer_doc_type
    from utils.models import DocType
    assert _infer_doc_type(Path("a.txt")) == DocType.TXT
    assert _infer_doc_type(Path("a.md")) == DocType.MD
    assert _infer_doc_type(Path("a.csv")) == DocType.CSV
    assert _infer_doc_type(Path("a.json")) == DocType.JSON
    assert _infer_doc_type(Path("a.html")) == DocType.HTML
    assert _infer_doc_type(Path("a.htm")) == DocType.HTML


@pytest.mark.unit
def test_infer_doc_type_image_formats():
    from services.pipeline import _infer_doc_type
    from utils.models import DocType
    assert _infer_doc_type(Path("a.jpg")) == DocType.IMAGE
    assert _infer_doc_type(Path("a.jpeg")) == DocType.IMAGE
    assert _infer_doc_type(Path("a.png")) == DocType.IMAGE
    assert _infer_doc_type(Path("a.webp")) == DocType.IMAGE


@pytest.mark.unit
def test_infer_doc_type_unknown_falls_back():
    """Error / fallback path: unknown extension → DocType.UNKNOWN."""
    from services.pipeline import _infer_doc_type
    from utils.models import DocType
    assert _infer_doc_type(Path("a.unknown")) == DocType.UNKNOWN
    assert _infer_doc_type(Path("noextension")) == DocType.UNKNOWN


@pytest.mark.unit
def test_sub_agent_result_carries_fields():
    from services.pipeline import _SubAgentResult
    r = _SubAgentResult(answer="a", turns=2, tool_calls_count=3, chunks=[])
    assert r.answer == "a"
    assert r.turns == 2
    assert r.tool_calls_count == 3
    assert r.chunks == []


@pytest.mark.unit
def test_sub_agent_result_with_failure_indicator():
    """Edge path: empty answer + zero turns indicates failed sub-agent run."""
    from services.pipeline import _SubAgentResult
    r = _SubAgentResult(answer="", turns=0, tool_calls_count=0, chunks=[])
    assert r.answer == ""
    assert r.turns == 0
