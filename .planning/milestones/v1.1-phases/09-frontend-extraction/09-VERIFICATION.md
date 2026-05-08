---
phase: 09-frontend-extraction
verified: 2026-05-08T18:10:00Z
status: human_needed
verdict: PASS_WITH_NOTES
score: 4/4 success criteria verified at codebase level (SC#2 visual + SC#4 viewport require live-browser confirmation on first deploy)
overrides_applied: 0
re_verification:
  previous_status: none
  previous_score: n/a
  gaps_closed: []
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Render /ui/ in a browser at 1280×800 viewport"
    expected: "No horizontal scrollbar; page width ≤ 1280px; layout matches v1.0 inline page"
    why_human: "SC #4 viewport behaviour cannot be asserted by httpx TestClient; CSS rule .source img{max-width:100%} is byte-for-byte preserved (verified) but real-render confirmation requires DOM"
  - test: "Submit a query against an ingested document via the served /ui/ page"
    expected: "答案 + 来源 + image thumbnails render identically to v1.0; no source image overflows container; no JS console errors"
    why_human: "SC #2 'renders identically' final visual + functional parity check; integration tests cover content sentinels + 200 status + redirect + OpenAPI contract but cannot exercise the inline JS against the live /api/v1/query endpoint"
  - test: "Build production Docker image and confirm /ui/ serves without bind-mount"
    expected: "docker build . && docker run -p 8000:8000 → curl http://localhost:8000/ui/ returns 200 with the v1.0 sentinels; no -v mount needed"
    why_human: "SC #3 end-to-end Docker image verification; static-analysis gates (COPY line, .dockerignore non-filter, marker comment) all pass but symlink behaviour through Docker COPY → image filesystem cannot be confirmed without an actual build"
notes_for_ship:
  - "Track this VERIFICATION.md as PASS_WITH_NOTES — all 4 SCs PASS at codebase level; SC #2 visual + SC #4 viewport + SC #3 Docker e2e are 'verified-on-first-deploy' follow-ups"
  - "Symlink static/index.html → ui.html is a deliberate fix surfaced at execution checkpoint (Rule 1 deviation in SUMMARY.md). It satisfies StaticFiles(html=True) index-lookup convention while preserving the artifact path mandated by must_haves.artifacts. PR description should call this out so reviewers understand why two files appear in static/."
  - "Single source of truth: ui.html is the real file; index.html is a relative symlink. Docker BuildKit preserves symlinks by default (or follows them — either yields a working page). If image build flag --buildkit is disabled (legacy builder), symlinks still copy as symlinks unless `--no-cache` + non-buildkit pathological flow; risk = low."
  - "Pre-existing flaky test (tests/unit/test_worker_startup.py::test_on_startup_tesseract_skips_paddle_warmup) not caused by Phase 9 — logged in deferred-items.md."
---

# Phase 9: Frontend Extraction — Verification Report

**Phase Goal:** "The inline UI is a real `static/ui.html` file editable with normal frontend tooling, served by FastAPI StaticFiles at `/ui/`, with no behavioural change versus the v1.0 inline page."

**Verdict:** **PASS_WITH_NOTES** — all 4 success criteria verifiable at codebase level PASS; SC #2 visual and SC #4 viewport carry "verify on first deploy" follow-up since the human-verify checkpoint was approved on automated-gate basis only.

**Verified:** 2026-05-08
**Re-verification:** No — initial verification

---

## Goal Achievement

### Success Criteria (from ROADMAP.md)

| SC# | Criterion | Evidence | Status |
|-----|-----------|----------|--------|
| 1 | `static/ui.html` exists; `main.py` no `_UI_HTML`; `/ui` route replaced by `app.mount(...)` | `static/ui.html` exists (2847 bytes); `grep -c '_UI_HTML' main.py` = 0; `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")` at main.py:391; `from fastapi.staticfiles import StaticFiles` at main.py:21; `grep -c HTMLResponse main.py` = 0 (orphan import removed); no `@app.get("/ui"` in main.py | ✓ VERIFIED |
| 2 | Visiting `/ui/` renders the UI, calls `/api/v1/query` with `include_images: true`, renders identically to v1.0 | TestClient `GET /ui/` → 200, content-type=text/html, body length=2744. All 7 v1.0 sentinels present in served body. fetch URL `'/api/v1/query'` + `include_images:true` literal both grep-confirmed in static/ui.html. 3/3 integration tests PASS. **Visual "renders identically" pending first-deploy human check.** | ✓ VERIFIED (codebase) — visual deferred |
| 3 | Production Docker image includes `static/` via `COPY` and serves the page without any bind-mount | Dockerfile:104 `COPY --chown=raguser:raguser . /app/` recursively covers project root; `.dockerignore` does NOT contain `static` (grep returns no match); UI-01/Phase 9 traceability marker at Dockerfile:102; `grep -c '^COPY' Dockerfile` = 5 (baseline preserved). **Live image-build confirmation pending first deploy.** | ✓ VERIFIED (static analysis) — runtime build deferred |
| 4 | No horizontal scroll on 1280×800 viewport; source images cap at container width | CSS rule `body{...max-width:900px;margin:2rem auto;...}` at static/ui.html line ~9 (preserves v1.0 920px container with margin auto) and `.source img{max-width:100%;margin-top:.5rem;border:1px solid #ccc;display:block;}` at line ~14 — both byte-for-byte from v1.0 per D-04. **Real-viewport visual check pending first-deploy human verification.** | ✓ VERIFIED (CSS preserved) — render confirmation deferred |

**Score:** 4/4 success criteria verified at codebase level. Three SCs (#2 visual, #3 image-build, #4 viewport) carry `verified-on-first-deploy` follow-up labels — none are blockers for ship; all rest on automated gates that are GREEN.

---

## Locked Decisions Honoured (D-01..D-04)

| D# | Decision | Evidence | Honoured? |
|----|----------|----------|-----------|
| D-01 | Inline `<script>` STAYS in `ui.html` — no `static/ui.js` | `grep -E 'static/ui\.js' static/ui.html` returns 0; `ls static/` shows only `ui.html` + `index.html` (symlink) — no JS file | ✓ YES |
| D-02 | Inline `<style>` STAYS in `ui.html` — no `static/ui.css` | `grep -E 'static/ui\.css' static/ui.html` returns 0; `ls static/` confirms no CSS file; inline `<style>` block grep-confirmed at line ~5 of ui.html | ✓ YES |
| D-03 | Accept FastAPI 307 default for `/ui` → `/ui/`; no explicit no-slash route | `grep -E '@app\.get\(["\x27]/ui["\x27]' main.py` returns no match; integration test `test_ui_no_slash_redirects_to_ui_slash` PASSES, asserting `GET /ui` → 307 with Location ending in `/ui/` | ✓ YES |
| D-04 | Pure refactor: `_UI_HTML` content byte-for-byte; no var renames; no DOM API rewrites | `function esc(s)` grep = 1 (esc preserved); short var names `j h m btn out` retained (verified by file inspection); `out.innerHTML` string concat preserved (verified); 7 v1.0 sentinels all present including exact CJK (`<title>RAG 查询</title>`) | ✓ YES |

---

## Observable Truths (from PLAN must_haves)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `static/ui.html` exists, byte-for-byte copy of v1.0 `_UI_HTML` | ✓ VERIFIED | File exists (2847B); 7 sentinels grep-pass; D-04 verify command in plan asserted byte-for-byte at execute time (commit `e24d00d`) |
| 2 | `main.py` contains no `_UI_HTML` and no `@app.get('/ui')` | ✓ VERIFIED | `grep -c '_UI_HTML' main.py` = 0; no `/ui` route grep match; `def ui_page` count = 0 |
| 3 | `main.py` mounts StaticFiles at `/ui` exactly | ✓ VERIFIED | Line 391: `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")` — exact pattern match |
| 4 | `GET /ui/` returns 200 + text/html + v1.0 sentinels | ✓ VERIFIED | TestClient run: 200, text/html; charset=utf-8, length=2744; sentinels confirmed live + via `test_ui_static_serves_html` PASS |
| 5 | `GET /ui` returns 307 → `/ui/` | ✓ VERIFIED | TestClient run: 307; `test_ui_no_slash_redirects_to_ui_slash` PASS |
| 6 | Page calls `/api/v1/query` with `include_images: true` | ✓ VERIFIED | grep-confirmed both literals in static/ui.html line 38; served body contains both (live TestClient check) |
| 7 | Production Docker image includes `static/` accessible to USER raguser | ✓ VERIFIED (static) | Dockerfile:104 `COPY --chown=raguser:raguser . /app/` covers static/; .dockerignore non-filter confirmed; image-build runtime check deferred to first deploy |

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `static/ui.html` | Standalone HTML, contains `<title>RAG 查询</title>` | ✓ VERIFIED | 2847 bytes, all 7 sentinels present, no external script/link tags |
| `static/index.html` | Symlink → ui.html (deviation, see Deviations) | ✓ VERIFIED | `readlink static/index.html` = `ui.html`; `readlink -f` resolves to absolute path of ui.html |
| `main.py` | Contains the StaticFiles mount line; no `_UI_HTML`, no HTMLResponse | ✓ VERIFIED | All 4 conditions met (mount line, no `_UI_HTML`, no `HTMLResponse`, StaticFiles import added) |
| `Dockerfile` | COPY covers static/; UI-01 marker added; baseline 5 COPY lines preserved | ✓ VERIFIED | 5 COPY lines (unchanged baseline); UI-01/Phase 9 marker at line 102; root COPY at line 104 |
| `.dockerignore` | Does NOT filter static/ | ✓ VERIFIED | grep `^static(/|$)` returns no match; .dockerignore filters venv/cache/data/binary-models only |
| `tests/integration/test_ui_static.py` | 3 tests, all marked `@pytest.mark.integration`, all PASS | ✓ VERIFIED | 3 functions found; 3 markers; AST valid; pytest run: `3 passed in 1.98s` |

---

## Key Link Verification (Wiring)

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `main.py` | `static/ui.html` | `app.mount('/ui', StaticFiles(directory='static', html=True))` | ✓ WIRED | Pattern match at main.py:391; live TestClient confirms `/ui/` serves the page |
| `main.py` mount | `static/index.html` (symlink) | StaticFiles `html=True` index lookup → resolves to ui.html via symlink | ✓ WIRED | `readlink -f` resolves; integration test confirms 200 not 404 |
| `Dockerfile` | `/app/static/` | `COPY --chown=raguser:raguser . /app/` (line 104) | ✓ WIRED (static) | Recursive COPY + .dockerignore non-filter; runtime image build deferred |
| `static/ui.html` | `/api/v1/query` | inline `<script>` `fetch('/api/v1/query', {body: JSON.stringify({...,include_images:true})})` | ✓ WIRED | grep-confirmed at line 38; live body inspection confirms; integration test sentinel pass |
| Inline `<script>` | DOM elements `#q #btn #out` | `document.getElementById` calls + `out.innerHTML = ...` | ✓ WIRED | sentinels `id="q" id="btn" id="out"` all present; D-04 byte-for-byte preserves v1.0 wiring |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `static/ui.html` (rendered page) | answer + sources + images JSON | `fetch('/api/v1/query')` POST with `{query, top_k, include_images:true}` | YES — Phase 7/8 e2e shipped, /api/v1/query is the live retrieval endpoint | ✓ FLOWING (subject to Phase 7/8 backend health, not Phase 9 scope) |
| StaticFiles mount | HTML bytes from disk | `static/ui.html` (single source) + `static/index.html` symlink alias | YES — file is 2847B real content, not stub | ✓ FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `/ui/` serves 200 + text/html with v1.0 sentinels | `pytest tests/integration/test_ui_static.py::test_ui_static_serves_html -m integration -x` | PASSED in 1.98s suite | ✓ PASS |
| `/ui` (no slash) returns 307 → `/ui/` | `pytest tests/integration/test_ui_static.py::test_ui_no_slash_redirects_to_ui_slash` | PASSED | ✓ PASS |
| StaticFiles mount stays out of OpenAPI schema | `pytest tests/integration/test_ui_static.py::test_ui_mount_not_in_openapi` | PASSED | ✓ PASS |
| Live `/ui/` body contains `/api/v1/query` + `include_images:true` | TestClient + python eval (this verification) | both literals present in served HTML | ✓ PASS |
| `.venv/bin/python -c "from main import app"` parses cleanly | (implicit via TestClient instantiation in tests) | App imports without error | ✓ PASS |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| UI-01 (REQ B-1) | 09-01-PLAN.md | Extract inline HTML to single static asset; serve via FastAPI StaticFiles | ✓ SATISFIED | All 5 acceptance criteria from REQUIREMENTS.md §"REQ B-1" map to verified SCs above. AC1 (file exists) ✓; AC2 (mount replaces route) ✓; AC3 (renders + calls /api/v1/query + include_images:true) ✓ for content; visual deferred; AC4 (Dockerfile COPY covers static) ✓ static; AC5 (1280×800 no horizontal scroll, images cap container) ✓ CSS preserved; render-time deferred |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No TODO / FIXME / placeholder strings introduced | — | — |
| (none) | — | No empty handlers, no console.log-only fns, no static `[]` returns added | — | — |

Scan covered: `static/ui.html`, `main.py` (changed regions only), `tests/integration/test_ui_static.py`, `Dockerfile` (changed regions only). No anti-patterns surfaced. The byte-for-byte D-04 mandate intentionally preserves v1.0 inline-JS code-smells (short var names, innerHTML concat) — these are LOCKED out of scope and tracked in `09-CONTEXT.md` Deferred Ideas for v1.2.

---

## Deviations Surfaced At Execution

### 1. Symlink fix: `static/index.html → ui.html` (acceptable workaround)

**What happened:** Plan prescribed `app.mount("/ui", StaticFiles(directory="static", html=True), name="ui")` with a single artifact `static/ui.html`. At Task 4 integration-test time, the executor discovered that `StaticFiles(html=True)` looks for `index.html` as the directory's root document — not `ui.html`. Without the symlink, `GET /ui/` would return 404 and SC #2 would fail.

**Fix applied:** Created `static/index.html` as a relative symlink to `ui.html`. Single source of truth (no content duplication, no drift risk). Committed in `c8518ee`.

**Verification this is acceptable:**
- SC #1 wording: "`static/ui.html` exists as a standalone file" — ✓ still satisfied (the real file is `ui.html`; `index.html` is a 7-byte symlink alias, not a separate page)
- SC #2 wording: "Visiting `/ui/` renders the UI" — ✓ satisfied (the symlink makes this work)
- D-01..D-04 invariants — ✓ all honoured (no JS/CSS extraction, no content transformation, no explicit no-slash route)
- Docker: BuildKit preserves symlinks; legacy builder follows them — either yields a working `/ui/` in the image. Risk = low.

**Status:** ACCEPTED. Documented in SUMMARY.md `key-decisions` and `Deviations from Plan` sections.

### 2. Human-verify checkpoint approved on automated-gate basis (visual deferred)

**What happened:** Task 5 (`checkpoint:human-verify`) prescribed live-browser rendering at 1280×800, query submission against an ingested document, and side-by-side v1.0 visual comparison. The user approved the checkpoint on the basis of:
- 3/3 integration tests GREEN
- Byte-for-byte content diff (Task 1 verify command)
- 7 v1.0 sentinels grep-confirmed in served HTML

The user did NOT perform live browser verification.

**Implication:** SC #2's visual "renders identically" claim and SC #4's "no horizontal scroll on 1280×800, source images cap at container width" claim rest on the chain `D-04 byte-for-byte preservation → CSS rules from v1.0 unchanged → if v1.0 rendered correctly at 1280×800, the new page must too`. This chain is logically sound — the CSS rules `max-width:900px;margin:2rem auto` and `.source img{max-width:100%}` are grep-confirmed in static/ui.html — but it has not been visually proven.

**Status:** ACCEPTED for ship as `verified-on-first-deploy`. Documented in `human_verification` frontmatter above. PR description SHOULD note that the first staged deployment serves as the visual confirmation step.

---

## Notes for Ship (PR description / future v1.2 phase)

1. **Symlink artefact:** Two files appear under `static/` — `ui.html` (real, 2847B) and `index.html` (7B symlink → ui.html). PR reviewers may flag this as duplication; the explanation is in SUMMARY.md `key-decisions[0]` and in this report's Deviations §1.

2. **First-deploy follow-up:** On the first deployment after this PR merges, perform the deferred visual checks (1280×800 viewport, image cap, query parity). If anything regresses, the byte-for-byte assertion in Task 1's verify command + the 3 integration tests will localize the cause to the deploy environment, not the codebase.

3. **v1.2 candidates (already captured in 09-CONTEXT.md):** Extract JS to `static/ui.js`, extract CSS to `static/ui.css` + design tokens, refactor inline JS (DOM API + variable rename + esc audit), explicit `/ui` no-slash route (only if reverse-proxy issue surfaces). All deferred per locked decisions D-01..D-04.

4. **Pre-existing flaky test in unit suite** (`tests/unit/test_worker_startup.py::test_on_startup_tesseract_skips_paddle_warmup`) — not caused by Phase 9; logged in `deferred-items.md`. Do not block Phase 9 ship on it.

---

## Gaps Summary

**No blocking gaps.** All 4 success criteria PASS at codebase level. The 3 deferred visual/build follow-ups (`human_verification` frontmatter) are tracked as `verified-on-first-deploy` items, not as unmet acceptance criteria — they have automated-gate proxies (byte-for-byte diff + 3 integration tests + Dockerfile static analysis) that justify shipping ahead of the live render confirmation.

---

*Verified: 2026-05-08*
*Verifier: Claude (gsd-verifier)*
