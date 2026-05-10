"""Static-source assertions for the Phase 20 UI render branch (AGENT-12, SC4).

These tests verify the shape of static/ui.js after the locator-token-swap edit
without spinning up the FastAPI app. The CSS-unchanged invariant is verified
by grepping static/ui.css for absence of any web-source-specific selector.

Behavioral rendering is verified by an executor-side smoke test (Plan 20-05
human-verify checkpoint), not here.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_UI_JS = Path("static/ui.js")
_UI_CSS = Path("static/ui.css")
_UI_HTML = Path("static/ui.html")


@pytest.fixture(scope="module")
def ui_js_src() -> str:
    return _UI_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ui_css_src() -> str:
    return _UI_CSS.read_text(encoding="utf-8")


# ── Dimension 1: copywriting ─────────────────────────────────────────────


def test_url_label_literal_is_uppercase_ascii(ui_js_src: str) -> None:
    """UI-SPEC §Copywriting Contract: literal label is `URL=` (no `网址=` / `Source=`)."""
    assert "'URL='" in ui_js_src or '"URL="' in ui_js_src
    assert "网址=" not in ui_js_src
    assert "'Source='" not in ui_js_src


def test_page_label_preserved(ui_js_src: str) -> None:
    """v1.4 PDF locator `页=` still rendered for non-web chunks."""
    assert "页=" in ui_js_src


def test_url_question_mark_fallback_via_hostof(ui_js_src: str) -> None:
    """UI-SPEC §Host Extraction Rule: malformed URL → '?' (literal in catch branch)."""
    # The catch branch returns '?' — same fallback as `(m.page_number ?? '?')`.
    assert (
        "catch(e) { return '?'; }" in ui_js_src
        or "catch(e){return '?';}" in ui_js_src.replace(" ", "")
    )


# ── Dimension 2: visuals (CSS classes reused, no new classes) ─────────────


def test_source_row_uses_existing_classes(ui_js_src: str) -> None:
    """`.source` and `.meta` classes reused; no new class names introduced."""
    assert 'class="source"' in ui_js_src
    assert 'class="meta"' in ui_js_src


# ── Dimension 3-5: CSS / typography / spacing unchanged ──────────────────


def test_static_ui_css_has_no_web_specific_selector(ui_css_src: str) -> None:
    """No `.source.web` / `.meta-web` / `[data-chunk-type=web]` style introduced."""
    assert ".source.web" not in ui_css_src
    assert ".meta-web" not in ui_css_src
    assert "[data-chunk-type" not in ui_css_src
    assert "data-chunk-type=" not in ui_css_src


# ── Dimension 6: registry safety / no clickable hyperlink ────────────────


def test_url_is_plain_text_not_clickable_anchor(ui_js_src: str) -> None:
    """UI-SPEC §Visual-Treatment Delta: `URL=<host>` is plain text, NOT `<a href>`."""
    # The web-branch locator string assembles `'URL=' + esc(hostOf(m.source))`.
    # No `<a ` markup anywhere near the locator (or anywhere in the file —
    # current v1.4 ui.js has zero anchor tags).
    assert "<a href" not in ui_js_src
    assert "<a " not in ui_js_src


# ── Branch shape (the locator ternary) ───────────────────────────────────


def test_locator_ternary_uses_strict_equality(ui_js_src: str) -> None:
    """UI-SPEC §Source-Row §invariant 1: STRICT equality, lowercase 'web'."""
    assert "chunk_type === 'web'" in ui_js_src
    assert "chunk_type == 'web'" not in ui_js_src    # weak equality NOT used
    assert "chunk_type === 'WEB'" not in ui_js_src   # case-insensitive NOT used


def test_hostof_helper_present(ui_js_src: str) -> None:
    """UI-SPEC §Host Extraction Rule: `hostOf` defined, uses `new URL(...).host`."""
    assert "function hostOf" in ui_js_src
    assert "new URL(url).host" in ui_js_src


def test_host_passed_through_escape_helper(ui_js_src: str) -> None:
    """Host string passes through `esc()` before HTML insertion (XSS defence)."""
    assert "esc(hostOf(" in ui_js_src


# ── HTML / sentinels unchanged ───────────────────────────────────────────


def test_ui_html_unchanged_sentinels() -> None:
    """v1.0 sentinels in ui.html still present (no Phase 20 HTML edit)."""
    if not _UI_HTML.exists():
        pytest.skip("ui.html not found")
    body = _UI_HTML.read_text(encoding="utf-8")
    # Sentinels reflect actual v1.4 baseline (Agent-prefixed, NOT plan's stale "RAG"
    # wording — plan-text drift caught by Rule 1 auto-fix during execution).
    for needle in (
        "<title>Agent 查询</title>",
        "Agent 查询界面",
        'id="q"',
        'id="btn"',
        'id="out"',
    ):
        assert needle in body, f"sentinel removed: {needle!r}"
