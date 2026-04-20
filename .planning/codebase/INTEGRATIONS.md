# External Integrations

**Analysis Date:** 2026-04-20

## Summary

The system integrates with multiple interchangeable LLM providers (OpenAI, Anthropic, Azure OpenAI, or local Ollama), multiple vector store backends (Qdrant, pgvector, Chroma), Redis for caching and rate limiting, and optional observability services (Langfuse, OpenTelemetry, Prometheus/Grafana). All integrations are configured via environment variables and can be switched without code changes.

## LLM Providers (Switchable via `LLM_PROVIDER`)

**Ollama (default in Docker):**
- Purpose: Local LLM inference (Qwen2.5:14b default), local embedding (BGE-M3)
- Endpoint: `http://localhost:11434` (local) / `http://ollama:11434` (Docker)
- Docker image: `ollama/ollama:0.5.4`
- Models: `qwen2.5:14b` (generation), `bge-m3` (embedding)
- Config: `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `EMBEDDING_MODEL`
- GPU: optional via nvidia-container-toolkit

**OpenAI:**
- Purpose: GPT-4o for generation, Ada/text-embedding for embedding, GPT-4o as RAGAS judge
- Auth env var: `OPENAI_API_KEY`
- Config: `OPENAI_MODEL` (default: `gpt-4o`)
- SDK: `openai==1.59.6`

**Anthropic:**
- Purpose: Claude (claude-sonnet-4-6) for generation or RAGAS judge
- Auth env var: `ANTHROPIC_API_KEY`
- Config: `ANTHROPIC_MODEL` (default: `claude-sonnet-4-6`)
- SDK: `anthropic==0.43.0`
- Context window: auto-detected (200k for Sonnet/Opus 4+)

**Azure OpenAI:**
- Purpose: Enterprise GPT-4o via Azure deployment
- Config: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`
- Auth: uses `OPENAI_API_KEY` (Azure-scoped)

## Embedding Providers (Switchable via `EMBEDDING_PROVIDER`)

**HuggingFace (local, default in dev):**
- Model: BGE-M3 (`bge-m3`), 1024-dim
- Path: `MODEL_DIR/embedding_models/bge-m3` (default `/mnt/f/my_models/...`)
- SDK: `sentence-transformers==3.3.1`
- Config: `EMBEDDING_MODEL_PATH`, `EMBEDDING_DIM`

**Ollama (default in Docker):**
- Shared Ollama service endpoint

**OpenAI:**
- Uses OpenAI embedding API via `OPENAI_API_KEY`

## Reranker

**Local Cross-Encoder:**
- Model: BGE-M3 reranker (`bge-m3-rerank`) or `cross-encoder/ms-marco-MiniLM-L-6-v2`
- Path: `MODEL_DIR/embedding_models/bge-m3-rerank`
- SDK: `sentence-transformers==3.3.1`

**Reranker Microservice (optional):**
- Purpose: Offload Cross-Encoder to a dedicated HTTP service
- Endpoint: `RERANKER_SERVICE_URL` (default `http://reranker:8001`)
- SLA: `RERANKER_SLA_MS=45ms` (auto-fallback to local on timeout)
- Docker image: built from `services/reranker_service/Dockerfile`

## Data Storage

**Vector Database — Qdrant (recommended production):**
- Docker image: `qdrant/qdrant:v1.11.5`
- REST endpoint: `http://localhost:6333` / `http://qdrant:6333` (Docker)
- gRPC endpoint: port 6334
- Collection: `rag_enterprise_v3` (configurable via `QDRANT_COLLECTION`)
- Client: `qdrant-client==1.12.1`
- Auth: `QDRANT_API_KEY` (optional)
- Config file: `docker/qdrant/config.yaml`
- Storage: Docker volume `qdrant-storage`

**Vector Database — pgvector (alternative):**
- Purpose: PostgreSQL with pgvector extension
- Connection: `PG_DSN` (default: `postgresql+asyncpg://rag:rag@localhost:5432/ragdb`)
- Client: `asyncpg==0.30.0`

**Vector Database — Chroma (dev/PoC):**
- Client: `chromadb==0.6.3`
- Not recommended for production (no distributed persistence)

**Cache & Rate Limiting — Redis:**
- Docker image: `redis:7.4-alpine`
- Connection: `REDIS_URL` (default: `redis://localhost:6379/0`)
- Client: `redis[asyncio]==5.2.1`
- Config file: `docker/redis/redis.conf`
- Storage: Docker volume `redis-data`
- Use cases:
  - Query result cache (TTL: `CACHE_TTL_SEC=3600`)
  - Distributed rate limiting (sliding window Sorted Set, `RATE_LIMIT_RPM=60`)
  - Short-term conversation memory (session TTL: `SESSION_TTL_SEC=7200`)
  - Fallback: in-process dict if Redis unavailable (fail-open)

**Long-term Memory — PostgreSQL:**
- Connection: same `PG_DSN` as pgvector
- Purpose: persistent conversation memory + audit log (`audit_db_enabled=True`)

## Authentication & Identity

**JWT (Local):**
- Library: `python-jose[cryptography]==3.3.0`
- Algorithm: HS256 (configurable: HS384, HS512)
- Secret: `SECRET_KEY` env var (must be changed in production)
- Expiry: `JWT_EXPIRE_MINUTES=60`
- Implementation: `services/auth/oidc_auth.py`

