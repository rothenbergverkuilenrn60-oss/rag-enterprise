# Phase 13: LLM Filter Fallback - Pattern Map

**Mapped:** 2026-05-09
**Files analyzed:** 4 new/modified files
**Analogs found:** 4 / 4

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/nlu/filter_extractor.py` (REFACTOR: add `FilterExtractor` class + `ExtractionResult` + `_FILTER_EXTRACT_SYSTEM` + `get_filter_extractor()`) | service / nlu | request-response (regex → cache → LLM) | `services/pipeline.py` `SwarmQueryPipeline` (lines 916–1264) | exact (async LLM + JSON parse + ERR-01) |
| `services/pipeline.py` (4-callsite migration at lines 317, 478, 674, 1166) | service / pipeline | — | `services/pipeline.py` lines 317–318, 346, 414 (existing `extract_filters` + `cache_get`/`cache_set` patterns) | exact (in-place patch) |
| `tests/unit/test_filter_extractor.py` (extend with `TestFilterExtractor` class) | test / unit | — | `tests/unit/test_swarm_pipeline.py` (lines 73–99 fixture, 118–145 mark/assert pattern) + `tests/unit/test_nlu_service.py` (lines 17–23 autouse reset) | exact |
| `tests/integration/test_filter_extractor_llm.py` (NEW) | test / integration | — | `tests/integration/test_swarm_pipeline_e2e.py` (entire file — 73 lines) | exact |

---

## Pattern Assignments

### `services/nlu/filter_extractor.py` — `FilterExtractor` class + `get_filter_extractor()` factory

**Primary analog:** `services/pipeline.py` `SwarmQueryPipeline` (lines 916–1264) — closest async-LLM-with-cache pattern. Secondary: `services/extractor/ocr_engine.py` (lazy singleton via global+getter at lines 65–72).

**Imports pattern** — extend the existing module's imports. Mirror analog at `services/pipeline.py:14–58`:

```python
# Source: services/pipeline.py lines 14-58 (project canonical async-LLM imports)
from __future__ import annotations
import asyncio, json, re
from dataclasses import dataclass, field
from typing import Literal

import anthropic, httpx, openai
from loguru import logger

from utils.cache import cache_get, cache_set
# Lazy import inside __init__ to avoid circular dep (llm_client doesn't import nlu):
#   from services.generator.llm_client import get_llm_client
```

**Class-level constants (OPS-01 pattern)** — copy from `SwarmQueryPipeline` at `services/pipeline.py:926–927`:

```python
# Source: services/pipeline.py lines 926-927
class SwarmQueryPipeline:
    MAX_SWARM_AGENTS: int = int(getattr(settings, "max_swarm_agents", 5))
    MAX_SWARM_TURNS_PER_AGENT: int = int(getattr(settings, "max_swarm_turns_per_agent", 5))
```

For Phase 13: `_FILTER_EXTRACT_SYSTEM` is a module-level prompt constant (string), not a settings-backed int. No new env vars needed (CONTEXT.md `<code_context>`: `cache_ttl_sec`, `cache_enabled` already exist). Constant lives as a module-level frozen string above the class definition; no `getattr(settings, ...)` wrapper.

**`__init__` pattern (lazy LLM client init)** — copy from `SwarmQueryPipeline` at `services/pipeline.py:929–934`:

```python
# Source: services/pipeline.py lines 929-934
def __init__(self) -> None:
    self._retriever  = get_retriever()
    self._llm        = get_llm_client()
    self._memory     = get_memory_service()
    self._audit      = get_audit_service()
    self._tenant_svc = get_tenant_service()
```

For Phase 13 reduce to a single dependency:
```python
def __init__(self) -> None:
    from services.generator.llm_client import get_llm_client  # lazy to avoid circular import
    self._llm = get_llm_client()
```

**Async method body pattern (LLM call + JSON parse)** — copy from `SwarmQueryPipeline._decompose` at `services/pipeline.py:944–965`:

```python
# Source: services/pipeline.py lines 944-965
raw: str = await self._llm.chat(
    system=_COORDINATOR_SYSTEM,
    user=query,
    temperature=0.0,
    task_type="generate",   # Phase 13 uses task_type="nlu" → Haiku
)

# Extract first JSON array substring (LLM may wrap in prose despite instruction).
match = re.search(r"\[.*\]", raw, re.DOTALL)
if match is None:
    logger.warning(f"[Swarm] coordinator returned no JSON array; falling back to N=1. raw={raw[:200]!r}")
    return [query]

