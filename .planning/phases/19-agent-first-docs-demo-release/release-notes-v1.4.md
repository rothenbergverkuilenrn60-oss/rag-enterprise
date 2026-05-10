# v1.4.0 Release Notes — Draft

*Prepared by plan 19-08. Two sections: (A) tag annotation for `git tag -a -m`, (B) full prose for `gh release create --notes-file`. The user runs the ceremony from `release-tag-commands.md` after the v1.4 milestone PR merges to `master`.*

## Tag annotation (for `git tag -a v1.4.0 -m "..."`)

Copy the contents of the fenced block below verbatim into the `-m` flag. Six lines of content (1 headline + 4 phase bullets + 1 thesis paragraph) plus the two separator blank lines, per CONTEXT.md D-15.

```
v1.4.0 — Agent-first architecture inversion

Phase 16: Planner + Executor extraction (AGENT-06, AGENT-09, NLU-03)
Phase 17: Tool abstraction + RetrieveTool (AGENT-07)
Phase 18: SSE event stream (AGENT-04)
Phase 19: Agent-first docs + demo + release (AGENT-08)

Architectural inversion: the agent runtime (Planner / Executor / Synthesizer)
is the project's core; agentic RAG is one of the tools the agent calls.
```

---

## GitHub release notes (full prose for `gh release create --notes-file`)

# v1.4 — Agent-First Architecture Inversion

*Released 2026-05-09. Cut from `master` after the v1.4 milestone PR merge.*

A Planner → Executor → Synthesizer agent. RAG is one of its tools.

v1.4 inverts the architecture: where v1.0..v1.3 framed EnterpriseRAG as a RAG
platform with an optional agentic mode, v1.4 makes the agent runtime the
project's core. The Planner emits a `ToolPlan`. The Executor walks
`parallel_groups` and dispatches concurrently with `BaseException` isolation.
The Synthesizer composes the final answer. Hybrid retrieval (pgvector + BM25
+ RRF + reranker) is now `RetrieveTool` — one of several tools the agent
calls. The same registry that ships `RetrieveTool` is designed for MCP tool
discovery to replace it later without changing callsites.

Full architectural thesis: [docs/v1.4-design.md](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/docs/v1.4-design.md) (Approach A — incremental refactor, no framework lock-in).

## What changed

### Phase 16 — Planner + Executor extraction

`services/pipeline.py::AgentQueryPipeline.run` rewritten as a thin
orchestrator (43 lines) over `Planner` + `Executor` + `Synthesizer`. Each
collaborator has a single-purpose Pydantic V2 frozen interface (`ToolPlan`,
`ToolCall`). Query intent is encoded as `ToolPlan` shape — no separate
`IntentRouter` class. Behavioral parity vs v1.3 baseline asserted before any
new behavior landed.

`_execute_tool_call` consolidated to `services/agent/tool_executor.py` and
consumed by both `SwarmQueryPipeline` and the new `Executor` —
`grep -rn "def _execute_tool_call" services/` returns 0 (the helper moved to
`execute_tool_call` in `services/agent/`).

Closes AGENT-06, AGENT-09, NLU-03.
See [Phase 16 SUMMARY](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/.planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md).

### Phase 17 — Tool abstraction + RetrieveTool

`BaseTool` ABC + static `ToolRegistry` (`services/agent/tools/`).
`RetrieveTool` wraps `QueryPipeline.run()` — v1.3 retrieval behavior
preserved on existing test fixtures (no recall/rank regression).
`RefinedRetrieveTool` shares `_retrieve_impl` with `RetrieveTool`.
`WebSearchTool` placeholder registered but excluded from
`AGENT_TOOL_ALLOWLIST` — proves pluggability with a non-RAG implementation.

