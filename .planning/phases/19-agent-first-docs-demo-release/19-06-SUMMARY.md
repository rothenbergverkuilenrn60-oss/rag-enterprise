---
phase: 19-agent-first-docs-demo-release
plan: 06
subsystem: docs
tags: [readme, agent-first, narrative, AGENT-08, SC1, SC4]
requires:
  - 19-04  # docs/agent-architecture.md#planner-executor-model + #authoring-tools + #event-schema-reference anchors
  - 19-05  # docs/demo.cast (asciicast v2)
  - 19-07  # CHANGELOG.md + docs/v1.4-design.md
provides:
  - "README.md (agent-first thesis lead, 8-section D-02 order)"
affects:
  - "first-impression surface for the v1.4 release; closes ROADMAP SC1, contributes to SC4"
tech-stack:
  added: []
  patterns:
    - "agent-first framing — RAG demoted to one tool of several"
    - "asciinema cast linked + asciinema.org placeholder (post-merge upload)"
    - "ASCII flow diagram (no mermaid / diagrams-as-code)"
    - "v1.3 technical content preserved verbatim under ## Platform features (D-04)"
key-files:
  created: []
  modified:
    - README.md
decisions:
  - "Quick demo embed form C — link to docs/demo.cast + asciinema play instruction + commented HTML asciinema.org embed placeholder. Form chosen because plan 19-05 produced the cast file but did NOT produce .demo-cast-url or docs/demo.gif (asciinema/agg binaries not on the executor host)."
  - "Tools table includes RefinedRetrieveTool as a 5th tool row even though plan acceptance gates only enumerate 4 — RefinedRetrieveTool ships in v1.4 per Phase 17 and is on the explicit `## Tools the agent calls` 5-row reference in plan 19-06 must-have spec."
  - "## License section retained as a separate H2 (8 H2 sections + License = 9 by `grep ^## ` count). Plan acceptance line says 'monotonically increasing' across the 8 named sections; license-as-9th preserves the v1.3 placement of the AGPL note (T-19-06-04 mitigation: don't drop the legal note)."
metrics:
  duration: ~12m
  completed: 2026-05-09
  tasks: 1/1
  commits: 1
  files_modified: 1
  lines_changed: "+143 / -155 (300 lines final, was 312)"
---

# Phase 19 Plan 06: Agent-First README Rewrite Summary

Replaced `README.md` with the v1.4 agent-first narrative. Opens with the thesis "A Planner → Executor → Synthesizer agent. RAG is one of its tools." and reorders the surface into the D-02 section sequence so peer engineers see the parallel-tool fan-out demo before the implementation mechanics. All v1.3 technical content (RLS, HNSW, BM25, RRF, HyDE, reranker, 6/10-stage pipelines, image extraction, JWT, RAGAS, coverage, Prometheus, Langfuse, audit) is preserved under `## Platform features` and `## Quick start`, reframed in agent-first terms but never deleted (D-04). Single atomic commit closes ROADMAP SC1 and contributes to SC4.

## What Shipped

`README.md` (300 lines, was 312):

| Section | Line | Content |
|---------|------|---------|
| Title + thesis | 1–7 | `# EnterpriseRAG` + the agent-first thesis verbatim + 4-line elaboration (multi-tenant, parallel dispatch, structured event stream, provider-neutral) |
| `## Quick demo` | 9 | `make demo-agent` intro + `asciinema play docs/demo.cast` instruction + commented-out asciinema.org embed placeholder + parallel-fan-out paragraph |
| `## Architecture` | 36 | ASCII flow diagram (Request → Planner → ToolPlan → Executor → Synthesizer → Response) + 4-line concept summary + cross-link to `docs/agent-architecture.md#planner-executor-model` |
| `## Tools the agent calls` | 53 | 5-row table — RetrieveTool / RefinedRetrieveTool / WebSearchTool / SQLTool / MCPTool — + cross-link to `#authoring-tools` |
| `## Platform features` | 69 | 7 subsections (multi-tenant isolation, hybrid retrieval / RetrieveTool internals, document ingestion, image extraction, provider neutrality, security, module layout) + Testing & coverage table |
| `## Observability` | 134 | 6 SSE event types + cross-link to `#event-schema-reference` + Prometheus / structlog / Langfuse / audit summary |
| `## Quick start` | 140 | 4 sub-sections — Try the demo first → Docker stack → Local dev → cURL example → Configuration table |
| `## Project status` | 287 | v1.4 release callout + design-doc / phase-summaries / CHANGELOG / ROADMAP links + archived-milestone note |
| `## License` | 298 | SECURITY.md link + PyMuPDF AGPL note (preserved verbatim from v1.3) |

## Files Modified

