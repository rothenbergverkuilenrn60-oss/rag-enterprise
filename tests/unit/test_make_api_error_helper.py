"""Tests for the make_api_error() factory helper.

Verifies that the helper in tests/factories/openai_errors.py constructs
openai.APIError with the v1.x required ``request`` positional arg — fixing
the 32 latent test failures tracked in REQUIREMENTS.md OAI-01.
"""
from __future__ import annotations

import httpx
from openai import APIError

from tests.factories.openai_errors import make_api_error


class TestMakeApiErrorImport:
    """Test 1: helper is importable and callable."""

    def test_import_and_no_arg_call_returns_api_error(self) -> None:
        """No-arg call returns an openai.APIError instance (import + default construction)."""
        err = make_api_error()
        assert isinstance(err, APIError)


class TestMakeApiErrorSignatureContract:
    """Test 2: signature contract — message and status_code forwarded correctly."""

    def test_message_and_status_code_forwarded(self) -> None:
        """make_api_error('hi', status_code=429).message == 'hi'."""
        err = make_api_error("hi", status_code=429)
        assert err.message == "hi"


class TestMakeApiErrorRequestAttribute:
    """Test 3: .request attribute is present and is an httpx.Request."""

    def test_default_request_is_httpx_request(self) -> None:
        """Default construction sets .request to an httpx.Request (not None)."""
        err = make_api_error()
        assert err.request is not None
        assert isinstance(err.request, httpx.Request)

    def test_explicit_request_override(self) -> None:
        """Caller-supplied request is passed through unchanged."""
        custom_req = httpx.Request("GET", "https://example.com/api")
        err = make_api_error("override", request=custom_req)
        assert err.request is custom_req
