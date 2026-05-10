# Phase 12: Fork-Agent Swarm - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

When a `GenerationRequest` has `swarm_mode=True`, decompose the user query into N independent sub-questions via a coordinator LLM call, run N isolated sub-agent coroutines concurrently (each calling `call_agentic_turn` with a fresh `messages` list), synthesize all answers in a second LLM call, and emit one unified `GenerationResponse` with a full swarm audit trail.

Out of scope: NLU-based filter extraction for sub-queries (Phase 13), frontend changes (Phase 14), coverage floor (Phase 15).

</domain>

<decisions>
## Implementation Decisions

### Architecture
- **D-01:** Introduce a new `SwarmQueryPipeline` class in `services/pipeline.py`. `AgentQueryPipeline` remains unchanged as the single-agent path. No modification to the existing class.
- **D-02:** Add a new `get_swarm_pipeline()` factory function (following the existing `get_agent_pipeline()` pattern). `get_agent_pipeline()` is not modified and continues to return `AgentQueryPipeline`.
- **D-03:** N=1 edge case: if the coordinator LLM call returns only one sub-question, `SwarmQueryPipeline.run()` delegates to `get_agent_pipeline().run(req)` without spawning swarm machinery.

### Swarm Trigger
- **D-04:** Add `swarm_mode: bool = False` to `GenerationRequest` in `utils/models.py`. This is the explicit opt-in gate; callers (API layer, tests) set it.
- **D-05:** Coordinator = LLM call with a decomposition system prompt. Output is a JSON list of sub-question strings. Capped at `MAX_SWARM_AGENTS` (default 5, env-var-configurable per OPS-01). No sub-questions field on `GenerationRequest` — the coordinator produces them.

### Memory Context Inheritance
- **D-06:** Sub-agents start with clean context. Each sub-agent's `messages` list = `[{"role": "user", "content": sub_question}]`. Session chat history (`short_term[-6:]`) is NOT injected into sub-agents. Isolation is the priority (matches AGENT-03 AC#1).

### Partial Failure Handling
- **D-07:** Use `asyncio.gather(*coros, return_exceptions=True)`. A failed sub-agent produces an error marker string (e.g., `"[Sub-agent {i} failed: {exc!r}]"`) that is passed to the synthesis LLM alongside successful results. The swarm always returns a response.
- **D-08:** Audit log records per-agent failure status. Fields: `swarm_n`, `per_agent_turns: list[int]`, `per_agent_tool_calls: list[int]`, `swarm_latency_ms`, `synthesis_latency_ms` (as specified in STATE.md).

### Caps and Config
- **D-09:** `MAX_SWARM_AGENTS = 5` and `MAX_SWARM_TURNS_PER_AGENT = 5` are class-level constants backed by `settings` env vars (OPS-01 pattern — same as `MODEL_DIR`).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirement
- `.planning/REQUIREMENTS.md` §AGENT-03 (E-3) — Full acceptance criteria for fork-agent swarm (5 ACs)
- `.planning/ROADMAP.md` §Phase 12 — Success criteria, depends-on, UI hint

### Core Codebase
- `services/pipeline.py` — `AgentQueryPipeline` (single-agent, starting at line 532); `IngestionPipeline`, `QueryPipeline` above it; factory functions at bottom. New `SwarmQueryPipeline` goes in this file.
- `utils/models.py` — `GenerationRequest` (line 205, add `swarm_mode: bool = False`), `AgenticTurn` (line 260), `ToolCall` (line 243)
- `services/generator/llm_client.py` — `call_agentic_turn` abstraction (provider-agnostic)
- `services/audit/audit_service.py` — `AuditEvent`, `log_query()`, `AuditResult` enum

### Prior Phase Context
- `.planning/STATE.md` §Phase 12 Implementation Notes — locked constraints: coordinator = LLM call, synthesis = LLM call, N=1 fallback, audit fields
- No prior CONTEXT.md files exist (Phase 12 is the first phase of v1.3)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AgentQueryPipeline._execute_tool_call()` (`pipeline.py` ~line 727): side-effect-free tool execution coroutine — sub-agents in `SwarmQueryPipeline` can reuse the same tool execution pattern (or call a shared helper)
- `AgentQueryPipeline._AGENT_TOOLS` and `_AGENT_SYSTEM`: same tool definitions and system prompt apply to each sub-agent
- `asyncio.gather` pattern already battle-tested in `AgentQueryPipeline` for parallel tool calls within a single turn

### Established Patterns
- **OPS-01 config pattern:** Class constants backed by `settings.*` env vars (see `MAX_ITERATIONS = 5` in `AgentQueryPipeline`). Apply same pattern for `MAX_SWARM_AGENTS` and `MAX_SWARM_TURNS_PER_AGENT`.
- **ERR-01 narrow exceptions:** `(anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError)` — use same tuple for sub-agent error catching; do NOT catch generic `Exception`.
- **Audit pattern:** `self._audit.log_query(...)` at end of `run()`. Swarm adds new fields to the `extra` dict without breaking existing `log_query` signature.
- **`return_exceptions=True` gather:** Already used in test fixtures; production path adds it at the swarm level.

### Integration Points
- `GenerationRequest.swarm_mode` → API layer routes to `get_swarm_pipeline().run(req)`
- `SwarmQueryPipeline` calls `self._llm.call_agentic_turn(...)` for coordinator decomposition AND for each sub-agent turn loop
- `get_agent_pipeline()` called by `SwarmQueryPipeline` for N=1 fallback
- `self._audit.log_query(...)` called at swarm end with extended fields

</code_context>

<specifics>
## Specific Ideas

No specific examples beyond STATE.md notes. Implementation open to standard asyncio patterns.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 12-Fork-Agent-Swarm*
*Context gathered: 2026-05-08*
