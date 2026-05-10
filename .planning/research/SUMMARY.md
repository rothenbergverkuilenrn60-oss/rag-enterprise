# SUMMARY — v1.5 Research Synthesis

*Generated 2026-05-10 inline. Synthesizes STACK.md / FEATURES.md / ARCHITECTURE.md / PITFALLS.md.*

## Stack additions

- **`tavily-python>=0.7.24,<0.8`** — only new dependency; `AsyncTavilyClient` plugs into existing async pipeline; SDK handles auth, retry, JSON parsing
- **No new packages** for AGENT-05 verifier (reuses v1.2 `BaseLLMClient.call_agentic_turn`) or coverage lift (existing pytest stack)
- **Settings additions:** `tavily_api_key`, `tavily_search_depth="basic"`, `tavily_max_results=5`
- **Env var routing:** `.env` (gitignored, real key) → `.env.docker` (`${TAVILY_API_KEY:-}` placeholder) → compose `env_file` → container → Pydantic Settings

## Feature table stakes (must ship)

1. **WebSearchTool real impl** — Tavily-backed, replaces v1.4 placeholder, joins `AGENT_TOOL_ALLOWLIST`; Tavily results convert to `RetrievedChunk` shape so existing source rendering works
2. **AGENT-05 verifier role** — single-pass verifier sub-agent reads N peer answers + evidence chunks, returns consensus or disagreement; `req.debate=True` opt-in flag; SSE adds `verifier.start/complete/disagreement` events
3. **Per-module 70% coverage** on `pipeline.py`, `llm_client.py`, `vector_store.py`, `retriever.py`, `extractor.py` — no production code changes (v1.3 D-04 lock)

## Differentiators (defer to v1.6+)

- Per-tenant Tavily domain allowlist + budget cap
- Iterative peer debate (multi-round critique) — v1.5 ships single-pass verifier first
- Web result caching in Redis (defeats freshness)
- Memory tool (10x #1) — needs `/office-hours` to lock wedge
- Code-acting / SQLTool (10x #4) — sandbox unresolved

## Architecture integration points

| New artifact | Touches | New? |
|---|---|---|
| `services/agent/tools/web_search.py::WebSearchTool.run()` body | Tavily SDK call + `RetrievedChunk` mapping | Replaces existing placeholder |
| `services/pipeline.py::AGENT_TOOL_ALLOWLIST` | Add `"web_search"` | Append to existing list |
| `services/agent/verifier.py::Verifier` | New module | NEW |
| `services/pipeline.py::SwarmQueryPipeline` | Conditional verifier hop after `asyncio.gather` peer fan-out | Modified existing |
| `utils/models.py::GenerationRequest.debate` | New optional bool field | Additive |
| `utils/models.py` AgentEvent subclasses | `VerifierStartEvent`, `VerifierCompleteEvent`, `VerifierDisagreementEvent` | NEW (extend ABC) |
| `controllers/api.py::agent_run_stream` | Already passes events through | No code change |
| `docs/agent-architecture.md` | Add 3 new event-schema subsections | Additive |
| `tests/unit/test_*_coverage.py` | 5 new test files | NEW |

## Suggested build order

**Phase 20** (smallest, highest leverage, ship first): WebSearchTool real impl + Tavily settings + UI render fix for `chunk_type="web"`. Independent of other v1.5 phases.

**Phase 21** (depends on Phase 20 only for the AGENT_TOOL_ALLOWLIST update pattern, not behavior): AGENT-05 verifier role + new SSE events + docs extension. Reuses v1.4 `SwarmQueryPipeline` infrastructure.

**Phase 22** (independent, can run after 20 or in parallel in dev): Coverage lift on 5 modules; pure test work.

## Watch Out For (top 5)

1. **P-01 Tavily key leakage** — `.env` only, never planning docs / commits / SSE error frames. Pre-commit scans for `tvly-` prefix.
2. **P-03 Tavily 5xx** — tenacity retry with `reraise=True`, then `_build_error_result` returning typed error `ToolResult` (do not raise into orchestrator). v1.4.2 pattern.
3. **P-07 Verifier hallucination** — verifier system prompt forbids inventing facts; verdict requires `evidence_chunk_ids: list[str]`; empty evidence → treat as disagreement.
4. **P-12 Mock-at-source regression** — Coverage lift MUST mock at consumer path (`services.<mod>.<dep>`), not source. v1.3 Phase 13 / 15 pattern.
5. **P-18 Stale Redis cache after pipeline change** — every v1.5 phase SUMMARY includes `redis-cli --scan --pattern 'rag:query:*' | xargs redis-cli del` ops note. v1.4.2 lesson.

## Open questions deferred to phase discussions

(Mirrored from STATE.md `Open Questions Carried into v1.5 Planning`.)

1. WebSearch citation contract (URL/snippet → `RetrievedChunk` shape) — Phase 20 discuss
2. WebSearch trigger condition (always-pickable vs only when KB empty) — Phase 20 plan
3. AGENT-05 debate shape (verifier vs peer-debate) — RECOMMENDED single-pass verifier; confirm Phase 21 discuss
4. AGENT-05 trigger (always-on vs opt-in) — RECOMMENDED opt-in `debate=true` flag; confirm Phase 21 discuss
5. Coverage lift scope (per-class vs whole-file) — Phase 22 plan
6. Tavily quota / fallback UX — Phase 20 plan

## v1.5 invariants (carried from v1.4 / v1.3)

- PostgreSQL RLS multi-tenancy preserved
- `asyncio.gather` + `BaseException` isolation for parallel calls
- Combined coverage `--fail-under=70` global floor (v1.5 strengthens it on 5 modules)
- `diff-cover --fail-under=80` on touched files
- Mock-at-consumer-path pattern (v1.3 Phase 13/15)
- SSE event format unchanged: `event: <type>\ndata: <model_dump_json>\n\n`
- Provider-neutral via `BaseLLMClient.call_agentic_turn` — verifier inherits this
- v1.3 D-04 — no production code changes for coverage lift
