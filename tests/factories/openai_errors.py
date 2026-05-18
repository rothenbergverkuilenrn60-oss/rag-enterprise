"""Factory helpers for constructing openai.APIError instances in tests.

Centralises the v1.x SDK signature so a future SDK drift is a one-site fix
instead of an N-site sweep. See REQUIREMENTS.md OAI-01.
"""
from __future__ import annotations

import httpx
from openai import APIError


def make_api_error(
    message: str = "test error",
    *,
    status_code: int = 500,
    request: httpx.Request | None = None,
) -> APIError:
    """Construct an openai.APIError with the v1.x required ``request`` arg.

    See REQUIREMENTS.md OAI-01 (32 latent test failures on master caused by
    openai SDK v1.x introducing ``request`` as a required positional arg).

    Args:
        message: Human-readable error description.
        status_code: HTTP status code to associate with the error.
        request: The ``httpx.Request`` that triggered the error. Defaults to
            a POST to ``https://api.openai.com/v1/chat/completions``.

    Returns:
        An ``openai.APIError`` instance with the correct v1.x shape.
    """
    if request is None:
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return APIError(message=message, request=request, body=None)
