"""Self-tests for tests/factories/app.py — TD-02 D-01 brute-force isolation scaffold.

Plan 27-00 — Test Infra Prep.

Tests 1-3 are non-gated: verify the inventory + reset helper independently of main._configure_app.
Tests 4-5 are gated via `pytest.importorskip` on `main._configure_app` (introduced in plan
27-01). Until 27-01 lands they MUST report SKIPPED, not failure.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import pytest


def test_factory_module_imports() -> None:
    """Test 1: module loads and exports create_app + _SINGLETON_INVENTORY + _reset_singletons."""
    from tests.factories.app import _SINGLETON_INVENTORY, _reset_singletons, create_app

    assert callable(create_app)
    assert callable(_reset_singletons)
    assert isinstance(_SINGLETON_INVENTORY, tuple)


def test_inventory_size_and_reset_idempotent() -> None:
    """Test 2 + 3: inventory >=32 entries; _reset_singletons() is idempotent."""
    import services.agent.executor as exec_mod
    from tests.factories.app import _SINGLETON_INVENTORY, _reset_singletons

    assert len(_SINGLETON_INVENTORY) >= 32, (
        f"expected >=32 singleton entries (RESEARCH §1 - 4 non-services), "
        f"got {len(_SINGLETON_INVENTORY)}"
    )

    # Pre-set a singleton, then verify reset zeroes it.
    sentinel = object()
    exec_mod._executor_instance = sentinel  # type: ignore[assignment]
    _reset_singletons()
    assert exec_mod._executor_instance is None

    # Idempotent: calling again on an already-None state is fine.
    _reset_singletons()
    assert exec_mod._executor_instance is None


def test_inventory_excludes_non_services() -> None:
    """The 4 cached primitives (RESEARCH §1) MUST NOT be in inventory."""
    from tests.factories.app import _SINGLETON_INVENTORY

    attrs = {attr for _, attr in _SINGLETON_INVENTORY}
    forbidden = {
        "_tiktoken_enc",
        "_anthropic_rate_limit_cls",
        "_anthropic_overload_cls",
        "_sem",
    }
    leaked = attrs & forbidden
    assert not leaked, f"non-service primitives leaked into inventory: {leaked}"


def _configure_app_available() -> bool:
    """Return True iff main._configure_app exists (lands in plan 27-01)."""
    try:
        import main

        return getattr(main, "_configure_app", None) is not None
    except Exception:  # noqa: BLE001 — guard, not error-path
        return False


@pytest.mark.skipif(
    not _configure_app_available(),
    reason="needs main._configure_app from plan 27-01",
)
def test_create_app_returns_distinct_instances() -> None:
    """Test 4 (gated): two create_app() calls return distinct FastAPI instances."""
    from tests.factories.app import create_app

    app_a = create_app()
    app_b = create_app()
    assert app_a is not app_b


@pytest.mark.skipif(
    not _configure_app_available(),
    reason="needs main._configure_app from plan 27-01",
)
def test_create_app_applies_dependency_overrides() -> None:
    """Test 5 (gated): dependency_overrides kwarg is applied to the new app."""
    from tests.factories.app import create_app

    def _dep() -> str:
        return "real"

    def _stub() -> str:
        return "stub"

    app = create_app(dependency_overrides={_dep: _stub})
    assert app.dependency_overrides.get(_dep) is _stub
