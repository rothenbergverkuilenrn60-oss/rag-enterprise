# Requirements — v1.3 Fork Swarm, NLU & Quality

**Defined:** 2026-05-08
**Status:** Active

---

## v1 Requirements

### Track E — Agentic Layer

#### REQ E-3 (AGENT-03): True fork-agent swarm with isolated sub-agent contexts

**As a** user issuing a multi-dimension query (e.g., "审计上月所有未结案件的产假天数、病假规定、加班补偿政策") with `agent_mode=True`
**I want** the system to automatically decompose my query into N independent sub-queries and pursue each with a dedicated sub-agent (isolated message history, tool registry, and iteration budget)
**So that** complex multi-faceted questions are answered with full depth on each dimension, without one sub-question crowding out another's context

**Background:** v1.2 shipped `asyncio.gather` parallel tool-call burst within a single agent turn — multiple tool calls execute concurrently, but all share one message history and one iteration budget. True swarm is different: each sub-question gets its own agent with isolated context, its own tool-use loop, and its own stop condition. The coordinator synthesizes N sub-agent answers into one final response. The v1.2 `call_agentic_turn` abstraction is the foundation — sub-agents reuse the same interface.

**Acceptance criteria:**
1. `AgentQueryPipeline` (or a new `SwarmQueryPipeline`) includes a coordinator that decomposes a multi-dimension query into N sub-queries (N ≥ 2 for swarm to activate; N = 1 falls back to single-agent mode).
2. Each sub-agent runs an independent `call_agentic_turn` loop with its own `messages: list`, `tools: list`, and `max_iterations` budget; no shared message state between sub-agents.
3. All N sub-agents execute concurrently (via `asyncio.gather` or equivalent); total swarm latency is bounded by the slowest sub-agent, not the sum.
4. The coordinator collects all N sub-agent final answers and performs a synthesis LLM call to produce one unified response citing all sub-results.
5. A global stop condition (`MAX_SWARM_AGENTS` config, default 5; `MAX_SWARM_TURNS_PER_AGENT` config, default 5) prevents unbounded expansion.
6. Audit log per swarm invocation records: N sub-agents spawned, per-sub-agent turn count, per-sub-agent tool calls, total latency, synthesis latency.
7. Unit tests: coordinator decomposition logic (mock LLM decomposer), sub-agent isolation (verify no shared state), synthesis call (mock final LLM), max-agents/max-turns enforcement. Integration test: live multi-dimension query → N sub-agents → synthesis → final answer references all N dimensions.

---

### Track NLU — Query Understanding

#### REQ NLU-02: LLM-based filter extractor fallback

**As a** user whose query uses natural language to reference a page or section (e.g., "关于第三章的内容" instead of "第3章") that the regex extractor misses
**I want** the system to automatically fall back to an LLM call to extract the page/section filter
**So that** filtered retrieval works for the full range of Chinese query expressions, not just the patterns covered by the regex

**Background:** `services/nlu/filter_extractor.py` uses regex patterns for `第N页`/`第N.M节` style queries (QUERY-01, v1.1). These cover the most common patterns but miss paraphrases and natural language variants. The LLM fallback should activate only when regex returns empty, to preserve zero-cost behavior on regex hits.

**Acceptance criteria:**
1. `FilterExtractor.extract(query: str) -> QueryFilter | None` calls the LLM only when the regex path returns `None` (no match). The LLM is never called when regex succeeds.
2. LLM fallback result is cached by query string (e.g., in Redis with a TTL matching the existing cache layer, or a local `functools.lru_cache` for in-process caching). Identical queries incur at most one LLM call per cache TTL window.
3. The LLM prompt instructs the model to return a structured `QueryFilter`-compatible JSON object (with `page_number`, `section_id` fields, nullable). Invalid JSON or missing fields are caught and treated as "no filter" (`None`), never propagating exceptions to the caller.
4. `FilterExtractor` exposes a `fallback_source` field on the returned filter (`"regex"` | `"llm"` | `None`) so callers can log and trace which path was used.
5. Unit tests: regex-hit path (LLM never called), regex-miss → LLM-hit path, regex-miss → LLM-invalid-JSON path (returns None), cache-hit path (LLM called once for N identical queries). Integration test: query using natural language section reference → LLM fallback → correct `QueryFilter` produced.

---

### Track UI — Frontend

#### REQ UI-02: Frontend multi-file split and DOM modernization

**As a** developer maintaining the EnterpriseRAG UI
**I want** the frontend JavaScript and CSS extracted from `static/ui.html` into separate `static/ui.js` and `static/ui.css` files, with the inline JS modernized to use current DOM APIs
**So that** the frontend is easier to read, edit, and test without opening a monolithic HTML file, and browser developer tools can apply source maps

**Background:** `static/ui.html` currently contains all JavaScript and CSS inline. The file is served via FastAPI `StaticFiles` with the `static/index.html → ui.html` symlink. Extraction must preserve this serve path.

