---
phase: 20-websearchtool-real-implementation-tavily
plan: 04
subsystem: ui
tags: [ui, locator-token, static-js, render-branch, smoke-test]
type: execute
wave: 3
status: complete
completed: 2026-05-10
duration_min: 5
tasks_completed: 2
tasks_total: 2

requires:
  - 20-02 (RetrievedChunk shape contract: chunk_type="web", metadata.source=url)
provides:
  - "static/ui.js source-row branch: chunk_type === 'web' renders URL=<host>"
  - "hostOf(url) helper using browser-native URL constructor with '?' fallback"
  - "10 static-source assertion tests covering UI-SPEC §Verification Hooks"
affects:
  - "static/ui.css remains byte-identical (verified by git diff)"
  - "static/ui.html remains byte-identical (verified by git diff)"

tech_stack:
  added: []
  patterns:
    - "browser-native URL parsing (no regex, no manual scheme stripping)"
    - "try/catch fallback to '?' literal for parity with v1.4 (page_number ?? '?')"
    - "esc()-wrapped host string at HTML insertion site (XSS defence)"

key_files:
  created:
    - "tests/unit/test_static_ui_web_branch.py"
  modified:
    - "static/ui.js"
  unchanged_verified:
    - "static/ui.css"
    - "static/ui.html"

decisions:
  - "Locator-token swap is the entire visual contract — no new CSS, no new colors, no clickable hyperlink (per UI-SPEC §Visual-Treatment Delta)"
  - "Strict equality === 'web' (lowercase) — wrong-case 'WEB' / null / undefined / 'pdf' etc. fall through to v1.4 byte-identical 页= branch"
  - "host string passes through esc() before HTML concat — defends against homograph / unicode injection in metadata.source"
  - "ui.html sentinel test uses ACTUAL v1.4 baseline 'Agent 查询' wording (Rule 1 deviation: plan's stale 'RAG 查询' literal would have broken the test)"

requirements:
  - AGENT-12

commits:
  - hash: 3317949
    type: feat
    subject: "feat(20-04): web source row renders URL=<host>; non-web preserved byte-identical"
    files: [static/ui.js]
  - hash: d10f286
    type: test
    subject: "test(20-04): static-source assertions for web URL=<host> branch + ui.css invariant"
    files: [tests/unit/test_static_ui_web_branch.py]
---

# Phase 20 Plan 04: Static-UI Web-Branch Locator Token Summary

**One-liner:** Surgical 10-line edit to `static/ui.js` adding a `hostOf()` helper and a per-row locator ternary so `chunk_type === "web"` renders `URL=<host>` (plain text) while every other chunk_type preserves the v1.4 `页=<page_number>` rendering byte-identically; covered by 10 static-source assertions in a new `tests/unit/test_static_ui_web_branch.py`.

## Diff Surface

### static/ui.js (modified)

| Chunk | Lines | Description |
|-------|------:|-------------|
| Added: locator ternary inside `(j.data.sources \|\| []).forEach` | +3 | `const locator = (m.chunk_type === 'web') ? 'URL=' + esc(hostOf(m.source)) : '页=' + (m.page_number ?? '?');` |
| Modified: source-row `<div class="meta">…</div>` template literal | +1 / -1 | Replaced inline `· 页=' + (m.page_number ?? '?') +` with `· ' + locator + ' ·` |
| Added: `hostOf` helper adjacent to existing `esc` | +5 | `function hostOf(url){ try { return new URL(url).host; } catch(e) { return '?'; } }` (incl. surrounding blank line) |

`git diff --numstat static/ui.js` → `9\t1` (9 additions, 1 deletion = 10 total, within ≤12 cap).

### tests/unit/test_static_ui_web_branch.py (new)

10 tests, ~126 lines, zero external dependencies. Layout:

| Dimension (UI-SPEC §Verification Hooks) | Tests |
|-----------------------------------------|-------|
| 1. Copywriting | `test_url_label_literal_is_uppercase_ascii`, `test_page_label_preserved`, `test_url_question_mark_fallback_via_hostof` |
| 2. Visuals | `test_source_row_uses_existing_classes` |
| 3-5. Color / typography / spacing | `test_static_ui_css_has_no_web_specific_selector` (covers all three by asserting absence of `.source.web` / `.meta-web` / `[data-chunk-type]` selectors in `static/ui.css`) |
| 6. Registry safety / no clickable anchor | `test_url_is_plain_text_not_clickable_anchor` |
| Branch shape | `test_locator_ternary_uses_strict_equality`, `test_hostof_helper_present`, `test_host_passed_through_escape_helper` |
| HTML preservation | `test_ui_html_unchanged_sentinels` |

`uv run pytest tests/unit/test_static_ui_web_branch.py -v` → **10 passed in 0.03s**.

## Byte-Identity Proofs

```bash
$ git diff HEAD~2..HEAD -- static/ui.css
(empty — exit 0)

$ git diff HEAD~2..HEAD -- static/ui.html
(empty — exit 0)
```

