# Phase 18: SSE Planner Trace Event Stream - Pattern Map

**Mapped:** 2026-05-09
**Files analyzed:** 7
**Analogs found:** 7 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `utils/models.py` (+AgentEvent + 6 subclasses) | model | transform | `utils/models.py::ToolResult` / `ToolPlan` / `ToolCall` (same file) | exact |
| `services/pipeline.py::AgentQueryPipeline.run_streaming` | service / orchestrator | streaming (async generator) | `AgentQueryPipeline.run` (same file, line 763) | exact (sibling method) |
| `services/agent/executor.py::Executor.execute_plan_streaming` | service | streaming (async generator) | `Executor.execute_plan` (same file, line 42) | exact (sibling method) |
| `controllers/api.py` (+`/agent/v1/run/stream`) | controller | streaming (SSE) | `controllers/api.py::query_stream` (line 232) | exact |
| `tests/unit/test_agent_sse.py` | test | streaming + mock | `tests/unit/test_executor.py` | role-match |
| `tests/unit/test_executor_streaming.py` | test | streaming + mock | `tests/unit/test_executor.py` | exact (sibling test) |
| `docs/agent-architecture.md` (+ `## Event Schema Reference`) | docs | reference | existing `## Authoring Tools` section | exact |

---

## Pattern Assignments

### 1. `utils/models.py` — `AgentEvent` base + 6 concrete event classes

**Analog:** `utils/models.py::ToolResult` (lines 359-380), `ToolCall` (244-258), `ToolPlan` (291-356).

**Frozen Pydantic V2 model pattern** (lines 359-380):
```python
class ToolResult(BaseModel):
    """A single tool's output, normalized across tool implementations (AGENT-07).
    ...
    Metadata key convention (Phase 18 SSE forward-compat):
      - ``latency_ms: int``    — wall-clock ms for the tool run
      - ``chunk_count: int``   — number of chunks returned (RetrieveTool family)
    """
    model_config = ConfigDict(frozen=True)

    content:  str
    chunks:   list[Any]       = Field(default_factory=list)
    metadata: dict[str, Any]  = Field(default_factory=dict)
    is_error: bool             = False
```

**Frozen + arguments-as-dict pattern (closest to `ToolSpanStartEvent.args`)** (lines 244-258):
```python
class ToolCall(BaseModel):
    """A single tool invocation requested by the LLM in one assistant turn.
    ...
    ``id`` correlates the call to its result on the next turn (Anthropic
    ``tool_use_id``, OpenAI ``tool_call_id``). Frozen — adapters never mutate.
    """
    model_config = ConfigDict(frozen=True)

    id:        str
    name:      str
    arguments: dict[str, Any] = Field(default_factory=dict)
```

**Imports already in file** (lines 6-12):
```python
from __future__ import annotations
import time
import uuid
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
```

**Adaptation notes for AgentEvent**
- Add new section banner `# STAGE 7 — SSE Trace Events (AGENT-04, Phase 18)` after `STAGE 6 — Agentic Tool Use`.
- `event_type: ClassVar[str]` requires `from typing import ClassVar` (add to existing typing import — file already imports `Any`, `Literal`).
- Base class `AgentEvent(BaseModel)`: `model_config = ConfigDict(frozen=True)`; fields `trace_id: str`, `seq: int`, `ts_ms: int`. Do NOT declare `event_type` on base (subclasses each declare their own ClassVar).
- Each concrete class re-declares `model_config = ConfigDict(frozen=True)` (same as `ToolResult` does — Pydantic V2 V2 does not auto-inherit `model_config`).
- Concrete classes per D-09:
  - `PlannerPlanEvent`: `event_type: ClassVar[str] = "planner.plan"`, `plan: ToolPlan`
  - `ToolSpanStartEvent`: `event_type: ClassVar[str] = "tool.span.start"`, `span_id: str`, `name: str`, `args: dict[str, Any] = Field(default_factory=dict)`
  - `ToolSpanEndEvent`: `event_type: ClassVar[str] = "tool.span.end"`, `span_id: str`, `latency_ms: int`, `chunk_count: int`, `is_error: bool`, `content_preview: str`
  - `ToolSpanErrorEvent`: `event_type: ClassVar[str] = "tool.span.error"`, `span_id: str`, `latency_ms: int`, `error_type: str`, `error_message: str`
  - `ExecutorParallelEvent`: `event_type: ClassVar[str] = "executor.parallel"`, `fan_out: int`, `group_latency_ms: int`
  - `SynthesizerFinalEvent`: `event_type: ClassVar[str] = "synthesizer.final"`, `answer: str`, `sources_count: int`
