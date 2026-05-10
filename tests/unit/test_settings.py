"""Smoke tests for top-level Settings defaults (Phase 21+).

Mirrors the pattern of `tests/unit/test_settings_ocr.py`: import the canonical
`settings` singleton and assert its declared defaults. Env-var override behavior
is provided by Pydantic-Settings itself and is not re-asserted here.
"""
from __future__ import annotations


def test_verifier_settings_default_none() -> None:
    """Phase 21 AGENT-05 — verifier_model and verifier_provider both default to None.

    Both `None` defaults force Verifier._resolve_llm() into the get_llm_client()
    fallback branch (Plan 21-03 / 21-RESEARCH.md Pitfall P-09 default branch).
    A future regression that flips the default would silently re-route every
    swarm verifier call to a hard-coded provider.
    """
    from config.settings import settings
    assert settings.verifier_model is None
    assert settings.verifier_provider is None
