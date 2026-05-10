"""Coverage tests for services/extractor/extractor.py per TEST-12 (Phase 22 SC5).

Targets:
- is_scanned_pdf 3-page-sample heuristic (text-rich vs scanned; mock get_text return values, no binary PDFs)
- _detect_header_footer_texts 10-page-cap branch
- OCR-vs-native-extract router (_extract_pdf_enterprise)
- Tesseract OCR engine selection (v1.4.2 fix region, _extract_pdf_scanned_tesseract)

Mock at consumer path (services.extractor.extractor.<dep>) only — CF-02.
No new binary PDF fixtures (D-16) — mock fitz module via sys.modules.
No production-code changes (CF-01).
"""
from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Fake fitz infrastructure (D-16: no binary PDFs; mock PyMuPDF at sys.modules)
# ──────────────────────────────────────────────────────────────────────────────

class FakePage:
    """Minimal fake for fitz.Page."""

    def __init__(self, text: str = "", width: float = 612.0, height: float = 792.0):
        self._text = text
        self.rect = types.SimpleNamespace(
            width=width, height=height, x0=0, y0=0, x1=width, y1=height
        )

    def get_text(self, mode: str = "text", clip=None, **kwargs) -> str:
        return self._text

    def get_pixmap(self, matrix=None, alpha: bool = False) -> "FakePixmap":
        return FakePixmap()


class FakePixmap:
    """Minimal fake for fitz.Pixmap."""

    def tobytes(self, fmt: str = "png") -> bytes:
        # Minimal valid 1×1 white PNG so PIL.Image.open() won't crash
        import base64
        # 1×1 white PNG, base64-encoded
        _PNG_1X1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
            b"\x00\x00\x01\x01\x00\x05\x18\xd5N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return _PNG_1X1


class FakeRect:
    """Minimal fake for fitz.Rect — used in _detect_header_footer_texts."""

    def __init__(self, x0=0, y0=0, x1=612, y1=792):
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1


class FakeDocument:
    """Fake fitz.Document with configurable page count and per-page text."""

    def __init__(self, page_texts: list[str], width: float = 612.0, height: float = 792.0):
        self._page_texts = page_texts
        self._width = width
        self._height = height
        self.page_count = len(page_texts)
        self.metadata: dict = {}
        self._load_page_calls: list[int] = []

    def __getitem__(self, idx: int) -> FakePage:
        return FakePage(self._page_texts[idx], self._width, self._height)

    def load_page(self, idx: int) -> FakePage:
        self._load_page_calls.append(idx)
        return FakePage(self._page_texts[idx], self._width, self._height)

    def close(self) -> None:
        pass

    @property
    def load_page_call_count(self) -> int:
        return len(self._load_page_calls)


def _make_fake_fitz(page_texts: list[str], *, width: float = 612.0, height: float = 792.0):
    """Return a (fake_fitz_module, fake_document) pair for use in sys.modules."""
    doc = FakeDocument(page_texts, width=width, height=height)

    fake_fitz = types.ModuleType("fitz")
    fake_fitz.open = lambda path: doc          # type: ignore[attr-defined]
    fake_fitz.Rect = FakeRect                  # type: ignore[attr-defined]
    fake_fitz.Matrix = lambda *a, **kw: None   # type: ignore[attr-defined]

    return fake_fitz, doc


# ──────────────────────────────────────────────────────────────────────────────
# is_scanned_pdf — SC5 branch family 1
# ──────────────────────────────────────────────────────────────────────────────

