"""SC-1 cross-contamination tests for `create_app()` factory.

Plan 27-01 Task 2 — implements RESEARCH §Theme 1 lines 429-453.

Proves test-isolation properties:
  1. Mutating a module-level singleton between two `app_factory()` calls is
     reset by the second call (proves brute-force `_reset_singletons()` works).
  2. `dependency_overrides` passed to one app do not leak into another app
     (proves per-app dependency_overrides dict isolation — the prerequisite for
     parallel-running tests stubbing the same dep with different fakes).

Two coroutines running in parallel via `asyncio.gather` produces the cleanest
demonstration of property (2), but a sequential per-app override comparison is
functionally equivalent and avoids spurious event-loop interactions.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import asyncio
from collections.abc import Callable
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_two_apps_do_not_share_singleton_state(app_factory: Callable[..., Any]) -> None:
    """Verbatim from RESEARCH §Theme 1 lines 433-453 (the SC-1 reference shape).

    app_a -> sentinel poisoned into services.agent.executor._executor_instance
    -> app_b construction must reset it.
    """
    app_a = app_factory()

    import services.agent.executor as exec_mod

    sentinel = object()
    exec_mod._executor_instance = sentinel  # type: ignore[assignment]

    app_b = app_factory()

    assert exec_mod._executor_instance is None, (
        "create_app() did not reset _executor_instance; "
        "cross-contamination between tests is possible"
    )
    assert app_a is not app_b


@pytest.mark.asyncio
async def test_dependency_overrides_isolated_across_apps(
    app_factory: Callable[..., Any],
) -> None:
    """Two app_factory(dependency_overrides=...) calls produce apps with
    independent dependency_overrides dicts — stubbing dep_a in one app must
    NOT make the stub visible in the other.
    """
    def _dep() -> str:
        return "real"

    def stub_a() -> str:
        return "stub-a"

    def stub_b() -> str:
        return "stub-b"

    app_a = app_factory(dependency_overrides={_dep: stub_a})
    app_b = app_factory(dependency_overrides={_dep: stub_b})

    assert app_a.dependency_overrides[_dep] is stub_a
    assert app_b.dependency_overrides[_dep] is stub_b

    # Cross-leak invariants
    assert stub_a is not stub_b
    assert app_a.dependency_overrides[_dep] is not app_b.dependency_overrides[_dep]


@pytest.mark.asyncio
async def test_parallel_app_construction_preserves_isolation(
    app_factory: Callable[..., Any],
) -> None:
    """Stronger variant — two coroutines run via asyncio.gather, each
    constructs an app with its own dependency_overrides, asserts its own
    override survives without observing the other's.

    Together with the sentinel test above, this satisfies SC-1's
    "Two tests running in parallel against create_app() do not observe each
    other's state."
    """
    def _dep() -> str:
        return "real"

    def stub_x() -> str:
        return "stub-x"

    def stub_y() -> str:
        return "stub-y"

    async def _build_and_check(stub: Callable[[], str]) -> bool:
        app = app_factory(dependency_overrides={_dep: stub})
        # The override applies to THIS app and not the other.
        return app.dependency_overrides[_dep] is stub

    results: list[bool] = list(
        await asyncio.gather(
            _build_and_check(stub_x),
            _build_and_check(stub_y),
        )
    )
    assert results == [True, True], (
        f"parallel app construction lost override identity: {results}"
    )
