# Requirements: EnterpriseRAG v1.5 — Web Search + Multi-Agent Debate + Coverage Lift

**Defined:** 2026-05-10
**Core Value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.

**Milestone goal:** Replace v1.4's `WebSearchTool` placeholder with a Tavily-backed real implementation; introduce AGENT-05 multi-agent debate / sub-agent verify (10x roadmap #2) on top of v1.3 `SwarmQueryPipeline`; lift 5 large modules above per-module ≥ 70% coverage. The agent gains a non-RAG tool that actually queries the live web, the swarm gains a verify dimension on top of v1.3's parallel fan-out, and the coverage gate strengthens on the modules that have carried the most behavior.

**v1.4 requirements archived:** `.planning/milestones/v1.4-REQUIREMENTS.md`

---

## v1.5 Requirements

Twelve checkable requirements grouped into three categories. Each maps to exactly one roadmap phase. v1.4 invariants preserved: PostgreSQL RLS multi-tenancy, JWT auth, audit log, combined coverage ≥ 70%, diff-cover ≥ 80% on touched files, mock-at-consumer-path test pattern, no production-code changes for coverage lift (v1.3 D-04).

### Web Search Tool (AGENT)

- [x] **AGENT-10**: `services/agent/tools/web_search.py::WebSearchTool.run()` body replaced — calls `AsyncTavilyClient.search()` from `tavily-python>=0.7.24,<0.8`. Async-throughout (no sync client in async pipeline). Settings exposed: `tavily_api_key: str = ""`, `tavily_search_depth: str = "basic"`, `tavily_max_results: int = 5`. Settings read from env via Pydantic Settings; key never echoed in logs / errors / SSE frames. Phase 20. ✓ Plan 20-01 (settings) + 20-02 (impl) shipped 2026-05-10.

- [x] **AGENT-11**: Tavily error handling implemented end-to-end. `@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=10), reraise=True)` on the search call. Final-attempt failure converts to typed `ToolResult(metadata={"error": True, "kind": "web_search_failed"})`. Tavily 429 → `kind="quota_exhausted"` (via `tavily.UsageLimitExceededError`). Empty `tavily_api_key` → `kind="tavily_disabled"`. No exception escapes `run()` into orchestrator. Phase 20. ✓ Plan 20-02 shipped 2026-05-10 (15 unit tests, 94.8% coverage).

- [x] **AGENT-12**: Tavily response converts to `RetrievedChunk` shape so existing source-citation flow works without UI rewrite: `metadata.source = url`, `metadata.title = title`, `metadata.chunk_type = "web"`, `metadata.page_number = None`. `static/ui.js` updated to render `URL=<host>` instead of `页=?` when `chunk_type === "web"`. PDF source rendering unchanged. Phase 20. ✓ Plan 20-02 (`_map_tavily_result`) + 20-04 (`hostOf` helper + locator ternary at static/ui.js:28-30) shipped 2026-05-10; 10 static-source assertion tests pass; live UI render approved Plan 20-05 Task C.

- [x] **AGENT-13**: `web_search` added to `AGENT_TOOL_ALLOWLIST` in `services/pipeline.py`. Planner's tool schema list now includes `web_search`. Integration test asserts that for a query unanswerable from the indexed knowledge base, the planner picks `web_search`; for an in-corpus query, it still picks `search_knowledge_base`. Phase 20. ✓ Plan 20-03 shipped 2026-05-10 (commits 3dddfb0/23b360a; allowlist at services/pipeline.py:600; 4 integration tests pass; _AGENT_SYSTEM byte-identical D-01 preserved).

### Multi-Agent Debate / Sub-Agent Verify (AGENT)

