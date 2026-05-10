---
phase: 20
slug: websearchtool-real-implementation-tavily
status: draft
shadcn_initialized: false
preset: none
created: 2026-05-10
---

# Phase 20 — UI Design Contract

> Visual and interaction contract for the source-row rendering delta required by AGENT-12 / SC4. Scope is intentionally thin: a single ternary branch in `static/ui.js` and a host-extraction helper. No new components, no layout changes, no typography overhaul.

---

## Scope (binding)

In scope for this UI-SPEC:

- Source-row rendering contract for `chunk_type === "web"` vs all other chunk types (PDF / text / image / table / etc.)
- Host extraction rule from `metadata.source` (URL parsing + malformed URL fallback)
- Mixed-result rendering (a single answer block interleaves web and pdf source rows)
- Empty / fallback rendering when `metadata.source` is missing or unparseable
- Visual treatment delta vs the existing PDF source row (ZERO delta — only the page-vs-URL token swap)

Out of scope (do NOT touch in Phase 20):

- Layout, typography, color system audit — none change
- Error placeholder source rows for failed `web_search` (CONTEXT D-16 — empty `chunks=[]` renders nothing)
- Banner / toast / degraded-mode UX (deferred to v1.6+)
- React/Vue migration (UI-03, deferred per REQUIREMENTS.md "Out of Scope")
- Image rendering, score formatting, escaping helpers — preserved verbatim from v1.4

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none (vanilla JS + handwritten CSS, locked since v1.1 Phase 9) |
| Preset | not applicable |
| Component library | none |
| Icon library | none (text-only labels — `URL=`, `页=`, `类型=`, `score=`) |
| Font | `-apple-system, sans-serif` (system stack from `static/ui.css:1`) |

**Rationale:** Phase 20 changes one ternary in `static/ui.js`. Initializing shadcn or any component library is out of scope and would violate v1.1 Phase 9's frontend extraction contract. UI-03 React/Vue migration is explicitly deferred per REQUIREMENTS.md.

---

## Source-Row Rendering Contract

**File:** `static/ui.js` (single render branch in the `(j.data.sources || []).forEach` loop)

**Current line (v1.4 baseline, line 28):**

```javascript
h += '<div class="source"><div class="meta">来源' + (i+1) + ' · 页=' + (m.page_number ?? '?') + ' · 类型=' + (m.chunk_type || '?') + ' · score=' + score.toFixed(3) + '</div>';
```

**Phase 20 contract (mandatory shape):**

```javascript
const locator = (m.chunk_type === 'web')
  ? 'URL=' + esc(hostOf(m.source))
  : '页=' + (m.page_number ?? '?');
h += '<div class="source"><div class="meta">来源' + (i+1) + ' · ' + locator + ' · 类型=' + (m.chunk_type || '?') + ' · score=' + score.toFixed(3) + '</div>';
```

| Token in source-row | When `chunk_type === "web"` | When `chunk_type !== "web"` (pdf / text / image / table / null / undefined) |
|---------------------|------------------------------|------------------------------------------------------------------------------|
| `来源N` | unchanged — same prefix | unchanged — same prefix |
| Locator token | `URL=<host>` | `页=<page_number ?? '?'>` |
| `类型=` | unchanged — `web` | unchanged — current value or `?` |
| `score=` | unchanged — `score.toFixed(3)` | unchanged — `score.toFixed(3)` |
| Content `<div>` | unchanged — `esc(s.content)` (Tavily snippet verbatim per CONTEXT D-12) | unchanged |
| Optional `<img>` | not emitted (web chunks have no `image_b64`) | unchanged — emitted iff `m.image_b64` |

**Branch invariants:**

1. The `chunk_type` field check is `=== "web"` (strict equality, lowercase). Any other value — including `"pdf"`, `"text"`, `"image"`, `"table"`, `null`, `undefined`, `"WEB"` (wrong case) — falls through to the existing `页=...` branch. Source: CONTEXT D-12 + REQUIREMENTS AGENT-12.
2. PDF / text / image / table / null source-row rendering is byte-identical to v1.4. Verified by snapshot test on a non-web fixture.
3. No new CSS classes, no new colors, no new spacing. The `.source` and `.meta` classes from `static/ui.css` are reused unchanged.
4. Mixed-result rendering: when `data.sources` interleaves web and non-web entries (e.g., index 0 is web, index 1 is pdf), each source row is rendered independently by the same `forEach` loop — the branch decision is per-row. No grouping, no sorting, no section headers.

---

## Host Extraction Rule

**Helper function** (added once to `static/ui.js`, before the `ask` function or near `esc`):

```javascript
function hostOf(url){
  try { return new URL(url).host; }
  catch(e) { return '?'; }
}
```

**Contract:**

