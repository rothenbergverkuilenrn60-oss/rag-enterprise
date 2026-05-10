# Phase 20: WebSearchTool Real Implementation (Tavily) - Pattern Map

**Mapped:** 2026-05-10
**Files analyzed:** 8 (5 modified, 3 new)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/agent/tools/web_search.py` (rewrite body) | tool / adapter | request-response (external HTTP) | `services/agent/tools/retrieve.py` (RetrieveTool sibling) + `services/vectorizer/embedder.py` (tenacity inner-helper pattern) | exact (tool shape) + role-match (retry helper) |
| `services/pipeline.py` allowlist edit (line 598) | config constant | n/a | self (line 598 already lists 2 names) | exact (1-line literal extension) |
| `static/ui.js` web-render branch | utility (frontend renderer) | transform | self (line 28 — existing `forEach` source-row block) | exact (single ternary insert) |
| `requirements.txt` (Tavily pin) | dependency manifest | n/a | self (lines 50–51 — `openai==`, `anthropic==` adjacent) | exact |
| `.env.docker` (TAVILY_API_KEY placeholder) | config / secrets manifest | n/a | self (line 26 `ANTHROPIC_API_KEY=` empty placeholder) | exact |
| `config/settings.py` Tavily fields | config / Pydantic Settings | n/a | self (lines 271–275 — `openai_api_key`, `anthropic_api_key` adjacent) | exact |
| `tests/unit/test_web_search_tool.py` (rewrite) | test (unit) | request-response | `tests/unit/test_retrieve_tool.py` (sibling tool unit) + `tests/unit/test_agent_sse.py` (consumer-path monkeypatch idiom) | exact (sibling tool) + role-match (mock pattern) |
| `tests/integration/test_planner_picks_web_search.py` (NEW) | test (integration) | request-response | `tests/integration/test_agent_pipeline_parallel.py` (live OpenAI agent integration) | role-match (closest agentic integration test) |

---

## Pattern Assignments

### `services/agent/tools/web_search.py` (tool, request-response)

**Primary analog:** `services/agent/tools/retrieve.py` (RetrieveTool sibling — same `BaseTool` subclass shape, same registry decorator, same `t0 = time.perf_counter()` + `latency_ms` envelope, same try/except → `_build_error_result` flow).

**Secondary analog (tenacity inner helper):** `services/vectorizer/embedder.py:48-59` — `@retry` on a single private async method (`_embed_single`) called by the public method; `retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException))` to scope retries to transient network errors only.

**Tertiary analog (final-attempt typed error path):** `services/generator/llm_client.py:275-302` — `@retry(..., before_sleep=before_sleep_log(...))` for observability of intermediate attempts.

#### Imports pattern (from `retrieve.py:14-32`):

```python
from __future__ import annotations

import time
from typing import Any, ClassVar

# loguru convention (every adapter module — embedder.py:12, retrieve.py:22)
from loguru import logger

from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from utils.models import (
    ChunkMetadata,
    RetrievedChunk,
    ToolContext,
    ToolResult,
)
```

Phase 20 adds (per CONTEXT D-07 module-level settings + D-08 tenacity inner helper):

```python
import hashlib  # D-09: chunk_id = f"web:{sha1(url).hexdigest()[:16]}"

from tenacity import retry, stop_after_attempt, wait_random_exponential
# (Tavily SDK exception types — verified at plan time; see RESEARCH STACK.md)
from tavily import AsyncTavilyClient

from config.settings import settings  # D-07 module-level settings import
```

#### Tool subclass / registry decorator pattern (from `retrieve.py:145-156`):

```python
@get_tool_registry().register
class RetrieveTool(BaseTool):
    """search_knowledge_base — primary RAG retrieval tool."""

    name: ClassVar[str] = "search_knowledge_base"
    description: ClassVar[str] = "在企业知识库中搜索相关信息"
    parameters_schema: ClassVar[dict[str, Any]] = _SEARCH_PARAMETERS_SCHEMA