- [ ] **AGENT-05**: `services/agent/verifier.py::Verifier` class implemented. Single-pass verifier sub-agent reads N peer answers + their cited evidence chunks, returns `VerifierVerdict` Pydantic V2 frozen model with fields `verdict: Literal["agree","disagree"]`, `final_answer: str`, `dissenting_peers: list[int]`, `evidence_chunk_ids: list[str]`. Verifier uses `BaseLLMClient.call_agentic_turn` (text-only, no tools). System prompt forbids inventing facts; `verdict == "agree"` with empty `evidence_chunk_ids` is treated as disagreement. Phase 21.

- [ ] **AGENT-14**: `GenerationRequest` gains `debate: bool = False` opt-in field. `SwarmQueryPipeline.run()` (and streaming sibling if applicable) appends a verifier hop after the existing `asyncio.gather` peer fan-out when `req.debate=True`. End-to-end latency stays bounded by `max(peer_latency) + verifier_latency` (single verifier call, not N). Existing swarm behavior unchanged when `debate=False`. Phase 21.

- [x] **AGENT-15**: Three new SSE event types added to `utils/models.py` as Pydantic V2 frozen subclasses of `AgentEvent`: `VerifierStartEvent`, `VerifierCompleteEvent`, `VerifierDisagreementEvent`. Events emit through the existing `/api/v1/agent/v1/run/stream` route — wire format unchanged (`event: <type>\ndata: <model_dump_json>\n\n`). `synthesizer.final` remains the terminal event. `docs/agent-architecture.md` Event Schema Reference extended with three new subsections + example payloads. Phase 21. ✓ shipped 2026-05-10 (21-02 schemas + 21-05 wire emission/route dispatch + 21-06 doc extension).

### Coverage Lift (TEST)

- [ ] **TEST-08**: `services/pipeline.py` per-module coverage ≥ 70% (currently ~60-65%). New unit tests under `tests/unit/test_pipeline_coverage.py` (or extending existing) cover `AgentQueryPipeline.run` / `run_streaming` error branches, `SwarmQueryPipeline.run` synthesis path, `_dedup_chunks`, `_build_initial_messages`. Mock at consumer paths only (`services.pipeline.get_planner` etc.). No production-code changes (v1.3 D-04). Phase 22.

- [ ] **TEST-09**: `services/generator/llm_client.py` per-module coverage ≥ 70%. Reuses v1.2 wire fixtures (`tests/unit/fixtures/agent_parity/`) for happy-path; new tests cover `RateLimitError` (429) / `OverloadedError` / `RetryError` / `APIConnectionError` branches across both `AnthropicLLMClient.call_agentic_turn` and `OpenAILLMClient.call_agentic_turn`. Phase 22.

- [ ] **TEST-10**: `services/vectorizer/vector_store.py` per-module coverage ≥ 70%. New tests cover `_build_filter_where` (table-driven over `page_number` int / string / null cases including the v1.4.2 fix), `metadata isinstance str` JSONB-decoding branch (line 347), and HNSW DDL idempotency (`CREATE INDEX IF NOT EXISTS` branch). Phase 22.

- [ ] **TEST-11**: `services/retriever/retriever.py` per-module coverage ≥ 70%. New tests cover `_to_retrieved_chunk` with the v1.4.2 `model_validate` auto-passthrough path (page_number / section_id round-trip), reranker SLA timeout fallback to passthrough (`_rerank_with_sla`), and `_expand_to_parent` `asyncpg.PostgresError` non-fatal branch. Phase 22.

- [ ] **TEST-12**: `services/extractor/extractor.py` per-module coverage ≥ 70%. New tests cover `is_scanned_pdf` 3-page-sample heuristic (text-rich vs scanned), `_detect_header_footer_texts` 10-page-cap branch, OCR-vs-native-extract router, and the v1.4.2 Tesseract OCR engine selection branch. Phase 22.

---

## v1.5 Out of Scope

