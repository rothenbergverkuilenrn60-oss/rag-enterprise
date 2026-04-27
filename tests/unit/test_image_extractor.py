# =============================================================================
# tests/unit/test_image_extractor.py
# TDD RED — failing tests for image_extractor.py (Plan 04-02)
# =============================================================================
from __future__ import annotations

import io
import struct
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image as PILImage

from utils.models import ExtractedImage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_png_bytes(width: int = 200, height: int = 200) -> bytes:
    """Create a minimal valid PNG in memory."""
    buf = io.BytesIO()
    img = PILImage.new("RGB", (width, height), color=(100, 150, 200))
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_jpeg_bytes(width: int = 200, height: int = 200) -> bytes:
    buf = io.BytesIO()
    img = PILImage.new("RGB", (width, height), color=(200, 100, 50))
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_large_png_bytes(width: int = 2048, height: int = 2048) -> bytes:
    buf = io.BytesIO()
    img = PILImage.new("RGB", (width, height), color=(50, 50, 50))
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests for extract_images_from_pdf
# ---------------------------------------------------------------------------

class TestExtractImagesFromPdf:
    """Tests for the sync extract_images_from_pdf() function."""

    def test_import_succeeds(self):
        from services.extractor.image_extractor import extract_images_from_pdf
        assert callable(extract_images_from_pdf)

    def test_returns_list_type(self, tmp_path):
        """Return type must always be list[ExtractedImage]."""
        from services.extractor.image_extractor import extract_images_from_pdf

        # Create a minimal PDF with no images using fitz
        import fitz
        doc = fitz.open()
        doc.new_page()
        pdf_path = tmp_path / "no_images.pdf"
        doc.save(str(pdf_path))
        doc.close()

        result = extract_images_from_pdf(pdf_path, "test-doc-001")
        assert isinstance(result, list)

    def test_empty_pdf_returns_empty_list(self, tmp_path):
        """A PDF with no images should return [] with no exception."""
        from services.extractor.image_extractor import extract_images_from_pdf

        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Hello world, no images here.")
        pdf_path = tmp_path / "text_only.pdf"
        doc.save(str(pdf_path))
        doc.close()

        result = extract_images_from_pdf(pdf_path, "doc-text-only")
        assert result == []

    def test_small_images_filtered_out(self, tmp_path):
        """Images < 100×100 px must be skipped (D-01)."""
        from services.extractor.image_extractor import extract_images_from_pdf

        # Patch the fitz doc to return a tiny image
        small_img_bytes = _make_png_bytes(50, 50)

        mock_img_tuple = (1, None, 50, 50, None, None, None, None, None)  # xref=1,w=50,h=50

        mock_page = MagicMock()
        mock_page.get_images.return_value = [mock_img_tuple]

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.extract_image.return_value = {"image": small_img_bytes, "ext": "png"}

        with patch("fitz.open", return_value=mock_doc):
            result = extract_images_from_pdf(tmp_path / "fake.pdf", "doc-small")

        assert result == [], "Small images (50×50) must be filtered out"

    def test_large_image_not_filtered(self, tmp_path):
        """Images >= 100×100 and <= 1024 px should NOT be filtered or resized."""
        from services.extractor.image_extractor import extract_images_from_pdf

        normal_bytes = _make_png_bytes(300, 200)
        mock_img_tuple = (1, None, 300, 200, None, None, None, None, None)

        mock_page = MagicMock()
        mock_page.get_images.return_value = [mock_img_tuple]

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.extract_image.return_value = {"image": normal_bytes, "ext": "png"}

        with patch("fitz.open", return_value=mock_doc):
            result = extract_images_from_pdf(tmp_path / "fake.pdf", "doc-normal")

        assert len(result) == 1
        assert result[0].width == 300
        assert result[0].height == 200
        assert isinstance(result[0], ExtractedImage)

    def test_image_cap_at_50(self, tmp_path):
        """No more than 50 images per document (D-02)."""
        from services.extractor.image_extractor import extract_images_from_pdf

        normal_bytes = _make_png_bytes(200, 200)
        # 60 images on one page
        mock_img_tuples = [(i + 1, None, 200, 200, None, None, None, None, None) for i in range(60)]

        mock_page = MagicMock()
        mock_page.get_images.return_value = mock_img_tuples

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.extract_image.return_value = {"image": normal_bytes, "ext": "png"}

        with patch("fitz.open", return_value=mock_doc):
            result = extract_images_from_pdf(tmp_path / "fake.pdf", "doc-many")

        assert len(result) <= 50, f"Got {len(result)} images, cap must be 50"

    def test_oversized_image_resized(self, tmp_path):
        """Images > 1024 px on either dimension must be resized (D-05)."""
        from services.extractor.image_extractor import extract_images_from_pdf

        large_bytes = _make_large_png_bytes(2048, 2048)
        mock_img_tuple = (1, None, 2048, 2048, None, None, None, None, None)

        mock_page = MagicMock()
        mock_page.get_images.return_value = [mock_img_tuple]

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.extract_image.return_value = {"image": large_bytes, "ext": "png"}

        with patch("fitz.open", return_value=mock_doc):
            result = extract_images_from_pdf(tmp_path / "fake.pdf", "doc-large")

        assert len(result) == 1
        assert result[0].width <= 1024
        assert result[0].height <= 1024

    def test_extracted_image_has_correct_fields(self, tmp_path):
        """ExtractedImage must have raw_bytes, page_number, image_index, ext."""
        from services.extractor.image_extractor import extract_images_from_pdf

        normal_bytes = _make_png_bytes(200, 150)
        mock_img_tuple = (1, None, 200, 150, None, None, None, None, None)

        mock_page = MagicMock()
        mock_page.get_images.return_value = [mock_img_tuple]

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.extract_image.return_value = {"image": normal_bytes, "ext": "jpeg"}

        with patch("fitz.open", return_value=mock_doc):
            result = extract_images_from_pdf(tmp_path / "fake.pdf", "doc-fields")

        img = result[0]
        assert isinstance(img.raw_bytes, bytes)
        assert len(img.raw_bytes) > 0
        assert img.page_number == 1
        assert img.image_index == 0
        assert img.ext == "jpeg"

    def test_fitz_open_failure_returns_empty_list(self, tmp_path):
        """If fitz.open raises, return [] gracefully."""
        from services.extractor.image_extractor import extract_images_from_pdf
        import fitz

        with patch("fitz.open", side_effect=RuntimeError("corrupt PDF")):
            result = extract_images_from_pdf(tmp_path / "bad.pdf", "doc-corrupt")

        assert result == []

    def test_no_bare_except_in_module(self):
        """ERR-01: no bare 'except Exception' in image_extractor.py."""
        import ast
        module_path = Path("services/extractor/image_extractor.py")
        if not module_path.exists():
            pytest.skip("image_extractor.py not yet created")
        source = module_path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    pytest.fail("Bare 'except:' found — violates ERR-01")
                if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    pytest.fail("'except Exception' found — violates ERR-01")


