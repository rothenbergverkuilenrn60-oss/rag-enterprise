# PITFALLS — v1.5 Web Search + Multi-Agent Debate + Coverage Lift

*Generated 2026-05-10 inline. Common mistakes when ADDING these features to existing system.*

## WebSearchTool real impl pitfalls

### P-01: Leaking Tavily API key into git / logs / SSE

**Mistake:** Hardcode key in `.env.docker` (committed) or echo it in logs / SSE error events.
**Prevention:**
- Key lives ONLY in `.env` (gitignored); `.env.docker` uses `TAVILY_API_KEY=${TAVILY_API_KEY:-}` substitution
- Settings reads `os.environ["TAVILY_API_KEY"]`; never logs the value
- Tavily error path returns generic message, not the raw `httpx.Response.headers` (which may echo auth)
- Pre-commit hook scans for `tvly-` prefix matches
**Phase:** WebSearch impl (Phase 20)

### P-02: Sync `TavilyClient` in async pipeline = thread blocking

**Mistake:** Use `TavilyClient(...).search(...)` (sync) inside `async def run(...)`. Blocks event loop, kills concurrency.
**Prevention:** Always `AsyncTavilyClient(...)` + `await client.search(...)`.
**Phase:** WebSearch impl

### P-03: Tavily 5xx / timeout = unhandled `httpx.HTTPError` propagating into orchestrator

**Mistake:** Let exception escape `WebSearchTool.run()`. v1.4 `Executor` wraps with `BaseException` isolation, but error trace pollutes audit log.
**Prevention:** Tenacity `@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=10), reraise=True)` decorator on the search call; final-attempt failure → `_build_error_result(exc)` returning `ToolResult(metadata={"error": True, "kind": "web_search_failed"})`.
**Phase:** WebSearch impl

### P-04: Tavily quota exhausted mid-day → silent failures

**Mistake:** Tavily returns 429 → user gets cryptic "Internal server error".
**Prevention:** Map Tavily 429 to a specific error result with `metadata={"error": True, "kind": "quota_exhausted"}`; orchestrator surfaces to LLM in next turn so synthesizer can degrade gracefully ("web search unavailable, answering from knowledge base only").
**Phase:** WebSearch impl

### P-05: Tavily snippet ≠ full document → faithfulness eval breaks

**Mistake:** RAGAS faithfulness check assumes citations have full retrievable content. Tavily `content` is a snippet.
**Prevention:** Don't run RAGAS faithfulness over web_search chunks; tag `chunk_type="web"` and skip them in faithfulness scoring; OR run faithfulness only when source contains `[来源N]` referring to web_search by fetching full content via Tavily Extract API (defer; not v1.5 scope).
**Phase:** WebSearch impl

### P-06: Web sources rendered with `页=?` confuses users

**Mistake:** v1.4.2 fix made `页=` show real numbers; web sources have no page → still shows `?`.
**Prevention:** Frontend `static/ui.js` change: when `chunk_type === "web"`, render `URL=<host>` instead of `页=?`. Backward-compatible (existing PDF chunks unchanged).
**Phase:** WebSearch impl (small UI follow-up)

## AGENT-05 verifier pitfalls

### P-07: Verifier sees both peer answers AND chunks → can hallucinate "verified" content not in evidence

**Mistake:** Verifier prompt encourages composing from peer answers (text), bypassing chunk evidence check.
**Prevention:** Verifier system prompt explicitly forbids inventing facts not in chunks; verifier output JSON requires `evidence_chunk_ids: list[str]` per claim; if verdict is `agree` but `evidence_chunk_ids == []`, treat as disagreement.
**Phase:** AGENT-05 (Phase 21)

### P-08: Verifier latency × N peer answers blows iteration budget

**Mistake:** Run verifier per peer answer in series → swarm latency = sum(peer) + N × verifier.
**Prevention:** Single verifier call sees ALL N peer answers + all evidence in one prompt; latency = max(peer) + 1 × verifier. Per v1.4 Phase 18 latency invariant ("max not sum").
**Phase:** AGENT-05

### P-09: Verifier disagreement = always re-synthesize → infinite loop risk

**Mistake:** On disagreement, kick another planner-loop → planner asks more tools → more peers → more disagreement → cap blown.
**Prevention:** Verifier runs ONCE per swarm. If disagreement, synthesizer composes a "answers diverge: peer 1 says X, peer 3 says Y, evidence supports peer 3" final response. No re-planning loop. v1.6+ may add iterative debate.
**Phase:** AGENT-05