- Reuse existing `ToolPlan` reference (same file — no import gymnastics).
- For `model_dump_json()` SSE serialization (D-10), `ClassVar` fields are excluded by Pydantic automatically — verify in test_agent_sse.py round-trip.

---

### 2. `services/pipeline.py::AgentQueryPipeline.run_streaming`

**Analog:** `services/pipeline.py::AgentQueryPipeline.run` (lines 763-810).

**Existing non-streaming run loop** (lines 763-810):
```python
async def run(self, req: GenerationRequest) -> GenerationResponse:
    trace_id = str(uuid.uuid4())[:8]
    tenant_id, user_id = getattr(req, "tenant_id", ""), getattr(req, "user_id", "")
    t0 = time.perf_counter()
    tf = await self._build_tf(req, tenant_id)
    mem_ctx = await self._memory.load_context(req.session_id, user_id, tenant_id, req.query)
    messages = self._build_initial_messages(req, mem_ctx)
    planner, executor = get_planner(), get_executor()
    all_chunks: list[RetrievedChunk] = []
    parallelism_factors: list[int] = []
    answer = ""

    for iteration in range(MAX_ITERATIONS):
        try:
            plan: ToolPlan = await planner.plan_from_messages(
                messages,
                tools=get_tool_registry().schemas_for(
                    self._llm.provider_name,
                    names=AGENT_TOOL_ALLOWLIST,
                ),
                system=self._AGENT_SYSTEM,
            )
        except NotImplementedError:
            ...
        except (anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError) as exc:
            ...

        if not plan.steps:  # terminal: plan.rationale IS the final answer (D-10)
            answer = plan.rationale or answer
            break

        messages.append(plan.raw_assistant_msg)
        parallelism = len(plan.steps)
        parallelism_factors.append(parallelism)
        raw_outputs = await executor.execute_plan(plan, tf, req)
        tool_results = self._build_tool_results(plan, raw_outputs, all_chunks)
        all_chunks = self._dedup_chunks(all_chunks)
        messages.append({"role": "user", "content": tool_results})

    return await self._persist_turn(req, answer, all_chunks, trace_id, t0, parallelism_factors)
```

**Adaptation notes for `run_streaming`**
- Signature: `async def run_streaming(self, req: GenerationRequest) -> AsyncIterator[AgentEvent]:` — `AsyncIterator` already importable via `typing` (file already imports `AsyncGenerator` at line 24; either works).
- Reuse helpers verbatim: `self._build_tf`, `self._build_initial_messages`, `self._build_tool_results`, `self._dedup_chunks`, `self._persist_turn`.
- Reuse `trace_id = uuid.uuid4().hex[:8]` (CONTEXT.md Discretion: hex form; existing `run` uses `str(uuid.uuid4())[:8]` — use `.hex[:8]` per Phase 18 convention).
- Add `seq_counter = itertools.count()` at top of method (`import itertools` to file imports — currently absent).
- After each `planner.plan_from_messages` returns: `yield PlannerPlanEvent(trace_id=trace_id, seq=next(seq_counter), ts_ms=int(time.time()*1000), plan=plan)`.
- Replace `raw_outputs = await executor.execute_plan(plan, tf, req)` with `async for evt_or_result in executor.execute_plan_streaming(plan, tf, req): yield evt` for events, accumulate `ToolResult`s into `raw_outputs`. See `execute_plan_streaming` design below for the discriminator.
- After the iteration loop: build `answer`, then `yield SynthesizerFinalEvent(trace_id=trace_id, seq=next(seq_counter), ts_ms=..., answer=answer, sources_count=len(all_chunks))`.
- Call `await self._persist_turn(...)` AFTER yielding `synthesizer.final` (D-07 says plan-time decision; "after" preserves audit-on-success semantics — answer is final by then). Do not yield the `GenerationResponse`.
- Same exception classes as `run` (`anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError`); on error, yield a `SynthesizerFinalEvent` with the fallback Chinese error string and break.
- `parallelism_factors` is still tracked (passed to `_persist_turn`).

