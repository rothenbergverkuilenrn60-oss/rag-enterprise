"""Integration tests for UI-01 (Phase 9): static/ui.html served via FastAPI StaticFiles.

Pins the v1.0-equivalent behaviour after extracting the inline `_UI_HTML` string to
`static/ui.html`. See `.planning/phases/09-frontend-extraction/09-CONTEXT.md` for the
locked decisions (D-01..D-04) — this test asserts the contract those decisions imply,
NOT internal implementation details.
"""
from __future__ import annotations

import os

# Match conftest.py preconditions so app import succeeds in a clean env.
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    # Imported lazily so env vars above are set before settings load.
    from main import app
    return TestClient(app)


@pytest.mark.integration
def test_ui_static_serves_html(client: TestClient) -> None:
    """SC #2: GET /ui/ returns 200 + text/html with v1.0 page sentinels."""
    resp = client.get("/ui/")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}"
    assert resp.headers["content-type"].startswith("text/html"), (
        f"expected text/html, got {resp.headers['content-type']}"
    )
    body = resp.text

    # 5 v1.0 HTML sentinels — see 09-01-PLAN.md <interfaces> for derivation.
    # Phase 14 (UI-02) note: 2 JS-side sentinels ('/api/v1/query', 'include_images:true')
    # moved out of ui.html into static/ui.js; covered by tests/unit/test_static_ui.py::test_ui_js_served.
    sentinels = [
        "<title>RAG 查询</title>",
        "<h1>RAG 查询界面</h1>",
        'id="q"',
        'id="btn"',
        'id="out"',
    ]
    for needle in sentinels:
        assert needle in body, f"missing v1.0 sentinel: {needle!r}"


@pytest.mark.integration
def test_ui_no_slash_redirects_to_ui_slash(client: TestClient) -> None:
    """D-03 contract: /ui (no slash) → 307 → /ui/ (FastAPI StaticFiles default)."""
    resp = client.get("/ui", follow_redirects=False)
    assert resp.status_code == 307, f"expected 307, got {resp.status_code}"
    assert resp.headers["location"].endswith("/ui/"), (
        f"expected redirect to /ui/, got {resp.headers['location']!r}"
    )


@pytest.mark.integration
def test_ui_mount_not_in_openapi(client: TestClient) -> None:
    """Regression guard: app.mount() doesn't appear in OpenAPI (replaces include_in_schema=False).

    Note: /openapi.json is gated on settings.debug in main.py. We bypass that gate
    by invoking app.openapi() directly — the schema is what we want to assert
    against, not the HTTP exposure of it.
    """
    schema = client.app.openapi()
    paths = schema.get("paths", {})
    assert "/ui" not in paths, "static mount leaked into OpenAPI schema"
    assert "/ui/" not in paths, "static mount leaked into OpenAPI schema"