```

**Phase 20 swap-in for `WebSearchTool`** (existing class at `web_search.py:34-43`):

```python
@get_tool_registry().register
class WebSearchTool(BaseTool):
    """web_search — real-time/external web retrieval via Tavily (Phase 20)."""

    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = (
        "Search the public web for current/real-time information, news, "
        "recent events, or topics not covered by the internal knowledge "
        "base. Prefer search_knowledge_base for indexed corpus questions."
    )  # CONTEXT D-02 — steering inside the descriptor; system prompt unchanged.
    parameters_schema: ClassVar[dict[str, Any]] = _WEB_SEARCH_PARAMETERS_SCHEMA
```

#### Tenacity inner-helper pattern (from `embedder.py:48-59`):

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=8),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
)
async def _embed_single(self, text: str) -> list[float]:
    resp = await self._client.post(
        f"{self._base_url}/api/embeddings",
        json={"model": self._model, "prompt": text},
    )
    resp.raise_for_status()
    return resp.json()["embedding"]
```

**Phase 20 adaptation** (D-08 — tenacity scope = inner private async helper, `reraise=True`, max=10):

```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=1, max=10),
    reraise=True,  # D-08: caller catches the underlying exception, not RetryError
)
async def _tavily_search(query: str) -> dict[str, Any]:
    client = get_tavily_client()
    return await client.search(
        query=query,
        search_depth=settings.tavily_search_depth,
        max_results=settings.tavily_max_results,
    )
```

#### Lazy-singleton factory pattern (from `services/agent/tools/registry.py:106-118`):

```python
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Return the process-wide ToolRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
```

**Phase 20 adaptation** (D-05 — `get_tavily_client()` factory at module level):

```python
_tavily_client: AsyncTavilyClient | None = None


def get_tavily_client() -> AsyncTavilyClient:
    """Process-wide AsyncTavilyClient singleton — keeps httpx pool warm."""
    global _tavily_client
    if _tavily_client is None:
        _tavily_client = AsyncTavilyClient(api_key=settings.tavily_api_key)
    return _tavily_client
```

#### Core `run()` body pattern (from `retrieve.py:158-190`):

```python
async def run(
    self,
    args: dict[str, Any],
    ctx: ToolContext,
) -> ToolResult:
    t0 = time.perf_counter()
    a = args or {}
    query_str = a.get("query") or ctx.req.query
    top_k = int(a.get("top_k", 5))
    try:
        chunks, ctx_text = await _retrieve_impl(...)
    except _RETRIEVE_RUNTIME_ERRORS as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        logger.error(f"[RetrieveTool] failed: {exc!r}")
        return self._build_error_result(exc, latency_ms=latency_ms)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    return ToolResult(
        content=ctx_text,
        chunks=list(chunks),
        metadata={
            "latency_ms": latency_ms,
            "query": query_str,
            "chunk_count": len(chunks),
        },
    )
```

**Phase 20 adaptation** — three short-circuit branches (D-13 / D-14 / D-15) inside `run()`:

1. `tavily_disabled` short-circuit BEFORE the retry boundary (D-03):
   ```python
   if not settings.tavily_api_key:
       return ToolResult(
           content="Web search not configured. Answer from the knowledge base only.",
           chunks=[],
           metadata={"error": True, "kind": "tavily_disabled", "latency_ms": 0},
           is_error=True,
       )
   ```
2. Try `_tavily_search`; on Tavily HTTP 429 → `kind="quota_exhausted"`; on any other transient/5xx (after 3 attempts) → `kind="web_search_failed"`. **NEVER** include `exc.response.headers`, `exc.response.text`, or stack traces in the result (D-15 source-side redaction).
3. Happy path: map Tavily results to `RetrievedChunk` (see next section).

#### `RetrievedChunk` / `ChunkMetadata` construction pattern

**Source (`utils/models.py:124-146` for ChunkMetadata, `:180-198` for RetrievedChunk):**

