"""Worker startup hook tests — Phase 7 Plan 02 Task 2 (OCR-02 acceptance #4).

Pins the contracts for ``services.ingest_worker.on_startup`` / ``WorkerSettings.on_startup``:

  * ``WorkerSettings.on_startup`` exists as an attribute and is awaitable.
  * Auto path: when ``settings.ocr_engine == 'auto'`` and paddleocr is importable,
    ``on_startup({})`` calls ``_paddle_pipeline()`` exactly once.
  * Tesseract path: when ``settings.ocr_engine == 'tesseract'``, ``on_startup``
    skips the pre-warm entirely.
  * Paddleocr missing: ``ImportError`` from the inner import is caught and logged;
    ``on_startup`` does NOT raise (worker must boot regardless).
  * No event-loop crash / completes promptly under mock.

All paddleocr access is mocked; this file does NOT require paddleocr to be installed.
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Test 1 — WorkerSettings.on_startup attribute exists and is async-callable
# ──────────────────────────────────────────────────────────────────────────────
def test_worker_settings_has_on_startup_attribute() -> None:
    from services.ingest_worker import WorkerSettings, on_startup

    assert hasattr(WorkerSettings, "on_startup"), \
        "WorkerSettings must expose on_startup so ARQ wires it at boot"
    # The attribute must be the same coroutine function we defined.
    assert WorkerSettings.on_startup is on_startup
    assert inspect.iscoroutinefunction(on_startup), \
        "on_startup must be `async def` — ARQ awaits the hook"


# ──────────────────────────────────────────────────────────────────────────────
# Test 2 — Auto path warms the singleton exactly once
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_on_startup_auto_warms_paddle_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import settings as _settings
    monkeypatch.setattr(_settings, "ocr_engine", "auto")

    # Reset the lru_cache so the test sees a fresh first-call count.
    from services.extractor import ocr_engine as oe
    oe._paddle_pipeline.cache_clear()

    from services.ingest_worker import on_startup

    with patch.object(oe, "_paddle_pipeline") as mock_warmup:
        await on_startup({})

    assert mock_warmup.call_count == 1, \
        f"expected one pre-warm call, got {mock_warmup.call_count}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 3 — Tesseract / none path skips the pre-warm
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_on_startup_tesseract_skips_paddle_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import settings as _settings
    monkeypatch.setattr(_settings, "ocr_engine", "tesseract")

    from services.extractor import ocr_engine as oe
    oe._paddle_pipeline.cache_clear()

    from services.ingest_worker import on_startup

    with patch.object(oe, "_paddle_pipeline") as mock_warmup:
        await on_startup({})

    assert mock_warmup.call_count == 0, \
        "no point pre-warming PaddleOCR when ocr_engine=tesseract"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4 — paddleocr missing → log warning, do not raise
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_on_startup_handles_missing_paddleocr_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import settings as _settings
    monkeypatch.setattr(_settings, "ocr_engine", "auto")

    from services.extractor import ocr_engine as oe
    oe._paddle_pipeline.cache_clear()

    from services.ingest_worker import on_startup

    # Simulate ImportError raised from inside the singleton constructor (which
    # itself does `from paddleocr import PPStructureV3`).
    with patch.object(oe, "_paddle_pipeline", side_effect=ImportError("paddleocr not installed")):
        # Must NOT raise — worker boot must succeed even without PaddleOCR.
        await on_startup({})


# ──────────────────────────────────────────────────────────────────────────────
# Test 5 — Hook completes promptly under mocking (no event-loop hang)
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_on_startup_completes_promptly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from config.settings import settings as _settings
    monkeypatch.setattr(_settings, "ocr_engine", "auto")

    from services.extractor import ocr_engine as oe
    oe._paddle_pipeline.cache_clear()

    from services.ingest_worker import on_startup

    with patch.object(oe, "_paddle_pipeline"):
        await asyncio.wait_for(on_startup({}), timeout=5.0)


# ──────────────────────────────────────────────────────────────────────────────
# Test 6 — Generic Exception (other than ImportError) is logged but not raised
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_on_startup_swallows_unexpected_warmup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If pre-warm crashes for any other reason, the worker must still boot —
    the first real OCR job will surface a clean error via the normal path.

    This is the documented exception to ERR-01: a startup hook where blocking
    boot would harm reliability more than swallowing the error. The code path
    is required to log the exception (not silently swallow it).
    """
    from config.settings import settings as _settings
    monkeypatch.setattr(_settings, "ocr_engine", "auto")

    from services.extractor import ocr_engine as oe
    oe._paddle_pipeline.cache_clear()

    from services.ingest_worker import on_startup

    with patch.object(oe, "_paddle_pipeline", side_effect=RuntimeError("boom")):
        # Must NOT raise.
        await on_startup({})
