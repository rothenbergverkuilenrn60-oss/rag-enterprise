# Phase 14: Frontend Split and DOM Modernization - Discussion Log

**Date:** 2026-05-09
**Phase:** 14 (UI-02)

## Gray Areas Selected

User selected ALL 4 gray areas:
- Bundler
- JS module pattern
- DOM API + event wiring style
- CSS organization

## Q&A Trail

**Q1: Bundler (AC#5 explicit decision point)?**
- A: No bundler ← **Selected**
- B: Vite
- C: esbuild

**Decision (D-01):** No bundler. 29 lines of JS doesn't justify build infra.
**Reason:** AC#5 explicitly says "If not needed, no bundler is introduced." STATE.md Phase 14 notes echo this. Adding package.json + node_modules for one file is over-engineering.

---

**Q2: JS module pattern?**
- A: Classic `<script src="ui.js">` + IIFE-wrapped ← **Selected**
- B: `<script type="module" src="ui.js">`
- C: Plain `<script>` with global functions

**Decision (D-02):** IIFE-wrapped classic script. `(function(){ "use strict"; ... })();`
**Reason:** Avoids global namespace pollution. No ES module quirks (CORS for `file://`, MIME requirements). `"use strict"` enables strict mode without ESM. Browser-cache friendly. Native ESM is forward-compatible but unnecessary at current size.

---

**Q3: DOM API + event wiring style?**
- A: Keep `getElementById`, wire on DOMContentLoaded ← **Selected**
- B: Migrate to querySelector + data-action attributes
- C: Module-scope const refs at top, wire at end

**Decision (D-04, D-05):** Keep all 6 existing `getElementById` calls. Wire event listeners inside `DOMContentLoaded` handler at the end of the IIFE. Replace `onclick="ask()"` with `addEventListener('click', ask)`.
**Reason:** Minimal diff, satisfies AC#3 + AC#4. `data-action` convention not present elsewhere — introducing it for one button is YAGNI.

---

**Q4: CSS organization?**
- A: Single `static/ui.css` ← **Selected**
- B: Split base.css + components.css

**Decision (D-03):** Single ui.css file (14 lines).
**Reason:** Multi-file split for 14 lines is over-engineered. Satisfies AC#1 + AC#2 minimum.

---

## All 13 Decisions Locked (D-01 through D-13)

See `14-CONTEXT.md` `<decisions>` block. Categories:
- Architecture (D-01, D-02, D-03)
- DOM API + Event Wiring (D-04, D-05, D-06)
- Helper Functions (D-07)
- Serving / FastAPI Layer (D-08, D-09, D-10)
- Testing (D-11, D-12)
- Failure Handling (D-13)

## Out of Scope (Deferred)

- Bundler / package.json
- Frontend framework migration
- Dark mode / theme toggle
- Search history / saved queries
- Playwright E2E browser tests
- Source maps
- TypeScript migration

## Next Action

Run `/gsd-plan-phase 14` to research + plan Phase 14.