```python
class ChunkMetadata(BaseModel):
    source:          str           = ""
    doc_id:          str           = ""
    title:           str           = ""
    page_number:     int | None    = None
    chunk_type:      str           = "text"   # accepts "web" without schema change
    # ... (other fields default-populated)


class RetrievedChunk(BaseModel):
    chunk_id:         str
    doc_id:           str
    content:          str
    metadata:         ChunkMetadata
    dense_score:      float = 0.0
    sparse_score:     float = 0.0
    rrf_score:        float = 0.0
    rerank_score:     float = 0.0
    final_score:      float = 0.0
    retrieval_method: str   = "dense"
```

**Phase 20 adaptation** (D-09 / D-10 / D-11 / D-12):

```python
url = result["url"]
chunk_id = f"web:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}"
chunk = RetrievedChunk(
    chunk_id=chunk_id,
    doc_id="web",                                    # D-10 constant bucket
    content=result["content"],                       # D-12 verbatim Tavily snippet
    metadata=ChunkMetadata(
        source=url,
        title=result.get("title", ""),
        chunk_type="web",                            # D-12 — UI render switch key
        page_number=None,                            # D-12 — explicit None
    ),
    final_score=float(result.get("score", 0.0)),    # D-11 Tavily score passthrough
    retrieval_method="web",                          # D-11 method tag
)
```

#### Error-result construction (from `BaseTool._build_error_result`, `base.py:59-74`):

```python
def _build_error_result(self, exc: Exception, latency_ms: int = 0) -> ToolResult:
    return ToolResult(
        content=f"[{self.name}] error: {exc}",
        is_error=True,
        metadata={"latency_ms": latency_ms},
    )
```

**Phase 20 deviation:** The base helper exposes `f"{exc}"` in `content` — for Tavily this risks leaking response text (D-15). Phase 20 builds typed-error `ToolResult`s **inline** in `run()` instead of calling `_build_error_result`, so the `content` strings are the three D-13 user-facing messages and the only fields placed in `metadata` are `error`, `kind`, `latency_ms` (no exception text, no headers).

---

### `services/pipeline.py:598` (config constant, n/a)

**Analog:** self — current line 598:

```python
# Explicit allowlist of tool names exposed to the planner LLM (AGENT-07).
# WebSearchTool is registered but excluded here (placeholder — v1.5+).
AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search"]
```

**Phase 20 mutation** (single literal edit):

```python
# Explicit allowlist of tool names exposed to the planner LLM (AGENT-07).
# Phase 20: web_search joins the allowlist with the real Tavily impl.
AGENT_TOOL_ALLOWLIST: list[str] = ["search_knowledge_base", "refine_search", "web_search"]
```

The 3 callsites at `pipeline.py:789 / :862 / :1089` (`registry.schemas_for(provider, names=AGENT_TOOL_ALLOWLIST)`) automatically pick up the new value — no other edits in `pipeline.py`.

---

### `static/ui.js` (utility / frontend renderer, transform)

**Analog:** self — line 28 (existing PDF source-row render in `forEach` loop).

**Current line (`static/ui.js:25-32`):**

```javascript
(j.data.sources || []).forEach((s, i) => {
  const m = s.metadata || {};
  const score = s.final_score || s.rerank_score || s.rrf_score || s.dense_score || 0;
  h += '<div class="source"><div class="meta">来源' + (i+1) + ' · 页=' + (m.page_number ?? '?') + ' · 类型=' + (m.chunk_type || '?') + ' · score=' + score.toFixed(3) + '</div>';
  h += '<div>' + esc(s.content) + '</div>';
  if(m.image_b64) h += '<img src="data:image/png;base64,' + m.image_b64 + '">';
  h += '</div>';
});
```

**Phase 20 contract** (per UI-SPEC §"Source-Row Rendering Contract" + §"Host Extraction Rule"):

1. Add `hostOf` helper near existing `esc` helper (`ui.js:41-43`):
   ```javascript
   function hostOf(url){
     try { return new URL(url).host; }
     catch(e) { return '?'; }
   }
   ```

