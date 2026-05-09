# Phase 12: Fork-Agent Swarm - Pattern Map

**Mapped:** 2026-05-08
**Files analyzed:** 4 new/modified files
**Analogs found:** 4 / 4

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/pipeline.py` (add `SwarmQueryPipeline` + `get_swarm_pipeline()`) | service / pipeline | event-driven (fan-out/gather) | `services/pipeline.py` — `AgentQueryPipeline` (lines 532–861) | exact |
| `utils/models.py` (add `swarm_mode: bool = False` to `GenerationRequest`) | model | — | `utils/models.py` — `GenerationRequest` (lines 205–223); `agent_mode: bool = False` at line 214 | exact |
| `tests/unit/test_swarm_pipeline.py` | test | — | `tests/unit/test_agent_pipeline_refactor.py` | exact |
| `tests/integration/test_swarm_pipeline_e2e.py` | test | — | `tests/integration/test_agent_pipeline_parallel.py` | exact |

---

## Pattern Assignments

### `services/pipeline.py` — `SwarmQueryPipeline` class + `get_swarm_pipeline()` factory

**Analog:** `services/pipeline.py`, `AgentQueryPipeline` class (lines 532–861)

**Imports pattern** (lines 14–79) — these are already present; `SwarmQueryPipeline` reuses all of them plus adds `json`, `re`, and `dataclasses`:

```python
# Already in file — reuse verbatim:
from __future__ import annotations
import asyncio, hashlib, json, re, time, uuid
from dataclasses import dataclass
from typing import Any
import anthropic, httpx, openai
from loguru import logger
from config.settings import settings
from services.audit.audit_service import AuditResult, get_audit_service
from services.generator.llm_client import get_llm_client
from services.memory.memory_service import ConversationTurn, get_memory_service
from services.retriever.retriever import get_retriever
from services.tenant.tenant_service import get_tenant_service
from utils.models import (
    AgenticTurn, GenerationRequest, GenerationResponse,
    RetrievedChunk, ToolCall,
)
```

**Class-level constants (OPS-01 pattern)** — copy `MAX_ITERATIONS` at line 548, rename for swarm:

```python
# Analog: AgentQueryPipeline line 548
MAX_ITERATIONS = 5  # existing

# SwarmQueryPipeline equivalent:
MAX_SWARM_AGENTS: int = int(getattr(settings, "max_swarm_agents", 5))
MAX_SWARM_TURNS_PER_AGENT: int = int(getattr(settings, "max_swarm_turns_per_agent", 5))
```

**`__init__` pattern** (lines 609–614) — identical dependency set:

```python
# Analog: AgentQueryPipeline.__init__ lines 609-614
def __init__(self) -> None:
    self._retriever  = get_retriever()
    self._llm        = get_llm_client()
    self._memory     = get_memory_service()
    self._audit      = get_audit_service()
    self._tenant_svc = get_tenant_service()
```

**`run()` method — preamble** (lines 616–631) — copy tenant filter + trace_id setup verbatim:

```python
# Analog: AgentQueryPipeline.run() lines 616-631
async def run(self, req: GenerationRequest) -> GenerationResponse:
    trace_id  = str(uuid.uuid4())[:8]
    tenant_id = getattr(req, "tenant_id", "")
    user_id   = getattr(req, "user_id",   "")
    t0        = time.perf_counter()

    extraction = extract_filters(req.query)
    tf = self._tenant_svc.get_tenant_filter(tenant_id)
    if req.filters:
        tf = {**(tf or {}), **req.filters}
    if extraction.filters:
        tf = {**(tf or {}), **extraction.filters}
```

**`asyncio.gather` with `return_exceptions=True` + error dispatch** (lines 719–745) — the sub-agent fan-out is a direct scale-up of the per-turn tool gather pattern:

```python
# Analog: AgentQueryPipeline.run() lines 719-745
tool_coros = [
    self._execute_tool_call(tc, tf or {}, req)
    for tc in turn.tool_calls
]
tool_outputs = await asyncio.gather(*tool_coros, return_exceptions=True)

