# EnterpriseRAG

A Planner → Executor → Synthesizer agent. RAG is one of its tools.

Multi-tenant document understanding, parallel tool dispatch, structured event
stream — built on FastAPI + PostgreSQL/pgvector. Provider-neutral across
Anthropic, OpenAI, Azure, and Ollama.

## Quick demo

`make demo-agent` runs a 4-tool parallel `RetrieveTool` plan against fixture data
(no API keys required). Replay the recorded session locally:

```bash
asciinema play docs/demo.cast
```

The cast file lives in-repo at [`docs/demo.cast`](docs/demo.cast) (asciicast v2,
~0.6s playback, 11 SSE events).

<!--
GitHub-inline asciinema render — populate after a maintainer runs
`asciinema upload docs/demo.cast` post-merge. Replace <ID> with the returned
asciinema.org id; the SVG below renders inline on github.com.

<a href="https://asciinema.org/a/<ID>" target="_blank">
  <img src="https://asciinema.org/a/<ID>.svg" alt="Phase 19 demo: 4-way parallel tool fan-out via SSE event stream" width="720">
</a>
-->

Each `tool.span.start` event fires near-simultaneously; each `tool.span.end`
event fires ~500 ms later, bounded by `max(tool_latency)`, not the sum. The SSE
event stream IS the architectural surface — what you see in the cast is what
`POST /api/v1/agent/v1/run/stream` emits over the wire.

## Architecture

```
Request ──▶ Planner ──ToolPlan──▶ Executor ──results──▶ Synthesizer ──▶ Response
                                     │
                              parallel dispatch
                              (asyncio.as_completed,
                               BaseException isolation)
```

Three explicit collaborators behind a Pydantic V2 frozen contract. The
Planner is stateless and provider-neutral (`BaseLLMClient.call_agentic_turn`).
The Executor walks `ToolPlan.parallel_groups` via `asyncio.as_completed`. The
Synthesizer is the LLM's terminal turn after results return.

