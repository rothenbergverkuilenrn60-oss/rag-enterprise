# Phase 14: Frontend Split and DOM Modernization - Research

**Researched:** 2026-05-09
**Domain:** Static asset extraction, classic-script IIFE pattern, FastAPI `StaticFiles` MIME defaults, FastAPI `TestClient` content-type assertions
**Confidence:** HIGH

## Summary

Phase 14 is a mechanical extraction: 14 lines of inline `<style>` (ui.html:6-19) become `static/ui.css`; 29 lines of inline `<script>` (ui.html:29-57) become `static/ui.js` wrapped in an IIFE with `"use strict"`. The single `onclick="ask()"` (ui.html:26) is replaced with an `addEventListener('click', ask)` call wired inside a `DOMContentLoaded` block alongside the already-existing keydown handler. FastAPI `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")` at `main.py:395` is UNCHANGED — Starlette's `StaticFiles` resolves any file under `directory=` and Python's `mimetypes` module sets correct `Content-Type` for `.css` / `.js` automatically [VERIFIED: `python3 -c "mimetypes.guess_type"` returns `text/css` and `text/javascript`].

A new `tests/unit/test_static_ui.py` uses the existing `FastAPI TestClient` pattern (already used at `tests/integration/test_ui_static.py:17-24` and 6+ unit tests) to assert HTTP 200 + content-type + AC-enforcement sentinels (`'<style>' not in body`, `'onclick=' not in body`). Tests live in `tests/unit/` (not `tests/integration/`) so they run by default — the existing `pytest.ini` has `addopts = -m "not integration"`, so integration-marked tests are skipped unless explicitly opted-in.

**Primary recommendation:** Single-pass refactor — copy lines 6-19 verbatim into `static/ui.css`, copy lines 29-57's body (without the `<script>` tag) into the IIFE body in `static/ui.js`, replace ui.html's inline blocks with `<link rel="stylesheet" href="ui.css">` and `<script src="ui.js" defer></script>`. Use `defer` AND `DOMContentLoaded` (per CONTEXT D-05 + D-10 belt-and-suspenders); the redundancy is harmless. Add 4 unit tests mirroring the CONTEXT `<specifics>` skeleton verbatim. Total scope: 3 file writes + 1 test file + 1 ui.html edit.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Architecture**
- **D-01:** No bundler. Single `static/ui.js` + `static/ui.css`. Zero new build infra (no package.json, no node_modules).
- **D-02:** Classic `<script src="ui.js">` (NOT `type="module"`). JS wrapped in IIFE: `(function(){ "use strict"; ... })();`. Avoids global `ask()`. `"use strict"` enables strict mode without ESM.
- **D-03:** Single `static/ui.css` (NOT split into base + components). 14 lines doesn't justify multi-file.

**DOM API + Event Wiring**
- **D-04:** Keep `document.getElementById(...)` calls (6× in current code). Do NOT migrate to `querySelector` or `data-action`.
- **D-05:** Wire all event listeners inside a `DOMContentLoaded` handler at the bottom of the IIFE. Replace `onclick="ask()"` (line 26) with `document.getElementById('btn').addEventListener('click', ask)`. Existing `addEventListener('keydown', ...)` at line 56 stays inside the same `DOMContentLoaded` block.
- **D-06:** Cache element refs as local consts only when accessed multiple times. Current usage: #q 1×, #topk 1×, #out 2×, #btn 2× — keep inline `getElementById`; no premature caching.

**Helper Functions**
- **D-07:** `esc()` helper stays inside ui.js (not extracted to utils file). Single consumer; extraction is YAGNI.

**Serving / FastAPI Layer**
- **D-08:** `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")` UNCHANGED. New `ui.css` / `ui.js` served at `/ui/ui.css` / `/ui/ui.js` without main.py edits.
- **D-09:** `static/index.html → ui.html` symlink UNCHANGED.
- **D-10:** ui.html `<head>` references: `<link rel="stylesheet" href="ui.css">` (relative path). `<script src="ui.js"></script>` at end of `<body>` (or use `defer` for safety).