for tc, output in zip(turn.tool_calls, tool_outputs):
    if isinstance(output, BaseException):
        tool_results.append({
            "type":        "tool_result",
            "tool_use_id": tc.id,
            "content":     f"工具执行失败:{type(output).__name__}: {output}",
            "is_error":    True,
        })
    else:
        chunks, ctx_text = output
        all_chunks.extend(chunks)
        tool_results.append({"type": "tool_result", "tool_use_id": tc.id, "content": ctx_text})
# Swarm fan-out replaces tool_coros with sub-agent coros; same gather + isinstance check.
```

**Narrow exception tuple (ERR-01)** (lines 668–680):

```python
# Analog: AgentQueryPipeline.run() lines 668-680
except (
    anthropic.APIError,
    openai.APIError,
    httpx.HTTPError,
    asyncio.TimeoutError,
) as exc:
    logger.error(f"[Agent] call_agentic_turn failed iter={iteration+1}: {exc!r}")
    answer = "抱歉，智能助手在处理您的请求时遇到了错误，请稍后重试。"
    break
# In SwarmQueryPipeline._run_sub_agent: same tuple, different logger prefix [Swarm].
```

**`_AGENT_TOOLS` and `_AGENT_SYSTEM`** (lines 550–607) — `SwarmQueryPipeline` reads these directly from `AgentQueryPipeline` or they are extracted as module-level constants shared by both classes. Do NOT copy-paste; reference by import or module-level alias.

**`_execute_tool_call` signature** (lines 797–838) — `SwarmQueryPipeline` either (a) holds a copy as an instance method or (b) calls it on a shared `AgentQueryPipeline` instance. Copy signature exactly:

```python
# Analog: AgentQueryPipeline._execute_tool_call lines 797-838
async def _execute_tool_call(
    self,
    tc: ToolCall,
    tf: dict[str, Any],
    req: GenerationRequest,
) -> tuple[list[RetrievedChunk], str]:
    args       = tc.arguments or {}
    query_str  = args.get("query") or args.get("refined_query", req.query)
    top_k      = min(int(args.get("top_k", 5)), 10)
    # ... retrieve + format XML blocks ...
    return chunks, ctx_text
```

**Audit call pattern** (lines 776–781) — `log_query` has a FIXED signature (no `**kwargs`). Swarm must call `self._audit.log(AuditEvent(...))` directly for extra fields:

```python
# Analog: AgentQueryPipeline.run() lines 776-781
await self._audit.log_query(
    user_id=user_id, tenant_id=tenant_id,
    query=req.query, trace_id=trace_id,
    result=AuditResult.SUCCESS, latency_ms=total_ms,
    sources_count=len(all_chunks), intent="agent",
)
# SwarmQueryPipeline: call self._audit.log(AuditEvent(..., detail={swarm fields})) directly
# because log_query does not accept swarm_n, per_agent_turns, etc.
# See: services/audit/audit_service.py lines 116-137 for self._audit.log() signature.
```

**`GenerationResponse` return** (lines 787–795) — copy exactly:

```python
# Analog: AgentQueryPipeline.run() lines 787-795
return GenerationResponse(
    answer=answer,
    sources=all_chunks[:req.top_k],
    session_id=req.session_id,
    query=req.query,
    latency_ms=total_ms,
    trace_id=trace_id,
    model=settings.active_model,
)
```

**`get_swarm_pipeline()` factory** (lines 857–861) — copy `get_agent_pipeline()` exactly, substituting names:

```python
# Analog: get_agent_pipeline() lines 857-861
_agent_pipeline = None
def get_agent_pipeline():
    global _agent_pipeline
    if _agent_pipeline is None:
        _agent_pipeline = AgentQueryPipeline()
    return _agent_pipeline

# SwarmQueryPipeline version:
_swarm_pipeline = None
def get_swarm_pipeline():
    global _swarm_pipeline
    if _swarm_pipeline is None:
        _swarm_pipeline = SwarmQueryPipeline()
    return _swarm_pipeline
