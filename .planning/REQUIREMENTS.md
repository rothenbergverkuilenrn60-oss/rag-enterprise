# Requirements: EnterpriseRAG v1.4 — Agent-First Architecture Inversion

**Defined:** 2026-05-09
**Core Value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.

**Source design doc:** `/home/ubuntu/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` (Approach A — incremental refactor, recommended).

**Milestone goal:** Invert the architecture so the agent runtime is the project's core (planner + executor + tool registry); agentic RAG becomes one tool the agent calls. Today's v1.3 layout is "RAG-first, agent-as-mode" with four parallel pipelines and `AgentQueryPipeline` as one option. v1.4 makes the agent loop primary and wraps `QueryPipeline.run()` as `RetrieveTool`.

---

## v1.4 Requirements

Six checkable requirements. Each maps to exactly one roadmap phase. v1.3 invariants (multi-tenancy, RLS, JWT, audit, ≥70% combined coverage, ≥80% diff-cover on touched files) are preserved by construction — see Constraints below.

### Agent Architecture (AGENT)

- [ ] **AGENT-06**: Refactor `services/pipeline.py::AgentQueryPipeline` into three explicit collaborators — `Planner` (first LLM call returns a `ToolPlan`: list of `ToolCall` objects with declared parallelism), `Executor` (runs `ToolPlan` via `asyncio.gather`, yields `tool.span` events), and `Synthesizer` (final LLM call composes the response from accumulated tool outputs). Behavioral parity vs the v1.3 baseline `AgentQueryPipeline` is asserted by tests before any new behavior lands. Multi-tenancy / audit / JWT / RLS untouched.

- [ ] **AGENT-09**: Extract `_execute_tool_call` to a single shared helper used by both `SwarmQueryPipeline` and the new `Executor`. Eliminates the verbatim duplication accepted at v1.3 close (decision row 176 in PROJECT.md Key Decisions). `inspect.getsource` token-equivalent normalized comparison is no longer required after this lands — replaced by direct identity (`is` check) on the helper function reference.