---

### 3. `services/agent/executor.py::Executor.execute_plan_streaming`

**Analog:** `Executor.execute_plan` (lines 42-90).

**Existing non-streaming gather loop** (lines 42-90):
```python
async def execute_plan(
    self,
    plan: ToolPlan,
    tf: dict[str, Any],
    req: GenerationRequest,
) -> list[ToolResult | BaseException]:
    if not plan.steps:
        return []

    results: list[ToolResult | BaseException | None] = [None] * len(plan.steps)

    for group in plan.parallel_groups:
        t0 = time.perf_counter()
        coros = [
            self._dispatch_one(plan.steps[idx], tf, req)
            for idx in group
        ]
        group_results: list[ToolResult | BaseException] = (
            await asyncio.gather(*coros, return_exceptions=True)
        )
        for idx, res in zip(group, group_results):
            if isinstance(res, BaseException):
                logger.error(
                    f"[Executor] step_idx={idx} name={plan.steps[idx].name} "
                    f"failed: {res!r}"
                )
            results[idx] = res

        logger.info(
            f"[Executor] group_size={len(group)} parallel_factor={len(group)} "
            f"latency_ms={int((time.perf_counter() - t0) * 1000)}"
        )

    return [r for r in results if r is not None]
```

**Existing dispatcher** (lines 92-105):
```python
async def _dispatch_one(
    self,
    tc: ToolCall,
    tf: dict[str, Any],
    req: GenerationRequest,
) -> ToolResult:
    ctx = ToolContext(req=req, tf=tf, retriever=self._retriever, llm=self._llm)
    tool = get_tool_registry().get(tc.name)
    return await tool.run(args=tc.arguments or {}, ctx=ctx)
```

**Adaptation notes for `execute_plan_streaming`**
- Signature: `async def execute_plan_streaming(self, plan: ToolPlan, tf: dict[str, Any], req: GenerationRequest, *, trace_id: str, seq_counter: Iterator[int]) -> AsyncIterator[AgentEvent | ToolResult | BaseException]:`. The mixed yield type lets the orchestrator distinguish "event-to-forward" from "result-to-collect" via `isinstance(item, AgentEvent)`.
- Use a per-step `span_id = uuid.uuid4().hex[:8]`. Maintain `span_id_by_idx: dict[int, str]` so end events match start events.
- For each `group`:
  1. Record `t_group = time.perf_counter()`.
  2. Pre-emit `ToolSpanStartEvent` for every idx in `group` BEFORE creating tasks (D-05: "starts BEFORE asyncio.gather"). Each event: `span_id=span_id_by_idx[idx], name=plan.steps[idx].name, args=plan.steps[idx].arguments` (verbatim — D-11).
  3. Per-task wrapper records its own `t_task = time.perf_counter()` so `ToolSpanEndEvent.latency_ms` is per-tool, not per-group.
  4. Use `asyncio.as_completed` over `asyncio.create_task(...)` for the group. As each task finishes:
     - Catch `BaseException` via `task.exception()` (preserve v1.3 D-01 BaseException isolation — DO NOT let `CancelledError` raise out of the generator; collect it like `gather(return_exceptions=True)` does). The cleanest pattern is `try: res = await fut; except BaseException as exc: res = exc`.
     - If `res` is `ToolResult`: yield `ToolSpanEndEvent(span_id=..., latency_ms=int((time.perf_counter()-t_task)*1000), chunk_count=res.metadata.get("chunk_count", len(res.chunks)), is_error=res.is_error, content_preview=res.content[:200])`.
     - If `res` is `BaseException`: yield `ToolSpanErrorEvent(span_id=..., latency_ms=..., error_type=type(res).__name__, error_message=str(res)[:200])`. Logger.error like existing path.
     - Then yield the `res` itself (or store it in `results[idx]` for later). Pattern: yield events as `AgentEvent` instances; yield results as bare `ToolResult | BaseException` for orchestrator to collect by step-index order.
  5. After all tasks in the group done: yield `ExecutorParallelEvent(fan_out=len(group), group_latency_ms=int((time.perf_counter()-t_group)*1000))`.
