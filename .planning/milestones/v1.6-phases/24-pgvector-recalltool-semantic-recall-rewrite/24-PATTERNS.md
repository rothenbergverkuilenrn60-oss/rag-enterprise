# Phase 24: pgvector RecallTool + semantic recall rewrite — Pattern Map

**Mapped:** 2026-05-16
**Files analyzed:** 13 (3 CREATE source, 1 CREATE-doc, 5 CREATE-test, 4 MODIFY)
**Analogs found:** 13 / 13

## File Classification

| New / Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/memory/memory_service.py::LongTermMemory.get_relevant_facts` (REWRITE) | service / model reader | request-response (embed → pgvector cosine SELECT) | `services/vectorizer/vector_store.py:310-340` (filter-path HNSW recall) | **exact (line-for-line clone with 2 documented swaps)** |
| `services/memory/memory_service.py::LongTermMemory.load_context` (semantic shift, no rewrite) | service composer | request-response (asyncio.gather of 3 reads) | own existing body at `services/memory/memory_service.py:396-417` | exact (no source change — only doc-comment) |
| `services/agent/tools/recall.py` (NEW — RecallTool class) | agent-runtime tool | request-response (tool dispatch) | `services/agent/tools/web_search.py` (307 LOC) + `services/agent/tools/retrieve.py:161-206` (RetrieveTool) | **exact (verbatim clone — body already drafted in RESEARCH §Code Examples)** |
| `services/agent/tools/__init__.py` (registration addition) | package init | module-load (decorator side-effect) | own existing body at `services/agent/tools/__init__.py:15-20` | exact |
| `services/pipeline.py:744` (`AGENT_TOOL_ALLOWLIST` grows 3→4) | controller constant | static config | own existing literal at `services/pipeline.py:744` | exact |
| `config/settings.py` (new field `recall_tool_enabled: bool = True`) | config | config-load | `config/settings.py:296-304` (`extractor_enabled` precedent — Phase 23) | exact |
| `scripts/backfill_fact_embeddings.py` (NEW standalone async CLI) | operational CLI | batch / chunked-commit / cursor | `scripts/ingest_batch.py` (116 LOC — argparse+asyncio.run only); RESEARCH §Pattern 4 skeleton (idempotent UPDATE loop) | **partial** (argparse+asyncio.run shape from ingest_batch.py; chunked-commit + WHERE-IS-NULL cursor + txn-rollback are NEW idioms — no in-tree analog) |
| `docs/memory-eviction.md` (NEW companion doc) | docs | static | `docs/agent-architecture.md` (23.6K) + `docs/DOCKER_DEPLOY.md` (6.3K) for layout | role-match (companion section, no prior in-tree pattern for cost-formula docs) |
| `tests/unit/test_memory_recall_semantic.py` (NEW — MEM-06) | unit test | mock-at-consumer-path (fake pool + embedder) | `tests/unit/test_memory_save_fact.py` (the Phase 23 sibling) | exact |
| `tests/unit/test_recall_tool.py` (NEW — MEM-08/09) | unit test | mock-at-consumer-path (fake registry + memory) | `tests/unit/test_web_search_tool.py` (TestWebSearchToolRegistration shape) + `tests/unit/test_retrieve_tool.py` | exact |
| `tests/unit/test_backfill_fact_embeddings.py` (NEW — MEM-07) | unit test | mock-at-consumer-path (fake pool + embedder) | `tests/unit/test_memory_save_fact.py` (fake-pool harness) | role-match |
| `tests/unit/test_settings_recall_kill_switch.py` (NEW — D-B4) | unit test | importlib reload | (no in-tree analog; precedent shape from `tests/unit/test_memory_pool.py` for module-attr patching) | role-match (importlib.reload idiom — first use in tree) |
| `tests/integration/test_recall_tool_planner_pick.py` + `test_pipeline_load_context_audit.py` (NEW) | integration test | pgvector marker, real PG | `tests/integration/test_pgvector_filtered_recall.py` + `tests/integration/test_pgvector_recall.py` + `tests/integration/test_extractor_e2e.py` | exact |

---

## Pattern Assignments

### 1. `services/memory/memory_service.py::get_relevant_facts` (REWRITE — MEM-06)

**Analog:** `services/vectorizer/vector_store.py:310-340` (filter-path HNSW recall — already used by chunks-table SELECT under WHERE prefilter; the exact precedent CONTEXT D-A1 invokes)

#### Before (current popularity SELECT at `services/memory/memory_service.py:270-287`)

```python
async def get_relevant_facts(
    self, user_id: str, tenant_id: str, query: str, limit: int = 5
) -> list[str]:
    """检索用户的长期记忆中与当前查询相关的事实。"""
    try:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT fact FROM long_term_facts
                   WHERE user_id=$1 AND tenant_id=$2
                   ORDER BY importance DESC, created_at DESC
                   LIMIT $3""",
                user_id, tenant_id, limit,
            )
        return [r["fact"] for r in rows]
    except asyncpg.PostgresError as exc:
        logger.error("memory service failure", operation="get_facts", exc_info=exc)
        return []
```

#### After (Phase 24 rewrite — direct drop-in body)

```python
async def get_relevant_facts(
    self, user_id: str, tenant_id: str, query: str, limit: int = 5
) -> list[str]:
    """检索用户的长期记忆中与当前查询相关的事实（语义相似度排序）。

    Phase 24 / MEM-06 — replaces popularity-ranked v1.0 path with pgvector
    cosine similarity under HNSW iterative_scan='strict_order' (D-A1).
    Tie-break: importance DESC, created_at DESC (ROADMAP literal).

    Failure modes (all return ``[]`` — never raise; load_context relies on
    bare list contract per Pitfall 3):
      - Embedder failure (httpx.HTTPError / RuntimeError / OSError)
      - asyncpg.PostgresError on SELECT
    """
    # Lazy local imports — circular-import resilience per repo convention
    # (mirrors save_fact at memory_service.py:298-301).
    import httpx
    from config.settings import settings
    from services.vectorizer.embedder import get_embedder

    # Step 1 — embed the query (provider-neutral via BatchedEmbedder).
    try:
        q_vec: list[float] = await get_embedder().embed_one(query)
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        # Narrow-exception list (mirrors save_fact at memory_service.py:305):
        #   RuntimeError      — OllamaEmbedder.embed_batch re-raise (embedder.py:68)
        #   httpx.HTTPError   — Ollama + OpenAI transport failures
        #   OSError           — HuggingFace torch device / model-load failures
        logger.error(
            "memory service failure",
            operation="get_facts_embed",
            exc_info=exc,
        )
        return []

    # Step 2 — HNSW filtered recall inside explicit transaction (Pitfall 2).
    try:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Pitfall 2 / Pattern 1: SET LOCAL scopes to current txn ONLY.
                ef = int(
                    getattr(settings, "pgvector_ef_search_filtered", 200)
                )
                await conn.execute(
                    "SET LOCAL hnsw.iterative_scan = 'strict_order'"
                )
                # ef is a trusted int from settings — int() cast is the only
                # f-string surface (T-08-01 precedent vector_store.py:326).
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

#### Explicit swap list vs `vector_store.py:310-340` analog

| `vector_store.py:310-340` (analog) | `get_relevant_facts` rewrite | Swap reason |
|---|---|---|
| `SET LOCAL hnsw.iterative_scan = 'relaxed_order'` (line 322) | `'strict_order'` | D-A1 — facts-per-tenant rowcount smaller; exact recall correctness > latency |
| Tenant-scope GUC `SELECT set_config('app.current_tenant', $1, true)` (line 314-316) | **OMIT entirely** | No RLS on `long_term_facts` in v1.6 (carry-forward TODO from v1.0 Phase 2). User_id + tenant_id WHERE prefilter is the access boundary; no RLS GUC needed. |
| `SELECT chunk_id, doc_id, content, metadata, 1 - (embedding <=> $1::vector) AS score` | `SELECT fact` (single column, no score) | RecallTool consumer needs only the string; score is computed offline by SC-1 eval gate (D-A3 — no runtime threshold) |
| `ORDER BY embedding <=> $1::vector LIMIT $2` (no tie-break) | `ORDER BY embedding <=> $3::vector, importance DESC, created_at DESC LIMIT $4` | ROADMAP literal — facts share rank under cosine, tie-break stabilizes ordering |
| `query_vector` is `$1`, `top_k` is `$2`, filter_params append from `$3+` | Fixed binding: `user_id=$1`, `tenant_id=$2`, `q_vec=$3`, `limit=$4` | No dynamic WHERE — simpler params |
| One try/except wraps embed + pool acquire | Two SEPARATE try blocks (embed first, SELECT second) | Mirrors `save_fact` at memory_service.py:303-313 — embedder failure logged with `operation="get_facts_embed"`, PG failure with `"get_facts_semantic"` (separate ops dashboards) |
| `score: float` returned in VectorSearchResult | Bare `list[str]` returned | Pitfall 3 — `MemoryContext.long_term_facts: list[str]` shape MUST NOT drift |

#### Anti-pattern callouts (what NOT to copy from `vector_store.py`)

- **DO NOT** include the `SELECT set_config('app.current_tenant', $1, true)` line — `long_term_facts` has no RLS in v1.6.
- **DO NOT** add `WHERE 1 - (embedding <=> $q::vector) > $threshold` — D-A3 forbids runtime similarity floor.
- **DO NOT** raise `MemoryFactWriteError` (or any typed exception) on failure — `load_context` at `memory_service.py:404` uses `asyncio.gather(..., return_exceptions=True)`, but Pitfall 6 + D-B3 require the bare `[]` return for length-only regression assertion.
- **DO NOT** hoist `from config.settings import settings` to module top — current convention is lazy local import inside `_create_tables` (line 163) and `_get_pool` (line 148); preserve it.
- **DO NOT** use `relaxed_order` — D-A1 / Open-Question-4 resolution mandates `strict_order`.

---

### 2. `services/memory/memory_service.py::load_context` (no code change — doc-comment only)

**Analog:** own existing body at `services/memory/memory_service.py:396-417` (unchanged).

The semantic shift (popularity → query-relevance) lives entirely inside `get_relevant_facts`. The `load_context` body is preserved verbatim. Only the docstring acquires a Phase 24 / MEM-10 note:

```python
async def load_context(
    self,
    session_id: str,
    user_id:    str,
    tenant_id:  str,
    query:      str,
) -> MemoryContext:
    """加载当前请求所需的全部记忆上下文。

    Phase 24 / MEM-10 — ``long_term_facts`` semantics flip from popularity
    to query-relevance (handled inside ``_long.get_relevant_facts``). The
    LIST SHAPE (``list[str]``, length ≤ 5) is PRESERVED — pipeline call
    sites at services/pipeline.py:429,608,971,1062 see no length regression.
    See ``tests/integration/test_pipeline_load_context_audit.py`` for the
    MEM-10 length-only regression gate + token-delta artifact.
    """
    short_term, long_term_facts, user_profile = await asyncio.gather(
        self._short.get_history(session_id),
        self._long.get_relevant_facts(user_id, tenant_id, query),
        self._long.get_user_profile(user_id, tenant_id),
        return_exceptions=True,
    )
    return MemoryContext(
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        short_term=short_term if isinstance(short_term, list) else [],
        long_term_facts=long_term_facts if isinstance(long_term_facts, list) else [],
        user_profile=user_profile if isinstance(user_profile, UserProfile) else None,
    )
```

**Swap:** Docstring addition only — no executable change.
**Anti-pattern:** DO NOT change the `isinstance(long_term_facts, list)` guard — `asyncio.gather(return_exceptions=True)` may surface a `BaseException`; the guard is the defense.

---

### 3. `services/agent/tools/recall.py` (NEW — RecallTool class, MEM-08)

**Analog:** `services/agent/tools/web_search.py` (307 LOC — exact shape mirror) + `services/agent/tools/retrieve.py:161-206` (RetrieveTool — `ctx.req.query` access pattern, `_RETRIEVE_RUNTIME_ERRORS` tuple convention)

#### Verbatim skeleton (drop-in, ~100 LOC)

```python
"""RecallTool — pgvector cosine-similarity recall via LongTermMemory (Phase 24, MEM-08).

