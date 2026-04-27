# =============================================================================
# services/extractor/ocr_engine.py — Phase 7 OCR-01 / OCR-02
#
# Hosts the PP-StructureV3 process-singleton, the asyncio.to_thread + Semaphore
# plumbing, and a small Protocol so the extractor layer never imports paddleocr
# directly. The Tesseract path is preserved as a fallback adapter — its body
# (services.extractor.extractor._extract_pdf_scanned_tesseract) stays untouched.
#
# Decisions (locked in 07-01-PLAN.md):
#   * Singleton via functools.lru_cache(maxsize=1)
#   * Sync invocation wrapped in asyncio.to_thread to keep the event loop free
#   * Module-level asyncio.Semaphore(settings.ocr_concurrency) caps OCR
#     concurrency independently of WorkerSettings.max_jobs (=10 ARQ jobs)
#   * Tesseract adapter wraps the existing function — minimum diff
# =============================================================================
from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from loguru import logger

from config.settings import settings


# ── Module-level concurrency gate ────────────────────────────────────────────
# Created lazily so import order does not bind the Semaphore to the wrong
# event loop. asyncio.Semaphore is loop-agnostic in modern CPython, but we
# stay defensive and lazy-init on first use.
_sem: asyncio.Semaphore | None = None


def _semaphore() -> asyncio.Semaphore:
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(settings.ocr_concurrency)
    return _sem


# ── Engine Protocol ──────────────────────────────────────────────────────────
class OcrEngine(Protocol):
    """Async OCR engine contract.

    Implementations return the dict shape consumed by
    ExtractorService.extract() (services/extractor/extractor.py:614+):

        {
            "body_text":  str,
            "tables":     list[dict],
            "pages":      int,
            "title":      str,
            "engine":     str,
            # OPTIONAL: "extraction_errors": list[str]
        }
    """

    name: str

    async def extract_pdf(self, file_path: Path) -> dict[str, Any]: ...


# ── PP-StructureV3 (primary engine) ──────────────────────────────────────────
@lru_cache(maxsize=1)
def _paddle_pipeline() -> Any:
    """Process-singleton PP-StructureV3.

    First call triggers model download into ~/.paddlex/official_models/
    (~600MB–1.2GB). Subsequent calls reuse the in-memory pipeline.
    Plan 02 pre-warms this in the ARQ worker startup hook so live ingest
    does not pay the 5–15s cold-start cost.
    """
    from paddleocr import PPStructureV3  # local import: optional dep
    logger.info("[OCR] Initializing PP-StructureV3 singleton (first call)")
    return PPStructureV3(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        lang="ch",
    )


class PpStructureV3Engine:
    """Layout-aware OCR via PaddleOCR PP-StructureV3 (text + tables + reading order)."""

    name: str = "ppstructurev3"

    async def extract_pdf(self, file_path: Path) -> dict[str, Any]:
        async with _semaphore():
            return await asyncio.to_thread(self._run_sync, file_path)

    def _run_sync(self, file_path: Path) -> dict[str, Any]:
        results = _paddle_pipeline().predict(input=str(file_path))
        pages_text: list[str] = []
        tables: list[dict[str, Any]] = []

        for page_idx, page in enumerate(results):
            # Per-page text in reading order (markdown_texts).
            page_text = ""
            try:
                md = getattr(page, "markdown", None) or {}
                page_text = md.get("markdown_texts", "") or ""
            except AttributeError:
                page_text = ""
            if page_text.strip():
                pages_text.append(f"[第{page_idx + 1}页·OCR]\n{page_text}")

            # Tables — preserve pred_html so downstream chunker can keep structure.
            try:
                page_json = getattr(page, "json", None) or {}
                table_list = (page_json.get("res") or {}).get("table_res_list", []) or []
                for tbl in table_list:
                    html = tbl.get("pred_html") if isinstance(tbl, dict) else None
                    if html:
                        tables.append({
                            "page": page_idx + 1,
                            "html": html,
                        })
            except (KeyError, AttributeError, TypeError):
                # Defensive: malformed page result must not poison the whole doc.
                pass

        return {
            "body_text": "\n\n".join(pages_text),
            "tables":    tables,
            "pages":     len(pages_text),
            "title":     file_path.stem,
            "engine":    self.name,
        }


# ── Tesseract adapter (fallback engine) ──────────────────────────────────────
class TesseractEngine:
    """Async adapter around the existing sync Tesseract extractor.

    The wrapped function (`_extract_pdf_scanned_tesseract`) is left byte-identical
    in extractor.py — Plan 07-01's principle of minimum diff.
    Bounded by the same semaphore so a Tesseract call and a Paddle call do not
    both saturate the CPU.
    """

    name: str = "tesseract"

    async def extract_pdf(self, file_path: Path) -> dict[str, Any]:
        # Local import avoids a circular import at module load time
        # (extractor.py imports settings; ocr_engine.py imports settings too).
        from services.extractor.extractor import _extract_pdf_scanned_tesseract
        async with _semaphore():
            return await asyncio.to_thread(_extract_pdf_scanned_tesseract, file_path)


# ── Selector ─────────────────────────────────────────────────────────────────
def get_ocr_engine(engine: str | None = None) -> OcrEngine:
    """Select an OCR engine based on settings or an explicit override.

    Args:
        engine: override; defaults to ``settings.ocr_engine``. Accepts
            ``{"auto", "paddle", "tesseract"}``. The ``"none"`` route is
            handled by the caller (extractor) and never reaches this function.

    Returns:
        An ``OcrEngine`` (PpStructureV3Engine | TesseractEngine).

    Behaviour:
        * ``"tesseract"`` → ``TesseractEngine``
        * ``"paddle"``    → ``PpStructureV3Engine`` (raises ImportError on use
          if paddleocr is missing — explicit choice = explicit failure)
        * ``"auto"``      → ``PpStructureV3Engine`` if paddleocr is importable,
          else ``TesseractEngine`` with a clear warning (no silent regression).
    """
    eng = (engine or settings.ocr_engine or "auto").lower()

    if eng == "tesseract":
        return TesseractEngine()
    if eng == "paddle":
        return PpStructureV3Engine()

    # "auto" — probe availability of paddleocr, fall back to Tesseract on miss.
    try:
        import paddleocr  # noqa: F401  — probe only
        return PpStructureV3Engine()
    except ImportError:
        logger.warning(
            "[OCR] PaddleOCR未安装 (paddleocr import failed); "
            "falling back to Tesseract. Install paddlepaddle==3.0.0 + "
            "paddleocr[doc-parser]==3.1.* to enable PP-StructureV3."
        )
        return TesseractEngine()
