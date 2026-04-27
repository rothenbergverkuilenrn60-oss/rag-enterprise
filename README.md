# EnterpriseRAG

A production-grade Retrieval-Augmented Generation platform built on FastAPI. Serves enterprise tenants with multi-tenant document ingestion, hybrid retrieval, and LLM-powered query answering.

## Features

- **Multi-tenant isolation** — PostgreSQL Row-Level Security; each tenant's data is strictly separated at the database level
- **Hybrid retrieval** — dense vector search (pgvector HNSW) + BM25 sparse, fused with RRF; HyDE and multi-query expansion
- **6-stage ingest pipeline** — preprocess → extract → PII detect → chunk → vectorize → audit
- **10-stage query pipeline** — NLU → memory → rewrite → HyDE → hybrid retrieval → rerank → rules → generate → audit → stream
- **Image extraction** — PDF-embedded images extracted, captioned by LLM, and stored as retrievable `chunk_type="image"` vector chunks
- **Async ingest** — `POST /ingest/async` returns a `task_id` immediately; ARQ/Redis worker processes in background; poll status via `GET /ingest/status/{task_id}`
- **Agentic RAG** — Anthropic Tool Use loop (max 5 iterations) for complex multi-step queries
- **Security** — JWT startup validation, per-route rate limiting, PII blocking by default, CORS locked to explicit origins
- **Observability** — Prometheus metrics, structured logging, optional Langfuse tracing, audit log with flush buffer
- **Streaming** — SSE responses for real-time token delivery

## Architecture

```
controllers/api.py          HTTP layer (FastAPI routes, auth, rate-limit, SSE)
    │
services/pipeline.py        IngestionPipeline / QueryPipeline / AgentQueryPipeline
    │
services/
    preprocessor/           Stage 1 — clean, deduplicate, language detect
    extractor/              Stage 2 — PDF text + image extraction (PyMuPDF)
    doc_processor/          Stage 3/4 — PII detection, chunking strategies
    vectorizer/             Stage 5 — BGE-M3 embedding, pgvector upsert
    retriever/              Dense + BM25 + RRF fusion + reranker
    generator/              LLM client (Ollama / OpenAI / Anthropic / Azure)
    nlu/                    Intent classification, entity disambiguation
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

**Vector store:** PostgreSQL + pgvector (HNSW index, `ef_construction=200 m=16`)  
**Task queue:** ARQ + Redis  
**Auth:** OIDC/JWT  

## Quick Start — Docker

### 1. Configure environment

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

### 2. Place documents

Put source files under `data/raw/`. Supported formats:

| Format | Extensions |
|--------|-----------|
| PDF | `.pdf` |
| Word | `.docx` `.doc` |
| Excel | `.xlsx` `.xls` |
| Text | `.txt` `.md` `.csv` `.json` |
| Web | `.html` `.htm` |

### 3. Start the stack

```bash
make build        # build images (first time or after code changes)
make up           # start all services in background
make logs-all     # watch logs — wait for ollama-init to finish pulling models
make health       # confirm API is up: {"status": "ok"}
```

Services started: `rag-api`, `qdrant`, `redis`, `ollama`, `ollama-init` (one-shot model pull), `arq-worker`, `nginx`.

### 4. Ingest documents

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

## Quick Start — Local Development

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

## API Reference

Base URL: `http://localhost:8000/api/v1`

All endpoints require `Authorization: Bearer <jwt_token>` except `/health` and `/readiness`.

### Core endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/readiness` | Readiness check (DB + Redis) |
| `POST` | `/query` | Synchronous RAG query |
| `POST` | `/query/stream` | Streaming SSE query |
| `POST` | `/query/agent` | Agentic multi-step query |
| `POST` | `/ingest` | Synchronous document ingest |
| `POST` | `/ingest/async` | Async ingest — returns `task_id` |
| `GET` | `/ingest/status/{task_id}` | Poll async ingest status |
| `GET` | `/metrics` | Prometheus metrics |

### Query example

```bash
curl -X POST http://localhost:8000/api/v1/query \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "query": "What is the annual leave policy?",
        "tenant_id": "acme",
        "session_id": "user-123"
    }'
```

### Async ingest example

```bash
# Submit
TASK=$(curl -s -X POST http://localhost:8000/api/v1/ingest/async \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"file_path": "/app/data/raw/policy.pdf", "tenant_id": "acme"}' \
    | jq -r .task_id)

# Poll
curl http://localhost:8000/api/v1/ingest/status/$TASK \
    -H "Authorization: Bearer $TOKEN"
# {"status": "complete", "task_id": "...", "error": null}
```

## Configuration

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

## Testing

```bash
# All unit tests
make test

# Unit tests only
make test-unit

# With coverage report
conda run -n torch_env pytest tests/unit/ -v --cov=services --cov-report=term-missing
```

Current coverage: **46.6%** (CI floor enforced). Target 80% deferred to v1.1.

## RAGAS Evaluation

```bash
# Run evaluation suite (requires OPENAI_API_KEY for judge model)
make eval

# Local run
make eval-local
```

Evaluates 200 stratified QA pairs against RAGAS `faithfulness > 0.85` and `answer_relevancy > 0.80` gates. Runs automatically on `main` branch CI.

## Makefile Reference

```
make build        Build all Docker images
make up           Start full stack (background)
make down         Stop containers (keep volumes)
make logs         Tail rag-api logs
make logs-all     Tail all service logs
make health       Check API health endpoint
make ingest       Batch ingest data/raw inside container
make test         Run unit tests locally
make eval         Run RAGAS evaluation (Docker)
make shell        Open shell in rag-api container
make clean        Prune Docker build cache
```

## License

See [SECURITY.md](SECURITY.md) for security policy. PyMuPDF (image extraction) is licensed under AGPL-3.0 — commercial on-premise deployments require a separate license.
