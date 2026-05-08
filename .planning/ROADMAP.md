# Roadmap — EnterpriseRAG

## Milestones

- ✅ **v1.0 Hardening** — Phases 1–6 (shipped 2026-04-27) — [archive](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Retrieval Depth & Frontend** — Phases 7–10 (shipped 2026-05-08) — [archive](milestones/v1.1-ROADMAP.md)
- 🚧 **v1.2 Agentic Layer + Swarm** — Phase 11 (in progress)

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

### v1.2 Agentic Layer + Swarm (Phase 11)

- [ ] **Phase 11: Provider-Agnostic Agentic Layer + Parallel Tool-Call Burst** — `BaseLLMClient.call_agentic_turn` abstraction (Step 0) + single-turn multi-call execution via `asyncio.gather` (v0)

**Phase grouping rationale:** Step 0 (abstraction) and v0 (parallel burst) ship as one phase per the office-hours design D14 decision (2026-05-08). The abstraction without a real consumer is unverifiable; the parallel burst without the abstraction can't be added cleanly to OpenAI mode. Both share the same code surface (`utils/llm_client.py`, `services/generator/llm_client.py`, `services/pipeline.py:514-748`) and the same test surface (parametrized provider mocks + live OpenAI integration). True swarm with fork agents (the office-hours v1 layer) is deferred to v1.3 — it's a deeper architectural change (multi-agent orchestration, inter-agent coordination, stop conditions) that benefits from a clean Step 0 + v0 baseline first.

## Phase Details

### Phase 11: Provider-Agnostic Agentic Layer + Parallel Tool-Call Burst

**Goal:** `AgentQueryPipeline` with `agent_mode=True` runs the real tool-use loop on both OpenAI and Anthropic providers, and a single LLM turn returning N ≥ 2 tool calls executes them concurrently — closing the OpenAI silent-fallback gap from `services/pipeline.py:599-604` and adding parallel-burst latency reduction.
**Depends on:** v1.1 (must run on the shipped pgvector + OCR + filter stack; tests use existing query infrastructure)
**Requirements:** AGENT-01, AGENT-02
**Success Criteria** (what must be TRUE):
  1. `BaseLLMClient.call_agentic_turn(messages, tools, ...)` exists as an abstract method with a provider-neutral return shape (text + tool_calls + finish_reason); `AnthropicLLMClient` and `OpenAILLMClient` both implement it.
  2. `services/pipeline.py:599-604` Anthropic-only fallback is REMOVED; running `AgentQueryPipeline` with `llm_provider="openai"` (the project default) executes the real tool-use loop end-to-end, honoring `MAX_ITERATIONS = 5`.
  3. When the LLM returns N ≥ 2 tool calls in a single turn, `AgentQueryPipeline` executes them concurrently via `asyncio.gather`; the total turn-internal latency is bounded by the slowest tool, not the sum of all tools.
  4. Audit log per turn records the parallelism factor (number of tool calls executed in parallel).
  5. Live integration test against OpenAI through OneAPI gateway (`gpt-4o-mini`) submits a multi-dimension `agent_mode=True` query, verifies ≥ 2 tool calls executed concurrently, and verifies all results made it into the next turn's message list. Anthropic side mock-tested if no `ANTHROPIC_API_KEY` available.
**Plans:** TBD

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
| 11. Provider-Agnostic Agentic Layer + Parallel Burst | v1.2 | 0/0 | Not started | - |

## Coverage Validation

All 2 v1.2 REQ-IDs map to exactly one phase:

| REQ-ID | Track | Phase |
|--------|-------|-------|
| AGENT-01 (E-1) | E — Agentic Layer | Phase 11 |
| AGENT-02 (E-2) | E — Agentic Layer | Phase 11 |

**Coverage:** 2/2 requirements mapped ✓
**Orphans:** none
**Duplicates:** none
