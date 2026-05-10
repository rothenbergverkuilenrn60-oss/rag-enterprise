# Phase 20: WebSearchTool Real Implementation (Tavily) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-10
**Phase:** 20-websearchtool-real-implementation-tavily
**Areas discussed:** Planner trigger policy, Tavily client lifecycle + Settings flow, Web chunk identity (chunk_id / doc_id), Tavily-failure UX surface

---

## Planner trigger policy

### Q1: Selection mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Description-driven | Planner LLM picks freely based on each tool's `description` field. Simple, no `_AGENT_SYSTEM` prompt change. Trusts LLM tool selection — same shape as v1.4 planner. | ✓ |
| KB-first via prompt guidance | Update `_AGENT_SYSTEM` to instruct: 'Try search_knowledge_base first. Use web_search only if KB returns insufficient evidence or query is clearly about real-time/external info.' | |
| KB-first via gated allowlist | Hide `web_search` from planner schemas on first turn; expose it on subsequent turns only after a KB tool call returned <N chunks. | |

### Q2: Tool description wording

| Option | Description | Selected |
|--------|-------------|----------|
| Real-time/external bias | Description states: 'Search the public web for current/real-time information, news, or topics not in the internal knowledge base. Prefer search_knowledge_base for indexed corpus questions.' | ✓ |
| Neutral capability statement | Description only says 'Search the public web for current information.' | |
| Hard fallback wording | 'Use ONLY when search_knowledge_base returns insufficient evidence after 1+ attempts.' | |

### Q3: Phase 20 SC3 integration test shape

| Option | Description | Selected |
|--------|-------------|----------|
| Two recorded fixtures | Two real planner calls (mocked LLM client returning canned tool_use): weather query → web_search; GB-standard query → search_knowledge_base. | ✓ |
| Single fixture + parametrize | One test parametrized with (query, expected_tool_name). | |
| Live LLM call (network) | Hit the actual OpenAI/Anthropic API for the queries. | |

### Q4: Empty-key allowlist policy

| Option | Description | Selected |
|--------|-------------|----------|
| Always allowlisted, returns tavily_disabled | `web_search` always in allowlist. If planner picks it without a key, run() returns ToolResult kind="tavily_disabled". | ✓ |
| Filtered when key missing | AgentQueryPipeline computes `_effective_allowlist` at startup. | |
| Hard-fail at startup | App refuses to boot if TAVILY_API_KEY missing. | |

**Notes:** User chose to keep `_AGENT_SYSTEM` prompt unchanged so v1.3/v1.4 parity fixtures don't need re-baselining; steering moves into the tool description text instead.

---

## Tavily client lifecycle + Settings flow

### Q1: AsyncTavilyClient instantiation

| Option | Description | Selected |
|--------|-------------|----------|
| Module-level lazy singleton | `get_tavily_client()` factory in `services/agent/tools/web_search.py` — first call constructs, subsequent reuse. httpx connection pool reused. | ✓ |
| Per-call instantiation | Create new `AsyncTavilyClient` inside every `run()`. | |
| Class attribute on WebSearchTool | `_client: ClassVar[AsyncTavilyClient \| None] = None` populated lazily inside `run()`. | |

### Q2: Settings location

| Option | Description | Selected |
|--------|-------------|----------|
| Existing config/settings.py Settings class | Add three fields next to `openai_api_key`/`anthropic_api_key`. Single source of truth; matches v1.0+ pattern. | ✓ |
| Dedicated TavilySettings sub-model | New `TavilySettings(BaseSettings)` class with `env_prefix='TAVILY_'`. | |
| Tool-local config dict | Hardcode defaults; read `os.environ['TAVILY_API_KEY']` directly. | |

### Q3: Settings access pattern in run()

| Option | Description | Selected |
|--------|-------------|----------|
| Module-level `settings = get_settings()` import | Read inside `run()`. Matches v1.0+ pattern. No ToolContext schema change. | ✓ |
| Read from ToolContext | Add `settings: Settings` field to `ToolContext`; reads `ctx.settings.tavily_api_key`. | |
| Tenacity decorator reads at call-time | Late-bind by reading inside the retried function. | |

### Q4: Tenacity retry placement

| Option | Description | Selected |
|--------|-------------|----------|
| Inner private async helper | `@retry(...)` on a private `async def _tavily_search(query) -> dict` that wraps `await client.search(...)`. | ✓ |
| Decorate run() itself | `@retry` on `WebSearchTool.run`. | |
| Manual loop inside run() | Write the 3-attempt + exp-backoff loop by hand. | |

**Notes:** User explicitly preserved Phase 17 D-03's `ToolContext(req, tf, retriever, llm)` shape — no new field added. Future tools needing settings follow the same module-level pattern.

---

## Web chunk identity (chunk_id / doc_id)

### Q1: chunk_id shape

| Option | Description | Selected |
|--------|-------------|----------|
| `web:<sha1(url)[:16]>` | Stable, dedup-friendly, fixed-length (20 chars). | ✓ |
| Use the raw URL as chunk_id | Simple; URL is unique. But unbounded length in audit log / SSE / index keys. | |
| `web:<position>:<query_hash>` | Encodes result position + query. Loses dedup across queries. | |

### Q2: doc_id value

