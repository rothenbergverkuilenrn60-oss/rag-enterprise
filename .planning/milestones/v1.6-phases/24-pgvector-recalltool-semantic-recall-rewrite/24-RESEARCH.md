# Phase 24: pgvector RecallTool + semantic recall rewrite — Research

**Researched:** 2026-05-16
**Domain:** pgvector cosine-similarity recall + agent-runtime tool registration + idempotent offline backfill
**Confidence:** HIGH (every load-bearing claim verified against the working tree on 2026-05-16; assumptions explicitly flagged)

## Summary

Phase 24 flips the **READ** path for `long_term_facts` from popularity-ranked to query-embedding-relevance, and exposes that path to the planner as `RecallTool`. Five touch points:

1. **Recall query rewrite** — `LongTermMemory.get_relevant_facts()` at `services/memory/memory_service.py:270-287` swaps the popularity SELECT for `ORDER BY embedding <=> $query::vector LIMIT $k`, wrapped in a single `async with conn.transaction()` that issues `SET LOCAL hnsw.iterative_scan = 'strict_order'` + `SET LOCAL hnsw.ef_search = {settings.pgvector_ef_search_filtered}` (D-A1 + D-A2). Pattern mirrors `services/vectorizer/vector_store.py:311-340` byte-for-byte with two deltas: scan mode `strict_order` (not `relaxed_order`) and no tenant-GUC (`set_config('app.current_tenant', …)`) — long_term_facts has no RLS in v1.6 (carry-forward TODO).
2. **RecallTool class** — new `services/agent/tools/recall.py` clones `services/agent/tools/web_search.py` shape: `@get_tool_registry().register` decorator, class-vars `name="recall_memory"` / `description=<ROADMAP verbatim>` / `parameters_schema={"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}`, `async def run(self, args, ctx) -> ToolResult`. Reads `ctx.req.user_id`, `ctx.req.tenant_id`, `query` (args or `ctx.req.query` fallback per RetrieveTool precedent at retrieve.py:181). Best-effort error wrapping (D-C3) — never raises.
3. **Tool registration + allowlist** — `services/agent/tools/__init__.py:15-20` adds `from services.agent.tools.recall import RecallTool  # noqa: F401` import (side-effect registers via decorator at package load). `services/pipeline.py:744` allowlist literal `["search_knowledge_base", "refine_search", "web_search"]` grows to length 4 with `"recall_memory"` appended.
4. **Settings kill-switch** — `config/settings.py` adds `recall_tool_enabled: bool = True` next to existing `extractor_enabled` precedent (line 302). Gating shape diverges from extractor: instead of branching in pipeline code, the gate guards the **registration** — when False the import-time `@get_tool_registry().register` is skipped so registry lookup returns absent (D-B4 implementation choice; planner section §Implementation note for D-B4 below details the two valid shapes).
5. **Offline backfill** — `scripts/backfill_fact_embeddings.py` (new) — async CLI, idempotent via `WHERE embedding IS NULL` cursor, chunked-commit 100 rows/txn, whole-batch rollback on failure with non-zero exit. Reuses `Embedder.embed_batch` (OpenAI 2048/batch; HF/Ollama bounded by local CPU/GPU). Constructs its own asyncpg pool (or reuses `LongTermMemory()` to inherit `register_vector` codec init) — recommendation: instantiate `LongTermMemory()` and call its `_get_pool()` to inherit the Phase 23 `register_vector` callback. Discretion item: planner picks (a) reuse `LongTermMemory._get_pool` (zero new pool config) or (b) standalone asyncpg pool with own `register_vector` init (mirrors the LongTermMemory pattern). Recommendation: (a).

**Primary recommendation:** Land the `get_relevant_facts` rewrite + RecallTool class + registration + allowlist edit in one TDD-first wave (mirroring Phase 23 Wave-1 atomic schema+save_fact), then the backfill script in a separate wave (operational tool with its own ergonomics and unit tests). Wire the kill-switch via **conditional registration** in `services/agent/tools/__init__.py` (`if settings.recall_tool_enabled: from … import RecallTool`) so the allowlist behavior naturally degrades when the toggle flips.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**A — HNSW recall tuning:**

- **D-A1:** `SET LOCAL hnsw.iterative_scan = 'strict_order'`. Slower than relaxed_order (~10-30% latency hit per HNSW benchmarks [ASSUMED — benchmark figures from prior literature, not measured against this tree]) but returns exact top-k under the `WHERE user_id=$1 AND tenant_id=$2` prefilter. Cost vs `vector_store.py:322` precedent (which uses `relaxed_order`) accepted because recall correctness > latency for facts (smaller per-tenant rowcount; SC-3 still demands <50ms p95 at 10k rows).
- **D-A2:** Reuse `settings.pgvector_ef_search_filtered = 200` (defined in `config/settings.py:243`). Single tuning knob across both stores. Single `SET LOCAL hnsw.ef_search = {value}` inside the recall transaction.
- **D-A3:** Top-K only, NO `WHERE embedding <=> $query < threshold` similarity floor. SQL returns up to K closest facts regardless of cosine quality. Eval gate (SC-1) tests cosine quality offline, not at runtime. Avoids guessing a threshold pre-deploy. Matches `vector_store.py` chunks pattern.
- **D-A4:** `get_relevant_facts(limit=5)` default preserved. Existing signature unchanged — `load_context` + future `RecallTool.run` both call with default K=5. Per-caller override via `limit` param. Keeps prompt-budget delta measurable vs popularity baseline (SC-5).

**B — load_context() vs RecallTool overlap:**

- **D-B1:** Keep BOTH paths in v1.6. `load_context()` continues always-on injection at all 4 pipeline call sites (now query-relevant after the rewrite). `RecallTool` sits in the planner's tool allowlist as refinement path.
- **D-B2:** Accept duplicate facts when `load_context` and `RecallTool` both surface the same fact in one turn. ~30 token cost per dup; LLM dedupes at synthesis.
- **D-B3:** MEM-10 audit shape — length-only regression test at each of the 4 `load_context` call sites (`assert len(ctx.long_term_facts) <= N` preserved) + separate prompt-budget measurement (mean/p95 token delta vs popularity baseline) written to phase audit artifact. NOT a gating test — purely observational.
- **D-B4:** Always-pickable by planner + `settings.recall_tool_enabled: bool = True` operator kill-switch. When False, RecallTool not registered → registry lookup returns absent.

**C — Recall result formatting:**

- **D-C1:** Bulleted plain text, no metadata. `RecallTool.run()` returns `ToolResult(content="- fact1\n- fact2\n- fact3", ...)`. `MemoryContext.long_term_facts: list[str]` shape preserved in `load_context()`.
- **D-C2:** Empty-result marker. When `get_relevant_facts() == []`, RecallTool emits `ToolResult(content="No matching facts found.", ...)`. Prevents planner from interpreting empty as 'tool failed' or hallucinating facts. ~5 tokens.
- **D-C3:** Best-effort error handling. RecallTool catches `(asyncpg.PostgresError, httpx.HTTPError, RuntimeError, OSError)` from underlying `embed_one` + `get_relevant_facts` calls, returns `ToolResult(content="Memory unavailable; proceed without recall.", is_error=True)`. Mirrors Phase 23 MEM-04 isolation pattern — recall failure MUST NOT fail the user-facing turn.
- **D-C4:** Tool description verbatim from ROADMAP: `"Recall durable facts the agent has previously learned about this user. Call when the query references prior context, preferences, or recurring topics. Skip when conversation pivots to a new topic."`

**D — Backfill job ops shape:**

- **D-D1:** Standalone async CLI `scripts/backfill_fact_embeddings.py`. `uv run python scripts/backfill_fact_embeddings.py [--dry-run] [--batch-size 100] [--resume-from-id N]`. Run-once-and-archive model. Idempotent via `WHERE embedding IS NULL` cursor; resume via CLI flag (not checkpoint file).
- **D-D2:** Rate limiting via existing `Embedder.embed_batch` + chunked-commit 100 rows/txn. No explicit `--qps` flag in v1.6.
- **D-D3:** Whole-batch txn rollback on mid-batch failure. Idempotent re-run skips the 0-covered rows from the failed batch. Exit non-zero on rollback.
- **D-D4:** Cost docs in `docs/memory-eviction.md` companion section (~30-50 lines): cost formula by provider, `--dry-run` usage, rate-limit fallback.

### Claude's Discretion (locked-in resolutions for the planner)

