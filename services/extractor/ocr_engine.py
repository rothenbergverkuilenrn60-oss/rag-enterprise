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
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from loguru import logger
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)

from config.settings import settings

# ── Garbled-CJK heuristic ────────────────────────────────────────────────────
# Triggered when the document was expected Chinese (lang='ch') but the OCR output
# is mostly non-CJK noise. Per CONTEXT.md / RESEARCH.md: warn-not-raise.
# Skip empty / very short bodies to avoid false positives on blank pages.
_CJK_RE = re.compile(r"[一-鿿]")
_ASCII_RE = re.compile(r"[\x20-\x7e]")
_GARBLED_MIN_LEN = 50


def _looks_garbled(body_text: str) -> bool:
    """Detect probable PaddleOCR garbled output for a CJK document.

    Returns True when:
      * body_text length >= 50 chars (avoids false positives on tiny snippets), AND
      * ASCII printable ratio < 5% (so it isn't legitimate English content), AND
      * CJK character ratio < 30% (so it isn't legitimate Chinese content).

    Pure function; no side effects. Safe to call from tests directly.
    """
    if not body_text or len(body_text) < _GARBLED_MIN_LEN:
        return False
    total = len(body_text)
    cjk_ratio = len(_CJK_RE.findall(body_text)) / total
    ascii_ratio = len(_ASCII_RE.findall(body_text)) / total
    return ascii_ratio < 0.05 and cjk_ratio < 0.30


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
    from paddleocr import PPStructureV3  # type: ignore[import-not-found]  # why: paddleocr has no stubs as of 2026-05; local import: optional dep
    logger.info("[OCR] Initializing PP-StructureV3 singleton (first call)")
    # paddleocr 3.1.x dropped the `lang` kwarg from PPStructureV3 (now controlled via config / model selection);
    # default Chinese support is built in for the layout/table sub-pipelines.
    return PPStructureV3(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )


class PpStructureV3Engine:
    """Layout-aware OCR via PaddleOCR PP-StructureV3 (text + tables + reading order)."""

    name: str = "ppstructurev3"

    async def extract_pdf(self, file_path: Path) -> dict[str, Any]:
        """Run OCR with bounded concurrency, hard timeout, and retry-once.

        Failure modes (per Phase 7 CONTEXT.md):
          * ``asyncio.TimeoutError`` — ``asyncio.wait_for(timeout=ocr_timeout_sec)``
            triggers. Tenacity retries exactly once after a 1s wait. On the second
            timeout the function returns a result dict with ``body_text=""`` and
            ``extraction_errors=["OCR timeout after Xs, retried 1x"]`` — surfacing
            via the existing ``IngestionResponse.extraction_errors`` channel.
          * ``MemoryError`` — bubbles up. ARQ's retry policy + worker max_jobs cap
            handles OOM at the platform layer; we deliberately do not catch it.
          * Garbled CJK output — detected via ``_looks_garbled``. Logs a warning;
            does not raise or modify the result (warn-not-raise per CONTEXT).

        Note: no broad ``except`` is used — ERR-01 forbids them, and OOM must
        propagate. Only ``asyncio.TimeoutError`` is caught for the retry policy.
        """
        timeout = settings.ocr_timeout_sec

        async def _attempt() -> dict[str, Any]:
            async with _semaphore():
                return await asyncio.wait_for(
                    asyncio.to_thread(self._run_sync, file_path),
                    timeout=timeout,
                )

        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(asyncio.TimeoutError),
                stop=stop_after_attempt(2),  # 1 try + 1 retry
                wait=wait_fixed(1),
                reraise=True,
            ):
                with attempt:
                    result = await _attempt()
        except asyncio.TimeoutError:
            logger.error(
                f"[OCR] timeout after {timeout}s on {file_path.name}, "
                f"retried 1x — surfacing in extraction_errors"
            )
            return {
                "body_text": "",
                "tables": [],
                "pages": 0,
                "title": file_path.stem,
                "engine": self.name,
                "extraction_errors": [
                    f"OCR timeout after {timeout}s, retried 1x"
                ],
            }
        # MemoryError and any other exception types are NOT caught here — they
        # propagate to ARQ which handles retries / worker restart.

        # Garbled-CJK heuristic — warn only, do not raise or modify result.
        if _looks_garbled(result.get("body_text", "")):
            logger.warning(
                f"[OCR] {file_path.name}: output looks garbled "
                f"(low CJK + low ASCII ratio) — flagging for review"
            )
        return result

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