- Note D-15 says `executor.parallel` is emitted BEFORE the `tool.span.start`s of that group (smoke test sequence: "1 × executor.parallel (group 1, fan_out=1) → 1 × tool.span.start"). RECONCILE: per-group `executor.parallel` is emitted at group START with the announced fan_out; `group_latency_ms` is then computed retroactively — but D-09 ties `group_latency_ms` to total. Plan resolution: emit `executor.parallel` ONCE at group start with `group_latency_ms=0` is wrong; the cleaner read is "emit at group end with full latency." If smoke test expects start-of-group placement, that is a planner decision — flag this in the planning step. Recommendation: emit at group END (matches D-09 `group_latency_ms` semantics), and update D-15 sequence in plan if needed. The planner picks.
- `_dispatch_one` reused unchanged. Wrap its call with the per-task timer.
- `seq_counter` is the orchestrator's `itertools.count()`; executor advances it for every event yielded so the global `seq` is monotonic across pipeline+executor.
- Add to imports: nothing new (asyncio.as_completed, time, uuid all already in file). Add `from utils.models import ToolSpanStartEvent, ToolSpanEndEvent, ToolSpanErrorEvent, ExecutorParallelEvent, AgentEvent` to existing `from utils.models import ...` line (line 28).

---

### 4. `controllers/api.py` — `POST /agent/v1/run/stream`

**Analog:** `controllers/api.py::query_stream` (lines 232-253).

**Existing SSE route** (lines 232-253):
```python
@router.post("/query/stream", tags=["query"])
@_limiter.limit(f"{settings.rate_limit_query_rpm}/minute")
async def query_stream(request: Request, req: GenerationRequest) -> StreamingResponse:
    """流式 SSE 查询。"""
    pipeline = get_query_pipeline()

    async def _sse():
        try:
            async for token in pipeline.stream(req):
                yield f"data: {token}\n\n"
            yield "data: [DONE]\n\n"
        except (asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError) as exc:
            logger.error(f"[API:stream] error={exc}")
            yield "data: [ERROR] 服务暂时不可用，请稍后重试\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Adaptation notes for `/agent/v1/run/stream`**
- Decorator block changes:
  - Path: `"/agent/v1/run/stream"` (D-01 — URL versioned).
  - Tag: `tags=["agent"]` (CONTEXT.md Established Patterns: new "agent" tag).
  - Same `@_limiter.limit(f"{settings.rate_limit_query_rpm}/minute")` (D-03).
- Body: `req: GenerationRequest` unchanged (CONTEXT.md Discretion).
- Pipeline: `pipeline = get_agent_pipeline()` (NOT `get_query_pipeline`).
- SSE line format changes from `data: ...\n\n` (legacy) to NAMED-EVENT form (D-01, D-10):
  ```python
  async for evt in pipeline.run_streaming(req):
      yield f"event: {evt.event_type}\ndata: {evt.model_dump_json()}\n\n"
  ```
  No `[DONE]` sentinel — `synthesizer.final` IS the terminal event.
- Exception classes: SAME as `query_stream` line 243 (`asyncpg.PostgresError, httpx.HTTPError, openai.APIError, ValueError`); on error yield `event: error\ndata: {"message": "服务暂时不可用，请稍后重试"}\n\n` (named-event form to stay consistent).
- Auth: existing `/query` route uses no explicit auth dependency in this snippet (auth is global middleware — see `services.auth.oidc_auth.get_current_user` import at line 20). Match what `/query/stream` does (no extra `Depends(get_current_user)` parameter); auth comes from middleware. Verify in plan — if `/query` adds a `Depends`, mirror it.
- StreamingResponse headers IDENTICAL to `query_stream` (D-01).

---

### 5. `tests/unit/test_agent_sse.py` (NEW)

**Analog:** `tests/unit/test_executor.py` (full file, 232 lines) — same mock-at-consumer-path discipline.

**Mock-at-consumer-path pattern + BaseTool stub** (lines 29-49):
```python
def _make_fake_tool(tool_name: str, content: str) -> type[BaseTool]:
    """Factory: returns a BaseTool subclass that returns a canned ToolResult."""

    class _FakeTool(BaseTool):
        name: ClassVar[str] = tool_name
        description: ClassVar[str] = "fake"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            return ToolResult(content=content, chunks=[], metadata={"latency_ms": 0})

    _FakeTool.__name__ = f"FakeTool_{tool_name}"
    return _FakeTool


