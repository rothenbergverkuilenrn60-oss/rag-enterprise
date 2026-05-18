# Roadmap — EnterpriseRAG

## Milestones

- ✅ **v1.0 Hardening** — Phases 1–6 (shipped 2026-04-27) — [archive](milestones/v1.0-ROADMAP.md)
- ✅ **v1.1 Retrieval Depth & Frontend** — Phases 7–10 (shipped 2026-05-08) — [archive](milestones/v1.1-ROADMAP.md)
- ✅ **v1.2 Agentic Layer + Swarm** — Phase 11 (shipped 2026-05-08) — [archive](milestones/v1.2-ROADMAP.md)
- ✅ **v1.3 Fork Swarm, NLU & Quality** — Phases 12–15 (shipped 2026-05-09) — [archive](milestones/v1.3-ROADMAP.md)
- ✅ **v1.4 Agent-First Architecture Inversion** — Phases 16–19 (shipped 2026-05-10) — [archive](milestones/v1.4-ROADMAP.md)
- ✅ **v1.5 Web Search + Multi-Agent Debate + Coverage Lift** — Phases 20–22 (shipped 2026-05-11) — [archive](milestones/v1.5-ROADMAP.md)
- ✅ **v1.6 Memory Tool — Agent-Authored Long-Term Facts** — Phases 23–25 (shipped 2026-05-17) — [archive](milestones/v1.6-ROADMAP.md)
- ✅ **v1.7 Memory Tech-Debt Burn-Down** — Phases 26–28 (shipped 2026-05-17) — [archive](milestones/v1.7-ROADMAP.md)
- ✅ **v1.8 Production Hardening Round 2** — Phases 29–30 (shipped 2026-05-17) — [archive](milestones/v1.8-ROADMAP.md)
- ✅ **v1.9 Hardening Round 3** — Phases 31–35 (shipped 2026-05-18) — [archive](milestones/v1.9-ROADMAP.md)

<details>
<summary>✅ v1.7 Memory Tech-Debt Burn-Down (Phases 26–28) — SHIPPED 2026-05-17</summary>

- [x] Phase 26: Memory Infra Hygiene (5/5 plans) — completed 2026-05-17
- [x] Phase 27: Test Isolation + Memory Reliability (5/5 plans) — completed 2026-05-17
- [x] Phase 28: Doc Sweep + v1.7 Release (5/5 plans) — completed 2026-05-17

See [milestones/v1.7-ROADMAP.md](milestones/v1.7-ROADMAP.md) for full phase details.

</details>

## Phases

<details>
<summary>✅ v1.9 Hardening Round 3 (Phases 31–35) — SHIPPED 2026-05-18</summary>

- [x] Phase 31: Event-Loop Leak Sweep (1/1 plan) — EVT-02
- [x] Phase 32: mypy `--strict` Cleanup (1/1 plan) — MYPY-02/03/04
- [x] Phase 33: Autouse-Mock Opt-Out + Order-Dependent Failures (2/2 plans, parallel worktrees) — TEST-08/09
- [x] Phase 34: Sentinel Drift Refresh (inline) — TEST-10/11
- [x] Phase 35: Planning Artifact Backfill (inline) — DOC-02/03

Ship: PR #10 (squash `e917a9e`) + PR #12 (squash `d89ca90`); tag `v1.9`.
v1.10 carry-forward: TEST-12 (OCR Cluster C semaphore-loop-binding), TEST-13 (llm_client coverage 68→≥70).

See [milestones/v1.9-ROADMAP.md](milestones/v1.9-ROADMAP.md) for full phase details and [milestones/v1.9-REQUIREMENTS.md](milestones/v1.9-REQUIREMENTS.md) for requirements traceability.

</details>

---

<details>
<summary>✅ v1.8 Production Hardening Round 2 (Phases 29–30) — SHIPPED 2026-05-17</summary>

- [x] Phase 29: TOCTOU + Silent-Skip Enforcement (3/3 plans) — completed 2026-05-17
- [x] Phase 30: Test Infra + mypy Hardening (3 shipped + 1 superseded plan; orchestrator-accepted override on Plan 30-01) — completed 2026-05-17

