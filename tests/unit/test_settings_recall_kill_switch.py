"""Unit tests for Plan 24-01: settings kill-switch field + RecallTool ClassVar presence.

RED gates (Task 1): all three tests fail until Task 2 lands the settings field
and the stub module. GREEN after Task 2.

Tests deferred to Plan 04: importlib.reload registration paths, conditional-import
behavior, and allowlist assertions. Only field-presence and ClassVar-shape are
verified here (MEM-08, MEM-09, D-B4).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")


def test_recall_tool_enabled_default_true() -> None:
    """settings.recall_tool_enabled exists and defaults to True (D-B4 / MEM-09)."""
    from config.settings import settings  # noqa: PLC0415

    assert settings.recall_tool_enabled is True


def test_recall_tool_enabled_is_bool() -> None:
    """Pydantic V2 model_fields introspection: annotation is bool, default True."""
    from config.settings import Settings  # noqa: PLC0415

    field = Settings.model_fields["recall_tool_enabled"]
    assert field.annotation is bool
    assert field.default is True


def test_recall_tool_classvars_present() -> None:
    """RecallTool is importable with correct name, description, and parameters_schema ClassVars.

    Asserts:
    - RecallTool.name == "recall_memory"  (MEM-08)
    - RecallTool.parameters_schema == MEM-08 literal schema
    - D-C4 verbatim description substrings present
    """
    from services.agent.tools.recall import RecallTool  # noqa: PLC0415

    assert RecallTool.name == "recall_memory"
    assert RecallTool.parameters_schema == {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    assert "Recall durable facts" in RecallTool.description
    assert "Skip when conversation pivots" in RecallTool.description