Mirrors the WebSearchTool / RetrieveTool shape (BaseTool subclass with three
ClassVars + async run + @get_tool_registry().register decorator). Reads
``ctx.req.user_id`` / ``ctx.req.tenant_id`` / ``query`` per RetrieveTool
precedent at retrieve.py:181. Best-effort error wrapping (D-C3) — never
raises; recall failure must NOT poison the user-facing turn.

Module-public symbols:
  * ``RecallTool`` — registered tool, BaseTool subclass.
  * ``_RECALL_PARAMETERS_SCHEMA`` — JSON-Schema for the planner LLM (REQUIREMENTS MEM-08 verbatim).
  * ``_RECALL_RUNTIME_ERRORS`` — narrow-exception tuple caught in run().
  * ``_EMPTY_MARKER`` / ``_ERROR_MARKER`` — user-facing content strings (D-C2 / D-C3).
"""

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

# ---------------------------------------------------------------------------
# JSON-Schema for the planner LLM (REQUIREMENTS MEM-08 verbatim)
# ---------------------------------------------------------------------------

_RECALL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

# ---------------------------------------------------------------------------
# Narrow runtime-error tuple (mirrors retrieve.py:151 _RETRIEVE_RUNTIME_ERRORS)
# Catches the union of: pgvector SELECT failures (asyncpg.PostgresError),
# embedder transport (httpx.HTTPError), Ollama re-raise (RuntimeError),
# HuggingFace torch device (OSError). Covers all real failure modes from
# get_embedder().embed_one() + _long.get_relevant_facts().
# ---------------------------------------------------------------------------

_RECALL_RUNTIME_ERRORS = (
    asyncpg.PostgresError,
    httpx.HTTPError,
    RuntimeError,
    OSError,
)

# ---------------------------------------------------------------------------
# User-facing content strings (D-C2 + D-C3 — single source of truth)
# ---------------------------------------------------------------------------

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

        # ── 1. Auth precondition: missing IDs → empty marker (NOT error). ──
        # D-C2 / Pattern 3 — planner sees same content as legitimate empty
        # result; avoids the planner re-trying or hallucinating facts.
        if not user_id or not tenant_id or not query_str:
            return ToolResult(
                content=_EMPTY_MARKER,
                metadata={
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "reason": "missing_user_or_tenant_id",
                },
            )

        # ── 2. Best-effort recall (D-C3 isolation). ────────────────────────
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

        # ── 3. Result shaping (D-C1 bullets + D-C2 empty marker). ──────────
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

#### Explicit swap list vs `web_search.py:208-307` analog

| `web_search.py` (analog) | `recall.py` | Swap reason |
|---|---|---|
| `name = "web_search"` | `name = "recall_memory"` | MEM-09 |
| Multi-line description "Search the public web…" | ROADMAP-verbatim description (D-C4) | Tool surface contract |
| `_WEB_SEARCH_PARAMETERS_SCHEMA` includes `description` on the `query` property | `_RECALL_PARAMETERS_SCHEMA` is the minimal MEM-08 literal (no description) | REQUIREMENTS MEM-08 verbatim |
| `@retry(...)` on `_tavily_search` (3-attempt exponential backoff) | **OMIT entirely** | Embedder + asyncpg already have tenacity wrappers in `embedder.py:84` + provider-side retry. No new retry layer. |
| `get_tavily_client()` lazy singleton + `_tavily_search` retry helper | **OMIT** — call `get_memory_service()._long.get_relevant_facts(...)` directly | Memory singleton already exists at `memory_service.py:454`; no new factory needed |
| `_ERROR_CONTENT: dict[str, str]` with 3 kinds (`tavily_disabled`, `quota_exhausted`, `web_search_failed`) | Two single constants `_EMPTY_MARKER` + `_ERROR_MARKER` (single kind each) | Recall has 2 paths (empty vs error); web_search has 3 typed kinds for planner re-plan steering |
| `_format_results_content(query, chunks)` (multi-line formatter) | Inline `"- " + "\n- ".join(facts)` | D-C1 bullets; no helper needed |
| `_map_tavily_result(result)` (Tavily dict → RetrievedChunk mapper) | **OMIT** — facts return as bare `list[str]` from `get_relevant_facts` | No chunk-shape conversion required |
| `_error_result(kind, latency_ms)` helper + `metadata={"error": True, "kind": kind, ...}` | Inline ToolResult with `metadata={"latency_ms": ..., "error": True}` | Single error kind — no helper needed |
| `is_error=True` ONLY on error paths | Same — `is_error=True` ONLY in `_RECALL_RUNTIME_ERRORS` branch (empty marker is NOT an error per D-C2) | D-C2 — planner must distinguish "tool unreachable" from "no facts found" |

#### Swaps vs `retrieve.py:161-206` analog (secondary reference)

| `retrieve.py:181` | `recall.py` | Why |
|---|---|---|
| `query_str = a.get("query") or ctx.req.query` | `query_str = (a.get("query") or ctx.req.query or "").strip()` | Add `.strip()` defensively (mirrors web_search.py:227) |
| Reads `ctx.tf`, `ctx.retriever`, `ctx.llm` | Reads `ctx.req.user_id`, `ctx.req.tenant_id` ONLY | RecallTool needs auth identifiers, not retriever/llm |
| `_RETRIEVE_RUNTIME_ERRORS = (RuntimeError, ValueError, anthropic.APIError, openai.APIError, httpx.HTTPError, TimeoutError)` | `_RECALL_RUNTIME_ERRORS = (asyncpg.PostgresError, httpx.HTTPError, RuntimeError, OSError)` | Different downstream — recall hits PG + embedder, not LLM APIs |
| Calls `self._build_error_result(exc, latency_ms)` from BaseTool helper | Constructs ToolResult inline | `_build_error_result` echoes exception text into `content` — D-C3 forbids leaking exception detail to planner; use literal `_ERROR_MARKER` instead |

#### Anti-pattern callouts (what NOT to copy)

- **DO NOT** copy `_build_error_result` from `BaseTool` at `services/agent/tools/base.py:59-74` — it echoes `f"[{self.name}] error: {exc}"` into `ToolResult.content`. D-C3 requires the planner see a STABLE literal (`_ERROR_MARKER`), not the exception class name. Use inline `ToolResult(content=_ERROR_MARKER, ...)` instead.
- **DO NOT** wrap the recall call in tenacity. Compound retry layers (embedder tenacity + RecallTool tenacity + planner re-plan) blow latency budgets. Phase 23 sub-agents (verifier, extractor) already established this no-double-retry precedent.
- **DO NOT** add a kill-switch branch INSIDE `run()` (e.g. `if not settings.recall_tool_enabled: return ...`). The kill-switch is implemented via conditional registration in `__init__.py` (D-B4 / Pattern 3) — registry lookup returns absent when disabled, so `run()` is unreachable. Adding a runtime branch wastes a planner-prompt slot.
- **DO NOT** set `is_error=True` on the empty-result branch (D-C2). Empty IS a legitimate outcome.
- **DO NOT** import `services.memory.memory_service` at module top in a way that creates a circular import — `recall.py` imports from `memory_service`, and `memory_service` does NOT import from `services.agent.*` (verified). Safe to import at top; no lazy-import needed.

---

### 4. `services/agent/tools/__init__.py` (MODIFY — conditional registration, D-B4 / MEM-09)

**Analog:** own existing body at `services/agent/tools/__init__.py:15-20` (RetrieveTool / WebSearchTool registration imports)

#### Before (current `services/agent/tools/__init__.py:1-30`)

```python
"""services.agent.tools — Tool abstraction layer (Phase 17, AGENT-07).
... (existing docstring) ...
"""

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry, get_tool_registry

# Side-effect imports trigger @get_tool_registry().register decorators at
# package load time (RESEARCH §Decision 3 — explicit named imports).
from services.agent.tools.retrieve import (  # noqa: F401
    RefinedRetrieveTool,
    RetrieveTool,
    retrieve_impl,
)
from services.agent.tools.web_search import WebSearchTool  # noqa: F401

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "get_tool_registry",
    "RetrieveTool",
    "RefinedRetrieveTool",
    "WebSearchTool",
    "retrieve_impl",
]
```

#### After (Phase 24 edit — add conditional import + extend `__all__`)

```python
from config.settings import settings
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import ToolRegistry, get_tool_registry

# Side-effect imports trigger @get_tool_registry().register decorators at
# package load time (RESEARCH §Decision 3 — explicit named imports).
from services.agent.tools.retrieve import (  # noqa: F401
    RefinedRetrieveTool,
    RetrieveTool,
    retrieve_impl,
)
from services.agent.tools.web_search import WebSearchTool  # noqa: F401

# Phase 24 / D-B4 / Pattern 3 — kill-switch via conditional registration.
# When False, the decorator never runs → registry.get("recall_memory")
# raises KeyError → planner-LLM never sees the tool schema.
if settings.recall_tool_enabled:
    from services.agent.tools.recall import RecallTool  # noqa: F401

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "get_tool_registry",
    "RetrieveTool",
    "RefinedRetrieveTool",
    "WebSearchTool",
    "retrieve_impl",
]
```

#### Swap list

| Analog (existing tool imports) | RecallTool addition | Swap reason |
|---|---|---|
| Unconditional `from services.agent.tools.web_search import WebSearchTool` (line 20) | Wrap in `if settings.recall_tool_enabled:` block | D-B4 — kill-switch shape |
| `from config.settings import settings` not currently imported in `__init__.py` | Add as first line | Needed for the conditional |
| `RecallTool` NOT added to `__all__` | Optional — RESEARCH discretion. **Recommend OMIT** because when toggle is False the symbol does not exist and `from services.agent.tools import RecallTool` would raise `ImportError`. Consumers should import directly from `services.agent.tools.recall`. | Defensive — avoid surprising `ImportError` at consumer sites |

#### Anti-pattern callouts

- **DO NOT** unconditionally register and then short-circuit inside `run()` — defeats the kill-switch (Pattern 3 anti-pattern).
- **DO NOT** add a separate `RECALL_TOOL_ENABLED` constant duplicated from settings — single source of truth lives in `config/settings.py`.
- **DO NOT** import `RecallTool` from anywhere else in the tree (e.g. `pipeline.py`, `executor.py`) — Pitfall 4 — only `__init__.py` triggers the decorator. Other consumers go through `get_tool_registry().get("recall_memory")`.

---

### 5. `services/pipeline.py:744` (MODIFY — `AGENT_TOOL_ALLOWLIST` grows 3→4, MEM-09)

**Analog:** own existing literal at `services/pipeline.py:744`

#### Before

```python
# Explicit allowlist of tool names exposed to the planner LLM (AGENT-07).
# Phase 20: web_search joins the allowlist with the real Tavily impl
# (services/agent/tools/web_search.py). Empty TAVILY_API_KEY is a runtime
# short-circuit per CONTEXT D-03 — no startup-time filtering here.
AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search", "web_search"]
```

#### After

```python
# Explicit allowlist of tool names exposed to the planner LLM (AGENT-07).
# Phase 20: web_search joins with real Tavily impl.
# Phase 24 / MEM-09: recall_memory joins with pgvector cosine-recall impl
# (services/agent/tools/recall.py). settings.recall_tool_enabled gates
# REGISTRATION (not allowlist membership) — when False the registry lookup
# at registry.py:78 silently drops "recall_memory" from schemas_for(...).
AGENT_TOOL_ALLOWLIST: list[str] = [
    "search_knowledge_base",
    "refine_search",
    "web_search",
    "recall_memory",
]
```

#### Swap list

- Add `"recall_memory"` as the 4th list element (preserve insertion order — planner sees tools in this order).
- Update the comment block to reference Phase 24 / MEM-09 + the D-B4 registration-not-allowlist gating note.

#### Anti-pattern callouts

- **DO NOT** add a runtime `if settings.recall_tool_enabled` filter around the allowlist — D-B4 spec says the LIST stays length 4 regardless of toggle; only registry membership flips. `registry.schemas_for("anthropic", names=ALLOWLIST)` at `registry.py:78` already filters by registered names.
- **DO NOT** rename the constant — it is referenced at `services/pipeline.py:984`, `:1075`, `:1321` (3 call sites). Search-and-confirm.

---

### 6. `config/settings.py` (MODIFY — new `recall_tool_enabled` field, D-B4)

**Analog:** `config/settings.py:296-304` (the Phase 23 `extractor_enabled` + `extractor_model` + `extractor_provider` block — exact precedent CONTEXT D-B4 invokes)

#### Before (current `config/settings.py:296-304`)

```python
# Extractor sub-agent (Phase 23, MEM-03) ──────────────────────────────────
# extractor_enabled gates dispatch_extraction at the pipeline boundary
# (Plan 23-05). extractor_provider overrides the peer LLM provider just
# like verifier_provider; None = reuse the get_llm_client() singleton.
# extractor_model is reserved for per-call model override (not wired in
# v1.6; mirrors verifier_model precedent).
extractor_enabled:  bool                                = True
extractor_model:    str | None                          = None
extractor_provider: Literal["openai", "anthropic"] | None = None
```

#### After (append directly after extractor block, before line 306 `# ═══ Swarm ═══`)

```python
# Extractor sub-agent (Phase 23, MEM-03) ──────────────────────────────────
# ... existing extractor_enabled / extractor_model / extractor_provider ...
extractor_enabled:  bool                                = True
extractor_model:    str | None                          = None
extractor_provider: Literal["openai", "anthropic"] | None = None

# Recall tool (Phase 24, MEM-09 / D-B4) ───────────────────────────────────
# recall_tool_enabled=False kill-switch (default True — always-on).
# Gates REGISTRATION (not allowlist membership) at
# services/agent/tools/__init__.py: when False, the conditional
# `if settings.recall_tool_enabled: from ... import RecallTool` skips
# the decorator → registry lookup returns absent → planner-LLM never
# sees the tool schema (D-B4 / Pattern 3). AGENT_TOOL_ALLOWLIST stays
# at length 4 regardless of toggle.
recall_tool_enabled: bool = True
```

#### Swap list

| `extractor_enabled` precedent | `recall_tool_enabled` | Swap reason |
|---|---|---|
| Default `True` | Default `True` | Same — operator opts OUT not IN |
| Comment references Plan 23-05 dispatch gate | Comment references conditional registration + D-B4 | Different gating mechanism (Phase 23 branches at dispatch; Phase 24 branches at module-load) |
| Also adds `_model` + `_provider` siblings | NO sibling fields | RecallTool has no LLM provider override (it uses the embedder) — single bool sufficient |

#### Anti-pattern callouts

- **DO NOT** add `recall_model` / `recall_provider` siblings — RecallTool calls the embedder, not the LLM. Provider is governed by `settings.embedding_provider` (already exists).
- **DO NOT** rename existing `pgvector_ef_search_filtered` (line 243) — D-A2 explicitly reuses the chunks-table value (single tuning knob).
- **DO NOT** add a `recall_min_similarity` threshold — D-A3 / Deferred Idea (v1.7+).

---

### 7. `scripts/backfill_fact_embeddings.py` (NEW — MEM-07)

**Analog 1 (argparse + asyncio.run shape):** `scripts/ingest_batch.py` (116 LOC — the ONLY existing async CLI in `scripts/`)
**Analog 2 (chunked-commit + cursor + txn-rollback idiom):** NEW for this project — RESEARCH §Pattern 4 provides the skeleton; no in-tree precedent for `WHERE col IS NULL` cursor loops

#### `scripts/ingest_batch.py` reusable shape (lines 1-30, 61-116)

```python
#!/usr/bin/env python
# scripts/ingest_batch.py
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from services.pipeline import get_ingest_pipeline
from utils.logger import setup_logger
from utils.models import IngestionRequest

# ... business logic ...

async def main() -> None:
    setup_logger()
    parser = argparse.ArgumentParser(description="Enterprise RAG Batch Ingestion")
    parser.add_argument("--dir", required=True, help="目标目录路径")
    parser.add_argument("--dry-run", action="store_true", help="仅打印，不实际执行")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    # ... body ...

if __name__ == "__main__":
    asyncio.run(main())
```

#### Verbatim skeleton (Phase 24 — drop-in, ~180 LOC)

```python
#!/usr/bin/env python
# =============================================================================
# scripts/backfill_fact_embeddings.py
# Phase 24 / MEM-07 — backfill long_term_facts.embedding for pre-existing rows.
#
# Run-once-and-archive (D-D1). Idempotent via `WHERE embedding IS NULL` cursor.
# Resume via --resume-from-id (not checkpoint file). Whole-batch txn rollback
# on mid-batch failure (D-D3) — re-runs skip the 0 covered rows.
#
# Usage:
#   uv run python scripts/backfill_fact_embeddings.py [--dry-run] \
#       [--batch-size 100] [--resume-from-id <uuid>]
#
# Cost (D-D4): docs/memory-eviction.md companion section.
# =============================================================================
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 sys.path (mirrors scripts/ingest_batch.py:18-19)
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from services.memory.memory_service import LongTermMemory
from services.vectorizer.embedder import get_embedder
from utils.logger import setup_logger


async def _count_remaining(pool) -> int:
    """Cheap pre-flight count for --dry-run + final progress report."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM long_term_facts WHERE embedding IS NULL"
        )
    return int(row["n"])


