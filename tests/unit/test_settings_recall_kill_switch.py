"""Unit tests for Plans 24-01 + 24-04: settings kill-switch field + RecallTool ClassVar
presence (Plan 01) and importlib.reload-based kill-switch behavior (Plan 04).

RED gates (Task 1 / 24-01): first 3 tests fail until Task 2 of Plan 01 lands the
settings field and the stub module. GREEN after Plan 01 Task 2.

RED gates (Task 1 / 24-04): tests 4-8 fail until Plan 04 Task 2 lands the conditional
registration in services/agent/tools/__init__.py.

Tests deferred to Plan 04: importlib.reload registration paths, conditional-import
behavior, and allowlist assertions (MEM-08, MEM-09, D-B4).
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest

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


# ──────────────────────────────────────────────────────────────────────────────
# Plan 24-04 kill-switch reload tests (RED until Plan 04 Task 2 lands).
# Uses importlib.reload to re-evaluate the conditional import guard in
# services/agent/tools/__init__.py.  T6 (eng-review Decision-8) requires
# sys.modules.pop("services.agent.tools.recall", None) BEFORE reload so that
# Python does not short-circuit the conditional via the cached child module.
# ──────────────────────────────────────────────────────────────────────────────


def _reset_registry_and_reimport(monkeypatch, enabled: bool):  # type: ignore[no-untyped-def]
    """Reset singleton registry + reload the tools package so the conditional
    import in services/agent/tools/__init__.py re-evaluates.

    T6 amendment (eng-review Decision-8): clear the recall child-module cache
    BEFORE reloading the parent.  Without this, Python sees the cached
    ``services.agent.tools.recall`` in sys.modules and skips re-running the
    ``@get_tool_registry().register`` decorator — the test would then pass
    trivially because the registry was just reset to empty, NOT because the
    kill-switch actually fired.
    """
    from config.settings import settings as _settings  # noqa: PLC0415

    import services.agent.tools.registry as reg_mod  # noqa: PLC0415

    # 1. Reset registry singleton so we start with a fresh, empty registry.
    monkeypatch.setattr(reg_mod, "_registry", None, raising=False)

    # 2. Flip the kill-switch toggle BEFORE reload.
    monkeypatch.setattr(_settings, "recall_tool_enabled", enabled, raising=False)

    # 3. T6 FIX — clear the cached recall child module so the conditional
    #    ``if settings.recall_tool_enabled: from services.agent.tools.recall import RecallTool``
    #    line ACTUALLY re-imports recall.py (running @register) rather than returning
    #    the cached no-op module reference.
    #
    #    We save the existing recall module (if any) and pop it from sys.modules so the
    #    reload re-evaluates the conditional import.  After the reload we PUT IT BACK so
    #    that monkeypatch teardown (which restores _registry to the pre-test singleton)
    #    sees a consistent sys.modules state — specifically, so that subsequent tests
    #    that patch "services.agent.tools.recall.get_memory_service" target the same
    #    module object that RecallTool's closure references.
    _prior_recall_mod = sys.modules.pop("services.agent.tools.recall", None)

    # 4. Reload the tools package — re-evaluates the conditional import guard.
    import services.agent.tools as tools_mod  # noqa: PLC0415

    importlib.reload(tools_mod)

    # 5. Re-register sibling tools on the now-fresh registry singleton.
    import services.agent.tools.retrieve as r1  # noqa: PLC0415
    import services.agent.tools.web_search as r2  # noqa: PLC0415

    importlib.reload(r1)
    importlib.reload(r2)

    # 6. Restore the recall module in sys.modules (put back the pre-test version).
    #    This is critical: monkeypatch teardown will restore _registry to the
    #    pre-test singleton (which has recall_memory already registered against the
    #    original RecallTool class).  If sys.modules["services.agent.tools.recall"]
    #    is absent at that point, the next `import services.agent.tools.recall` would
    #    re-run @get_tool_registry().register on a registry that already has it →
    #    ValueError.  By restoring the prior module, subsequent imports are no-ops.
    if _prior_recall_mod is not None:
        sys.modules.setdefault("services.agent.tools.recall", _prior_recall_mod)

    return tools_mod.get_tool_registry()


def test_enabled_registers_recall_memory(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """When recall_tool_enabled=True, reload registers recall_memory in the registry.

    RED until Plan 04 Task 2: __init__.py does not yet conditionally import
    recall.py, so registry singleton reset + reload never triggers @register,
    leaving "recall_memory" absent regardless of the toggle value.
    """
    reg = _reset_registry_and_reimport(monkeypatch, enabled=True)
    assert "recall_memory" in reg.list()


def test_disabled_skips_recall_memory(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """When recall_tool_enabled=False, reload does NOT register recall_memory.

    Load-bearing kill-switch test — sys.modules.pop + registry reset ensure
    the skip fires for the right reason (T6).
    """
    reg = _reset_registry_and_reimport(monkeypatch, enabled=False)
    assert "recall_memory" not in reg.list()


def test_disabled_registry_lookup_raises_keyerror(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """When disabled, registry.get("recall_memory") raises KeyError.

    This is the executor's defence: if the planner hallucinates "recall_memory"
    while the toggle is False, Executor.dispatch raises KeyError before calling
    any tool body (Phase 17 behavior).
    """
    reg = _reset_registry_and_reimport(monkeypatch, enabled=False)
    with pytest.raises(KeyError):
        reg.get("recall_memory")


def test_allowlist_length_constant_regardless_of_toggle(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """D-B4 wording: AGENT_TOOL_ALLOWLIST stays length 4 in BOTH toggle states.

    T11 amendment (eng-review 2026-05-16): tests BOTH enabled=True AND
    enabled=False states inline instead of a single-state tautology.
    The allowlist literal is static; registration is the dynamic surface.
    """
    from services.pipeline import AGENT_TOOL_ALLOWLIST  # noqa: PLC0415

    # State 1: enabled=True
    _reset_registry_and_reimport(monkeypatch, enabled=True)
    assert len(AGENT_TOOL_ALLOWLIST) == 4, "allowlist must be length 4 when enabled"
    assert "recall_memory" in AGENT_TOOL_ALLOWLIST

    # State 2: enabled=False — reload registry but verify allowlist literal unchanged
    _reset_registry_and_reimport(monkeypatch, enabled=False)
    # Re-read the module attribute to verify the literal was not mutated at runtime.
    import services.pipeline as pipeline_mod  # noqa: PLC0415

    importlib.reload(pipeline_mod)
    allowlist_disabled = pipeline_mod.AGENT_TOOL_ALLOWLIST
    assert len(allowlist_disabled) == 4, "allowlist must stay length 4 when disabled"
    assert "recall_memory" in allowlist_disabled, "recall_memory stays in allowlist when disabled"


def test_schemas_for_omits_when_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """When disabled, schemas_for("anthropic", names=AGENT_TOOL_ALLOWLIST) returns 3.

    registry.py:78 filters by registered names — when "recall_memory" is not
    registered, the 4-element allowlist yields only 3 schemas.  This is the
    actual mechanism by which the planner stops seeing the tool.
    """
    from services.pipeline import AGENT_TOOL_ALLOWLIST  # noqa: PLC0415

    reg = _reset_registry_and_reimport(monkeypatch, enabled=False)
    schemas = reg.schemas_for("anthropic", names=AGENT_TOOL_ALLOWLIST)
    assert len(schemas) == 3
    names_in_schemas = [s["name"] for s in schemas]
    assert "recall_memory" not in names_in_schemas
