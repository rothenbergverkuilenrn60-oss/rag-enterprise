# Technology Stack

**Analysis Date:** 2026-04-20

## Summary

Enterprise RAG system built on Python 3.11 with FastAPI as the web framework. The pipeline covers document ingestion → extraction → chunking → embedding → vector storage → hybrid retrieval → LLM generation. All dependencies are pinned for reproducibility; the system is designed to run fully on-premise (Ollama) or via cloud LLM APIs.

## Languages

**Primary:**
- Python 3.11 — all application code, services, controllers, utilities

**Secondary:**
- YAML — Docker Compose, Kubernetes manifests, Prometheus/Grafana config
- Shell — Ollama model pull init scripts (`docker/ollama/pull_models.sh`)

## Runtime

**Environment:**
- Python 3.11 (base image `python:3.11-slim` in Docker)
- Conda environment: `torch_env` (local dev install target per `requirements.txt` header)

**Package Manager:**
- pip (with pre-compiled wheels in Docker multi-stage build)
- Lockfile: pinned versions in `requirements.txt`, `requirements-dev.txt`, `requirements-eval.txt`

## Frameworks

**Web:**
- FastAPI `0.115.6` — async REST API, lifespan management, middleware stack
- Uvicorn `0.32.1` (with `uvloop` + `httptools` for production performance) — ASGI server

**Data Validation & Settings:**
- Pydantic `2.10.4` — request/response models, DTOs
- pydantic-settings `2.7.0` — environment-based config via `config/settings.py`

**Testing:**
- pytest `8.3.4` — test runner
- pytest-asyncio `0.24.0` — async test support
- pytest-cov `6.0.0` — coverage reporting
- pytest-timeout `2.3.1` — test timeouts

**Evaluation:**
- RAGAS `0.2.6` — RAG pipeline quality evaluation (faithfulness, answer relevancy, context precision)
- LangChain `0.3.14` / langchain-community / langchain-openai — RAGAS internal dependency

**Build/Dev:**
- ruff `0.8.6` — linting
- mypy `1.14.0` — static type checking
- bandit `1.8.0` — security scanning

## Key Dependencies

**LLM Clients:**
- openai `1.59.6` — OpenAI GPT-4o API + embeddings + RAGAS judge model
- anthropic `0.43.0` — Anthropic Claude API (primary: `claude-sonnet-4-6`)

**Embedding & Reranking:**
- sentence-transformers `3.3.1` — HuggingFace BGE-M3 embeddings + Cross-Encoder reranker (local)

**Document Extraction:**
- PyMuPDF `1.25.1` — primary PDF parser
- pdfplumber `0.11.4` — PDF table extraction
- python-docx `1.1.2` — DOCX support
- openpyxl `3.1.5` — XLSX support
- pandas `2.2.3` — CSV/XLSX data handling
- beautifulsoup4 `4.12.3` + lxml `5.3.0` — HTML parsing

**Chunking & Token Handling:**
- tiktoken `0.8.0` — token counting (cl100k_base)
- langdetect `1.0.9` — language detection (Chinese/English)

**Vector Storage Clients:**
- qdrant-client `1.12.1` — Qdrant (recommended production)
- chromadb `0.6.3` — Chroma (dev/PoC)
- asyncpg `0.30.0` — PostgreSQL pgvector

**Sparse Retrieval:**
- rank-bm25 `0.2.2` — BM25 keyword indexing

**Caching:**
- redis `5.2.1` (asyncio) — distributed rate limiting, query cache, session memory

**Auth:**
- python-jose `3.3.0` [cryptography] — JWT signing/verification + OIDC token validation

**Observability:**
- prometheus-client `0.21.1` — `/metrics` endpoint
- langfuse `2.57.2` — LLM observability / tracing
- opentelemetry-sdk `1.29.0` + opentelemetry-exporter-otlp `1.29.0` — distributed tracing

**HTTP & Async:**
- httpx `0.28.1` — async HTTP client
- anyio `4.7.0` — async compatibility layer
- tenacity `9.0.0` — retry logic

**Logging:**
- loguru `0.7.3` — structured logging

## Configuration

**Environment:**
- All config via `config/settings.py` (`Settings(BaseSettings)`)
- Loaded from `.env` file at project root (or `APP_BASE_DIR` override)
- Docker: environment vars injected via `docker-compose.yml` anchors

**Key Config Areas (settings.py):**
- `llm_provider`: `ollama | openai | anthropic | azure`
- `embedding_provider`: `ollama | openai | huggingface`
- `vector_store`: `qdrant | milvus | pgvector | chroma`
- `chunk_primary_strategy`: `auto | structure | recursive | semantic | sentence`
- Rate limiting, JWT, OIDC, Prometheus, Langfuse, OpenTelemetry toggles

**Build:**
- `Dockerfile` — multi-stage build (builder + runtime), base `python:3.11-slim`
- `docker-compose.yml` — full production stack definition

## Platform Requirements

**Development:**
- Python 3.11, conda env `torch_env`
- Optional: local Ollama (`http://localhost:11434`) for offline LLM/embeddings
- Redis and Qdrant reachable (local Docker or remote)
- Model files at `/mnt/f/my_models/` (WSL2/Windows path convention)

**Production:**
- Docker Compose (primary) or Kubernetes (`k8s/` manifests with HPA)
- Non-root user `raguser` (uid 1001) inside container
- Port 8000 (API), behind Nginx reverse proxy on 80/443
- GPU optional for Ollama (nvidia-container-toolkit)
- Tesseract OCR (`tesseract-ocr`, `tesseract-ocr-chi-sim`) installed in runtime image

## Sources

Files examined: `requirements.txt`, `requirements-dev.txt`, `requirements-eval.txt`, `main.py`, `config/settings.py`, `Dockerfile`, `docker-compose.yml`