2. Insert per-row locator ternary inside the `forEach`:
   ```javascript
   const locator = (m.chunk_type === 'web')
     ? 'URL=' + esc(hostOf(m.source))
     : '页=' + (m.page_number ?? '?');
   h += '<div class="source"><div class="meta">来源' + (i+1) + ' · ' + locator + ' · 类型=' + (m.chunk_type || '?') + ' · score=' + score.toFixed(3) + '</div>';
   ```

**Invariants preserved (UI-SPEC):**
- `.source` / `.meta` CSS classes unchanged.
- No new colors, no new spacing, no new typography (`static/ui.css` not touched).
- `URL=<host>` is plain text, NOT a clickable `<a>` (UI-SPEC §"Visual-Treatment Delta").
- Strict equality `=== 'web'` — wrong-case, null, undefined fall through to `页=`.
- Failed `web_search` returns `chunks=[]` so no row is rendered (CONTEXT D-16); no error placeholder UX.

---

### `requirements.txt` (dependency manifest)

**Analog:** self — adjacent LLM SDK pins at lines 50–51:

```
openai==1.59.6               # OpenAI Embedding / Chat
anthropic==0.43.0            # Anthropic Claude
```

**Phase 20 append** (placement: after the LLM SDK block, before vector DB clients; or in a new "Web search" sub-section between STAGE-4 and STAGE-5):

```
# ── Web search ────────────────────────────────────────────────────────────────
tavily-python>=0.7.24,<0.8   # Tavily AsyncTavilyClient (Phase 20, AGENT-10)
```

Pin range source: CONTEXT canonical_refs → `.planning/research/STACK.md`. Plan-time may refine if 0.7.x has a known regression.

---

### `.env.docker` (config / secrets manifest)

**Analog:** self — lines 25–26 (Anthropic placeholder pattern):

```
# Anthropic (optional)
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6
```

**Phase 20 append** (P-16 prevention — `${TAVILY_API_KEY:-}` substitution prevents real keys from being committed to the file):

```
# ── Web search: Tavily ────────────────────────────────────────────────────────
TAVILY_API_KEY=${TAVILY_API_KEY:-}
TAVILY_SEARCH_DEPTH=basic
TAVILY_MAX_RESULTS=5
```

Note: lower-case env names work too (Pydantic V2 BaseSettings with `case_sensitive=False`, see `settings.py:54`); the `.env.docker` convention is upper-snake.

---

### `config/settings.py` (config / Pydantic Settings)

**Analog:** self — adjacent fields at lines 271–275 (`openai_api_key`, `anthropic_api_key`):

```python
openai_api_key:     str   = ""
openai_base_url:    str   = ""   # custom proxy, e.g. https://free.v36.cm/v1/; empty = official API
openai_model:       str   = "gpt-4o"
anthropic_api_key:  str   = ""
anthropic_model:    str   = "claude-sonnet-4-6"
```

**Phase 20 addition** (D-06 — three new fields placed adjacent to the LLM keys; no `TavilySettings` sub-model):

```python
# Tavily web search (Phase 20, AGENT-10) ───────────────────────────────────────
tavily_api_key:        str = ""
tavily_search_depth:   str = "basic"   # SDK accepts: basic | fast | advanced | ultra-fast
tavily_max_results:    int = 5
```

**Settings-construction notes (existing module patterns):**
- `BaseSettings` base class auto-loads from `.env` chain (`settings.py:50-55`); env-var binding is automatic via case-insensitive name match (`TAVILY_API_KEY` ↔ `tavily_api_key`).
- `extra="ignore"` (settings.py:53) — extra env vars don't crash startup; safe for incremental rollouts.
- No `field_validator` required for empty default `str = ""` — D-03 says empty key is observable behavior, not a startup error (`tavily_disabled` ToolResult).

---

### `tests/unit/test_web_search_tool.py` (rewrite — test, request-response)

