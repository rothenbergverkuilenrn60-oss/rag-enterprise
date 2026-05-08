"""Tests for OCR-related settings (Phase 7 OCR-02).

Pins:
  - settings.ocr_concurrency default == 2
  - settings.ocr_timeout_sec  default == 120
  - OCR_CONCURRENCY env var override works
  - existing settings.ocr_engine literal still accepts {"auto","paddle","tesseract","none"}
"""
from __future__ import annotations

import importlib

import pytest


def _reload_settings():
    """Reload config.settings so a freshly constructed Settings sees the
    current process environment (handy for env-override tests)."""
    import config.settings as cfg
    importlib.reload(cfg)
    return cfg


def test_ocr_concurrency_default_is_two() -> None:
    from config.settings import settings
    assert settings.ocr_concurrency == 2


def test_ocr_timeout_sec_default_is_120() -> None:
    from config.settings import settings
    assert settings.ocr_timeout_sec == 120


def test_ocr_concurrency_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """OCR_CONCURRENCY env var should override the default."""
    monkeypatch.setenv("OCR_CONCURRENCY", "4")
    from config.settings import Settings
    s = Settings()
    assert s.ocr_concurrency == 4


def test_ocr_engine_literal_still_works() -> None:
    """Sanity: the existing ocr_engine literal accepts all 4 values."""
    from config.settings import Settings
    for value in ("auto", "paddle", "tesseract", "none"):
        s = Settings(ocr_engine=value)  # type: ignore[arg-type]
        assert s.ocr_engine == value