Full mental model + signatures + runnable example: [Planner / Executor Model](docs/agent-architecture.md#planner-executor-model).

## Tools the agent calls

Tools register via a static class registry (`services/agent/tools/registry.py`)
and are dispatched provider-neutrally. The planner sees only tools listed in
`AGENT_TOOL_ALLOWLIST` in `services/pipeline.py`.

| Tool | Status | Implementation |
|------|--------|----------------|
| `RetrieveTool` | shipped (v1.4) | Hybrid pgvector + BM25 + RRF + reranker (Phase 17). Wraps `QueryPipeline.run()` — v1.3 retrieval behavior preserved. |
| `RefinedRetrieveTool` | shipped (v1.4) | LLM-driven query refinement before retrieval (Phase 17). |
| `WebSearchTool` | placeholder | Registered but excluded from `AGENT_TOOL_ALLOWLIST`. Real implementation deferred to v1.5+. |
| `SQLTool` | planned | Tool-authoring example shipped in [docs/agent-architecture.md#authoring-tools](docs/agent-architecture.md#authoring-tools). |
| `MCPTool` | planned | MCP plug-in discovery as a registry replacement — interface clean enough that callsites do not change. |

Add a tool: see [Authoring Tools](docs/agent-architecture.md#authoring-tools).

## Platform features

Each item below is a tool the agent calls OR a supporting service the agent depends on.

### Multi-tenant isolation
PostgreSQL Row-Level Security; each tenant's data is strictly separated at the database level. Every `RetrieveTool` dispatch carries a `tenant_id` that the executor scopes via Postgres RLS — no cross-tenant leakage by construction.

### Hybrid retrieval (RetrieveTool internals)
Dense vector search (pgvector HNSW, `ef_construction=200 m=16`) + BM25 sparse, fused with RRF; HyDE and multi-query expansion. The reranker runs cross-encoder over the top-K fused candidates. The legacy 10-stage query pipeline (NLU → memory → rewrite → HyDE → hybrid retrieval → rerank → rules → generate → audit → stream) lives intact behind `QueryPipeline.run()` and is what `RetrieveTool` wraps.

### Document ingestion
Six-stage pipeline: preprocess → extract → PII detect → chunk → vectorize → audit. Async variant returns a `task_id` immediately (`POST /ingest/async`); ARQ/Redis worker processes in background; poll status via `GET /ingest/status/{task_id}`.

### Image extraction
PDF-embedded images extracted via PyMuPDF, captioned by LLM, stored as retrievable `chunk_type="image"` vector chunks. Note: PyMuPDF is licensed under AGPL-3.0 — commercial on-premise deployments require a separate license.

### Provider neutrality
`BaseLLMClient.call_agentic_turn` (Phase 11) abstracts Anthropic Tool Use, OpenAI function-calling, Azure, and Ollama into one shape. The Planner consumes only this interface — no provider branches in pipeline code. `parallel_tool_calls=True` enabled on OpenAI; `disable_parallel_tool_use=False` on Anthropic. Providers without native tool-use (e.g. Ollama in v1.2) gracefully fall back to the fixed `QueryPipeline`; the pipeline catches `NotImplementedError` from the adapter and emits a structured-log warning.

### Security
JWT startup validation, per-route rate limiting, PII blocking by default, CORS locked to explicit origins. v1.0 hardening + v1.1 multi-tenant RLS form the defense-in-depth baseline. Auth is OIDC/JWT via `services/auth/`.

### Module layout

```
controllers/api.py          HTTP layer (FastAPI routes, auth, rate-limit, SSE)
    │
services/pipeline.py        IngestionPipeline / QueryPipeline / AgentQueryPipeline
    │
services/
    agent/                  Planner / Executor / Synthesizer + tools/ registry (v1.4 core)
    preprocessor/           Stage 1 — clean, deduplicate, language detect
    extractor/              Stage 2 — PDF text + image extraction (PyMuPDF)
    doc_processor/          Stage 3/4 — PII detection, chunking strategies
    vectorizer/             Stage 5 — BGE-M3 embedding, pgvector upsert
    retriever/              Dense + BM25 + RRF fusion + reranker
    generator/              LLM client (Ollama / OpenAI / Anthropic / Azure)
    nlu/                    Filter extraction (intent classification by Planner — Phase 16)
    memory/                 Redis short-term + PostgreSQL long-term
    auth/                   OIDC/JWT validation
    audit/                  Buffered audit log
    rules/                  Business rules engine (ABC enforcement)
    knowledge/              Version control + quality validation
    ab_test/                A/B experiment service
    events/                 In-process or Kafka event bus

utils/                      Shared: models, logger, cache, metrics, tasks
config/settings.py          Pydantic V2 BaseSettings — all config via env vars
```

**Stack:** PostgreSQL + pgvector (HNSW), ARQ + Redis, OIDC/JWT, FastAPI.

### Testing & coverage

| Gate | Threshold | Scope |
|------|-----------|-------|
| Combined coverage | ≥ 70% (TEST-06, v1.3 Phase 15) | unit + integration |
| Diff-coverage | ≥ 80% on changed lines (TEST-03) | per-PR |
| RAGAS faithfulness | > 0.85 | 200 stratified QA pairs, judge model |
| RAGAS answer relevancy | > 0.80 | same suite |

Run locally: `make test`, `make coverage-combined`, `make eval`. CI enforces all four on PRs against `master`.

The `coverage-combine` job (Phase 15) downloads the unit and integration `.coverage` artifacts, runs `coverage combine`, then `coverage report --fail-under=70` and `diff-cover coverage.xml --fail-under=80` on the combined artifact. A floor below 70% OR diff-coverage below 80% **blocks the merge** — no override comments, no soft-warn mode. Phase 10's "only unit-test coverage counts" decision is superseded by Phase 15's combined-report rule.

**Per-module floor (Phase 22, v1.5):** Five high-traffic modules carry a per-module ≥70% line-coverage gate in addition to the global ≥70% combined floor: `services/pipeline.py`, `services/generator/llm_client.py`, `services/vectorizer/vector_store.py`, `services/retriever/retriever.py`, `services/extractor/extractor.py`. CI fails the `coverage-combine` job if any of these regress below 70%. Run `make coverage-per-module` locally to mirror the CI check.

## Observability

The agent runtime emits a structured SSE event stream on `POST /api/v1/agent/v1/run/stream` (Phase 18, AGENT-04). Six event types: `planner.plan`, `tool.span.start`, `tool.span.end`, `tool.span.error`, `executor.parallel`, `synthesizer.final`. Each carries a `trace_id`, monotonic `seq`, and `ts_ms`. Wire format + payload tables: [Event Schema Reference](docs/agent-architecture.md#event-schema-reference).

Other observability: Prometheus metrics on `/metrics`; structured logging via `structlog`; optional Langfuse tracing; buffered audit log with flush.

## Quick start

### Try the demo first

```bash
git clone <repo-url> && cd rag_enterprise
make demo-agent
```

Stub-LLM, fixture-only, no API keys needed. Exits 0 in ~1.5s and prints the SSE event stream to stdout.

### Docker stack

#### 1. Configure environment

```bash
cp .env.docker .env.docker.local   # keep original as template
```

Edit `.env.docker.local`:

```bash
# Required — server refuses to start without a strong key
SECRET_KEY=$(openssl rand -hex 32)

# Required — path for model files inside the container
APP_MODEL_DIR=/app/models

# Choose one LLM provider:
LLM_PROVIDER=ollama          # local, no API key needed (default)
OLLAMA_MODEL=qwen2.5:14b

# LLM_PROVIDER=openai
# OPENAI_API_KEY=sk-...

# LLM_PROVIDER=anthropic
# ANTHROPIC_API_KEY=sk-ant-...
```

#### 2. Place documents

Put source files under `data/raw/`. Supported formats:

| Format | Extensions |
|--------|-----------|
| PDF | `.pdf` |
| Word | `.docx` `.doc` |
| Excel | `.xlsx` `.xls` |
| Text | `.txt` `.md` `.csv` `.json` |
| Web | `.html` `.htm` |

#### 3. Start the stack

```bash
make build        # build images (first time or after code changes)
make up           # start all services in background
make logs-all     # watch logs — wait for ollama-init to finish pulling models
make health       # confirm API is up: {"status": "ok"}
```

Services started: `rag-api`, `qdrant`, `redis`, `ollama`, `ollama-init` (one-shot model pull), `arq-worker`, `nginx`.

#### 4. Ingest documents

```bash
make ingest       # scans /app/data/raw inside the container
```

To ingest a local directory not yet in the container:

```bash
docker cp ./data/raw/. $(docker ps -qf name=rag-api):/app/data/raw/
make ingest
```

For local development without Docker:

```bash
conda run -n torch_env python scripts/ingest_batch.py \
    --dir ./data/raw \
    --recursive \
    --concurrency 3
```

### Local dev

```bash
# 1. Infrastructure
docker run -d -p 5432:5432 \
    -e POSTGRES_USER=rag -e POSTGRES_PASSWORD=rag -e POSTGRES_DB=ragdb \
    ankane/pgvector
docker run -d -p 6379:6379 redis:7-alpine

# 2. Environment
cp .env.docker .env
# Edit .env:
#   SECRET_KEY=<openssl rand -hex 32>
#   APP_MODEL_DIR=/tmp/models
#   VECTOR_STORE=pgvector
#   PG_DSN=postgresql+asyncpg://rag:rag@localhost:5432/ragdb
#   LLM_PROVIDER=anthropic
#   ANTHROPIC_API_KEY=sk-ant-...

# 3. Install dependencies
conda activate torch_env
pip install -r requirements.txt

# 4. Run
uvicorn main:app --reload --port 8000
```

### cURL example

Stream events from a real agent invocation:

```bash
curl --no-buffer -X POST http://localhost:8000/api/v1/agent/v1/run/stream \
    -H "Authorization: Bearer <JWT>" \
    -H "Content-Type: application/json" \
    -d '{
        "query": "What is the annual leave policy?",
        "session_id": "user-123",
        "tenant_id": "demo-tenant",
        "user_id": "demo-user",
        "top_k": 5
    }'
```

`<JWT>` is a token issued by your identity provider; see `services/auth/` for OIDC integration. Replace `demo-tenant` with the tenant ID your JWT scopes you to.

### Configuration

All settings are read from environment variables (or `.env` file). Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | JWT signing key — must be ≥32 chars, not a known-weak value |
| `APP_MODEL_DIR` | Yes | Path to model files directory |
| `LLM_PROVIDER` | No | `ollama` (default) / `openai` / `anthropic` / `azure` |
| `VECTOR_STORE` | No | `qdrant` (default Docker) / `pgvector` |
| `PG_DSN` | If pgvector | `postgresql+asyncpg://user:pass@host/db` |
| `REDIS_URL` | No | Default `redis://localhost:6379/0` |
| `ENVIRONMENT` | No | `development` / `staging` / `production` |
| `CORS_ORIGINS` | Production | Comma-separated allowed origins (no localhost in prod) |

See `config/settings.py` for the full list with defaults.

## Project status

**Current release:** v1.4 — Agent-First Architecture Inversion (Phases 16–19).

- **Design doc:** [docs/v1.4-design.md](docs/v1.4-design.md) — the architectural-inversion thesis (Approach A: incremental refactor, no framework lock-in).
- **Phase summaries:** [Planner + Executor Extraction](.planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md) · [Tool Abstraction + RetrieveTool](.planning/phases/17-tool-abstraction-retrievetool/17-03-SUMMARY.md) · [SSE Event Stream](.planning/phases/18-sse-planner-trace-event-stream/18-03-SUMMARY.md) · Agent-First Docs + Demo + Release (this milestone).
- **Changelog:** [CHANGELOG.md](CHANGELOG.md) (keep-a-changelog 1.1.0 format; v1.0 → v1.4 reverse-chronological).
- **Roadmap:** [.planning/ROADMAP.md](.planning/ROADMAP.md).

Prior milestones (archived): v1.0 Hardening · v1.1 Retrieval Depth & Frontend · v1.2 Agentic Layer + Swarm · v1.3 Fork Swarm, NLU & Quality. Per-milestone roadmaps live under `.planning/milestones/`.

## License

See [SECURITY.md](SECURITY.md) for security policy. PyMuPDF (image extraction) is licensed under AGPL-3.0 — commercial on-premise deployments require a separate license.
