# Phase 24: pgvector RecallTool + semantic recall rewrite — Context

**Gathered:** 2026-05-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the semantic READ path for `long_term_facts`. `LongTermMemory.get_relevant_facts()` flips from popularity-ranked (`ORDER BY importance DESC`) to query-embedding cosine similarity with `WHERE user_id=$1 AND tenant_id=$2` prefilter, using `SET LOCAL hnsw.iterative_scan = 'strict_order'` + `ef_search` GUC pattern (mirrors v1.1 Phase 8 filter-path). New `services/agent/tools/recall.py::RecallTool` subclasses `BaseTool`, registered via `@get_tool_registry().register`, added to `AGENT_TOOL_ALLOWLIST` at `services/pipeline.py:744` (allowlist grows 3→4). Always-pickable by planner; new `settings.recall_tool_enabled: bool = True` kill-switch mirrors Phase 23 `extractor_enabled` precedent. Backfill job `scripts/backfill_fact_embeddings.py` embeds pre-existing `embedding IS NULL` rows idempotently.

Semantic shift acknowledged at all 4 `load_context()` call sites in `services/pipeline.py` (lines 429, 608, 971, 1062): returned facts flip from popularity-ranked to query-relevant. Always-on injection PRESERVED; RecallTool sits alongside as planner-pick refinement path. Double-fetch duplication accepted for v1.6.

</domain>

<decisions>
## Implementation Decisions

### A — HNSW recall tuning
- **D-A1:** `SET LOCAL hnsw.iterative_scan = 'strict_order'` — matches ROADMAP. Slower than relaxed_order but returns exact top-k under the user_id+tenant_id prefilter. Cost vs `services/vectorizer/vector_store.py:322` chunks-table precedent (which uses `relaxed_order`) accepted because recall correctness > latency for facts (smaller per-tenant rowcount).
- **D-A2:** Reuse `settings.pgvector_ef_search_filtered = 200` — same field as chunks. Single tuning knob across both stores. Single `SET LOCAL hnsw.ef_search = {value}` inside the recall txn.
- **D-A3:** Top-K only, NO `WHERE embedding <=> $query < threshold` similarity floor. SQL returns up to K closest facts regardless of cosine quality. Eval gate (SC-1) tests cosine quality offline, not at runtime. Avoids guessing a threshold without real eval data. Matches `vector_store.py` chunks pattern.
- **D-A4:** `get_relevant_facts(limit=5)` default preserved. Existing signature unchanged — `load_context` + future `RecallTool.run` both call with default K=5. Per-caller override via `limit` param. Keeps prompt-budget delta measurable vs popularity baseline (SC-5).

### B — load_context() vs RecallTool overlap
- **D-B1:** Keep BOTH paths in v1.6. `load_context()` continues always-on injection at all 4 pipeline call sites (now query-relevant after the rewrite). `RecallTool` sits in the planner's tool allowlist as refinement path. Simplest migration; doesn't require teaching planner to always pick recall.
- **D-B2:** Accept duplicate facts when `load_context` and `RecallTool` both surface the same fact in one turn. ~30 token cost per dup; LLM dedupes at synthesis. Revisit in v1.7 if eval shows real prompt-quality regression.
- **D-B3:** MEM-10 audit shape — length-only regression test at each of the 4 `load_context` call sites (`assert len(ctx.long_term_facts) <= N` preserved) + separate prompt-budget measurement (mean/p95 token delta vs popularity baseline) written to phase audit artifact. NOT a gating test — purely observational. Matches ROADMAP SC-5 wording.
- **D-B4:** Always-pickable by planner + `settings.recall_tool_enabled: bool = True` operator kill-switch (mirrors Phase 23 `extractor_enabled`). When False, RecallTool not registered → `AGENT_TOOL_ALLOWLIST` length stays 4 BUT the registry lookup returns absent. Cheap insurance for ops emergency rollback without code change.