- [ ] **AGENT-07**: Define a provider-neutral `Tool` Protocol (or `BaseTool` ABC, decided in Phase 17 plan). Wrap `QueryPipeline.run()` as `RetrieveTool` — hybrid retrieval + RRF fusion + reranker logic stays inside the tool, unchanged. Register at minimum one additional skeletal tool (`WebSearchTool` placeholder OR `SQLTool` placeholder) to prove pluggability. Static class registry in v1.4; abstraction clean enough that MCP plug-in discovery (10x roadmap #3) can replace it later without callsite changes.

- [ ] **AGENT-04**: Emit a planner trace event stream on `/query/stream` (and/or new `/agent/v1/run/stream`) with at minimum these event types: `planner.plan` (the `ToolPlan` the planner just emitted), `tool.span` with start / end / error variants and per-call timing/inputs/outputs, `executor.parallel` marker showing fan-out factor, `synthesizer.final` carrying the composed answer. Event schemas documented in `docs/agent-architecture.md`. Supersedes the original AGENT-04 carry-forward note "streaming SSE for agentic + swarm responses."

### Documentation, Demo, Distribution (AGENT)

- [ ] **AGENT-08**: README rewrite that frames the architecture as agent-first (lead with the agent loop; agentic RAG is one of several tools). Add `docs/agent-architecture.md` covering the planner/executor model, tool authoring guide, and the SSE event schema reference. Add a `make demo-agent` target that spins up the stack and runs a multi-hop demo query end-to-end so reviewers can reproduce the whoa locally without reading code. Record an asciinema/gif of the parallel fan-out and embed it in the README.

### NLU (subsumed)

- [ ] **NLU-03**: Query intent classification absorbed into the planner's first call — no separate router. The planner emits a `ToolPlan` whose shape is the intent (single-hop retrieve, parallel multi-tool, short-circuit answer). NLU-03 is satisfied implicitly when AGENT-06 lands; the only explicit deliverable is a documented mapping between historical intent labels (`Query` / `Agent` / `Swarm`) and `ToolPlan` shapes for migration clarity.

---

## Out of Scope (deferred to v1.5+)

- **AGENT-05** — Inter-agent coordination / multi-agent debate / sub-agent verify. 10x roadmap item #2; foundation in v1.4 leaves design hooks (e.g. `SwarmQueryPipeline` callable as a tool) but does not deliver the feature.
- **MCP plug-in registry** — 10x roadmap #3. Static registry in v1.4; MCP comes later behind the same `Tool` protocol.
- **Code-acting tools (sandboxed Python / SQL execution)** — 10x roadmap #4. Reserves namespace; not built in v1.4.
- **Memory + cross-session learning** — 10x roadmap #1. Reserves namespace via `MemoryTool` placeholder; learning loop deferred.
- **5 large modules below per-module 70%** (`pipeline.py`, `llm_client.py`, `vector_store.py`, `retriever.py`, `extractor.py`) — combined floor still gates; per-module deep-mocking deferred.
- **UI-03** — React/Vue full migration. Static HTML demo for agent-first is enough.
- **TEST-07** — Mutation testing. Independent quality concern.
- **UI-02 first-deploy browser smoke test** — independent ops concern.
- **Backwards-incompatible API change** — keep `/query?agent_mode=true` working as a thin alias for the new agent endpoint (Open Question #4 — recommend alias).

---

## Constraints (v1.3 invariants — must hold)

| Constraint | Source | Enforcement |
|------------|--------|-------------|
| PostgreSQL RLS multi-tenancy on every tool call | v1.0 | Tool dispatch threads `tenant_id` end-to-end; integration test asserts cross-tenant isolation |
| JWT denylist + 32-char min, per-route rate limits | v1.0 | Existing middleware untouched; agent endpoint inherits via FastAPI router |
| Audit log on every agentic turn (incl. swarm fields) | v1.2 / v1.3 | New `Executor` writes the same audit fields; new event types do not bypass audit |
| Combined coverage `--fail-under=70` | v1.3 Phase 15 | New v1.4 modules included from day one — no exemption |
| Diff-cover ≥ 80% on touched files | v1.1 Phase 10 | All v1.4 PRs gated |
| Pydantic V2 frozen models, mypy --strict, ruff clean, no bare except | v1.0 + project standard | Carries; `ToolPlan`, `ToolCall`, `Tool` protocol all conform |
| `BaseLLMClient.call_agentic_turn` abstraction | v1.2 Phase 11 | New planner / executor reuse this — no provider-specific code in pipeline body |

---

## Coverage / Traceability

| REQ-ID  | Phase | Status |
|---------|-------|--------|
| AGENT-06 | Phase 16 | Pending |
| AGENT-09 | Phase 16 | Pending |
| NLU-03   | Phase 16 | Pending |
| AGENT-07 | Phase 17 | Pending |
| AGENT-04 | Phase 18 | Pending |
| AGENT-08 | Phase 19 | Pending |

**Coverage:**
- v1.4 requirements: 6 total
- Mapped to phases: 6
- Unmapped: 0 ✓

---

## Open Questions (resolve during phase planning)

1. **Planner output schema fields.** `steps: list[ToolCall]`, `parallel_groups: list[list[int]]`, `rationale: str` — confirm shape in Phase 16 plan.
2. **Tool registration mechanism.** Static class registry in v1.4 (recommended); MCP later behind same Protocol.
3. **Iteration cap policy.** v1.3 hardcoded `max_iterations=5` — keep static for v1.4 to constrain blast radius; revisit if eval flags tail latency.
4. **Backwards compatibility.** `/query?agent_mode=true` as thin alias for `/agent/v1/run` — recommend alias to protect open-source repo external users.
5. **Sub-agent reuse.** `SwarmQueryPipeline` callable as a tool the planner can dispatch — recommend yes; confirm in Phase 16 discussion. AGENT-05 (debate / verify) still deferred to v1.5+.
6. **Cross-model second opinion.** Worth running `codex review` on the source design doc before locking Phase 16 plan — cheapest premise stress test.

---

*Requirements defined: 2026-05-09*
*Last updated: 2026-05-09 — v1.4 milestone opened*