try:
    parsed = json.loads(match.group(0))
except (json.JSONDecodeError, TypeError) as exc:
    logger.warning(f"[Swarm] coordinator JSON parse failed: {exc!r}; falling back to N=1. raw={match.group(0)[:200]!r}")
    return [query]

if not isinstance(parsed, list):
    logger.warning(f"[Swarm] coordinator returned non-list ({type(parsed).__name__}); falling back to N=1.")
    return [query]
```

For Phase 13: substitute `\[.*\]` → `\{.*\}`, `task_type="generate"` → `task_type="nlu"` (D-09), `_COORDINATOR_SYSTEM` → `_FILTER_EXTRACT_SYSTEM`, fallback return `[query]` → `ExtractionResult(filters={}, semantic_query=query, fallback_source=None)` (D-14).

**Cache lookup + write pattern** — copy from `services/pipeline.py:340–414`:

```python
# Source: services/pipeline.py lines 340-414 (existing query-result cache, namespace="query")
cache_key = {
    "q": effective_query,
    "top_k": req.top_k,
    "filters": {**(req.filters or {}), **extraction.filters},
    "tenant": tenant_id,
}
cached = await cache_get("query", cache_key)
if cached:
    cache_hit_total.labels(result="hit").inc()
    return GenerationResponse(**cached)
cache_hit_total.labels(result="miss").inc()
# ... LLM work ...
await cache_set("query", cache_key, response)
```

For Phase 13: namespace `"query"` → `"nlu:filter"`; payload is the raw `query: str` (let `_make_cache_key` MD5-hash it — no manual hashing per RESEARCH.md "Don't Hand-Roll" table); cached value is a plain dict `{"filters": ..., "semantic_query": ...}` — restore as `ExtractionResult(**cached, fallback_source="llm")`. **Don't cache empty/failed results** (RESEARCH.md Pitfall 1) — gate `cache_set` behind `if filters:`.

**Narrow exception tuple (ERR-01) — LLM call domain** — copy verbatim from `SwarmQueryPipeline._run_sub_agent` at `services/pipeline.py:1012–1020`:

```python
# Source: services/pipeline.py lines 1012-1020
except (
    anthropic.APIError,
    openai.APIError,
    httpx.HTTPError,
    asyncio.TimeoutError,
) as exc:
    logger.error(f"[Swarm] sub-agent {agent_index} call_agentic_turn failed iter={turns}: {exc!r}")
    answer = f"[Sub-agent {agent_index} failed: {exc!r}]"
    break
```

For Phase 13: same tuple; logger prefix `[FilterExtractor]`; on catch return `ExtractionResult(filters={}, semantic_query=query, fallback_source=None)` (D-14 — never raise, log WARNING).

**Narrow exception tuple — parse domain** — copy from `SwarmQueryPipeline._decompose` at `services/pipeline.py:957–965` and extend:

```python
# Source: services/pipeline.py lines 957-961 (parse-domain narrow tuple)
try:
    parsed = json.loads(match.group(0))
except (json.JSONDecodeError, TypeError) as exc:
    logger.warning(f"[Swarm] coordinator JSON parse failed: {exc!r}; falling back to N=1. raw={match.group(0)[:200]!r}")
    return [query]
```

Phase 13 widens the tuple per RESEARCH.md §Pattern 4 — `(json.JSONDecodeError, AttributeError, TypeError, ValueError)`. `AttributeError` covers `m.group()` when `re.search` returns `None`; `ValueError` covers `int(parsed["page_number"])` coercion against non-numeric string (Pitfall 2).

**Singleton factory pattern** — copy verbatim from `services/pipeline.py:890–910` and `services/pipeline.py:1259–1264`:

```python
# Source: services/pipeline.py lines 890-910 (project canonical singleton pattern)
_query_pipeline  = None
_agent_pipeline  = None

def get_query_pipeline():
    global _query_pipeline
    if _query_pipeline is None:
        _query_pipeline = QueryPipeline()
    return _query_pipeline

def get_agent_pipeline():
    global _agent_pipeline
    if _agent_pipeline is None:
        _agent_pipeline = AgentQueryPipeline()
    return _agent_pipeline
```

```python
# Source: services/pipeline.py lines 1259-1264 (Phase 12 swarm singleton)
_swarm_pipeline = None
def get_swarm_pipeline():
    global _swarm_pipeline
    if _swarm_pipeline is None:
        _swarm_pipeline = SwarmQueryPipeline()
    return _swarm_pipeline
