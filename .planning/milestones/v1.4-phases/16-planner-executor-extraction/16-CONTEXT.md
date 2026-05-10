# Phase 16: Planner + Executor Extraction - Context

**Gathered:** 2026-05-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Refactor `services/pipeline.py::AgentQueryPipeline` so its single `run` method delegates to two explicit collaborators — `Planner` (first LLM call returns a `ToolPlan`) and `Executor` (runs the plan via `asyncio.gather`). Extract `_execute_tool_call` into a single shared helper consumed by both `SwarmQueryPipeline` and the new `Executor`. Subsume query-intent classification (NLU-03) into the planner's `ToolPlan` shape — no separate router class.

The phase ships a refactor + helper extraction. It does NOT add new tools, the SSE planner trace, or any documentation rewrite — those are Phases 17, 18, 19 respectively. Behavioral parity vs the v1.3 baseline is asserted before any new behavior lands.

</domain>

<decisions>
## Implementation Decisions

### Planner output schema
- **D-01:** `ToolPlan` is a Pydantic V2 frozen model with three fields: `steps: list[ToolCall]`, `parallel_groups: list[list[int]]` (each inner list is a wave of step indices that run concurrently), `rationale: str` (planner's prose explanation, surfaced verbatim in the Phase 18 `planner.plan` SSE event). `ToolCall` is the same `utils/models.py::ToolCall` already in use since v1.2 (do NOT redefine).
- **D-02:** `parallel_groups` is the canonical source of execution shape. The `Executor` does NOT infer parallelism from `steps` order; it walks `parallel_groups` and dispatches each group via `asyncio.gather`. Empty `parallel_groups` is invalid (planner always emits at least `[[0, 1, ..., N-1]]` for a single-wave plan, or `[[0]]` for a single-step plan).
- **D-03:** The planner prompt MUST instruct the LLM to emit `rationale` in the same language as the user query (preserves the v1.2/v1.3 multilingual behavior — Chinese queries return Chinese rationale).

### Shared helper placement
- **D-04:** A new module `services/agent/` is created. The shared `_execute_tool_call` helper (extracted verbatim from the v1.3 duplicates at `services/pipeline.py:846` and `:1107`) lives at `services/agent/tool_executor.py` as a free module-level async function, NOT a class method. `Planner`, `Executor`, and (for the time being) `SwarmQueryPipeline` all import it from this module.
- **D-05:** The new `services/agent/` module also houses `planner.py` (containing `Planner` class), `executor.py` (containing `Executor` class), and `__init__.py` re-exports. `AgentQueryPipeline.run` body becomes a thin orchestrator that imports from `services/agent/`. `services/pipeline.py` does NOT grow; the line count goes DOWN after the refactor.
- **D-06:** `SwarmQueryPipeline._execute_tool_call` (line 1107) is deleted in favor of importing from `services/agent/tool_executor.py`. After Phase 16, `grep -rn "def _execute_tool_call" services/` returns 1 result, not 2 — verified as an acceptance criterion (REQ AGENT-09).

### Behavioral parity proof
- **D-07:** Parity test fixtures live at `tests/unit/fixtures/agent_parity/` as hand-curated JSON files in the same style as the existing `tests/unit/fixtures/agentic_turn/` (v1.2 Phase 11). Each fixture is a dict with three top-level keys: `input_messages: list[dict]` (the user/system messages going INTO the pipeline), `expected_tool_call_sequence: list[ToolCall]` (the exact ordered tool-call sequence v1.3 produced), `expected_final_text: str | None` (the assistant's last turn text after tools complete). The v1.3 LLM responses are NOT recorded — instead, the fixture mocks `BaseLLMClient.call_agentic_turn` to return canned `AgenticTurn` objects so the test exercises pipeline glue, not LLM determinism.
- **D-08:** A minimum of TWO parity fixtures: one single-step query (one tool call, no parallel fan-out) and one multi-step query (≥2 tool calls in parallel via the planner). The mocked LLM responses for these fixtures are constructed by replaying what v1.3 `AgentQueryPipeline.run` produced for the same inputs, captured manually by running the v1.3 baseline once with `LOG_LEVEL=DEBUG` and reading the structured logger output. The capture step is part of the Phase 16 plan, not pre-work.
- **D-09:** Parity tests run BEFORE any new feature wiring. The Phase 16 wave structure is: Wave 1 (extract helper + capture v1.3 baseline fixtures), Wave 2 (build `Planner`/`Executor` skeletons, parity tests pass with the new collaborators), Wave 3 (delete duplicated `_execute_tool_call`, switch `AgentQueryPipeline.run` to the new orchestrator). No "new behavior" lands in this phase — that's Phase 17+.

### Synthesizer (intentionally absent)
- **D-10:** There is NO `Synthesizer` class introduced in Phase 16. The "final synthesized answer" semantics are inherited verbatim from v1.3 `AgentQueryPipeline.run`: after the `Executor` finishes, the orchestrator stuffs tool outputs back into `messages` and calls `BaseLLMClient.call_agentic_turn` once more; the resulting assistant turn's text IS the answer. This preserves multi-turn refinement that v1.3 users may have come to depend on (the pipeline can iterate beyond the planner's first plan if the LLM returns more `tool_calls` instead of a final assistant message).
- **D-11:** The Phase 18 `synthesizer.final` SSE event therefore carries the text of that final assistant turn. The "synthesizer" is a logical role, not a class. If a future phase (post-v1.4) wants an explicit `Synthesizer` class for distinct prompting, it's a refactor in its own right.
- **D-12:** As a consequence, the v1.3 `max_iterations=5` cap STILL governs the orchestrator's outer loop (planner emits a plan → executor runs it → orchestrator may re-call the LLM → new plan or final answer → ...). The cap is NOT enforced inside `Executor` (which runs exactly one `ToolPlan`); it's enforced in `AgentQueryPipeline.run`. **Phase 16 acceptance criterion 5** (combined coverage ≥70%) MUST cover the iteration cap branch.

### NLU-03 — query intent absorbed into planner
- **D-13:** No `IntentRouter` class. The planner's `ToolPlan.parallel_groups` shape IS the intent: a single-wave single-step plan = "single-hop retrieve" (Query intent); a single-wave multi-step plan = "parallel multi-tool" (Agent intent); a deferred-to-Phase-17 SwarmTool dispatch = "Swarm intent". A short-form mapping table goes into `docs/agent-architecture.md` in Phase 19 (NOT Phase 16); Phase 16 only ensures the shapes are achievable via the prompt.
- **D-14:** Existing `agent_mode` / `swarm_mode` request fields STAY in `utils/models.py::GenerationRequest` (no breaking change in Phase 16). They continue to gate the legacy three-way routing in `controllers/api.py:202-211`. The decision on `/query?agent_mode=true` deprecation is Phase 19 territory (per v1.4 design doc Open Question #4 — recommendation is "thin alias, not break").

### Claude's Discretion
- Internal naming inside `services/agent/` (file split granularity, helper function names) — pick what reads well.
- Whether `Executor` exposes a generator or returns a final list of `ToolResult`s — both work; pick the one that makes the Phase 18 SSE event emission cleanest. Phase 17 will validate the choice when it adds the registry surface.
- Logging field names for the new `parallel_factor` audit trail (already present in v1.2 audit fields per PROJECT.md row "parallelism factor logged per turn" — REUSE that exact name).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source design and milestone artifacts
- `~/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` — v1.4 design doc, Approach A (incremental refactor). Defines the agent-first inversion strategy and Phase 16's role in it. **The single most important read.**
- `.planning/PROJECT.md` — v1.4 Active requirements (AGENT-06, AGENT-09, NLU-03 mapped to Phase 16); Key Decisions table rows 173, 174, 175, 176 (v1.3 invariants this phase must preserve).
- `.planning/REQUIREMENTS.md` — Phase 16 REQ-IDs with constraints, Out of Scope list, Open Questions #1, #2, #5.
- `.planning/STATE.md` — Carry-Forward decisions table (v1.3 invariants in force) and Open Questions Carried into Planning.

### Code anchors
- `services/pipeline.py:581-1099` — `class AgentQueryPipeline` (refactor target; current `.run` at line 665, `_execute_tool_call` at line 846).
- `services/pipeline.py:1100-1200` — `class SwarmQueryPipeline` (other consumer of `_execute_tool_call` at line 1107; must import from new shared helper after Phase 16).
- `services/generator/llm_client.py` — `BaseLLMClient.call_agentic_turn` interface (v1.2 Phase 11 abstraction); `AgenticTurn` and `ToolCall` Pydantic models the planner and executor consume.
- `utils/models.py` — `ToolCall`, `AgenticTurn` models (DO NOT redefine in `services/agent/`); `GenerationRequest` with `agent_mode`/`swarm_mode` fields.
- `controllers/api.py:202-232` — `/query` and `/query/stream` routes; the three-way routing block (`swarm_mode > agent_mode > default`).
- `services/audit/audit_service.py` — `AuditAction`, `AuditEvent` (line 53 area); `parallel_factor` audit fields established v1.2; agent run must keep these.
- `tests/unit/fixtures/agentic_turn/` — v1.2 wire-fixture pattern that the new `tests/unit/fixtures/agent_parity/` mirrors.
- `tests/unit/test_agent_pipeline_refactor.py` — v1.2 reference test file for `AgentQueryPipeline` behavior; parity tests live alongside it.
- `tests/unit/test_swarm_pipeline.py` — companion test that exercises the `_execute_tool_call` consumer path; must still pass after Phase 16.

### Codebase maps (read once for orientation)
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/CONVENTIONS.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/codebase/TESTING.md`

### Milestones archive (precedent decisions)
- `.planning/milestones/v1.2-ROADMAP.md` — Phase 11 (provider-neutral `call_agentic_turn` + parallel burst) — direct precedent.
- `.planning/milestones/v1.3-ROADMAP.md` — Phase 12 (Fork-Agent Swarm) — origin of the `_execute_tool_call` duplication this phase eliminates.
- `.planning/milestones/v1.3-MILESTONE-AUDIT.md` — documented v1.4 follow-up #1 ("extract `_execute_tool_call` to shared helper") = AGENT-09 here.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`BaseLLMClient.call_agentic_turn`** (`services/generator/llm_client.py`) — provider-neutral; both `Planner` and `Executor` consume this. NEVER add provider-specific code in `services/agent/`.
- **`ToolCall` / `AgenticTurn`** (`utils/models.py`) — Pydantic V2 frozen models from v1.2; reused as-is. `ToolPlan` is the new addition.
- **`utils/cache.py`** (`cache_get`, `cache_set`) — already used by NLU filter extractor. `Planner` MAY cache (planner_input_hash → ToolPlan) but Phase 16 deliberately defers caching to a v1.5 follow-up — keep planner stateless for parity.
- **`AuditAction` / `AuditEvent` / `audit_service.log()`** — direct path used by v1.3 SwarmQueryPipeline; the new orchestrator writes the same audit fields (`parallel_factor`, latency, sources_count) via `log()` to preserve v1.3 audit shape.
- **Existing `tests/unit/fixtures/agentic_turn/`** — fixture directory and loader pattern that the new `tests/unit/fixtures/agent_parity/` clones.

### Established Patterns
- **Mock at consumer path, not source** (v1.3 Phase 13 + 15 convention). New unit tests `monkeypatch.setattr("services.agent.executor.call_agentic_turn", ...)`, NOT `services.generator.llm_client.call_agentic_turn`.
- **Pydantic V2 frozen models** — every new model in `services/agent/` (e.g., `ToolPlan`, `Wave` if introduced) declares `model_config = ConfigDict(frozen=True)`. Match `utils/models.py::ToolCall` style verbatim.
- **mypy --strict + ruff clean** — non-negotiable. Match the existing baseline; do NOT introduce new mypy errors. The pre-existing `pipeline.py` mypy baseline (11 errors) is documented as accepted SCOPE BOUNDARY in v1.3 STATE.md — Phase 16 should not increase that count.
- **`BaseException` (not `Exception`) for `asyncio.gather` isolation** (v1.3 Phase 12 D-01). New `Executor.execute_plan` uses the same scope.
- **Singleton factory pattern** (`get_agent_pipeline()`, `get_swarm_pipeline()`, `get_filter_extractor()`) — NEW collaborators in `services/agent/` follow the same pattern: `get_planner()`, `get_executor()`. `services/pipeline.py::get_agent_pipeline()` continues to exist; its body just constructs `Planner` + `Executor` lazily and threads them in.
- **`parallel_tool_calls=True` (OpenAI) / `disable_parallel_tool_use=False` (Anthropic) explicit in adapter** — Phase 16 does NOT need to change this. The new `Executor` inherits whatever `call_agentic_turn` returns.

### Integration Points
- `controllers/api.py:202-232` — `/query` route stays unchanged in Phase 16. Routing logic preserved (swarm > agent > default). No new endpoint introduced — Phase 18 may add `/agent/v1/run/stream`, but Phase 16 surface is purely internal.
- `services/pipeline.py::AgentQueryPipeline.run` — this is the seam. The body becomes ~10–20 lines: build `Planner` + `Executor` (or pull singletons), call `Planner.plan(req)` → `Executor.execute_plan(plan)` → outer-loop check (max_iterations) → final `call_agentic_turn` for synthesis text → audit write → return `GenerationResponse`.
- `services/pipeline.py::SwarmQueryPipeline._execute_tool_call` — DELETED. Method replaced by `from services.agent.tool_executor import execute_tool_call` import; the call site at the existing usage line continues to work.
- `services/audit/audit_service.py` — no changes; the orchestrator still calls `log()` with the same fields.
- `tests/integration/test_agent_pipeline_parallel.py` (existing v1.2 live demo) — must still pass post-refactor; integration parity is part of the Phase 16 verify gate.

</code_context>

<specifics>
## Specific Ideas

- The user's design doc Q4 answer (in /office-hours session): "改造 AgentQueryPipeline 加 planner+executor + 事件流 trace" — the chosen wedge. Phase 16 implements the planner+executor part; the trace is Phase 18. Implementation must not couple the two so tightly that Phase 18 becomes a new refactor instead of a wiring task.
- The user's stated differentiation vs LangGraph (in /office-hours session): "enterprise-grade (多租户、JWT、RLS、审计) + planner trace 划到 SSE 事件流级别，而不是 intermediate_steps 黑盒." Phase 16 must not regress the enterprise constraint half (multi-tenancy, JWT, RLS, audit). The trace half is delivered in Phase 18.
- 10x roadmap priority order (in /office-hours): Memory → Swarm v2 → MCP → Code-acting. Phase 16 reserves naming room (e.g., `services/agent/` is the umbrella for future `MemoryTool`, `SwarmTool` etc.). No premature implementation.

</specifics>

<deferred>
## Deferred Ideas

### To Phase 17 (Tool Abstraction + RetrieveTool)
- `Tool` Protocol / `BaseTool` ABC declaration.
- `RetrieveTool` wrapping `QueryPipeline.run()`.
- Static class registry; tool authoring guide stub.
- ≥1 additional skeletal tool (`WebSearchTool` or `SQLTool` placeholder).

### To Phase 18 (SSE Planner Trace Event Stream)
- `planner.plan` / `tool.span` / `executor.parallel` / `synthesizer.final` SSE events.
- Event schema documentation in `docs/agent-architecture.md`.
- Latency assertion (parallel queries bounded by `max(tool_latency)`).

### To Phase 19 (Agent-First Docs + Demo + Release)
- README rewrite with agent-first framing.
- `make demo-agent` target.
- Asciinema/gif of parallel fan-out.
- v1.4 release tag.
- **Decision on `/query?agent_mode=true` alias** (Open Question #4 — recommendation: keep alias). Defer to Phase 19 because that's where the surface is locked + documented.
- **NLU-03 mapping table** (`Query / Agent / Swarm` → `ToolPlan` shapes) — written into `docs/agent-architecture.md` in Phase 19; Phase 16 only ensures the shapes are achievable.

### To v1.5+
- **Swarm-as-tool** (Open Question #5) — Phase 16 reserves the design hook (`SwarmQueryPipeline` keeps existing surface; `services/agent/` is the umbrella module where a future `SwarmTool` would live), but does NOT register it as a tool. Decision deferred to v1.5+ AGENT-05 phase.
- **Planner caching** (planner_input_hash → ToolPlan) — keep planner stateless in v1.4 for parity; revisit once the eval gate has v1.4 baselines.
- **Iteration cap policy variants** (Open Question #3) — keep static `max_iterations=5` in v1.4. Adaptive / per-tenant cap is a v1.5+ topic.
- **Explicit `Synthesizer` class** (D-10 / D-11) — only revisit if a future phase wants distinct prompting for the final composing call.
- **AGENT-05 multi-agent debate / sub-agent verify**, MCP plug-in registry, code-acting tools, Memory loop — full 10x roadmap items, all deferred per design doc.

</deferred>

---

*Phase: 16-Planner+Executor-Extraction*
*Context gathered: 2026-05-09*