| Item | Locked-in resolution |
|---|---|
| Tie-break after cosine sort | `ORDER BY embedding <=> $query::vector, importance DESC, created_at DESC` (ROADMAP literal; SQL fragment goes in the recall SELECT) |
| `parameters_schema` JSON | `{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}` — verbatim REQUIREMENTS MEM-08 |
| `ToolContext` access pattern | `args.get("query") or ctx.req.query`; `ctx.req.user_id`; `ctx.req.tenant_id` — matches retrieve.py:181 + web_search.py:227. Empty `user_id` or `tenant_id` → return `"No matching facts found."` (D-C2 path) before any pool acquire. |
| Backfill `--dry-run` output | `Would embed N facts (~M tokens, ~$X)` then exit 0. Standard CLI convention. |
| RecallTool registration in `services/agent/tools/__init__.py` | YES — add `from services.agent.tools.recall import RecallTool  # noqa: F401` line guarded by `if settings.recall_tool_enabled:`. Mirrors RetrieveTool / WebSearchTool entries at lines 15-20. |
| `MemoryService` accessor inside RecallTool | Use `get_memory_service()` singleton at `services/memory/memory_service.py:454`. Call `mem._long.get_relevant_facts(...)` directly (the private `_long` access is acceptable per the v1.4 RetrieveTool pattern that reaches `ctx.retriever`). Alternative: add a `MemoryService.get_relevant_facts` passthrough — leave to planner. |

### Deferred Ideas (OUT OF SCOPE for Phase 24)

- **Recall result metadata** (C1 option 2) — return importance + recalled_days_ago. v1.7+.
- **Dedup at planner-tool-result-merge** (B2 option 2) — only if eval shows duplicates hurt synthesis. v1.7+.
- **`load_context` K shrink to 1-2** (B1 option 2) — alternate v1.7+ path if prompt-bloat surfaces.
- **`--qps N` rate-limit flag for backfill** (D2 option 2) — add if OpenAI 429s become routine.
- **Configurable similarity threshold** (A3 option 3) — `settings.recall_min_similarity` opt-in once eval data justifies.
- **CronJob template for ongoing backfill** (D1 option 2) — only if recurring need surfaces.
- **SSE `memory.recalled` event** — per design doc Premise 5; v1.7+.
- **Cross-user-within-tenant recall** — v1.6 Out of Scope (REQUIREMENTS.md).
- **RLS enforcement on `long_term_facts`** — carry-forward TODO from v1.0 Phase 2; NOT this phase.
- **Live planner `save_memory` tool** — rejected in /office-hours D3.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEM-06 | `LongTermMemory.get_relevant_facts()` rewrite — query embedding + pgvector cosine similarity with `WHERE user_id=$1 AND tenant_id=$2`; `SET LOCAL hnsw.iterative_scan = strict_order` + `ef_search`; top-K ordered by similarity with tie-break on importance then created_at | Architecture §Pattern 1 + Code Examples §get_relevant_facts rewrite; mirrors `vector_store.py:311-340` byte-for-byte with scan-mode + tenant-GUC deltas documented in Pitfall 2 |
| MEM-07 | Backfill job `scripts/backfill_fact_embeddings.py` — idempotent (`WHERE embedding IS NULL`), resumable cursor, chunked-commit 100 rows/txn, rate-limited via embed_batch; cost documented in `docs/memory-eviction.md` | Architecture §Pattern 4 + Code Examples §backfill skeleton; reuses `BatchedEmbedder.embed_batch` (embedder.py:142) for OpenAI 2048/batch + tenacity retry already in place |
| MEM-08 | `services/agent/tools/recall.py::RecallTool` — `BaseTool` subclass mirroring `web_search.py`; class-vars name/description/parameters_schema; `run()` returns bulleted ToolResult | Architecture §Pattern 2 + Code Examples §RecallTool skeleton; verified `BaseTool.__init_subclass__` enforces three ClassVars at class-body time (base.py:40-49) |
| MEM-09 | `"recall_memory"` added to `AGENT_TOOL_ALLOWLIST` at `services/pipeline.py:744` (3→4); RecallTool registered via `@get_tool_registry().register` in `services/agent/tools/__init__.py`; planner-pick integration test | Architecture §Pattern 3; verified registration is decorator-driven at module-import time (registry.py:33-42); allowlist literal at line 744 — used by all 3 agent pipelines at lines 984/1075/1321 |
| MEM-10 | Downstream consumer audit at all 4 `load_context` call sites (pipeline.py:429, 608, 971, 1062); length-only regression assertion + prompt-budget measurement; no v1.0-v1.5 test failures | Architecture §Pattern 5; verified all 4 call sites exist at exact line numbers; `MemoryContext.long_term_facts: list[str]` shape unchanged (memory_service.py:69) |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HNSW recall SQL execution | Database / Storage | — | pgvector + asyncpg; `SET LOCAL` GUCs are session-scoped DB settings; all logic lives in `LongTermMemory.get_relevant_facts` |
| Query embedding | Backend (service adapter) | — | `Embedder.embed_one()` adapter (BatchedEmbedder.embed_one at embedder.py:152); reused at recall time |
| RecallTool dispatch | Backend (agent-runtime tool) | — | `services/agent/tools/recall.py` sits alongside RetrieveTool / WebSearchTool — same agent-runtime tier |
| Tool registration | Backend (module load) | — | Decorator at class definition; `@get_tool_registry().register` runs at import time |
| Planner tool selection | Backend (planner LLM) | — | `AGENT_TOOL_ALLOWLIST` data-driven; no planner code change needed — planner sees the 4th tool schema via `registry.schemas_for(provider, names=ALLOWLIST)` |
| Backfill job | Backend (CLI script) | Database / Storage | Standalone async script; reads pgvector rows via `LongTermMemory._get_pool()` (reuse) or own asyncpg pool; embeds via `BatchedEmbedder.embed_batch` |
| MEM-10 audit | Backend (regression test) | — | `tests/integration/test_pipeline_load_context_audit.py` asserts `len(ctx.long_term_facts) <= N` at each call site + writes token-delta artifact |

## Project Constraints (from ./CLAUDE.md)

- **No prototype code** — Pydantic V2, mypy --strict, ruff
- **No bare `except`** — narrow exception types only (ERR-01)
- **No blocking I/O in async contexts** — all I/O via existing async adapters
- **Adapter pattern** for external dependencies — RecallTool uses `BaseEmbedder` ABC + `LongTermMemory` instance only
- **Tenacity retry** for all external calls — recall path inherits tenacity from `BatchedEmbedder.embed_one` → `embed_batch` (embedder.py:84 stop_after_attempt(3)). No new retry layer at RecallTool level (matches WebSearchTool precedent — retry lives in `_tavily_search` inner helper, not on the tool itself).
- **Structured logging** for every operation — `loguru.logger` with kwarg fields, matching `memory_service.py:204-326` patterns

## Standard Stack

### Core (zero new dependencies — all in tree)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pydantic` (V2) | already pinned | `ToolContext` / `ToolResult` frozen models | utils/models.py:386-407 [VERIFIED] |
| `asyncpg` | already pinned | HNSW recall SELECT + tx-scoped `SET LOCAL` GUCs | memory_service.py:156-158 pool already created with `register_vector` init [VERIFIED post-Phase-23] |
| `pgvector.asyncpg` | already pinned | `$N::vector` codec binding (registered by `_init_conn` callback) | memory_service.py:150-153 [VERIFIED — Phase 23 already added the callback] |
| `loguru` | already pinned | Structured error logging in RecallTool best-effort catch | memory_service.py error-shape convention [VERIFIED] |

### Supporting (reused as-is)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `services.vectorizer.embedder.get_embedder()` → `embed_one(text)` | v1.0 | Embed the query string at recall time | Inside `get_relevant_facts` rewrite [VERIFIED: embedder.py:32 + BatchedEmbedder.embed_one at 152] |
| `services.vectorizer.embedder.BatchedEmbedder.embed_batch` | v1.0 | Backfill batch embedding (OpenAI: 2048/call; HF/Ollama: CPU/GPU bound) | Inside `scripts/backfill_fact_embeddings.py` [VERIFIED: embedder.py:142-150] |
| `services.agent.tools.base.BaseTool` | v1.4 Phase 17 | RecallTool subclass | tools/base.py:24-74 [VERIFIED] |
| `services.agent.tools.registry.get_tool_registry().register` | v1.4 Phase 17 | Decorator registration; raises ValueError on duplicate name | tools/registry.py:33-42 [VERIFIED] |
| `services.memory.memory_service.get_memory_service()` → `._long.get_relevant_facts(...)` | v1.0 | RecallTool reaches the LongTermMemory instance via the MemoryService singleton | memory_service.py:454-458 [VERIFIED] |
| `services.memory.memory_service.LongTermMemory._get_pool()` | v1.0 + Phase 23 register_vector init | Backfill pool reuse (recommended path) | memory_service.py:146-160 [VERIFIED post-Phase-23] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reuse `pgvector_ef_search_filtered = 200` (D-A2) | Dedicated `pgvector_ef_search_memory` | Discussed in Discussion-Log A2 option 2; rejected — single tuning knob; smaller per-tenant rowcount makes 200 a safe upper bound |
| Conditional registration (kill-switch via if-guarded import) | Always-register + branch in pipeline | Discussion-Log B4 option 2 was always-pickable-no-kill-switch (rejected); conditional registration is the simplest implementation of the locked D-B4 choice; alternative would be a runtime check inside `RecallTool.run` to early-return — wastes a registry entry |
| Reuse `LongTermMemory._get_pool` for backfill | Standalone asyncpg pool in script | Reuse path inherits `register_vector` codec automatically; standalone pool requires duplicating the `_init_conn` callback — recommend reuse |
| Bulleted plain text (D-C1) | JSON + importance + age | Discussion-Log C1 option 2 (rejected) — 3x token cost; no evidence planner uses metadata yet |