def _stub_registry(*tool_classes: type[BaseTool]) -> ToolRegistry:
    reg = ToolRegistry()
    for cls in tool_classes:
        reg.register(cls)
    return reg
```

**Monkeypatch consumer-path** (lines 56-58, used in every test):
```python
monkeypatch.setattr(
    "services.agent.executor.get_tool_registry",
    lambda: _stub_registry(FakeTool),
)
```

**Adaptation notes for test_agent_sse.py**
- Test the orchestrator end-to-end: invoke `pipeline.run_streaming(req)` and `async for evt in ...` collect events into a `list[AgentEvent]`.
- Stub `Planner.plan_from_messages` via `monkeypatch.setattr("services.pipeline.get_planner", lambda: stub_planner)` so the test doesn't need a real LLM. Stub returns a canned `ToolPlan`.
- Stub `Executor` via `monkeypatch.setattr("services.pipeline.get_executor", lambda: stub_executor)` OR mock at registry path (same as test_executor.py): `monkeypatch.setattr("services.agent.executor.get_tool_registry", ...)` so a real `Executor` runs against fake tools. Either valid; latter is closer to D-16 wording.
- Also stub `_memory`, `_audit`, `_tenant_svc`, `_filter_extractor` — easiest via `monkeypatch.setattr` on `AgentQueryPipeline.__init__` -bound singletons (`get_memory_service`, `get_audit_service`, `get_tenant_service`, `get_filter_extractor` in `services.pipeline`). Cleanest: build a fixture that patches all five at consumer paths and yields a fresh `AgentQueryPipeline()`.
- Smoke test (D-15): assert exact 11-event sequence by `(evt.event_type, fan_out_or_span_id_or_count)`.
- Latency test (D-14): tools sleep 0.5s each, gather start time before iteration begins, assert `450 < (t1 - t0)*1000 < 700`.
- Error test (D-12): tool raises `RuntimeError` → assert one `ToolSpanErrorEvent` with `error_type == "RuntimeError"`, `error_message` truncated to 200 chars.
- Redaction test (D-11): tool args `{"password": "x"}` appear verbatim in `ToolSpanStartEvent.args`; tool content > 200 chars truncated in `ToolSpanEndEvent.content_preview`.
- Pydantic validation test: `PlannerPlanEvent.model_dump_json()` round-trips through `PlannerPlanEvent.model_validate_json(...)` — frozen + ConfigDict must not break serialization.

---

### 6. `tests/unit/test_executor_streaming.py` (NEW)

**Analog:** `tests/unit/test_executor.py` (sibling test for `execute_plan` non-streaming).

**Reuse the same fixtures**: `_tc`, `_req`, `_make_fake_tool`, `_stub_registry`, the consumer-path `monkeypatch.setattr("services.agent.executor.get_tool_registry", ...)` pattern. Import them or duplicate inline (no shared conftest — test_executor.py defines locally).

**Adaptation notes for test_executor_streaming.py**
- Test `Executor.execute_plan_streaming` directly — no pipeline orchestrator involved.
- Provide `trace_id="abc12345"` and `seq_counter=itertools.count()` as keyword args.
- Collect yields into `events: list[AgentEvent] = []` and `results: list[ToolResult | BaseException] = []` by `isinstance` discriminator.
- Tests:
  - `test_execute_plan_streaming_single_step` — 1-step plan: assert `len(events) == 3` (1 start + 1 end + 1 parallel) and `len(results) == 1`.
  - `test_execute_plan_streaming_two_groups` — `parallel_groups=[[0],[1,2]]`: assert 2 `ExecutorParallelEvent`s with `fan_out` 1 then 2; assert `tool.span.start` count == 3.
  - `test_execute_plan_streaming_baseexception_isolation` — one tool raises; assert one `ToolSpanErrorEvent` AND `results[idx] isinstance BaseException` (parity with `test_execute_plan_returns_exception_as_value` lines 149-190).
  - `test_execute_plan_streaming_span_id_match` — every `tool.span.start.span_id` appears in exactly one `tool.span.end` OR `tool.span.error`.
  - `test_execute_plan_streaming_seq_monotonic` — `[e.seq for e in events]` is strictly increasing.
  - `test_execute_plan_streaming_empty_plan` — empty plan → no yields (parity with `test_execute_plan_empty` line 226).

---

### 7. `docs/agent-architecture.md` — `## Event Schema Reference`

