# Phase 16: Planner + Executor Extraction - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-09
**Phase:** 16-planner-executor-extraction
**Areas discussed:** D-1 ToolPlan model fields · D-2 `_execute_tool_call` placement · D-3 parity test fixture format · D-4 Synthesizer class

User selected `critical` from the area triage; D-5 (swarm-as-tool), D-6 (NLU-03 landing), D-7 (`/query?agent_mode=true` alias), D-8 (iteration cap) were deferred to design-doc default recommendations as captured in CONTEXT.md `<deferred>` and the user's reply during triage.

---

## D-1 ToolPlan model fields

| Option | Description | Selected |
|--------|-------------|----------|
| steps + parallel_groups + rationale (design doc tentative, recommended) | Pydantic V2 frozen with explicit parallel grouping by index + planner rationale string for SSE trace readability | ✓ |
| steps only | Simplest; parallelism inferred from execution order (consecutive waves merged); loses trace reasoning visibility | |
| steps + per-step `wave: int` field | Field-on-ToolCall variant; trace shows "lanes"; planner LLM may occasionally emit malformed wave values | |
| steps + parallel_groups + rationale + per-step retry policy | Adds `retry: ToolRetryPolicy \| None` per step; transfers reliability authority into planner; over-scoped for v1.4 | |

**User's choice:** Option 1 — `steps + parallel_groups + rationale`.
**Notes:** Aligns with the design doc's tentative spec. `parallel_groups` is treated as the canonical execution shape (D-02 in CONTEXT.md). `rationale` is required, in the same language as the user query, surfaced verbatim in Phase 18 `planner.plan` SSE event.

---

## D-2 `_execute_tool_call` shared helper placement

| Option | Description | Selected |
|--------|-------------|----------|
| Top-level module function in `pipeline.py` | Free function next to existing classes; minimum file delta; pipeline.py keeps growing past its current ~1100 lines | |
| New `services/agent/tool_executor.py` (recommended) | New `services/agent/` umbrella module hosts `tool_executor.py` and the future `Planner` / `Executor` / `Synthesizer`. Clean boundary for Phase 17 tool registry; pipeline.py shrinks | ✓ |
| Static method on a new `Executor` class | `Executor.execute_tool_call()`; isolation OK but the helper is stateless — no benefit from class binding | |
| `utils/agent_helpers.py` | Junk-drawer / mis-uses `utils/`; not recommended | |

**User's choice:** Option 2 — new `services/agent/tool_executor.py`.
**Notes:** Triggered the broader decision (D-04 in CONTEXT.md) to make `services/agent/` the umbrella for the new collaborators (`planner.py`, `executor.py`) and the future tool registry / Memory module. v1.3 duplicated `_execute_tool_call` (lines 846 and 1107 in `services/pipeline.py`) is deleted; `SwarmQueryPipeline` switches to `from services.agent.tool_executor import execute_tool_call`. Acceptance criterion: `grep -rn "def _execute_tool_call" services/` returns exactly 1 result after Phase 16.

---

## D-3 Behavioral parity test fixture format

| Option | Description | Selected |
|--------|-------------|----------|
| Hand-curated `messages` list (v1.2 wire-fixture style, recommended) | `tests/unit/fixtures/agent_parity/` mirrors existing `tests/unit/fixtures/agentic_turn/`; readable; hand-editable; same-architecture as current tests | ✓ |
| JSON replay + pytest fixture loader | Records actual v1.3 LLM transcripts; LLM nondeterminism leaks into "byte-identical" claim; needs replay harness | |
| VCR.py cassette | Adds VCR.py dependency; intercepts HTTP layer; auto-record/replay; cassettes need re-record on every new test path; not recommended | |
| Audit-side-effect assertions only | Skips replay; only asserts that audit log post-refactor matches v1.3 schema; loses real "parity" claim | |

**User's choice:** Option 1 — hand-curated `messages` list, v1.2 wire-fixture style.
**Notes:** Fixture is a dict with `input_messages`, `expected_tool_call_sequence`, `expected_final_text`. The mocked LLM responses are constructed by manually replaying the v1.3 baseline once with `LOG_LEVEL=DEBUG` and reading structured-logger output (capture step is part of the Phase 16 plan, not pre-work). Minimum two fixtures required: one single-step query and one multi-step parallel query. Detail in CONTEXT.md D-07 / D-08.

---

## D-4 Synthesizer class type

| Option | Description | Selected |
|--------|-------------|----------|
| No Synthesizer class — final LLM turn is the answer (preserves v1.3 parity, recommended) | Multi-turn iteration up to `max_iterations`; the orchestrator stuffs tool outputs back into messages and re-calls `call_agentic_turn`; final assistant text IS the answer; SSE `synthesizer.final` carries that text | ✓ |
| Standalone Synthesizer class (explicit Plan struct) | `Synthesizer.compose(plan, tool_outputs)` is a discrete LLM call; cleaner architecture but breaks v1.3 multi-turn refinement semantics; parity tests would need cassettes | |
| Inline inside Executor | `Executor.execute_plan()` does tool fan-out AND final composing call; single class carries too much; SSE event scoping muddied | |
| Reuse `SwarmQueryPipeline._synthesize` | `_synthesize` is multi-sub-agent oriented; semantics mismatch a single-agent flow; would force re-shaping | |

**User's choice:** Option 1 — no explicit Synthesizer class; final LLM turn IS the synthesizer.
**Notes:** Phase 16 collaborators are `Planner` + `Executor` only; "Synthesizer" is a logical role, not a class. The v1.3 `max_iterations=5` outer cap STAYS at the orchestrator level (`AgentQueryPipeline.run`), NOT inside `Executor`. SSE `synthesizer.final` event in Phase 18 will carry the text of the last assistant turn. If a future phase wants distinct prompting for the final composing call, that's its own refactor (deferred to v1.5+). Detail in CONTEXT.md D-10 through D-12.

---

## Claude's Discretion

- Internal naming inside `services/agent/` (file split granularity, helper function names) — pick what reads well.
- Whether `Executor.execute_plan` returns a list of `ToolResult` or yields a generator — pick the shape that simplifies Phase 18 SSE event emission. Phase 17's tool registry surface will validate the choice.
- Logging field names for the audit trail — REUSE the v1.2 `parallel_factor` name verbatim; do not invent new field names for the same concept.

## Deferred Ideas

- **D-5 swarm-as-tool** — defer to v1.5+ AGENT-05 phase. Phase 16 reserves the design hook by keeping `services/agent/` as the umbrella module where a future `SwarmTool` would live, but does NOT register it.
- **D-6 NLU-03 landing** — keep `agent_mode` / `swarm_mode` request fields in v1.4 (no breaking change). Documentation mapping (`Query / Agent / Swarm` → `ToolPlan` shapes) deferred to Phase 19's `docs/agent-architecture.md`.
- **D-7 `/query?agent_mode=true` alias** — defer decision to Phase 19 (release / docs phase). Recommendation per design doc: keep thin alias to protect open-source repo external users.
- **D-8 iteration cap policy** — keep static `max_iterations=5` in v1.4 per design doc. Adaptive / per-tenant cap is a v1.5+ topic.
- **Planner caching** (planner_input_hash → ToolPlan) — keep planner stateless in v1.4 for parity; revisit once the eval gate has v1.4 baselines.
- **Explicit `Synthesizer` class** (D-10 in CONTEXT.md) — only revisit if a future phase wants distinct prompting for the final composing call.