**Installation:** No `uv add` needed. All dependencies already pinned in `pyproject.toml`.

**Version verification (zero new packages):**

```bash
# Confirm all required modules import — no install needed
uv run python -c "import pydantic, asyncpg, pgvector, loguru, tenacity; print('OK')"
```

## Package Legitimacy Audit

> **Not applicable** — Phase 24 introduces **zero new packages**. Every import is already in the dependency tree and has been used by shipped milestones v1.0–v1.6 (Phase 23). No slopcheck required.

## Architecture Patterns

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  AgentQueryPipeline.run / .run_streaming / SwarmQueryPipeline.run    │
│  (services/pipeline.py:971, 1062, 1321)                              │
│                                                                       │
│   mem_ctx = await self._memory.load_context(                          │
│       session_id, user_id, tenant_id, req.query  ←── query passed in  │
│   )                                                                   │
│                          │                                            │
│                          ▼                                            │
│   _build_initial_messages(req, mem_ctx)                               │
│       — mem_ctx.long_term_facts: list[str]                            │
│         (NOW query-relevant after MEM-06; semantic shift              │
│          documented in MEM-10 audit)                                  │
│                                                                       │
│   ── planner.plan_from_messages(messages,                             │
│         tools=get_tool_registry().schemas_for(                        │
│             "anthropic",                                              │
│             names=AGENT_TOOL_ALLOWLIST,  ← now 4 entries              │
│         ),                                                            │
│         system=self._AGENT_SYSTEM,                                    │
│      )                                                                │
│                          │                                            │
│       ┌──────────────────┴────────────┐                               │
│       ▼ planner picks "recall_memory" ▼ planner picks other tools     │
│   executor dispatches via registry.get("recall_memory")               │
│       │                                                               │
│       ▼ (BaseTool.run signature)                                      │
│   RecallTool.run(args, ctx):                                          │
│       ├ short-circuit: if not settings.recall_tool_enabled            │
│       │   → unreachable (tool not registered) NOTE: kill-switch       │
│       │   implemented via conditional registration in __init__.py     │
│       ├ query_str = args["query"] or ctx.req.query                    │
│       ├ user_id, tenant_id = ctx.req.user_id, ctx.req.tenant_id       │
│       ├ if not user_id or not tenant_id:                              │
│       │   return ToolResult(content="No matching facts found.")       │
│       ├ try:                                                          │
│       │   mem = get_memory_service()                                  │
│       │   facts = await mem._long.get_relevant_facts(                 │
│       │       user_id, tenant_id, query_str, limit=5                  │
│       │   )                                                           │
│       │ except (asyncpg.PostgresError, httpx.HTTPError,               │
│       │         RuntimeError, OSError) as exc:                        │
│       │     logger.error(...) ; return ToolResult(                    │
│       │         content="Memory unavailable; proceed without recall.",│
│       │         is_error=True)                                        │
│       └ if not facts:                                                 │
│             return ToolResult(content="No matching facts found.")     │
│         return ToolResult(content="- " + "\n- ".join(facts))          │
└──────────────────────────────────────────────────────────────────────┘

   LongTermMemory.get_relevant_facts (MEM-06 rewrite):
   ┌──────────────────────────────────────────────────────────────────┐
   │ q_vec: list[float] = await get_embedder().embed_one(query)       │
   │ async with pool.acquire() as conn:                               │
   │   async with conn.transaction():       ← SET LOCAL needs txn     │
   │     ef = int(settings.pgvector_ef_search_filtered)               │
   │     await conn.execute("SET LOCAL hnsw.iterative_scan ="         │
   │                         " 'strict_order'")                       │
   │     await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")       │
   │     rows = await conn.fetch(                                     │
   │         """SELECT fact FROM long_term_facts                      │
   │            WHERE user_id=$1 AND tenant_id=$2                     │
   │            ORDER BY embedding <=> $3::vector,                    │
   │                     importance DESC, created_at DESC             │
   │            LIMIT $4""",                                          │
   │         user_id, tenant_id, q_vec, limit,                        │
   │     )                                                            │
   │ return [r["fact"] for r in rows]                                 │
   │ except (asyncpg.PostgresError, httpx.HTTPError,                  │
   │         RuntimeError, OSError) as exc:                           │
   │     logger.error(operation="get_facts_semantic", exc_info=exc)   │
   │     return []                                                    │
   └──────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
services/
├── agent/
│   ├── tools/
│   │   ├── __init__.py            # MODIFY — add conditional import of RecallTool
│   │   ├── base.py                # existing — DO NOT modify
│   │   ├── registry.py            # existing — DO NOT modify
│   │   ├── recall.py              # NEW — ~120 LOC, mirrors web_search.py shape
│   │   ├── retrieve.py            # existing pattern reference
│   │   └── web_search.py          # existing pattern reference
│   ├── extractor.py               # Phase 23 kill-switch precedent
│   └── …
├── memory/
│   └── memory_service.py          # MODIFY get_relevant_facts (lines 270-287)
├── pipeline.py                    # MODIFY AGENT_TOOL_ALLOWLIST line 744 (3→4)
└── vectorizer/
    ├── vector_store.py            # existing HNSW pattern source — DO NOT modify
    └── embedder.py                # existing — DO NOT modify (Phase 23 dim fix landed)

config/
└── settings.py                    # MODIFY — add recall_tool_enabled: bool = True

scripts/
└── backfill_fact_embeddings.py    # NEW — async CLI, ~180 LOC

docs/
└── memory-eviction.md             # MODIFY — companion section (~30-50 lines)

tests/
├── unit/
│   ├── test_recall_tool.py                       # NEW — RecallTool unit tests
│   ├── test_memory_recall_semantic.py            # NEW — get_relevant_facts rewrite
│   ├── test_backfill_fact_embeddings.py          # NEW — backfill script unit tests
│   └── test_settings_recall_kill_switch.py       # NEW — conditional registration
└── integration/
    ├── test_recall_tool_planner_pick.py          # NEW — planner picks/skips integration
    └── test_pipeline_load_context_audit.py       # NEW — MEM-10 4-call-site length regression
```

### Pattern 1: HNSW filtered cosine recall inside an explicit transaction (MEM-06)

**What:** Recall SQL with `WHERE user_id=$1 AND tenant_id=$2` prefilter using `SET LOCAL hnsw.iterative_scan` + `hnsw.ef_search` to walk the HNSW graph until top-k filter-matches found, ordered by cosine distance.
**When:** Any pgvector SELECT that has a WHERE clause AND an HNSW index AND wants top-k correctness.
**Why an explicit txn is required:** `SET LOCAL` scopes to the current transaction. Outside `conn.transaction()`, asyncpg `conn.execute` runs in auto-commit mode → `SET LOCAL` becomes a no-op-then-forgotten setting, and the SELECT runs with default `ef_search=40`. This is **Pitfall 2** below — verified against existing `vector_store.py:312` which DOES wrap in `async with conn.transaction()`. [VERIFIED: services/vectorizer/vector_store.py:311-340]
**Example:**
```python
# Source: services/vectorizer/vector_store.py:311-340 (filter-path)
# Phase 24 mirror with deltas: scan_mode='strict_order'; no tenant-GUC; query vector arg
pool = await self._get_pool()
async with pool.acquire() as conn:
    async with conn.transaction():
        ef_search = int(settings.pgvector_ef_search_filtered)
        await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
        await conn.execute(f"SET LOCAL hnsw.ef_search = {ef_search}")
        rows = await conn.fetch(
            """SELECT fact FROM long_term_facts
               WHERE user_id=$1 AND tenant_id=$2
               ORDER BY embedding <=> $3::vector, importance DESC, created_at DESC
               LIMIT $4""",
            user_id, tenant_id, q_vec, limit,
        )
