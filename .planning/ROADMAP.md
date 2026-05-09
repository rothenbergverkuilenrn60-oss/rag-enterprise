# Roadmap — EnterpriseRAG

## Milestones

- ✅ **v1.0 Hardening** — Phases 1–6 (shipped 2026-04-27) — [archive](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Retrieval Depth & Frontend** — Phases 7–10 (shipped 2026-05-08) — [archive](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Agentic Layer + Swarm** — Phase 11 (shipped 2026-05-08) — [archive](milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Fork Swarm, NLU & Quality** — Phases 12–15 (shipped 2026-05-09) — [archive](milestones/v1.3-ROADMAP.md)
- 📋 **v1.4 Agent-First Architecture Inversion** — Phases 16–19 (in planning, opened 2026-05-09)

## Phases

<details>
<summary>✅ v1.0 Hardening (Phases 1–6) — SHIPPED 2026-04-27</summary>

- [x] Phase 1: pgvector Foundation (4/4 plans) — completed 2026-04-22
- [x] Phase 2: Security Hardening + Operational Fixes (3/3 plans) — completed 2026-04-23
- [x] Phase 3: Error Handling Sweep (3/3 plans) — completed 2026-04-24
- [x] Phase 4: Image Extraction (4/4 plans) — completed 2026-04-25
- [x] Phase 5: Async Ingest Tracking (3/3 plans) — completed 2026-04-26
- [x] Phase 6: Test Coverage and Eval (3/3 plans) — completed 2026-04-27

See [milestones/v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) for full phase details.

</details>

<details>
<summary>✅ v1.1 Retrieval Depth & Frontend (Phases 7–10) — SHIPPED 2026-05-08</summary>

- [x] Phase 7: OCR Engine Integration (2/2 plans) — completed 2026-05-08
- [x] Phase 8: Multimodal Metadata + Query Filter (5/5 plans) — completed 2026-05-08
- [x] Phase 9: Frontend Extraction (1/1 plan) — completed 2026-05-08
- [x] Phase 10: Coverage Gate on New Code (1/1 plan) — completed 2026-05-08

See [milestones/v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md) for full phase details.

</details>

<details>
<summary>✅ v1.2 Agentic Layer + Swarm (Phase 11) — SHIPPED 2026-05-08</summary>

- [x] Phase 11: Provider-Agnostic Agentic Layer + Parallel Tool-Call Burst (4/4 plans) — completed 2026-05-08

See [milestones/v1.2-ROADMAP.md](milestones/v1.2-ROADMAP.md) for full phase details.

</details>

<details>
<summary>✅ v1.3 Fork Swarm, NLU & Quality (Phases 12–15) — SHIPPED 2026-05-09</summary>

- [x] Phase 12: Fork-Agent Swarm (3/3 plans) — completed 2026-05-09
- [x] Phase 13: LLM Filter Fallback (3/3 plans) — completed 2026-05-09
- [x] Phase 14: Frontend Split and DOM Modernization (1/1 plan) — completed 2026-05-09
- [x] Phase 15: Coverage Combine and 70% Floor (2/2 plans) — completed 2026-05-09

See [milestones/v1.3-ROADMAP.md](milestones/v1.3-ROADMAP.md) for full phase details.

</details>

## v1.4 Agent-First Architecture Inversion (Phases 16–19) — IN PLANNING (opened 2026-05-09)

**Milestone goal:** Invert the architecture so the agent runtime is the project's core (planner + executor + tool registry), and agentic RAG becomes one tool the agent calls. Source design doc: `~/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` (Approach A — incremental refactor, no framework lock-in).

### Phase 16: Planner + Executor Extraction
**Goal:** Refactor `services/pipeline.py::AgentQueryPipeline` into three explicit collaborators (`Planner`, `Executor`, `Synthesizer`); extract `_execute_tool_call` to a shared helper used by both `SwarmQueryPipeline` and the new `Executor`; subsume query-intent classification into the planner's `ToolPlan` output. Behavioral parity vs v1.3 baseline asserted before any new behavior lands.
**Requirements:** AGENT-06, AGENT-09, NLU-03
**Depends on:** Phase 11 (v1.2 `call_agentic_turn` abstraction), Phase 12 (v1.3 `SwarmQueryPipeline` source for `_execute_tool_call` shared helper)
**Canonical refs:** `~/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md`, `services/pipeline.py`, `services/generator/llm_client.py`
**Success Criteria:**
1. `AgentQueryPipeline.run` body delegates to `Planner` → `Executor` → `Synthesizer`; collaborators each have a single-purpose Pydantic V2 frozen model interface (`ToolPlan`, `ToolCall`).
2. Behavioral parity test fixture (recorded v1.3 transcript) replays through the new pipeline and produces byte-identical tool-call sequences for the parity scenarios.
3. `_execute_tool_call` exists in exactly one location; both `SwarmQueryPipeline` and the new `Executor` import the helper (no copy duplicates; verified via `grep -rn "def _execute_tool_call"` returning ≤ 1 match).
4. Query intent (single-hop / parallel / short-circuit) is encoded as `ToolPlan` shape — no separate `IntentRouter` class introduced.
5. v1.3 invariants intact under integration test: PostgreSQL RLS isolates tenants on every tool call; audit log carries the same fields as v1.3; combined coverage ≥ 70%.

### Phase 17: Tool Abstraction + RetrieveTool
**Goal:** Define a provider-neutral `Tool` Protocol; wrap `QueryPipeline.run()` as `RetrieveTool` with hybrid retrieval + RRF + rerank kept internal; register ≥ 1 additional skeletal tool to prove pluggability via static class registry; abstraction clean enough that MCP plug-in discovery (10x roadmap #3) replaces it later without callsite changes.
**Requirements:** AGENT-07
**Depends on:** Phase 16 (Planner + Executor + Synthesizer extracted)
**Canonical refs:** `services/pipeline.py::QueryPipeline`, `services/retriever/retriever.py`, `services/reranker_service/`
**Success Criteria:**
1. `Tool` Protocol (or `BaseTool` ABC, decided in plan) declared with `name`, `description`, `parameters_schema`, `async run(...)` surface.
2. `RetrieveTool` wraps `QueryPipeline.run()`; v1.3 retrieval behavior preserved on existing test fixtures (no recall/rank regression).
3. ≥ 1 additional skeletal tool registered (`WebSearchTool` or `SQLTool` placeholder) — exercises the registry with a non-RAG implementation.
4. `Executor` dispatches strictly through the registry; no direct imports of `RetrieveTool` or other tools by name in pipeline code.
5. Tool authoring guide stub exists at `docs/agent-architecture.md#authoring-tools` with one runnable example.
**Plans:** 3 plans (Wave 1 → Wave 2 → Wave 3; TDD on Waves 1-2)
Plans:
- [ ] 17-01-PLAN.md — Wave 1 (TDD): BaseTool ABC + ToolRegistry + ToolResult/ToolContext + provider_name ClassVar on BaseLLMClient
- [ ] 17-02-PLAN.md — Wave 2 (TDD): RetrieveTool + RefinedRetrieveTool (sharing _retrieve_impl) + WebSearchTool placeholder; byte-identical-to-_AGENT_TOOLS parity assertion
- [ ] 17-03-PLAN.md — Wave 3 (execute): Executor seam swap to registry; delete services/agent/tool_executor.py; AGENT_TOOL_ALLOWLIST in pipeline.py; SwarmQueryPipeline import switch via shim alias; docs/agent-architecture.md#authoring-tools stub

### Phase 18: SSE Planner Trace Event Stream
**Goal:** Emit a planner trace event stream on `/query/stream` (and/or new `/agent/v1/run/stream`) so peer engineers can see the agent's reasoning as it happens; documented schemas; latency assertion that parallel tool calls are bounded by `max(tool_latency)`, not sum.
**Requirements:** AGENT-04
**Depends on:** Phase 16 (collaborator boundaries), Phase 17 (tool registry — `tool.span` references tool names)
**Canonical refs:** `services/pipeline.py` (existing SSE infra), `controllers/api.py` (`/query/stream` route), `docs/agent-architecture.md` (created in Phase 17, extended here)
**Success Criteria:**
1. Streaming endpoint emits at minimum: `planner.plan` (with the `ToolPlan` JSON), `tool.span.start` / `tool.span.end` / `tool.span.error` (per-call timing, inputs, outputs/error), `executor.parallel` (fan-out factor), `synthesizer.final` (composed answer).
2. Event schemas documented in `docs/agent-architecture.md` with example payloads; one example per event type.
3. Streaming smoke test asserts each event type fires exactly the expected count for a known multi-hop query.
4. Latency assertion in integration test: agentic query with N parallel tools completes in `max(tool_latency) + planner + synthesizer + small overhead`, NOT `sum(tool_latency)`.
5. Multi-hop demo query produces visible parallel fan-out in the SSE timeline (manual reproduction via `make demo-agent` in Phase 19).
**Plans:** 5 plans (Wave 1 → 2 → 3 → 4 → 5; TDD on Waves 1-4; sequential since each plan reads the prior plan's output)
Plans:
- [x] 18-01-PLAN.md — Wave 1 (TDD): AgentEvent base + 6 frozen Pydantic V2 event subclasses in utils/models.py (planner.plan / tool.span.start/end/error / executor.parallel / synthesizer.final)
- [x] 18-02-PLAN.md — Wave 2 (TDD): Executor.execute_plan_streaming async generator (as_completed loop, BaseException isolation, span_id generation)
- [x] 18-03-PLAN.md — Wave 3 (TDD): AgentQueryPipeline.run_streaming async generator (smoke sequence + latency-bound + redaction + error tests; _persist_turn audit gate)
- [x] 18-04-PLAN.md — Wave 4 (TDD): POST /agent/v1/run/stream route in controllers/api.py (named-event SSE, rate limit, threat model focus)
- [x] 18-05-PLAN.md — Wave 5 (execute): docs/agent-architecture.md ## Event Schema Reference section (6 subsections + EventSource consumer snippet)

### Phase 19: Agent-First Docs + Demo + Release
**Goal:** README rewrite leading with agent-first architecture (RAG framed as one tool); `docs/agent-architecture.md` covers planner/executor model + tool authoring + SSE event schema; `make demo-agent` target reproduces the whoa from a clean checkout; recorded asciinema/gif embedded in README; v1.4 release tagged.
**Requirements:** AGENT-08
**Depends on:** Phase 16, Phase 17, Phase 18 (all features in place before docs/demo lock the surface)
**Canonical refs:** `README.md`, `docs/agent-architecture.md`, `Makefile`, source design doc Distribution Plan
**Success Criteria:**
1. README "What This Is" / "Architecture" sections lead with agent-first framing; agentic RAG appears under "Tools the agent calls."
2. `docs/agent-architecture.md` has Planner/Executor model section, Tool authoring guide, SSE event schema reference — each with a runnable code snippet.
3. `make demo-agent` target spins up the Docker stack and runs the multi-hop demo query end-to-end from a clean checkout; exits 0; produces SSE event log to stdout.
4. Asciinema (or gif) recording of the parallel fan-out demo embedded in README; renders correctly on GitHub.
5. v1.4 release tag created on `main` after merge; release notes link to design doc + the four phase summaries.
**Plans:** 8 plans (Wave 1 → 2 → 3 → 4 → 5 → 6; TDD on Waves 1-2)
Plans:
- [ ] 19-01-PLAN.md — Wave 1 (TDD): services/agent/_demo_stubs.py — DemoStubPlanner + make_fake_retrieve_tool + build_demo_registry + DEMO_QUERY (4-tool fan-out fixture promoted from Phase 18 SSE tests)
- [x] 19-02-PLAN.md — Wave 2 (TDD): services/agent/_demo_runner.py + tests/integration/test_demo_agent.py — in-process + subprocess demo correctness gate (11-event sequence + max-not-sum latency bound)
- [ ] 19-03-PLAN.md — Wave 3 (execute): Makefile demo-agent + demo-agent-record targets (bilingual help, asciinema-guarded record path)
- [ ] 19-04-PLAN.md — Wave 3 (execute): docs/agent-architecture.md insert ## Planner / Executor Model section before ## Authoring Tools (D-09); closes ROADMAP SC2
- [ ] 19-05-PLAN.md — Wave 4 (execute, autonomous: false): record docs/demo.cast via make demo-agent-record; redaction gates; visual playback verification
- [ ] 19-06-PLAN.md — Wave 5 (execute): full README.md rewrite per D-02 section order — agent-first framing; v1.3 technical content preserved under ## Platform features
- [ ] 19-07-PLAN.md — Wave 1 (execute, parallel with 19-01): CHANGELOG.md (keep-a-changelog v1.0..v1.4) + docs/v1.4-design.md (verbatim copy of gstack milestone-design)
- [ ] 19-08-PLAN.md — Wave 6 (execute, autonomous: false): draft v1.4 release-notes-v1.4.md + release-tag-commands.md; user runs the ceremony post-PR-merge per D-12

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. pgvector Foundation | v1.0 | 4/4 | Complete ✓ | 2026-04-22 |
| 2. Security Hardening + Operational Fixes | v1.0 | 3/3 | Complete ✓ | 2026-04-23 |
| 3. Error Handling Sweep | v1.0 | 3/3 | Complete ✓ | 2026-04-24 |
| 4. Image Extraction | v1.0 | 4/4 | Complete ✓ | 2026-04-25 |
| 5. Async Ingest Tracking | v1.0 | 3/3 | Complete ✓ | 2026-04-26 |
| 6. Test Coverage and Eval | v1.0 | 3/3 | Complete ✓ | 2026-04-27 |
| 7. OCR Engine Integration | v1.1 | 2/2 | Complete ✓ | 2026-05-08 |
| 8. Multimodal Metadata + Query Filter | v1.1 | 5/5 | Complete ✓ | 2026-05-08 |
| 9. Frontend Extraction | v1.1 | 1/1 | Complete ✓ | 2026-05-08 |
| 10. Coverage Gate on New Code | v1.1 | 1/1 | Complete ✓ | 2026-05-08 |
| 11. Provider-Agnostic Agentic Layer + Parallel Burst | v1.2 | 4/4 | Complete ✓ | 2026-05-08 |
| 12. Fork-Agent Swarm | v1.3 | 3/3 | Complete ✓ | 2026-05-09 |
| 13. LLM Filter Fallback | v1.3 | 3/3 | Complete ✓ | 2026-05-09 |
| 14. Frontend Split and DOM Modernization | v1.3 | 1/1 | Complete ✓ | 2026-05-09 |
| 15. Coverage Combine and 70% Floor | v1.3 | 2/2 | Complete ✓ | 2026-05-09 |
| 16. Planner + Executor Extraction | v1.4 | 2/3 | Wave 1 + 2 executed; Wave 3 pending | — |
| 17. Tool Abstraction + RetrieveTool | v1.4 | 0/0 | Pending | — |
| 18. SSE Planner Trace Event Stream | v1.4 | 0/0 | Pending | — |
| 19. Agent-First Docs + Demo + Release | v1.4 | 3/8 | Plans 19-01, 19-02, 19-07 complete | — |