`Executor` dispatches strictly through the registry; no direct imports of
tool classes by name in pipeline code. Tool authoring guide stub at
[docs/agent-architecture.md#authoring-tools](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/docs/agent-architecture.md#authoring-tools) with one runnable example.

Closes AGENT-07.
See [Phase 17 SUMMARY](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/.planning/phases/17-tool-abstraction-retrievetool/17-03-SUMMARY.md).

### Phase 18 — SSE planner-trace event stream

New endpoint `POST /api/v1/agent/v1/run/stream` emits a structured event
stream as the agent runs:

| Event | Emitted | Contains |
|-------|---------|----------|
| `planner.plan` | once per non-terminal `ToolPlan` | the full `ToolPlan` |
| `tool.span.start` | once per dispatch (before await) | `span_id`, tool `name`, `args` |
| `tool.span.end` | once per resolved dispatch | `latency_ms`, `chunk_count`, `is_error`, `content_preview` (200-char) |
| `tool.span.error` | replaces end on `BaseException` | `error_type`, `error_message` (200-char) |
| `executor.parallel` | once per group at group END | `fan_out`, `group_latency_ms` |
| `synthesizer.final` | terminal | `answer`, `sources_count` |

Latency assertion: agentic queries with N parallel tools complete in
`max(tool_latency) + planner + synthesizer + small overhead`, NOT
`sum(tool_latency)`. Verified by integration test
`tests/unit/test_agent_sse.py::test_run_streaming_latency_bounded_by_max_not_sum_d14_sc4`
(4 × 0.5 s tools complete in 450..700 ms wall-time).

Closes AGENT-04.
See [Phase 18 SUMMARY](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/.planning/phases/18-sse-planner-trace-event-stream/18-03-SUMMARY.md).

### Phase 19 — Agent-first docs + demo + release

`docs/agent-architecture.md` now covers the Concept → Tool authoring → Wire
format trilogy with a runnable code snippet in each section.

`make demo-agent` runs the 4-tool parallel fan-out from a clean checkout in
~1.5 seconds. Stub LLM + fixture tools — no API keys required, no Docker
stack required. The same code path as the SC4 latency test; the demo IS the
integration test, dressed up with a real query string.

README rewritten with agent-first framing; v1.3 technical content preserved
under `## Platform features` (D-04 — no information lost, framing inverted).
Asciinema cast embedded near the top showing the SSE event timeline with
visible parallel fan-out.

Closes AGENT-08.
See [Phase 19 SUMMARY](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/.planning/phases/19-agent-first-docs-demo-release/19-08-SUMMARY.md).

## Demo

Replay locally: [`docs/demo.cast`](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/docs/demo.cast). Run `asciinema play docs/demo.cast` (asciinema only required to PLAY the cast — the demo itself does not depend on it).

From a clean checkout:

```bash
git clone https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise.git && cd <repo>
make demo-agent
```

Exits 0 in ~1.5 s. Prints the SSE event stream to stdout. No API keys, no
Docker stack required.

## Carried forward from v1.3

- PostgreSQL + pgvector with HNSW + Row-Level Security (multi-tenant by construction)
- Hybrid retrieval (dense + BM25 + RRF + reranker) — now inside `RetrieveTool`
- Async ingest (`POST /ingest/async` + ARQ/Redis worker)
- Image extraction via PyMuPDF (AGPL-3.0 — commercial deployments require a separate license)
- JWT startup validation, per-route rate limiting, PII blocking, CORS lockdown
- Combined unit + integration coverage with ≥ 70% floor (TEST-06) and ≥ 80% diff-cover gate (TEST-03)
- Provider-neutral agentic layer (`BaseLLMClient.call_agentic_turn` — Anthropic, OpenAI, Azure, Ollama)

## Upgrade notes

- **Endpoint surface:** `/query`, `/query/stream`, `/query/agent`, `/ingest`,
  `/ingest/async`, `/ingest/status/{task_id}` UNCHANGED. The new
  `/agent/v1/run/stream` endpoint is the canonical agent-streaming
  entrypoint going forward; the legacy `/query?agent_mode=true` path remains
  as a thin alias.
- **Tool registration:** custom tools authored against the v1.4 `BaseTool`
  ABC will continue to work in v1.5+ when MCP plug-in discovery replaces
  the static class registry — the `BaseTool` interface is the stable
  contract.
- **SSE event schema:** the 6-event surface is locked; future minor
  versions may add fields (additive) but will not rename or remove existing
  ones. Subscribe via `EventSource` (consumer snippet in
  [docs/agent-architecture.md#consuming-the-stream](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/docs/agent-architecture.md#consuming-the-stream)).

## Roadmap (next)

Deferred to v1.5+:

- Real `WebSearchTool` implementation (placeholder in v1.4)
- `SQLTool`, `MCPTool`
- `SwarmQueryPipeline.run_streaming` (Phase 18 D-11 deferral)
- OpenTelemetry-style trace propagation (Phase 18 D-08 — currently 8-hex `trace_id`)
- GitHub Actions auto-tag workflow

See [.planning/ROADMAP.md](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/.planning/ROADMAP.md) for the full forward plan.

## Acknowledgements

v1.0..v1.3 milestones: see [CHANGELOG.md](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/blob/v1.4.0/CHANGELOG.md).
Per-milestone roadmaps archived under [.planning/milestones/](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/tree/v1.4.0/.planning/milestones/).

---

Full diff: `v1.3.0...v1.4.0` ([compare](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.3.0...v1.4.0)).
