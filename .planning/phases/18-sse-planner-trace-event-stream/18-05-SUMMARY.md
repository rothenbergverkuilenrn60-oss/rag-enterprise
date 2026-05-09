---
phase: 18-sse-planner-trace-event-stream
plan: 05
subsystem: docs
tags: [docs, sse, agent, AGENT-04, ROADMAP-SC2]
type: execute
wave: 5
depends_on: [18-01, 18-02, 18-03, 18-04]
requirements: [AGENT-04]
dependency_graph:
  requires:
    - "utils/models.py STAGE 7: AgentEvent + 6 concrete subclasses (plan 18-01)"
    - "controllers/api.py: /agent/v1/run/stream named-event SSE format (plan 18-04)"
    - "services/pipeline.py: AgentQueryPipeline.run_streaming (plan 18-03)"
    - "services/agent/executor.py: execute_plan_streaming contract (plan 18-02)"
  provides:
    - "docs/agent-architecture.md: ## Event Schema Reference + 6 event subsections + ### Consuming the Stream"
  affects:
    - "docs/agent-architecture.md (additive only; ## Authoring Tools content byte-identical)"
tech_stack:
  added: []
  patterns:
    - "Field-table-plus-JSON-example documentation pattern, one block per event class"
    - "SSE named-event consumer reference (one addEventListener per event type)"
key_files:
  created: []
  modified:
    - "docs/agent-architecture.md"
decisions:
  - "Drop trace_id/seq/ts_ms rows from per-event tables — documented once in the common-fields table at the top, with explicit note that they are present on every payload. Frees ~18 lines and reduces table noise without losing information."
  - "Compress JSON examples (single-line for the 4 simplest events, 2-line wrap for tool.span.end / tool.span.error, multi-line only for the largest planner.plan example) to fit the file under the ≤250-line CONTEXT.md budget while keeping every field demonstrated."
  - "Use one addEventListener call per event type (not a switch or generic handler) so the snippet is a literal copy-paste template and grep-verifiable (acceptance criteria require ≥6 addEventListener occurrences)."
metrics:
  duration_minutes: 9
  completed_date: 2026-05-09
  total_lines_added: 150
  final_file_lines: 244
  budget_lines: 250
---

# Phase 18 Plan 05: Event Schema Reference Documentation Summary

Added `## Event Schema Reference` to `docs/agent-architecture.md` documenting all 6 Phase 18 SSE event types with field tables and JSON examples, plus a `### Consuming the Stream` browser EventSource snippet — closing ROADMAP Phase 18 SC2 and AGENT-04.

## Commit

- `ccc763b` — `docs(18-05): add SSE Event Schema Reference (AGENT-04, ROADMAP SC2)` (1 file changed, 150 insertions, 3 deletions)

## What Was Delivered

`docs/agent-architecture.md` final structure:

| Section | Lines | Status |
|---|---|---|
| Title + status teaser | 1–5 | Updated: Phase 17 → Phase 18 (3 lines, no net delta) |
| `## Authoring Tools` (Phase 17) | 7–97 | **Byte-identical** to pre-edit (verified via `git diff`) |
| `## Event Schema Reference` (this plan) | 99–244 | **NEW** — 146 lines |

### `## Event Schema Reference` contents