- **Memory tool** (10x roadmap #1) — needs `/office-hours` to lock the wedge (per-tenant scope, RAG-vs-tool boundary, eviction policy). Defer to v1.6.
- **Code-acting / SQLTool** (10x roadmap #4) — sandbox selection (subprocess+seccomp / Docker / E2B / WASM) and security model unresolved. Defer to v1.6+.
- **UI-03 React/Vue full migration** — single static HTML still sufficient.
- **TEST-07 mutation testing** — coverage gate adequately strengthened by per-module 70% lift; mutation testing is a v1.6+ concern.
- **UI-02 first-deploy browser smoke** — natural confirmation on first production deploy.
- **Tavily Extract / Crawl / Map** — beyond `search` endpoint; not requested.
- **Iterative peer-debate (multi-round critique)** — v1.5 ships single-pass verifier; iterative debate becomes v1.6+ if v1.5 verifier proves valuable.
- **Per-tenant Tavily domain allowlist or budget cap** — premature config surface; rely on Tavily account-level quota.
- **Generic web-search abstraction layer** (SerpAPI / Brave / Tavily switching) — premature; abstraction emerges if a second provider is added.

---

## Constraints (carried from v1.0..v1.4, still in force)

- **PostgreSQL + pgvector backend** with HNSW + RLS multi-tenancy preserved.
- **`diff-cover ≥ 80%`** on all v1.5-touched files (TEST-03 from v1.1).
- **Combined coverage `--fail-under=70`** global floor (TEST-04/06 from v1.3); v1.5 strengthens this on 5 modules.
- **`BaseLLMClient.call_agentic_turn`** non-abstract default-raise — verifier reuses; do NOT add `@abstractmethod`.
- **`asyncio.gather` + `BaseException`** isolation for parallel calls (verifier inherits this).
- **Sub-agents do NOT inherit chat history** (v1.3 D-06) — verifier sees peer answers as data, not as conversation turns.
- **Mock at consumer path** (`services.<mod>.<dep>`), not source — applies to all v1.5 unit tests.
- **No production-code changes for coverage lift** (v1.3 D-04) — TEST-08..12 add tests only; if a module cannot reach 70% without prod changes, document the residual gap in phase SUMMARY.
- **SSE wire format**: `event: <type>\ndata: <model_dump_json>\n\n` — verifier events extend the schema without changing the format.
- **TAVILY_API_KEY** lives in `.env` only (gitignored); `.env.docker` references via `${TAVILY_API_KEY:-}`; never committed; never echoed in logs / errors / SSE frames.

---

## Traceability

| REQ-ID | Phase | Plans |
|--------|-------|-------|
| AGENT-10 | 20 — WebSearchTool Real Implementation (Tavily) | 20-01 (settings) + 20-02 (impl) ✓ |
| AGENT-11 | 20 — WebSearchTool Real Implementation (Tavily) | 20-02 ✓ |
| AGENT-12 | 20 — WebSearchTool Real Implementation (Tavily) | 20-02 (mapping side ✓) + 20-04 (UI render side) |
| AGENT-13 | 20 — WebSearchTool Real Implementation (Tavily) | 20-03 |
| AGENT-05 | 21 — AGENT-05 Multi-Agent Debate / Sub-Agent Verifier | tbd (assigned during `/gsd-plan-phase 21`) |
| AGENT-14 | 21 — AGENT-05 Multi-Agent Debate / Sub-Agent Verifier | tbd |
| AGENT-15 | 21 — AGENT-05 Multi-Agent Debate / Sub-Agent Verifier | 21-02 (schemas) + 21-05 (wire emission + route dispatch) + 21-06 (doc extension) ✓ |
| TEST-08  | 22 — Per-Module 70% Coverage Lift | tbd (assigned during `/gsd-plan-phase 22`) |
| TEST-09  | 22 — Per-Module 70% Coverage Lift | tbd |
| TEST-10  | 22 — Per-Module 70% Coverage Lift | tbd |
| TEST-11  | 22 — Per-Module 70% Coverage Lift | tbd |
| TEST-12  | 22 — Per-Module 70% Coverage Lift | tbd |

**Coverage:** 12/12 requirements mapped to phases; every phase has ≥ 1 requirement; no orphans.
