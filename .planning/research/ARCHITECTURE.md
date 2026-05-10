# ARCHITECTURE — v1.5 integration with v1.4 agent runtime

*Generated 2026-05-10 inline. Supersedes prior milestone research.*

## Existing architecture (v1.4 close)

```
HTTP Request
    │
    ▼
controllers/api.py
    ├─ POST /api/v1/query?agent_mode=true   → AgentQueryPipeline.run() (non-stream)
    ├─ POST /api/v1/agent/v1/run/stream     → AgentQueryPipeline.run_streaming() (SSE)
    └─ POST /api/v1/query?swarm_mode=true   → SwarmQueryPipeline.run() (parallel sub-agents)
                       │
                       ▼
              services/pipeline.py
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
   Planner         Executor       Synthesizer (= LLM terminal turn)
       │               │
       ▼               ▼
  call_agentic   ToolRegistry
   _turn          .get(name).run()
                       │
                       ▼
                  BaseTool subclass
                  (RetrieveTool, RefinedRetrieveTool, WebSearchTool[placeholder])
```

## v1.5 architectural changes

### Change 1 — WebSearchTool real impl (Phase 20 candidate)

**Touch points:**
- `services/agent/tools/web_search.py` — replace placeholder `run()` body with `AsyncTavilyClient.search()` call
- `services/pipeline.py:598` — add `"web_search"` to `AGENT_TOOL_ALLOWLIST`
- `utils/config.py` — add Tavily settings fields
- `requirements.txt` — pin `tavily-python>=0.7.24,<0.8`
- `services/agent/tools/web_search.py` — convert Tavily response → `RetrievedChunk` list inside `ToolResult.chunks`
- `services/generator/generator.py` — UI source rendering already reads `metadata.source` / `metadata.title` so web sources render with no UI change

**No changes needed in:**
- `Planner` — will pick `web_search` tool from registry once allowlist permits
- `Executor` — already dispatches via `ToolRegistry`; no tool-specific code
- SSE event schema — `tool.span.start/end/error` already covers web_search
- Frontend `static/ui.js` — already iterates `sources[]` reading `metadata.page_number ?? "?"`; web sources will show `页=?` because there is no page (acceptable; page-not-applicable for web)

**Data flow:**
```
Planner picks "web_search" → Executor dispatches → WebSearchTool.run(args={"query": ..., "max_results": ...})
  → AsyncTavilyClient.search(...) → Tavily REST → response dict
  → for r in response["results"]: build RetrievedChunk(metadata=ChunkMetadata(source=r["url"], title=r["title"], chunk_type="web", page_number=None), content=r["content"])
  → ToolResult(content=formatted_text, chunks=chunks, metadata={"latency_ms", "query", "tavily_response_time"})
```

### Change 2 — AGENT-05 verifier role (Phase 21 candidate)

**Touch points:**
- `services/pipeline.py::SwarmQueryPipeline` — add `run_with_verifier()` method OR add verifier hop inside existing `run()` gated by `req.debate`
- `utils/models.py::GenerationRequest` — add `debate: bool = False` field
- `utils/models.py` — add `VerifierStartEvent`, `VerifierCompleteEvent`, `VerifierDisagreementEvent` (extend AgentEvent ABC)
- `services/agent/verifier.py` (new) — `Verifier` class with `verify(peer_answers: list[SubAgentAnswer], evidence: list[RetrievedChunk]) → VerifierVerdict`
- `controllers/api.py::agent_run_stream` — yield new event types (no change to event-frame format)
- `docs/agent-architecture.md` — extend Event Schema Reference with 3 new event types

**Verifier sub-agent design:**
```
SwarmQueryPipeline (existing v1.3):
   coordinator → decompose → N sub-agents → asyncio.gather → synthesizer → answer
                                                                     │
                                                                     ▼ (v1.5 if req.debate=True)
                                                              Verifier.verify(peer_answers, evidence)
                                                                     │
                                                                     ▼
                                                           VerifierVerdict(consensus / disagreement)
                                                                     │
                                                                     ▼
                                                              Final synthesizer call (revised)
```

The verifier is itself a `BaseLLMClient.call_agentic_turn` invocation — single-shot text-only (no tools). It reads each peer's answer + the chunks they cited, and returns a JSON verdict. If `verdict == "disagree"`, the verifier specifies which peers and why; the synthesizer then re-composes with the disagreement context surfaced.

**Why not a new tool:** The verifier reads peer answers, not external sources. Modeling it as a `Tool` would force it through the planner — wrong layer. It's a post-fan-out pipeline stage, like Synthesizer.

### Change 3 — Coverage lift on 5 modules (Phase 22 candidate)

**Touch points:**
- `tests/unit/test_pipeline_coverage.py` (new or extend existing)
- `tests/unit/test_llm_client_coverage.py` (extend with provider error branches)
- `tests/unit/test_vector_store_coverage.py` (filter where + JSONB branches)
- `tests/unit/test_retriever_coverage.py` (rerank SLA + parent_expand)
- `tests/unit/test_extractor_coverage.py` (OCR vs native + header/footer)
- **NO production code changes** (v1.3 D-04 lock)

**Pattern (from v1.3 Phase 13/15):** Mock at consumer-path (`services.pipeline.get_X`), exercise real module code, only stub external boundaries.

## Data flow integrity

All v1.4 invariants preserved:
- PostgreSQL RLS isolates tenants on every tool call (web_search has no DB access; AGENT-05 verifier reuses same pool)
- Audit log carries trace_id + tenant_id + tool_name; web_search and verifier add new tool_name values, schema unchanged
- JWT/auth middleware applies to new endpoints (none added — debate piggybacks on existing routes)
- Combined coverage `--fail-under=70` global floor + per-module 70% on the 5 lifted modules

## Suggested build order (informs roadmap)

1. **WebSearchTool real impl** — independent, smallest, highest leverage; ship first to validate Tavily integration end-to-end
2. **AGENT-05 verifier** — depends on v1.4 SwarmQueryPipeline being available (it is); ship second
3. **Coverage lift** — independent of feature work; can run in parallel with #2 in dev, but bench separately to keep PR scope clean

Phase numbering continues from 19: **Phase 20** = WebSearch, **Phase 21** = AGENT-05 verifier, **Phase 22** = Coverage lift.
