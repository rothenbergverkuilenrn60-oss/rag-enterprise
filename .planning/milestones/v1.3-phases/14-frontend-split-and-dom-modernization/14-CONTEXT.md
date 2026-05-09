# Phase 14: Frontend Split and DOM Modernization - Context

**Gathered:** 2026-05-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract inline `<style>` and `<script>` from `static/ui.html` into separate `static/ui.css` and `static/ui.js`. Replace the single `onclick="ask()"` inline handler with `addEventListener` wired on `DOMContentLoaded`. Wrap JS in IIFE to avoid global namespace pollution. Preserve FastAPI `StaticFiles` mount at `/ui/` and the `static/index.html → ui.html` symlink. Manual smoke test for visual regression — no automated visual diff in this phase.

Out of scope:
- Bundler / package.json / node_modules (AC#5 explicit "decided at implementation time" — decision: NO bundler for 29 lines of JS)
- Frontend framework (React/Vue/Svelte) — refactor is plain HTML/JS/CSS only
- E2E browser tests (Playwright/Cypress) — manual smoke test sufficient per STATE.md Phase 14 notes
- New UI features (search history, dark mode, etc.) — refactor only, identical visual output (AC#6)
</domain>

<decisions>
## Implementation Decisions

### Architecture
- **D-01:** No bundler. AC#5 makes bundler optional and explicitly says "If not needed, no bundler is introduced." 29 lines of JS does not benefit from ES module splitting. Single `static/ui.js` file. Single `static/ui.css` file. Zero new build infra (no package.json, no node_modules).
- **D-02:** Classic `<script src="ui.js">` (NOT `type="module"`). JS wrapped in IIFE pattern: `(function(){ "use strict"; ... })();`. Avoids global `ask()` function. `"use strict"` enables strict mode without ESM (since classic scripts default to sloppy mode).
- **D-03:** Single `static/ui.css` (NOT split into base + components). 14 lines CSS doesn't justify multi-file organization.

### DOM API + Event Wiring
- **D-04:** Keep `document.getElementById(...)` calls (already 6x in current code). Do NOT migrate to `querySelector` or `data-action` attributes — convention not present elsewhere in codebase.
- **D-05:** Wire all event listeners inside a `DOMContentLoaded` handler at the bottom of the IIFE. Replaces the single `onclick="ask()"` (line 26) with `document.getElementById('btn').addEventListener('click', ask)`. The existing `addEventListener('keydown', ...)` at line 56 stays inside the same `DOMContentLoaded` block.
- **D-06:** Cache element refs as local consts inside the IIFE only when accessed multiple times (#q is read 1x, #topk 1x, #out 2x, #btn 2x — keep inline `getElementById` calls; no premature caching).

### Helper Functions
- **D-07:** `esc()` helper stays inside ui.js (not extracted to a separate utils file). Only one consumer; extraction is YAGNI.

### Serving / FastAPI Layer
- **D-08:** `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")` is UNCHANGED. The existing mount serves any file in `static/` automatically — `ui.css` and `ui.js` will be served at `/ui/ui.css` and `/ui/ui.js` without main.py changes.
- **D-09:** `static/index.html → ui.html` symlink is UNCHANGED. Verified at `static/index.html` (size 7B, points to `ui.html`).
- **D-10:** ui.html `<head>` references: `<link rel="stylesheet" href="ui.css">` (not `/ui/ui.css` — relative path resolves under StaticFiles mount). `<script src="ui.js"></script>` placed at end of `<body>` for natural DOM availability without `defer` (or use `defer` attribute for safety).

### Testing
- **D-11:** No new automated UI tests in this phase. Manual smoke test (per STATE.md): document upload → query submission → result display. Browser dev tools verify no console errors, no 404s for ui.css / ui.js, sources panel renders identically.
- **D-12:** Add a minimal pytest verifying FastAPI serves all 3 files (ui.html, ui.css, ui.js) with HTTP 200 + correct Content-Type. Catches regression if mount config breaks. Single test file `tests/unit/test_static_ui.py` using FastAPI TestClient — already a project pattern.

### Failure Handling
- **D-13:** No JS error handling changes — existing `try/catch` on fetch stays as-is. esc() helper stays as-is. Refactor is mechanical extraction, not behavior change.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirement
- `.planning/REQUIREMENTS.md` §UI-02 (lines 52-67) — 6 acceptance criteria
- `.planning/ROADMAP.md` §Phase 14

### Core Codebase
- `static/ui.html` (58 lines, 2.8 KB) — FILE BEING REFACTORED. Inline `<style>` lines 6-19 (14 lines CSS), inline `<script>` lines 29-57 (29 lines JS). Single `onclick="ask()"` at line 26. Single existing `addEventListener` at line 56.
- `static/index.html` — symlink to `ui.html` (7 bytes, PRESERVE)
- `main.py:395` — `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")` (UNCHANGED)

### Prior Phase Context
- v1.1 Phase 9: FastAPI StaticFiles mount + symlink. Phase 14 reuses both verbatim.
- v1.1 Phase 10 TEST-03: `diff-cover ≥ 80%` gate on v1.1+ files. New `static/ui.js` and `static/ui.css` lines must satisfy this gate. Trivial since the test file (`tests/unit/test_static_ui.py`) covers HTTP-200 paths.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- FastAPI `TestClient` pattern — used elsewhere in project for API tests. Same pattern applies to static file serving.
- `StaticFiles(directory="static", html=True)` mount config — automatically serves any file in `static/`, no per-file registration needed.

### Established Patterns
- **Conventional commit format** — `feat(14-XX): ...` for refactor, `test(14-XX): ...` for test addition.
- **Manual smoke test for visual changes** — STATE.md Phase 14 notes: "no automated visual diff required."

### Integration Points
- `static/ui.html` (refactored) → `static/ui.css` (new) + `static/ui.js` (new). Three files served via existing FastAPI mount.
- No backend code changes. main.py unchanged. Pipeline / API unchanged.
</code_context>

<specifics>
## Specific Ideas

### IIFE Skeleton for ui.js
```javascript
(function(){
  "use strict";

  async function ask(){
    const q = document.getElementById('q').value.trim();
    if(!q) return;
    // ... existing body ...
  }

  function esc(s){
    return (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('btn').addEventListener('click', ask);
    document.getElementById('q').addEventListener('keydown', e => {
      if(e.ctrlKey && e.key==='Enter') ask();
    });
  });
})();
```

### ui.html Skeleton (post-refactor)
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
<textarea id="q" rows="3" placeholder="..."></textarea>
<div class="row">
  <label>top_k: <input type="number" id="topk" value="5" min="1" max="20" style="width:4rem;"></label>
  <button id="btn">提问</button>
</div>
<div id="out"></div>
<script src="ui.js" defer></script>
</body>
</html>
```

Note: `defer` on `<script>` ensures it executes after DOM parse but before `DOMContentLoaded`, removing any need to gate on it. (If using DOMContentLoaded inside IIFE per D-05, both belt-and-suspenders is fine but `defer` alone is sufficient.)

### Test Skeleton (`tests/unit/test_static_ui.py`)
```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_ui_html_served():
    r = client.get("/ui/ui.html")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert '<script src="ui.js"' in r.text
    assert '<link rel="stylesheet" href="ui.css"' in r.text
    assert "<style>" not in r.text  # AC#1 enforcement
    assert 'onclick=' not in r.text  # AC#3 enforcement

def test_ui_js_served():
    r = client.get("/ui/ui.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"].lower()

def test_ui_css_served():
    r = client.get("/ui/ui.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]

def test_index_redirects_to_ui_html():
    r = client.get("/ui/")
    assert r.status_code == 200
    assert "RAG 查询界面" in r.text  # served via index.html → ui.html symlink
```

### File Layout (final)
```
static/
├── ui.html              # 58 → ~28 lines (reduced; inline blocks gone)
├── ui.css               # NEW, 14 lines
├── ui.js                # NEW, ~33 lines (IIFE-wrapped)
└── index.html           # symlink → ui.html (PRESERVED)

tests/unit/
└── test_static_ui.py    # NEW, 4 tests (HTTP 200 + content assertions)

main.py                  # UNCHANGED
```
</specifics>

<deferred>
## Deferred Ideas

- Bundler (Vite/esbuild) — overkill for 29 lines; revisit if ui.js grows past ~200 lines or splits into multiple modules
- Frontend framework migration — out of scope; v1.x is a thin admin UI
- Dark mode / theme toggle — feature work, not refactor
- Search history / saved queries — feature work
- Playwright E2E browser tests — manual smoke test sufficient at this scale; revisit if UI complexity grows
- Source maps — no transpilation, original JS already debuggable
- TypeScript migration — speculative; would require bundler
</deferred>

---

*Phase: 14-Frontend-Split-and-DOM-Modernization*
*Context gathered: 2026-05-09*