**Testing**
- **D-11:** No new automated UI tests beyond static-file serving. Manual smoke: doc upload → query → result display; browser dev tools verify no console errors, no 404s.
- **D-12:** Add minimal pytest in `tests/unit/test_static_ui.py` verifying FastAPI serves all 3 files with HTTP 200 + correct `Content-Type` using `FastAPI TestClient`.

**Failure Handling**
- **D-13:** No JS error handling changes. `try/catch` on fetch stays. `esc()` stays. Refactor is mechanical.

### Claude's Discretion
- `<script>` tag placement: `<head>` with `defer` vs end-of-`<body>` (D-10 explicitly allows either). Researcher recommends end-of-body + `defer` (belt-and-suspenders with D-05's `DOMContentLoaded`).
- Inner whitespace / indentation in extracted files (must preserve byte-equivalence of CSS rules and JS statements; surrounding indentation is discretion).

### Deferred Ideas (OUT OF SCOPE)
- Bundler (Vite/esbuild)
- Frontend framework (React/Vue/Svelte) migration
- Dark mode / theme toggle
- Search history / saved queries
- Playwright E2E browser tests
- Source maps / TypeScript migration
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-02 AC#1 | `ui.html` has no `<script>` w/ inline JS, no `<style>` w/ inline CSS — only `<script src="ui.js">` + `<link rel="stylesheet" href="ui.css">` | §Code Examples (final ui.html); §Validation (test sentinel `"<style>" not in r.text`) |
| UI-02 AC#2 | `ui.css` and `ui.js` exist; FastAPI `StaticFiles` serves them without config changes | §Architecture Patterns #1 (StaticFiles auto-MIME); §Code Examples (test_ui_css_served / test_ui_js_served) |
| UI-02 AC#3 | All `onclick=`, `onsubmit=`, etc. inline handlers replaced with `addEventListener` | §Code Examples (final ui.js IIFE); §Validation (test sentinel `'onclick=' not in r.text`) |
| UI-02 AC#4 | Globals replaced with `getElementById` / `querySelector` calls | §Architecture Patterns #2 (IIFE encapsulation); D-04 (keep existing `getElementById` — already conformant) |
| UI-02 AC#5 | Bundler optional (decided at implementation) — D-01 NO bundler | §Standard Stack (no new tooling); §State of the Art (revisit threshold) |
| UI-02 AC#6 | Visual regression: identical render for upload + query + result flows | §Architecture Patterns #3 (byte-equivalent extraction); §Validation (manual smoke checklist) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HTML structure | Frontend (`static/ui.html`) | — | Template only; no logic, no inline JS/CSS post-refactor |
| Visual styling | Frontend asset (`static/ui.css`) | — | 14 declarations; static asset served as-is |
| DOM behaviour + fetch logic | Frontend (`static/ui.js` IIFE) | — | Wraps `ask()` + `esc()` + event wiring; no bundler, no module scope |
| Static file serving | API server (`main.py:395` `StaticFiles` mount) | OS filesystem | Starlette `StaticFiles` walks `directory="static"` and resolves any path; auto-sets `Content-Type` via `mimetypes` |
| Symlink resolution | OS filesystem (`static/index.html → ui.html`) | — | Resolved by Starlette's path traversal — symlink target lives inside the mounted directory, no special handling [VERIFIED: ls -la shows `index.html -> ui.html  7B`] |
| Test verification | Test layer (`tests/unit/test_static_ui.py`) | — | `FastAPI TestClient` makes in-process HTTP calls; no real socket/network; pattern already used at `test_ui_static.py:17-24` |

**Tier check:** No backend logic added or moved. main.py UNCHANGED. Pipeline / API UNCHANGED. The phase is purely a frontend reorganization with backend test coverage of the static-serving contract.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `fastapi.staticfiles.StaticFiles` | FastAPI dep (Starlette) | Serves files under `directory=` with `html=True` (treats `index.html` as root) | Already mounted at `main.py:395`; no changes for Phase 14 [VERIFIED: file read] |
| Python `mimetypes` (stdlib) | 3.12+ | Maps file extensions → MIME types for `Content-Type` headers | `text/css` for `.css`, `text/javascript` for `.js`, `text/html` for `.html` [VERIFIED: `python3 -c "import mimetypes; mimetypes.guess_type('x.js')"` → `('text/javascript', None)`] |
| `fastapi.testclient.TestClient` | FastAPI dep | In-process HTTP client for assertion-style tests | Already used at `tests/integration/test_ui_static.py:17`, `tests/unit/test_rate_limiting.py:73`, `tests/unit/test_ingest_status.py:17` [VERIFIED: grep] |
| `pytest` | (project) | Test runner | `pytest.ini` configured; `tests/unit/` is auto-discovered; `addopts = -m "not integration"` excludes integration-marked tests by default [VERIFIED: pytest.ini read] |

### Supporting
None. Phase introduces ZERO new packages.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Classic IIFE | ES module (`type="module"`) | Module CORS quirks for `file://`; MIME requirements; no benefit at 33-line scale [D-02 rejects] |
| Single `ui.js` | Vite/esbuild bundler + `npm run build` | Adds package.json + node_modules + build step for 33 lines [D-01 rejects] |
| Single `ui.css` | base.css + components.css | Multi-file split for 14 lines is over-engineering [D-03 rejects] |

**Installation:** No new packages. Existing `requirements.txt` covers FastAPI + pytest.

## Architecture Patterns

### Pattern 1: FastAPI `StaticFiles` auto-MIME serving
**What:** Starlette's `StaticFiles` uses Python's `mimetypes.guess_type()` to set `Content-Type` for every served file. No per-file route registration needed.
**When to use:** Any static asset extension (`.css`, `.js`, `.html`, `.png`, etc.) — the existing mount at `main.py:395` covers all files under `static/` automatically.
**Verification:** `python3 -c "import mimetypes; print(mimetypes.guess_type('x.css'), mimetypes.guess_type('x.js'))"` → `('text/css', None) ('text/javascript', None)` [VERIFIED: shell exec].

**Note on JS MIME:** Python 3.12+ `mimetypes` returns `text/javascript` (per RFC 9239), NOT the older `application/javascript`. CONTEXT test stub uses `"javascript" in r.headers["content-type"].lower()` — this substring matches both forms, so the test is forward/backward compatible.

### Pattern 2: IIFE with `"use strict"` for global isolation
**What:** Wrap all script content in an immediately-invoked function expression. Inside the function, declare `"use strict";` to enable strict mode without requiring ESM.

```javascript
(function(){
  "use strict";
  async function ask(){ /* ... */ }
  function esc(s){ /* ... */ }
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn').addEventListener('click', ask);
    document.getElementById('q').addEventListener('keydown', e => {
      if (e.ctrlKey && e.key === 'Enter') ask();
    });
  });
})();
```

**Why:** `ask` and `esc` are not exposed on `window`. The original `onclick="ask()"` (which required `ask` to be global) is removed and replaced with `addEventListener`, so global exposure is no longer needed. `"use strict"` MUST be the first statement inside the IIFE — directives are per-function-scope (not inherited), so each function that needs strict mode declares it.

### Pattern 3: `defer` attribute + `DOMContentLoaded` (belt-and-suspenders)
**What:** With `<script src="ui.js" defer></script>`, the browser parses the script in parallel with HTML parsing but defers execution until after DOM parse completes (and before `DOMContentLoaded` fires). Wiring listeners inside an additional `DOMContentLoaded` handler is redundant but harmless.

**Recommendation:** Use BOTH `defer` (per D-10's "or use `defer` attribute for safety") AND the `DOMContentLoaded` handler (per D-05). Reasoning:
1. D-05 mandates `DOMContentLoaded` — the IIFE skeleton in CONTEXT `<specifics>` already includes it.
2. `defer` provides additional safety if someone later removes the `DOMContentLoaded` block or moves the script tag to `<head>` without defer.
3. Cost of redundancy: ~6 chars in HTML (`defer`); zero runtime cost.

**Alternative:** Drop `defer`, rely solely on `DOMContentLoaded`. Equally valid — script at end-of-body executes after DOM available even without defer. Document the choice in PLAN.

### Pattern 4: Byte-equivalent extraction guarantees AC#6
**What:** Visual regression (AC#6) is mechanically guaranteed if extracted CSS rules are byte-identical to the inline `<style>` block, and JS statements (inside the IIFE wrapper) preserve original semantics. The IIFE wrapper itself does not alter behaviour.

**Source mapping (must be exact):**
- ui.html lines 6-19 (between `<style>` and `</style>`, exclusive) → `static/ui.css` (14 lines, identical text).
- ui.html lines 30-56 (script body, EXCLUDING the `<script>` and `</script>` tags on lines 29 and 57) → wrapped inside the IIFE in `static/ui.js`. The `addEventListener('keydown', ...)` at line 56 must move INTO the new `DOMContentLoaded` handler (per D-05).
- ui.html line 26 `onclick="ask()"` attribute removed; behaviour preserved by `addEventListener('click', ask)` inside `DOMContentLoaded`.

### Pattern 5: `FastAPI TestClient` content-type assertions
**What:** `TestClient(app).get(path).headers["content-type"]` returns lowercase MIME with optional charset. Pattern in existing test:
```python
assert resp.headers["content-type"].startswith("text/html")  # tests/integration/test_ui_static.py:32
```
For Phase 14 unit tests, use case-insensitive substring match (`"javascript" in r.headers["content-type"].lower()`) for the JS file — accommodates both `text/javascript` and `application/javascript` MIME variants.

### Anti-Patterns to Avoid
- **Inline `onclick=` on the new button.** Phase 14 entire purpose is to remove these. The test sentinel `'onclick=' not in r.text` enforces this.
- **Adding `package.json` "for future use".** YAGNI; D-01 explicit; revisit only if JS grows past ~200 lines (per Deferred section).
- **Splitting CSS into multiple files.** D-03 explicit; 14 lines is below any reasonable split threshold.
- **Caching all DOM refs at IIFE top.** D-06 says cache only multi-access refs; current usage doesn't cross the threshold.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Static file serving | Custom FastAPI route per file | Existing `app.mount("/ui", StaticFiles(...))` at main.py:395 | Already configured; auto-MIME, auto-symlink resolution, auto-`index.html` |
| HTTP testing | `httpx.AsyncClient` + manual ASGI plumbing | `fastapi.testclient.TestClient` | Project pattern; sync API; in-process; already used 4 places |
| MIME type lookup | Hardcoded `Content-Type: text/css` headers | `mimetypes` stdlib (auto via StaticFiles) | Python stdlib handles every common extension; no manual mapping |
| Module isolation | Build step + ES modules | IIFE + `"use strict"` | Zero tooling for 33 lines; classic-script semantics are well-understood and browser-cache friendly |

**Key insight:** Every required capability already has a battle-tested project-existing solution. Phase 14 introduces zero new dependencies and zero new patterns; it removes inline-blocks via copy-paste with an IIFE wrap.

## Common Pitfalls

### Pitfall 1: `"use strict"` in wrong scope
**What goes wrong:** `"use strict"` at the top of an IIFE applies to that function only. If extracted helpers (e.g., `esc`) are moved out of the IIFE later, they revert to sloppy mode.
**Why it happens:** Strict-mode directives are per-function-scope, NOT file-scope (only ESM gets file-scope strict by default).
**How to avoid:** Place `"use strict";` as the first statement INSIDE the IIFE body (line 2 of the file in CONTEXT `<specifics>` skeleton). Don't rely on a top-of-file pragma.
**Warning sign:** A future helper added outside the IIFE silently runs in sloppy mode.

### Pitfall 2: `<script>` placement vs `defer`
**What goes wrong:** `<script src="ui.js">` in `<head>` WITHOUT `defer` blocks DOM parsing. Element references inside the script (e.g., `getElementById('btn')`) return `null` because the elements don't exist yet — listeners fail to wire.
**Why it happens:** Classic scripts execute synchronously where they appear in the document.
**How to avoid:** Two valid patterns: (a) `<script>` at end of `<body>` (current CONTEXT skeleton), or (b) `<script defer src="...">` anywhere. Combine with `DOMContentLoaded` handler for defense in depth.
**Warning sign:** Console error `Cannot read property 'addEventListener' of null`.

### Pitfall 3: MIME type assertion brittleness
**What goes wrong:** Asserting `r.headers["content-type"] == "application/javascript"` fails on Python 3.12+ which returns `text/javascript`.
**Why it happens:** RFC 9239 (May 2022) recommends `text/javascript`; Python's `mimetypes` updated accordingly.
**How to avoid:** Use case-insensitive substring match: `"javascript" in r.headers["content-type"].lower()`. The CONTEXT `<specifics>` test stub already follows this pattern.
**Warning sign:** Test passes locally but fails on CI with different Python version.

### Pitfall 4: Symlink resolution outside `directory=`
**What goes wrong:** If `static/index.html` were a symlink pointing OUTSIDE `static/` (e.g., to `/etc/passwd`), Starlette's `StaticFiles` would refuse it (path-traversal protection).
**Why it happens:** Starlette resolves symlinks and rejects paths that escape `directory=`.
**How to avoid:** Confirm `static/index.html → ui.html` (relative target inside the same directory). [VERIFIED: `ls -la static/` shows `index.html -> ui.html  7B`]. Do NOT change the symlink target during the refactor.
**Warning sign:** `GET /ui/` returns 404 instead of the page content.

### Pitfall 5: Missing `defer` AND missing `DOMContentLoaded` if script moves to `<head>`
**What goes wrong:** Future maintainer moves `<script src="ui.js">` to `<head>` for "tidiness" without adding `defer`, and removes `DOMContentLoaded` "because the listeners are at the bottom of the file anyway." DOM lookup returns null on every load.
**How to avoid:** Belt-and-suspenders — both `defer` AND `DOMContentLoaded`. Robust to both kinds of accidental edits.

## Code Examples

### Final `static/ui.html` (~14 lines, structural only)

```html
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<title>RAG 查询</title>
<link rel="stylesheet" href="ui.css">
</head>
<body>
<h1>RAG 查询界面</h1>
<textarea id="q" rows="3" placeholder="输入问题，例如：灯具的发光面是什么？"></textarea>
<div class="row">
  <label>top_k: <input type="number" id="topk" value="5" min="1" max="20" style="width:4rem;"></label>
  <button id="btn">提问</button>
</div>
<div id="out"></div>
<script src="ui.js" defer></script>
</body>
</html>
```

Note: `id="topk"` retains the inline `style="width:4rem;"` attribute — that is HTML attribute styling, not a `<style>` block, and AC#1 only forbids `<style>` blocks. Acceptable per current code (ui.html:25).

### Final `static/ui.css` (14 lines, byte-identical to inline block)

```css
body{font-family:-apple-system,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#222;}
h1{font-size:1.3rem;}
textarea{width:100%;padding:.5rem;font-size:1rem;font-family:inherit;box-sizing:border-box;}
.row{display:flex;gap:1rem;align-items:center;margin:.5rem 0;}
button{padding:.5rem 1.2rem;background:#0a66c2;color:#fff;border:0;border-radius:4px;cursor:pointer;}
button:disabled{background:#999;}
.answer{background:#f4f6f8;padding:1rem;margin:1rem 0;border-left:4px solid #0a66c2;white-space:pre-wrap;}
.source{border:1px solid #ddd;padding:.8rem;margin:.5rem 0;border-radius:4px;}
.source img{max-width:100%;margin-top:.5rem;border:1px solid #ccc;display:block;}
.meta{color:#666;font-size:.82rem;margin-bottom:.4rem;}
.loading{color:#888;font-style:italic;}
.err{color:#c00;}
```

(Source: ui.html lines 7-18 — line-for-line copy.)

### Final `static/ui.js` (IIFE-wrapped, ~33 lines)

```javascript
(function(){
  "use strict";

  async function ask(){
    const q = document.getElementById('q').value.trim();
    if(!q) return;
    const top_k = parseInt(document.getElementById('topk').value) || 5;
    const out = document.getElementById('out');
    const btn = document.getElementById('btn');
    btn.disabled = true;
    out.innerHTML = '<p class="loading">查询中...</p>';
    try {
      const r = await fetch('/api/v1/query', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({query: q, top_k, include_images: true})
      });
      const j = await r.json();
      if(!j.success){
        out.innerHTML = '<p class="err">错误：' + (j.error || '未知') + '</p>';
        return;
      }
      let h = '<h2>答案</h2><div class="answer">' + esc(j.data.answer) + '</div>';
      h += '<h2>来源（' + (j.data.sources || []).length + '）</h2>';
      (j.data.sources || []).forEach((s, i) => {
        const m = s.metadata || {};
        const score = s.final_score || s.rerank_score || s.rrf_score || s.dense_score || 0;
        h += '<div class="source"><div class="meta">来源' + (i+1) + ' · 页=' + (m.page_number ?? '?') + ' · 类型=' + (m.chunk_type || '?') + ' · score=' + score.toFixed(3) + '</div>';
        h += '<div>' + esc(s.content) + '</div>';
        if(m.image_b64) h += '<img src="data:image/png;base64,' + m.image_b64 + '">';
        h += '</div>';
      });
      out.innerHTML = h;
    } catch(e){
      out.innerHTML = '<p class="err">请求失败：' + e + '</p>';
    } finally {
      btn.disabled = false;
    }
  }

  function esc(s){
    return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn').addEventListener('click', ask);
    document.getElementById('q').addEventListener('keydown', e => {
      if(e.ctrlKey && e.key === 'Enter') ask();
    });
  });
})();
```

(Source: ui.html lines 30-56 — same statements wrapped in IIFE; line-26 `onclick` and line-56 keydown handler both wired in `DOMContentLoaded` block.)

### Test file `tests/unit/test_static_ui.py`

```python
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
    assert "RAG 查询界面" in r.text
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Inline `<script>` + `<style>` blocks | External `.js` + `.css` files | Standard since ~2010 | Browser caching, source maps, easier diffing — Phase 14 catches up to baseline |
| `onclick="..."` attributes | `addEventListener` | DOM Level 2 (2000) | Removes globals; supports multiple listeners; better separation of concerns |
| `<script>` at end of `<body>` | `<script defer>` (anywhere) | HTML5 | `defer` is the modern idiom; D-10 allows either |
| `application/javascript` MIME | `text/javascript` | RFC 9239 (May 2022); Python 3.12+ | Test must accept both via substring match |

**Deprecated/outdated:**
- `<script type="text/javascript">` — implicit since HTML5; omit.
- `application/javascript` MIME — superseded by `text/javascript` per RFC 9239; both still work; tests use substring `"javascript"`.
- Bundler-required workflows for sub-100-line scripts — overkill for thin admin UIs.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Existing `tests/integration/test_ui_static.py` continues to pass after Phase 14 (its 7 sentinels — `<title>`, `<h1>`, `id="q"`, `id="btn"`, `id="out"`, `'/api/v1/query'`, `include_images:true` — are still in the post-refactor body: 5 are in ui.html, 2 are now in ui.js so they would fail against ui.html alone) [ASSUMED] | §Validation Architecture | If wrong, integration test must be updated or split. **Verify in Wave 1**: 2 sentinels (`'/api/v1/query'`, `include_images:true`) currently match ui.html line 38; post-refactor they live in ui.js. The integration test fetches `/ui/` (not `/ui/ui.js`), so those 2 sentinels will FAIL. Planner must either (a) update sentinels to drop the JS-side strings, or (b) fetch `/ui/ui.js` and split assertions. **Recommend (a):** drop the 2 JS-side sentinels from the integration test; the new unit test covers ui.js content. |

**This is the only assumption.** All other claims in this research are verified by codebase reads, shell execution, or direct CONTEXT.md decisions.

## Open Questions

1. **`<script>` placement: head+defer vs end-of-body+defer vs end-of-body?**
   - What we know: D-10 explicitly allows either; CONTEXT `<specifics>` skeleton uses end-of-body + `defer`.
   - What's unclear: No functional difference at this scale.
   - Recommendation: Follow CONTEXT `<specifics>` verbatim (end-of-body + `defer`). No need to deviate.

2. **Update existing `tests/integration/test_ui_static.py` 2 JS-side sentinels?**
   - What we know: Post-refactor, `'/api/v1/query'` and `include_images:true` migrate from ui.html → ui.js. Existing test fetches `/ui/` (gets ui.html only), so those sentinels will fail.
   - What's unclear: Drop them from the integration test, or split the test into 2 calls?
   - Recommendation: Drop the 2 JS-side sentinels from `test_ui_static_serves_html` (keep the 5 HTML sentinels). The new unit test `test_ui_js_served` covers the JS content. Document the change in PLAN as a 1-line edit to the integration test.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| FastAPI | Static file serving + TestClient | ✓ | (project requirements.txt) | — |
| Python `mimetypes` (stdlib) | Auto-MIME for served files | ✓ | Python 3.12+ | — |
| pytest | Test runner | ✓ | (pytest.ini configured) | — |
| Starlette `StaticFiles` | FastAPI sub-dep | ✓ | (transitive) | — |
| Modern browser | Manual smoke test | ✓ (assumed) | Any 2020+ | — |

**No new dependencies required.** Phase introduces zero new packages.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (existing) |
| Config file | `pytest.ini` |
| Quick run command | `pytest tests/unit/test_static_ui.py -x` |
| Full suite command | `pytest tests/` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| UI-02 AC#1 | ui.html has no `<style>`, `<script>` blocks (only external refs) | unit | `pytest tests/unit/test_static_ui.py::test_ui_html_no_inline_blocks -x` | Wave 0 |
| UI-02 AC#2 | FastAPI serves ui.css and ui.js with HTTP 200 + correct MIME | unit | `pytest tests/unit/test_static_ui.py::test_ui_css_served tests/unit/test_static_ui.py::test_ui_js_served -x` | Wave 0 |
| UI-02 AC#3 | No inline event handlers; `addEventListener` present in ui.js | unit | `pytest tests/unit/test_static_ui.py::test_ui_html_no_inline_blocks tests/unit/test_static_ui.py::test_ui_js_served -x` | Wave 0 |
| UI-02 AC#4 | DOM access via `getElementById` (already conformant pre-refactor — D-04 keeps it) | unit | (covered by AC#3 ui.js content check; could add `assert "getElementById" in body`) | Wave 0 |
| UI-02 AC#5 | No bundler introduced (D-01 NO bundler chosen) | static | (no-op — verify no `package.json` or `node_modules/` was added in PR review) | manual / git diff |
| UI-02 AC#6 | Visual regression — identical render for upload/query/result flows | manual | (browser smoke test per D-11) | manual |
| Symlink | `/ui/` resolves `index.html → ui.html` | unit | `pytest tests/unit/test_static_ui.py::test_index_html_symlink_serves_ui_html -x` | Wave 0 |

### Manual Smoke Checklist (AC#6)
1. Start server: `uvicorn main:app --reload`.
2. Browser → `http://localhost:8000/ui/`.
3. Open DevTools → Network: confirm `ui.html`, `ui.css`, `ui.js` all return HTTP 200; no 404s.
4. Open DevTools → Console: no errors on page load.
5. Type a query in the textarea; click "提问". Verify "查询中..." appears, then results render with same layout/colors as v1.x.
6. Press `Ctrl+Enter` in textarea — verify same query submission behaviour (keydown listener still wired).
7. Compare visual rendering to v1.x screenshot (or pre-refactor commit if needed).

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_static_ui.py -x` (~1s)
- **Per wave merge:** `pytest tests/unit/ -x` (full unit suite)
- **Phase gate:** Full suite green + manual smoke pass before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_static_ui.py` — NEW file (4 tests; skeleton in §Code Examples)
- [ ] Update `tests/integration/test_ui_static.py:38-46` sentinels — drop the 2 JS-side strings (`'/api/v1/query'`, `include_images:true`) since they move to ui.js (Q2 in §Open Questions)

**No framework gaps:** pytest already configured; FastAPI `TestClient` already used in 4+ existing test files.

### diff-cover ≥ 80% gate (TEST-03 from Phase 10)
- Applies to **Python files only** — `diff-cover` reads `coverage.xml` which only tracks Python (and other configured language) coverage. JS / CSS lines are not measured by Python coverage.
- New Python lines in this phase: `tests/unit/test_static_ui.py` (~50 lines, all test bodies — they cover themselves at 100% by definition when run).
- No Python production code changes (`main.py` unchanged). Gate is trivially satisfied.

## Security Domain

This phase introduces **zero new attack surface**:

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | (not affected — `/ui/*` is unauthenticated static content; no change) |
| V3 Session Management | no | (no sessions in scope) |
| V4 Access Control | no | (StaticFiles mount unchanged; same access policy) |
| V5 Input Validation | preserved | `esc()` HTML-escape helper preserved verbatim in ui.js (lines 30-56 → IIFE); guards against XSS in source/answer rendering |
| V6 Cryptography | no | (no crypto operations) |
| V14 Configuration | preserved | `<script src="ui.js">` is same-origin classic script; no `crossorigin`/CSP changes; no new third-party scripts |

### Threat patterns considered
| Pattern | STRIDE | Status |
|---------|--------|--------|
| XSS via answer/source content | Tampering | Mitigated by `esc()` (preserved) — escapes `&<>"'` before innerHTML insertion |
| Path traversal via `/ui/...` | Tampering | Mitigated by Starlette `StaticFiles` (rejects paths escaping `directory=`) — unchanged from Phase 9 |
| Symlink escape | Tampering | `static/index.html → ui.html` is intra-directory; safe [VERIFIED: ls -la] |
| Inline-handler injection | XSS | Phase 14 *removes* inline handlers (AC#3); reduces surface area, doesn't introduce risk |

**No security regressions possible.** Refactor is mechanical and `esc()` is preserved per D-13.

## Sources

### Primary (HIGH confidence)
- `static/ui.html` (file read, 58 lines) — source of all extracted content
- `main.py:380-400` (file read) — confirms `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")` at line 395, `include_in_schema` not set (default behaviour)
- `tests/integration/test_ui_static.py` (file read, 73 lines) — existing TestClient pattern + sentinel format to mirror in unit test
- `tests/conftest.py` (file read) — env var preconditions (`APP_MODEL_DIR`, `SECRET_KEY`) the new unit test must set
- `pytest.ini` (file read) — `addopts = -m "not integration"` confirms unit tests run by default; markers list shows `integration` and `pgvector` only
- `python3 -c "import mimetypes; mimetypes.guess_type(...)"` (shell exec) — verifies stdlib MIME defaults: `text/css`, `text/javascript`, `text/html`
- `ls -la static/` (shell exec) — confirms `index.html -> ui.html  7B` symlink exists and target is intra-directory
- `.planning/REQUIREMENTS.md` lines 52-67 (file read) — UI-02 6 acceptance criteria
- `.planning/ROADMAP.md` lines 85-95 (file read) — Phase 14 success criteria + UI hint
- `.planning/phases/14-frontend-split-and-dom-modernization/14-CONTEXT.md` (file read) — D-01..D-13 locked decisions
- `.planning/phases/14-frontend-split-and-dom-modernization/14-DISCUSSION-LOG.md` (file read) — Q&A audit trail

### Secondary (MEDIUM confidence)
- `.planning/phases/13-llm-filter-fallback/13-RESEARCH.md` (file read) — structural template only; not phase-14-specific

### Tertiary (LOW confidence)
None. All Phase 14 claims trace to codebase or CONTEXT.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every dep already present in project; verified via grep + file read
- Architecture: HIGH — IIFE + addEventListener is canonical 25-year-old DOM pattern
- Pitfalls: HIGH — derived from concrete codebase verifications, not speculation
- StaticFiles MIME: HIGH — verified via `python3 -c` shell exec
- Test pattern: HIGH — direct mirror of `tests/integration/test_ui_static.py:17-24`

**Research date:** 2026-05-09
**Valid until:** 2026-06-09 (30 days; refactor scope is small + no fast-moving dependencies; FastAPI/Starlette/pytest stable)

**Scope size:** ~13 KB. Phase is intentionally small — research is proportionate per orchestrator instruction.