| File | Change |
|------|--------|
| `README.md` | +143 / −155 (full rewrite; net −12 lines) |

## Verification

All acceptance gates from plan 19-06 ran post-commit:

| Gate | Expected | Actual |
|------|----------|--------|
| Thesis present | 1 | **1** ✓ |
| Section order monotonic | 8 increasing line numbers (Quick demo → … → Project status → License) | confirmed: 9, 36, 53, 69, 134, 140, 287, 298 ✓ |
| Quick demo embed | ≥ 1 of (asciinema.org / demo.gif / demo.cast) | **5** matches (cast file linked in body + comment block) ✓ |
| Architecture diagram | 1 | **1** ✓ |
| Tools table 5 rows | 5 (with backtick names) | **5** ✓ (plan's grep regex omitted backticks; semantic content correct — see Deviations) |
| Cross-link `#planner-executor-model` | ≥ 1 | **1** ✓ |
| Cross-link `#event-schema-reference` | ≥ 1 | **1** ✓ |
| Cross-link `#authoring-tools` | ≥ 2 | **2** ✓ |
| `docs/v1.4-design.md` link | ≥ 1 | **1** ✓ |
| `CHANGELOG.md` link | ≥ 1 | **1** ✓ |
| cURL POST route | 1 | **1** ✓ (`POST http://localhost:8000/api/v1/agent/v1/run/stream`) |
| `curl --no-buffer` | 1 | **1** ✓ |
| `Bearer <JWT>` placeholder | 1 | **1** ✓ |
| Real-token leak (`Bearer sk-` / `Bearer ey...`) | 0 | **0** ✓ |
| `demo-tenant` placeholder | ≥ 1 | **2** ✓ |
| Real tenant leak (`tenant_id.*acme` / `production`) | 0 | **0** ✓ |
| `make demo-agent` count | ≥ 2 | **2** ✓ (Quick demo intro + Try the demo first) |
| Tech-content breadth (18 keywords) | ≥ 14 | **26** ✓ |
| Configuration table keys | ≥ 5 | **15** ✓ |
| Length | 200 ≤ N ≤ 350 | **300** ✓ |
| License at bottom (PyMuPDF last line within last 10) | last-10 | line 300 of 300 ✓ |
| Internal markdown links | ≥ 5 | **12** ✓ |

### Cross-link target file existence (T-19-06-04 mitigation)

| Target | Exists |
|--------|--------|
| `docs/agent-architecture.md` | FOUND |
| `docs/v1.4-design.md` | FOUND |
| `CHANGELOG.md` | FOUND |
| `docs/demo.cast` | FOUND |
| `SECURITY.md` | FOUND |
| `.planning/ROADMAP.md` | FOUND |
| `.planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md` | FOUND |
| `.planning/phases/17-tool-abstraction-retrievetool/17-03-SUMMARY.md` | FOUND |
| `.planning/phases/18-sse-planner-trace-event-stream/18-03-SUMMARY.md` | FOUND |

### Anchor existence in `docs/agent-architecture.md` (auto-anchor verification)

- `## Planner / Executor Model` → `#planner-executor-model` (line 7) ✓
- `## Authoring Tools` → `#authoring-tools` (line 153) ✓
- `## Event Schema Reference` → `#event-schema-reference` (line 245) ✓

## Threat Model Verification (T-19-06-01 .. T-19-06-04)

| Threat ID | Disposition | Verification |
|-----------|-------------|--------------|
| T-19-06-01 (JWT samples leak) | mitigate | `grep -cE "Bearer (sk-|ey[A-Za-z0-9])" README.md` returns **0**; cURL example uses `Bearer <JWT>` placeholder. ✓ |
| T-19-06-02 (real tenant IDs leak) | mitigate | `grep -cE "tenant_id.*acme|tenant_id.*production" README.md` returns **0**; cURL body uses `demo-tenant` / `demo-user`. ✓ |
| T-19-06-03 (API keys / secrets in env-var examples) | mitigate | Quick start preserves v1.3 ellipsis pattern (`OPENAI_API_KEY=sk-...` / `ANTHROPIC_API_KEY=sk-ant-...`); no real keys present. ✓ |
| T-19-06-04 (broken cross-links) | mitigate | All 9 link targets verified existent on disk; all 3 anchors confirmed in `docs/agent-architecture.md`. ✓ |

## Deviations from Plan

### Auto-fixed / Clarifications

**1. [Rule 1 — Doc-correctness] Quick demo embed: form C (cast link + asciinema.org placeholder) chosen over forms A and B**

- **Found during:** Task 1 read of dependency artifacts.
- **Issue:** Plan provided three candidate embed forms (A: HTML asciinema.org embed; B: docs/demo.gif img embed; C: cast link + local-play instructions). Form A requires `.planning/phases/.../.demo-cast-url` (not produced — 19-05 noted asciinema upload not run); form B requires `docs/demo.gif` (not produced — `agg` not installed on the executor host per 19-05 SUMMARY).
- **Fix:** Adopted form C verbatim per the user's prompt directive ("Embed the cast via a markdown link to `docs/demo.cast` PLUS a code-block instruction for users to run `asciinema play docs/demo.cast` locally"). Added a commented-out HTML embed block with a maintainer note: "populate after a maintainer runs `asciinema upload docs/demo.cast` post-merge. Replace `<ID>` with the returned asciinema.org id; the SVG below renders inline on github.com." This keeps the embed-upgrade path one-line (uncomment + substitute) without blocking on a missing artifact.
- **Files modified:** README.md (`## Quick demo` section, lines 9–34).
- **Commit:** 5ce314e.

**2. [Rule 1 — Doc-correctness] Tools table includes 5 rows (plan acceptance regex matches 4 with backticks-stripped)**

- **Found during:** acceptance-gate verification.
- **Issue:** Plan's grep gate `grep -c "^| \\(RetrieveTool\\|RefinedRetrieveTool\\|WebSearchTool\\|SQLTool\\|MCPTool\\)"` does not match the lines because all 5 names are wrapped in backticks (`` `RetrieveTool` ``) per the markdown table convention spelled out in the plan body. The gate's regex omits the backtick prefix.
- **Fix:** Wrote the table with backtick-wrapped names per the plan's verbatim must-have content. Re-ran the gate with the corrected regex `^\| \`(RetrieveTool|...)\`` — returns **5** matches as semantically required. The plan's grep-gate regex is a planner-side glitch; the content is correct against the plan body.
- **Files modified:** none (no-op fix; content was correct as written).

**3. [Clarification — narrative] Provider neutrality subsection extended to mention Ollama fallback**

- **Found during:** Task 1 preservation pass over the v1.3 README.
- **Issue:** v1.3 README lines 32–34 documented an Ollama-without-tool-use fallback path ("the pipeline catches `NotImplementedError` from the adapter and emits a structured-log warning"). The plan body's "Provider neutrality" subsection text omitted this detail.
- **Fix:** Appended the Ollama-fallback sentence verbatim under `## Platform features` → `### Provider neutrality`. D-04 mandates "no information lost" — this is preserved verbatim, just regrouped. Same applies to the legacy 10-stage pipeline mention preserved in `### Hybrid retrieval (RetrieveTool internals)` and the Phase-15-supersession callout preserved in `### Testing & coverage`.
- **Files modified:** README.md (within `## Platform features`).
- **Rationale:** D-04 preservation rule is a hard constraint; the plan's subsection text was a sketch, not a strict ceiling.

### Auth Gates

None.

## Threat Surface Scan

No new attack surface introduced. README is documentation-only. Zero credentials, zero real tenant IDs, zero internal infrastructure paths in the rewritten file. The only added "surface" is the asciinema.org embed placeholder (commented out) — when a maintainer populates it post-merge, the URL is a public asciinema.org id (no credentials embedded).

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `[ -f README.md ]` | FOUND (300 lines) |
| `git log --oneline | grep -q 5ce314e` | FOUND (`docs(19-06-T1): full README rewrite — agent-first framing ...`) |
| `[ -f .planning/phases/19-agent-first-docs-demo-release/19-06-SUMMARY.md ]` | created (this file) |
| Branch is `gsd/v1.3-milestone` (sticky) | confirmed |
| No shared orchestrator artifacts modified | STATE.md, ROADMAP.md, REQUIREMENTS.md untouched ✓ |
| No accidental deletions | `git diff --diff-filter=D HEAD~1 HEAD` returned empty ✓ |
| Out-of-scope state untouched | `services/feedback/__pycache__/...pyc` modification + untracked `19-03-SUMMARY.md` left alone (not part of this plan) ✓ |

## Files Written (this plan)

- `README.md` (modified, +143 / -155, 300 lines final)
- `.planning/phases/19-agent-first-docs-demo-release/19-06-SUMMARY.md` (this file)

## Commits

| # | Hash    | Message                                                                                                          | Files       | Lines |
|---|---------|------------------------------------------------------------------------------------------------------------------|-------------|-------|
| 1 | 5ce314e | docs(19-06-T1): full README rewrite — agent-first framing (Phase 19, AGENT-08, SC1+SC4)                          | README.md   | +143 / -155 |

## Follow-up (post-merge, optional)

If a maintainer runs `asciinema upload docs/demo.cast` after the v1.4 PR merges, replace the commented-out HTML embed block in `## Quick demo` with the returned asciinema.org id. The README is otherwise complete; the cast file alone (linked + locally playable) satisfies SC4 today.