| Option | Description | Selected |
|--------|-------------|----------|
| `doc_id="web"` constant | All web results share `doc_id="web"`. Audit log can filter `doc_id='web'`. | ✓ |
| `doc_id=url` | Each unique URL is its own doc. | |
| `doc_id=f"web:{host}"` | Group by host. | |

### Q3: final_score handling

| Option | Description | Selected |
|--------|-------------|----------|
| Pass through Tavily `score` to `final_score` | UI already renders `score=` field. `retrieval_method="web"` so downstream can branch. | ✓ |
| Leave all scores 0.0 | Avoid conflating Tavily score semantics with RRF/rerank. | |
| Compute a synthetic score from result position | `final_score = 1.0 - (position / max_results)`. | |

### Q4: content field shape

| Option | Description | Selected |
|--------|-------------|----------|
| Snippet only | `content = result['content']` verbatim. Title in `metadata.title` separately. | ✓ |
| Title + newline + snippet | `content = f"{title}\n\n{snippet}"`. | |
| Snippet + appended URL | `content = f"{snippet}\n\nSource: {url}"`. | |

**Notes:** Snippet-only matches v1.0 PDF chunk semantics — `content` is the citable evidence text and nothing else; faithfulness eval boundaries preserved.

---

## Tavily-failure UX surface

### Q1: Error content for LLM

| Option | Description | Selected |
|--------|-------------|----------|
| Human-readable message per kind | `web_search_failed`/`quota_exhausted`/`tavily_disabled` each get a short natural-language `content` string. Planner re-plans on next turn. | ✓ |
| Empty content + metadata.error only | `content=""`, `metadata={"error": True, "kind": ...}`. | |
| JSON-encoded error blob in content | `content='{"error":"web_search_failed","message":"..."}'`. | |

### Q2: is_error flag

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, is_error=True + chunks=[] | Matches v1.4 ToolResult D-02 contract. Phase 18 SSE `tool.span.error` event triggered. | ✓ |
| is_error=False, signal only via metadata.kind | Phase 18 `tool.span.error` event won't fire — silent in SSE trace. | |
| Distinguish by kind | is_error=True only for `web_search_failed`/`quota_exhausted`; False for `tavily_disabled`. | |

### Q3: Redaction location

| Option | Description | Selected |
|--------|-------------|----------|
| Catch httpx.HTTPStatusError in _tavily_search; never propagate response.headers/body | Inside the retry wrapper, on exception convert ONLY the status code + exception type into typed ToolResult. | ✓ |
| Add a global SSE redaction filter | In Phase 18 SSE serialization layer, regex-strip `tvly-` prefix from emitted JSON. | |
| Both — source-side prevention + SSE filter | Defence-in-depth. | |

### Q4: UI rendering on web_search error

| Option | Description | Selected |
|--------|-------------|----------|
| Nothing — error chunks not in sources | `chunks=[]` means no row in `sources` array. UI source list shows only KB hits. Synthesizer's final answer mentions degraded mode. | ✓ |
| Render an error placeholder source row | UI renders one entry like 'web search unavailable'. | |
| Send error in a separate SSE field | New `errors[]` field in /api/v1/query response. | |

**Notes:** SC5 `tvly-` grep is treated as a smoke test. Real defence is at the Tavily exception-handling boundary inside `_tavily_search` — never serialize `exc.response.headers` or full traceback into `ToolResult` or logs.

---

## Claude's Discretion

- **UI host extraction implementation** — `URL=<host>` contract is locked; exact JS code (e.g., `try { new URL(m.source).host } catch { '?' }`) is plan-time discretion.
- **Tool description final prose** — D-02 specifies the steering intent (real-time / external bias); planner picks the exact wording, including any trailing source attribution clause.
- **Test file layout / naming** — `tests/unit/test_web_search_tool.py` and `tests/integration/test_planner_picks_web_search.py` are recommended; planner can rename per v1.3 directory conventions.
- **Pre-commit `tvly-` grep mechanism** — exact hook (pre-commit YAML entry vs `make` recipe) is plan-time discretion.
- **`requirements.txt` pin range** — `tavily-python>=0.7.24,<0.8` from research; planner refines if a 0.7.x regression surfaces at plan-time.
- **Audit log fields** — reuse v1.3 audit fields (no schema migration); planner confirms.

## Deferred Ideas

### To Phase 21
- Verifier system-prompt language matching (P-11) — orthogonal.
- Per-tool retry/timeout policy on `BaseTool` ABC — revisit when ≥ 3 real tools need divergent policies.

### To Phase 22
- Allowlist coverage in TEST-08 must include the new `web_search` entry.
- `services/agent/tools/web_search.py` may be added to per-module 70% list if Phase 20 unit tests don't already deliver it.

### To v1.6+
- Tavily Extract / Crawl / Map endpoints (out of scope per REQUIREMENTS.md).
- Per-tenant Tavily quota / domain allowlist / budget cap (out of scope).
- Generic web-search abstraction layer (SerpAPI / Brave / Tavily switching).
- Iterative quota-bypass strategy on `quota_exhausted`.
- RAGAS faithfulness over web chunks via Tavily Extract (P-05).
- Pre-deploy Redis cache flush ops checklist line (P-18).
- UI banner / toast for degraded-mode answers.
- `MultiQueryRetrieveTool` exposing `retrieve_multi_query`.
- Collapse `search_knowledge_base` + `refine_search` into a single RetrieveTool.
