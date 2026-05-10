---
phase: 19-agent-first-docs-demo-release
plan: 04
subsystem: docs
tags: [agent, docs, planner, executor, AGENT-08, SC2]
requires:
  - 19-01  # _demo_stubs.py / runtime contracts referenced (advisory; no import)
provides:
  - "docs/agent-architecture.md::## Planner / Executor Model"
affects: []
tech-stack:
  added: []
  patterns:
    - "Concept->Tool authoring->Wire format docs trilogy with runnable snippets"
key-files:
  created: []
  modified:
    - docs/agent-architecture.md
decisions:
  - "Section inserted BEFORE Authoring Tools (D-09 ordering: Concept first)"
  - "Runnable snippet imports real shipped types (AgentQueryPipeline, GenerationRequest); offline-runnability deferred to make demo-agent (Phase 19-03)"
  - "Cross-reference links via GitHub auto-anchors (#authoring-tools, #event-schema-reference)"
metrics:
  duration: ~10m
  completed: 2026-05-09
---

# Phase 19 Plan 04: Planner / Executor Docs Section Summary

Inserted a 147-line `## Planner / Executor Model` section into `docs/agent-architecture.md` BEFORE the existing `## Authoring Tools` (Phase 17) and `## Event Schema Reference` (Phase 18) sections. Closes ROADMAP SC2: each of the 3 docs sections now has its runnable snippet, completing the Concept->Tool authoring->Wire format trilogy.

## What Shipped

- New H2 section `## Planner / Executor Model` with 5 subsections:
  - **Concept** (2 paragraphs) — three collaborators (Planner / Executor / Synthesizer); links to Authoring Tools.
  - **Flow** — ASCII diagram of `Request -> AgentQueryPipeline -> Planner -> ToolPlan -> Executor (parallel groups, BaseException isolation) -> ToolResult[] -> Synthesizer -> Response`; `MAX_ITERATIONS = 5` callout.
  - **Pydantic V2 Signatures** — `ToolCall` and `ToolPlan` verbatim from `utils/models.py:244-315` (header + fields, no validator bodies per plan).
  - **Method Signatures** — `Planner.plan_from_messages` and `Executor.execute_plan_streaming` verbatim from source; cross-link to Event Schema Reference.
  - **Runnable Example** — 25-line `asyncio.run(main())` snippet importing `AgentQueryPipeline` and `GenerationRequest`; iterates `pipeline.run_streaming(req)` and prints every event; uses placeholder identifiers `demo-tenant`/`demo-user`/`demo-session` (T-19-04-01 mitigation).
- Status banner updated: Phase 18 -> Phase 19 trilogy complete.
- Existing Phase 17 (Authoring Tools) and Phase 18 (Event Schema Reference) sections byte-identical (verified via `diff`).

## Files Modified

| File | Change |
|------|--------|
| `docs/agent-architecture.md` | +149 / -3 (status banner: 3 lines replaced; new section: 147 lines inserted) |

Total file size: 244 -> 390 lines.

## Verification

All acceptance gates passed:

- `grep -c "^## Planner / Executor Model$"` -> 1
- H2 ordering: Planner / Executor Model (line 7) -> Authoring Tools (line 153) -> Event Schema Reference (line 245)
- All 4 new H3 subsections present (`### Flow`, `### Pydantic V2 Signatures`, `### Method Signatures`, `### Runnable Example`)
- `### Runnable Example` total = 2 (this section + Phase 17's existing one)
- ASCII diagram present (`Request ──▶ AgentQueryPipeline`)
- `parallel_groups: list[list[int]] = Field(default_factory=list)` verbatim from `utils/models.py`
- `async def plan_from_messages(` and `async def execute_plan_streaming(` signatures verbatim
- Runnable snippet markers all present: `asyncio.run(main())`, `AgentQueryPipeline()`, `pipeline.run_streaming(req)`
- Cross-references resolve: `[Authoring Tools](#authoring-tools)` (×1), `[Event Schema Reference](#event-schema-reference)` (×2 — Method Signatures + Runnable Example, per plan body even though plan acceptance line said "1")
- Phase 19 status banner present
- No real tenant IDs leaked (`grep -E "tenant_id=\"acme\"|tenant.*production"` -> 0)
- Phase 17 + Phase 18 sections byte-identical (diff against `HEAD~1`)
- Section line count: 147 (target 120-160; D-10 budget OK)
- Imports validated: `APP_MODEL_DIR=/tmp .venv/bin/python -c "from services.pipeline import AgentQueryPipeline; from utils.models import ToolPlan, ToolCall, ToolResult, GenerationRequest"` -> "imports OK"

## Deviations from Plan

### Auto-fixed / Clarifications

**1. [Rule 1 — Doc-correctness] `[Event Schema Reference]` cross-reference appears 2× not 1×**
- **Found during:** verification.
- **Issue:** Plan acceptance criterion line 342 stated the cross-reference grep returns 1, but the verbatim section content the plan provided (lines 273-277 + line 316) contains the link TWICE — once in the Method Signatures subsection ("see [Event Schema Reference](#event-schema-reference) for the wire format") and once in the Runnable Example trailer ("Decode the events on the wire: see [Event Schema Reference](#event-schema-reference)").
- **Fix:** Followed the plan body (verbatim content has authority over a numerically inconsistent acceptance gate). Both cross-references retained because both contexts genuinely benefit from the link.
- **Files modified:** docs/agent-architecture.md
- **Commit:** d9ce5cc

**2. [Rule 1 — Doc-correctness] `@get_tool_registry().register` count is 3, not 2**
- **Found during:** verification.
- **Issue:** Plan line 344 expected count = 2 in the post-edit file. Pre-edit file already had 3 occurrences (1 inline-code mention in `### Registering a Tool` prose + 2 in code blocks). My edit did not add or remove any `@get_tool_registry().register` lines.
- **Fix:** No fix needed — the plan's expected count was based on a stale read of the file; the existing Phase 17 section was byte-identical post-edit. No regression.
- **Files modified:** none (no-op).

### Auth Gates

None.

## Threat Surface Scan

No new attack surface. Runnable snippet uses placeholder identifiers (`demo-tenant`, `demo-user`, `demo-session`) per T-19-04-01 mitigation. No JWT samples, no cURL, no real credentials. All file changes are documentation-only.

## Self-Check: PASSED

- `[ -f docs/agent-architecture.md ]` -> FOUND
- `git log --oneline | grep -q d9ce5cc` -> FOUND
- `[ -f .planning/phases/19-agent-first-docs-demo-release/19-04-SUMMARY.md ]` -> created