See [milestones/v1.8-ROADMAP.md](milestones/v1.8-ROADMAP.md) for full phase details and audit findings.

</details>

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

<details>
<summary>✅ v1.6 Memory Tool — Agent-Authored Long-Term Facts (Phases 23–25) — SHIPPED 2026-05-17</summary>

- [x] Phase 23: Background Extractor + schema migration (6/6 plans) — completed 2026-05-16
- [x] Phase 24: pgvector RecallTool + semantic recall rewrite (7/7 plans) — completed 2026-05-16
- [x] Phase 25: Eviction job + GDPR forget API (7/7 plans) — completed 2026-05-17

See [milestones/v1.6-ROADMAP.md](milestones/v1.6-ROADMAP.md) for full phase details.

</details>

<details>
<summary>✅ v1.5 Web Search + Multi-Agent Debate + Coverage Lift (Phases 20–22) — SHIPPED 2026-05-11</summary>

See [milestones/v1.5-ROADMAP.md](milestones/v1.5-ROADMAP.md) for the snapshot at milestone close. Phase details follow for in-tree traceability.

## v1.5 Web Search + Multi-Agent Debate + Coverage Lift (Phases 20–22) — SHIPPED 2026-05-11

**Milestone goal:** Replace v1.4's `WebSearchTool` placeholder with a Tavily-backed real implementation; introduce AGENT-05 multi-agent debate / sub-agent verify on top of v1.3 `SwarmQueryPipeline`; lift 5 large modules above per-module ≥ 70% coverage.

