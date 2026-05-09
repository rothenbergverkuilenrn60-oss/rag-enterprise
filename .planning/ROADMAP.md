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

### 📋 v1.4 Agent-First Architecture Inversion (Phases 16–19) — IN PLANNING (opened 2026-05-09)

**Goal:** Invert the architecture so the agent runtime is the project's core (planner + executor + tool registry), and agentic RAG becomes one tool the agent calls. Source design doc: `~/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` (Approach A — incremental refactor).

- [ ] **Phase 16: Planner + Executor Extraction** (REQ-IDs: AGENT-06, AGENT-09, NLU-03)
  - Refactor `services/pipeline.py::AgentQueryPipeline` into `Planner` + `Executor` + `Synthesizer` collaborators
  - Extract `_execute_tool_call` to a single shared helper used by both `SwarmQueryPipeline` and the new `Executor` (eliminates v1.3-accepted duplication)
  - Subsume NLU-03 into the planner output (intent = `ToolPlan` shape, no separate router)
  - Behavioral parity vs v1.3 baseline asserted by tests before any new behavior lands
  - Success criteria: parity tests green; coverage ≥ 70% combined; no v1.3 invariant regressed (multi-tenancy, JWT, audit)

- [ ] **Phase 17: Tool Abstraction + RetrieveTool** (REQ-IDs: AGENT-07)
  - Define `Tool` Protocol (or `BaseTool` ABC, decided in plan)
  - Wrap `QueryPipeline.run()` as `RetrieveTool` — hybrid + RRF + rerank stays internal
  - Register ≥ 1 additional skeletal tool (`WebSearchTool` or `SQLTool` placeholder) to prove pluggability
  - Static class registry; abstraction clean enough that MCP can replace it later
  - Success criteria: `Executor` dispatches via the registry only; multi-tool integration test green; tool authoring guide stub exists

- [ ] **Phase 18: SSE Planner Trace Event Stream** (REQ-IDs: AGENT-04)
  - Emit `planner.plan` / `tool.span` (start/end/error w/ timing) / `executor.parallel` / `synthesizer.final` on `/query/stream` (and/or new `/agent/v1/run/stream`)
  - Document event schemas in `docs/agent-architecture.md`
  - Latency assertion: agentic queries with N parallel tools bounded by `max(tool_latency)`, not sum
  - Success criteria: streaming smoke test asserts each event type fires once; multi-hop demo query produces visible parallel fan-out in the timeline

- [ ] **Phase 19: Agent-First Docs + Demo + Release** (REQ-IDs: AGENT-08)
  - README rewrite: lead with agent-first architecture; agentic RAG framed as one tool
  - `docs/agent-architecture.md`: planner/executor model + tool authoring + SSE event schema reference
  - `make demo-agent` target: spins up stack and runs multi-hop demo query end-to-end
  - Recorded asciinema/gif of parallel fan-out embedded in README
  - Tag v1.4 release on `main`
  - Success criteria: `make demo-agent` exits 0 from clean checkout; README screenshots/gif render correctly on GitHub; release tag pushed

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
| 16. Planner + Executor Extraction | v1.4 | 0/0 | Pending | — |
| 17. Tool Abstraction + RetrieveTool | v1.4 | 0/0 | Pending | — |
| 18. SSE Planner Trace Event Stream | v1.4 | 0/0 | Pending | — |
| 19. Agent-First Docs + Demo + Release | v1.4 | 0/0 | Pending | — |