**Primary analog:** `tests/unit/test_retrieve_tool.py` (sibling tool unit test — same class-grouped structure, same `_ctx()` factory, same `pytest.mark.asyncio`).

**Secondary analog:** existing `tests/unit/test_web_search_tool.py` (placeholder version) — keeps the registry/classvar/parameters_schema test classes untouched; replaces only the `TestWebSearchToolRun` class with real-impl tests.

**Tertiary analog (consumer-path monkeypatch):** `tests/unit/test_agent_sse.py:141-169` — locks the v1.3 D-04 mock-at-consumer pattern.

#### `_ctx()` factory pattern (from `test_web_search_tool.py:21-27`, kept):

```python
def _ctx() -> ToolContext:
    return ToolContext(
        req=GenerationRequest(query="q"),
        tf={},
        retriever=object(),
        llm=object(),
    )
```

#### Class-grouped test layout pattern (from `test_retrieve_tool.py:131-298`):

```python
class TestWebSearchToolRegistration:
    def test_web_search_tool_registered(self) -> None: ...
    def test_web_search_tool_name_classvar(self) -> None: ...
    # description / parameters_schema assertions

class TestWebSearchToolRun:
    @pytest.mark.asyncio
    async def test_happy_path_returns_chunks(self, monkeypatch) -> None: ...
    @pytest.mark.asyncio
    async def test_429_yields_quota_exhausted(self, monkeypatch) -> None: ...
    # 5xx-then-success / 5xx-final-failure / mapping / is_error / metadata.kind
```

#### Consumer-path mocking pattern (from `test_agent_sse.py:141-169`):

```python
monkeypatch.setattr("services.pipeline.get_planner",       lambda: planner)
monkeypatch.setattr("services.pipeline.get_executor",      lambda: executor)
monkeypatch.setattr("services.pipeline.get_llm_client",    lambda: _LLM())
```

**Phase 20 adaptation** (CONTEXT D-05 / D-07 — patch the singleton factory and the module-level settings binding):

```python
# Stub settings (D-07: module-level settings is the patch target)
class _StubSettings:
    tavily_api_key = "fake-key"
    tavily_search_depth = "basic"
    tavily_max_results = 5

monkeypatch.setattr("services.agent.tools.web_search.settings", _StubSettings())

# Stub Tavily client (D-05: patch the factory, not the SDK)
class _StubTavilyClient:
    async def search(self, **kwargs): return {"results": [...]}

monkeypatch.setattr(
    "services.agent.tools.web_search.get_tavily_client",
    lambda: _StubTavilyClient(),
)
```

#### Tavily fixture shape (from CONTEXT canonical_refs → STACK.md):

```python
{
    "query": "...",
    "results": [
        {"title": "...", "url": "https://...", "content": "snippet text",
         "score": 0.91, "raw_content": "...", "favicon": "..."},
        ...
    ],
    "response_time": 0.42,
}
```

#### Test branch coverage targets (CONTEXT integration_points):

| Test | Branch | Target metadata |
|------|--------|-----------------|
| settings-disabled | empty `tavily_api_key` short-circuit | `is_error=True`, `kind="tavily_disabled"`, `chunks=[]` |
| 200 happy path | full Tavily response | `is_error=False`, `chunks=N`, no `kind` key |
| 429 | `httpx.HTTPStatusError(status_code=429)` | `kind="quota_exhausted"` |
| 5xx final failure | three 500s through tenacity, `RetryError` raised | `kind="web_search_failed"` |
| 5xx-then-200 | first attempt 500, second 200 | retry succeeds, no `kind` key |
| RetrievedChunk mapping | snippet → `content`, url → `metadata.source`, title → `metadata.title`, `chunk_type="web"`, `page_number=None`, `final_score == result.score`, `retrieval_method="web"`, `chunk_id` matches `^web:[0-9a-f]{16}$`, `doc_id="web"` | per-field assertions |
| Redaction | `metadata` dict contains no key whose value is a header/body/traceback string | assert no `Authorization` substring anywhere in JSON-serialized result |

