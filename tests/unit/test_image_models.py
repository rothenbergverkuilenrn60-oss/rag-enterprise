# =============================================================================
# tests/unit/test_image_models.py
# TDD RED phase — tests for image extraction model additions (Plan 04-01)
# =============================================================================
"""
Tests for:
  - ExtractedImage model (new)
  - ExtractedContent.images field + model_post_init auto-count
  - ChunkMetadata.chunk_type and image_b64 fields
  - IngestionResponse.extraction_errors field
  - DocType.IMAGE enum member
"""
import pytest


# ---------------------------------------------------------------------------
# DocType.IMAGE
# ---------------------------------------------------------------------------

def test_doctype_image_exists() -> None:
    from utils.models import DocType
    assert DocType.IMAGE == "image"


def test_doctype_image_is_str() -> None:
    from utils.models import DocType
    assert isinstance(DocType.IMAGE, str)


# ---------------------------------------------------------------------------
# ExtractedImage
# ---------------------------------------------------------------------------

def test_extracted_image_importable() -> None:
    from utils.models import ExtractedImage  # noqa: F401


def test_extracted_image_required_fields() -> None:
    from utils.models import ExtractedImage
    img = ExtractedImage(raw_bytes=b"abc", width=100, height=80, page_number=1, image_index=0)
    assert img.raw_bytes == b"abc"
    assert img.width == 100
    assert img.height == 80
    assert img.page_number == 1
    assert img.image_index == 0


def test_extracted_image_default_ext() -> None:
    from utils.models import ExtractedImage
    img = ExtractedImage(raw_bytes=b"x")
    assert img.ext == "png"


def test_extracted_image_custom_ext() -> None:
    from utils.models import ExtractedImage
    img = ExtractedImage(raw_bytes=b"x", ext="jpeg")
    assert img.ext == "jpeg"


def test_extracted_image_default_dimensions_zero() -> None:
    from utils.models import ExtractedImage
    img = ExtractedImage(raw_bytes=b"x")
    assert img.width == 0
    assert img.height == 0
    assert img.page_number == 0
    assert img.image_index == 0


# ---------------------------------------------------------------------------
# ExtractedContent.images + model_post_init
# ---------------------------------------------------------------------------

def test_extracted_content_images_field_exists() -> None:
    from utils.models import ExtractedContent
    ec = ExtractedContent(raw_id="r1")
    assert ec.images == []


def test_extracted_content_images_count_auto_set() -> None:
    from utils.models import ExtractedContent, ExtractedImage
    img = ExtractedImage(raw_bytes=b"data", width=200, height=150, page_number=2, image_index=0)
    ec = ExtractedContent(raw_id="r1", images=[img])
    assert ec.images_count == 1


def test_extracted_content_images_count_not_overridden_when_explicit() -> None:
    """If images_count is set explicitly (non-zero), model_post_init must NOT overwrite it."""
    from utils.models import ExtractedContent, ExtractedImage
    img = ExtractedImage(raw_bytes=b"data")
    ec = ExtractedContent(raw_id="r1", images=[img], images_count=5)
    assert ec.images_count == 5


def test_extracted_content_multiple_images_count() -> None:
    from utils.models import ExtractedContent, ExtractedImage
    imgs = [ExtractedImage(raw_bytes=bytes([i])) for i in range(3)]
    ec = ExtractedContent(raw_id="r1", images=imgs)
    assert ec.images_count == 3
    assert len(ec.images) == 3


def test_extracted_content_existing_fields_intact() -> None:
    """Ensure no regression on existing ExtractedContent fields."""
    from utils.models import ExtractedContent, DocType
    ec = ExtractedContent(
        raw_id="r2",
        doc_type=DocType.PDF,
        title="T",
        body_text="hello",
        pages=3,
    )
    assert ec.doc_type == DocType.PDF
    assert ec.title == "T"
    assert ec.body_text == "hello"
    assert ec.pages == 3


# ---------------------------------------------------------------------------
# ChunkMetadata.chunk_type + image_b64
# ---------------------------------------------------------------------------

def test_chunk_metadata_chunk_type_default() -> None:
    from utils.models import ChunkMetadata
    cm = ChunkMetadata()
    assert cm.chunk_type == "text"


def test_chunk_metadata_image_b64_default() -> None:
    from utils.models import ChunkMetadata
    cm = ChunkMetadata()
    assert cm.image_b64 == ""


def test_chunk_metadata_chunk_type_image() -> None:
    from utils.models import ChunkMetadata
    cm = ChunkMetadata(chunk_type="image", image_b64="aGVsbG8=")
    assert cm.chunk_type == "image"
    assert cm.image_b64 == "aGVsbG8="


def test_chunk_metadata_existing_fields_intact() -> None:
    from utils.models import ChunkMetadata, DocType
    cm = ChunkMetadata(source="s", doc_id="d", chunk_index=2, doc_type=DocType.PDF)
    assert cm.source == "s"
    assert cm.doc_id == "d"
    assert cm.chunk_index == 2
    assert cm.doc_type == DocType.PDF


# ---------------------------------------------------------------------------
# IngestionResponse.extraction_errors
# ---------------------------------------------------------------------------

def test_ingestion_response_extraction_errors_default() -> None:
    from utils.models import IngestionResponse
    ir = IngestionResponse(doc_id="d1")
    assert ir.extraction_errors == []


def test_ingestion_response_extraction_errors_populated() -> None:
    from utils.models import IngestionResponse
    ir = IngestionResponse(doc_id="d1", extraction_errors=["page 3: corrupt image"])
    assert ir.extraction_errors == ["page 3: corrupt image"]


def test_ingestion_response_existing_fields_intact() -> None:
    from utils.models import IngestionResponse
    ir = IngestionResponse(doc_id="d2", total_chunks=10, success=True, elapsed_ms=42.0)
    assert ir.doc_id == "d2"
    assert ir.total_chunks == 10
    assert ir.success is True
    assert ir.elapsed_ms == 42.0


# ---------------------------------------------------------------------------
# ExtractedImage appears BEFORE ExtractedContent in file (forward ref check)
# ---------------------------------------------------------------------------

def test_extracted_image_defined_before_extracted_content() -> None:
    """Verify no forward-reference issue: ExtractedContent.images uses ExtractedImage directly."""
    import inspect
    import utils.models as m
    source = inspect.getsource(m)
    idx_img = source.index("class ExtractedImage")
    idx_ec = source.index("class ExtractedContent")
    assert idx_img < idx_ec, "ExtractedImage must be defined before ExtractedContent"
