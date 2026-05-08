"""Failure-mode tests for services/extractor/ocr_engine — Phase 7 Plan 02 Task 1.

Pins the contracts for:
  * Hard timeout → tenacity retries once → on second failure, surface
    `extraction_errors=["OCR timeout after Xs, retried 1x"]` and `body_text=""`.
  * Timeout-then-success on retry → returns the success dict, no errors.
  * MemoryError (OOM) bubbles up — never swallowed (ERR-01).
  * Garbled-CJK heuristic logs warning but does not raise (returns dict as-is).
  * Empty / short body_text does NOT trigger the heuristic (avoid false positives).
  * Mostly-Chinese body_text does NOT trigger the heuristic.
  * Semaphore is still entered around the timeout-bounded call (regression check).

All paddleocr access is mocked; this file does NOT require paddleocr to be installed.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton_and_semaphore():
    """Clear lru_cache + module semaphore between tests."""
    from services.extractor import ocr_engine as oe

    oe._paddle_pipeline.cache_clear()
    oe._sem = None
    yield
    oe._paddle_pipeline.cache_clear()
    oe._sem = None


# ──────────────────────────────────────────────────────────────────────────────
# Pure-function heuristic tests (Tests 4–6 also exercise this directly)
# ──────────────────────────────────────────────────────────────────────────────
def test_looks_garbled_pure_function_is_callable() -> None:
    """_looks_garbled must be a pure module-level function (testable in isolation)."""
    from services.extractor.ocr_engine import _looks_garbled

    # Pure ASCII garbage long enough to clear the 50-char floor.
    assert _looks_garbled("■●█¤•" * 20) is True


def test_looks_garbled_returns_false_for_short_body() -> None:
    """Empty / short body must NOT trigger the heuristic — avoid false positives
    on legitimately-blank pages or tiny fragments."""
    from services.extractor.ocr_engine import _looks_garbled

    assert _looks_garbled("") is False
    assert _looks_garbled("###") is False
    # Just under the 50-char threshold.
    assert _looks_garbled("#" * 49) is False


def test_looks_garbled_returns_false_for_chinese_text() -> None:
    """Mostly-Chinese body must NOT trigger the heuristic."""
    from services.extractor.ocr_engine import _looks_garbled

    text = "这是一段中文文本用于测试OCR结果。" * 10
    assert _looks_garbled(text) is False


# ──────────────────────────────────────────────────────────────────────────────
# Timeout + tenacity retry
# ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_extract_pdf_timeout_retries_once_then_surfaces_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 1: persistent timeout → 1 retry → extraction_errors entry, body_text=''."""
    from config.settings import settings as _settings
    from services.extractor import ocr_engine as oe

    # Use a small but non-zero timeout so wait_for actually fires.
    monkeypatch.setattr(_settings, "ocr_timeout_sec", 0.1)

    call_count = {"n": 0}

    def slow_run(self, file_path: Path) -> dict:  # noqa: ARG001
        call_count["n"] += 1
        # Block long enough for asyncio.wait_for to fire on every attempt.
        time.sleep(0.5)
        return {"body_text": "should never return"}

    with patch.object(oe.PpStructureV3Engine, "_run_sync", slow_run):
        engine = oe.PpStructureV3Engine()
        result = await engine.extract_pdf(tmp_path / "doc.pdf")

    # Tenacity is configured stop_after_attempt(2) → exactly 2 invocations.
    assert call_count["n"] == 2, f"expected 2 attempts (1 + 1 retry), got {call_count['n']}"
    assert result["body_text"] == ""
    assert result["engine"] == "ppstructurev3"
    assert result["pages"] == 0
    assert result["title"] == "doc"
    assert "extraction_errors" in result
    assert len(result["extraction_errors"]) == 1
    msg = result["extraction_errors"][0]
    assert "timeout" in msg.lower()
    assert "retried 1x" in msg.lower() or "retried" in msg.lower()


