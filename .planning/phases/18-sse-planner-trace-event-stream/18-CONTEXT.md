# Phase 18: SSE Planner Trace Event Stream - Context

**Gathered:** 2026-05-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a structured SSE event stream surface (`POST /agent/v1/run/stream`) that emits typed `AgentEvent` payloads from `AgentQueryPipeline`. Events: `planner.plan`, `tool.span.start`, `tool.span.end`, `tool.span.error`, `executor.parallel`, `synthesizer.final`. Documented schemas in `docs/agent-architecture.md`. Latency assertion proves parallel tools bounded by `max(tool_latency)`, not `sum`. v1.3 invariants (multi-tenancy / RLS / JWT / audit) preserved. Existing `/query/stream` token route untouched.

</domain>

<decisions>
## Implementation Decisions

### Endpoint surface + backwards-compat

- **D-01:** New route `POST /agent/v1/run/stream` in `controllers/api.py`. URL versioned (`/agent/v1/...`) leaves room for `/agent/v2/...` later. Returns `StreamingResponse(media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})` matching existing `/query/stream` shape. Body shape: `event: <type>\ndata: <json>\n\n` per SSE spec — uses the named-event form (legacy `/query/stream` only used `data:` lines). JWT validation + tenant filter same as existing `/query` route (request goes through the same auth dependency).

- **D-02:** Existing `POST /query/stream` (token-level) STAYS UNCHANGED in Phase 18. It's QueryPipeline-only; AgentQueryPipeline uses the new `/agent/v1/run/stream`. No deprecation in Phase 18 — Phase 19 may revisit.

- **D-03:** Rate limit: same as `/query` (`rate_limit_query_rpm` settings). Reuse `_limiter.limit(...)` decorator. SSE long-lived connections count as a single request for rate-limit purposes (existing behavior).

### Event emission architecture

- **D-04:** Add `AgentQueryPipeline.run_streaming(req: GenerationRequest) -> AsyncIterator[AgentEvent]` as a SIBLING method to existing `run`. Existing `run` stays for non-streaming consumers (legacy `/query?agent_mode=true`). `run_streaming` drives the same Planner/Executor flow but `yield`s `AgentEvent` instances at each step. Final iteration returns nothing (the synthesizer.final event carries the answer text).

- **D-05:** `Executor.execute_plan_streaming(plan, tf, req) -> AsyncIterator[ExecutorEventOrResult]` is added as a sibling to existing `execute_plan`. Yields `ToolSpanStartEvent` for every step BEFORE `asyncio.gather` starts, then `ToolSpanEndEvent` (or `.error`) AS EACH future resolves (using `asyncio.as_completed` instead of plain gather), then a terminal `ExecutorParallelEvent` carrying the fan-out factor + total group latency. Maintains v1.3 D-01 BaseException isolation. Existing `execute_plan` UNCHANGED — non-streaming path continues to work.

- **D-06:** `Planner.plan_from_messages` UNCHANGED. The orchestrator (`AgentQueryPipeline.run_streaming`) wraps the planner call and emits `PlannerPlanEvent` immediately after the planner returns. No change to Planner's signature.

- **D-07:** `synthesizer.final` is emitted by the orchestrator AFTER the final `call_agentic_turn` returns (Phase 16 D-10/11/12 — synthesizer is a logical role, not a class). Event carries the final assistant turn's text verbatim.

### Event payload format + redaction policy

- **D-08:** `AgentEvent` is an abstract Pydantic V2 frozen base class in `utils/models.py` (matches Phase 16/17 D-01 placement). All concrete event classes inherit it. Common fields: `event_type: ClassVar[str]`, `trace_id: str` (8-hex), `seq: int` (monotonic per stream), `ts_ms: int` (Unix epoch ms). `model_config = ConfigDict(frozen=True)` on every concrete class.

- **D-09:** Concrete event classes (5):
  - `PlannerPlanEvent(event_type="planner.plan", plan: ToolPlan)` — full ToolPlan model (steps + parallel_groups + rationale)
  - `ToolSpanStartEvent(event_type="tool.span.start", span_id: str, name: str, args: dict[str, Any])` — args VERBATIM from `tc.arguments`
  - `ToolSpanEndEvent(event_type="tool.span.end", span_id: str, latency_ms: int, chunk_count: int, is_error: bool, content_preview: str)` — content_preview = first 200 chars of `ToolResult.content`; latency_ms + chunk_count read from `ToolResult.metadata` (Phase 17 D-02 convention)
  - `ToolSpanErrorEvent(event_type="tool.span.error", span_id: str, latency_ms: int, error_type: str, error_message: str)` — error_message TRUNCATED to first 200 chars (no full traceback)
  - `ExecutorParallelEvent(event_type="executor.parallel", fan_out: int, group_latency_ms: int)` — emitted ONCE per parallel group
  - `SynthesizerFinalEvent(event_type="synthesizer.final", answer: str, sources_count: int)` — full answer text