```

---

### `utils/models.py` — add `swarm_mode: bool = False` to `GenerationRequest`

**Analog:** `utils/models.py`, `GenerationRequest` lines 205–223; specifically `agent_mode: bool = False` at line 214.

**Field addition pattern** (line 214):

```python
# Analog: utils/models.py line 213-214
agent_mode:   bool                          = False   # True 時使用 Agentic 工具循環
# Add immediately after:
swarm_mode:   bool                          = False   # True 時使用 Fork-Agent Swarm
```

No validator needed (plain bool field). Pydantic V2 parses `False` by default. Follow exact column-alignment style of adjacent fields.

---

### `tests/unit/test_swarm_pipeline.py`

**Analog:** `tests/unit/test_agent_pipeline_refactor.py` (entire file — 7 test contracts, same structure)

**File header / imports pattern** (lines 1–37):

```python
# Analog: test_agent_pipeline_refactor.py lines 1-37
from __future__ import annotations
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest
from loguru import logger as loguru_logger
from utils.models import (
    AgenticTurn, ChunkMetadata, GenerationRequest,
    GenerationResponse, RetrievedChunk, ToolCall,
)
```

**Helper factories** (lines 45–76) — reuse `_chunk()`, `_turn()`, `_tool_call()` verbatim:

```python
# Analog: test_agent_pipeline_refactor.py lines 45-76
def _chunk(chunk_id: str, doc_id: str = "d1", title: str = "t") -> RetrievedChunk: ...
def _turn(*, tool_calls=None, stop_reason="text_only", text="") -> AgenticTurn: ...
def _tool_call(call_id: str, name: str = "search_knowledge_base", **args) -> ToolCall: ...
```

**`mock_pipeline` fixture pattern** (lines 79–106) — replace `AgentQueryPipeline` with `SwarmQueryPipeline`; add coordinator mock (`_llm.chat = AsyncMock`) alongside `call_agentic_turn`:

```python
# Analog: test_agent_pipeline_refactor.py lines 79-106
@pytest.fixture
def mock_pipeline():
    from services.pipeline import AgentQueryPipeline   # → SwarmQueryPipeline
    from services.memory.memory_service import MemoryContext

    pipe = AgentQueryPipeline.__new__(AgentQueryPipeline)  # → SwarmQueryPipeline
    pipe._llm = MagicMock()
    pipe._llm.call_agentic_turn = AsyncMock()
    pipe._llm.chat = AsyncMock()            # added for swarm: coordinator + synthesis
    pipe._retriever = MagicMock()
    pipe._retriever.retrieve = AsyncMock(return_value=([], {}))
    pipe._memory = MagicMock()
    pipe._memory.load_context = AsyncMock(return_value=MemoryContext(...))
    pipe._memory.save_turn = AsyncMock()
    pipe._audit = MagicMock()
    pipe._audit.log_query = AsyncMock()
    pipe._audit.log = AsyncMock()           # added: swarm calls log() directly
    pipe._tenant_svc = MagicMock()
    pipe._tenant_svc.get_tenant_filter = MagicMock(return_value={})
    return pipe
```

**`gen_req` fixture pattern** (lines 109–117) — set `swarm_mode=True` instead of `agent_mode=True`:

```python
# Analog: test_agent_pipeline_refactor.py lines 109-117
@pytest.fixture
def gen_req():
    return GenerationRequest(
        query="测试 多维度 查询",
        top_k=5,
        swarm_mode=True,     # was: agent_mode=True
        tenant_id="t1",
        user_id="u1",
    )
```

**Concurrent execution test pattern** (lines 185–224) — reuse `asyncio.Event` + counter pattern:

```python
# Analog: test_agent_pipeline_refactor.py lines 185-224
async def test_two_tool_calls_run_concurrently(mock_pipeline, gen_req):
    started_event = asyncio.Event()
    pending_count = {"n": 0}
    async def slow_retrieve(**kwargs):
        pending_count["n"] += 1
        if pending_count["n"] >= 2:
            started_event.set()
        await asyncio.wait_for(started_event.wait(), timeout=2.0)
        return ([_chunk(f"c-{pending_count['n']}")], {})
    # In swarm test: replace slow_retrieve with slow_call_agentic_turn
    # Same Event + counter logic, different mock target.