### Phase 20: WebSearchTool Real Implementation (Tavily)
**Goal:** Replace v1.4's `WebSearchTool` placeholder body with a Tavily-backed real implementation. Add `web_search` to `AGENT_TOOL_ALLOWLIST` so the planner can pick it. Map Tavily search results to `RetrievedChunk` so existing source-citation flow works without UI rewrite. Update the static UI to render `URL=<host>` for `chunk_type="web"` instead of `页=?`. End-to-end Tavily integration with tenacity retry + typed error results, no exceptions escaping into the orchestrator.
**Requirements:** AGENT-10, AGENT-11, AGENT-12, AGENT-13
**Depends on:** Phase 17 (v1.4 `BaseTool` + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST`), Phase 19 (`docs/agent-architecture.md` Authoring Tools section as the implementation pattern)
**Canonical refs:** `services/agent/tools/web_search.py` (replace placeholder body), `services/pipeline.py:598` (`AGENT_TOOL_ALLOWLIST`), `static/ui.js` (chunk_type rendering), `requirements.txt` (pin `tavily-python`), `.env.docker` (key placeholder)
**Success Criteria:**
1. `WebSearchTool.run()` issues async Tavily search via `AsyncTavilyClient`; happy-path returns `ToolResult(content, chunks, metadata)` with chunks shaped as `RetrievedChunk(metadata=ChunkMetadata(source=url, title=title, chunk_type="web", page_number=None), content=snippet)`.
2. Tavily errors handled at three levels: 5xx/timeout → `kind="web_search_failed"`, 429 → `kind="quota_exhausted"`, missing/empty key → `kind="tavily_disabled"`. Tenacity 3-attempt exponential backoff on transient failures; final-attempt failure converts to typed error `ToolResult` (no raise into orchestrator).
3. `AGENT_TOOL_ALLOWLIST` includes `web_search`; planner schemas include the tool; integration test asserts an unanswerable-from-KB query causes the planner to pick `web_search` and an in-corpus query still picks `search_knowledge_base`.
4. `static/ui.js` source rendering: when `chunk_type === "web"`, displays `URL=<host>` (extracted from `metadata.source`) instead of `页=?`; PDF source rendering unchanged. UI smoke test verifies a mixed query renders both source types correctly.
5. TAVILY_API_KEY never appears in git history, planning docs, logs, or SSE error frames; pre-commit / repo grep confirms absence of `tvly-` prefix in tracked files; `.env` is gitignored; `.env.docker` uses `${TAVILY_API_KEY:-}` substitution.
**Plans:** 5 plans (Wave 1 → 2 → 3 → 4; Plans 03 + 04 run in parallel on Wave 3; TDD on Plans 02 + 03)
Plans:
- [x] 20-01-PLAN.md — Wave 1 (execute): Tavily settings (3 fields) + requirements.txt pin + .env.docker placeholder ✓ shipped 2026-05-10 (commits efc4fa8, 7fff13a)
- [x] 20-02-PLAN.md — Wave 2 (TDD): WebSearchTool real impl (RED→GREEN→REFACTOR) — _tavily_search retry helper + 3 typed-error kinds + RetrievedChunk mapping + D-15 source-side redaction ✓ shipped 2026-05-10 (commits dd4e5af, edf7a67, 57485a1; 15 tests; 94.8% coverage)
- [x] 20-03-PLAN.md — Wave 3 (TDD): AGENT_TOOL_ALLOWLIST literal edit + planner-picks-web_search integration test (4 tests) + _AGENT_SYSTEM byte-identical ✓ shipped 2026-05-10 (commits 3dddfb0, 23b360a)
- [x] 20-04-PLAN.md — Wave 3 (execute): static/ui.js URL=<host> locator-token branch + hostOf helper + 10 static-source assertion tests + ui.css byte-identical ✓ shipped 2026-05-10 (commits 3317949, d10f286)
- [x] 20-05-PLAN.md — Wave 4 (execute, autonomous:false): .pre-commit-config.yaml tvly- regex hook + SC5 secret-redaction smoke test (3 tests) + human-verify mixed-source UI render ✓ shipped 2026-05-10 (commits 7508fa5, 6242293, 72c2046; human-verify approved)


### Phase 21: AGENT-05 Multi-Agent Debate / Sub-Agent Verifier
**Goal:** Introduce a single-pass verifier sub-agent that runs after `SwarmQueryPipeline`'s `asyncio.gather` peer fan-out when `req.debate=True`. Verifier reads N peer answers + their cited evidence chunks and emits a structured `VerifierVerdict` (agree / disagree). On disagreement, the synthesizer composes a final response that surfaces the divergence and the evidence-supported answer. Three new SSE event types extend the v1.4 schema; `synthesizer.final` remains terminal. Latency stays bounded by `max(peer) + verifier`, not `sum`.
**Requirements:** AGENT-05, AGENT-14, AGENT-15
**Depends on:** Phase 12 (v1.3 `SwarmQueryPipeline`), Phase 16 (v1.4 `Planner`/`Executor`/`Synthesizer` triad), Phase 18 (v1.4 SSE event schema in `docs/agent-architecture.md`)
**Canonical refs:** `services/pipeline.py::SwarmQueryPipeline` (verifier hop integration), `services/generator/llm_client.py::BaseLLMClient.call_agentic_turn` (provider-neutral verifier LLM call), `utils/models.py` (new `VerifierVerdict`, `VerifierStartEvent`, `VerifierCompleteEvent`, `VerifierDisagreementEvent` Pydantic V2 frozen models), `controllers/api.py::agent_run_stream` (event passthrough), `docs/agent-architecture.md` (Event Schema Reference extension)
**Success Criteria:**
1. `services/agent/verifier.py::Verifier` class implemented; `verify(peer_answers: list[SubAgentAnswer], evidence: list[RetrievedChunk]) → VerifierVerdict`; uses `BaseLLMClient.call_agentic_turn` text-only (no tools); system prompt forbids inventing facts; `verdict == "agree"` with empty `evidence_chunk_ids` is forced to disagreement.
2. `GenerationRequest.debate: bool = False` opt-in field added; `SwarmQueryPipeline.run()` appends verifier hop after `asyncio.gather` peer fan-out when `req.debate=True`; existing swarm behavior unchanged when `debate=False`. Latency assertion in integration test: `total ≤ max(peer_latency) + verifier_latency + small_overhead`, NOT `sum(peer_latency)` and NOT `N × verifier_latency`.
3. Three new SSE event types added (`VerifierStartEvent`, `VerifierCompleteEvent`, `VerifierDisagreementEvent`) as Pydantic V2 frozen subclasses of `AgentEvent`; events emit through existing `/api/v1/agent/v1/run/stream` route; wire format unchanged; `synthesizer.final` remains terminal in all paths.
4. `docs/agent-architecture.md` Event Schema Reference extended with three new subsections + example payloads; backward-compat note documents that debate-mode events are additive and non-debate flows unchanged.
5. v1.3 invariants intact under integration test: PostgreSQL RLS isolates tenants; audit log records verifier sub-agent calls with same fields as v1.3 swarm; combined coverage stays ≥ 70%; no production code changes when `debate=False`.

### Phase 22: Per-Module 70% Coverage Lift
**Goal:** Lift five large modules — `services/pipeline.py`, `services/generator/llm_client.py`, `services/vectorizer/vector_store.py`, `services/retriever/retriever.py`, `services/extractor/extractor.py` — above per-module ≥ 70% coverage. New tests only; no production-code changes (v1.3 D-04 lock). Mock at consumer paths (`services.<mod>.<dep>`) per v1.3 Phase 13/15 pattern. Existing combined-coverage `--fail-under=70` global floor strengthened on these modules so per-module measurement now matches global.
**Requirements:** TEST-08, TEST-09, TEST-10, TEST-11, TEST-12
**Depends on:** Phase 13 (v1.3 mock-at-consumer pattern), Phase 15 (combine job topology, parallel=false), Phase 16 / 17 / 18 / 20 / 21 (test new code paths added in v1.4 + v1.5)
**Canonical refs:** `tests/unit/test_*_coverage.py` (new files; one per module), v1.2 wire fixtures at `tests/unit/fixtures/agent_parity/`, `pyproject.toml [tool.coverage.run]`, `pytest.ini`
**Success Criteria:**
1. `services/pipeline.py` per-module coverage ≥ 70% under `coverage report --fail-under=70`. New tests cover `AgentQueryPipeline.run`/`run_streaming` error branches, `SwarmQueryPipeline` synthesis path (debate=False), `_dedup_chunks`, `_build_initial_messages`. Mock at consumer paths only.
2. `services/generator/llm_client.py` per-module coverage ≥ 70%. Reuses v1.2 wire fixtures for happy-path; new tests cover `RateLimitError` (429) / `OverloadedError` / `RetryError` / `APIConnectionError` branches across both `AnthropicLLMClient.call_agentic_turn` and `OpenAILLMClient.call_agentic_turn`.
3. `services/vectorizer/vector_store.py` per-module coverage ≥ 70%. New tests cover `_build_filter_where` (table-driven over `page_number` int / string / null sentinel cases), JSONB `isinstance(metadata, str)` decoding branch (line 347), HNSW DDL idempotency.
4. `services/retriever/retriever.py` per-module coverage ≥ 70%. New tests cover `_to_retrieved_chunk` `ChunkMetadata.model_validate` auto-passthrough (page_number / section_id round-trip), reranker SLA timeout fallback to `PassthroughReranker` (`_rerank_with_sla`), `_expand_to_parent` `asyncpg.PostgresError` non-fatal warning branch.
5. `services/extractor/extractor.py` per-module coverage ≥ 70%. New tests cover `is_scanned_pdf` 3-page-sample heuristic (text-rich vs scanned PDF cases), `_detect_header_footer_texts` 10-page-cap branch, OCR-vs-native-extract router, Tesseract OCR engine selection branch (v1.4.2 fix). All 5 modules pass `coverage report --fail-under=70` simultaneously; no production-code changes; `diff-cover --fail-under=80` passes on all touched test files.

</details>

<details>
<summary>✅ v1.4 Agent-First Architecture Inversion (Phases 16–19) — SHIPPED 2026-05-10</summary>

See [milestones/v1.4-ROADMAP.md](milestones/v1.4-ROADMAP.md) for the snapshot at milestone close. Phase details follow for in-tree traceability.

## v1.4 Agent-First Architecture Inversion (Phases 16–19) — SHIPPED 2026-05-10

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
- [x] 19-01-PLAN.md — Wave 1 (TDD): services/agent/_demo_stubs.py — DemoStubPlanner + make_fake_retrieve_tool + build_demo_registry + DEMO_QUERY (4-tool fan-out fixture promoted from Phase 18 SSE tests)
- [x] 19-02-PLAN.md — Wave 2 (TDD): services/agent/_demo_runner.py + tests/integration/test_demo_agent.py — in-process + subprocess demo correctness gate (11-event sequence + max-not-sum latency bound)
- [x] 19-03-PLAN.md — Wave 3 (execute): Makefile demo-agent + demo-agent-record targets (bilingual help, asciinema-guarded record path)
- [x] 19-04-PLAN.md — Wave 3 (execute): docs/agent-architecture.md insert ## Planner / Executor Model section before ## Authoring Tools (D-09); closes ROADMAP SC2
- [x] 19-05-PLAN.md — Wave 4 (execute, autonomous: false): record docs/demo.cast via make demo-agent-record; redaction gates; visual playback verification
- [x] 19-06-PLAN.md — Wave 5 (execute): full README.md rewrite per D-02 section order — agent-first framing; v1.3 technical content preserved under ## Platform features
- [x] 19-07-PLAN.md — Wave 1 (execute, parallel with 19-01): CHANGELOG.md (keep-a-changelog v1.0..v1.4) + docs/v1.4-design.md (verbatim copy of gstack milestone-design)
- [x] 19-08-PLAN.md — Wave 6 (execute, autonomous: false): draft v1.4 release-notes-v1.4.md + release-tag-commands.md; user runs the ceremony post-PR-merge per D-12

</details>

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
| 16. Planner + Executor Extraction | v1.4 | 3/3 | Complete ✓ | 2026-05-09 |
| 17. Tool Abstraction + RetrieveTool | v1.4 | 3/3 | Complete ✓ | 2026-05-09 |
| 18. SSE Planner Trace Event Stream | v1.4 | 5/5 | Complete ✓ | 2026-05-09 |
| 19. Agent-First Docs + Demo + Release | v1.4 | 8/8 | Complete ✓ | 2026-05-10 |
| 20. WebSearchTool Real Implementation (Tavily) | v1.5 | 5/5 | Complete ✓ | 2026-05-10 |
| 21. AGENT-05 Multi-Agent Debate / Sub-Agent Verifier | v1.5 | 6/6 | Complete ✓ | 2026-05-10 |
| 22. Per-Module 70% Coverage Lift | v1.5 | 7/7 | Complete ✓ | 2026-05-11 |
| 23. Background Extractor + schema migration | v1.6 | 6/6 | Complete ✓ | 2026-05-16 |
| 24. pgvector RecallTool + semantic recall rewrite | v1.6 | 7/7 | Complete ✓ | 2026-05-16 |
| 25. Eviction job + GDPR forget API | v1.6 | 7/7 | Complete ✓ | 2026-05-17 |
| 26. Memory Infra Hygiene | v1.7 | 5/5 | Complete ✓ | 2026-05-17 |
| 27. Test Isolation + Memory Reliability | v1.7 | 5/5 | Complete ✓ | 2026-05-17 |
| 28. Doc Sweep + v1.7 Release | v1.7 | 5/5 | Complete ✓ | 2026-05-17 |
| 29. TOCTOU + Silent-Skip Enforcement | v1.8 | 3/3 | Complete ✓ | 2026-05-17 |
| 30. Test Infra + mypy Hardening | v1.8 | 3/4 (1 superseded) | Complete ✓ | 2026-05-17 |
| 31. Event-Loop Leak Sweep | v1.9 | 1/1 | Complete    | 2026-05-18 |
| 32. mypy --strict Cleanup | v1.9 | 1/1 | Complete    | 2026-05-18 |
| 33. Autouse Opt-Out + Order-Dependent Failures | v1.9 | 0/0 | Not started | - |
| 34. Sentinel Drift Refresh | v1.9 | 0/0 | Not started | - |
| 35. Planning Artifact Backfill | v1.9 | 0/0 | Not started | - |