**OIDC / SSO (Enterprise):**
- Enabled via: `OIDC_ENABLED=true`
- Config: `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_AUDIENCE`
- Compatible issuers: Azure AD (`https://login.microsoftonline.com/{tid}/v2.0`), any OIDC provider
- Middleware: `auth_middleware` in `main.py` — parses `Authorization: Bearer <token>`, sets `request.state.user`

## Monitoring & Observability

**Prometheus:**
- Docker image: `prom/prometheus:v2.51.2`
- Port: 9090
- Scrape target: `rag-api:8000/metrics`
- Config: `docker/prometheus/prometheus.yml`
- Alert rules: `docker/prometheus/rules/rag_alerts.yml`
- Metrics exported via `prometheus-client==0.21.1`
- Retention: 15 days
- App metrics: `http_requests_total`, `active_requests_gauge`, `rate_limit_hits_total`, `auth_attempts_total`

**Grafana:**
- Docker image: `grafana/grafana:11.0.0`
- Port: 3000
- Datasource: Prometheus (auto-provisioned via `docker/grafana/provisioning/datasources/prometheus.yml`)
- Dashboard: RAG overview (`docker/grafana/provisioning/dashboards/rag_overview.json`)
- Auth: `GRAFANA_USER` / `GRAFANA_PASSWORD` env vars

**Langfuse (LLM Observability):**
- Purpose: LLM call tracing, prompt tracking
- Enabled via: `LANGFUSE_ENABLED=true`
- Config: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` (default: `https://cloud.langfuse.com`)
- SDK: `langfuse==2.57.2`
- Flush called on app shutdown to prevent data loss

**OpenTelemetry (Distributed Tracing):**
- Enabled via: `OTEL_ENABLED=true`
- Exporter: OTLP (`OTEL_ENDPOINT=http://localhost:4317`)
- SDK: `opentelemetry-sdk==1.29.0` + `opentelemetry-exporter-otlp==1.29.0`

## Event Bus / Message Queue

**In-Process Event Bus (default):**
- Implementation: `services/events/event_bus.py`
- Used for: feedback-driven reindex events (`REINDEX_REQUESTED`)
- No external dependency when `KAFKA_BOOTSTRAP_SERVERS` is empty

**Kafka (optional, production-scale):**
- Enabled by setting: `KAFKA_BOOTSTRAP_SERVERS=localhost:9092`
- Topic prefix: `KAFKA_TOPIC_PREFIX=rag`
- No Kafka container in default `docker-compose.yml` (external cluster assumed)

## Reverse Proxy

**Nginx:**
- Docker image: `nginx:1.27-alpine`
- Ports: 80 (HTTP), 443 (HTTPS)
- Config: `docker/nginx/nginx.conf`, `docker/nginx/conf.d/rag.conf`
- Role: load balancing across `rag-api` instances, TLS termination
- TLS: mount Let's Encrypt or enterprise certs at `/etc/letsencrypt`

## CI/CD & Deployment

**Container Orchestration:**
- Docker Compose (`docker-compose.yml`) — primary deployment
- Kubernetes (`k8s/`) — HPA, blue/green deployments, ingress, StatefulSet for Qdrant

**Kubernetes Resources:**
- `k8s/rag-api/deployment.yaml` + `hpa.yaml` + `service.yaml`
- `k8s/qdrant/statefulset.yaml`
- `k8s/redis/deployment.yaml`
- `k8s/ingress.yaml`, `k8s/configmap.yaml`, `k8s/namespace.yaml`
- Blue/green: `k8s/blue-green/deployment-blue.yaml` + `deployment-green.yaml`

**No CI pipeline detected** — no `.github/workflows/` or similar CI config present (`.github/` directory listed as untracked in git status).

## RAG Evaluation

**RAGAS:**
- Framework: `ragas==0.2.6`
- Metrics: faithfulness, answer relevancy, context precision
- Dataset: `eval/datasets/qa_pairs.json`
- Judge model: GPT-4o (default) or Claude via `RAGAS_JUDGE_PROVIDER` / `RAGAS_JUDGE_API_KEY`
- Runner: `eval/ragas_runner.py`
- Reports: HTML via Jinja2 (`eval/report_renderer.py`), Excel via openpyxl
- Docker service: `ragas-eval` (one-shot run mode)

## Environment Variables (Key List)

Required for production operation:
- `SECRET_KEY` — JWT signing key (must replace default)
- `OPENAI_API_KEY` — if using OpenAI LLM or embeddings
- `ANTHROPIC_API_KEY` — if using Anthropic LLM
- `QDRANT_API_KEY` — if Qdrant authentication is enabled
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` — if Langfuse enabled
- `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_AUDIENCE` — if OIDC SSO enabled
- `GRAFANA_USER`, `GRAFANA_PASSWORD` — Grafana admin credentials
- `KAFKA_BOOTSTRAP_SERVERS` — if Kafka event bus enabled

Infrastructure (with defaults):
- `REDIS_URL` (default: `redis://localhost:6379/0`)
- `QDRANT_URL` (default: `http://localhost:6333`)
- `OLLAMA_BASE_URL` (default: `http://localhost:11434`)
- `PG_DSN` (default: `postgresql+asyncpg://rag:rag@localhost:5432/ragdb`)

## Sources

Files examined: `requirements.txt`, `requirements-eval.txt`, `config/settings.py`, `main.py`, `Dockerfile`, `docker-compose.yml`, directory listing of `services/`