return [r["fact"] for r in rows]
```

### Pattern 2: BaseTool subclass with class-var registration (MEM-08)

**What:** Subclass `BaseTool`, declare three `ClassVar` attributes (`name`, `description`, `parameters_schema`), implement `async def run(self, args, ctx) -> ToolResult`, decorate the class with `@get_tool_registry().register`.
**When:** Any new agent-runtime tool — RetrieveTool / RefinedRetrieveTool / WebSearchTool all follow this shape.
**Example:**
```python
# Source: services/agent/tools/web_search.py:208-307 (shape mirror)
from typing import Any, ClassVar
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from utils.models import ToolContext, ToolResult

_RECALL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

@get_tool_registry().register
class RecallTool(BaseTool):
    name: ClassVar[str] = "recall_memory"
    description: ClassVar[str] = (
        "Recall durable facts the agent has previously learned about this user. "
        "Call when the query references prior context, preferences, or recurring "
        "topics. Skip when conversation pivots to a new topic."
    )
    parameters_schema: ClassVar[dict[str, Any]] = _RECALL_PARAMETERS_SCHEMA

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        # Implementation per Architecture diagram above
        ...
```

### Pattern 3: Conditional registration as kill-switch (D-B4 implementation)

**What:** Wrap the side-effect import line in `services/agent/tools/__init__.py` with `if settings.recall_tool_enabled:`. When False, the `@get_tool_registry().register` decorator never runs → registry lookup `registry.get("recall_memory")` raises KeyError → planner-LLM never sees the tool schema (because `registry.schemas_for(..., names=AGENT_TOOL_ALLOWLIST)` filters by registered names at registry.py:78).
**When:** Operational kill-switch for a tool that should be entirely invisible to the planner when disabled.
**Why this shape:** Alternative is to add a runtime check inside `RecallTool.run` that returns "tool disabled" — wastes a planner-prompt slot and confuses the model. Conditional registration is cleaner. **Verify post-implementation**: `len(AGENT_TOOL_ALLOWLIST)` stays at 4 regardless of toggle (per D-B4 wording — the list is a *constant* allowlist; registry membership is what flips).
**Example:**
```python
# services/agent/tools/__init__.py — modified
from config.settings import settings
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry, get_tool_registry
from services.agent.tools.retrieve import (  # noqa: F401
    RefinedRetrieveTool, RetrieveTool, retrieve_impl,
)
from services.agent.tools.web_search import WebSearchTool  # noqa: F401

if settings.recall_tool_enabled:
    from services.agent.tools.recall import RecallTool  # noqa: F401
```

### Pattern 4: Idempotent backfill (MEM-07)

**What:** Async CLI script with `WHERE embedding IS NULL` cursor, chunked-commit 100 rows/txn, whole-batch rollback on failure with non-zero exit.
**When:** One-shot operational scripts that may be re-run after partial failure.
**Example skeleton:**
```python
# scripts/backfill_fact_embeddings.py — high-level skeleton (planner expands)
import argparse, asyncio, sys
from loguru import logger
from services.memory.memory_service import LongTermMemory
from services.vectorizer.embedder import get_embedder