`static/ui.css` and `static/ui.html` are byte-identical to the pre-Plan-20-04 state. UI-SPEC §Verification Hooks dimensions 3 / 4 / 5 (color / typography / spacing) all PASS by the empty-diff proof. `ui.html` (top-level) does not exist in this repo (only `static/ui.html` does), so the plan's `ui.html` invariant is vacuously satisfied.

## Acceptance Criteria — Task 1

| Criterion | Result |
|-----------|--------|
| `grep -c "function hostOf" static/ui.js` returns 1 | PASS |
| `grep -c "new URL(url).host" static/ui.js` returns 1 | PASS |
| `grep -c "chunk_type === 'web'" static/ui.js` returns 1 | PASS |
| `grep -c "URL=" static/ui.js` returns 1 | PASS |
| `grep -c "页=" static/ui.js` returns 1 | PASS |
| `grep -c "esc(hostOf(" static/ui.js` returns 1 | PASS |
| `grep -cE "<a " static/ui.js` returns 0 (no clickable anchor) | PASS |
| `git diff --numstat static/ui.css` shows 0/0 | PASS (empty diff) |
| `git diff --numstat static/ui.html` shows 0/0 | PASS (empty diff) |
| `git diff --numstat static/ui.js` shows ≤ 12 line delta | PASS (9+1=10) |
| Brace-balance smoke check (`{`/`}` balanced) | PASS |
| Node parse / eval reaches DOM-binding line (file syntactically valid; runtime `document is not defined` is expected outside a browser, not a parse error) | PASS |

## Acceptance Criteria — Task 2

| Criterion | Result |
|-----------|--------|
| `tests/unit/test_static_ui_web_branch.py` exists | PASS |
| `pytest --collect-only` lists ≥ 9 test items | PASS (10 collected) |
| `pytest -x` exits 0 | PASS (10 passed) |
| `grep -c "ui_js_src" …` ≥ 8 | PASS (25) |
| Zero `from (fastapi\|httpx\|playwright\|selenium)` imports | PASS (0) |
| Commit message starts with `test(20-04):` | PASS |

## Threat Mitigation Status (from PLAN.md threat_model)

| Threat ID | Disposition | Implemented Mitigation |
|-----------|-------------|------------------------|
| T-20-16 (DOM injection via crafted host) | mitigate | `hostOf` returns parsed `host` (or `?`); value passes through `esc()` before HTML concat. Asserted by `test_host_passed_through_escape_helper`. |
| T-20-17 (SSRF via clickable anchor) | accept | No `<a href>` rendering. Asserted by `test_url_is_plain_text_not_clickable_anchor`. |
| T-20-18 (homograph / IDN spoof) | accept | Display-only; no fetch. Browser-native `URL` constructor used per UI-SPEC §Host Extraction Rule. |
| T-20-19 (unauthorized CSS edit) | mitigate | `git diff static/ui.css` empty across both commits. Asserted by `test_static_ui_css_has_no_web_specific_selector`. |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 – Bug] HTML sentinel test text drift**
- **Found during:** Task 2 (writing `test_ui_html_unchanged_sentinels`)
- **Issue:** Plan-text snippet asserted sentinels `<title>RAG 查询</title>` and `<h1>RAG 查询界面</h1>`. The actual `static/ui.html` baseline (v1.4) contains `<title>Agent 查询</title>` and `<h1>Agent 查询界面 …</h1>` — the v1.4 phase already migrated the wording from "RAG" to "Agent". Plan-as-written would have produced an immediately-failing test for a non-existent regression.
- **Fix:** Updated the sentinel literals in the test to match the actual v1.4 baseline. The test still verifies the unchanged-HTML invariant (the asserted strings are the real strings present in `static/ui.html`); the spec intent (HTML untouched by Phase 20) is preserved.
- **Files modified:** `tests/unit/test_static_ui_web_branch.py`
- **Commit:** `d10f286`

### Auth Gates

None. Plan executed with no external service interaction.

## Hand-Off

Plan 20-05 (Wave 4 — type:execute, depends_on=[01,02,03,04]) includes a human-verify checkpoint that runs a mixed query (one web result + one PDF result) against the live UI and confirms the rendered output matches the UI-SPEC §Mixed-Result Rendering visual sample. The 10 static-source assertions in this plan cover the source-shape contract; the 20-05 checkpoint covers the rendered-pixel behavior end-to-end. Together they validate ROADMAP SC4 / AGENT-12.

## Verification

- [x] `uv run pytest tests/unit/test_static_ui_web_branch.py -v` — 10 passed
- [x] `git diff HEAD~2..HEAD -- static/ui.css` — empty
- [x] `git diff HEAD~2..HEAD -- static/ui.html` — empty
- [x] `git diff HEAD~2..HEAD -- static/ui.js` — 9 add / 1 del (≤12 cap)
- [x] No `<a href>` introduced (`grep -cE "<a " static/ui.js` → 0)
- [x] No new CSS classes (`.source.web` / `.meta-web` / `[data-chunk-type]` absent)

## Self-Check: PASSED

All claimed files exist and all claimed commits are present in `git log`.