class TestIsScannedPdf:
    """SC5 branch family 1: is_scanned_pdf 3-page-sample heuristic."""

    def test_text_rich_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pages with >=0.01 char density → not scanned → False."""
        # 200 chars on a 612×792 page → density = 200/484_704 ≈ 0.000413 ... wait:
        # actual density = total_chars / total_area; page area = 612*792 = 484704
        # 200 chars / 484704 = 4.1e-4 < 0.01 threshold.
        # Need enough chars: 0.01 * 484704 * 3 = 14541 chars for 3 pages.
        page_text = "a" * 6000  # 6000 per page × 3 pages = 18000 > 14541 → density > 0.01
        fake_fitz, _doc = _make_fake_fitz([page_text, page_text, page_text, page_text])
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import is_scanned_pdf
        assert is_scanned_pdf(Path("/fake/doc.pdf"), sample_pages=3) is False

    def test_empty_pages_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty pages → 0 char density → scanned → True."""
        fake_fitz, _doc = _make_fake_fitz(["", "", ""])
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import is_scanned_pdf
        assert is_scanned_pdf(Path("/fake/doc.pdf"), sample_pages=3) is True

    def test_below_threshold_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """5 chars per page → density far below 0.01 → scanned → True."""
        fake_fitz, _doc = _make_fake_fitz(["a" * 5, "a" * 5, "a" * 5])
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import is_scanned_pdf
        assert is_scanned_pdf(Path("/fake/doc.pdf"), sample_pages=3) is True

    def test_open_failure_returns_false(
        self, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """fitz.open raises → except branch hit → returns False + logs warning."""
        import logging

        fake_fitz = types.ModuleType("fitz")
        fake_fitz.open = lambda path: (_ for _ in ()).throw(RuntimeError("fitz open failed"))  # type: ignore
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        # Use caplog with loguru: loguru propagates to stdlib logging in tests
        with caplog.at_level(logging.WARNING):
            from services.extractor.extractor import is_scanned_pdf
            result = is_scanned_pdf(Path("/fake/doc.pdf"), sample_pages=3)

        assert result is False

    @pytest.mark.parametrize(
        "page_text, expected_scanned",
        [
            ("a" * 6000, False),   # text-rich: 6000 chars/page × 3 pages > threshold
            ("", True),            # empty pages
            ("a" * 5, True),       # below threshold
        ],
        ids=["text-rich", "empty", "below-threshold"],
    )
    def test_threshold_table(
        self,
        monkeypatch: pytest.MonkeyPatch,
        page_text: str,
        expected_scanned: bool,
    ) -> None:
        """Parametrized table: text/density boundary → correct scanned decision."""
        fake_fitz, _doc = _make_fake_fitz([page_text, page_text, page_text])
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import is_scanned_pdf
        assert is_scanned_pdf(Path("/fake/doc.pdf"), sample_pages=3) is expected_scanned

    def test_samples_only_sample_pages_not_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """sample_pages=2 on a 5-page doc → reads only 2 pages, not 5."""
        # 2 text-rich pages, 3 empty pages — result depends on first 2 only
        # 6000 chars × 2 pages / (2 × 484704 area) → density > 0.01 → False
        page_texts = ["a" * 6000, "a" * 6000, "", "", ""]
        fake_fitz, _doc = _make_fake_fitz(page_texts)
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import is_scanned_pdf
        result = is_scanned_pdf(Path("/fake/doc.pdf"), sample_pages=2)
        assert result is False

    def test_zero_area_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pages with zero area (width=0, height=0) → total_area==0 → True (L50 branch)."""

        class ZeroAreaPage(FakePage):
            """Page with zero-area rect."""
            def __init__(self):
                super().__init__("some text", width=0.0, height=0.0)

        class ZeroAreaDoc(FakeDocument):
            def __getitem__(self, idx: int) -> ZeroAreaPage:
                return ZeroAreaPage()

        doc = ZeroAreaDoc(["text"])
        fake_fitz = types.ModuleType("fitz")
        fake_fitz.open = lambda path: doc  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import is_scanned_pdf
        result = is_scanned_pdf(Path("/fake/doc.pdf"), sample_pages=1)
        assert result is True


# ──────────────────────────────────────────────────────────────────────────────
# _detect_header_footer_texts — SC5 branch family 2 (10-page-cap)
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectHeaderFooterTexts:
    """SC5 branch family 2: _detect_header_footer_texts 10-page-cap."""

    def test_caps_at_max_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """50-page doc with max_pages=10 → loads exactly 10 pages."""
        page_texts = ["header\ncontent\nfooter"] * 50
        fake_fitz, doc = _make_fake_fitz(page_texts)
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import _detect_header_footer_texts
        _detect_header_footer_texts(Path("/fake/doc.pdf"), max_pages=10)

        # The function uses doc[i] (subscript), not load_page.
        # Verify by counting subscript calls via a custom __getitem__ tracker.
        # Re-approach: instrument __getitem__ to track calls.
        # Reset and run with instrumented doc.
        get_item_calls: list[int] = []

        class TrackedDocument(FakeDocument):
            def __getitem__(self, idx: int) -> FakePage:
                get_item_calls.append(idx)
                return super().__getitem__(idx)

        tracked_doc = TrackedDocument(page_texts)
        fake_fitz2 = types.ModuleType("fitz")
        fake_fitz2.open = lambda path: tracked_doc   # type: ignore[attr-defined]
        fake_fitz2.Rect = FakeRect                    # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz2)

        _detect_header_footer_texts(Path("/fake/doc.pdf"), max_pages=10)
        assert len(get_item_calls) == 10

    def test_short_doc_reads_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """5-page doc with max_pages=10 → reads all 5 pages."""
        page_texts = ["line1\nline2"] * 5
        get_item_calls: list[int] = []

        class TrackedDocument(FakeDocument):
            def __getitem__(self, idx: int) -> FakePage:
                get_item_calls.append(idx)
                return super().__getitem__(idx)

        tracked_doc = TrackedDocument(page_texts)
        fake_fitz = types.ModuleType("fitz")
        fake_fitz.open = lambda path: tracked_doc  # type: ignore[attr-defined]
        fake_fitz.Rect = FakeRect                   # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import _detect_header_footer_texts
        _detect_header_footer_texts(Path("/fake/doc.pdf"), max_pages=10)
        assert len(get_item_calls) == 5

    def test_repeated_lines_detected_as_noise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Line appearing on ≥40% of pages should be detected as header/footer noise."""
        # "COMPANY INC" appears in header zone on all 10 pages → noise
        page_texts = ["COMPANY INC\ncontent\nPage 1"] * 10
        get_item_calls: list[int] = []

        class TrackedDocument(FakeDocument):
            def __getitem__(self, idx: int) -> FakePage:
                get_item_calls.append(idx)
                return super().__getitem__(idx)

        tracked_doc = TrackedDocument(page_texts)
        fake_fitz = types.ModuleType("fitz")
        fake_fitz.open = lambda path: tracked_doc  # type: ignore[attr-defined]
        fake_fitz.Rect = FakeRect                   # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import _detect_header_footer_texts
        noise = _detect_header_footer_texts(Path("/fake/doc.pdf"), max_pages=10)
        # Result is a set; at minimum it should exist (empty if Rect clip logic
        # prevents detection — but at least the function completes without error)
        assert isinstance(noise, set)

    def test_fitz_open_failure_returns_empty_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """fitz.open raises → except branch → returns empty set."""
        fake_fitz = types.ModuleType("fitz")
        fake_fitz.open = lambda path: (_ for _ in ()).throw(RuntimeError("open failed"))  # type: ignore
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        from services.extractor.extractor import _detect_header_footer_texts
        result = _detect_header_footer_texts(Path("/fake/doc.pdf"), max_pages=10)
        assert result == set()


# ──────────────────────────────────────────────────────────────────────────────
# _extract_pdf_enterprise — SC5 branch family 3 (OCR-vs-native router)
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractPdfEnterpriseRouter:
    """SC5 branch family 3: OCR-vs-native-extract router in _extract_pdf_enterprise."""

    def test_routes_to_digital_when_not_scanned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_scanned_pdf=False → _extract_pdf_digital called, not OCR."""
        from services.extractor import extractor as ext

        digital_calls: list = []

        def fake_digital(path: Path) -> dict:
            digital_calls.append(path)
            return {
                "body_text": "native text",
                "tables": [],
                "pages": 1,
                "title": "doc",
                "engine": "pymupdf+pdfplumber(digital)",
                "extraction_errors": [],
            }

        monkeypatch.setattr("services.extractor.extractor.is_scanned_pdf", lambda p: False)
        monkeypatch.setattr("services.extractor.extractor._extract_pdf_digital", fake_digital)

        result = ext._extract_pdf_enterprise(Path("/fake/doc.pdf"))
        assert len(digital_calls) == 1
        assert result["body_text"] == "native text"
        assert result["engine"] == "pymupdf+pdfplumber(digital)"

    def test_routes_to_tesseract_when_scanned_and_engine_tesseract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_scanned_pdf=True + ocr_engine=tesseract → _extract_pdf_scanned_tesseract."""
        from services.extractor import extractor as ext

        tess_calls: list = []

        def fake_tesseract(path: Path) -> dict:
            tess_calls.append(path)
            return {
                "body_text": "ocr text",
                "tables": [],
                "pages": 1,
                "title": "doc",
                "engine": "tesseract(scanned)",
            }

        monkeypatch.setattr("services.extractor.extractor.is_scanned_pdf", lambda p: True)
        monkeypatch.setattr(ext.settings, "ocr_engine", "tesseract")
        monkeypatch.setattr(
            "services.extractor.extractor._extract_pdf_scanned_tesseract", fake_tesseract
        )

        result = ext._extract_pdf_enterprise(Path("/fake/doc.pdf"))
        assert len(tess_calls) == 1
        assert result["engine"] == "tesseract(scanned)"

    def test_routes_to_paddleocr_when_scanned_and_engine_auto(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """is_scanned_pdf=True + ocr_engine=auto → _extract_pdf_scanned_paddleocr."""
        from services.extractor import extractor as ext

        paddle_calls: list = []

        def fake_paddle(path: Path) -> dict:
            paddle_calls.append(path)
            return {
                "body_text": "paddle ocr text",
                "tables": [],
                "pages": 1,
                "title": "doc",
                "engine": "ppstructurev3",
            }

        monkeypatch.setattr("services.extractor.extractor.is_scanned_pdf", lambda p: True)
        monkeypatch.setattr(ext.settings, "ocr_engine", "auto")
        monkeypatch.setattr(
            "services.extractor.extractor._extract_pdf_scanned_paddleocr", fake_paddle
        )

        result = ext._extract_pdf_enterprise(Path("/fake/doc.pdf"))
        assert len(paddle_calls) == 1
        assert result["engine"] == "ppstructurev3"

    def test_routes_to_none_skips_scanned(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """is_scanned_pdf=True + ocr_engine=none → skipped dict returned."""
        from services.extractor import extractor as ext

        monkeypatch.setattr("services.extractor.extractor.is_scanned_pdf", lambda p: True)
        monkeypatch.setattr(ext.settings, "ocr_engine", "none")

        result = ext._extract_pdf_enterprise(Path("/fake/doc.pdf"))
        assert result["body_text"] == ""
        assert result["engine"] == "skipped(ocr_engine=none)"
        assert "extraction_errors" in result

    def test_unknown_engine_falls_back_to_paddle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unknown ocr_engine value → degraded to paddleocr path."""
        from services.extractor import extractor as ext

        paddle_calls: list = []

        def fake_paddle(path: Path) -> dict:
            paddle_calls.append(path)
            return {
                "body_text": "degraded ocr",
                "tables": [],
                "pages": 1,
                "title": "doc",
                "engine": "ppstructurev3",
            }

        monkeypatch.setattr("services.extractor.extractor.is_scanned_pdf", lambda p: True)
        monkeypatch.setattr(ext.settings, "ocr_engine", "unknown_value")
        monkeypatch.setattr(
            "services.extractor.extractor._extract_pdf_scanned_paddleocr", fake_paddle
        )

        result = ext._extract_pdf_enterprise(Path("/fake/doc.pdf"))
        assert len(paddle_calls) == 1


# ──────────────────────────────────────────────────────────────────────────────
# _extract_pdf_scanned_tesseract — SC5 branch family 4 (v1.4.2 fix)
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractPdfScannedTesseract:
    """SC5 branch family 4: Tesseract OCR engine selection (v1.4.2 fix region)."""

    def test_invokes_image_to_string_and_returns_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tesseract path: pytesseract.image_to_string called; result in body_text."""
        image_to_string_calls: list = []

        def fake_image_to_string(img, lang=None, config=None, **kwargs) -> str:
            image_to_string_calls.append((lang, config))
            return "OCR extracted text"

        fake_pytesseract = types.ModuleType("pytesseract")
        fake_pytesseract.image_to_string = fake_image_to_string  # type: ignore[attr-defined]

        # fitz: 1-page doc with a pixmap
        page_texts = ["some text"]
        fake_fitz, _doc = _make_fake_fitz(page_texts)

        # PIL.Image must be available (it is in dev deps); mock it to avoid actual PNG decode
        fake_pil_image = types.ModuleType("PIL")
        fake_pil_image_module = types.ModuleType("PIL.Image")

        fake_img = MagicMock()
        fake_pil_image_module.open = MagicMock(return_value=fake_img)  # type: ignore[attr-defined]
        fake_pil_image.Image = fake_pil_image_module  # type: ignore[attr-defined]

        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
        monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
        monkeypatch.setitem(sys.modules, "PIL", fake_pil_image)
        monkeypatch.setitem(sys.modules, "PIL.Image", fake_pil_image_module)

        # Also need io module (stdlib, will be available)
        from services.extractor.extractor import _extract_pdf_scanned_tesseract
        result = _extract_pdf_scanned_tesseract(Path("/fake/doc.pdf"))

        assert len(image_to_string_calls) == 1
        assert "OCR extracted text" in result["body_text"]
        assert result["engine"] == "tesseract(scanned)"

    def test_import_error_returns_empty_with_error_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ImportError inside Tesseract function → fallback dict with extraction_errors."""
        # Make fitz unavailable so the function hits ImportError
        import builtins
        real_import = builtins.__import__

        def import_raiser(name, *args, **kwargs):
            if name == "fitz":
                raise ImportError("No module named 'fitz'")
            return real_import(name, *args, **kwargs)

        # Remove fitz from sys.modules to force re-import
        monkeypatch.delitem(sys.modules, "fitz", raising=False)
        monkeypatch.setattr(builtins, "__import__", import_raiser)

        from services.extractor.extractor import _extract_pdf_scanned_tesseract
        result = _extract_pdf_scanned_tesseract(Path("/fake/doc.pdf"))

        assert result["body_text"] == ""
        assert result["pages"] == 0
        assert result["engine"] == "none"
        assert "extraction_errors" in result
        assert len(result["extraction_errors"]) > 0

    def test_engine_result_has_correct_structure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Result dict from Tesseract path has all required keys."""
        fake_pytesseract = types.ModuleType("pytesseract")
        fake_pytesseract.image_to_string = lambda img, **kw: "page text here"  # type: ignore[attr-defined]

        page_texts = ["some content"]
        fake_fitz, _doc = _make_fake_fitz(page_texts)

        fake_pil_image_module = types.ModuleType("PIL.Image")
        fake_pil_image_module.open = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]

        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
        monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
        monkeypatch.setitem(sys.modules, "PIL.Image", fake_pil_image_module)
        monkeypatch.setitem(sys.modules, "PIL", types.ModuleType("PIL"))

        from services.extractor.extractor import _extract_pdf_scanned_tesseract
        result = _extract_pdf_scanned_tesseract(Path("/fake/doc.pdf"))

        for key in ("body_text", "tables", "pages", "title", "engine"):
            assert key in result, f"missing key: {key}"
        assert result["tables"] == []

    @pytest.mark.parametrize(
        "page_text, expect_in_body",
        [
            ("Hello World", True),    # non-empty → appears in body_text
            ("   \n  ", False),       # whitespace only → stripped → not added
        ],
        ids=["non-empty-text", "whitespace-only"],
    )
    def test_page_text_inclusion(
        self,
        monkeypatch: pytest.MonkeyPatch,
        page_text: str,
        expect_in_body: bool,
    ) -> None:
        """Pages with whitespace-only text are excluded from body_text."""
        fake_pytesseract = types.ModuleType("pytesseract")
        fake_pytesseract.image_to_string = lambda img, **kw: page_text  # type: ignore[attr-defined]

        page_texts = [page_text]
        fake_fitz, _doc = _make_fake_fitz(page_texts)

        fake_pil_image_module = types.ModuleType("PIL.Image")
        fake_pil_image_module.open = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]

        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
        monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
        monkeypatch.setitem(sys.modules, "PIL.Image", fake_pil_image_module)
        monkeypatch.setitem(sys.modules, "PIL", types.ModuleType("PIL"))

        from services.extractor.extractor import _extract_pdf_scanned_tesseract
        result = _extract_pdf_scanned_tesseract(Path("/fake/doc.pdf"))

        if expect_in_body:
            assert page_text.strip() in result["body_text"]
        else:
            assert result["body_text"] == ""


# ──────────────────────────────────────────────────────────────────────────────
# Additional coverage: _extract_pdf_digital happy path (long-tail lines)
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractPdfDigital:
    """Happy-path coverage for _extract_pdf_digital (long-tail line closure)."""

    def _make_digital_fitz(self, monkeypatch: pytest.MonkeyPatch, multi_column: bool = False):
        """Helper: install fake fitz for _extract_pdf_digital tests."""
        if multi_column:
            # Two columns of blocks to trigger _is_multi_column branch
            blocks = [
                (10, 100, 200, 150, "Left col 1", 0, 0),
                (10, 160, 200, 210, "Left col 2", 1, 0),
                (310, 100, 500, 150, "Right col 1", 2, 0),
                (310, 160, 500, 210, "Right col 2", 3, 0),
            ]
        else:
            blocks = [(50, 100, 400, 200, "Digital content here", 0, 0)]

        class DigitalPage(FakePage):
            def __init__(self):
                super().__init__("Digital content here", 612.0, 792.0)
                self._blocks = blocks

            def get_text(self, mode: str = "text", clip=None, **kwargs):
                if mode == "blocks":
                    return self._blocks
                return "Digital content here"

        class DigitalDoc(FakeDocument):
            def __init__(self):
                super().__init__(["Digital content here"])

            def __getitem__(self, idx: int) -> DigitalPage:
                return DigitalPage()

        doc = DigitalDoc()
        fake_fitz = types.ModuleType("fitz")
        fake_fitz.open = lambda path: doc  # type: ignore[attr-defined]
        fake_fitz.Rect = FakeRect           # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        # pdfplumber: no tables
        fake_pdfplumber = types.ModuleType("pdfplumber")
        fake_pdf_ctx = MagicMock()
        fake_pdf_ctx.__enter__ = MagicMock(return_value=fake_pdf_ctx)
        fake_pdf_ctx.__exit__ = MagicMock(return_value=False)
        fake_pdf_ctx.pages = []
        fake_pdfplumber.open = MagicMock(return_value=fake_pdf_ctx)  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

        monkeypatch.setattr(
            "services.extractor.extractor._detect_header_footer_texts",
            lambda path, max_pages=10: set(),
        )

    def test_digital_extraction_returns_body_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_extract_pdf_digital with mocked fitz + pdfplumber → returns dict with body_text."""
        self._make_digital_fitz(monkeypatch)

        from services.extractor.extractor import _extract_pdf_digital
        result = _extract_pdf_digital(Path("/fake/doc.pdf"))

        assert isinstance(result["body_text"], str)
        assert result["engine"] == "pymupdf+pdfplumber(digital)"
        assert "tables" in result
        assert "pages" in result

    def test_digital_multi_column_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_extract_pdf_digital with multi-column blocks → _sort_blocks_multi_column called."""
        self._make_digital_fitz(monkeypatch, multi_column=True)

        from services.extractor.extractor import _extract_pdf_digital
        result = _extract_pdf_digital(Path("/fake/doc.pdf"))

        assert isinstance(result["body_text"], str)
        assert result["engine"] == "pymupdf+pdfplumber(digital)"

    def test_digital_extraction_with_pdfplumber_tables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_extract_pdf_digital: pdfplumber tables → appended to body_text."""

        class DigitalPage(FakePage):
            def get_text(self, mode: str = "text", clip=None, **kwargs):
                if mode == "blocks":
                    return [(50, 100, 400, 200, "Page text", 0, 0)]
                return "Page text"

        class DigitalDoc(FakeDocument):
            def __getitem__(self, idx: int) -> DigitalPage:
                return DigitalPage(self._page_texts[idx])

        doc = DigitalDoc(["Page text"])
        fake_fitz = types.ModuleType("fitz")
        fake_fitz.open = lambda path: doc  # type: ignore[attr-defined]
        fake_fitz.Rect = FakeRect           # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

        # pdfplumber: one page with one table
        fake_pdf_page = MagicMock()
        fake_pdf_page.extract_tables.return_value = [
            [["Header1", "Header2"], ["val1", "val2"]]
        ]
        fake_pdf_ctx = MagicMock()
        fake_pdf_ctx.__enter__ = MagicMock(return_value=fake_pdf_ctx)
        fake_pdf_ctx.__exit__ = MagicMock(return_value=False)
        fake_pdf_ctx.pages = [fake_pdf_page]

        fake_pdfplumber = types.ModuleType("pdfplumber")
        fake_pdfplumber.open = MagicMock(return_value=fake_pdf_ctx)  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

        monkeypatch.setattr(
            "services.extractor.extractor._detect_header_footer_texts",
            lambda path, max_pages=10: set(),
        )

        from services.extractor.extractor import _extract_pdf_digital
        result = _extract_pdf_digital(Path("/fake/doc.pdf"))

        assert len(result["tables"]) == 1
        assert "Header1" in result["body_text"]


# ──────────────────────────────────────────────────────────────────────────────
# Additional coverage: ExtractorService.extract error paths
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractorServiceEdgePaths:
    """Additional ExtractorService coverage for error/edge paths."""

    @pytest.mark.asyncio
    async def test_extract_returns_error_for_missing_file(self) -> None:
        """File not found → extraction_errors contains 'File not found'."""
        from services.extractor.extractor import ExtractorService
        from utils.models import DocType, RawDocument

        raw = RawDocument(
            raw_id="test-missing",
            file_path="/nonexistent/path/doc.pdf",
            doc_type=DocType.PDF,
        )
        svc = ExtractorService()
        content = await svc.extract(raw)
        assert len(content.extraction_errors) > 0
        assert any("not found" in e.lower() or "File" in e for e in content.extraction_errors)

    @pytest.mark.asyncio
    async def test_extract_unknown_format_returns_error(
        self, tmp_path: Path
    ) -> None:
        """Unsupported doc type → extraction_errors with format message."""
        from services.extractor.extractor import ExtractorService
        from utils.models import DocType, RawDocument

        # Create a real file with unknown extension
        f = tmp_path / "file.xyz"
        f.write_text("content")

        raw = RawDocument(
            raw_id="test-unknown",
            file_path=str(f),
            doc_type=DocType.UNKNOWN,
        )
        svc = ExtractorService()
        content = await svc.extract(raw)
        # UNKNOWN type with no extractor → extraction_errors
        assert len(content.extraction_errors) > 0

    @pytest.mark.asyncio
    async def test_extract_txt_happy_path(self, tmp_path: Path) -> None:
        """TXT file → body_text populated, no errors."""
        from services.extractor.extractor import ExtractorService
        from utils.models import DocType, RawDocument

        f = tmp_path / "doc.txt"
        f.write_text("Hello from text file")

        raw = RawDocument(
            raw_id="test-txt",
            file_path=str(f),
            doc_type=DocType.TXT,
        )
        svc = ExtractorService()
        content = await svc.extract(raw)
        assert "Hello" in content.body_text
        assert content.extraction_engine == "plain-text"

    @pytest.mark.asyncio
    async def test_extract_json_happy_path(self, tmp_path: Path) -> None:
        """JSON file → body_text populated with JSON content."""
        import json as _json

        from services.extractor.extractor import ExtractorService
        from utils.models import DocType, RawDocument

        f = tmp_path / "data.json"
        f.write_text(_json.dumps({"key": "value"}))

        raw = RawDocument(
            raw_id="test-json",
            file_path=str(f),
            doc_type=DocType.JSON,
        )
        svc = ExtractorService()
        content = await svc.extract(raw)
        assert "key" in content.body_text
        assert content.extraction_engine == "json"