### C — Recall result formatting
- **D-C1:** Bulleted plain text, no metadata. `RecallTool.run()` returns `ToolResult(content="- fact1\n- fact2\n- fact3", ...)`. Smallest token footprint. Existing `load_context.long_term_facts: list[str]` shape preserved in `MemoryContext`. Importance + age deferred to v1.7+ (revisit when planner confidence-weighting evidence exists).
- **D-C2:** Empty-result marker. When `get_relevant_facts() == []`, RecallTool emits `ToolResult(content="No matching facts found.", ...)`. Prevents planner from interpreting empty as 'tool failed' or hallucinating facts. ~5 tokens overhead. Matches MCP tool-result best-practice conventions.
- **D-C3:** Best-effort error handling. RecallTool catches `(asyncpg.PostgresError, httpx.HTTPError, RuntimeError, OSError)` from the underlying `embed_one` + `get_relevant_facts` calls, returns `ToolResult(content="Memory unavailable; proceed without recall.", error=True)`. Mirrors Phase 23 MEM-04 isolation pattern — recall failure MUST NOT fail the user-facing turn.
- **D-C4:** Tool description verbatim from ROADMAP: `"Recall durable facts the agent has previously learned about this user. Call when the query references prior context, preferences, or recurring topics. Skip when conversation pivots to a new topic."`. Matches web_search.py / retrieve.py prose style. No examples (positive or negative) — defer if planner-pick eval shows reliability issue.

### D — Backfill job ops shape
- **D-D1:** Standalone async CLI `scripts/backfill_fact_embeddings.py`. `uv run python scripts/backfill_fact_embeddings.py [--dry-run] [--batch-size 100] [--resume-from-id N]`. Run-once-and-archive model — Phase 23 `save_fact` embeds-on-write so no recurring backfill needed in steady state. Idempotent via `WHERE embedding IS NULL` cursor; resume via CLI flag (not checkpoint file).
- **D-D2:** Rate limiting via existing `Embedder.embed_batch` (OpenAI: up to 2048 inputs/call; HuggingFace: local CPU/GPU bound) + chunked-commit 100 rows/txn (MEM-07 spec). No explicit `--qps` flag in v1.6. OpenAI 429 backoff already handled by tenacity in `embed_batch` (line 84 `stop_after_attempt(3)`). Add `--qps` later if 429s become routine.
- **D-D3:** Failure handling — whole-batch txn rollback on mid-batch failure. Operator re-runs script; idempotent `WHERE embedding IS NULL` skips the 0 covered rows from the failed batch, retries from the same chunk. Exit non-zero on rollback so CI / ops detect. Matches Phase 23 `save_fact` zero-partial-write pattern at the row level (extended here to the batch level).
- **D-D4:** Cost docs in `docs/memory-eviction.md` companion section (~30-50 lines): (a) cost formula by provider (OpenAI `text-embedding-3-large` @ $0.13/1M tokens × ~40 tokens/fact ≈ $5.2/M facts; HuggingFace zero-cost), (b) `--dry-run` flag usage for pre-run estimation, (c) rate-limit fallback if 429s hit. ROADMAP-spec'd location.

### Claude's Discretion
- Tie-break ordering within the cosine-similarity sort — ROADMAP says "tie-break on importance then created_at". Planner implements verbatim; no further discussion needed.
- Tool `parameters_schema` JSON shape `{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}` — verbatim from REQUIREMENTS MEM-08. Planner implements as-is.
- `ToolContext` shape — RecallTool reads `user_id`, `tenant_id`, `query` from existing `ToolContext` surface (mirrors RetrieveTool / WebSearchTool patterns at `services/agent/tools/`). No new ToolContext fields.
- Backfill `--dry-run` output format — print `Would embed N facts (~M tokens, ~$X)` and exit. Standard CLI convention.
- Whether to register RecallTool in `services/agent/tools/__init__.py` top-level (matches RetrieveTool/WebSearchTool registration pattern) — planner decides; default expected: yes.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Locked requirements + roadmap
- `.planning/REQUIREMENTS.md` lines 31-39 — MEM-06 through MEM-10 acceptance bullets
- `.planning/ROADMAP.md` §Phase 24 — goal, depends-on, canonical refs, 5 success criteria
- `.planning/STATE.md` §Carry-Forward Decisions + §Open Questions §4 (HNSW iterative_scan mode — resolved here as D-A1)