- **D-10:** Serialization: `event.model_dump_json()` produces the SSE `data:` line content. SSE event-line format: `event: {event_type}\ndata: {json}\n\n`. Frontend parses `event:` line to dispatch.

- **D-11:** Redaction policy locked to "args verbatim + content_preview truncated". Multi-tenant safety preserved by JWT + RLS — only the tenant's own JWT-authenticated stream sees their own data. No cross-tenant leak by construction. No env-var toggle in Phase 18 (configurable redaction deferred to v1.5+ if needed).

- **D-12:** `tool.span.error` is emitted INSTEAD OF `tool.span.end` when `Executor` collects a `BaseException` (per v1.3 Phase 12 D-01 isolation). `error_type = type(exc).__name__`; `error_message = str(exc)[:200]`. Full traceback NOT in stream (logged at `logger.error` only).

### Test strategy + latency assertion

- **D-13:** Test approach: mocked tools using `asyncio.sleep(N)` + `time.perf_counter` for latency assertions. Tests live in `tests/unit/test_agent_sse.py`. Strict-shape Pydantic validation per event + count assertions. Fast, deterministic, no API key required. Real integration test deferred to Phase 19 demo.

- **D-14:** Latency assertion (ROADMAP SC4): test mocks 4 tools each with `asyncio.sleep(0.5)`; asserts total elapsed ms is `450 < elapsed_ms < 700` (max(500) + overhead) — NOT `~2000ms` (sum). Test asserts `tool.span.start` count == 4 AND `tool.span.end` count == 4 AND `executor.parallel.fan_out == 4`.

- **D-15:** Smoke test (ROADMAP SC3): given a fixture `ToolPlan` with 2 parallel groups (one 1-step, one 3-step), assert exact event sequence: 1 × `planner.plan` → 1 × `executor.parallel` (group 1, fan_out=1) → 1 × `tool.span.start` → 1 × `tool.span.end` → 1 × `executor.parallel` (group 2, fan_out=3) → 3 × `tool.span.start` → 3 × `tool.span.end` → 1 × `synthesizer.final`. Total = 11 events.

- **D-16:** No mock at registry; tests inject a stub `BaseTool` subclass via `monkeypatch.setattr("services.agent.executor.get_tool_registry", lambda: stub_registry)` per Phase 13/15 + Phase 17 consumer-path convention.

### NLU-03 + AGENT-09 carry-forward (no new decision)

- **D-17:** `_AGENT_TOOLS` is gone (Phase 17 D-06). `AGENT_TOOL_ALLOWLIST` + `registry.schemas_for(provider, names=...)` is the planner-tools surface. Phase 18 does NOT change this.

- **D-18:** No `IntentRouter` (Phase 16 D-13 / Phase 17 D-12 carry-forward). Intent shape lives in `ToolPlan`; `planner.plan` event surfaces it via `plan.parallel_groups` shape.

### Claude's Discretion

- **`Executor.execute_plan_streaming` exact yield shape:** D-05 specifies start-events-before-gather + end-events-as-completed. Implementation choice between (a) `asyncio.as_completed` directly, (b) `asyncio.create_task` per step + `asyncio.wait(FIRST_COMPLETED)` loop, (c) wrap in a custom event-emitting executor — Phase 18 plan picks. Must preserve `BaseException` isolation guarantee.
- **`trace_id` generation:** `uuid.uuid4().hex[:8]` matches Phase 16 thin-orchestrator convention (`AgentQueryPipeline.run` line 783). Reuse same pattern. `span_id` per tool dispatch follows same `hex[:8]` shape.
- **`seq` monotonic counter:** simple `itertools.count()` instance per stream. Reset per `run_streaming` invocation. NOT global.
- **`docs/agent-architecture.md` event-schema section depth:** add `## Event Schema Reference` section AFTER existing `## Authoring Tools` (Phase 17). One subsection per event type with: event name, field table (name | type | required | description), one example payload (JSON pretty-printed). Total ≤ 250 lines.
- **`/agent/v1/run/stream` request body schema:** identical to existing `GenerationRequest` (utils/models.py — already has `agent_mode`/`swarm_mode` fields). Phase 18 does NOT introduce a new request type. The route uses `agent_mode=True` semantics regardless of the request flag (route-level intent).
- **Frontend example:** docs include a minimal browser `EventSource(url)` snippet showing how to consume named events. Live-demo wiring is Phase 19 territory.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source design and milestone artifacts

- `/home/ubuntu/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` — v1.4 milestone design doc; "agent reasoning visible at SSE event level, not intermediate_steps black box" is the differentiation thesis Phase 18 delivers.
- `.planning/PROJECT.md` — enterprise-grade preservation thesis.
- `.planning/ROADMAP.md` Phase 18 success criteria — 5 SCs are the acceptance contract.
- `.planning/REQUIREMENTS.md` AGENT-04 — minimum event types listed.