### P-10: AGENT-05 SSE events break existing frontend EventSource handlers

**Mistake:** Add new event types without backward-compat shim → frontend ignores them silently.
**Prevention:** New events `verifier.start/complete/disagreement` are additive; existing `synthesizer.final` still emits last; EventSource `addEventListener('synthesizer.final', ...)` remains the terminal. Document new events as "optional, debate-mode-only".
**Phase:** AGENT-05

### P-11: Verifier prompt template baked in English → mismatched language with user query

**Mistake:** Hardcode `"You are a verifier..."` in English; user query is Chinese; verdict mixes languages.
**Prevention:** Mirror v1.4 planner system prompt convention — instruct LLM to write `final_answer` in user query language; verifier system prompt itself can be Chinese for this project.
**Phase:** AGENT-05

## Coverage lift pitfalls

### P-12: Mock-at-source pattern leaks into v1.5 tests

**Mistake:** `@patch("services.retriever.retriever._retrieve_impl")` (mock-at-source) — tests don't actually exercise real module code.
**Prevention:** Mock at consumer path: `@patch("services.pipeline.get_retriever")`. v1.3 Phase 13 / Phase 15 lock this; v1.5 inherits.
**Phase:** Coverage lift (Phase 22)

### P-13: Coverage lift forces production-code changes (e.g., adding `if TYPE_CHECKING`)

**Mistake:** Module has untestable static block (e.g., `_engine = create_engine(...)` at module top); to test it, refactor to lazy init → production change.
**Prevention:** v1.3 D-04 prohibits this. Accept untestable static-import lines; cover the function bodies. If <70% achievable on a module without prod changes, document as accepted in phase SUMMARY.
**Phase:** Coverage lift

### P-14: pytest-asyncio fixture scope clash → flaky tests

**Mistake:** Mix `scope="module"` and `scope="function"` event_loop fixtures → "Event loop is closed" intermittent.
**Prevention:** Project uses `asyncio_mode = "auto"` in pytest.ini; do NOT redeclare event_loop fixture in v1.5 test files; use `@pytest_asyncio.fixture` for fixture-yielding async setup.
**Phase:** Coverage lift

### P-15: Heavy-mock test files give false 70% reading

**Mistake:** Mock everything → coverage line counters tick up but logic isn't actually exercised; mutations would survive.
**Prevention:** Each new test file include ≥ 1 happy-path test that exercises a real branch end-to-end with only external boundaries mocked. v1.3 Phase 13 pattern.
**Phase:** Coverage lift

## Cross-cutting pitfalls

### P-16: New env var added but Docker compose forgets to pass it

**Mistake:** `requirements.txt` adds `tavily-python`, code reads `os.environ["TAVILY_API_KEY"]`, but `.env.docker` and compose `environment:` block don't reference it → settings load with empty key → silent feature-off.
**Prevention:** Single source of truth — settings reads via Pydantic Settings + `.env` chain; compose `env_file: .env.docker` already loads everything; just ensure `.env.docker` has the placeholder line.
**Phase:** WebSearch impl

### P-17: Settings validator missing → empty key passes silently

**Mistake:** `tavily_api_key: str = ""` allows empty; tool runs and gets 401; user thinks system is broken.
**Prevention:** WebSearchTool.run() first checks `if not settings.tavily_api_key: return ToolResult(metadata={"error": True, "kind": "tavily_disabled", "message": "TAVILY_API_KEY not configured"})`. Clear error path; tool degrades gracefully when unconfigured.
**Phase:** WebSearch impl

### P-18: Forgetting to clear Redis query cache after pipeline change

**Mistake:** v1.4.2 lesson — after rebuilding, old cached responses still served stale data.
**Prevention:** Each phase SUMMARY includes a "ops checklist" line: `redis-cli --scan --pattern 'rag:query:*' | xargs redis-cli del` if pipeline behavior changed.
**Phase:** All v1.5 phases

## Watch list (by phase)

| Phase | Top-3 pitfalls to call out in DISCUSSION-LOG |
|---|---|
| Phase 20 (WebSearch) | P-01 (key handling), P-03 (error path), P-06 (UI render) |
| Phase 21 (AGENT-05) | P-07 (verifier hallucination), P-09 (no infinite loop), P-10 (SSE backward-compat) |
| Phase 22 (Coverage lift) | P-12 (mock pattern), P-13 (no prod changes), P-15 (real branches) |