```

**Test markers** (lines 125, 157, 185) — always `@pytest.mark.unit` + `@pytest.mark.asyncio`:

```python
# Analog: every test in test_agent_pipeline_refactor.py
@pytest.mark.unit
@pytest.mark.asyncio
async def test_...(mock_pipeline, gen_req):
```

---

### `tests/integration/test_swarm_pipeline_e2e.py`

**Analog:** `tests/integration/test_agent_pipeline_parallel.py` (entire file — same integration pattern)

**Module-level marker** (line 29) — matches pytest.ini `addopts = -m "not integration"`:

```python
# Analog: test_agent_pipeline_parallel.py line 29
pytestmark = [pytest.mark.integration]
```

**Provider override + singleton reset pattern** (lines 47–56):

```python
# Analog: test_agent_pipeline_parallel.py lines 47-56
monkeypatch.setenv("LLM_PROVIDER", "openai")
import services.generator.llm_client as llm_mod
llm_mod._llm_instance = None
# SwarmQueryPipeline integration: also reset _swarm_pipeline singleton:
import services.pipeline as pipe_mod
pipe_mod._swarm_pipeline = None
pipeline = SwarmQueryPipeline()
```

**Assertion pattern** (lines 33–80) — assert `resp.answer` is non-empty string, `resp.sources` is list, latency in reasonable range. Add swarm-specific: assert coordinator was called, synthesis answer references sub-question keywords.

---

## Shared Patterns

### Narrow Exception Tuple (ERR-01)
**Source:** `services/pipeline.py` lines 668–674
**Apply to:** `SwarmQueryPipeline._run_sub_agent` inner loop
```python
except (
    anthropic.APIError,
    openai.APIError,
    httpx.HTTPError,
    asyncio.TimeoutError,
) as exc:
```

### `asyncio.gather` with `return_exceptions=True` + `isinstance(res, BaseException)` check
**Source:** `services/pipeline.py` lines 719–745
**Apply to:** `SwarmQueryPipeline.run()` fan-out, `SwarmQueryPipeline._run_sub_agent()` tool loop

### Singleton factory (`global _x; if _x is None: _x = Cls()`)
**Source:** `services/pipeline.py` lines 841–861
**Apply to:** `get_swarm_pipeline()`

### `AuditService.log(AuditEvent(...))` direct call for extra `detail` fields
**Source:** `services/audit/audit_service.py` lines 116–137 (`log` method), lines 139–167 (`log_query` fixed signature — NO **kwargs)
**Apply to:** `SwarmQueryPipeline.run()` audit step — do NOT call `log_query`; call `log()` directly with a fully constructed `AuditEvent` carrying `detail` dict with swarm telemetry fields.

### `time.perf_counter()` latency measurement
**Source:** `services/pipeline.py` lines 620, 758
**Apply to:** `swarm_latency_ms` and `synthesis_latency_ms` measurements in `SwarmQueryPipeline.run()`

### `__new__` fixture construction (bypass `__init__` for mocking)
**Source:** `tests/unit/test_agent_pipeline_refactor.py` line 85
**Apply to:** `mock_swarm_pipeline` fixture in `tests/unit/test_swarm_pipeline.py`

---

## No Analog Found

None — all four files have exact analogs in the codebase.

---

## Metadata

**Analog search scope:** `services/`, `utils/`, `tests/unit/`, `tests/integration/`
**Key files read:** `services/pipeline.py` (lines 1–80, 530–862), `utils/models.py` (lines 200–250), `services/audit/audit_service.py` (lines 100–167), `tests/unit/test_agent_pipeline_refactor.py` (lines 1–224), `tests/integration/test_agent_pipeline_parallel.py` (lines 1–60)
**Pattern extraction date:** 2026-05-08
