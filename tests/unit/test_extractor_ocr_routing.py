"""Tests for the scanned-PDF OCR routing in extractor.py — Phase 7 OCR-01/02.

Verifies that:
  * `_extract_pdf_enterprise` with `ocr_engine=paddle` delegates to
    `services.extractor.ocr_engine.get_ocr_engine` and returns its dict.
  * `ocr_engine=tesseract` still calls `_extract_pdf_scanned_tesseract`
    (existing fallback path unchanged).
  * `ocr_engine=none` still returns the unchanged "skipped" dict
    (Phase 4 contract preserved).
  * Digital-PDF routing (`is_scanned_pdf=False`) is untouched.
  * `ExtractorService.extract` carries forward `tables` from the new dict shape
    into `ExtractedContent.tables`.

All paddleocr dependencies are mocked — no install required.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# _extract_pdf_enterprise routing
# ──────────────────────────────────────────────────────────────────────────────
def test_paddle_route_delegates_to_get_ocr_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.extractor import extractor as ext

    pdf = tmp_path / "scanned.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%mock\n")

    monkeypatch.setattr(ext, "is_scanned_pdf", lambda p, sample_pages=3: True)
    monkeypatch.setattr(ext.settings, "ocr_engine", "paddle")

    fake_dict = {
        "body_text": "ocr text",
        "tables": [{"page": 1, "html": "<table></table>"}],
        "pages": 1,
        "title": "scanned",
        "engine": "ppstructurev3",
    }
    fake_engine = MagicMock()
    fake_engine.extract_pdf = AsyncMock(return_value=fake_dict)

    with patch(
        "services.extractor.ocr_engine.get_ocr_engine", return_value=fake_engine
    ) as get_eng:
        result = ext._extract_pdf_enterprise(pdf)

    get_eng.assert_called_once()
    fake_engine.extract_pdf.assert_awaited_once()
    assert result == fake_dict


def test_tesseract_route_uses_legacy_function(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit `ocr_engine=tesseract` must call _extract_pdf_scanned_tesseract
    directly — the legacy fallback path is preserved."""
    from services.extractor import extractor as ext

    pdf = tmp_path / "scanned.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%mock\n")

    monkeypatch.setattr(ext, "is_scanned_pdf", lambda p, sample_pages=3: True)
    monkeypatch.setattr(ext.settings, "ocr_engine", "tesseract")

    fake_dict = {
        "body_text": "tess",
        "tables": [],
        "pages": 1,
        "title": "scanned",
        "engine": "tesseract(scanned)",
    }
    with patch.object(
        ext, "_extract_pdf_scanned_tesseract", return_value=fake_dict
    ) as mocked:
        result = ext._extract_pdf_enterprise(pdf)

    mocked.assert_called_once_with(pdf)
    assert result == fake_dict


def test_none_route_returns_skipped_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ocr_engine=none` must continue to return the unchanged 'skipped' dict."""
    from services.extractor import extractor as ext

    pdf = tmp_path / "scanned.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%mock\n")

    monkeypatch.setattr(ext, "is_scanned_pdf", lambda p, sample_pages=3: True)
    monkeypatch.setattr(ext.settings, "ocr_engine", "none")

    result = ext._extract_pdf_enterprise(pdf)

    assert result["body_text"] == ""
    assert result["pages"] == 0
    assert result["engine"] == "skipped(ocr_engine=none)"
    assert "extraction_errors" in result
    assert any("跳过" in e for e in result["extraction_errors"])


def test_digital_pdf_path_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the PDF is digital (not scanned), `_extract_pdf_digital` must run."""
    from services.extractor import extractor as ext

    pdf = tmp_path / "digital.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%mock\n")

    monkeypatch.setattr(ext, "is_scanned_pdf", lambda p, sample_pages=3: False)

    fake_dict = {
        "body_text": "digital text",
        "tables": [],
        "pages": 1,
        "title": "digital",
        "engine": "pymupdf+pdfplumber(digital)",
    }
    with patch.object(ext, "_extract_pdf_digital", return_value=fake_dict) as mocked:
        result = ext._extract_pdf_enterprise(pdf)

    mocked.assert_called_once_with(pdf)
    assert result == fake_dict


# ──────────────────────────────────────────────────────────────────────────────
# End-to-end ExtractorService — table propagation
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_extractor_service_carries_pp_structure_tables_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given a mocked `_extract_pdf_enterprise` returning the new PP-StructureV3
    dict shape with populated tables, the resulting ExtractedContent must carry
    those tables in `.tables`."""
    from services.extractor import extractor as ext
    from utils.models import DocType, RawDocument

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%mock\n")

    raw = RawDocument(
        raw_id="raw-1",
        file_path=str(pdf),
        doc_type=DocType.PDF,
    )

    pp_dict = {
        "body_text": "页一文本",
        "tables": [
            {"page": 1, "html": "<table><tr><td>X</td></tr></table>"},
            {"page": 2, "html": "<table><tr><td>Y</td></tr></table>"},
        ],
        "pages": 2,
        "title": "doc",
        "engine": "ppstructurev3",
    }

    # _EXTRACTOR_MAP captured the extractor function at module import — patch
    # the map entry directly so the dispatcher returns our fake.
    monkeypatch.setitem(ext._EXTRACTOR_MAP, DocType.PDF, lambda p: pp_dict)
    monkeypatch.setattr(
        ext, "extract_images_from_pdf", lambda p, raw_id: []
    )

    svc = ext.ExtractorService()
    content = await svc.extract(raw)

    assert content.extraction_engine == "ppstructurev3"
    assert content.pages == 2
    assert len(content.tables) == 2
    assert content.tables[0]["html"].startswith("<table>")
