# FEATURES — v1.5 Web Search + Multi-Agent Debate + Coverage Lift

*Generated 2026-05-10 inline. Supersedes prior milestone research.*

## v1.5 feature decomposition by category

### Category 1 — Web Search Tool

**Table stakes (must ship in v1.5):**

| Feature | Notes |
|---|---|
| WebSearchTool real impl backed by Tavily SDK | Async; subclasses v1.4 `BaseTool`; tool name stays `web_search` (already registered in v1.4) |
| `AGENT_TOOL_ALLOWLIST` includes `web_search` | Planner can pick it; v1.4 had it excluded |
| Tavily error → `ToolResult(metadata={"error": True})` | Tenacity 3-attempt exponential backoff; final failure returns error result, never raises into orchestrator |
| Result → `RetrievedChunk` shape conversion | Tavily `{title,url,content,score}` maps to existing `RetrievedChunk` so source rendering works without UI changes; `metadata.source = url`, `metadata.title = title`, `chunk_type = "web"`, `page_number = None` |
| Settings additions: `tavily_api_key`, `tavily_search_depth`, `tavily_max_results` | Pydantic Settings; key empty-string default → tool returns "WebSearch disabled" if unset |

**Differentiators (nice-to-have, may defer):**

| Feature | Defer reason |
|---|---|
| Domain include/exclude allowlist per tenant | Not requested; defer until enterprise asks |
| Credit-counter / budget cap per tenant | v1.5 punts; rely on Tavily account-level quota |
| Cache web search results in Redis | Tavily basic depth has fresh-content premium; caching defeats freshness |

### Category 2 — Multi-Agent Debate / Sub-Agent Verify (AGENT-05)

**Table stakes:**

| Feature | Notes |
|---|---|
| Verifier role pattern (recommended in STATE Open Q #3) | One extra sub-agent reads N peer answers + chunk evidence, returns either "consensus answer" or "flag disagreement"; lower latency than peer-debate-N-rounds |
| Opt-in flag `debate=true` on `GenerationRequest` | Off by default; user opts in for high-stakes queries; same `/api/v1/agent/v1/run/stream` endpoint |
| Reuses v1.3 `SwarmQueryPipeline` parallel sub-agents — verifier hops onto end | No new pipeline class; new method `SwarmQueryPipeline.run_with_verifier()` or extra step inside existing run |
| New SSE event types: `verifier.start`, `verifier.complete`, `verifier.disagreement` | Extends v1.4 schema in `docs/agent-architecture.md`; backward-compatible |
| Verifier prompt template | Includes peer answer texts + source chunks; outputs JSON `{verdict: agree\|disagree, final_answer, dissenting_peers}` |

**Differentiators:**

| Feature | Defer reason |
|---|---|
| Iterative peer debate (N rounds critique) | Latency cost N×; v1.5 picks single-pass verifier; iterative debate becomes v1.6+ if v1.5 verifier proves valuable |
| Per-tenant debate config | Premature config surface |
| Disagreement persistence to audit log | Already covered by audit log path; no new schema needed |

### Category 3 — Per-Module Coverage Lift

**Table stakes:**

| Module | Current coverage (approx) | Target | Test strategy |
|---|---|---|---|
| `services/pipeline.py` | 60–65% | ≥70% | Mock at consumer paths (`services.pipeline.get_planner` etc.); cover error branches in `run_streaming`; Phase 13/15 pattern |
| `services/generator/llm_client.py` | 55–60% | ≥70% | Use v1.2 wire fixtures; cover RateLimit/Overloaded/RetryError branches; `call_agentic_turn` happy + 429 + 5xx paths per provider |
| `services/vectorizer/vector_store.py` | 60–65% | ≥70% | Cover `_build_filter_where` table-driven; metadata `isinstance str` JSONB branch; HNSW index DDL idempotency |
| `services/retriever/retriever.py` | 60–65% | ≥70% | `_to_retrieved_chunk` model_validate branch (v1.4.2 fix); rerank SLA breach fallback; parent_expand error tolerance |
| `services/extractor/extractor.py` | 55–60% | ≥70% | OCR vs text-extract branch; header/footer detection; `is_scanned_pdf` sample heuristic |

**Constraint:** v1.3 D-04 — no production-code changes for coverage; tests only.

## Cross-feature dependencies

- WebSearchTool depends on no other v1.5 feature (independent)
- AGENT-05 debate depends on existing v1.4 SSE infrastructure (already shipped) — no v1.5 cross-deps
- Coverage lift independent (testing only)

## What's explicitly NOT in v1.5

- Memory tool (10x #1) → v1.6 after `/office-hours`
- Code-acting / SQLTool (10x #4) → v1.6+ after sandbox decision
- UI-03 React/Vue migration → v1.6+
- TEST-07 mutation testing → v1.6+
- UI-02 first-deploy browser smoke → first deploy