**Analog:** existing file structure (lines 1-98), specifically `## Authoring Tools` (line 7) with `###` subsections (`### Defining a Tool`, `### Registering a Tool`, etc.).

**Existing heading style (depth + table omitted; current doc uses prose + code blocks)**:
```markdown
## Authoring Tools

The agent runtime dispatches tool calls through a static class registry
(`services/agent/tools/registry.py`). New tools subclass `BaseTool`,
declare three ClassVar attributes, implement an async `run` method, and
register themselves at module import time.

### Defining a Tool

1. Subclass `BaseTool` from `services.agent.tools.base`.
2. Declare three required ClassVar attributes:
   - `name: ClassVar[str]` — unique identifier used by the planner LLM.
   ...
```

**Adaptation notes for `## Event Schema Reference`**
- Insert AFTER line 98 (end of file) — Phase 17 left a teaser at line 4-5 mentioning "SSE event schemas (Phase 18) ... extend this file later." Update that teaser line ("Phase 17 (v1.4)" → "Phase 18 (v1.4)").
- Section depth: top-level `## Event Schema Reference` matches `## Authoring Tools`.
- One subsection per event type: `### planner.plan`, `### tool.span.start`, `### tool.span.end`, `### tool.span.error`, `### executor.parallel`, `### synthesizer.final`. Six total.
- Each subsection: 1-line description, **field table** (CONTEXT.md Discretion: `name | type | required | description`), one **example payload** as JSON pretty-printed (3-space indent matches Pydantic default).
- Add a `### Consuming the Stream` final subsection with minimal browser `EventSource(url)` snippet (Discretion):
  ```javascript
  const es = new EventSource('/api/v1/agent/v1/run/stream');
  es.addEventListener('planner.plan', (e) => console.log(JSON.parse(e.data)));
  es.addEventListener('synthesizer.final', (e) => { console.log(JSON.parse(e.data)); es.close(); });
  ```