async def backfill(batch_size: int, dry_run: bool, resume_from_id: str | None) -> int:
    mem = LongTermMemory()
    pool = await mem._get_pool()   # inherits register_vector codec
    embedder = get_embedder()

    where_extra = "AND id > $2" if resume_from_id else ""
    total = 0
    while True:
        async with pool.acquire() as conn:
            sql = (
                f"SELECT id, fact FROM long_term_facts "
                f"WHERE embedding IS NULL {where_extra} "
                f"ORDER BY id LIMIT $1"
            )
            args: list = [batch_size]
            if resume_from_id:
                args.append(resume_from_id)
            rows = await conn.fetch(sql, *args)
        if not rows:
            break
        texts = [r["fact"] for r in rows]
        if dry_run:
            # token estimate: ~40 tokens/fact (D-D4 cost formula)
            est_tokens = sum(len(t) // 4 for t in texts)
            logger.info(f"Would embed {len(texts)} facts (~{est_tokens} tokens)")
            return 0
        try:
            vectors = await embedder.embed_batch(texts)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for row, vec in zip(rows, vectors):
                        await conn.execute(
                            "UPDATE long_term_facts SET embedding=$1::vector "
                            "WHERE id=$2",
                            vec, row["id"],
                        )
            total += len(rows)
            logger.info(f"backfilled batch: count={len(rows)} total={total}")
        except (RuntimeError, OSError, Exception) as exc:  # planner: narrow this
            logger.error(f"batch failed; rollback complete: {exc!r}")
            return 1
    return 0

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--resume-from-id", type=str, default=None)
    args = parser.parse_args()
    exit_code = asyncio.run(backfill(args.batch_size, args.dry_run, args.resume_from_id))
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
```

### Pattern 5: MEM-10 audit shape — length regression + token delta

**What:** Integration test reads `MemoryContext.long_term_facts` returned at each of the 4 `load_context` call sites, asserts `len(ctx.long_term_facts) <= settings.recall_top_k_default` (default 5), and writes mean/p95 token delta vs popularity baseline to a phase audit artifact (`.planning/phases/24-*/24-MEM10-AUDIT.json` or similar).
**When:** Phase ships a semantic shift to an existing contract — must prove no rowcount-shape regression even though the contents change.
**Anti-pattern:** Snapshot test against pre-shift `long_term_facts` strings — wrong test; the contract is *length-bounded list of str*, NOT *exact string match to popularity baseline*. Per D-B3.

### Anti-Patterns to Avoid

- **Hand-rolling the cosine-similarity SQL outside an `async with conn.transaction()` block** — `SET LOCAL` becomes a no-op; ef_search defaults to 40; SC-3 p95 SLA at 10k rows likely fails silently.
- **Building a separate asyncpg pool for the backfill script without `init=_init_conn` callback** — pgvector codec not registered → `UPDATE … SET embedding=$1::vector` binds the list as TEXT and pgvector REJECTS the row. Reuse `LongTermMemory._get_pool()` instead.
- **Letting RecallTool exceptions propagate** — violates D-C3; planner LLM may interpret the failure as "tool returned no result" and retry, burning quota. Wrap in `try/except (asyncpg.PostgresError, httpx.HTTPError, RuntimeError, OSError)` and return `is_error=True` ToolResult.
- **Registering RecallTool in `__init__.py` unconditionally** — defeats the D-B4 kill-switch. Guard the import with `if settings.recall_tool_enabled:`.
- **Adding `embedding <=> $query < threshold` to the WHERE clause** — violates D-A3; the eval gate (SC-1) tests cosine quality offline. No threshold guesswork at runtime.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cosine similarity computation | Custom numpy cosine + Python sort | `embedding <=> $query::vector` operator + `ORDER BY … LIMIT $k` | pgvector executes inside the HNSW-indexed B-tree; Python-side is O(N×D) memory + zero index acceleration |
| Tool registration scaffolding | Manual registry dict + key insertion | `@get_tool_registry().register` decorator | Decorator handles duplicate-name detection (registry.py:39-41); idempotent across imports |
| Query embedding | Re-embed inside RecallTool from scratch | `get_embedder().embed_one(query)` (BatchedEmbedder.embed_one) | Already has tenacity retry + provider-neutral adapter |
| Backfill resume / cursor state | Checkpoint file + custom serialization | `WHERE embedding IS NULL` cursor in SQL | Idempotent by data state; no operational file to manage |
| Backfill rate limiting | Custom asyncio.Semaphore + sleep | Tenacity already in `OpenAIEmbedder.embed_batch` (embedder.py:84) for 429s | Layering rate limiter on top of tenacity-retry causes compound backoff — already noted in Phase 21/23 RESEARCH |
| Kill-switch state machine | Multi-state enum + runtime branching | Bool + conditional import | Phase 23 `extractor_enabled` precedent — simplest viable |

**Key insight:** This phase is overwhelmingly about *wiring* existing infrastructure (embedder, pool, registry, tool ABC) together. There is no novel infra. The risk surface is alignment with locked decisions (D-A1..D-D4) and avoidance of the 7 pitfalls below.

## Runtime State Inventory

> Not applicable in the classic rename/refactor sense — Phase 24 introduces a new feature surface, not a rename. But two state items deserve explicit acknowledgement:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `long_term_facts.embedding` column rows where embedding IS NULL (pre-Phase-23 rows + any rows where `save_fact` ran when embedder was unavailable) | Run `scripts/backfill_fact_embeddings.py` once after Phase 24 deploy |
| Live service config | `settings.recall_tool_enabled` env var (new) | Default True; document in deploy notes / `docs/memory-eviction.md` companion section |
| OS-registered state | None | None — verified by checking that no OS task scheduler, cron, systemd unit references long_term_facts or recall_memory |
| Secrets / env vars | None new | `EMBEDDING_PROVIDER` already configured for Phase 23; same model reused at recall time |
| Build artifacts | None | None — no compiled binaries or package egg-info changes |

## Common Pitfalls

### Pitfall 1: pgvector codec NOT registered on RecallTool pool acquire path

**What goes wrong:** `$3::vector` binding silently treats the list as TEXT, INSERT/SELECT raises pgvector dim-mismatch or "invalid input syntax for type vector". Specifically: when `register_vector` is not called on the connection, asyncpg has no codec for the `vector` type, so passing `list[float]` becomes a TEXT-cast attempt.

**Why it happens:** asyncpg requires per-connection type codec registration. Phase 23 added the `init=_init_conn` callback to `LongTermMemory._get_pool` (memory_service.py:150-158) precisely to fix this for `save_fact`. **Verified [VERIFIED 2026-05-16]:** the callback IS in place post-Phase-23 — `register_vector` runs on every connection the recall query acquires.

**How to avoid:** Confirm the recall SELECT acquires its connection from the same `_get_pool()` that registers the codec. Backfill script: reuse `LongTermMemory._get_pool()` rather than constructing a standalone asyncpg pool.

**Warning signs:** SQL error mentioning `invalid input syntax for type vector` or `column "embedding" is of type vector but expression is of type text[]`. Or: query returns zero rows despite known seed data — pgvector silently fails to bind, runs SELECT with a "garbage" vector, no rows match.

**Verification:** Add a unit test that asserts `_get_pool`'s `init` callback is non-None AND calls `register_vector`. The Phase 23 PR added `tests/unit/test_memory_pool.py::test_register_vector_init` for exactly this — extend it or rely on it as a regression gate.

### Pitfall 2: `SET LOCAL hnsw.ef_search` outside an explicit transaction silently no-ops

**What goes wrong:** `conn.execute("SET LOCAL hnsw.ef_search = 200")` runs in asyncpg's implicit auto-commit mode (one statement = one transaction). The setting takes effect for that single statement, then the transaction ends, then the SELECT runs in a brand-new transaction at default `ef_search=40`. Result: recall correctness regresses to default HNSW behavior; SC-3 p95 SLA may pass at 10k rows by accident but fails at 100k.

**Why it happens:** Postgres `SET LOCAL` is documented to scope to "the current transaction" [CITED: postgresql.org docs SET LOCAL] [ASSUMED — not confirmed against PG version-specific behavior in this tree]. asyncpg `conn.execute` is auto-commit unless wrapped in `async with conn.transaction()`. The existing `vector_store.py:312` filter path DOES wrap in `async with conn.transaction()` — that's why it works.

**How to avoid:** Wrap the recall SQL block as:
```python
async with pool.acquire() as conn:
    async with conn.transaction():  # ← REQUIRED
        await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
        await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")
        rows = await conn.fetch(...)
```

**Warning signs:** Recall returns valid-looking results that don't exactly match the offline cosine ranking (because ef_search=40 truncates the HNSW candidate set). SC-1 eval gate may pass on a small fixture but fail at scale.

**Verification:** Add `tests/unit/test_memory_recall_semantic.py::test_get_relevant_facts_uses_transaction` that monkeypatches `asyncpg.Connection.transaction` and asserts it was entered. (Or a stronger test: instrument the pool's `init` to log `SET LOCAL` statement effective scope — likely overkill.)

### Pitfall 3: `MemoryContext.long_term_facts` type drift if RecallTool surfaces formatted bullets back into `load_context`

**What goes wrong:** D-C1 commits to bulleted plain text **inside the RecallTool ToolResult.content** — NOT inside `MemoryContext.long_term_facts`. The `MemoryContext.long_term_facts: list[str]` shape (memory_service.py:69) MUST remain a list of bare fact strings. If a downstream change attempts to "pre-format" the list inside `get_relevant_facts` (e.g., return `["- fact1", "- fact2"]`), the v1.0-v1.5 consumers that join with `", "` or iterate as raw facts will silently break.

**Why it happens:** Confusion between RecallTool output formatting (bullets, per D-C1) and the underlying `get_relevant_facts` return shape (raw `list[str]`, per memory_service.py:284). Phase 24 changes WHAT is in the list (query-relevant facts vs popularity-ranked), not the LIST SHAPE.

**How to avoid:** Keep `get_relevant_facts` returning `[r["fact"] for r in rows]` — bare strings. RecallTool does the bullet formatting at the ToolResult boundary only.

**Warning signs:** Audit failures or downstream synthesizer-prompt diffs that show `- ` prefixes inside `long_term_facts` content.

**Verification:** Type assertion in `test_memory_recall_semantic.py::test_returns_bare_strings` — assert no element starts with `"- "` or `"* "`.

### Pitfall 4: RecallTool registration import-order or duplicate-name collision

**What goes wrong:** `ToolRegistry.register` raises `ValueError(f"Tool {cls.name!r} already registered")` (registry.py:39-41). If two import paths reach `recall.py` (e.g., one direct + one via `services.agent.tools`), the second import's decorator re-execution raises. Or: name typo `"recall_memory"` vs `"recall_memories"` causes the planner's `AGENT_TOOL_ALLOWLIST` filter at registry.py:78 to silently drop the tool — planner never sees it.

**Why it happens:** Module-import-time decorators run side-effectfully. Python module caching prevents the duplicate-call case for module-level imports (verified [VERIFIED 2026-05-16]: existing RetrieveTool/WebSearchTool register at `__init__.py:15-20` exactly once across the package). Conditional import (`if settings.recall_tool_enabled`) does NOT trigger duplicate registration even if `__init__.py` is reloaded — Python's `sys.modules` cache prevents re-execution.

**How to avoid:** Single import path: `from services.agent.tools.recall import RecallTool` inside `services/agent/tools/__init__.py` (conditional-guarded). Never import `recall.py` from anywhere else (no `pipeline.py` or `executor.py` direct import). Use exactly the string `"recall_memory"` everywhere (search-and-confirm across allowlist + integration test + tool description).

**Warning signs:** `ValueError: Tool 'recall_memory' already registered` at startup, OR planner integration test fails because `registry.schemas_for("anthropic", names=["recall_memory"])` returns an empty schema list.

**Verification:** Add `tests/unit/test_recall_tool.py::test_registered_exactly_once` — assert `get_tool_registry().list().count("recall_memory") == 1`.

### Pitfall 5: `Embedder.embed_one` availability across providers — verified GOOD

**What goes wrong (theoretical):** Backfill or recall-time query embedding fails on HuggingFace or Ollama because `embed_one` is OpenAI-only.

**Verified [VERIFIED 2026-05-16]:** `BaseEmbedder.embed_one` is defined on the abstract base at `embedder.py:32-34` as `await self.embed_batch([text])`. ALL three providers (OllamaEmbedder, OpenAIEmbedder, HuggingFaceEmbedder) implement `embed_batch`. `BatchedEmbedder` (the wrapper returned by `get_embedder()`) also implements `embed_one` at `embedder.py:152-154`. EnsembleEmbedder same (line 218-220). **No provider-specific gap.**

**How to avoid:** Use `get_embedder().embed_one(query)` — no provider branching needed.

**Warning signs:** `AttributeError: 'XxxEmbedder' object has no attribute 'embed_one'`. Would only occur if a new provider is added without subclassing `BaseEmbedder`. Coverage-gate (per-module ≥ 70%) on `embedder.py` is the existing safety net.

### Pitfall 6: load_context regression at the 4 call sites

**What goes wrong:** A subtle behavior shift in `_long.get_relevant_facts` that returns more than K facts (because the rewrite forgets to honor `limit` parameter) breaks the `len(ctx.long_term_facts) <= 5` invariant assumed by `_build_initial_messages` at all 4 sites. Or: rewrite returns an empty list on legitimate query (silent embedder failure) — `load_context.long_term_facts` becomes `[]` and downstream prompts lose context.

**Why it happens:** The popularity SQL had a single `LIMIT $3` clause and a simple `ORDER BY`. The semantic rewrite has an `ORDER BY embedding <=> $3::vector, importance, created_at` + `LIMIT $4` — easy to mis-thread parameter indices. Also: `MemoryService.load_context` swallows exceptions via `asyncio.gather(..., return_exceptions=True)` (memory_service.py:404) — a `get_relevant_facts` exception becomes `[]` silently.

**How to avoid:** MEM-10 audit covers this via length-only regression at all 4 call sites. Add explicit `assert len(facts) <= limit` at end of `get_relevant_facts` (defensive — pgvector LIMIT should suffice but the assertion is cheap). Add explicit unit test for embedder-failure path: `get_relevant_facts` returns `[]`, NOT raises.

**Warning signs:** Snapshot-based prompt tests in v1.0-v1.5 fail not because the WORDS changed but because the LIST SIZE changed.

**Verification:** Phase 24 ships `tests/integration/test_pipeline_load_context_audit.py` (MEM-10 SC-5). Existing v1.0-v1.5 suite re-run pre-merge.

### Pitfall 7: Backfill atomicity — partial UPDATE on whole-batch rollback

**What goes wrong:** Backfill UPDATE loop inside a single `conn.transaction()` either commits ALL rows in the batch or NONE. If the loop raises after row 47 of 100, the txn rolls back; row 47 is the same as rows 0-99 — embedding still NULL. Re-running the script picks up at the same point (via `WHERE embedding IS NULL`). Good.

**Where it could go wrong:** If the planner forgets the `conn.transaction()` wrap around the UPDATE loop, asyncpg auto-commits each statement. Row 0-46 persist, row 47+ skipped, next run picks up at 47 — superficially correct, but the script's "exit non-zero" semantics no longer signal a meaningful rollback boundary (D-D3 requires whole-batch rollback).

**How to avoid:** The skeleton in Pattern 4 wraps the UPDATE loop in `async with conn.transaction():`. Add `tests/unit/test_backfill_fact_embeddings.py::test_batch_rollback_on_failure` that monkeypatches the embedder to raise on the 47th call and asserts ROW COUNT in long_term_facts where embedding IS NOT NULL is unchanged.

**Warning signs:** Re-runs of the backfill script after a failure show non-monotonic embedding-coverage progression (some rows in the failed batch ARE populated, others are not).

**Verification:** Unit test as above + manual operator run on a 1k-row staging seed with deliberate injected failure.

## Code Examples

> Verified-against-tree skeletons. Source citations inline.

### `LongTermMemory.get_relevant_facts` rewrite (MEM-06)

```python
# Source pattern: services/vectorizer/vector_store.py:311-340
# REPLACES: services/memory/memory_service.py:270-287 (popularity SELECT)
async def get_relevant_facts(
    self, user_id: str, tenant_id: str, query: str, limit: int = 5
) -> list[str]:
    """检索用户的长期记忆中与当前查询相关的事实（语义相似度排序）。

    Phase 24 / MEM-06 — rewrites the popularity-ranked v1.0 path to
    pgvector cosine similarity under HNSW iterative_scan = strict_order
    (D-A1). Tie-break: importance DESC, created_at DESC (ROADMAP literal).
    """
    from config.settings import settings
    from services.vectorizer.embedder import get_embedder
    import httpx

    # Step 1: embed the query (provider-neutral via BatchedEmbedder).
    try:
        q_vec: list[float] = await get_embedder().embed_one(query)
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        logger.error(
            "memory service failure",
            operation="get_facts_embed",
            exc_info=exc,
        )
        return []

    # Step 2: HNSW filtered recall inside explicit transaction (Pitfall 2).
    try:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                ef = int(
                    getattr(settings, "pgvector_ef_search_filtered", 200)
                )
                await conn.execute(
                    "SET LOCAL hnsw.iterative_scan = 'strict_order'"
                )
                # ef is a trusted int from settings — int() cast is the only
                # safe f-string surface (T-08-01 precedent in vector_store.py:326).
                await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")

                rows = await conn.fetch(
                    """SELECT fact FROM long_term_facts
                       WHERE user_id=$1 AND tenant_id=$2
                       ORDER BY embedding <=> $3::vector,
                                importance DESC,
                                created_at DESC
                       LIMIT $4""",
                    user_id, tenant_id, q_vec, limit,
                )
        return [r["fact"] for r in rows]
    except asyncpg.PostgresError as exc:
        logger.error(
            "memory service failure",
            operation="get_facts_semantic",
            exc_info=exc,
        )
        return []
```

### `RecallTool` complete implementation (MEM-08)

```python
# Source: services/agent/tools/web_search.py:208-307 shape (BaseTool subclass)
"""RecallTool — pgvector cosine-similarity recall via LongTermMemory (Phase 24, MEM-08)."""
from __future__ import annotations
import time
from typing import Any, ClassVar

import asyncpg
import httpx
from loguru import logger

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from services.memory.memory_service import get_memory_service
from utils.models import ToolContext, ToolResult

_RECALL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

_RECALL_RUNTIME_ERRORS = (
    asyncpg.PostgresError,
    httpx.HTTPError,
    RuntimeError,
    OSError,
)

_EMPTY_MARKER = "No matching facts found."
_ERROR_MARKER = "Memory unavailable; proceed without recall."


@get_tool_registry().register
class RecallTool(BaseTool):
    """recall_memory — pgvector cosine recall over long_term_facts."""

    name: ClassVar[str] = "recall_memory"
    description: ClassVar[str] = (
        "Recall durable facts the agent has previously learned about this user. "
        "Call when the query references prior context, preferences, or recurring "
        "topics. Skip when conversation pivots to a new topic."
    )
    parameters_schema: ClassVar[dict[str, Any]] = _RECALL_PARAMETERS_SCHEMA

    async def run(
        self,
        args: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        t0 = time.perf_counter()
        a = args or {}
        query_str = (a.get("query") or ctx.req.query or "").strip()
        user_id = getattr(ctx.req, "user_id", "")
        tenant_id = getattr(ctx.req, "tenant_id", "")

        # Auth precondition: missing IDs → empty marker (NOT an error).
        if not user_id or not tenant_id or not query_str:
            return ToolResult(
                content=_EMPTY_MARKER,
                metadata={
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "reason": "missing_user_or_tenant_id",
                },
            )

        try:
            mem = get_memory_service()
            facts = await mem._long.get_relevant_facts(
                user_id, tenant_id, query_str, limit=5,
            )
        except _RECALL_RUNTIME_ERRORS as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            logger.error(f"[RecallTool] failed: {exc!r}")
            return ToolResult(
                content=_ERROR_MARKER,
                metadata={"latency_ms": latency_ms, "error": True},
                is_error=True,
            )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        if not facts:
            return ToolResult(
                content=_EMPTY_MARKER,
                metadata={
                    "latency_ms": latency_ms,
                    "fact_count": 0,
                    "query": query_str,
                },
            )

        return ToolResult(
            content="- " + "\n- ".join(facts),
            metadata={
                "latency_ms": latency_ms,
                "fact_count": len(facts),
                "query": query_str,
            },
        )
```

### Allowlist edit (MEM-09)

```python
# services/pipeline.py:744 — modify in place
AGENT_TOOL_ALLOWLIST: list[str] = [
    "search_knowledge_base",
    "refine_search",
    "web_search",
    "recall_memory",   # Phase 24 / MEM-09 — pgvector recall via RecallTool
]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Popularity-ranked `ORDER BY importance DESC, created_at DESC` recall | Cosine-similarity `ORDER BY embedding <=> $q::vector` + tie-break on importance/created_at | Phase 24 (this) | Query-relevance over recency; matches RAG retrieval paradigm; SC-1 eval gate validates quality |
| Default HNSW `ef_search=40` | Tuned `SET LOCAL hnsw.ef_search = 200` inside explicit txn | v1.1 Phase 8 chunks path; Phase 24 mirrors for facts | Higher recall accuracy under WHERE prefilter; ~15-20% latency increase [ASSUMED — figure not measured in this tree] |
| `iterative_scan` not set (sequential scan fallback on filtered HNSW) | `SET LOCAL hnsw.iterative_scan = 'strict_order'` | Phase 24 (D-A1) | Walks HNSW until top-k filter-matches found; strict_order guarantees exact ranking under prefilter; ~10-30% slower than relaxed_order [ASSUMED — benchmark figures not measured in this tree] |

**Deprecated/outdated:**
- The popularity SQL at memory_service.py:278-283 — entirely replaced. Old `LIMIT $3` parameter index becomes `LIMIT $4` (q_vec is $3); planner must verify parameter indexing.

## Assumptions Log

> Claims tagged `[ASSUMED]` that need eng-review verification before plan acceptance. Each item is a concrete, verifiable contract or numeric — not a generic risk.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `SET LOCAL` GUC scope is bounded by `async with conn.transaction()` such that statements following the `SET LOCAL` within the same transaction inherit the setting, and statements outside it revert to session/default. [Verified against PostgreSQL `SET LOCAL` documentation but NOT empirically tested in this tree's asyncpg + pgvector combination.] | Pitfall 2 + Pattern 1 | If wrong: `ef_search` is silently 40, SC-3 p95 SLA degrades; mitigation: explicit unit test `tests/unit/test_memory_recall_semantic.py::test_ef_search_in_effect_during_select` that EXPLAIN-checks the executed plan |
| A2 | `strict_order` latency penalty vs `relaxed_order` is ~10-30%. Sourced from generic HNSW literature, NOT measured against this codebase's pgvector version, data distribution, or `pgvector_ef_search_filtered=200` setting. | D-A1 + State of the Art | If wrong by >2x: SC-3 (<50ms p95 @ 10k rows) may fail; mitigation: manual benchmark on staging tenant before merge — `scripts/bench_recall_latency.py` (not in scope but operator-runnable) |
| A3 | The cost formula `OpenAI text-embedding-3-large @ $0.13/1M tokens × ~40 tokens/fact ≈ $5.2/M facts` (CONTEXT D-D4) uses a fact-length estimate not measured against actual `long_term_facts` row distribution. | D-D4 | If wrong: cost docs in `docs/memory-eviction.md` mislead operators; mitigation: `--dry-run` flag prints actual token estimate before charge |
| A4 | The kill-switch implementation via **conditional import** in `services/agent/tools/__init__.py` is the right shape (vs runtime branch in `RecallTool.run` or runtime branch in pipeline). Discretion item — D-B4 locks the BEHAVIOR ("not registered when False") but not the IMPLEMENTATION mechanism. | Pattern 3 + Claude's Discretion table | If eng-review prefers runtime-branch: minor refactor, no requirement-level impact |
| A5 | `MemoryService` does not currently expose a `get_relevant_facts` passthrough on the OUTER service (only on `._long`). RecallTool reaches `mem._long.get_relevant_facts(...)` — uses private attribute. [Verified: memory_service.py:385-449 shows MemoryService has no such passthrough method.] Discretion item — planner may add a public passthrough for cleanliness. | Claude's Discretion table | If eng-review prefers public passthrough: add `MemoryService.get_relevant_facts(self, user_id, tenant_id, query, limit=5)` that delegates; <5 LOC change |
| A6 | The recall path's exception classes `(asyncpg.PostgresError, httpx.HTTPError, RuntimeError, OSError)` cover all real failure modes from `get_embedder().embed_one(query)` + `_long.get_relevant_facts(...)`. Inferred from existing `save_fact` rewrite at memory_service.py:303-313 + WebSearchTool / RetrieveTool error sets. Not exhaustively reviewed for HuggingFaceEmbedder torch / sentence-transformers exception paths. | Code Example §RecallTool | If wrong: an unhandled exception kind propagates and breaks the user turn; mitigation: integration test that monkeypatches embedder to raise various exception types |
| A7 | Backfill script reusing `LongTermMemory._get_pool()` will share connection pool with the production service if the script runs in-process (which it doesn't — it's a standalone CLI). Standalone CLI invocation creates a fresh `LongTermMemory()` instance with its own pool, so no contention. [Verified: `LongTermMemory.__init__` at line 143 creates fresh `self._pool = None`; pool is per-instance, not module-global.] | Backfill skeleton (Pattern 4) | Negligible — if wrong, backfill competes with prod for pool slots; mitigation: backfill is operator-run during maintenance window |

## Open Questions

> Phase 24 CONTEXT.md is comprehensive — all major decisions locked. Two minor items remain Claude-discretion (handled in the Discretion table above) and are NOT open questions for the planner.

1. **None substantive.** All 4 areas (A through D) and all 4 sub-decisions within each area are locked. The Discretion table addresses the small implementation choices the planner needs to make. No /plan-eng-review escalation expected unless the Assumptions Log items above surface unexpected drift during plan-checker review.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL + pgvector extension | MEM-06 recall path + MEM-07 backfill | ✓ | Postgres 15.x + pgvector ≥ 0.5 (verified by Phase 1 + Phase 23 deployment) | None — hard requirement |
| `asyncpg` Python package | Recall + backfill | ✓ | Pinned in pyproject.toml | None |
| `pgvector.asyncpg` (codec) | `register_vector` callback | ✓ | Pinned | None |
| `loguru` | Structured logging | ✓ | Pinned | None |
| `pydantic` V2 | `ToolResult` / `ToolContext` | ✓ | Pinned | None |
| Embedding provider (Ollama / OpenAI / HuggingFace) | Query embedding + backfill | ✓ | Phase 23 deployed; same model reused | Backfill --dry-run produces cost estimate without API calls |
| `uv` CLI | Run backfill via `uv run python scripts/backfill_fact_embeddings.py` | ✓ | Project default per CLAUDE.md | None |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio ≥ 1.3.0 (verified pyproject.toml:35-37) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) + `tests/conftest.py` |
| Quick run command | `uv run pytest tests/unit/ -x -q` |
| Full suite command | `uv run pytest --cov --cov-report=xml -p no:cacheprovider` |
| Estimated runtime | ~45 seconds (unit) / ~3 minutes (full) — matches Phase 23 envelope |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MEM-06 | `get_relevant_facts` runs SET LOCAL inside txn + cosine ORDER BY | unit (DDL+EXPLAIN) | `uv run pytest tests/unit/test_memory_recall_semantic.py::test_ef_search_in_effect -x` | ❌ Wave 0 |
| MEM-06 | Returns bare `list[str]`, length ≤ limit, query-relevance ordering on seeded data | unit | `uv run pytest tests/unit/test_memory_recall_semantic.py::test_returns_bare_strings_sorted_by_cosine -x` | ❌ Wave 0 |
| MEM-06 | Embedder failure → returns `[]`, does NOT raise | unit | `uv run pytest tests/unit/test_memory_recall_semantic.py::test_embedder_failure_returns_empty -x` | ❌ Wave 0 |
| MEM-07 | Backfill: idempotent — second run hits zero embedding API calls | unit | `uv run pytest tests/unit/test_backfill_fact_embeddings.py::test_idempotent_second_run -x` | ❌ Wave 0 |
| MEM-07 | Backfill: whole-batch rollback on mid-batch failure, exit non-zero | unit | `uv run pytest tests/unit/test_backfill_fact_embeddings.py::test_batch_rollback_on_failure -x` | ❌ Wave 0 |
| MEM-07 | Backfill: `--dry-run` prints estimate, exits 0, no API calls | unit | `uv run pytest tests/unit/test_backfill_fact_embeddings.py::test_dry_run_no_api_calls -x` | ❌ Wave 0 |
| MEM-08 | RecallTool class-vars enforced; `run()` returns `ToolResult` with bullets | unit | `uv run pytest tests/unit/test_recall_tool.py::test_happy_path_bullets -x` | ❌ Wave 0 |
| MEM-08 | Empty result returns `"No matching facts found."` marker | unit | `uv run pytest tests/unit/test_recall_tool.py::test_empty_marker -x` | ❌ Wave 0 |
| MEM-08 | Best-effort error: catches `(PostgresError, HTTPError, RuntimeError, OSError)` → `is_error=True` | unit | `uv run pytest tests/unit/test_recall_tool.py::test_error_isolation -x` | ❌ Wave 0 |
| MEM-08 | Missing user_id or tenant_id returns empty marker (NOT error) | unit | `uv run pytest tests/unit/test_recall_tool.py::test_missing_auth_returns_empty -x` | ❌ Wave 0 |
| MEM-09 | `recall_memory` in `AGENT_TOOL_ALLOWLIST`; registry returns RecallTool class | unit | `uv run pytest tests/unit/test_recall_tool.py::test_registered_in_allowlist -x` | ❌ Wave 0 |
| MEM-09 | `settings.recall_tool_enabled=False` → tool NOT registered (conditional import) | unit | `uv run pytest tests/unit/test_settings_recall_kill_switch.py::test_disabled_skips_registration -x` | ❌ Wave 0 |
| MEM-09 | Planner picks `recall_memory` for preference-query; SKIPS for unrelated query | integration | `uv run pytest tests/integration/test_recall_tool_planner_pick.py -x` | ❌ Wave 0 |
| MEM-10 | At each of 4 call sites: `len(ctx.long_term_facts) <= 5` preserved | integration | `uv run pytest tests/integration/test_pipeline_load_context_audit.py -x` | ❌ Wave 0 |
| MEM-10 | Token-delta artifact written: mean / p95 vs popularity baseline | integration | `uv run pytest tests/integration/test_pipeline_load_context_audit.py::test_writes_token_delta_artifact -x` | ❌ Wave 0 |
| SC-1 | Offline eval: "what frontend framework do I prefer?" recalls "React" fact at cosine > 0.7 | integration (offline-eval) | `uv run pytest tests/integration/test_recall_offline_eval.py -x` | ❌ Wave 0 |
| SC-3 | 10k-row seeded recall p95 < 50ms with `strict_order` + tuned ef_search | integration (bench, manual-only) | manual — `scripts/bench_recall_latency.py` (out of automated CI) | manual |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit/ -x -q` (~45s)
- **Per wave merge:** `uv run pytest --cov --cov-report=xml -p no:cacheprovider` (full ~3min)
- **Phase gate:** Full suite green; diff-cover ≥ 80% on touched files; per-module ≥ 70% on `services/agent/tools/recall.py` + `services/memory/memory_service.py` + `scripts/backfill_fact_embeddings.py`; v1.0-v1.5 suite still green (MEM-10 SC-5)

### Wave 0 Gaps

- [ ] `tests/unit/test_memory_recall_semantic.py` — stubs for MEM-06 (txn wrap, SET LOCAL verification, bare-strings + ordering, embedder-failure-empty)
- [ ] `tests/unit/test_recall_tool.py` — stubs for MEM-08 + MEM-09 (happy path, empty marker, error isolation, missing-auth, registered-in-allowlist)
- [ ] `tests/unit/test_backfill_fact_embeddings.py` — stubs for MEM-07 (idempotent, batch rollback, dry-run, resume-from-id)
- [ ] `tests/unit/test_settings_recall_kill_switch.py` — stubs for D-B4 conditional registration
- [ ] `tests/integration/test_recall_tool_planner_pick.py` — planner integration: picks for preference query, skips for unrelated
- [ ] `tests/integration/test_pipeline_load_context_audit.py` — MEM-10 4-call-site length regression + token delta artifact
- [ ] `tests/integration/test_recall_offline_eval.py` — SC-1 cosine quality fixture (React-preference seed)
- [ ] `tests/conftest.py` — extend with `recall_tool_pool`, `memory_pool_with_seeds`, `planner_with_recall_tool` fixtures

*(Framework install: not needed — pytest+asyncio+cov already in pyproject.toml)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no — auth precondition (user_id/tenant_id presence) handled by Phase 23 dispatch wrapper precedent; RecallTool inherits via `ctx.req.user_id` set upstream | — |
| V3 Session Management | no | — |
| V4 Access Control | partial — user_id+tenant_id WHERE prefilter is the access boundary; RLS on `long_term_facts` is the v1.0 Phase 2 carry-forward TODO (out of v1.6 scope; documented). RecallTool MUST NOT recall facts across users or across tenants within same query | WHERE-clause prefilter + future RLS |
| V5 Input Validation | yes | `parameters_schema` JSON-Schema validated at planner-LLM tool-call boundary (Anthropic / OpenAI / Ollama tool-use SDK enforcement); query string passed verbatim into `embed_one` (no SQL string interpolation — parameterized via `$3::vector`) |
| V6 Cryptography | no | — |

### Known Threat Patterns for {pgvector + agent-runtime tool}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via query text | Tampering | Parameterized `conn.fetch` with `$N` placeholders; ef_search uses `int()` cast in f-string (T-08-01 precedent at vector_store.py:326) |
| Cross-tenant data leak (recall returns another tenant's facts) | Information disclosure | `WHERE user_id=$1 AND tenant_id=$2` filter on every SELECT; integration test asserts no leak across tenant_id values |
| Embedding adapter exhaustion (DoS via recall flood) | Denial of Service | Tenacity already in place on `embed_batch`; planner-LLM tool-call rate-limit is the upstream control; v1.6 accepts this |
| RecallTool failure cascading to user response | Denial of Service | D-C3 best-effort isolation: caught exception → `is_error=True` ToolResult with explanatory content; user turn proceeds |
| Backfill script credential exposure | Information disclosure | Script reads `settings` (env-driven) — no inline secrets; standard ops practice |
| Planner LLM hallucinating recall results when tool errored | Tampering (model-level) | Explicit "No matching facts found." vs "Memory unavailable; proceed without recall." marker (D-C2 / D-C3) — planner sees the error kind and re-plans accordingly |

## Sources

### Primary (HIGH confidence)

- `services/memory/memory_service.py:1-459` — full file read 2026-05-16; current `get_relevant_facts` body at 270-287; `_get_pool` `register_vector` callback at 150-158; `save_fact` rewrite at 289-326; `load_context` at 396-417; `MemoryContext` at 62-71
- `services/vectorizer/vector_store.py:300-340` — HNSW filtered-recall pattern source; verified `SET LOCAL hnsw.iterative_scan = 'relaxed_order'` + `SET LOCAL hnsw.ef_search = {ef}` inside `async with conn.transaction()`
- `services/agent/tools/base.py` — `BaseTool` ABC with `__init_subclass__` ClassVar enforcement; `_build_error_result` helper
- `services/agent/tools/registry.py` — `ToolRegistry.register` decorator + duplicate-name detection + `schemas_for` provider mapping
- `services/agent/tools/web_search.py` — RecallTool shape mirror; decorator usage; class-vars; `run()` signature; error-result construction (note: WebSearchTool uses inline `_error_result` static method instead of base helper for D-15 redaction reasons — RecallTool can use either; recommend base `_build_error_result` for simplicity)
- `services/agent/tools/retrieve.py` — `ctx.req.query` / `args.get("query")` precedent; `@get_tool_registry().register` usage; narrow-exception tuple pattern (`_RETRIEVE_RUNTIME_ERRORS`)
- `services/agent/tools/__init__.py` — registration via top-level side-effect imports (lines 15-20)
- `services/vectorizer/embedder.py:1-254` — `BaseEmbedder.embed_one` (line 32), all three providers' `embed_batch`, `BatchedEmbedder.embed_one` (line 152), `get_embedder()` factory (line 239)
- `services/pipeline.py:744` — `AGENT_TOOL_ALLOWLIST` literal (3 entries currently); 4 `load_context` call sites at 429, 608, 971, 1062 (verified line numbers vs ROADMAP claim — ROADMAP says 427/606/960/1051; current tree shows 429/608/971/1062; CONTEXT acknowledges the tree positions are authoritative)
- `services/agent/extractor.py:200-246` — `dispatch_extraction` kill-switch precedent for D-B4 (`settings.extractor_enabled` checked first)
- `utils/models.py:206-235, 370-413` — `GenerationRequest` (with `user_id` / `tenant_id` defaulting to `""`), `ToolResult`, `ToolContext` definitions
- `config/settings.py:243, 285-304` — `pgvector_ef_search_filtered = 200`; extractor precedent fields
- `.planning/REQUIREMENTS.md` lines 31-39 — MEM-06 through MEM-10 acceptance bullets
- `.planning/ROADMAP.md` §Phase 24 (lines 45-56) — goal + canonical refs + 5 success criteria
- `.planning/phases/24-pgvector-recalltool-semantic-recall-rewrite/24-CONTEXT.md` + `24-DISCUSSION-LOG.md` — locked decisions D-A1..D-D4
- `.planning/phases/23-background-extractor-schema-migration/23-RESEARCH.md` (sections read) — Phase 23 shape precedent

### Secondary (MEDIUM confidence)

- `vector_store.py:322` precedent uses `'relaxed_order'` — different from Phase 24's locked `'strict_order'` (D-A1 explicit divergence justified by per-tenant rowcount)
- HNSW iterative_scan documentation — `strict_order` vs `relaxed_order` behavior tradeoff documented in pgvector README [VERIFIED conceptually; not URL-fetched in this session]

### Tertiary (LOW confidence)

- HNSW strict_order ~10-30% latency penalty figure [ASSUMED — generic literature; not measured against this tree]
- OpenAI text-embedding-3-large cost ~$0.13/1M tokens [ASSUMED — pricing changes; verify before publishing cost docs in D-D4 section]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every dependency verified in pyproject.toml + Phase 23 already exercised
- Architecture: HIGH — every pattern source verified line-for-line in the working tree
- Pitfalls: HIGH — 7 pitfalls each verified against canonical pattern source + 1 verified-as-OK item (Pitfall 5)
- Assumptions Log: MEDIUM — 7 items explicitly flagged for eng-review; mitigation paths documented

**Pitfall count:** 7 (6 active mitigations + 1 verified-as-OK)
**ASSUMED claims:** 7 (see Assumptions Log)

**Research date:** 2026-05-16
**Valid until:** 2026-06-15 (30 days — stable infrastructure; recheck if Phase 23 schema or v1.6 milestone reshuffles)