### Rewrite targets
- `services/memory/memory_service.py:270-287` — current `get_relevant_facts(user_id, tenant_id, query, limit=5) -> list[str]` (popularity-ranked; rewrite target for MEM-06)
- `services/memory/memory_service.py:395-417` — `load_context(session_id, user_id, tenant_id, query) -> MemoryContext` (calls `get_relevant_facts` at line 406 — semantic shifts when MEM-06 lands)
- `services/pipeline.py:429, 608, 971, 1062` — 4 `await self._memory.load_context(...)` call sites (MEM-10 audit subjects)
- `services/pipeline.py:744` — `AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search", "web_search"]` (grows 3→4 for MEM-09)

### Pattern sources
- `services/vectorizer/vector_store.py:316-326` — HNSW filtered-recall pattern: `SET LOCAL hnsw.iterative_scan = 'relaxed_order'` + `SET LOCAL hnsw.ef_search = {value}` + `ORDER BY embedding <=> $query::vector LIMIT $k`. Phase 24 mirrors with `'strict_order'` per D-A1.
- `services/agent/tools/web_search.py` (307 LOC) — `BaseTool` subclass shape: class-var `name`/`description`/`parameters_schema`, `async def run(ctx: ToolContext) -> ToolResult`, registration via `@get_tool_registry().register`. RecallTool mirror template.
- `services/agent/tools/retrieve.py` (`RetrieveTool`, `RefinedRetrieveTool`) — alternate `BaseTool` reference; `ToolContext.query` + `ctx.user_id` access patterns.
- `services/agent/tools/base.py` — `BaseTool` ABC + `ToolContext` + `ToolResult` Pydantic V2 contracts.
- `services/agent/tools/registry.py` — `ToolRegistry` + `@get_tool_registry().register` decorator pattern.
- `services/agent/tools/__init__.py` — top-level registration site (RecallTool addition mirrors RetrieveTool/RefinedRetrieveTool/WebSearchTool entries).
- `services/agent/extractor.py` — `settings.extractor_enabled` kill-switch precedent for D-B4 (`recall_tool_enabled`).
- `services/vectorizer/embedder.py:84-100` — `OpenAIEmbedder.embed_batch` with tenacity + `dimensions=settings.embedding_dim` (Phase 23 A1). Reused by backfill batch path.

