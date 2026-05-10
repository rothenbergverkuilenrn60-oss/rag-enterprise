# Phase 20: WebSearchTool Real Implementation (Tavily) - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace v1.4's `services/agent/tools/web_search.py::WebSearchTool` placeholder body with a Tavily-backed real implementation using `AsyncTavilyClient` from `tavily-python>=0.7.24,<0.8`. Add `web_search` to `AGENT_TOOL_ALLOWLIST` in `services/pipeline.py:598` so the planner LLM sees its schema. Map Tavily search results into `RetrievedChunk(metadata=ChunkMetadata(source=url, title=title, chunk_type="web", page_number=None), content=snippet)` so the existing source-citation flow works without UI rewrite. Extend `static/ui.js` to render `URL=<host>` instead of `页=?` when `chunk_type === "web"`. End-to-end tenacity retry + typed error `ToolResult` (no exceptions escape into orchestrator); `TAVILY_API_KEY` never appears in git history, planning docs, logs, or SSE error frames.

OUT OF SCOPE for Phase 20: AGENT-05 verifier (Phase 21), per-module coverage lift (Phase 22), Tavily Extract/Crawl/Map endpoints, SerpAPI/Brave/Tavily abstraction layer, per-tenant Tavily quota or domain allowlist, MCP plug-in discovery (10x roadmap #3, deferred to v1.6+).

</domain>

<decisions>
## Implementation Decisions

### Planner trigger policy

- **D-01:** Selection is **description-driven** — planner LLM picks between `search_knowledge_base` and `web_search` purely from each tool's `description` field. `_AGENT_SYSTEM` prompt at `services/pipeline.py:617-665` is **NOT changed** in Phase 20 (preserves v1.3/v1.4 parity fixtures; no re-baseline).
- **D-02:** `WebSearchTool.description` carries the **real-time/external bias** wording. Recommended text: *"Search the public web for current/real-time information, news, recent events, or topics not covered by the internal knowledge base. Prefer search_knowledge_base for indexed corpus questions."* Steering lives INSIDE the tool descriptor, not in the system prompt — so prompt parity is preserved.
- **D-03:** **`web_search` is always present in `AGENT_TOOL_ALLOWLIST`** — no startup-time filtering on `tavily_api_key` presence. When the key is empty, `WebSearchTool.run()` short-circuits with `ToolResult(is_error=True, content="Web search not configured.", metadata={"error": True, "kind": "tavily_disabled"})`. Behavior is uniform across dev/CI/prod; key absence is visible in audit log and SSE `tool.span.error`.
- **D-04:** **Phase 20 SC3 integration test = two recorded fixtures.** (a) Real-time query (e.g., "What's the weather in Beijing today?") → planner emits `ToolPlan` whose first `ToolCall.name == "web_search"`. (b) In-corpus query (e.g., "GB standard §3.10 透光面 definition") → planner emits `ToolCall.name == "search_knowledge_base"`. Mock the LLM client at the **consumer path** (`services.agent.planner.<llm_attr>` or equivalent under v1.4 Phase 16 `Planner` shape) returning canned tool_use blocks; real `Planner` code path runs.

### Tavily client lifecycle + Settings flow

- **D-05:** **Module-level lazy singleton** `get_tavily_client()` factory in `services/agent/tools/web_search.py`. First call constructs `AsyncTavilyClient(api_key=settings.tavily_api_key)`; subsequent calls reuse the instance (httpx connection pool stays warm). Test override: `monkeypatch.setattr("services.agent.tools.web_search.get_tavily_client", lambda: stub_client)`. Mirrors v1.4 `get_planner` / `get_executor` / `get_tool_registry` factory pattern.
- **D-06:** **Three new fields on existing `config/settings.py::Settings`** (Pydantic V2 `BaseSettings`), placed adjacent to `openai_api_key` / `anthropic_api_key`:
  - `tavily_api_key: str = ""`
  - `tavily_search_depth: str = "basic"` *(allowed values per Tavily SDK: `basic`, `fast`, `advanced`, `ultra-fast`)*
  - `tavily_max_results: int = 5`
  No new `TavilySettings` sub-model; single Settings entrypoint convention preserved (v1.0).
- **D-07:** `WebSearchTool` reads settings via **module-level `settings = get_settings()` import** at the top of `services/agent/tools/web_search.py`. Inside `run()`, fields are read as `settings.tavily_api_key` etc. **`ToolContext` shape (Phase 17 D-03: `req`, `tf`, `retriever`, `llm`) is NOT extended** — adding `settings` would ripple to all existing tools. Test override via `monkeypatch.setattr("services.agent.tools.web_search.settings", stub_settings)`.
- **D-08:** **Tenacity scope = inner private async helper.** `_tavily_search(query: str) -> dict[str, Any]` is decorated with `@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=10), reraise=True)` and is the only thing wrapping `await client.search(...)`. `WebSearchTool.run()` calls `_tavily_search`; on `tenacity.RetryError` (or the underlying httpx exception when `reraise=True`), `run()` catches and converts to a typed-error `ToolResult`. Arg parsing, schema mapping, and the `tavily_disabled` short-circuit are NOT inside the retry boundary.

### Web chunk identity (`RetrievedChunk` shape)

- **D-09:** **`chunk_id = f"web:{sha1(url).hexdigest()[:16]}"`** — stable, dedup-friendly, fixed-length (20 chars). Hash collision risk negligible at v1.5 scale. SSE `tool.span` payloads / audit log entries get short readable IDs. Full URL still preserved in `metadata.source`.
- **D-10:** **`doc_id = "web"` constant** for all web results. RetrievedChunk dedup logic (`_dedup_chunks` in `services/pipeline.py`) keys on `chunk_id`; `doc_id` is a coarse bucket. Audit log can filter `doc_id='web'` to surface all web tool invocations.
- **D-11:** **Tavily `score` passes through to `final_score`.** `dense_score` / `sparse_score` / `rrf_score` / `rerank_score` stay at default `0.0`. `retrieval_method = "web"` so any future per-method analytics can branch. UI source-row `score=` field renders the Tavily score directly.
- **D-12:** **`content` = Tavily snippet verbatim only** (`result["content"]`). No title prefix, no URL append, no formatting wrapper. `metadata.title` carries the page title separately; `metadata.source` carries the URL. Faithfulness-eval semantics preserved: `content` is the citable evidence text, nothing else (P-05 from `.planning/research/PITFALLS.md` — RAGAS faithfulness will skip `chunk_type="web"` per that pitfall, but Phase 20 itself does not change RAGAS code).

### Tavily-failure UX surface

- **D-13:** **Three error kinds, three human-readable `content` strings** the planner LLM reads on the next turn:
  - `kind="tavily_disabled"` → *"Web search not configured. Answer from the knowledge base only."*
  - `kind="quota_exhausted"` → *"Web search quota exhausted today. Answer from the knowledge base only."*
  - `kind="web_search_failed"` → *"Web search temporarily unavailable. Answer from the knowledge base only."*
  All three error results carry `metadata={"error": True, "kind": <kind>, "latency_ms": <int>}` and `chunks=[]`. Planner reads the natural-language guidance and re-plans (typically picks `search_knowledge_base` on the next turn).
- **D-14:** **`is_error=True`** on every typed-failure `ToolResult`. Matches Phase 17 D-02 contract. Phase 18 SSE pipeline will emit `tool.span.error` (vs `tool.span.end`) automatically when `is_error=True` — the failure becomes visible in the SSE trace without bespoke wiring.
- **D-15:** **Redaction at source.** `_tavily_search` catches `httpx.HTTPStatusError` (or whatever exception type the Tavily SDK raises — verified in research phase) and converts ONLY status-code + exception class name into typed `ToolResult.metadata`. **Never propagate `exc.response.headers`, `exc.response.text`, or full traceback into `ToolResult` or logs** — Tavily 401/403 responses can echo the `Authorization` header in some proxy paths, and SSE Phase 18 serializes the entire `ToolResult.metadata` JSON. SC5 `tvly-` grep is a smoke test, not the line of defence; the line of defence is "don't put it in the result to begin with."
- **D-16:** **UI sources panel renders nothing for error rows.** When `is_error=True` and `chunks=[]`, no entry appears in `data.sources`; `static/ui.js` source loop iterates an empty list for the failed tool. The synthesizer's final answer text mentions degraded mode (drawn from D-13 `content`). No special-case render branch in `static/ui.js` beyond the `URL=<host>` change already scoped for non-error web chunks.

### Claude's Discretion

- **UI host extraction wording** — `URL=<host>` is the contract. Implementation in `static/ui.js`: `try { new URL(m.source).host } catch { '?' }` so malformed URLs don't crash the render. Final renderer text: ``` h += '...类型=' + (m.chunk_type || '?') + ' · ' + (m.chunk_type === 'web' ? 'URL=' + esc(hostOf(m.source)) : '页=' + (m.page_number ?? '?')) + ... ``` (or equivalent — planner picks the cleanest layout).
- **Tool description final wording** — D-02 specifies the steering intent; planner phase chooses exact prose, including any trailing `(Source: tavily-python search API)` clause.
- **Test file layout** — `tests/unit/test_web_search_tool.py` for unit (settings-disabled / 200 / 429 / 5xx → typed-error / mapping); `tests/integration/test_planner_picks_web_search.py` for D-04 fixtures. Planner picks names; v1.3 directory convention controls.
- **Pre-commit `tvly-` grep hook** — exact mechanism (a new pre-commit hook entry vs a `make` recipe vs a Phase 20 Wave-3 step) is a plan-time decision. SC5 only requires the absence; how that's enforced is implementation detail.
- **`requirements.txt` pin range** — `tavily-python>=0.7.24,<0.8` from research STACK.md. Planner can refine if 0.7.x has a known regression at plan-time.
- **Audit log fields for `web_search`** — reuse v1.3 audit fields (`tool_name`, `tenant_id`, `latency_ms`, `is_error`); no schema migration. Planner confirms.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 20 source artifacts

- `.planning/ROADMAP.md` Phase 20 — five Success Criteria (SC1–SC5) are the acceptance contract.
- `.planning/REQUIREMENTS.md` AGENT-10 / AGENT-11 / AGENT-12 / AGENT-13 — checkable requirement text (settings shape, error kinds, RetrievedChunk mapping, allowlist + integration test).
- `.planning/research/STACK.md` — Tavily SDK locked stack: `tavily-python>=0.7.24,<0.8`, `AsyncTavilyClient`, response shape `{query, results: [{title, url, content, score, raw_content, favicon}, ...], response_time}`, env-var convention.
- `.planning/research/PITFALLS.md` P-01 → P-06, P-16, P-17 — Tavily-impl pitfalls (key leak, sync-in-async, 5xx handling, 429 path, snippet vs faithfulness, UI render, env-var wiring, empty-key validator). P-18 (Redis cache flush ops checklist) applies to all v1.5 phases.
- `.planning/PROJECT.md` — Core value: every query returns a grounded, auditable answer.
- `.planning/STATE.md` — Carry-forward decisions table + Open Questions #1, #2, #6 (resolved by D-09…D-13).

### Code anchors (read before editing)

- `services/agent/tools/web_search.py` — current placeholder body (lines 1–60). `run()` body and `_WEB_SEARCH_PARAMETERS_SCHEMA` are Phase 20 surgery surface. `description` ClassVar replaced per D-02.
- `services/agent/tools/base.py` — `BaseTool` ABC (Phase 17 D-01) signature and ClassVar contract (`name`, `description`, `parameters_schema`).
- `services/agent/tools/registry.py` — `@registry.register` decorator semantics (Phase 17 D-09); `WebSearchTool` is already registered.
- `services/pipeline.py:598` — `AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search"]`. Phase 20 mutates to `["search_knowledge_base", "refine_search", "web_search"]`.
- `services/pipeline.py:617-665` — `_AGENT_SYSTEM` prompt. **Unchanged in Phase 20** per D-01.
- `services/pipeline.py:789` / `:862` / `:1089` — `registry.schemas_for(provider, names=AGENT_TOOL_ALLOWLIST)` callsites. Phase 20 doesn't edit these; they pick up the new allowlist value automatically.
- `utils/models.py:124-146` — `ChunkMetadata` shape; `chunk_type: str = "text"` accepts `"web"` without schema change. `source`, `title`, `page_number=None` populated per D-12.
- `utils/models.py:180-198` — `RetrievedChunk` shape; `final_score`, `retrieval_method` populated per D-11.
- `utils/models.py` — `ToolResult` (Phase 17 D-02): `content`, `chunks=[]`, `metadata={}`, `is_error=False`. Phase 20 sets `is_error=True` on failure per D-14.
- `services/agent/executor.py` — `Executor._dispatch_one` invokes `registry.get(tc.name).run(...)`; **unchanged**. Phase 18 latency-bound (`max(tool_latency)` not `sum`) preserved by registry indirection.
- `static/ui.js:28` — current source render: `' · 页=' + (m.page_number ?? '?') + ' · 类型=' + (m.chunk_type || '?') + ...`. Phase 20 inserts the `chunk_type === "web"` branch per D-16.
- `config/settings.py:271-275` — adjacent location for new tavily fields (D-06).
- `requirements.txt` — append `tavily-python>=0.7.24,<0.8` (D-15 Claude's discretion: pin reviewed at plan time).
- `.env.docker` — append `TAVILY_API_KEY=${TAVILY_API_KEY:-}` placeholder line (P-16 prevention).

### Precedent CONTEXT.md (read once for orientation)

- `.planning/milestones/v1.4-phases/17-tool-abstraction-retrievetool/17-CONTEXT.md` — D-01 (BaseTool ABC), D-02 (ToolResult shape), D-03 (ToolContext shape — NOT extended in Phase 20), D-09 (registry decorator), D-10 (placeholder behavior being replaced).
- `.planning/milestones/v1.4-phases/18-sse-planner-trace-event-stream/18-CONTEXT.md` — `tool.span.start` / `tool.span.end` / `tool.span.error` event semantics; `is_error=True` triggers `tool.span.error` per D-14.
- `.planning/milestones/v1.2-phases/11-provider-agnostic-agentic-layer-parallel-tool-call-burst/11-CONTEXT.md` — `BaseLLMClient.call_agentic_turn` provider-neutral surface; tenacity 3-attempt + exp-backoff baseline pattern.
- `.planning/milestones/v1.3-phases/13-llm-filter-fallback/13-CONTEXT.md` — mock-at-consumer-path pattern (locks D-04 and unit test mocking style).

### Codebase maps (read once for orientation)

- `.planning/codebase/ARCHITECTURE.md` — three-layer (`utils/` → `services/` → `controllers/`).
- `.planning/codebase/STRUCTURE.md` — file-tree directory of services and tools.
- `.planning/codebase/CONVENTIONS.md` — Pydantic V2 frozen, mypy --strict, ruff clean baseline.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`services/agent/tools/web_search.py` placeholder skeleton** (Phase 17) — `WebSearchTool` class is already registered, `parameters_schema` for `{query: string}` already exists, `BaseTool` subclass shape correct. Phase 20 only mutates the `run()` body, the `description` ClassVar text, and adds the `_tavily_search` helper + `get_tavily_client()` factory in the same module.
- **`config/settings.py::Settings`** — Pydantic V2 `BaseSettings` with `.env` chain already loads `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`. Adding `TAVILY_API_KEY` is mechanically identical (D-06).
- **Tenacity dependency + decorator pattern** — already in v1.0+ (`requirements.txt`); used across `services/generator/llm_client.py` for LLM calls. Phase 20 reuses the same `@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=10), reraise=True)` shape (D-08).
- **`utils/models.py::RetrievedChunk` + `ChunkMetadata`** — both accept `chunk_type="web"` and `page_number=None` without schema changes; v1.4.2 already made `page_number` `int | None`.
- **`Executor._dispatch_one` registry indirection** (Phase 17) — `web_search` will dispatch through the same code path as `search_knowledge_base`; no Executor change required.
- **`get_tool_registry` / `get_planner` / `get_executor` factory pattern** — Phase 20 adds `get_tavily_client` next to it (same lazy-init shape).
- **Pre-commit infrastructure** — repo already has pre-commit; adding a `tvly-` grep hook is a config-only addition (Claude's discretion).

### Established Patterns

- **Pydantic V2 frozen + `ConfigDict(frozen=True)`** — `ToolResult` already frozen (Phase 17). Construction in `WebSearchTool.run()` follows v1.4 D-02 contract.
- **Mock at consumer path, not source** (v1.3 Phase 13/15) — Phase 20 unit tests `monkeypatch.setattr("services.agent.tools.web_search.get_tavily_client", stub)` and `monkeypatch.setattr("services.agent.tools.web_search.settings", stub_settings)`, NOT `tavily.AsyncTavilyClient`.
- **Async-throughout, no sync clients in async pipeline** (v1.0+ pattern; P-02 from research) — `AsyncTavilyClient` only; never `TavilyClient`.
- **`BaseException` (not `Exception`)** for `asyncio.gather` isolation in Executor (Phase 11/12) — Phase 20 inherits without code change; tenacity-wrapped failures convert to `ToolResult` before escaping `run()` so isolation is moot.
- **`mypy --strict` + `ruff` clean** — Phase 20 must match v1.4 close baseline (296 errors = baseline; 0 new) for any file it touches.
- **`diff-cover ≥ 80%`** on all touched files — applies to `web_search.py`, `pipeline.py:598` allowlist edit, `config/settings.py` settings additions, `static/ui.js` render branch, `requirements.txt`, `.env.docker`, any new test files.

### Integration Points

- **`services/agent/tools/web_search.py`** — primary Phase 20 surgery surface (run() body + description + helper + factory). Touch is ≤ 200 lines including types.
- **`services/pipeline.py:598`** — `AGENT_TOOL_ALLOWLIST` literal addition. Touch ≤ 1 line.
- **`config/settings.py:~275`** — three new settings fields. Touch ≤ 5 lines.
- **`static/ui.js:28`** — single ternary branch added for `chunk_type === "web"`; backward-compat for PDF unchanged. Touch ≤ 6 lines.
- **`requirements.txt`** — append `tavily-python>=0.7.24,<0.8`. Touch 1 line.
- **`.env.docker`** — append `TAVILY_API_KEY=${TAVILY_API_KEY:-}` placeholder. Touch ≤ 3 lines (line + section header if needed).
- **`tests/unit/test_web_search_tool.py`** — NEW: settings-disabled / 200 / 429 / 5xx-then-success / 5xx-final-failure / mapping-to-RetrievedChunk / is_error=True / metadata.kind paths.
- **`tests/integration/test_planner_picks_web_search.py`** (or extension to existing planner integration tests) — NEW: SC3 two-fixture assertion (D-04).
- **`tests/unit/test_ui_render.py`** OR static-html smoke fixture — NEW: SC4 chunk_type=="web" → URL=<host>; chunk_type=="text" → 页=<n> unchanged.
- **Pre-commit hook config** — NEW: `tvly-` regex grep entry blocking commits that contain a Tavily key.
- **Audit log** — `tool_name="web_search"` rows added on each call; reuses existing v1.3 fields (tenant_id, latency_ms, is_error). No DB migration.

</code_context>

<specifics>
## Specific Ideas

- **Steering inside the tool descriptor** — D-02's "real-time/external bias" wording is the user's chosen mechanism. The user explicitly rejected updating `_AGENT_SYSTEM` to preserve v1.3/v1.4 prompt-parity fixtures. This is a non-trivial constraint: any future request to "make the agent prefer KB" must update the tool description, NOT the system prompt.
- **No ToolContext schema expansion** (D-07) — The user chose module-level `settings` import over `ToolContext.settings` injection. This locks Phase 17 D-03's `ToolContext(req, tf, retriever, llm)` shape across v1.5; future tools that need settings follow the same module-level pattern.
- **`web_search` always allowlisted** (D-03) — The user explicitly rejected startup-time filtering on `tavily_api_key` presence. This means the `tavily_disabled` ToolResult IS observable behavior in the audit log — not a fallback nobody sees. Phase 22 coverage tests for `WebSearchTool.run()` MUST cover this branch.
- **Source-side redaction over SSE-side filter** (D-15) — The user chose "don't put it in the result to begin with" over defence-in-depth. SC5 `tvly-` grep is a smoke test only; the actual redaction lives in `_tavily_search`'s exception handling. Implementation must treat the Tavily SDK's exception types as untrusted (do not assume `exc.response` is safe to serialize).
- **UI sources panel = empty rows for failed web_search** (D-16) — The synthesizer's final answer prose is the only UI-visible signal of a degraded-mode response. Phase 20 does NOT introduce an "error placeholder source row" or new SSE field. Future UX evolution (banner, toast) is v1.6+.

</specifics>

<deferred>
## Deferred Ideas

### To Phase 21 (AGENT-05 Multi-Agent Debate / Sub-Agent Verifier)

- **Verifier system-prompt language matching** (P-11 from research) — verifier writes `final_answer` in user query language; orthogonal to Phase 20.
- **Per-tool retry/timeout config on `BaseTool`** — uniform infrastructure (`retry: ClassVar[RetryPolicy]`); deferred per Phase 17 deferred list. Phase 20 hard-codes the tenacity decorator on `_tavily_search`. Revisit when ≥ 3 real tools (web_search + verifier-helper + future SQLTool) need divergent retry policies.

### To Phase 22 (Per-Module 70% Coverage Lift)

- TEST-08 `services/pipeline.py` coverage — must include `AGENT_TOOL_ALLOWLIST` containing `web_search` (Phase 20's edit) in the new allowlist-coverage tests.
- New tests for `services/agent/tools/web_search.py` — Phase 20 ships unit tests for the real impl; Phase 22 may add module-level coverage assertions if `web_search.py` is added to the per-module 70% list (currently only the 5 modules in TEST-08..12 are tracked; web_search.py is small enough to hit ≥ 70% with Phase 20 unit tests alone).

### To v1.6+

- **Tavily Extract / Crawl / Map endpoints** — beyond `search`; not requested in v1.5 (REQUIREMENTS.md "Out of Scope").
- **Per-tenant Tavily quota / domain allowlist / budget cap** — explicitly out of scope per REQUIREMENTS.md.
- **Generic web-search abstraction layer** (SerpAPI / Brave / Tavily switching) — deferred until a second provider is requested.
- **Iterative planner-loop over `kind="quota_exhausted"` to bypass quota** — D-13 ships natural-language guidance only; iterative quota-bypass strategies (cache, fallback to public scrape, etc.) not in scope.
- **RAGAS faithfulness over web chunks via Tavily Extract** (P-05 from research) — defer; v1.5 skips faithfulness on `chunk_type="web"`.
- **Pre-deploy Redis cache flush** (P-18) — ops checklist line, not Phase 20 code change.
- **UI banner / toast for degraded-mode answers** — D-16 keeps the surface minimal; richer UX awaits a frontend phase.
- **`MultiQueryRetrieveTool` exposing `services/retriever/retriever.py:549::retrieve_multi_query`** — Phase 17 deferred; still deferred.
- **Collapse `search_knowledge_base` + `refine_search` into a single RetrieveTool** — Phase 17 deferred; still deferred.

</deferred>

---

*Phase: 20-websearchtool-real-implementation-tavily*
*Context gathered: 2026-05-10*