- Total ≤ 250 lines (Discretion).
- Match existing prose register: terse, no emoji, English (the doc is English; pipeline source has Chinese strings but docs/ is English).

---

## Shared Patterns

### Pydantic V2 frozen + ClassVar discriminator
**Source:** `utils/models.py::ToolResult` (lines 359-380), `ToolCall` (244-258).
**Apply to:** every `AgentEvent` subclass.
```python
class XEvent(AgentEvent):
    event_type: ClassVar[str] = "x.y"
    model_config = ConfigDict(frozen=True)
    field1: str
    field2: int = 0
```
- `model_config` re-declared on each subclass (Pydantic V2 does not auto-inherit).
- `ClassVar[str]` excluded from `model_dump_json()` automatically — inject manually if needed, or include in payload via separate field.

### `uuid.uuid4().hex[:8]` for trace/span IDs
**Source:** `services/pipeline.py::AgentQueryPipeline.run` line 764 (`str(uuid.uuid4())[:8]`) — Phase 18 D-Discretion uses `.hex[:8]` form (8 hex chars without dashes).
**Apply to:** `trace_id` (per `run_streaming` invocation) and `span_id` (per tool dispatch in `execute_plan_streaming`).

### `time.perf_counter()` latency timing
**Source:** `services/agent/executor.py::execute_plan` line 69 + 87, `services/pipeline.py::_persist_turn` line 736.
**Apply to:** per-tool span latency in `execute_plan_streaming`, per-group latency in `ExecutorParallelEvent`, total stream latency in tests.
```python
t0 = time.perf_counter()
# ... do work ...
latency_ms = int((time.perf_counter() - t0) * 1000)
```

### `BaseException` isolation via `gather(return_exceptions=True)` → `as_completed` + try-around-await
**Source:** `services/agent/executor.py::execute_plan` lines 74-83 (gather + isinstance(BaseException) + logger.error).
**Apply to:** `execute_plan_streaming` per-task wrapper. v1.3 Phase 12 D-01 isolation guarantee MUST be preserved when switching from `gather` to `as_completed`. The pattern:
```python
try:
    res = await fut   # fut is a Future from as_completed/wait
except BaseException as exc:   # preserves CancelledError / TimeoutError isolation
    logger.error(f"[Executor] step_idx={idx} ... failed: {exc!r}")
    res = exc
```

### Mock-at-consumer-path discipline
**Source:** `tests/unit/test_executor.py` lines 56-58 (and 95-98, 130-133, 173-176, 208-211 — every test).
**Apply to:** every test in `test_agent_sse.py` and `test_executor_streaming.py`.
```python
monkeypatch.setattr(
    "services.agent.executor.get_tool_registry",
    lambda: _stub_registry(FakeTool),
)
```
- Patch where it's IMPORTED (consumer side: `services.agent.executor.get_tool_registry`), not where it's DEFINED (`services.agent.tools.registry.get_tool_registry`).

### SSE response shape
**Source:** `controllers/api.py::query_stream` lines 249-253.
**Apply to:** `/agent/v1/run/stream`. Headers identical:
```python
return StreamingResponse(
    _sse(),
    media_type="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
)
```
ONLY the inner `async def _sse()` body changes (named-event form vs. data-only).

### Rate limit decorator
**Source:** `controllers/api.py::query_stream` line 233 (`@_limiter.limit(...)`).
**Apply to:** `/agent/v1/run/stream` route — same `f"{settings.rate_limit_query_rpm}/minute"`.

---

## No Analog Found

None. Every Phase 18 file maps to an existing analog in the codebase (Phases 16/17 prepared the ground deliberately).

---

## Metadata

**Analog search scope:** `utils/models.py`, `services/pipeline.py`, `services/agent/executor.py`, `controllers/api.py`, `tests/unit/test_executor.py`, `docs/agent-architecture.md`.
**Files scanned:** 6 (one per output file; each Phase 18 target had a single best analog within the same module or a sibling test).
**Pattern extraction date:** 2026-05-09