---

### `tests/integration/test_planner_picks_web_search.py` (NEW — test, integration)

**Analog:** `tests/integration/test_agent_pipeline_parallel.py` (live OpenAI agent integration — same `pytestmark = [pytest.mark.integration]` marker, same lazy-import-after-monkeypatch pattern, same `from services.pipeline import AgentQueryPipeline` consumer path).

**However**, CONTEXT D-04 specifies **mocking at the consumer path** (not live LLM) for SC3 — so the structural shape comes from `test_agent_sse.py:178-220` (the smoke-sequence pattern). Integration here means "Planner + Executor + Registry + AGENT_TOOL_ALLOWLIST exercised end-to-end with a stubbed LLM".

#### Module-level marker pattern (from `test_agent_pipeline_parallel.py:29`):

```python
pytestmark = [pytest.mark.integration]
```

#### Test fixture pair (CONTEXT D-04 — two recorded fixtures):

```python
@pytest.mark.asyncio
async def test_realtime_query_picks_web_search(monkeypatch) -> None:
    """SC3-a: 'What's the weather in Beijing today?' → planner picks web_search."""
    # Mock LLM at consumer path: services.agent.planner.<llm_attr> (or v1.4 Phase 16
    # Planner shape — verified at plan time). Returns a canned tool_use block whose
    # first ToolCall.name == "web_search".
    ...
    plan = await planner.plan(req=req, ...)
    assert plan.steps[0].name == "web_search"


@pytest.mark.asyncio
async def test_in_corpus_query_picks_search_knowledge_base(monkeypatch) -> None:
    """SC3-b: 'GB standard §3.10 透光面 definition' → planner picks search_knowledge_base."""
    ...
    plan = await planner.plan(req=req, ...)
    assert plan.steps[0].name == "search_knowledge_base"
```

#### Consumer-path mocking pattern (from `test_agent_sse.py:141-169`):

The exact `services.agent.planner.<llm_attr>` symbol is plan-time-discoverable from the v1.4 Phase 16 `Planner` class shape. **DO NOT** mock `BaseLLMClient` directly or `services.agent.tools.web_search.get_tavily_client` for this test — the assertion is "planner CHOSE web_search", not "web_search returned X". The choice happens before any tool runs.

---

## Shared Patterns

### Tenacity retry decorator (cross-cutting)

**Source:** `services/vectorizer/embedder.py:48-59` + `services/generator/llm_client.py:275-280`.
**Apply to:** `WebSearchTool._tavily_search` only (D-08 — narrow scope).

```python
from tenacity import retry, stop_after_attempt, wait_random_exponential

@retry(
    stop=stop_after_attempt(3),                                   # v1.0+ baseline
    wait=wait_random_exponential(multiplier=1, max=10),           # llm_client.py:277 max
    reraise=True,                                                 # D-08 — caller catches the underlying exception
)
async def _tavily_search(query: str) -> dict[str, Any]: ...
```

**Why `reraise=True`:** Phase 20 D-08 specifies the caller (`run()`) catches the **underlying** exception type (httpx / Tavily SDK exception class), not `tenacity.RetryError`. This is the same shape as `embedder.py:48` (no `reraise` because the caller `embed_batch` re-wraps via `asyncio.gather(return_exceptions=True)`); for direct-await callers, `reraise=True` is the v1.0 idiom.

### Lazy module-level singleton (cross-cutting)

**Source:** `services/agent/tools/registry.py:106-118` (`get_tool_registry`).
**Apply to:** `services/agent/tools/web_search.py::get_tavily_client` (D-05).

```python
_X: T | None = None

def get_X() -> T:
    global _X
    if _X is None:
        _X = T(...)
    return _X
```

Mirrors v1.4 `get_planner` / `get_executor` / `get_tool_registry`.

### Module-level `settings` import (cross-cutting)

