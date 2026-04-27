"""End-to-end OCR integration test — Phase 7 OCR-01 acceptance #5.

Verifies that ingesting `data/raw/GB4785-2019.pdf` through the real
ExtractorService → PP-StructureV3 path produces non-empty body_text with at
least one CJK character.

This test is gated by:

  * ``@pytest.mark.integration`` — excluded from default unit runs (see
    pytest.ini), invoked only via ``pytest -m integration``.
  * ``importlib.util.find_spec('paddleocr')`` — skips cleanly when
    PaddleOCR is not installed (i.e. unit-only dev environments).
  * ``Path('data/raw/GB4785-2019.pdf').exists()`` — skips when the test
    fixture is absent (e.g. minimal CI runners).

Inside the built Docker image (``rag-enterprise:phase7-test``) all three
preconditions are satisfied; the test must pass with chars > 0 and a CJK
character present in the output.

This test does NOT exercise the LLM client — image-caption-style downstream
work is orthogonal. We exercise only the extraction layer that OCR-01/02
target.
"""
from __future__ import annotations

import importlib.util
import re
import time
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Skip gating — guard against unit-only environments
# ──────────────────────────────────────────────────────────────────────────────
_PADDLEOCR_AVAILABLE = importlib.util.find_spec("paddleocr") is not None
_GB_PDF = Path("data/raw/GB4785-2019.pdf")
_PDF_AVAILABLE = _GB_PDF.exists()

_CJK_RE = re.compile(r"[一-鿿]")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _PADDLEOCR_AVAILABLE,
        reason="paddleocr not installed; run inside the built Docker image",
    ),
    pytest.mark.skipif(
        not _PDF_AVAILABLE,
        reason=f"fixture {_GB_PDF} not available on this host",
    ),
]


@pytest.mark.asyncio
async def test_ocr_e2e_gb4785_produces_non_empty_chinese_text() -> None:
    """OCR-01 acceptance #5 — chars > 0 + at least one CJK character.

    Wall-clock time is recorded for the SUMMARY's per-page latency record.
    A loose ceiling (5 × ocr_timeout_sec × pages) confirms the timeout/retry
    logic is not infinite-looping.
    """
    from config.settings import settings
    from services.extractor.extractor import get_extractor
    from utils.models import DocType, RawDocument

    extractor = get_extractor()
    raw = RawDocument(
        file_path=str(_GB_PDF.resolve()),
        doc_type=DocType.PDF,
    )

    start = time.time()
    extracted = await extractor.extract(raw)
    elapsed = time.time() - start

    # OCR-01 acceptance #5: non-empty body_text.
    assert len(extracted.body_text) > 0, \
        "ExtractedContent.body_text is empty — OCR did not produce text"

    # Sanity: the PaddleOCR path actually ran on a Chinese GB doc, not the
    # empty-text Tesseract failure mode.
    assert _CJK_RE.search(extracted.body_text), \
        "no CJK characters in OCR output — engine likely returned empty string"

    # Timeout/retry logic is not infinite-looping.
    pages = max(extracted.pages, 1)
    ceiling_sec = 5 * settings.ocr_timeout_sec * pages
    assert elapsed < ceiling_sec, \
        f"extract took {elapsed:.1f}s, exceeded ceiling {ceiling_sec}s for {pages} pages"

    # No timeout-induced failures bubbled into extraction_errors.
    timeout_errors = [
        e for e in extracted.extraction_errors if "timeout" in str(e).lower()
    ]
    assert not timeout_errors, \
        f"extraction_errors contained timeout entries: {timeout_errors}"

    # Record measurements via captured logging; pytest -s surfaces these.
    print(
        f"\n[OCR e2e] file={_GB_PDF.name} pages={extracted.pages} "
        f"chars={len(extracted.body_text)} elapsed={elapsed:.2f}s "
        f"per_page={elapsed / pages:.2f}s engine={extracted.extraction_engine}"
    )
