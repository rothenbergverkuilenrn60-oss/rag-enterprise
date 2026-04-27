# =============================================================================
# services/extractor/image_extractor.py
# Stage 2 — Image extraction from PDF pages and standalone image files
# =============================================================================
from __future__ import annotations

import io
from pathlib import Path

from loguru import logger
from PIL import Image

# T-04-02-02: Guard against decompression bombs (50 MP limit)
Image.MAX_IMAGE_PIXELS = 50_000_000

from utils.models import ExtractedImage

_MAX_IMAGES_PER_DOC = 50
_MIN_DIMENSION_PX = 100
_MAX_DIMENSION_PX = 1024


def extract_images_from_pdf(file_path: Path, doc_id: str) -> list[ExtractedImage]:
    """
    Sync function — call via run_in_executor.
    Extracts qualifying images from a PDF using PyMuPDF.
    Filters: width/height < 100 px skipped silently (D-01).
    Cap: first 50 images only (D-02).
    Resize: images > 1024 px on either side are thumbnail-resized in memory (D-05).
    Returns empty list for PDFs with no qualifying images (no error raised).
    """
    import fitz

    extracted: list[ExtractedImage] = []
    total_found = 0

    try:
        doc = fitz.open(str(file_path))
    except (RuntimeError, fitz.FileDataError) as exc:
        logger.warning(f"[ImageExtract] fitz.open failed: doc_id={doc_id} exc={exc}")
        return []

    try:
        for page_idx in range(doc.page_count):
            if len(extracted) >= _MAX_IMAGES_PER_DOC:
                logger.warning(
                    f"[ImageExtract] cap reached: doc_id={doc_id} "
                    f"total_found={total_found} limit={_MAX_IMAGES_PER_DOC}"
                )
                break

            page = doc[page_idx]
            img_list = page.get_images(full=True)

            for img_idx, img_tuple in enumerate(img_list):
                total_found += 1
                xref = img_tuple[0]
                w    = img_tuple[2]
                h    = img_tuple[3]

                # D-01: filter small/decorative images
                if w < _MIN_DIMENSION_PX or h < _MIN_DIMENSION_PX:
                    logger.debug(
                        f"[ImageExtract] skip small: doc_id={doc_id} "
                        f"page={page_idx+1} idx={img_idx} size={w}x{h}"
                    )
                    continue

                if len(extracted) >= _MAX_IMAGES_PER_DOC:
                    logger.warning(
                        f"[ImageExtract] cap reached mid-page: doc_id={doc_id} "
                        f"total_found={total_found} limit={_MAX_IMAGES_PER_DOC}"
                    )
                    break

                try:
                    img_info  = doc.extract_image(xref)
                    raw_bytes: bytes = img_info["image"]
                    ext: str         = img_info.get("ext", "png")

                    # D-05: resize if either dimension exceeds 1024 px
                    if w > _MAX_DIMENSION_PX or h > _MAX_DIMENSION_PX:
                        raw_bytes, w, h = _resize_image(raw_bytes)
                        ext = "png"

                    extracted.append(ExtractedImage(
                        raw_bytes=raw_bytes,
                        width=w,
                        height=h,
                        page_number=page_idx + 1,
                        image_index=img_idx,
                        ext=ext,
                    ))
                except (RuntimeError, KeyError, OSError) as exc:
                    logger.warning(
                        f"[ImageExtract] extract_image failed: doc_id={doc_id} "
                        f"page={page_idx+1} xref={xref} exc={exc}"
                    )
    finally:
        doc.close()

    logger.info(
        f"[ImageExtract] done: doc_id={doc_id} extracted={len(extracted)} "
        f"total_found={total_found}"
    )
    return extracted


def _resize_image(raw_bytes: bytes) -> tuple[bytes, int, int]:
    """Resize image in-memory to fit within 1024×1024, preserving aspect ratio."""
    with Image.open(io.BytesIO(raw_bytes)) as img:
        img.thumbnail((_MAX_DIMENSION_PX, _MAX_DIMENSION_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), img.width, img.height


class ImageExtractorService:
    """Extracts a single ExtractedImage from a standalone image file (jpg/png/webp)."""

    _SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}

    def extract_standalone(self, file_path: Path) -> ExtractedImage:
        """
        Load a standalone image file, optionally resize, return ExtractedImage.
        Raises ValueError for unsupported formats.
        """
        if file_path.suffix.lower() not in self._SUPPORTED:
            raise ValueError(f"Unsupported image format: {file_path.suffix}")

        try:
            with Image.open(str(file_path)) as img:
                img = img.convert("RGB")  # normalise mode (handles RGBA, P, etc.)
                w, h = img.width, img.height
                if w > _MAX_DIMENSION_PX or h > _MAX_DIMENSION_PX:
                    img.thumbnail((_MAX_DIMENSION_PX, _MAX_DIMENSION_PX), Image.LANCZOS)
                    w, h = img.width, img.height
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                raw_bytes = buf.getvalue()
        except (OSError, ValueError) as exc:
            raise ValueError(f"Failed to open image {file_path.name}: {exc}") from exc

        return ExtractedImage(
            raw_bytes=raw_bytes,
            width=w,
            height=h,
            page_number=0,
            image_index=0,
            ext="png",
        )


def get_image_extractor() -> ImageExtractorService:
    return ImageExtractorService()