1. **Preamble** (lines 99–124) — SSE frame format, Pydantic V2 base reference, common-fields table (`trace_id`/`seq`/`ts_ms`), `event_type` discriminator note, redaction policy (D-11).
2. **`### planner.plan`** — full `ToolPlan` shape including `steps`, `parallel_groups`, `rationale`, `raw_assistant_msg`, `stop_reason`. Notes terminal-plan skip behavior.
3. **`### tool.span.start`** — `span_id` + `name` + verbatim `args`. Notes pre-await emit timing.
4. **`### tool.span.end`** — `span_id` + `latency_ms` + `chunk_count` (with Phase 17 D-02 fallback note) + `is_error` + `content_preview` (200-char truncation).
5. **`### tool.span.error`** — `span_id` + `latency_ms` + `error_type` + `error_message` (200-char truncation). Notes v1.3 D-01 isolation guarantee.
6. **`### executor.parallel`** — `fan_out` + `group_latency_ms`. Documents D-09 / D-15 option-c reconciliation: emit at group END after all child end-or-error events fire.
7. **`### synthesizer.final`** — `answer` + `sources_count`. Documents terminal-frame contract (no `[DONE]` sentinel).
8. **`### Consuming the Stream`** — minimal browser `EventSource` consumer with one `addEventListener` per event type, plus a note on POST-vs-GET (referencing Phase 19's `make demo-agent`).

## Field-Shape Cross-Check vs `utils/models.py` STAGE 7

Verified against the source-of-truth declarations at `utils/models.py:537–632`:

| Class | Fields documented | Fields in `model_fields` | Match? |
|---|---|---|---|
| `PlannerPlanEvent` | `trace_id`, `seq`, `ts_ms`, `plan` | `trace_id`, `seq`, `ts_ms`, `plan` | ✓ |
| `ToolSpanStartEvent` | + `span_id`, `name`, `args` | + `span_id`, `name`, `args` | ✓ |
| `ToolSpanEndEvent` | + `span_id`, `latency_ms`, `chunk_count`, `is_error`, `content_preview` | + `span_id`, `latency_ms`, `chunk_count`, `is_error`, `content_preview` | ✓ |
| `ToolSpanErrorEvent` | + `span_id`, `latency_ms`, `error_type`, `error_message` | + `span_id`, `latency_ms`, `error_type`, `error_message` | ✓ |
| `ExecutorParallelEvent` | + `fan_out`, `group_latency_ms` | + `fan_out`, `group_latency_ms` | ✓ |
| `SynthesizerFinalEvent` | + `answer`, `sources_count` | + `answer`, `sources_count` | ✓ |

`event_type` discriminator strings (verbatim):
- `"planner.plan"`, `"tool.span.start"`, `"tool.span.end"`, `"tool.span.error"`, `"executor.parallel"`, `"synthesizer.final"` — all match `utils/models.py` ClassVar declarations.

**No field renames occurred during plans 18-01..18-04** that required docs adjustment. Field shapes locked in plan 18-01 (`utils/models.py` STAGE 7) flowed through 18-02 (executor contract), 18-03 (pipeline shim), and 18-04 (route serializer) unchanged. The docs reflect the as-shipped code 1:1.

## `## Authoring Tools` Byte-Identical Verification

```
$ git diff HEAD~1 docs/agent-architecture.md | grep -E "^[-+]" | grep -v "^---\|^+++"
```

Shows changes ONLY at:
1. Lines 3–5 (status teaser: Phase 17 → Phase 18, 3-line replacement preserving line count)
2. End-of-file append (146 lines after line 97)

Lines 7–97 (the `## Authoring Tools` section: `### Defining a Tool`, `### Registering a Tool`, `### parameters_schema Shape`, `### Allowlisting`, `### Runnable Example`, `### ToolResult metadata convention`) are byte-identical to pre-edit per CONSTRAINT #1 ("DO NOT touch `## Authoring Tools` section content").

## Acceptance Criteria — All Pass

| Criterion | Result |
|---|---|
| `wc -l docs/agent-architecture.md` ≤ 250 | **244 lines** (under budget by 6) |
| `grep -c "^## " docs/agent-architecture.md` returns 2 | **2** (`## Authoring Tools` + `## Event Schema Reference`) |
| All 6 event-type subsection headings exist | **6/6** present |
| `### Consuming the Stream` heading exists | ✓ |
| `grep -c "EventSource" docs/agent-architecture.md` ≥ 1 | **2** (mention + code) |
| `grep -c "addEventListener" docs/agent-architecture.md` ≥ 6 | **7** (one per event type + intro mention) |
| Phase 18 (v1.4) status teaser present | ✓ |
| `## Authoring Tools` content byte-identical | ✓ (verified via `git diff`) |
| Commit titled `docs(18-05): ...` | ✓ (`ccc763b`) |

## ROADMAP Coverage

- **AGENT-04** (event schema documentation): closed.
- **ROADMAP Phase 18 SC2** (event schemas documented in `docs/agent-architecture.md` with example payloads; one example per event type): **delivered**. 6 examples, one per event type.
- All Phase 18 ROADMAP success criteria except SC5 (Phase 19 demo) are now satisfied across plans 18-01..18-05.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Verbatim plan text exceeded the file ≤250-line budget**

- **Found during:** Task 1 — first-pass write of the verbatim plan text produced a 346-line file (96 lines over the ≤250 budget specified in the plan's CONSTRAINT #2 and acceptance criterion #1).
- **Issue:** The plan's `<action>` block contained ~256 lines of literal markdown to append, but the same `<action>` block also constrained the resulting file to ≤250 total lines. Plus the existing 97-line file gives at most 153 lines for the new section. The verbatim text and the budget constraint conflicted.
- **Fix:** Trimmed the new section to fit the 153-line budget while preserving every must-have:
  - Removed `trace_id` / `seq` / `ts_ms` rows from the 6 per-event tables (the same fields are documented once in the top common-fields table; per-event tables now show event-specific fields only). Saved ~18 lines.
  - Removed `trace_id` / `seq` / `ts_ms` from JSON examples for the same reason. Saved ~18 lines.
  - Compressed the 4 small JSON examples to single-line; kept multi-line for the larger `planner.plan`, `tool.span.end`, `tool.span.error` examples. Saved ~12 lines.
  - Tightened prose paragraphs (removed redundant "this is", merged sentences). Saved ~12 lines.
  - Final 2 small examples (`executor.parallel`, `synthesizer.final`) inlined as backtick code on the "Example payload:" line. Saved 4 more lines.
- **Files modified:** `docs/agent-architecture.md` (this plan's only target).
- **Commit:** `ccc763b`.
- **Information loss:** zero — every field, every event type, every JSON example, the 6 addEventListener handlers, the redaction policy, and the D-09/D-15 reconciliation note are all present. The compression is strictly cosmetic (table-row deduplication + JSON whitespace compaction).

### Architectural changes

None.

## Self-Check: PASSED

- File `docs/agent-architecture.md` exists at expected path and is 244 lines (≤ 250).
- Commit `ccc763b` exists in `git log`.
- All 8 required headings present (`## Event Schema Reference` + 7 `###` subsections under it).
- Field shapes match `utils/models.py` STAGE 7 verbatim (static cross-check; runtime Python check unavailable in worktree env — `pydantic` not on `sys.path`, but source-level comparison passes).
- `## Authoring Tools` section byte-identical to HEAD~1.

## Stubs / Threat Flags

**Known stubs:** none. This plan is pure documentation; the documented behavior is fully implemented in plans 18-01..18-04.

**Threat flags:** none. No new network endpoints, auth paths, file access patterns, or schema changes — pure docs.

## Next

Phase 18 implementation plans (18-01..18-05) all complete. Phase 18 SC1, SC2, SC3, SC4 (latency parallel-bound assertion in 18-02 smoke test) and SC6 (regression-safe — `/query/stream` untouched per 18-04) are all delivered. SC5 (Phase 19 demo) is the only remaining cross-phase deliverable. Ready for `/gsd-verify-work 18`.
