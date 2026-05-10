"""Unit tests for UI-02 (Phase 14): static/ui.html split into ui.css + ui.js.

Asserts FastAPI StaticFiles serves all 3 files with correct Content-Type and
that ui.html no longer contains inline <style>, <script>, or onclick= handlers.
Mirrors the test pattern at tests/integration/test_ui_static.py:17-24 but lives
in tests/unit/ so it runs by default (no -m integration filter).
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
    from main import app
    return TestClient(app)


def test_ui_html_no_inline_blocks(client: TestClient) -> None:
    """AC#1 + AC#3: ui.html has no inline <style>, <script>, or onclick handlers."""
    r = client.get("/ui/ui.html")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    # AC#1: external references present
    assert '<link rel="stylesheet" href="ui.css"' in body
    assert '<script src="ui.js"' in body
    # AC#1: no inline blocks
    assert "<style>" not in body
    # AC#3: no inline event handlers
    assert "onclick=" not in body
    assert "onsubmit=" not in body


def test_ui_css_served(client: TestClient) -> None:
    """AC#2: ui.css served with text/css MIME."""
    r = client.get("/ui/ui.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


def test_ui_js_served(client: TestClient) -> None:
    """AC#2 + AC#3: ui.js served with javascript MIME and contains addEventListener."""
    r = client.get("/ui/ui.js")
    assert r.status_code == 200
    # Match both 'text/javascript' (Python 3.12+) and 'application/javascript' (older).
    assert "javascript" in r.headers["content-type"].lower()
    body = r.text
    # AC#3: event wiring uses addEventListener (not inline handlers).
    assert "addEventListener" in body


def test_index_html_symlink_serves_ui_html(client: TestClient) -> None:
    """D-09: GET /ui/ resolves index.html → ui.html symlink."""
    r = client.get("/ui/")
    assert r.status_code == 200
    # v1.4.2: heading reframed to "Agent 查询界面" (Planner / Executor / Synthesizer
    # is the project's core; agentic RAG is one tool — README + ROADMAP narrative).
    assert "Agent 查询界面" in r.text
