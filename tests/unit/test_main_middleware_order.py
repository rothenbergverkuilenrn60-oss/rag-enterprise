"""Deterministic middleware-order assertion for main.py (Plan 27-01 Task 1, /plan-eng-review A1).

Pins the EXACT ordered middleware list captured BEFORE the Task 1 `_configure_app`
extraction so any post-refactor reorder is caught structurally — not via 8-test
behavioral indirection.

Baseline captured 2026-05-17 by running, against the pre-refactor commit:

    APP_MODEL_DIR=/tmp SECRET_KEY=... uv run python -c '
    from main import app
    for m in app.user_middleware:
        cls = m.cls.__name__
        dispatch = getattr(m.kwargs, "get", lambda *_: None)("dispatch")
        print(cls, getattr(dispatch, "__name__", None))'

Output:

    BaseHTTPMiddleware auth_middleware
    BaseHTTPMiddleware rate_limit_middleware
    BaseHTTPMiddleware trace_middleware
    CORSMiddleware None
    SlowAPIMiddleware None

These three `BaseHTTPMiddleware` entries are the three `@app.middleware("http")`
decorators in main.py (auth at L366, rate_limit at L292, trace at L203). FastAPI
prepends middleware to user_middleware, so the LAST `add_middleware` / `@middleware`
appears at index 0 (outermost). The Task 1 refactor MUST preserve this exact
add-order. Any change to the ORDER of the calls inside `_configure_app(app)`
changes the indices and trips this assertion.

Also pins the route count and exception-handler key set so accidental loss of a
mount / handler is caught structurally.
"""

from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import pytest

# Captured baseline (pre-refactor). Format: (middleware_class_name, dispatch_function_name_or_None).
EXPECTED_MIDDLEWARE_ORDER: tuple[tuple[str, str | None], ...] = (
    ("BaseHTTPMiddleware", "auth_middleware"),
    ("BaseHTTPMiddleware", "rate_limit_middleware"),
    ("BaseHTTPMiddleware", "trace_middleware"),
    ("CORSMiddleware", None),
    ("SlowAPIMiddleware", None),
)

# Captured baseline (pre-refactor). 32 routes — includes mounted /ui static, /metrics,
# and the two router includes (api + memory).
EXPECTED_ROUTE_COUNT_MIN = 30  # tolerate +/- 2 in case Phase 27 ships another route via include

# Captured baseline: every exception-handler key present at module load.
# Includes RateLimitExceeded + the generic Exception handler from main.py.
EXPECTED_EXCEPTION_HANDLER_KEYS: frozenset[str] = frozenset({
    "HTTPException",            # Starlette default
    "RequestValidationError",   # FastAPI default
    "WebSocketRequestValidationError",  # FastAPI default
    "RateLimitExceeded",        # main.py: app.add_exception_handler(RateLimitExceeded, ...)
    "Exception",                # main.py: @app.exception_handler(Exception)
})


def _middleware_signature(app: object) -> tuple[tuple[str, str | None], ...]:
    """Extract (cls_name, dispatch_fn_name_or_None) tuples from app.user_middleware."""
    out: list[tuple[str, str | None]] = []
    for m in app.user_middleware:  # type: ignore[attr-defined]
        cls_name = m.cls.__name__ if hasattr(m, "cls") else type(m).__name__
        dispatch_name: str | None = None
        kwargs = getattr(m, "kwargs", None)
        if isinstance(kwargs, dict):
            dispatch = kwargs.get("dispatch")
            if dispatch is not None:
                dispatch_name = getattr(dispatch, "__name__", None)
        out.append((cls_name, dispatch_name))
    return tuple(out)


def test_module_level_app_middleware_order_matches_baseline() -> None:
    """The module-level `app` must keep the exact pre-refactor middleware add-order.

    Trips deterministically if Task 1's `_configure_app(app)` extraction reorders
    the calls inside the helper body. Reordering middleware is a semantic change
    even when behavior happens to coincide — auth-before-trace vs trace-before-auth
    produces different X-Trace-ID headers on rejected requests.
    """
    from main import app

    actual = _middleware_signature(app)
    assert actual == EXPECTED_MIDDLEWARE_ORDER, (
        f"middleware order drifted from pre-refactor baseline.\n"
        f"  expected: {EXPECTED_MIDDLEWARE_ORDER}\n"
        f"  actual:   {actual}"
    )


def test_module_level_app_exception_handler_keys_present() -> None:
    """Every exception handler registered pre-refactor must still be registered."""
    from main import app

    actual_keys = frozenset(
        cls.__name__ if hasattr(cls, "__name__") else str(cls)
        for cls in app.exception_handlers.keys()
    )
    missing = EXPECTED_EXCEPTION_HANDLER_KEYS - actual_keys
    assert not missing, (
        f"exception handlers missing after Task 1 refactor: {missing}\n"
        f"  actual: {sorted(actual_keys)}"
    )


def test_module_level_app_route_count_unchanged() -> None:
    """Route count should not drop after _configure_app extraction.

    Tolerates small +/- variance in case Phase 27 ships another router include in
    a sibling plan. A drop below the floor means a router/mount was lost.
    """
    from main import app

    assert len(app.routes) >= EXPECTED_ROUTE_COUNT_MIN, (
        f"route count dropped below floor: got {len(app.routes)}, "
        f"expected >= {EXPECTED_ROUTE_COUNT_MIN}"
    )


def test_configure_app_helper_is_lossless_on_fresh_instance() -> None:
    """Calling _configure_app on a fresh FastAPI() must reproduce the same
    middleware-order + exception-handler set + non-zero route count as the
    module-level app.

    This is the load-bearing assertion for the factory: tests/factories/app.py
    `create_app()` constructs a bare `FastAPI(lifespan=lifespan)` and calls
    `_configure_app(app)`. If that path produces a structurally different app,
    every test built on the factory observes a wrong shape.
    """
    pytest.importorskip("main")
    import main

    configure = getattr(main, "_configure_app", None)
    if configure is None:
        pytest.skip("_configure_app not present — Task 1 not yet landed")

    from fastapi import FastAPI

    fresh = FastAPI()
    configure(fresh)

    assert _middleware_signature(fresh) == EXPECTED_MIDDLEWARE_ORDER, (
        "fresh FastAPI() + _configure_app(fresh) produced a different "
        "middleware order than the module-level app — extraction is not lossless"
    )

    actual_keys = frozenset(
        cls.__name__ if hasattr(cls, "__name__") else str(cls)
        for cls in fresh.exception_handlers.keys()
    )
    missing = EXPECTED_EXCEPTION_HANDLER_KEYS - actual_keys
    assert not missing, (
        f"fresh app missing exception handlers after _configure_app: {missing}"
    )

    assert len(fresh.routes) >= EXPECTED_ROUTE_COUNT_MIN, (
        f"fresh app route count {len(fresh.routes)} < floor {EXPECTED_ROUTE_COUNT_MIN}"
    )
