"""
tests/unit/test_settings_validators.py

Unit tests for Settings validators:
  - JWT secret denylist + minimum length (SEC-01)
  - CORS origins production guard (SEC-04)

All tests import Settings directly (not the singleton) and use monkeypatch
to control environment variables, ensuring complete isolation.
"""
from __future__ import annotations

import sys

import pytest
from pydantic import ValidationError


def _fresh_settings(**overrides):
    """Import a fresh Settings class (not the singleton) and instantiate it.

    Callers must set APP_MODEL_DIR in the environment before calling this.
    """
    # Remove any cached config modules so module-level guards re-execute
    for key in list(sys.modules.keys()):
        if key.startswith("config"):
            del sys.modules[key]

    from config.settings import Settings  # noqa: PLC0415
    return Settings(**overrides)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_SECRET = "a9f3d2e1b8c7f6e5d4c3b2a1f0e9d8c7"  # 32 random mixed chars


# ---------------------------------------------------------------------------
# SEC-01: JWT denylist tests
# ---------------------------------------------------------------------------

class TestJWTDenylist:
    def test_denylist_secret_raises(self, monkeypatch):
        """Settings() with secret_key='secret' must raise ValueError."""
        monkeypatch.setenv("APP_MODEL_DIR", "/tmp")
        monkeypatch.setenv("SECRET_KEY", "secret")
        with pytest.raises((ValidationError, ValueError)):
            _fresh_settings()

    def test_default_secret_raises(self, monkeypatch):
        """Settings() with the default CHANGE-ME secret must raise ValueError."""
        monkeypatch.setenv("APP_MODEL_DIR", "/tmp")
        monkeypatch.setenv("SECRET_KEY", "CHANGE-ME-IN-PRODUCTION-USE-256BIT-KEY")
        with pytest.raises((ValidationError, ValueError)):
            _fresh_settings()

    def test_short_secret_raises(self, monkeypatch):
        """Settings() with a 31-char secret must raise ValueError (too short)."""
        monkeypatch.setenv("APP_MODEL_DIR", "/tmp")
        monkeypatch.setenv("SECRET_KEY", "a" * 31)
        with pytest.raises((ValidationError, ValueError)):
            _fresh_settings()

    def test_repeated_char_secret_raises(self, monkeypatch):
        """Settings() with a 32-char all-same-character secret must raise ValueError."""
        monkeypatch.setenv("APP_MODEL_DIR", "/tmp")
        monkeypatch.setenv("SECRET_KEY", "a" * 32)
        with pytest.raises((ValidationError, ValueError)):
            _fresh_settings()

    def test_valid_secret_passes(self, monkeypatch):
        """Settings() with a 32+ char mixed secret must not raise."""
        monkeypatch.setenv("APP_MODEL_DIR", "/tmp")
        monkeypatch.setenv("SECRET_KEY", VALID_SECRET)
        s = _fresh_settings()
        assert s.secret_key == VALID_SECRET


# ---------------------------------------------------------------------------
# SEC-04: CORS production guard tests
# ---------------------------------------------------------------------------

class TestCORSProductionGuard:
    def test_production_empty_cors_raises(self, monkeypatch):
        """Settings(environment='production', cors_origins=[]) must raise ValueError."""
        monkeypatch.setenv("APP_MODEL_DIR", "/tmp")
        monkeypatch.setenv("SECRET_KEY", VALID_SECRET)
        with pytest.raises((ValidationError, ValueError)):
            _fresh_settings(environment="production", cors_origins=[])

    def test_production_localhost_cors_raises(self, monkeypatch):
        """Settings(environment='production') with localhost CORS must raise ValueError."""
        monkeypatch.setenv("APP_MODEL_DIR", "/tmp")
        monkeypatch.setenv("SECRET_KEY", VALID_SECRET)
        with pytest.raises((ValidationError, ValueError)):
            _fresh_settings(
                environment="production",
                cors_origins=["http://localhost:3000"],
            )

    def test_development_empty_cors_passes(self, monkeypatch):
        """Settings(environment='development', cors_origins=[]) must NOT raise."""
        monkeypatch.setenv("APP_MODEL_DIR", "/tmp")
        monkeypatch.setenv("SECRET_KEY", VALID_SECRET)
        s = _fresh_settings(environment="development", cors_origins=[])
        assert s.cors_origins == []