### Code anchors

- `controllers/api.py` — existing `/query/stream` route at the `@router.post("/query/stream")` block; pattern Phase 18 mirrors. Auth dependency + rate limit decorator + `StreamingResponse` shape.
- `services/pipeline.py::AgentQueryPipeline.run` (line 782, 43-line body) — non-streaming path; sibling `run_streaming` lives in same class.
- `services/pipeline.py::AGENT_TOOL_ALLOWLIST` (line 590) — `run_streaming` uses same constant for `tools=` arg.
- `services/agent/executor.py::Executor.execute_plan` — sibling `execute_plan_streaming` joins.
- `services/agent/executor.py:60` (current `_dispatch_one`) — Phase 18 may reuse OR fold into streaming-path-only.
- `utils/models.py::ToolResult` (line 359) + `ToolPlan` (line 291) + `ToolCall` (line 244) — read by event payloads.
- `utils/models.py::GenerationRequest` — request body for `/agent/v1/run/stream`; UNCHANGED in Phase 18.
- `services/agent/tools/registry.py::get_tool_registry` — registry already in place from Phase 17.
- `docs/agent-architecture.md` — Phase 17 stub at `#authoring-tools`; Phase 18 adds `#event-schema-reference` section after.

### Codebase maps (read once for orientation)

- `.planning/phases/16-planner-executor-extraction/16-CONTEXT.md` — Phase 16 D-10/11/12 (synthesizer is logical role, max_iterations at orchestrator) drive D-07.
- `.planning/phases/17-tool-abstraction-retrievetool/17-CONTEXT.md` — Phase 17 D-02 (ToolResult.metadata convention) drives D-09 latency_ms/chunk_count read path.
- `.planning/phases/17-tool-abstraction-retrievetool/17-RESEARCH.md` §"Phase 18 SSE Forward-Compat" — gap analysis confirms ToolResult.metadata covers tool.span needs.
- `.planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md` — thin orchestrator helper extraction patterns; `_build_tf`, `_build_initial_messages`, `_build_tool_results` are the analogs `run_streaming` reuses.

### Milestones archive (precedent decisions)

- `.planning/milestones/v1.1-phases/09-frontend-extraction/` — frontend SSE consumer precedent (existing `/query/stream` browser code in `static/`).
- `.planning/milestones/v1.2-phases/11-provider-agnostic-agentic-layer-parallel-tool-call-burst/` — `BaseLLMClient.call_agentic_turn` returns `AgenticTurn` with `.tool_calls` list — Phase 18 reads this for `planner.plan` event.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`controllers/api.py:/query/stream` route** — exact pattern Phase 18 mirrors (StreamingResponse + media_type + headers). Copy-adapt for `/agent/v1/run/stream`.
- **`AgentQueryPipeline.run` non-streaming path** — keeps working unchanged. `run_streaming` shares `_build_tf` / `_build_initial_messages` / `_build_tool_results` / `_dedup_chunks` / `_persist_turn` private helpers.
- **`Executor.execute_plan` non-streaming path** — keeps working unchanged. `execute_plan_streaming` is additive.
- **`uuid.uuid4().hex[:8]`** — already used at `AgentQueryPipeline.run:783` for trace_id; identical pattern for span_id.
- **`time.perf_counter()`** — already used at `Executor.execute_plan` for group latency; reused for per-step latency in span events.
- **`logger.error` for exceptions** — Phase 16 D-01 BaseException isolation already logs; Phase 18 reads exception types/messages for error event without changing log behavior.
- **`asyncio.gather(return_exceptions=True)`** — Phase 16 + Phase 17 patterns. Phase 18 may switch to `asyncio.as_completed` for streaming, but BaseException collection semantics preserved.

### Established Patterns

- **Mock at consumer path** (Phase 13/15/17). `monkeypatch.setattr("services.agent.executor.get_tool_registry", ...)` for tests. Phase 18 follows.
- **Pydantic V2 frozen models with ConfigDict** — every event class declares `model_config = ConfigDict(frozen=True)`. Match `ToolResult` (utils/models.py:375) shape.
- **Singleton factory pattern** — Phase 18 does NOT add new singletons (events are per-stream values, not singletons; pipeline + registry singletons already exist).
- **`@router.post(..., tags=["agent"])` decorator** — `/agent/v1/run/stream` introduces a new "agent" tag. Routes group naturally in OpenAPI schema.
- **Auth dependency injection** — `/query` route uses an auth dependency that resolves `req.tenant_id` + `req.user_id` from JWT. Phase 18 reuses the SAME dependency. RLS preserved.
- **Audit log call site** — `AgentQueryPipeline._persist_turn` (Phase 16 helper) writes audit fields. `run_streaming` calls `_persist_turn` BEFORE yielding `synthesizer.final` (or after, plan-time decision). Audit shape preserved.