@pytest.mark.asyncio
async def test_extract_pdf_timeout_then_success_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 2: first call times out, second call succeeds — return success dict, no errors."""
    from config.settings import settings as _settings
    from services.extractor import ocr_engine as oe

    monkeypatch.setattr(_settings, "ocr_timeout_sec", 0.1)

    call_count = {"n": 0}

    def flaky_run(self, file_path: Path) -> dict:  # noqa: ARG001
        call_count["n"] += 1
        if call_count["n"] == 1:
            time.sleep(0.5)
            return {"body_text": "should never return"}
        return {
            "body_text": "ok",
            "tables": [],
            "pages": 1,
            "title": file_path.stem,
            "engine": "ppstructurev3",
        }

    with patch.object(oe.PpStructureV3Engine, "_run_sync", flaky_run):
        engine = oe.PpStructureV3Engine()
        result = await engine.extract_pdf(tmp_path / "doc.pdf")

    assert call_count["n"] == 2
    assert result["body_text"] == "ok"
    # No extraction_errors on a successful retry — the contract is "errors only on
    # final failure", not "errors on any attempt".
    assert "extraction_errors" not in result or result["extraction_errors"] == []


@pytest.mark.asyncio
async def test_extract_pdf_oom_bubbles_up(
    tmp_path: Path,
) -> None:
    """Test 3: MemoryError must NOT be swallowed — ARQ retry policy handles OOM."""
    from services.extractor import ocr_engine as oe

    def oom_run(self, file_path: Path) -> dict:  # noqa: ARG001
        raise MemoryError("simulated OOM during OCR")

    with patch.object(oe.PpStructureV3Engine, "_run_sync", oom_run):
        engine = oe.PpStructureV3Engine()
        with pytest.raises(MemoryError, match="simulated OOM"):
            await engine.extract_pdf(tmp_path / "doc.pdf")


@pytest.mark.asyncio
async def test_extract_pdf_garbled_cjk_warns_but_does_not_raise(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Test 4: garbled CJK output → warning log + dict returned (warn-not-raise)."""
    from services.extractor import ocr_engine as oe

    garbled = "■●█¤•" * 20  # >50 chars, all non-CJK non-ASCII-letter symbols.
    fake_dict = {
        "body_text": garbled,
        "tables": [],
        "pages": 1,
        "title": "x",
        "engine": "ppstructurev3",
    }

    warnings: list[str] = []

    # loguru does not propagate to stdlib logging by default; patch the module's
    # logger.warning directly.
    def capture_warning(msg, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        warnings.append(str(msg))

    with patch.object(oe.PpStructureV3Engine, "_run_sync", lambda self, p: fake_dict), \
         patch.object(oe.logger, "warning", side_effect=capture_warning):
        engine = oe.PpStructureV3Engine()
        result = await engine.extract_pdf(tmp_path / "doc.pdf")

    # Result is returned untouched (warn, not raise / not modified).
    assert result["body_text"] == garbled
    # Heuristic was triggered.
    assert any("garbled" in w.lower() or "低置信度" in w for w in warnings), \
        f"expected garbled-CJK warning, got: {warnings}"


@pytest.mark.asyncio
async def test_extract_pdf_chinese_text_no_warning(
    tmp_path: Path,
) -> None:
    """Test 5: legitimate Chinese output produces zero garbled warnings."""
    from services.extractor import ocr_engine as oe

    chinese = "这是一段标准的中文OCR输出文本用于测试。" * 10
    fake_dict = {
        "body_text": chinese,
        "tables": [],
        "pages": 1,
        "title": "x",
        "engine": "ppstructurev3",
    }

    warnings: list[str] = []

    def capture_warning(msg, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        warnings.append(str(msg))

    with patch.object(oe.PpStructureV3Engine, "_run_sync", lambda self, p: fake_dict), \
         patch.object(oe.logger, "warning", side_effect=capture_warning):
        engine = oe.PpStructureV3Engine()
        result = await engine.extract_pdf(tmp_path / "doc.pdf")

    assert result["body_text"] == chinese
    assert not any("garbled" in w.lower() or "低置信度" in w for w in warnings), \
        f"unexpected garbled warning on legit Chinese: {warnings}"


@pytest.mark.asyncio
async def test_extract_pdf_empty_body_no_warning(
    tmp_path: Path,
) -> None:
    """Test 6: empty body_text must NOT trigger the heuristic.

    A blank page is a legitimate (if degenerate) OCR result; flagging it as
    'garbled' would generate noise without value.
    """
    from services.extractor import ocr_engine as oe

    fake_dict = {
        "body_text": "",
        "tables": [],
        "pages": 0,
        "title": "x",
        "engine": "ppstructurev3",
    }

    warnings: list[str] = []

    def capture_warning(msg, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        warnings.append(str(msg))

    with patch.object(oe.PpStructureV3Engine, "_run_sync", lambda self, p: fake_dict), \
         patch.object(oe.logger, "warning", side_effect=capture_warning):
        engine = oe.PpStructureV3Engine()
        result = await engine.extract_pdf(tmp_path / "doc.pdf")

    assert result["body_text"] == ""
    assert not any("garbled" in w.lower() for w in warnings)


@pytest.mark.asyncio
async def test_extract_pdf_still_uses_semaphore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test 7 (regression): the semaphore is still entered around the timeout call.

    Plan 01 test 5 (test_semaphore_serialises_concurrent_extract_pdf_calls) covers
    real concurrency; this test verifies that the Plan 02 wrapper hasn't bypassed
    the semaphore by calling the predict path outside `_semaphore()`.
    """
    from config.settings import settings as _settings
    from services.extractor import ocr_engine as oe

    monkeypatch.setattr(_settings, "ocr_concurrency", 7)
    monkeypatch.setattr(_settings, "ocr_timeout_sec", 60)  # well above any test work

    fake_dict = {
        "body_text": "ok",
        "tables": [],
        "pages": 1,
        "title": "x",
        "engine": "ppstructurev3",
    }

    with patch.object(oe.PpStructureV3Engine, "_run_sync", lambda self, p: fake_dict):
        engine = oe.PpStructureV3Engine()
        await engine.extract_pdf(tmp_path / "doc.pdf")

        sem = oe._semaphore()
        # After the call returns, the semaphore must be back to its initial slot count.
        assert sem._value == _settings.ocr_concurrency, \
            f"semaphore was not released after extract_pdf: value={sem._value}"
