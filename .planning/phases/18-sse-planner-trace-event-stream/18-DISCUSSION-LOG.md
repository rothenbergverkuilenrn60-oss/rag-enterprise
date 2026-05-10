# Phase 18: SSE Planner Trace Event Stream - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-09
**Phase:** 18-sse-planner-trace-event-stream
**Areas discussed:** Endpoint surface + backwards-compat, Event emission architecture, Event payload format + redaction policy, Test strategy + latency assertion

---

## Endpoint surface + backwards-compat (GA1)

| Option | Description | Selected |
|--------|-------------|----------|
| New /agent/v1/run/stream — separate route | URL versioned. Existing /query/stream untouched. Frontend splits cleanly: token consumer for legacy, event consumer for agent. | ✓ |
| Extend /query/stream — discriminate on agent_mode | Single endpoint; two protocols at same path. Frontend must parse `event:` line. May break existing consumers. | |
| Both — /query/stream gets agent-mode AND /agent/v1/run/stream new | Backwards-compat plus clean namespace. Costs duplication; gains zero migration friction. | |

**User's choice:** New /agent/v1/run/stream — recommended option.
**Notes:** No external consumers wire to /query/stream?agent_mode=true today. Versioned URL leaves room for v2.

---

## Event emission architecture (GA2)

| Option | Description | Selected |
|--------|-------------|----------|
| Async generator: AgentQueryPipeline.run_streaming yields events | Sibling method to existing `run`. Plays naturally with FastAPI StreamingResponse + asyncio. Easy to test. | ✓ |
| Callback injection: pass on_event=fn into Planner/Executor | Forces collaborators to know about events. Couples Planner/Executor to event types. Regresses Phase 17 D-01 isolation. | |
| asyncio.Queue passed in | Decouples emission from consumption. Extra plumbing, queue overflow handling, cancellation semantics. | |
| Decorator/middleware (event_recorder context manager) | Clean separation. contextvars + asyncio interaction is a known landmine. | |

**User's choice:** Async generator — recommended option.
**Notes:** Existing `run` stays for non-streaming consumers. `Executor.execute_plan_streaming` joins as sibling generator. `Planner` UNCHANGED.

---

## Event payload format + redaction policy (GA3)

### GA3-A — Payload type system

| Option | Description | Selected |
|--------|-------------|----------|
| Pydantic V2 frozen models per event type | Matches Phase 16/17 D-01 precedent. Discriminated union via `event_type: ClassVar[str]`. Schema validation; codegen ready. | ✓ |
| Single AgentEvent model with type+payload dict | Less boilerplate; no per-event-type validation; payload drift goes unnoticed. | |
| Plain dicts — no model classes | Lightest weight. Breaks frozen-model precedent; loses JSON Schema autogen. | |

**User's choice:** Pydantic V2 frozen per-event-type — recommended option.

### GA3-B — Redaction policy

| Option | Description | Selected |
|--------|-------------|----------|
| Args verbatim + content_preview truncated | tool.span.start.args verbatim. tool.span.end carries first 200 chars + chunk_count + latency_ms. Multi-tenant safe by JWT+RLS. | ✓ |
| Args + full content verbatim | No redaction. Stream payload bloats. Reasonable for v1.4 internal eyes-on. | |
| Hash everything; no preview | Maximum privacy. Defeats Phase 18 goal ("see agent reasoning live"). | |
| Configurable: SSE_REDACT_TOOL_CONTENT env var | Production deployments flip to true. Marginal value in v1.4. | |

**User's choice:** Args verbatim + content_preview truncated — recommended option.
**Notes:** content_preview = first 200 chars; chunk_count + latency_ms read from ToolResult.metadata convention (Phase 17 D-02).

---

## Test strategy + latency assertion (GA4)

| Option | Description | Selected |
|--------|-------------|----------|
| Mocked tools w/ asyncio.sleep + time.perf_counter | Unit tests in tests/unit. Fast, deterministic, no API key. Strict-shape Pydantic validation + count assertions. | ✓ |
| Real integration test only | Slower; needs API key; flaky under rate limits. Realistic but expensive. | |
| Both tiers: mocked unit + real integration | Highest confidence; doubles test surface. v1.5+. | |

**User's choice:** Mocked tools — recommended option.
**Notes:** Real integration test deferred to Phase 19 demo (`make demo-agent`).

---

## Claude's Discretion

- **Executor.execute_plan_streaming exact yield shape:** start-events-before-gather + end-events-as-completed. Plan-time picks between `asyncio.as_completed`, `asyncio.create_task` + `wait(FIRST_COMPLETED)`, or custom event-emitting executor. Must preserve BaseException isolation.
- **trace_id generation:** `uuid.uuid4().hex[:8]` matching Phase 16 thin-orchestrator convention. span_id same shape.
- **seq monotonic counter:** `itertools.count()` instance per stream. Reset per `run_streaming` invocation.
- **docs/agent-architecture.md depth:** add `## Event Schema Reference` after `## Authoring Tools`. One subsection per event type; field table + JSON example payload. ≤ 250 lines.
- **/agent/v1/run/stream request body:** identical to existing `GenerationRequest`. Route uses `agent_mode=True` semantics regardless of flag.
- **Frontend example in docs:** minimal `EventSource(url)` snippet. Live demo wiring is Phase 19.

## Deferred Ideas

- `make demo-agent` target — Phase 19.
- README rewrite mentioning SSE differentiator — Phase 19.
- Asciinema/gif of parallel fan-out — Phase 19.
- Historical intent mapping table — Phase 19 (Phase 16 D-13 carry-forward).
- Configurable redaction via env var — v1.5+.
- OpenTelemetry-style W3C Trace Context — v1.5+.
- Explicit backpressure / disconnect hooks — v1.5+.
- `/query/stream` deprecation — v1.5+ (post-confirmation that /agent/v1 is canonical).
- Real WebSearchTool event flow — v1.5+ (Phase 17 placeholder still fires events with metadata.placeholder=true).
- SSE event replay / resume via `Last-Event-ID` header — v1.5+.
- Per-event JSON Schema export → TypeScript codegen — v1.5+.
- Streaming `synthesizer.final` text deltas — v1.5+.
- `SwarmQueryPipeline.run_streaming` — v1.5+ after AGENT-05.