```

For Phase 13: `_filter_extractor: FilterExtractor | None = None`; `def get_filter_extractor() -> FilterExtractor: ...`. Mirror exact name/structure. (Note: do NOT use `@lru_cache` like `services/extractor/ocr_engine.py:98` — pipeline-style global+getter is the dominant project pattern, see RESEARCH.md §Pattern 5.)

**Frozen dataclass (`ExtractionResult`)** — extend the existing dataclass in same file at `services/nlu/filter_extractor.py:33–43`:

```python
# Source: services/nlu/filter_extractor.py lines 33-43 (existing dataclass — KEEP)
@dataclass
class FilterExtractionResult:
    """Result of regex-first filter extraction.

    `filters` carries typed values (page_number: int, section_id: str) ready
    for vector_store.search(filters=…). `semantic_query` is the user query
    with filter tokens removed; falls back to the original query if stripping
    produced an empty string.
    """
    filters:        dict[str, int | str] = field(default_factory=dict)
    semantic_query: str                  = ""
```

For Phase 13 add NEW dataclass alongside (don't modify existing — `extract_filters` still returns `FilterExtractionResult` per D-02):

```python
@dataclass(frozen=True)
class ExtractionResult:
    filters:         dict[str, int | str]
    semantic_query:  str
    fallback_source: Literal["regex", "llm"] | None = None
