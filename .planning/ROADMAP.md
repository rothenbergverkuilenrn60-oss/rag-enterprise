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
- 🚧 **v1.8 Production Hardening Round 2** — Phases 29–30 (in planning, opened 2026-05-17)

<details>
<summary>✅ v1.7 Memory Tech-Debt Burn-Down (Phases 26–28) — SHIPPED 2026-05-17</summary>

- [x] Phase 26: Memory Infra Hygiene (5/5 plans) — completed 2026-05-17
- [x] Phase 27: Test Isolation + Memory Reliability (5/5 plans) — completed 2026-05-17
- [x] Phase 28: Doc Sweep + v1.7 Release (5/5 plans) — completed 2026-05-17

See [milestones/v1.7-ROADMAP.md](milestones/v1.7-ROADMAP.md) for full phase details.

</details>

## v1.8 Production Hardening Round 2 (Phases 29–30) — IN PLANNING

**Milestone goal:** Close v1.7-deferred hardening items — promote near-duplicate audit-mode to silent-skip (after closing TOCTOU race), clean up 32 pre-existing openai SDK drift test failures, fix +14 event-loop singleton leaks exposed by the Phase 27 `uses_redis` marker rollout, resolve mypy --strict accumulation, rewrite save_facts precheck tests against bulk-SELECT shape. Zero new user-facing capabilities — pure reliability + test infra polish.

**Carry-forward gates** (inherited from v1.7): `diff-cover ≥ 80%` on touched files; combined coverage `--fail-under=70`; INSERT-ONLY `audit_log` invariant; audit-mode-before-enforce (SK-01 promotes audit-mode→enforce per this discipline, post-TOC-01); audit-write failure must NOT block destructive action.

### Phase 29: TOCTOU + Silent-Skip Enforcement

**Goal:** Close the precheck/INSERT race on `LongTermMemory.save_facts`, then promote v1.7 near-duplicate audit-mode (D-09) to silent-skip enforcement. Rewrite precheck unit tests against the bulk-SELECT shape (same code paths).

**Requirements:** TOC-01, SK-01, TEST-INFRA-02

**Success criteria:**
1. Two parallel `save_facts` writers with the same `(user_id, tenant_id)` + fact text produce exactly 1 row in `long_term_facts` (TOC-01 acceptance). TOCTOU mitigation choice (ON CONFLICT vs advisory-lock vs WITH ... RETURNING) locked at v1.8 discussion + documented in plan.
2. When `_is_near_duplicate` returns `True` for a candidate, the candidate is NOT included in `rows_to_insert`; `executemany` inserts only non-duplicate rows; `MEMORY_NEAR_DUPLICATE_SKIPPED` audit row still emitted. v1.7 pin test `test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows` flipped to `..._inserts_non_dup_rows_only` form. `save_fact` wrapper (D-12) inherits via delegation.
3. `save_facts` precheck unit tests rewritten against bulk-SELECT mock shape; `nearest_distance=None` branch covered explicitly; assertions match C1 SQL shape (`unnest($1::text[]) WITH ORDINALITY` + `vec_txt::vector` cast). Per-file LOC delta ≤ +150; no production-code changes from TEST-INFRA-02 alone.

**Plans:** 3 plans
- [x] 29-00-PLAN.md — TOC-01: advisory-lock wraps precheck+INSERT in `save_facts` (TDD, Wave 1) ✓ shipped 2026-05-17 (commits bc9c523, 23b0d18, 9892b72, bb45835)
- [x] 29-01-PLAN.md — SK-01: silent-skip filter excludes dups from `rows_to_insert` (TDD, Wave 2, depends on 29-00) ✓ shipped 2026-05-17 (commits 44278ab, cf916e2, 5bbae8f, c1d7bfe)
- [x] 29-02-PLAN.md — TEST-INFRA-02: rewrite precheck unit tests to C1 bulk-SELECT shape (execute, Wave 3, depends on 29-00, 29-01) ✓ shipped 2026-05-17 (commits 12d6ed9, 0122b1e, ce14dea)

### Phase 30: Test Infra + mypy Hardening

**Goal:** Clean up the test surface that's been masking real failures + finish the mypy --strict sweep. Fixes 32 openai-SDK-drift failures + 14 event-loop singleton leaks + 1 known-flaky extractor_e2e test + parametric-type annotations.

**Requirements:** OAI-01, EVT-01, TEST-INFRA-01, MYPY-01

**Success criteria:**
1. All 32 enumerated openai-SDK-drift unit tests pass with the new `APIError(request=...)` construction shape. `pytest tests/unit/ -m 'not benchmark'` on master post-fix shows green. No production-code changes (test-only) unless the test mirrors a production codepath (OAI-01).
2. Each of the +14 event-loop leak sites (enumerated via `pytest tests/integration/ -v 2>&1 | grep "no current event loop" | sort -u`) either migrates to the `create_app()` factory pattern or adds an explicit per-test loop fixture. Marker rollout (`@pytest.mark.uses_redis`) introduces zero regressions in integration suite. Curated `_SINGLETON_INVENTORY` in `tests/factories/app.py` grows from 34 to cover the +14 (EVT-01).
3. `uv run pytest tests/integration/test_extractor_e2e.py -v` passes on a clean checkout. Fix path documented in plan SUMMARY: either (a) earlier `embedder_or_mock` patching, (b) CI pre-download of bge-m3, or (c) direct mock of `HuggingFaceEmbedder.__init__` (TEST-INFRA-01).
4. `uv run mypy --strict config/settings.py` returns "Success: no issues found in 1 source file". Full-repo `uv run mypy --strict` scan: surfaced violations either fixed or explicitly silenced with `# type: ignore[error-code]` + comment justifying the silence (MYPY-01).

**Plans:** 4 plans (Wave 1 → Wave 2 (overlap halt gate) → Wave 3)
- [x] 30-00-PLAN.md — OAI-01: `make_api_error()` helper in tests/factories/openai_errors.py (DEVIATION: 32 callsites stale — no APIError construction failures on current master; executor pivoted to fix event-loop / Redis fixture leaks. Helper landed for future SDK drift. 16 RED → 1200 passed.) ✓ shipped 2026-05-17 (commits 030d774, 0c28ae9, f0a2d33, 8e681b2)
- [~] 30-01-PLAN.md — EVT-01: +14 event-loop leak sites — PARTIALLY SUPERSEDED by Plan 30-00 deviation. Re-evaluate scope before running (likely now 0-2 remaining sites + `_SINGLETON_INVENTORY` extension only).
- [x] 30-02-PLAN.md — TEST-INFRA-01: mock HuggingFaceEmbedder + CrossEncoderReranker init at tests/integration/conftest.py (Rule-2 deviation: reranker also raises FileNotFoundError on bge-m3-rerank — both mocked in same fixture) ✓ shipped 2026-05-17 (commits 4cbb4e0, 7b5c6e5)
- [x] 30-03-PLAN.md — MYPY-01: fix config/settings.py:154 + bounded sweep cap=25 — 32→7 mypy errors (NET -25); 1 fix + 25 silenced with `# type: ignore[error-code]` + `# why:`; 7 overflow → deferred-items.md ✓ shipped 2026-05-17 (commits 3736b62, 2f67cd7, a9db41d, ee3273c)

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
| 29. TOCTOU + Silent-Skip Enforcement | v1.8 | 0/? | Planning | — |
| 30. Test Infra + mypy Hardening | v1.8 | 0/? | Planning | — |