# ---------------------------------------------------------------------------
# Tests for ImageExtractorService.extract_standalone
# ---------------------------------------------------------------------------

class TestImageExtractorService:
    """Tests for ImageExtractorService.extract_standalone()."""

    def test_import_succeeds(self):
        from services.extractor.image_extractor import ImageExtractorService, get_image_extractor
        svc = get_image_extractor()
        assert isinstance(svc, ImageExtractorService)

    def test_extract_standalone_png(self, tmp_path):
        """PNG file → ExtractedImage with ext='png'."""
        from services.extractor.image_extractor import get_image_extractor

        png_path = tmp_path / "test.png"
        PILImage.new("RGB", (300, 200)).save(str(png_path), format="PNG")

        svc = get_image_extractor()
        result = svc.extract_standalone(png_path)

        assert isinstance(result, ExtractedImage)
        assert result.ext == "png"
        assert result.width == 300
        assert result.height == 200
        assert result.page_number == 0
        assert result.image_index == 0
        assert len(result.raw_bytes) > 0

    def test_extract_standalone_jpeg(self, tmp_path):
        """JPEG file → ExtractedImage."""
        from services.extractor.image_extractor import get_image_extractor

        jpg_path = tmp_path / "photo.jpg"
        PILImage.new("RGB", (400, 300)).save(str(jpg_path), format="JPEG")

        svc = get_image_extractor()
        result = svc.extract_standalone(jpg_path)

        assert isinstance(result, ExtractedImage)
        assert result.ext == "png"  # always saves as PNG

    def test_extract_standalone_webp(self, tmp_path):
        """WEBP file → ExtractedImage."""
        from services.extractor.image_extractor import get_image_extractor

        webp_path = tmp_path / "image.webp"
        PILImage.new("RGB", (200, 200)).save(str(webp_path), format="WEBP")

        svc = get_image_extractor()
        result = svc.extract_standalone(webp_path)

        assert isinstance(result, ExtractedImage)
        assert result.ext == "png"

    def test_extract_standalone_unsupported_format_raises(self, tmp_path):
        """Unsupported format raises ValueError."""
        from services.extractor.image_extractor import get_image_extractor

        bmp_path = tmp_path / "image.bmp"
        PILImage.new("RGB", (100, 100)).save(str(bmp_path), format="BMP")

        svc = get_image_extractor()
        with pytest.raises(ValueError, match="Unsupported image format"):
            svc.extract_standalone(bmp_path)

    def test_extract_standalone_large_image_resized(self, tmp_path):
        """Large standalone image > 1024 px is resized."""
        from services.extractor.image_extractor import get_image_extractor

        large_path = tmp_path / "large.png"
        PILImage.new("RGB", (2000, 1500)).save(str(large_path), format="PNG")

        svc = get_image_extractor()
        result = svc.extract_standalone(large_path)

        assert result.width <= 1024
        assert result.height <= 1024

    def test_extract_standalone_small_image_not_resized(self, tmp_path):
        """Small standalone image <= 1024 px is NOT resized."""
        from services.extractor.image_extractor import get_image_extractor

        small_path = tmp_path / "small.png"
        PILImage.new("RGB", (200, 150)).save(str(small_path), format="PNG")

        svc = get_image_extractor()
        result = svc.extract_standalone(small_path)

        assert result.width == 200
        assert result.height == 150