```

`frozen=True` per project coding-style immutability rule and RESEARCH.md §Pattern 1.

---

### `services/pipeline.py` — 4-callsite migration

**Analog:** `services/pipeline.py` lines 317, 478, 674, 1166 (the very lines being patched — exact in-place edits).

**Import update at line 44:**
```python
# BEFORE — services/pipeline.py:44
from services.nlu.filter_extractor import extract_filters
# AFTER
from services.nlu.filter_extractor import get_filter_extractor
```

**Callsite migration (4 sites — identical patch each)** — at lines 317, 478, 674, 1166:

```python
# Source: services/pipeline.py:317 (analog — pre-patch shape)
extraction = extract_filters(req.query)
effective_query = extraction.semantic_query
# AFTER
extraction = await get_filter_extractor().extract(req.query)
effective_query = extraction.semantic_query
```

Subsequent reads of `extraction.filters` (e.g., line 343 `"filters": {**(req.filters or {}), **extraction.filters}`) and `extraction.semantic_query` (lines 318, 479) require NO change — `ExtractionResult` exposes both fields with identical names and types (D-04 truthiness compat). Optional: append `extraction.fallback_source` to existing `logger.info` calls for AC#4 telemetry.

All 4 callsites are already inside `async def` methods (`QueryPipeline.run`, `QueryPipeline.stream`, `AgentQueryPipeline.run`, related), so `await` is the correct primitive — no `asyncio.run()` (RESEARCH.md anti-pattern).

---

### `tests/unit/test_filter_extractor.py` — extend with `TestFilterExtractor` class

**Primary analog:** `tests/unit/test_swarm_pipeline.py` (lines 73–99 fixture, 118–145 test pattern). Secondary: `tests/unit/test_nlu_service.py` lines 17–23 (autouse singleton reset).

**Existing 7 regex tests** at `tests/unit/test_filter_extractor.py:15–59` — wrap into `class TestExtractFiltersRegex:` (move existing methods inside). They continue to test the sync `extract_filters` function (D-02, frozen).

**File header / env bootstrap** — preserve the existing top-of-file pattern at `tests/unit/test_filter_extractor.py:1–12`:

```python
# Source: tests/unit/test_filter_extractor.py lines 1-12 (existing — keep)
"""
tests/unit/test_filter_extractor.py
...
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only-32c")
```

Add the imports needed for new LLM-path tests (after the env bootstrap, mirror `tests/unit/test_swarm_pipeline.py:8–11`):

```python
# Source: tests/unit/test_swarm_pipeline.py lines 8-11
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
```

**Singleton reset autouse fixture** — copy verbatim shape from `tests/unit/test_nlu_service.py:17–23`:

```python
# Source: tests/unit/test_nlu_service.py lines 17-23 (canonical singleton-reset autouse pattern)
@pytest.fixture(autouse=True)
def reset_nlu_singleton(monkeypatch):
    import services.nlu.nlu_service as mod
    yield
    for attr in ("_nlu_service", "_service"):
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, None, raising=False)
```

For Phase 13:
```python
@pytest.fixture(autouse=True)
def reset_filter_extractor_singleton(monkeypatch):
    import services.nlu.filter_extractor as mod
    yield
    monkeypatch.setattr(mod, "_filter_extractor", None, raising=False)
```

**`__new__` bypass + AsyncMock fixture** — copy from `tests/unit/test_swarm_pipeline.py:73–99`:

```python
# Source: tests/unit/test_swarm_pipeline.py lines 73-99
@pytest.fixture
def mock_pipeline() -> SwarmQueryPipeline:
    """Build a SwarmQueryPipeline with all collaborators replaced by AsyncMock."""
    pipe = SwarmQueryPipeline.__new__(SwarmQueryPipeline)
    pipe._llm = MagicMock()
    pipe._llm.call_agentic_turn = AsyncMock()
    pipe._llm.chat = AsyncMock()                  # coordinator + synthesis
    pipe._retriever = MagicMock()
    pipe._retriever.retrieve = AsyncMock(return_value=([], {}))
    pipe._memory = MagicMock()
    pipe._memory.load_context = AsyncMock(...)
    pipe._memory.save_turn = AsyncMock()
    pipe._audit = MagicMock()
    pipe._audit.log_query = AsyncMock()
    pipe._audit.log = AsyncMock()
    pipe._tenant_svc = MagicMock()
    pipe._tenant_svc.get_tenant_filter = MagicMock(return_value={})
    return pipe
```

For Phase 13 reduce to single mock — `FilterExtractor` only owns `_llm`:
```python
@pytest.fixture
def mock_extractor():
    from services.nlu.filter_extractor import FilterExtractor
    inst = FilterExtractor.__new__(FilterExtractor)   # bypass __init__ → no real LLM client
    inst._llm = MagicMock()
    inst._llm.chat = AsyncMock()
    return inst
```

**Cache patch pattern (per-test)** — analog `tests/unit/test_swarm_pipeline.py:134` shows the `with patch("services.pipeline.get_agent_pipeline")` form; for Phase 13 use `monkeypatch.setattr` to mock `cache_get` / `cache_set` at the module they were imported into:

```python
# Source: tests/unit/test_swarm_pipeline.py line 134 (module-level patch pattern)
with patch("services.pipeline.get_agent_pipeline") as mock_get_agent:
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=expected_resp)
    mock_get_agent.return_value = mock_agent
    resp = await mock_pipeline.run(gen_req)
```

For Phase 13 cache mocking inside a test:
```python
monkeypatch.setattr("services.nlu.filter_extractor.cache_get", AsyncMock(return_value=None))
monkeypatch.setattr("services.nlu.filter_extractor.cache_set", AsyncMock(return_value=True))
```

**Test marker pattern** — copy from `tests/unit/test_swarm_pipeline.py:118–119`:

```python
# Source: tests/unit/test_swarm_pipeline.py lines 118-119 (canonical marker pair)
@pytest.mark.unit
@pytest.mark.asyncio
async def test_n1_fallback_delegates_to_agent_pipeline(...) -> None:
```

Apply to all 6 new D-15 contracts (regex-hit-skips-llm, regex-miss-llm-hit, invalid-json, llm-api-exception, cache-hit-once, cache-disabled-every-miss).

**Assertion idiom for "LLM never called"** — analog at `tests/unit/test_swarm_pipeline.py:145`:

```python
# Source: tests/unit/test_swarm_pipeline.py line 145
mock_pipeline._llm.call_agentic_turn.assert_not_awaited()
```

For Phase 13 D-15 #1 (regex hit → LLM never called):
```python
mock_extractor._llm.chat.assert_not_awaited()
```

---

### `tests/integration/test_filter_extractor_llm.py` — NEW integration test

**Analog:** `tests/integration/test_swarm_pipeline_e2e.py` (entire file, 73 lines).

**Module-level marker** — copy verbatim from `tests/integration/test_swarm_pipeline_e2e.py:22`:

```python
# Source: tests/integration/test_swarm_pipeline_e2e.py line 22
pytestmark = [pytest.mark.integration]
```

Required because `pytest.ini` has `addopts = -m "not integration"` (per analog file's lines 4–7 docstring).

**Provider env override + singleton reset** — copy from `tests/integration/test_swarm_pipeline_e2e.py:38–47`:

```python
# Source: tests/integration/test_swarm_pipeline_e2e.py lines 38-47
# Force OpenAI provider (project default; assert explicitly to mirror analog).
monkeypatch.setenv("LLM_PROVIDER", "openai")

# Reset both singletons so the env override takes effect against a fresh client.
import services.generator.llm_client as llm_mod
import services.pipeline as pipe_mod
llm_mod._llm_instance = None
pipe_mod._swarm_pipeline = None

pipeline = SwarmQueryPipeline()
```

For Phase 13 substitute targets:
```python
monkeypatch.setenv("LLM_PROVIDER", "openai")
import services.generator.llm_client as llm_mod
import services.nlu.filter_extractor as fx_mod
llm_mod._llm_instance = None
fx_mod._filter_extractor = None
extractor = fx_mod.FilterExtractor()
```

**Live-LLM assertion pattern (D-15 #7, AC#5 #6)** — copy from `tests/integration/test_swarm_pipeline_e2e.py:60–73`:

```python
# Source: tests/integration/test_swarm_pipeline_e2e.py lines 60-73
resp: GenerationResponse = await pipeline.run(req)

assert isinstance(resp, GenerationResponse)
assert isinstance(resp.answer, str) and len(resp.answer) > 0, "swarm produced empty answer"
assert isinstance(resp.sources, list)
assert resp.latency_ms > 0, f"latency_ms must be positive; got {resp.latency_ms}"
assert resp.trace_id and len(resp.trace_id) > 0
```

For Phase 13 (canary query "关于第三章的内容" — RESEARCH.md A2 confirms Haiku may return either string `"3"` or int `3`):
```python
result = await extractor.extract("关于第三章的内容")
assert result.fallback_source == "llm"
assert result.filters.get("section_id") in {"3", 3}  # tolerate Haiku type drift (A2)
```

**Best-effort log + missing-key policy** — copy commentary at `tests/integration/test_swarm_pipeline_e2e.py:9–11` ("missing OPENAI_API_KEY is a CONFIGURATION ERROR and surfaces as a hard test failure, NOT a `pytest.skip`"). Phase 13 follows the same policy.

---

## Shared Patterns

### Narrow Exception Tuple — LLM call domain (ERR-01)
**Source:** `services/pipeline.py` lines 1012–1017
**Apply to:** `FilterExtractor.extract` LLM call try/except
```python
except (
    anthropic.APIError,
    openai.APIError,
    httpx.HTTPError,
    asyncio.TimeoutError,
) as exc:
```

### Narrow Exception Tuple — JSON parse domain (ERR-01)
**Source:** `services/pipeline.py` lines 957–961 (Phase 12 coordinator parse — `(json.JSONDecodeError, TypeError)`)
**Apply to:** `FilterExtractor.extract` parse try/except — Phase 13 widens to `(json.JSONDecodeError, AttributeError, TypeError, ValueError)` per RESEARCH.md §Pattern 4 (covers `m.group()` on None match and `int(parsed["page_number"])` on non-numeric).

### `re.search(r"\{.*\}", raw, re.DOTALL)` JSON-from-prose extraction
**Source:** `services/pipeline.py` line 952 (Phase 12 coordinator uses `\[.*\]` for arrays); also `services/generator/llm_client.py:138-146` `chat_with_tools` default impl uses `\{.*\}`
**Apply to:** `FilterExtractor.extract` parse step (Phase 13 wants single dict, so `\{.*\}` form)

### Singleton factory (`global _x; if _x is None: _x = Cls()`)
**Source:** `services/pipeline.py` lines 890–910 (canonical) + lines 1259–1264 (Phase 12)
**Apply to:** `get_filter_extractor()` at end of `services/nlu/filter_extractor.py`

### Cache via `utils/cache.py` — `cache_get(namespace, payload)` / `cache_set(namespace, payload, value)`
**Source:** `services/pipeline.py` lines 346, 414 (existing query-result cache, namespace `"query"`)
**Apply to:** `FilterExtractor.extract` — namespace `"nlu:filter"`, payload = raw `query: str` (let `_make_cache_key` MD5-hash; do NOT hand-roll `hashlib.sha256` per RESEARCH.md "Don't Hand-Roll" table).
**Gate:** only `cache_set` after non-empty filters (RESEARCH.md Pitfall 1 — never cache empty/failed).

### Frozen dataclass (immutability per project coding-style)
**Source:** `services/nlu/filter_extractor.py` lines 33–43 (existing `FilterExtractionResult`); RESEARCH.md §Pattern 1
**Apply to:** new `ExtractionResult` dataclass — use `@dataclass(frozen=True)` with `Literal["regex", "llm"] | None` typing for `fallback_source`.

### `task_type="nlu"` → Haiku routing
**Source:** `services/generator/llm_client.py:100` (`light_tasks = {"nlu", ...}`); CONTEXT.md D-09; RESEARCH.md Standard Stack
**Apply to:** `FilterExtractor.extract` LLM call — `await self._llm.chat(..., task_type="nlu")`

### `__new__` test fixture bypass
**Source:** `tests/unit/test_swarm_pipeline.py` line 76 (`SwarmQueryPipeline.__new__(SwarmQueryPipeline)`)
**Apply to:** `mock_extractor` fixture in `tests/unit/test_filter_extractor.py` — `FilterExtractor.__new__(FilterExtractor)` skips `__init__` → no real `get_llm_client()` call.

### Singleton reset autouse fixture
**Source:** `tests/unit/test_nlu_service.py` lines 17–23
**Apply to:** new `reset_filter_extractor_singleton` autouse fixture in `tests/unit/test_filter_extractor.py` — prevents singleton state leak across tests (RESEARCH.md Pitfall 7).

### Test marker pair `@pytest.mark.unit @pytest.mark.asyncio`
**Source:** `tests/unit/test_swarm_pipeline.py` lines 118–119 (every unit test in file)
**Apply to:** all 6 new D-15 LLM-path tests in `tests/unit/test_filter_extractor.py`

### Module-level integration marker
**Source:** `tests/integration/test_swarm_pipeline_e2e.py` line 22 — `pytestmark = [pytest.mark.integration]`
**Apply to:** `tests/integration/test_filter_extractor_llm.py` (excluded from default pytest run by `pytest.ini` `addopts`).

### Provider env override + dual singleton reset
**Source:** `tests/integration/test_swarm_pipeline_e2e.py` lines 38–47
**Apply to:** integration test setup — reset both `services.generator.llm_client._llm_instance` AND `services.nlu.filter_extractor._filter_extractor` so the env-overridden provider attaches to a fresh extractor.

---

## No Analog Found

None — every new code construct in Phase 13 has an exact in-project analog:

| Construct | Analog Citation |
|-----------|-----------------|
| Async LLM call + JSON parse + ERR-01 | `services/pipeline.py:944–965` (`SwarmQueryPipeline._decompose`) |
| Redis cache via `utils/cache.py` | `services/pipeline.py:346,414` (`QueryPipeline.run`) |
| Singleton factory | `services/pipeline.py:890–910, 1259–1264` |
| Frozen dataclass with `Literal` field | `services/nlu/filter_extractor.py:33–43` (existing dataclass shape; add `frozen=True` + `Literal` typing) |
| `__new__` test bypass + `AsyncMock` | `tests/unit/test_swarm_pipeline.py:73–99` |
| Singleton-reset autouse fixture | `tests/unit/test_nlu_service.py:17–23` |
| Live-LLM integration test | `tests/integration/test_swarm_pipeline_e2e.py` (entire file) |

---

## Metadata

**Analog search scope:** `services/nlu/`, `services/pipeline.py`, `services/extractor/`, `services/generator/`, `utils/cache.py`, `tests/unit/`, `tests/integration/`

**Key files read:**
- `services/nlu/filter_extractor.py` (lines 1–92, full file — existing regex extractor)
- `services/pipeline.py` (lines 38–58 imports, 300–470 QueryPipeline.run, 888–910 singleton factories, 916–1264 SwarmQueryPipeline + get_swarm_pipeline)
- `services/extractor/ocr_engine.py` (lines 1–120, 230–279 — singleton + lazy init via `lru_cache` and global+getter)
- `services/nlu/nlu_service.py` (singleton presence verified at 645–652)
- `utils/cache.py` (lines 1–137, full file — `cache_get`/`cache_set`/`_make_cache_key` API verified)
- `tests/unit/test_swarm_pipeline.py` (lines 1–160 — fixture, helpers, first 2 tests)
- `tests/unit/test_nlu_service.py` (lines 1–98, full file — singleton-reset autouse fixture)
- `tests/unit/test_filter_extractor.py` (lines 1–60, full file — existing 7 regex tests to wrap into `TestExtractFiltersRegex`)
- `tests/integration/test_swarm_pipeline_e2e.py` (lines 1–73, full file — integration template)

**Pattern extraction date:** 2026-05-09