**Acceptance criteria:**
1. `static/ui.html` contains no `<script>` blocks with inline JavaScript (only `<script src="ui.js">`) and no `<style>` blocks with inline CSS (only `<link rel="stylesheet" href="ui.css">`).
2. `static/ui.js` and `static/ui.css` exist and are referenced correctly; FastAPI `StaticFiles` serves them alongside `ui.html` without configuration changes.
3. All `onclick=`, `onsubmit=`, and other inline event handlers in `ui.html` are replaced with `addEventListener` calls in `ui.js`.
4. Global variable references are replaced with `document.getElementById` / `document.querySelector` calls where they reference DOM elements.
5. If the JS split benefits from ES module imports (e.g., utility functions), a lightweight bundler (Vite or esbuild) is introduced with a `npm run build` step that outputs to `static/`; the FastAPI layer requires no changes. If not needed, no bundler is introduced — this criterion is optional and decided at implementation time.
6. Visual regression: the UI renders identically to the pre-split version for the primary user flows (document upload, query submission, result display).

---

### Track TEST — Coverage

#### REQ TEST-04: Aggregate coverage across unit and integration pipelines

**As a** developer reviewing CI results
**I want** the coverage report to reflect execution from both unit tests and integration tests combined
**So that** service paths exercised only by integration tests count toward the coverage floor, giving an accurate picture of actual test coverage

**Background:** Currently `coverage report` runs only on unit test output. Integration tests exercise additional paths (e.g., full pipeline end-to-end, multi-tenant routing) that don't appear in the unit coverage report. `coverage combine` merges multiple `.coverage` files into one combined report.

**Acceptance criteria:**
1. CI runs `coverage run` for both unit and integration test suites, producing separate `.coverage.unit` and `.coverage.integration` files.
2. `coverage combine .coverage.unit .coverage.integration` produces a `.coverage` file; `coverage report` and `coverage xml` run on the combined artifact.
3. Combined coverage report is the source of truth used by the global floor check (TEST-06) and the diff-cover gate (TEST-03).
4. CI badge / PR comment reflects combined coverage, not unit-only.
5. No regression in existing `diff-cover` gate behavior — per-file new-code gate continues to work on combined `.coverage`.

#### REQ TEST-06: Raise global coverage floor from 46% to 70%

**As a** developer making changes to any service module
**I want** the CI to block merges that drop combined coverage below 70%
**So that** the codebase maintains a meaningful test baseline that prevents regression in core service paths

**Background:** The 46% floor was set in v1.0 as a temporary guard. v1.0–v1.2 added tests on new code but didn't backfill legacy modules. Raising to 70% requires covering service paths in the modules currently below threshold.

**Acceptance criteria:**
1. `.coveragerc` (or `pyproject.toml` `[tool.coverage.report]`) sets `fail_under = 70`.
2. CI step that checks the global floor runs `coverage report --fail-under=70` on the combined `.coverage` artifact (after TEST-04 combine step).
3. The per-file new-code diff-cover gate (TEST-03, `diff-cover ≥ 80%`) continues to run independently and is not affected.
4. All service modules that were below 70% threshold at v1.2 close have new unit tests covering their primary execution paths.
5. Coverage report in CI artifacts shows per-module breakdown, making it easy to identify remaining gaps.

---

## Future Requirements (deferred to v1.4+)

- **AGENT-04**: Streaming SSE for agentic + swarm responses — real-time sub-agent progress events
- **AGENT-05**: Inter-agent coordination and result sharing — sub-agents can pass partial results to each other
- **NLU-03**: Query intent classification — route to `QueryPipeline` vs `AgentQueryPipeline` vs `SwarmQueryPipeline` based on query complexity
- **UI-03**: Full React/Vue component migration — if mid-modernization proves insufficient
- **TEST-07**: Mutation testing — verify test suite catches logic bugs, not just execution paths

---

## Out of Scope (v1.3)

- React/Vue frontend framework — v1.3 ceiling is multi-file split + DOM cleanup + optional lightweight bundler; no component framework
- Streaming SSE for swarm responses — deferred to v1.4 (AGENT-04); adds significant complexity surface
- Inter-agent communication/coordination — sub-agents are fully isolated in v1.3; result sharing deferred to v1.4 (AGENT-05)
- Automatic query routing (agent vs swarm selection) — manual `agent_mode` flag only in v1.3; NLU-03 deferred
- Anthropic live integration tests for swarm — mock-tested; live test deferred until `ANTHROPIC_API_KEY` available in CI
- Raising coverage above 70% — 70% is the v1.3 ceiling; further raise in v1.4+

---

## Traceability

| REQ-ID | Track | Phase | Status |
|--------|-------|-------|--------|
| AGENT-03 (E-3) | E — Agentic Layer | Phase 12 | Implemented (verification pending) |
| NLU-02 | NLU — Query Understanding | Phase 13 | In Progress (Wave 1 done — class + dataclass + factory; Wave 2 + 3 pending) |
| UI-02 | UI — Frontend | Phase 14 | Pending |
| TEST-04 | TEST — Coverage | Phase 15 | Pending |
| TEST-06 | TEST — Coverage | Phase 15 | Pending |

**Coverage:** 5/5 requirements mapped ✓
**Orphans:** none
**Duplicates:** none