### Invariants
- `CLAUDE.md` — narrow exception types only (ERR-01); Tenacity for external calls; structured logging; Pydantic V2 frozen
- `Claude.md` — production-grade only; no prototype code; no bare `except`
- v1.1 Phase 8 — `hnsw.iterative_scan` + raised `ef_search` pattern when WHERE prefilter active (carried forward)
- v1.4 Phase 17 — `BaseTool` + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST` constant (Phase 24 grows allowlist by 1)
- v1.5 Phase 22 — per-module coverage gate ≥ 70% on touched modules; diff-cover ≥ 80%

### Companion docs
- `docs/memory-eviction.md` — existing doc; D-D4 adds the backfill cost-docs companion section
- `docs/agent-architecture.md` — SSE event schema (v1.4 Phase 18); Phase 24 ships WITHOUT new `memory.recalled` event per design doc Premise 5

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`Embedder.embed_one()`** at `services/vectorizer/embedder.py:32` — used by Phase 23 `save_fact`; reused at recall-time to embed the query before SELECT. Same model = same vector space = direct cosine comparison.
- **`Embedder.embed_batch()`** — used by backfill (D-D2) to process up to 2048 facts per OpenAI API call.
- **`LongTermMemory._get_pool()`** with `register_vector` init callback (Phase 23 Plan 01) — pgvector codec already registered; recall query's `$N::vector` binding works without further setup.
- **`MemoryContext` dataclass** at `services/memory/memory_service.py` — `long_term_facts: list[str]` field shape preserved (D-C1).
- **`BaseTool` + `ToolContext` + `ToolResult` contracts** at `services/agent/tools/base.py` — Pydantic V2 frozen; RecallTool subclasses cleanly.
- **`get_tool_registry().register` decorator** at `services/agent/tools/__init__.py:11-12` — RecallTool registers at module import time.
- **`extractor_enabled` kill-switch precedent** (Phase 23 `config/settings.py`) — `recall_tool_enabled` follows the same shape.

### Established Patterns
- **HNSW filtered-recall pattern** (`vector_store.py:316-326`) — `SET LOCAL hnsw.iterative_scan` + `SET LOCAL hnsw.ef_search` inside a single async-with-conn block, then `ORDER BY embedding <=> $query::vector LIMIT $k`. Phase 24's `get_relevant_facts` rewrite copies the shape verbatim with the operator + GUC value swap per D-A1.
- **Always-on `load_context()` injection** (`pipeline.py:429,608,971,1062`) — 4 call sites all use `await self._memory.load_context(req.session_id, user_id, tenant_id, req.query)`. Per D-B1, behavior preserved; only `long_term_facts` semantics shift (popularity→query-relevance).
- **Tool-result best-effort isolation** (Phase 23 MEM-04) — recall failure must NOT fail the user turn; D-C3 returns `error=True` ToolResult with explanatory content.
- **Backfill idempotency** — `WHERE embedding IS NULL` cursor + chunked-commit 100 rows/txn is the MEM-07 spec. D-D3 extends to whole-batch txn rollback.

### Integration Points
- **Planner ↔ ToolRegistry** — planner builds `ToolPlan` from registered tools in `AGENT_TOOL_ALLOWLIST`. Adding `"recall_memory"` (MEM-09) makes RecallTool selectable. No planner code change needed (allowlist is data-driven).
- **`AgentQueryPipeline.run` / `SwarmQueryPipeline._run_with_state`** — planner's `ToolPlan` flows through executor; RecallTool's `run(ctx)` invoked when planner picks `recall_memory`. No new pipeline code, just registry addition.
- **`MemoryService.load_context` ↔ `MemoryContext.long_term_facts`** — semantic shift internal to `load_context`; consumer contract `list[str]` unchanged.

</code_context>

<specifics>
## Specific Ideas

- D-A1's `strict_order` is the formal answer to STATE.md Open Question #4 (which noted that ROADMAP said `strict_order` while `vector_store.py:322` precedent uses `relaxed_order`). Reason: facts-per-tenant rowcount is small enough that exact recall correctness wins over the ~10-30% latency hit observed in HNSW benchmarks.
- D-B1's "keep both" plus D-B2's "accept duplicates" is an explicit punt to v1.7+. If eval data shows prompt-bloat regression, the v1.7 fix path is either: (a) shrink `load_context` K to 1-2 + lean on RecallTool, or (b) dedup at planner-tool-result-merge time (B2 option 2).
- D-C3's `error=True` flag on ToolResult is observable to executor/synthesizer audit logs even though the content string ("Memory unavailable; proceed without recall.") is what the LLM sees. Useful for ops dashboards to track recall-availability SLO.
- D-D1's "run-once-and-archive" model is consistent with the v1.6 deploy story: Phase 24 deploy runs backfill once to cover pre-existing rows; afterward `save_fact` embed-on-write covers steady state. No CronJob YAML needed in v1.6.

</specifics>

<deferred>
## Deferred Ideas

### v1.7+ follow-ups (captured during this discussion)
- **Recall result metadata** (C1 option 2) — return importance + recalled_days_ago alongside fact text. Defer until planner confidence-weighting evidence exists.
- **Dedup at planner-tool-result-merge** (B2 option 2) — only worth building if eval shows duplicates measurably hurt synthesis quality.
- **`load_context` K shrink to 1-2** (B1 option 2) — alternate v1.7+ path if duplicate-fact prompt-bloat surfaces.
- **`--qps N` rate-limit flag for backfill** (D2 option 2) — add if OpenAI 429s become routine on shared-quota tenants.
- **Configurable similarity threshold** (A3 option 3) — `settings.recall_min_similarity` opt-in once eval data justifies a value.
- **CronJob template for ongoing backfill** (D1 option 2) — only if a recurring need surfaces (e.g., periodic schema migrations adding new fact rows).
- **SSE `memory.recalled` event** — out per design doc Premise 5; v1.7+.

### Out of v1.6 scope (re-confirming carry-forward)
- Cross-user-within-tenant recall (REQUIREMENTS.md v1.6 Out of Scope)
- RLS enforcement on `long_term_facts` (carry-forward TODO from v1.0 Phase 2)
- Per-tenant capacity overrides + importance decay (Phase 25 deferred items)
- Live planner `save_memory` tool (rejected in /office-hours D3)
- Manual "remember this" UI surface (v1.7+ unless users ask)

</deferred>

---

*Phase: 24-pgvector-recalltool-semantic-recall-rewrite*
*Context gathered: 2026-05-16*