| `metadata.source` value | `hostOf(source)` returns | Rendered token |
|--------------------------|--------------------------|----------------|
| `"https://example.com/path?q=1"` | `"example.com"` | `URL=example.com` |
| `"https://www.example.com:8080/x"` | `"www.example.com:8080"` | `URL=www.example.com:8080` |
| `"http://localhost"` | `"localhost"` | `URL=localhost` |
| `"https://中文.example.com/x"` | host as Punycode-or-Unicode per browser `URL` semantics | passes through `esc()` → safe |
| `""` (empty string) | `"?"` (URL constructor throws → catch returns `'?'`) | `URL=?` |
| `null` / `undefined` (missing field) | `"?"` (URL constructor throws on non-string) | `URL=?` |
| `"not a url"` (malformed) | `"?"` | `URL=?` |
| `"ftp://files.example.com/a"` | `"files.example.com"` (URL accepts non-http schemes) | `URL=files.example.com` |

**Invariants:**

1. The `URL` constructor is the SOLE parsing primitive. No regex, no `split('/')`, no manual scheme stripping. Browser-native parsing avoids hand-rolled parser bugs.
2. ALL exceptions are caught (`catch(e)`) and yield `'?'`. The render NEVER crashes on malformed input.
3. The host string is passed through `esc()` at the call site so any unicode / homograph host renders as escaped HTML text. This is consistent with how `m.page_number` is already implicitly safe (it's a number) and how `s.content` is already escaped.
4. No truncation, no ellipsis, no max-length. Hosts are short by nature; if a Tavily result returns an unusually long host the meta line wraps via the existing `.source .meta` CSS (`color:#666;font-size:.82rem`) — no special handling.
5. The literal `?` fallback is intentionally identical to the existing `页=?` fallback when `page_number` is null. Visual consistency: a missing locator looks the same in both branches.

---

## Spacing Scale

The existing UI does NOT declare a token scale; it uses raw CSS values from `static/ui.css`. Phase 20 introduces no new spacing. The values below document the existing surface so the executor knows what NOT to change.

| Existing CSS rule | Value | Source | Phase 20 status |
|-------------------|-------|--------|-----------------|
| `body` margin | `2rem auto` | `ui.css:1` | unchanged |
| `body` padding | `0 1rem` | `ui.css:1` | unchanged |
| `body` max-width | `900px` | `ui.css:1` | unchanged |
| `.row` gap | `1rem` | `ui.css:4` | unchanged |
| `.row` margin | `.5rem 0` | `ui.css:4` | unchanged |
| `button` padding | `.5rem 1.2rem` | `ui.css:5` | unchanged |
| `.answer` padding | `1rem` | `ui.css:7` | unchanged |
| `.answer` margin | `1rem 0` | `ui.css:7` | unchanged |
| `.source` padding | `.8rem` | `ui.css:8` | unchanged |
| `.source` margin | `.5rem 0` | `ui.css:8` | unchanged |
| `.meta` margin-bottom | `.4rem` | `ui.css:10` | unchanged |

**Exception:** The 8-point scale lint is N/A for Phase 20 — no CSS file is touched.

---

## Typography

The existing UI does NOT declare a typographic scale. Phase 20 adds no new text styles. The table below documents the existing surface (read-only reference for executor / checker).

| Role | Existing CSS | Source | Phase 20 status |
|------|--------------|--------|-----------------|
| Body / default | `-apple-system, sans-serif`, `1rem` (default), color `#222` | `ui.css:1` | unchanged |
| `h1` | `1.3rem` | `ui.css:2` | unchanged |
| `h1 small` (version tag in `ui.html:9`) | `0.5em` of parent, color `#888` | inline | unchanged |
| `.answer` body text | inherits `1rem`, `white-space:pre-wrap` | `ui.css:7` | unchanged |
| `.meta` (source row metadata — THE Phase 20 surgery line) | `0.82rem`, color `#666` | `ui.css:10` | unchanged — `URL=<host>` token uses the same `.meta` class |
| `textarea` | `1rem`, `font-family:inherit` | `ui.css:3` | unchanged |
| `.loading` | inherits, italic, color `#888` | `ui.css:11` | unchanged |
| `.err` | inherits, color `#c00` | `ui.css:12` | unchanged |

**Exception:** The "3–4 sizes / 2 weights" rule is N/A for Phase 20 — no typography is changed; the existing surface uses default browser weights (400 / 700) and a `1rem` / `1.3rem` / `0.82rem` / `0.5em` spread inherited from the v1.1 Phase 9 frontend extraction.

---

## Color

Phase 20 introduces no new colors. The web-source row reuses `.meta` (color `#666` on white) — visually identical to the existing PDF source row. Documented for completeness:

| Role | Existing value | Source | Phase 20 status |
|------|---------------|--------|-----------------|
| Background (dominant) | `#fff` (default body background) | implicit | unchanged |
| Body text | `#222` | `ui.css:1` | unchanged |
| Accent (`.answer` left border + button background) | `#0a66c2` | `ui.css:5,7` | unchanged — web rows do NOT use accent |
| Card border (`.source`) | `#ddd` | `ui.css:8` | unchanged — same border for web rows |
| Image border | `#ccc` | `ui.css:9` | N/A for web (no image) |
| Meta / muted text | `#666` | `ui.css:10` | unchanged — `URL=<host>` token rendered in `.meta` |
| Muted text 2 (`.loading`, `h1 small`) | `#888` | `ui.css:9, 11` | unchanged |
| Error / destructive | `#c00` | `ui.css:12` | unchanged |

**Accent reserved for:** `.answer` left border (4px) and the primary button (`提问`) background. NEVER applied to source rows — web or otherwise. This is the existing v1.4 contract; Phase 20 preserves it exactly.

**Phase 20 invariant:** Web source rows MUST NOT introduce a different border color, background tint, or icon to "stand out" from PDF rows. The locator token swap (`URL=` vs `页=`) is the ONLY visual signal. Rationale: visual differentiation between source types is a UX concern deferred to v1.6+ per CONTEXT D-16 (degraded-mode UX kept minimal).

---

## Copywriting Contract

| Element | Copy | Source |
|---------|------|--------|
| Locator label for web chunks | `URL=<host>` (literal `URL=` prefix, ASCII, uppercase) | REQUIREMENTS AGENT-12 + CONTEXT D-12 |
| Locator label for non-web chunks | `页=<page_number>` (CJK character + `=`, unchanged from v1.4) | `static/ui.js:28` baseline |
| Host fallback (malformed / missing URL) | `?` (single ASCII question mark) | matches existing `(m.page_number ?? '?')` fallback for visual consistency |
| Source row prefix | `来源N` (CJK + index, unchanged) | `static/ui.js:28` baseline |
| Type token | `类型=<chunk_type>` or `类型=?` (unchanged) | `static/ui.js:28` baseline |
| Score token | `score=<n.nnn>` (unchanged, 3 decimals) | `static/ui.js:28` baseline |
| Empty state for failed `web_search` | NONE — failed `web_search` returns `chunks=[]`; the source loop iterates zero entries; the synthesizer's natural-language answer prose conveys degraded-mode (CONTEXT D-13 + D-16) | CONTEXT D-16 |
| Error state for fetch failure | unchanged: `请求失败：<error>` (`static/ui.js:35`) | v1.4 baseline |
| Primary CTA | unchanged: `提问` (`ui.html:13`) | v1.4 baseline |

**Copy invariants:**

1. The literal label is `URL=` (uppercase Latin), NOT `网址=` or `链接=` or `Source=`. Rationale: matches REQUIREMENTS AGENT-12 verbatim, parallels machine-readable `score=` / `类型=` token style, and is visually distinguishable from `页=` (CJK).
2. The fallback character is a single ASCII `?`, identical to the existing `页=?` fallback. NOT `—`, NOT `(unknown)`, NOT empty string.
3. Phase 20 introduces NO empty-state copy, NO error-state copy, NO destructive-action copy. Failed web_search renders zero source rows by design (CONTEXT D-16); the synthesizer answer prose carries the user-facing message (CONTEXT D-13 strings: "Web search not configured…" / "Web search quota exhausted today…" / "Web search temporarily unavailable…"). Those strings are produced by `WebSearchTool.run()` typed-error `ToolResult.content` and consumed by the planner LLM, NOT rendered by `static/ui.js` directly.
4. No destructive actions exist in Phase 20. No confirmation copy required.

---

## Mixed-Result Rendering

**Scenario:** `data.sources = [web, pdf, web, pdf]` (interleaved).

**Contract:**

1. The existing `forEach((s, i) => {...})` loop iterates each source independently.
2. Per-row branch: `m.chunk_type === "web"` decides locator format. No grouping, no reordering, no section dividers.
3. Index `i+1` is the array position (NOT a per-type counter). A web row at array position 2 renders as `来源3 · URL=...`, NOT `来源1 · URL=...`.
4. The source-rank ordering is decided upstream (planner / executor / synthesizer / `_dedup_chunks`). The UI is a pure renderer. No client-side sort.

**Visual sample (rendered output):**

```
来源（4）
┌──────────────────────────────────────────────────┐
│ 来源1 · 页=12 · 类型=pdf · score=0.842            │
│ <PDF snippet content...>                          │
│ [optional <img>]                                  │
├──────────────────────────────────────────────────┤
│ 来源2 · URL=example.com · 类型=web · score=0.731  │
│ <Tavily snippet content verbatim...>              │
├──────────────────────────────────────────────────┤
│ 来源3 · 页=? · 类型=text · score=0.654            │
│ <text chunk content...>                           │
├──────────────────────────────────────────────────┤
│ 来源4 · URL=? · 类型=web · score=0.612            │
│ <Tavily snippet with malformed metadata.source>   │
└──────────────────────────────────────────────────┘
```

(Box drawing illustrative only; actual render uses the existing `.source` CSS — 1px solid `#ddd` border, 4px radius, `0.8rem` padding.)

---

## Visual-Treatment Delta vs PDF Source Row

| Aspect | PDF source row (existing) | Web source row (Phase 20) | Delta? |
|--------|---------------------------|---------------------------|--------|
| Container | `.source` (border, padding, radius) | `.source` | NO |
| Meta line color/size | `.meta` (`#666`, `0.82rem`) | `.meta` | NO |
| Prefix | `来源N` | `来源N` | NO |
| Locator token | `页=<page_number>` | `URL=<host>` | YES — swap only |
| Type token | `类型=pdf` | `类型=web` | NO (driven by data) |
| Score token | `score=0.842` | `score=0.842` (Tavily score per CONTEXT D-11) | NO |
| Content | `esc(s.content)` | `esc(s.content)` (Tavily snippet verbatim per CONTEXT D-12) | NO |
| Image | optional `<img>` if `m.image_b64` | never (Tavily returns no image_b64) | implicit |
| Truncation | none | none | NO |
| Click target / hyperlink | none — content is plain text | none — `URL=<host>` is plain text, NOT a clickable `<a>` | NO |
| Icon | none | none | NO |

**The locator token swap is the ENTIRE visual contract.** Anything more is out of scope.

**Note on hyperlinks:** Phase 20 does NOT render `URL=<host>` as a clickable `<a>` element. Rationale: (a) clickable web sources is a UX evolution belonging to a frontend phase, not a tool-integration phase; (b) the full URL is in `metadata.source` and available to downstream tooling / future UI iterations; (c) keeps the `static/ui.js` patch surface ≤ 6 lines per CONTEXT integration-points table.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | none | not applicable (project uses no design system) |
| Third-party | none | not applicable |

No registries are in use. Phase 20 ships pure vanilla JavaScript with no third-party UI dependencies. SC5 (the TAVILY_API_KEY redaction gate) is a backend concern (`WebSearchTool` source-side redaction per CONTEXT D-15) and is tracked in the planner / executor specs, not here.

---

## Verification Hooks

The checker validates these dimensions against this UI-SPEC. Each maps to a concrete inspection target.

| Dimension | Validation target | Pass criterion |
|-----------|-------------------|----------------|
| 1. Copywriting | `static/ui.js` source-row meta string | Literal `URL=` + host (no localization, no `网址`); fallback `?` matches `页=?` fallback |
| 2. Visuals | `.source` / `.meta` CSS classes referenced | Web row uses identical classes as PDF row; no new classes introduced |
| 3. Color | No new color values in `static/ui.css` | `git diff static/ui.css` is empty (or contains only whitespace / comment edits) |
| 4. Typography | No new font-size / weight in `static/ui.css` | `git diff static/ui.css` is empty for typography rules |
| 5. Spacing | No new spacing in `static/ui.css` | `git diff static/ui.css` is empty for spacing rules |
| 6. Registry Safety | No new dependencies in `package.json` (file does not exist) or new `<script>` / `<link>` tags in `ui.html` | `ui.html` diff is empty; no new script srcs |

Additionally, an executor-side smoke test (SC4 from ROADMAP) verifies a mixed query renders both source types correctly. This is a behavioral test, not a UI-spec test.

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending

---

## Appendix: Pre-Population Provenance

| Section | Decision Source |
|---------|-----------------|
| Design System (vanilla JS, no shadcn) | Existing codebase (`static/ui.{js,css,html}` from v1.1 Phase 9); REQUIREMENTS.md UI-03 deferred |
| Locator token contract (`URL=<host>`) | REQUIREMENTS AGENT-12; ROADMAP Phase 20 SC4; CONTEXT D-12 |
| Host extraction rule (`new URL().host` + `?` fallback) | CONTEXT "Claude's Discretion" — UI host extraction wording |
| PDF row preservation | REQUIREMENTS AGENT-12; CONTEXT scope_note + D-16 |
| Empty state for failed `web_search` (none) | CONTEXT D-16 |
| Snippet content rendering (verbatim, escaped) | CONTEXT D-12 |
| Score rendering (Tavily score → `score=` token) | CONTEXT D-11 |
| No new colors / spacing / typography | Existing `static/ui.css` (v1.1 Phase 9 baseline) + scope_note |
| No clickable hyperlink for `URL=<host>` | Scope discipline (CONTEXT integration-points: `static/ui.js` touch ≤ 6 lines) |
| No registry / third-party blocks | Project has no `package.json` / `components.json` |