### Integration Points

- **`controllers/api.py`** — adds NEW `@router.post("/agent/v1/run/stream", tags=["agent"])` route. ~30 lines.
- **`services/pipeline.py::AgentQueryPipeline`** — adds `run_streaming` async generator method. Existing `run` UNCHANGED. ~80-120 lines.
- **`services/agent/executor.py::Executor`** — adds `execute_plan_streaming` async generator method. Existing `execute_plan` UNCHANGED. ~60-80 lines.
- **`utils/models.py`** — adds `AgentEvent` base + 6 concrete event classes (PlannerPlanEvent, ToolSpanStartEvent, ToolSpanEndEvent, ToolSpanErrorEvent, ExecutorParallelEvent, SynthesizerFinalEvent). ~80-100 lines total.
- **`tests/unit/test_agent_sse.py`** — NEW test module covering smoke (D-15) + latency (D-14) + error path (D-12) + redaction (D-11). Estimated 12-18 tests.
- **`tests/unit/test_executor_streaming.py`** — NEW test module for `execute_plan_streaming` event ordering. Estimated 6-8 tests.
- **`docs/agent-architecture.md`** — adds `## Event Schema Reference` section after Phase 17's `## Authoring Tools`. ~150 lines.
- **No frontend changes in Phase 18** (Phase 19 territory; consumer browser code lands with the `make demo-agent` target).

</code_context>

<specifics>
## Specific Ideas

- The user's v1.4 differentiation thesis: "planner trace 划到 SSE 事件流级别，而不是 intermediate_steps 黑盒." Phase 18 IS that thesis delivered. Every architectural choice should serve "make agent reasoning legible to peer engineers in real time" — verbose enough to debug, structured enough to consume programmatically.
- **Enterprise-grade preservation is non-negotiable.** RLS / JWT / audit field shape unchanged. Multi-tenant streams are JWT-isolated by route auth (existing dependency). No cross-tenant leak by construction.
- **Phase 19 demo is the validator.** `make demo-agent` (Phase 19) replays a multi-hop query against the new endpoint and shows visible parallel fan-out in browser EventSource. Phase 18 must surface enough signal that the demo is compelling without raw data leaks.

</specifics>

<deferred>
## Deferred Ideas

### To Phase 19 (Agent-First Docs + Demo + Release)

- **`make demo-agent` target** consumes `/agent/v1/run/stream` and renders parallel fan-out in browser EventSource UI. Phase 19 builds the consumer; Phase 18 builds the producer.
- **README rewrite** mentions SSE event stream as differentiator (not "intermediate_steps black box like LangGraph").
- **Asciinema/gif** of parallel fan-out demo embedded in README. Phase 19.
- **Historical intent mapping table** (`Query/Agent/Swarm` → `ToolPlan` shape) documented in `docs/agent-architecture.md` (Phase 16 D-13 carry-forward). Phase 19, NOT Phase 18.

### To v1.5+

- **Configurable redaction** via `SSE_REDACT_TOOL_CONTENT` env var. Phase 18 chose verbatim args + truncated content_preview; v1.5+ may add opt-out hash-only mode.
- **OpenTelemetry-style trace propagation** — `trace_id` + `span_id` aligned with W3C Trace Context. Phase 18 uses simple 8-hex strings; v1.5+ may upgrade to full OTEL.
- **Backpressure / disconnect handling** — Phase 18 lets asyncio handle disconnect via `CancelledError` propagation through generator; v1.5+ may add explicit cancellation hooks.
- **`/query/stream` deprecation** — Phase 18 leaves it untouched. If `/agent/v1/run/stream` proves to be the canonical surface, deprecate `/query/stream` later.
- **Real `WebSearchTool` event flow** — Phase 17 placeholder returns canned ToolResult; events still fire but `placeholder: True` shows in metadata. Real implementation is v1.5+.
- **SSE event replay / resume** — clients reconnecting to mid-stream. Phase 18 emits `seq`; v1.5+ may add resume support via `Last-Event-ID` header.
- **Per-event JSON Schema export** — codegen TypeScript types for frontend. Pydantic V2 supports `model_json_schema()`; Phase 18 captures Pydantic models, v1.5+ adds the build step.
- **Streaming `synthesizer.final` text** — currently emitted as one event with full answer. v1.5+ may stream synthesis tokens within `synthesizer.final.delta` events for better UX.
- **`SwarmQueryPipeline` event stream** — D-11 carry-forward (Phase 17 v1.5+ deferral). When swarm migrates to registry, also gets `run_streaming`.

</deferred>

---

*Phase: 18-sse-planner-trace-event-stream*
*Context gathered: 2026-05-09*
