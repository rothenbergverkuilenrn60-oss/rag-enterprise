"""Unit tests for services/extractor/ocr_engine — Phase 7 OCR-01/02.

All paddleocr access is mocked; this test file does NOT require paddleocr to be
installed. The Docker bake (Plan 02) is what makes paddleocr actually importable
at runtime — this file only pins the engine-abstraction contracts.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _fake_page(text: str, table_html: str | None = None) -> MagicMock:
    """Build a fake PP-StructureV3 per-page result object with .markdown / .json."""
    page = MagicMock()
    page.markdown = {"markdown_texts": text}
    page.json = {
        "res": {
            "parsing_res_list": [],
            "table_res_list": ([{"pred_html": table_html}] if table_html else []),
        }
    }
    return page


def _install_fake_paddleocr() -> None:
    """Install a minimal stand-in paddleocr module so `import paddleocr` succeeds.

    Keeps PPStructureV3 patchable from outside; tests that need the real
    constructor mock should patch services.extractor.ocr_engine._paddle_pipeline
    directly to avoid coupling to this stub.
    """
    if "paddleocr" in sys.modules and not isinstance(
        sys.modules["paddleocr"], types.SimpleNamespace
    ):
        return
    fake = types.ModuleType("paddleocr")
    fake.PPStructureV3 = MagicMock(return_value=MagicMock())
    sys.modules["paddleocr"] = fake


@pytest.fixture(autouse=True)
def _reset_singleton_and_semaphore():
    """Clear the lru_cache + module semaphore between tests so they don't bleed."""
    from services.extractor import ocr_engine as oe

    oe._paddle_pipeline.cache_clear()
    oe._sem = None
    yield
    oe._paddle_pipeline.cache_clear()
    oe._sem = None


# ──────────────────────────────────────────────────────────────────────────────
# Singleton + selector
# ──────────────────────────────────────────────────────────────────────────────
def test_paddle_pipeline_is_singleton() -> None:
    _install_fake_paddleocr()
    from services.extractor import ocr_engine as oe

    ctor = MagicMock(return_value=MagicMock())
    with patch.object(sys.modules["paddleocr"], "PPStructureV3", ctor):
        a = oe._paddle_pipeline()
        b = oe._paddle_pipeline()
        assert a is b
        assert ctor.call_count == 1


def test_get_ocr_engine_paddle_returns_pp_structure() -> None:
    _install_fake_paddleocr()
    from services.extractor.ocr_engine import (
        PpStructureV3Engine,
        get_ocr_engine,
    )
    eng = get_ocr_engine("paddle")
    assert isinstance(eng, PpStructureV3Engine)


def test_get_ocr_engine_auto_with_paddleocr_returns_pp_structure() -> None:
    _install_fake_paddleocr()
    from services.extractor.ocr_engine import (
        PpStructureV3Engine,
        get_ocr_engine,
    )
    eng = get_ocr_engine("auto")
    assert isinstance(eng, PpStructureV3Engine)


def test_get_ocr_engine_auto_falls_back_to_tesseract_when_paddleocr_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from services.extractor.ocr_engine import (
        TesseractEngine,
        get_ocr_engine,
    )

    # Force ImportError on `import paddleocr`
    saved = sys.modules.pop("paddleocr", None)
    try:
        with patch.dict(sys.modules, {"paddleocr": None}):
            eng = get_ocr_engine("auto")
        assert isinstance(eng, TesseractEngine)
    finally:
        if saved is not None:
            sys.modules["paddleocr"] = saved


def test_get_ocr_engine_explicit_tesseract_always_returns_tesseract() -> None:
    from services.extractor.ocr_engine import (
        TesseractEngine,
        get_ocr_engine,
    )
    # Even if paddleocr is installed, "tesseract" must be honoured.
    _install_fake_paddleocr()
    eng = get_ocr_engine("tesseract")
    assert isinstance(eng, TesseractEngine)


# ──────────────────────────────────────────────────────────────────────────────
# Async / Semaphore
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pp_structure_extract_pdf_uses_to_thread_and_returns_dict(
    tmp_path: Path,
) -> None:
    _install_fake_paddleocr()
    from services.extractor import ocr_engine as oe

    fake_pages = [
        _fake_page("第一页正文", table_html="<table><tr><td>A</td></tr></table>"),
        _fake_page("第二页正文"),
    ]
    fake_pipeline = MagicMock()
    fake_pipeline.predict = MagicMock(return_value=fake_pages)

    with patch.object(oe, "_paddle_pipeline", lambda: fake_pipeline):
        engine = oe.PpStructureV3Engine()
        result = await engine.extract_pdf(tmp_path / "doc.pdf")

    assert result["engine"] == "ppstructurev3"
    assert "第一页正文" in result["body_text"]
    assert "第二页正文" in result["body_text"]
    assert result["pages"] == 2
    assert result["title"] == "doc"
    assert len(result["tables"]) == 1
    assert "<table>" in result["tables"][0]["html"]


@pytest.mark.asyncio
async def test_semaphore_serialises_concurrent_extract_pdf_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ocr_concurrency=1, two concurrent extract_pdf calls must enter
    the predict() critical section sequentially (not interleaved)."""
    _install_fake_paddleocr()
    from config.settings import settings as _settings
    monkeypatch.setattr(_settings, "ocr_concurrency", 1)

    from services.extractor import ocr_engine as oe

    in_flight = 0
    max_in_flight = 0
    enter = asyncio.Event()
    release = asyncio.Event()

    def slow_predict(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        # Signal first arrival; block until released so the second call would
        # overlap if the semaphore were not enforcing serial entry.
        try:
            enter.set()
            # Tight, bounded wait so we don't deadlock if the semaphore is broken
            import time
            for _ in range(20):
                if release.is_set():
                    break
                time.sleep(0.01)
        finally:
            in_flight -= 1
        return [_fake_page("ok")]

    fake_pipeline = MagicMock()
    fake_pipeline.predict = slow_predict

    with patch.object(oe, "_paddle_pipeline", lambda: fake_pipeline):
        engine = oe.PpStructureV3Engine()

        async def _runner(name: str):
            return await engine.extract_pdf(tmp_path / f"{name}.pdf")

        # Kick off two concurrent calls.
        t1 = asyncio.create_task(_runner("a"))
        t2 = asyncio.create_task(_runner("b"))
        # Wait until the first one is inside predict(), then release.
        await enter.wait()
        release.set()
        r1, r2 = await asyncio.gather(t1, t2)

    assert max_in_flight == 1, "Semaphore did not serialise concurrent OCR calls"
    assert r1["engine"] == r2["engine"] == "ppstructurev3"


# ──────────────────────────────────────────────────────────────────────────────
# Tesseract adapter
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_tesseract_engine_delegates_to_existing_function(
    tmp_path: Path,
) -> None:
    from services.extractor import ocr_engine as oe

    fake_dict = {
        "body_text": "tesseract output",
        "tables": [],
        "pages": 1,
        "title": "x",
        "engine": "tesseract(scanned)",
    }
    with patch(
        "services.extractor.extractor._extract_pdf_scanned_tesseract",
        return_value=fake_dict,
    ) as mocked:
        engine = oe.TesseractEngine()
        result = await engine.extract_pdf(tmp_path / "x.pdf")

    assert result == fake_dict
    mocked.assert_called_once()
