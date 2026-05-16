"""tests/unit/test_phase25_foundations.py — Phase 25 / Plan 25-01 (RED gates).

Covers the two Wave-1 foundation additions:

  Test 1: ``settings.memory_facts_cap_per_user`` default = 500 (EVICT-01).
  Test 2: field annotation is ``int`` and Pydantic default = 500.
  Test 3: ``Settings(memory_facts_cap_per_user=0)`` raises ``ValidationError``
          (T6 / outside-voice F4 — closes T-25-01-D1 silent total-wipe).
          Also ``=-1`` raises.
  Test 4: ``AuditAction.MEMORY_FORGET.value == "MEMORY_FORGET"`` (D-2.1, GDPR-03).
  Test 5: ``AuditAction.MEMORY_EVICT.value == "MEMORY_EVICT"`` (D-2.1, EVICT-02).

Imports of ``config.settings`` and ``services.audit.audit_service`` are kept
INSIDE test bodies so pytest collection succeeds in RED state without import
errors. Env-var setdefault block mirrors ``tests/unit/test_memory_save_fact.py``.
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest


def test_memory_facts_cap_per_user_default() -> None:
    """settings.memory_facts_cap_per_user defaults to 500 (EVICT-01)."""
    from config.settings import settings

    assert settings.memory_facts_cap_per_user == 500


def test_memory_facts_cap_per_user_is_int() -> None:
    """Field annotation is ``int`` and Pydantic default is 500."""
    from config.settings import Settings

    field = Settings.model_fields["memory_facts_cap_per_user"]
    assert field.annotation is int
    assert field.default == 500


def test_memory_facts_cap_zero_rejected() -> None:
    """T6 / outside-voice F4: Field(ge=1) rejects 0 and negative at settings-load.

    Closes T-25-01-D1 — ConfigMap typo MEMORY_FACTS_CAP_PER_USER=0 would silently
    wipe every long_term_facts row in enforce mode. Pydantic V2 ``Field(ge=1)``
    fails the process at settings-load before any DB write can happen.
    """
    from pydantic import ValidationError

    from config.settings import Settings

    with pytest.raises(ValidationError):
        Settings(memory_facts_cap_per_user=0)
    with pytest.raises(ValidationError):
        Settings(memory_facts_cap_per_user=-1)


def test_audit_action_memory_forget_exists() -> None:
    """AuditAction.MEMORY_FORGET enum value = ``"MEMORY_FORGET"`` (GDPR-03 / D-2.1)."""
    from services.audit.audit_service import AuditAction

    assert AuditAction.MEMORY_FORGET.value == "MEMORY_FORGET"


def test_audit_action_memory_evict_exists() -> None:
    """AuditAction.MEMORY_EVICT enum value = ``"MEMORY_EVICT"`` (EVICT-02 / D-2.1)."""
    from services.audit.audit_service import AuditAction

    assert AuditAction.MEMORY_EVICT.value == "MEMORY_EVICT"