async def backfill(
    batch_size: int,
    dry_run: bool,
    resume_from_id: str | None,
) -> int:
    """Returns POSIX exit code (0 success, 1 mid-batch failure rollback)."""
    # Reuse LongTermMemory._get_pool — inherits Phase 23 register_vector codec.
    # (Backfill standalone-pool alternative requires duplicating _init_conn —
    # Pitfall 1; reuse path is the recommended D-D1 implementation.)
    mem = LongTermMemory()
    pool = await mem._get_pool()
    embedder = get_embedder()

    remaining = await _count_remaining(pool)
    logger.info(f"backfill: {remaining} rows with embedding IS NULL")

    if dry_run:
        # D-D4 cost formula: ~40 tokens/fact × $0.13/1M (OpenAI text-embedding-3-large)
        est_tokens = remaining * 40
        est_cost_usd = est_tokens * 0.13 / 1_000_000
        logger.info(
            f"Would embed {remaining} facts "
            f"(~{est_tokens:,} tokens, ~${est_cost_usd:.4f})"
        )
        return 0

    total_done = 0
    while True:
        # ── 1. Fetch the next batch via cursor. ────────────────────────────
        async with pool.acquire() as conn:
            if resume_from_id:
                rows = await conn.fetch(
                    """SELECT id, fact FROM long_term_facts
                       WHERE embedding IS NULL AND id > $1
                       ORDER BY id LIMIT $2""",
                    resume_from_id, batch_size,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, fact FROM long_term_facts
                       WHERE embedding IS NULL
                       ORDER BY id LIMIT $1""",
                    batch_size,
                )

        if not rows:
            break

        texts = [r["fact"] for r in rows]

        # ── 2. Embed the batch (tenacity already in embed_batch). ──────────
        try:
            vectors = await embedder.embed_batch(texts)
        except (RuntimeError, OSError) as exc:
            # Narrow-exception per save_fact precedent (memory_service.py:305):
            #   RuntimeError — OllamaEmbedder re-raise; OSError — HF torch.
            #   httpx.HTTPError handled inside provider tenacity.
            logger.error(f"backfill: embedder failed, exit non-zero: {exc!r}")
            return 1

        # ── 3. Whole-batch txn UPDATE (D-D3 atomicity). ────────────────────
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for row, vec in zip(rows, vectors):
                        await conn.execute(
                            """UPDATE long_term_facts
                               SET embedding=$1::vector
                               WHERE id=$2""",
                            vec, row["id"],
                        )
        except Exception as exc:  # noqa: BLE001 — txn rollback contract
            # Whole-batch rollback already executed by `async with conn.transaction()`
            # exit-with-exception. Exit non-zero per D-D3 so CI/ops detect.
            logger.error(
                f"backfill: txn UPDATE failed, rollback complete: {exc!r}"
            )
            return 1

        total_done += len(rows)
        logger.info(
            f"backfilled batch: count={len(rows)} total={total_done} "
            f"remaining≈{remaining - total_done}"
        )

    logger.info(f"backfill complete: {total_done} rows embedded")
    return 0


def main() -> None:
    setup_logger()
    parser = argparse.ArgumentParser(
        description="Phase 24 / MEM-07 — backfill long_term_facts.embedding"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print estimate, no API calls or DB writes",
    )
    parser.add_argument(
        "--batch-size", type=int, default=100,
        help="Rows per UPDATE batch (txn boundary; D-D3)",
    )
    parser.add_argument(
        "--resume-from-id", type=str, default=None,
        help="UUID; resume after this row (skip already-processed)",
    )
    args = parser.parse_args()

    exit_code = asyncio.run(
        backfill(args.batch_size, args.dry_run, args.resume_from_id)
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
```

#### Swap list

| `scripts/ingest_batch.py` (analog 1) | `backfill_fact_embeddings.py` | Swap reason |
|---|---|---|
| `setup_logger()` + `argparse` + `asyncio.run(main())` shape | Preserved verbatim | Standard CLI shape |
| `sys.path.insert(0, str(Path(__file__).parent.parent))` | Preserved verbatim | Standard project-root injection |
| `--dir`, `--recursive`, `--dry-run`, `--concurrency` flags | `--dry-run`, `--batch-size`, `--resume-from-id` flags | Different operation (no dir scan; cursor loop instead) |
| Uses `Semaphore` for concurrency-bounded ingestion | NO semaphore — embedder tenacity + batch sizing govern rate | D-D2 — no `--qps` flag in v1.6 (deferred) |
| Calls `get_ingest_pipeline()` | Instantiates `LongTermMemory()` + calls `_get_pool()` directly | Reuse Phase 23 codec init (Pitfall 1) |
| No txn-rollback semantics | Wrap UPDATE loop in `async with conn.transaction()` | D-D3 — whole-batch atomicity |
| `sys.exit(1)` on first failure (line 73) | `return 1` from `backfill` then `sys.exit(exit_code)` | Distinguish dry-run zero-exit from operational success |

#### Anti-pattern callouts

- **DO NOT** construct a standalone `asyncpg.create_pool(...)` without the `init=_init_conn` callback — Pitfall 1, pgvector codec won't be registered, `$1::vector` binds will fail silently.
- **DO NOT** drop the `async with conn.transaction()` wrap around the UPDATE loop — Pitfall 7, partial-write rows break the D-D3 idempotency-on-rerun guarantee.
- **DO NOT** add `--qps` rate-limiting — D-D2 / Deferred (v1.7+).
- **DO NOT** add a checkpoint file — D-D1 says resume is via CLI flag, not state file. `WHERE embedding IS NULL` is the implicit cursor.
- **DO NOT** raise `MemoryFactWriteError` — backfill is operator-run; exit non-zero is the signal, not a typed exception.
- **DO NOT** call `save_fact` per row (would re-INSERT instead of UPDATE the existing row by id). Use `UPDATE long_term_facts SET embedding=...`.
- **DO NOT** copy `ingest_batch.py`'s `conda run -n torch_env python` docstring example — use `uv run python` per CLAUDE.md.

---

### 8. `docs/memory-eviction.md` (NEW — companion section, D-D4)

**Analog:** no existing `memory-eviction.md` in `docs/` (verified: only `DOCKER_DEPLOY.md`, `agent-architecture.md`, `v1.4-design.md`, `demo.cast` exist). This file is created NEW.

Layout reference: `docs/agent-architecture.md` (23.6K) for section-heading convention; `docs/DOCKER_DEPLOY.md` for ops-doc tone (short paragraphs + `bash` code blocks + numbered procedures).

#### Required sections (per D-D4 — ~30-50 lines total)

```markdown
# Memory Eviction & Backfill (Phase 24)

## Cost Formula (per provider)

| Provider | Per 1M facts | Per fact (~40 tokens) |
|---|---|---|
| OpenAI `text-embedding-3-large` (1024-dim) | $0.13/1M tokens × 40M = ~$5.20 | ~$5.2 µ |
| OpenAI `text-embedding-3-small` (1024-dim) | $0.02/1M tokens × 40M = ~$0.80 | ~$0.8 µ |
| HuggingFace local (BGE-M3, CPU/GPU) | $0 marginal | $0 |
| Ollama local (any) | $0 marginal | $0 |

## Backfill — Run Once

\`\`\`bash
# 1. Dry-run cost estimate (no API calls)
uv run python scripts/backfill_fact_embeddings.py --dry-run

# 2. Real run (100 rows per txn; tenacity 3-retry on 5xx)
uv run python scripts/backfill_fact_embeddings.py --batch-size 100

# 3. Resume after a partial failure (UUID from prior log line)
uv run python scripts/backfill_fact_embeddings.py --resume-from-id <uuid>
\`\`\`

## Failure Modes

| Symptom | Cause | Recovery |
|---|---|---|
| Exit 1 with `embedder failed` | Provider transient (429 / 5xx) | Re-run; cursor skips already-embedded rows |
| Exit 1 with `txn UPDATE failed, rollback complete` | pgvector codec or dim mismatch | Verify `settings.embedding_dim` matches column type; re-run after fix |
| Long runtime + no progress | Rate limit not honored | Wait, or split batches (`--batch-size 50`) |

## Recurring Backfill

Not needed in steady state. Phase 23 `save_fact` embeds-on-write — only pre-Phase-24 rows have `embedding IS NULL`. If a future schema migration adds new fact rows without embeddings, re-run the same script.
```

#### Anti-pattern callouts

- **DO NOT** document `memory_eviction` as a separate concept — this file's title is "Memory Eviction & Backfill" but Phase 24 ships the backfill section only. The eviction section is reserved for Phase 25 (per-tenant capacity overrides + importance decay — REQUIREMENTS Out of Scope here).
- **DO NOT** include cron / systemd / k8s CronJob YAML — D-D1 / Deferred (v1.7+).

---

### 9. `tests/unit/test_memory_recall_semantic.py` (NEW — MEM-06)

**Analog:** `tests/unit/test_memory_save_fact.py` (199 LOC — Phase 23 sibling for the same module + same fake-pool harness)

#### Reusable harness from `test_memory_save_fact.py:40-80`

```python
# Env-var setdefault MUST be at module top BEFORE any `services.*` import.
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


class _AcquireCtx:
    def __init__(self, conn):
        self._conn = conn
    async def __aenter__(self):
        return self._conn
    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_fake_pool(execute_mock, fetch_mock) -> tuple[MagicMock, MagicMock]:
    """Returns (pool, conn). conn carries execute + fetch AsyncMocks."""
    conn = MagicMock(execute=execute_mock, fetch=fetch_mock)
    # NEW for recall test: also stub conn.transaction() as async context manager.
    conn.transaction = MagicMock(return_value=_AcquireCtx(conn))
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool, conn


def _make_long(pool: MagicMock) -> LongTermMemory:
    """Construct LongTermMemory with pool pre-injected (bypass _get_pool)."""
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool
    async def _get_pool():
        return pool
    lt._get_pool = _get_pool
    return lt
```

#### Required tests (RESEARCH §Validation Architecture rows MEM-06)

| Test name | What it asserts | Mocks |
|---|---|---|
| `test_returns_bare_strings_sorted_by_cosine` | Happy path — fetch returns 3 rows; result is `["fact1", "fact2", "fact3"]` (bare strings, no `"- "` prefix per Pitfall 3) | `get_embedder().embed_one` → `[0.1]*1024`; `conn.fetch` → 3 fake rows |
| `test_ef_search_in_effect_during_select` | `conn.execute` called with `"SET LOCAL hnsw.iterative_scan = 'strict_order'"` AND `"SET LOCAL hnsw.ef_search = 200"` (in that order) BEFORE `conn.fetch` | Spy execute calls; assert call sequence |
| `test_get_relevant_facts_uses_transaction` | `conn.transaction()` is entered (Pitfall 2 — `SET LOCAL` requires explicit txn) | Stub `conn.transaction` as MagicMock returning `_AcquireCtx(conn)`; assert called once |
| `test_embedder_failure_returns_empty` | Embedder raises `RuntimeError` → `get_relevant_facts` returns `[]` (NOT raises); `conn.fetch` NEVER called | `embed_one.side_effect = RuntimeError(...)`; assert `fetch.await_count == 0` |
| `test_pg_failure_returns_empty` | `conn.fetch` raises `asyncpg.PostgresError` → returns `[]` | `fetch.side_effect = asyncpg.PostgresError(...)` |
| `test_limit_parameter_respected` | `conn.fetch` called with `limit` positional param = 5 (default) and = 3 (caller override) | Spy fetch.call_args.args[4] |
| `test_signature_unchanged` | `inspect.signature(get_relevant_facts).parameters` matches `["self", "user_id", "tenant_id", "query", "limit"]` + `limit` default == 5 | `inspect` module |
| `test_returns_bare_strings_no_prefix` (Pitfall 3 regression) | No element of return list starts with `"- "` or `"* "` | Same as happy path; assert no prefix |
| `test_tie_break_sql_includes_importance_and_created_at` | `conn.fetch` call_args.args[0] (SQL string) contains `"ORDER BY embedding <=> $3::vector, importance DESC, created_at DESC"` | Spy fetch.call_args.args[0] |

#### Swap list vs `test_memory_save_fact.py`

| `test_memory_save_fact.py` | `test_memory_recall_semantic.py` | Swap reason |
|---|---|---|
| Mocks `execute` AsyncMock | Mocks `fetch` AsyncMock (recall reads rows) + `execute` AsyncMock (for `SET LOCAL`) | Different SQL op |
| `_make_fake_pool(execute_mock)` — only execute stub | `_make_fake_pool(execute_mock, fetch_mock)` — both | Recall needs both |
| Asserts `MemoryFactWriteError` raised on failure | Asserts `[]` returned on failure (Pitfall 6 — load_context contract) | Different error semantics |
| No txn-context stub | Stub `conn.transaction = MagicMock(return_value=_AcquireCtx(conn))` | Pitfall 2 requires txn |
| Mocks `services.vectorizer.embedder.get_embedder` (source-path) AND `services.memory.memory_service.get_embedder` (consumer-path) | Same dual patch | `get_relevant_facts` also does lazy `from services.vectorizer.embedder import get_embedder` |

#### Anti-pattern callouts

- **DO NOT** assert exact SQL string equality — use substring assertions (`"SET LOCAL hnsw.iterative_scan" in sql`). The exact wording may evolve.
- **DO NOT** test against a real PG — that's the integration test (`tests/integration/test_pipeline_load_context_audit.py`). This file is pure unit.
- **DO NOT** import `register_vector` — the fake pool bypasses codec entirely.

---

### 10. `tests/unit/test_recall_tool.py` (NEW — MEM-08 + MEM-09)

**Analog:** `tests/unit/test_web_search_tool.py` (TestWebSearchToolRegistration shape — lines 121-130 verbatim) + `tests/unit/test_retrieve_tool.py` (RetrieveTool happy-path)

#### Required tests (RESEARCH §Validation Architecture rows MEM-08 + MEM-09)

| Test name | What it asserts | Mocks |
|---|---|---|
| `test_recall_tool_registered` | `"recall_memory" in get_tool_registry().list()` | None — module-import side effect |
| `test_recall_tool_classvars` | `RecallTool.name == "recall_memory"`; `RecallTool.description` matches D-C4 verbatim; `RecallTool.parameters_schema == _RECALL_PARAMETERS_SCHEMA` | None |
| `test_registered_in_allowlist` | `"recall_memory" in services.pipeline.AGENT_TOOL_ALLOWLIST` | None |
| `test_registered_exactly_once` (Pitfall 4) | `get_tool_registry().list().count("recall_memory") == 1` | None |
| `test_parameters_schema_is_mem_08_literal` | `RecallTool.parameters_schema == {"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}` | None |
| `test_happy_path_bullets` | 3 facts → `ToolResult.content == "- fact1\n- fact2\n- fact3"`; `is_error is False`; `metadata["fact_count"] == 3` | Patch `services.agent.tools.recall.get_memory_service` to return MagicMock whose `_long.get_relevant_facts = AsyncMock(return_value=["fact1","fact2","fact3"])` |
| `test_empty_marker` (D-C2) | 0 facts → `content == "No matching facts found."`; `is_error is False`; `metadata["fact_count"] == 0` | Same patch, return `[]` |
| `test_error_isolation` (D-C3) | `_long.get_relevant_facts` raises `asyncpg.PostgresError` → `content == "Memory unavailable; proceed without recall."`; `is_error is True`; NO exception propagates | `get_relevant_facts.side_effect = asyncpg.PostgresError(...)` |
| `test_error_isolation_parametrized` | Same as above parametrized over `(asyncpg.PostgresError, httpx.HTTPError, RuntimeError, OSError)` | Parametrize side_effect |
| `test_missing_user_id_returns_empty` | `ctx.req.user_id == ""` → `content == _EMPTY_MARKER`; `metadata["reason"] == "missing_user_or_tenant_id"`; `get_relevant_facts` NEVER awaited | Spy on `get_memory_service` — assert `.assert_not_called()` |
| `test_missing_tenant_id_returns_empty` | Same as above with `tenant_id == ""` | Same |
| `test_args_query_overrides_ctx_query` | `args={"query": "explicit"}` + `ctx.req.query == "fallback"` → calls `get_relevant_facts` with `query="explicit"` | Spy call_args |
| `test_args_missing_falls_back_to_ctx_query` | `args={}` → calls with `ctx.req.query` | Spy |

#### Reusable ctx helper from `test_web_search_tool.py:42-48`

```python
def _ctx(user_id: str = "u1", tenant_id: str = "t1", query: str = "q") -> ToolContext:
    return ToolContext(
        req=GenerationRequest(query=query, user_id=user_id, tenant_id=tenant_id),
        tf={},
        retriever=object(),
        llm=object(),
    )
```

#### Swap list vs `test_web_search_tool.py`

| `test_web_search_tool.py` | `test_recall_tool.py` | Swap reason |
|---|---|---|
| Patches `services.agent.tools.web_search.settings` (`tavily_api_key`) | Patches `services.agent.tools.recall.get_memory_service` | Different downstream — recall reaches memory service, not Tavily SDK |
| Tests `tavily_disabled` short-circuit | Tests `missing_user_id` / `missing_tenant_id` short-circuit | Different precondition |
| Tests 3 error kinds (`tavily_disabled`, `quota_exhausted`, `web_search_failed`) | Tests 1 error kind (best-effort isolation) | Recall has single failure mode |
| Source-side redaction assertions (`"tvly-" not in result.model_dump_json()`) | OMIT — no secret leakage surface | RecallTool returns fact strings + literal marker only |
| `_StubTavilyClient` duck type | NOT needed | Patch `get_memory_service` directly |
| Tenacity 5xx-then-200 retry test | OMIT | No tenacity at RecallTool level (per D-C3 + anti-pattern callout) |

#### Anti-pattern callouts

- **DO NOT** reach into private `_long.get_relevant_facts` from tests via `mem._long` — patch at the consumer path (`services.agent.tools.recall.get_memory_service`) so the test exercises the same indirection chain the tool uses.
- **DO NOT** test cosine quality here — that belongs to `tests/integration/test_recall_offline_eval.py` (SC-1, separate file).
- **DO NOT** mock `BaseTool.__init_subclass__` — the `__init_subclass__` enforcement at `services/agent/tools/base.py:40-49` is a desired guard.

---

### 11. `tests/unit/test_backfill_fact_embeddings.py` (NEW — MEM-07)

**Analog:** `tests/unit/test_memory_save_fact.py` (fake-pool harness)

#### Required tests (RESEARCH §Validation Architecture rows MEM-07)

| Test name | What it asserts | Mocks |
|---|---|---|
| `test_dry_run_no_api_calls` | `--dry-run` → embedder NEVER called; `conn.execute` NEVER called (only `fetchrow` for count); exit 0 | Spy `embedder.embed_batch.await_count == 0` |
| `test_dry_run_cost_estimate_format` | `--dry-run` log output contains `"Would embed"` + count + `"tokens"` + `"$"` | Capture loguru logs via `caplog` (configure loguru→caplog propagation per conftest) |
| `test_happy_path_batch_commit` | 100 rows → embedder.embed_batch called once with 100 texts; `conn.execute` UPDATE called 100 times inside ONE transaction | Spy txn-enter count |
| `test_idempotent_second_run` | After successful run, `_count_remaining` returns 0; second `backfill()` call exits 0 with `total_done=0` | Two-pass fixture |
| `test_batch_rollback_on_failure` (Pitfall 7) | UPDATE raises on row 47 → txn rolls back; exit 1; assertion: zero rows had `embedding` populated | Stub execute to raise on 47th call |
| `test_embedder_failure_exit_1` | `embed_batch.side_effect = RuntimeError` → exit 1; NO UPDATE attempted | Spy `conn.execute.await_count == 0` |
| `test_resume_from_id_uses_cursor_filter` | `--resume-from-id <uuid>` → SQL includes `AND id > $1`; UUID passed as $1 binding | Spy fetch.call_args.args |
| `test_batch_size_parameter_respected` | `--batch-size 50` → fetch LIMIT param == 50 | Spy fetch.call_args |
| `test_reuses_long_term_memory_pool` (Pitfall 1) | Instantiates `LongTermMemory()` then awaits `_get_pool()`; verify `register_vector` codec init callback present (or trust Phase 23 regression test_memory_pool.py) | Reuse pattern from `test_memory_pool.py:30-79` |

#### Swap list vs `test_memory_save_fact.py`

| `test_memory_save_fact.py` | `test_backfill_fact_embeddings.py` | Swap reason |
|---|---|---|
| Tests single `save_fact()` call | Tests `backfill()` async function (full CLI body minus argparse) | Different scope |
| `_make_fake_pool(execute_mock)` | Same harness + `fetch_mock` + `fetchrow_mock` (for count + cursor) | Backfill reads rows |
| Mocks `get_embedder().embed_one` | Mocks `get_embedder().embed_batch` (batched embedder path) | D-D2 — batch reuse |
| Asserts `MemoryFactWriteError` | Asserts exit code (1 on failure) + zero partial-write rows | Operational tool semantics |
| No txn-context stub | Stub `conn.transaction = MagicMock(return_value=_AcquireCtx(conn))` | D-D3 atomicity |
| One-shot test | Multi-iteration `while True` cursor loop test (parametrized over batch counts) | Cursor mechanics |

#### Anti-pattern callouts

- **DO NOT** drive the script's `main()` via subprocess — patch `sys.argv` + call `main()` in-process, or test `backfill()` directly (preferred — argparse is thin).
- **DO NOT** assert exact dry-run output text — use substring matches (`"Would embed" in log`).
- **DO NOT** include real `asyncpg` connections — fake pool only.

---

### 12. `tests/unit/test_settings_recall_kill_switch.py` (NEW — D-B4)

**Analog:** no direct in-tree precedent for `importlib.reload`-based registration tests. Pattern shape derived from `tests/unit/test_memory_pool.py:30-79` (module-attr patching with `raising=False`).

#### Required tests

| Test name | What it asserts | Mechanism |
|---|---|---|
| `test_enabled_registers_tool` | With `settings.recall_tool_enabled = True`, reload `services.agent.tools.__init__`; assert `"recall_memory" in get_tool_registry().list()` | `importlib.reload(services.agent.tools)` after `monkeypatch.setattr(settings, "recall_tool_enabled", True)` |
| `test_disabled_skips_registration` | With `settings.recall_tool_enabled = False`, reload; assert `"recall_memory" not in get_tool_registry().list()` | Same + fresh registry: monkeypatch `services.agent.tools.registry._registry = None` BEFORE reload |
| `test_disabled_registry_lookup_raises` | `get_tool_registry().get("recall_memory")` raises `KeyError` when disabled | Same as above |
| `test_allowlist_length_unchanged` (D-B4 wording) | `len(AGENT_TOOL_ALLOWLIST) == 4` regardless of toggle | Compare both toggle states |
| `test_schemas_for_omits_when_disabled` | `registry.schemas_for("anthropic", names=AGENT_TOOL_ALLOWLIST)` returns 3 entries (not 4) when toggle is False | `registry.py:78` filters by registered names |

#### Skeleton (NEW pattern — propose this idiom)

```python
"""Phase 24 / D-B4 — recall_tool_enabled kill-switch via conditional registration."""
from __future__ import annotations

import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import importlib
import pytest

from config.settings import settings


def _reset_registry_and_reimport(monkeypatch, enabled: bool):
    """Reset the singleton registry + reload tools package so the conditional
    import at services.agent.tools.__init__.py:N re-evaluates."""
    import services.agent.tools.registry as reg_mod
    monkeypatch.setattr(reg_mod, "_registry", None, raising=False)
    monkeypatch.setattr(settings, "recall_tool_enabled", enabled, raising=False)
    import services.agent.tools as tools_mod
    importlib.reload(tools_mod)
    # Re-import the explicit submodules so RetrieveTool/WebSearchTool re-register.
    import services.agent.tools.retrieve as r1
    import services.agent.tools.web_search as r2
    importlib.reload(r1)
    importlib.reload(r2)
    return tools_mod.get_tool_registry()


def test_enabled_registers_recall_memory(monkeypatch):
    reg = _reset_registry_and_reimport(monkeypatch, enabled=True)
    assert "recall_memory" in reg.list()


def test_disabled_skips_recall_memory(monkeypatch):
    reg = _reset_registry_and_reimport(monkeypatch, enabled=False)
    assert "recall_memory" not in reg.list()


def test_disabled_registry_lookup_raises_keyerror(monkeypatch):
    reg = _reset_registry_and_reimport(monkeypatch, enabled=False)
    with pytest.raises(KeyError):
        reg.get("recall_memory")


def test_allowlist_length_constant_regardless_of_toggle():
    """D-B4 wording — allowlist literal stays at 4 regardless of toggle."""
    from services.pipeline import AGENT_TOOL_ALLOWLIST
    assert len(AGENT_TOOL_ALLOWLIST) == 4
    assert "recall_memory" in AGENT_TOOL_ALLOWLIST


def test_schemas_for_omits_when_disabled(monkeypatch):
    """registry.schemas_for filters by registered names (registry.py:78);
    when disabled, the 4-element allowlist yields 3 schemas."""
    from services.pipeline import AGENT_TOOL_ALLOWLIST
    reg = _reset_registry_and_reimport(monkeypatch, enabled=False)
    schemas = reg.schemas_for("anthropic", names=AGENT_TOOL_ALLOWLIST)
    assert len(schemas) == 3
    names = [s["name"] for s in schemas]
    assert "recall_memory" not in names
```

#### Anti-pattern callouts

- **DO NOT** clear `sys.modules["services.agent.tools.recall"]` manually — `importlib.reload(tools_mod)` plus the registry reset is sufficient.
- **DO NOT** leave registry mutated for the next test — `reset_registry_and_reimport` is per-test by virtue of `monkeypatch` undo.
- **DO NOT** patch `__init__.py`'s module body — patch `settings.recall_tool_enabled` and rely on the conditional.

---

### 13. `tests/integration/test_recall_tool_planner_pick.py` + `test_pipeline_load_context_audit.py` (NEW — integration)

**Analogs:**
- `tests/integration/test_pgvector_filtered_recall.py` (lines 1-30 — `pytestmark`, `DIM_TEST` constant, `pg_store` fixture usage)
- `tests/integration/test_pgvector_recall.py` (entire file — `PG_AVAILABLE` skip-gate, asyncpg.Pool fixture)
- `tests/integration/test_extractor_e2e.py` (Phase 23 — end-to-end pipeline patching pattern)

#### Marker convention (from `tests/integration/test_pgvector_filtered_recall.py:22-29`)

```python
import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import pytest
from tests.conftest import PG_AVAILABLE

pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.skipif(
        not PG_AVAILABLE,
        reason="PostgreSQL + pgvector not available — skipping",
    ),
]
```

#### `test_recall_tool_planner_pick.py` — required tests (MEM-09 row in RESEARCH §Validation Architecture)

| Test name | What it asserts | Mechanism |
|---|---|---|
| `test_planner_picks_recall_for_preference_query` | Given seeded facts including `"user prefers React"`, planner.plan_from_messages with query `"what frontend do I like?"` produces a ToolPlan whose tool_calls include `name="recall_memory"` | Real PG seed via `pgvector_pool` fixture; real planner LLM (or mock at planner) with `AGENT_TOOL_ALLOWLIST` including `recall_memory` |
| `test_planner_skips_recall_for_unrelated_query` | Query `"what's the weather in Paris?"` does NOT include `recall_memory` in the tool_calls | Same setup |
| `test_recall_tool_returns_seeded_fact` | After seed, calling `RecallTool().run(args={"query":"frontend"}, ctx=...)` returns `ToolResult` whose content contains `"React"` | Real PG + real embedder (provider-dependent — skip if `settings.embedding_provider == "huggingface"` and model not present) |

#### `test_pipeline_load_context_audit.py` — required tests (MEM-10 row + D-B3)

| Test name | What it asserts | Mechanism |
|---|---|---|
| `test_load_context_facts_length_le_5_all_four_callsites` | At each of `services/pipeline.py:429, 608, 971, 1062`, `len(mem_ctx.long_term_facts) <= 5` after the rewrite | Patch `_memory.load_context` to call real impl + spy; drive each pipeline path with stub req |
| `test_load_context_returns_list_of_str` (Pitfall 3 regression) | `mem_ctx.long_term_facts` is `list[str]`; no element starts with `"- "` | Type + prefix assertion |
| `test_writes_token_delta_artifact` (D-B3) | Phase audit artifact written to `.planning/phases/24-pgvector-recalltool-semantic-recall-rewrite/24-MEM10-AUDIT.json` containing `{"mean_tokens": ..., "p95_tokens": ..., "baseline_mean": ..., "delta_mean": ...}` | Open file post-test; assert structure (NOT a gating test per D-B3 — observational only) |
| `test_no_v1_5_regression` | Run a fixed v1.5 test fixture (e.g., a small recorded request) and assert pipeline returns `GenerationResponse` successfully | Use existing `tests/integration/test_pipeline.py` baseline shape |

#### Swap list vs `test_pgvector_filtered_recall.py`

| `test_pgvector_filtered_recall.py` | Phase 24 integration tests | Swap reason |
|---|---|---|
| Uses `pg_store` fixture (PgVectorStore for chunks) | Use `pgvector_pool` fixture + `LongTermMemory()` (facts table) | Different table |
| `store._dim = 384` override + `store._table = "..."` | Use real `long_term_facts` table with seed data; cleanup after test | Phase 24 ships embedding column at production dim |
| `await store.upsert(chunks)` then `store.search(...)` | `await mem._long.save_fact(...)` then `await mem._long.get_relevant_facts(...)` | Different API surface |
| Cleanup: `DROP TABLE` | Cleanup: `DELETE FROM long_term_facts WHERE user_id='test-u'` | Don't drop the shared production table |

#### Anti-pattern callouts

- **DO NOT** drop the `long_term_facts` table at test end — use scoped DELETE on the test's `user_id` / `tenant_id`.
- **DO NOT** assume the planner LLM is deterministic — gate the `test_planner_picks_recall_for_preference_query` test on multiple repeats or use a low-temp/mocked planner if SC-1 flakes.
- **DO NOT** assert exact `long_term_facts` content vs popularity baseline — only LENGTH (per D-B3 + Pattern 5 anti-pattern).
- **DO NOT** write the audit artifact via `print` — use `Path(...).write_text(json.dumps(...))` for repeatable parsing.

---

## Shared Patterns

### Structured logging (loguru kwargs)
**Source:** `services/memory/memory_service.py:239, 269, 286, 310, 325` (consistent shape).
**Apply to:** all new logger calls in `get_relevant_facts`, `RecallTool`, `backfill_fact_embeddings.py`.
```python
logger.error("memory service failure", operation="get_facts_semantic", exc_info=exc)
logger.error(f"[RecallTool] failed: {exc!r}")   # mirrors retrieve.py:194 / web_search.py:247
logger.info(f"backfilled batch: count={len(rows)} total={total_done}")   # mirrors ingest_batch.py:46
```

### `from __future__ import annotations`
**Source:** every existing `.py` file in this scope (`memory_service.py:5`, `vector_store.py`, `web_search.py:30`, `retrieve.py:14`).
**Apply to:** every new `.py` file in Phase 24. MANDATORY per repo convention.

### Narrow-exception tuple constants
**Source:** `services/agent/tools/retrieve.py:151` (`_RETRIEVE_RUNTIME_ERRORS`), `services/agent/tools/web_search.py:127` (tenacity `retry_if_exception_type` tuple).
**Apply to:** `services/agent/tools/recall.py::_RECALL_RUNTIME_ERRORS = (asyncpg.PostgresError, httpx.HTTPError, RuntimeError, OSError)`.

### Lazy local imports for circular-import resilience
**Source:** `services/memory/memory_service.py:88-92, 137, 148, 163-164, 298-301` (every `from config.settings import settings` is method-local in this module).
**Apply to:** `get_relevant_facts` rewrite — keep `from config.settings import settings` / `from services.vectorizer.embedder import get_embedder` / `import httpx` INSIDE the method body, not at module top.

### Mock-at-consumer-path test discipline (v1.3 D-08)
**Source:** `tests/unit/test_memory_save_fact.py:90-96` (dual source-path + consumer-path patches).
**Apply to:** all new Phase 24 unit tests. For `recall.py` patch `services.agent.tools.recall.get_memory_service`. For `get_relevant_facts` patch BOTH `services.vectorizer.embedder.get_embedder` (source) AND `services.memory.memory_service.get_embedder` (consumer, `raising=False`).

### Fake-pool harness for asyncpg-dependent unit tests
**Source:** `tests/unit/test_memory_save_fact.py:50-80` (`_AcquireCtx`, `_make_fake_pool`, `_make_long`).
**Apply to:** `test_memory_recall_semantic.py` + `test_backfill_fact_embeddings.py`. Extend `_make_fake_pool` to accept BOTH `execute_mock` and `fetch_mock` (recall reads rows), and stub `conn.transaction` as `MagicMock(return_value=_AcquireCtx(conn))` (Pitfall 2 requires entering the context manager).

### Env-var setdefault at test module top
**Source:** `tests/unit/test_memory_save_fact.py:25-28`, `tests/unit/test_memory_pool.py:13-16`, every Phase 23 test.
**Apply to:** every new Phase 24 test file. MANDATORY block — must precede ANY `services.*` import:
```python
import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")
```

### Singleton-reset autouse fixture
**Source:** `tests/unit/test_memory_save_fact.py:43-47`, `tests/unit/test_memory_pool.py:23-27`.
**Apply to:** every new Phase 24 unit test file that touches `MemoryService` or the tool registry.

### Pgvector integration marker convention
**Source:** `tests/integration/test_pgvector_filtered_recall.py:22-29`.
**Apply to:** both Phase 24 integration tests. `pytestmark = [pytest.mark.integration, pytest.mark.pgvector, pytest.mark.skipif(not PG_AVAILABLE, ...)]`.

### Conftest fixture reuse
**Source:** `tests/conftest.py:85-93` (`pgvector_pool` alias to `pg_pool`).
**Apply to:** Phase 24 integration tests reuse `pgvector_pool` (no new fixture needed). If a `memory_pool_with_seeds` or `planner_with_recall_tool` fixture is needed (RESEARCH §Wave 0 Gaps), add to conftest with the `pgvector_pool` dependency shape.

### `register_vector` codec init reuse (Pitfall 1)
**Source:** `services/memory/memory_service.py:146-160` (Phase 23 — already in place).
**Apply to:** `scripts/backfill_fact_embeddings.py` reuses `LongTermMemory()._get_pool()` (inherits the callback). DO NOT construct a standalone asyncpg pool.

---

## No Analog Found

| File / Element | Role | Data Flow | Reason |
|---|---|---|---|
| Chunked-commit `WHERE col IS NULL` cursor loop in `scripts/backfill_fact_embeddings.py` | operational CLI | batch UPDATE with whole-txn rollback | No in-tree precedent — `scripts/ingest_batch.py` is the closest script analog but it does single-file ingestion, not cursor-loop backfill. Pattern derived from RESEARCH §Pattern 4 (verbatim skeleton). |
| `importlib.reload`-based registration test in `tests/unit/test_settings_recall_kill_switch.py` | unit test | module-reload + registry state assertion | No in-tree precedent for kill-switch-via-conditional-import testing. Pattern proposed inline; mechanism is standard Python idiom. |
| `docs/memory-eviction.md` | docs | static | File does not exist yet — created NEW per D-D4. Layout reference: `docs/agent-architecture.md` for section convention. |
| MEM-10 token-delta audit artifact write in `test_pipeline_load_context_audit.py` | integration test | file write | No prior phase wrote a JSON audit artifact from an integration test. Mechanism: `Path(__file__).parent.parent.parent / ".planning/phases/24-.../24-MEM10-AUDIT.json".write_text(json.dumps(...))` — observational, NOT gating per D-B3. |

(All other Phase 24 surfaces have at least one role + data-flow exact analog.)

---

## Metadata

**Analog search scope:**
- `services/agent/tools/` (base, registry, retrieve, web_search, __init__)
- `services/agent/` (extractor for kill-switch precedent)
- `services/memory/memory_service.py` (LongTermMemory + MemoryService + load_context + save_fact + get_relevant_facts)
- `services/vectorizer/vector_store.py` (HNSW filter-path)
- `services/vectorizer/embedder.py` (embed_one + embed_batch + BatchedEmbedder)
- `services/pipeline.py:744` + lines 429/608/971/1062/984/1075/1321 (4 load_context call sites + 3 allowlist references)
- `config/settings.py:288-304` (verifier + extractor blocks)
- `scripts/ingest_batch.py` (sole existing async CLI)
- `tests/unit/` (test_memory_save_fact, test_memory_pool, test_memory_service, test_extractor_dispatch, test_verifier, test_web_search_tool, test_retrieve_tool)
- `tests/integration/` (test_pgvector_recall, test_pgvector_filtered_recall, test_extractor_e2e)
- `tests/conftest.py` (PG_AVAILABLE, pg_pool, pgvector_pool fixtures)
- `utils/models.py:380-413` (ToolResult + ToolContext)
- `docs/` (no `memory-eviction.md`; sibling docs for layout)

**Files scanned (read for excerpt extraction):** 13 source + 6 test + 2 docs/scripts
**Pattern extraction date:** 2026-05-16
**Verbatim skeletons provided:** 4 (get_relevant_facts rewrite, RecallTool full class, backfill script full body, settings_recall_kill_switch test file)