**Source:** `services/generator/llm_client.py:343` (`settings.openai_api_key` read inside `__init__`); `services/vectorizer/embedder.py:79` (`settings.openai_api_key`).
**Apply to:** `services/agent/tools/web_search.py` top-of-module (D-07 — `ToolContext` shape NOT extended).

```python
from config.settings import settings

# Inside async functions:
settings.tavily_api_key   # read at call time, not import time
```

Test override:

```python
monkeypatch.setattr("services.agent.tools.web_search.settings", _StubSettings())
```

### `loguru` logger pattern (cross-cutting)

**Source:** every `services/**/*.py` adapter (`embedder.py:12`, `llm_client.py:21`, `retrieve.py:22`).

```python
from loguru import logger

logger.error(f"[WebSearchTool] tavily 5xx after retries: {exc!r}")
```

**Phase 20 redaction rule (D-15):** never `logger.error(f"... {exc.response.text}")` or `f"... {exc.response.headers}"`. Log only `exc.__class__.__name__` and HTTP status code.

### Pydantic V2 `frozen=True` `ConfigDict` (cross-cutting)

**Source:** `utils/models.py:375` (`ToolResult`), `:396` (`ToolContext`).
**Apply to:** Every `ToolResult` constructed in `WebSearchTool.run()` is automatically frozen — no per-call ConfigDict needed.

---

## No Analog Found

None. All 8 files have a strong analog within the existing codebase.

---

## Metadata

**Analog search scope:**
- `services/agent/tools/` (4 files)
- `services/generator/`, `services/vectorizer/`, `services/nlu/`, `services/extractor/`, `services/knowledge/` (tenacity grep)
- `tests/unit/`, `tests/integration/`
- `config/settings.py`, `requirements.txt`, `.env.docker`, `static/ui.js`
- `utils/models.py` (ToolResult / RetrievedChunk / ChunkMetadata / ToolContext)
- `services/pipeline.py:580-700` (allowlist + agent system prompt context)

**Files scanned:** ~25 (read with offset/limit where >150 lines).

**Pattern extraction date:** 2026-05-10.

---

## PATTERN MAPPING COMPLETE

**Phase:** 20 — WebSearchTool Real Implementation (Tavily)
**Files classified:** 8
**Analogs found:** 8 / 8

### Coverage
- Files with exact analog: 7
- Files with role-match analog (different data flow): 1 (integration test — closest agent-integration test uses live OpenAI; Phase 20 mocks at consumer path per D-04, structural match preserved)
- Files with no analog: 0

### Key Patterns Identified
- All concrete tools subclass `BaseTool` with three ClassVars + `@get_tool_registry().register`; Phase 17 `RetrieveTool` is the byte-shape twin for `WebSearchTool.run()`.
- Tenacity `@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=10))` is the v1.0+ baseline for all external calls; D-08 scopes the decorator to a single private async helper (`_tavily_search`) outside the typed-error mapping logic.
- v1.3 D-04 "mock at consumer path" idiom (`monkeypatch.setattr("services.<mod>.<dep>", ...)`) carries verbatim into Phase 20 unit + integration tests; the patch points are `services.agent.tools.web_search.settings` and `services.agent.tools.web_search.get_tavily_client`.
- `RetrievedChunk(metadata=ChunkMetadata(...))` accepts `chunk_type="web"` and `page_number=None` without schema change; Tavily score passes through to `final_score`; `retrieval_method="web"` enables future per-method analytics.
- D-15 source-side redaction: typed-error `ToolResult` construction is **inline** in `run()` (NOT via `BaseTool._build_error_result`) so the error `content` / `metadata` strings never carry Tavily exception text, headers, or tracebacks.

### File Created
`.planning/phases/20-websearchtool-real-implementation-tavily/20-PATTERNS.md`

### Ready for Planning
Pattern mapping complete. Planner can now reference analog patterns in PLAN.md files for each of the 8 surgery surfaces (web_search.py rewrite, allowlist literal edit, ui.js ternary, requirements.txt pin, .env.docker placeholder, settings.py 3-field add, unit test rewrite, integration test new file).
