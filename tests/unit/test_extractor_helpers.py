"""tests/unit/test_extractor_helpers.py — Phase 15 backfill.

Existing tests/unit/test_extractor_ocr_routing.py covers the PDF OCR
routing branch. This file adds: lightweight format extractors (text, json,
html, csv), _detect_doc_type, _is_multi_column heuristic, _sort_blocks_multi_column.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import json
from pathlib import Path

import pytest


@pytest.mark.unit
def test_detect_doc_type_recognizes_known_extensions():
    from services.extractor.extractor import _detect_doc_type
    from utils.models import DocType
    assert _detect_doc_type(Path("a.pdf")) == DocType.PDF
    assert _detect_doc_type(Path("a.docx")) == DocType.DOCX
    assert _detect_doc_type(Path("a.txt")) == DocType.TXT
    assert _detect_doc_type(Path("a.png")) == DocType.IMAGE


@pytest.mark.unit
def test_detect_doc_type_unknown_falls_back():
    """Error path: unrecognized extension → DocType.UNKNOWN."""
    from services.extractor.extractor import _detect_doc_type
    from utils.models import DocType
    assert _detect_doc_type(Path("a.xyz")) == DocType.UNKNOWN
    assert _detect_doc_type(Path("noext")) == DocType.UNKNOWN


@pytest.mark.unit
def test_extract_text_reads_file(tmp_path):
    from services.extractor.extractor import _extract_text
    p = tmp_path / "doc.txt"
    p.write_text("hello world", encoding="utf-8")
    out = _extract_text(p)
    assert out["body_text"] == "hello world"
    assert out["engine"] == "plain-text"


@pytest.mark.unit
def test_extract_text_handles_bad_encoding(tmp_path):
    """Edge path: errors='ignore' allows undecodable bytes to be skipped."""
    from services.extractor.extractor import _extract_text
    p = tmp_path / "bad.txt"
    p.write_bytes(b"hello\xff\xfeworld")
    out = _extract_text(p)
    assert "hello" in out["body_text"]


@pytest.mark.unit
def test_extract_json_object(tmp_path):
    from services.extractor.extractor import _extract_json
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"k": "v", "n": 7}), encoding="utf-8")
    out = _extract_json(p)
    assert "k" in out["body_text"]
    assert out["engine"] == "json"


@pytest.mark.unit
def test_extract_json_list_serializes_per_element(tmp_path):
    from services.extractor.extractor import _extract_json
    p = tmp_path / "list.json"
    p.write_text(json.dumps([{"a": 1}, {"b": 2}]), encoding="utf-8")
    out = _extract_json(p)
    assert "\n" in out["body_text"]


@pytest.mark.unit
def test_extract_html_strips_scripts(tmp_path):
    from services.extractor.extractor import _extract_html
    p = tmp_path / "page.html"
    p.write_text(
        "<html><head><title>T</title></head><body>"
        "<script>alert(1)</script>"
        "<p>Body content</p>"
        "<table><tr><td>x</td><td>y</td></tr></table>"
        "</body></html>",
        encoding="utf-8",
    )
    out = _extract_html(p)
    assert out["title"] == "T"
    assert "alert" not in out["body_text"]
    assert "Body content" in out["body_text"]
    assert len(out["tables"]) == 1


@pytest.mark.unit
def test_extract_html_falls_back_to_filename_when_no_title(tmp_path):
    """Edge path: page without <title> → title = filename stem."""
    from services.extractor.extractor import _extract_html
    p = tmp_path / "untitled.html"
    p.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    out = _extract_html(p)
    assert out["title"] == "untitled"


@pytest.mark.unit
def test_is_multi_column_detects_two_columns():
    from services.extractor.extractor import _is_multi_column
    blocks = [
        {"x0": 10, "x1": 100, "y0": 0, "y1": 50, "text": "L1"},
        {"x0": 10, "x1": 100, "y0": 60, "y1": 100, "text": "L2"},
        {"x0": 300, "x1": 400, "y0": 0, "y1": 50, "text": "R1"},
        {"x0": 300, "x1": 400, "y0": 60, "y1": 100, "text": "R2"},
    ]
    assert _is_multi_column(blocks, page_width=500.0) is True


@pytest.mark.unit
def test_is_multi_column_too_few_blocks():
    """Edge path: < 4 blocks → not multi-column (early return)."""
    from services.extractor.extractor import _is_multi_column
    blocks = [
        {"x0": 10, "x1": 100, "y0": 0, "y1": 50, "text": "x"},
        {"x0": 10, "x1": 100, "y0": 60, "y1": 100, "text": "y"},
    ]
    assert _is_multi_column(blocks, page_width=500.0) is False


@pytest.mark.unit
def test_sort_blocks_multi_column_orders_left_then_right():
    from services.extractor.extractor import _sort_blocks_multi_column
    blocks = [
        {"x0": 10, "x1": 100, "y0": 0, "y1": 50, "text": "L1"},
        {"x0": 300, "x1": 400, "y0": 0, "y1": 50, "text": "R1"},
        {"x0": 10, "x1": 100, "y0": 60, "y1": 100, "text": "L2"},
        {"x0": 300, "x1": 400, "y0": 60, "y1": 100, "text": "R2"},
    ]
    out = _sort_blocks_multi_column(blocks, page_width=500.0)
    text_order = [b["text"] for b in out]
    assert text_order.index("L1") < text_order.index("R1")
    assert text_order.index("L2") < text_order.index("R2")


@pytest.mark.unit
def test_extract_csv_reads_basic_rows(tmp_path):
    from services.extractor.extractor import _extract_csv
    p = tmp_path / "tbl.csv"
    p.write_text("name,age\nA,1\nB,2\n", encoding="utf-8")
    out = _extract_csv(p)
    assert out["engine"] == "pandas-csv"
    assert "name" in out["body_text"]
    assert len(out["tables"]) == 1
