# Codebase Structure

**Analysis Date:** 2026-04-20

## Summary

The project is a single Python package rooted at `rag_enterprise/`. Source code is organized by layer and then by domain subdirectory under `services/`. Infrastructure config (Docker, K8s, Prometheus, Nginx) lives outside the Python package. Tests are co-located under `tests/` with `unit/` and `integration/` subdirectories.

## Directory Layout

```
rag_enterprise/                        # Project root
├── main.py                            # FastAPI app, middleware stack, lifespan
├── pytest.ini                         # Pytest configuration
├── requirements.txt                   # Runtime dependencies
├── requirements-dev.txt               # Dev/test dependencies
├── requirements-eval.txt              # Evaluation (RAGAS) dependencies
├── Makefile                           # Common dev commands
├── Dockerfile                         # Main app container
├── docker-compose.yml                 # Full local stack
│
├── config/
│   ├── __init__.py
│   └── settings.py                    # Pydantic BaseSettings — all app config
│
├── controllers/
│   ├── __init__.py
│   └── api.py                         # All FastAPI routes (single router, /api/v1 prefix)
│
├── services/
│   ├── __init__.py
│   ├── pipeline.py                    # IngestionPipeline, QueryPipeline, AgentQueryPipeline
│   ├── mcp_server.py                  # Model Context Protocol server (Claude agent integration)
│   │
│   ├── preprocessor/                  # STAGE 1 — cleaning, dedup, PII
│   │   ├── cleaner.py                 # Text normalization, duplicate fingerprinting
│   │   └── pii_detector.py            # Regex + optional ML PII detection and masking
│   │
│   ├── extractor/                     # STAGE 2 — file format parsing
│   │   └── extractor.py               # PDF/DOCX/XLSX/CSV/HTML/JSON/TXT/MD → ExtractedDocument
│   │
│   ├── doc_processor/                 # STAGE 3 — chunking
│   │   └── chunker.py                 # Four-layer chunking (semantic, fixed, hierarchical, contextual)
│   │
│   ├── vectorizer/                    # STAGE 4 — embedding + storage
│   │   ├── embedder.py                # Embedding model client (Ollama/OpenAI/HuggingFace)
│   │   ├── indexer.py                 # Vectorizer orchestrator; BM25 index management
│   │   └── vector_store.py            # Qdrant vector store client (CRUD + ANN search)
│   │
│   ├── retriever/                     # STAGE 5 — retrieval
│   │   └── retriever.py               # Dense+sparse hybrid, RRF fusion, cross-encoder reranking
│   │
│   ├── generator/                     # STAGE 6 — LLM generation
│   │   ├── generator.py               # RAG prompt construction, faithfulness scoring, streaming
│   │   └── llm_client.py              # LLM provider client (Anthropic/OpenAI/Ollama)
│   │
│   ├── nlu/                           # Query understanding
│   │   ├── nlu_service.py             # Intent classification, entity extraction, query rewriting
│   │   └── entity_disambiguator.py    # Entity disambiguation and normalization
│   │
│   ├── memory/                        # Conversation memory
│   │   └── memory_service.py          # Short-term (Redis) + long-term fact storage per session
│   │
│   ├── rules/                         # Business rules engine
│   │   └── rules_engine.py            # Pre/post query rules (BLOCK/MODIFY/PASS actions)
│   │
│   ├── tenant/                        # Multi-tenancy
│   │   └── tenant_service.py          # Tenant permission checks, Qdrant filter generation
│   │
│   ├── knowledge/                     # Knowledge base management
│   │   ├── knowledge_service.py       # Document quality validation, incremental scan-and-update
│   │   ├── summary_indexer.py         # LLM-generated document summaries, summary-layer retrieval
│   │   └── version_service.py         # Document version history (checksum, rollback)
│   │
│   ├── events/                        # Async event bus
│   │   └── event_bus.py               # In-process pub/sub (doc_ingested, query_completed, reindex_requested)
│   │
│   ├── auth/                          # Authentication
│   │   └── oidc_auth.py               # OIDC/JWT token verification; returns user identity object
│   │
│   ├── audit/                         # Audit logging
│   │   └── audit_service.py           # Buffered audit log (ingest, query, PII, permission denied, rules)
│   │
│   ├── feedback/                      # User feedback
│   │   └── feedback_service.py        # Positive/negative feedback storage, stats, reindex triggering
│   │
│   ├── annotation/                    # Human annotation
│   │   └── annotation_service.py      # Task queue (push/pop/skip), result submission, stats
│   │
│   ├── ab_test/                       # A/B testing
│   │   └── ab_test_service.py         # Experiment creation, traffic routing, variant stats, winner selection
│   │
│   └── reranker_service/              # Reranker microservice (optional sidecar)
│       └── app.py                     # Standalone FastAPI service for cross-encoder reranking
│
├── utils/
│   ├── models.py                      # All Pydantic DTOs (RawDocument, IngestionRequest/Response, GenerationRequest/Response, APIResponse, FeedbackRequest, AnnotationTask, etc.)
│   ├── cache.py                       # Redis connection, cache_get/set/invalidate helpers
│   ├── metrics.py                     # Prometheus counters, histograms, gauges; get_metrics_response()
│   ├── logger.py                      # Loguru setup, log_latency decorator
│   └── observability.py               # Langfuse + OpenTelemetry span management; setup_observability(), start_span(), flush()
│
├── eval/                              # Offline evaluation (RAGAS)
│   ├── models.py                      # Evaluation dataset/result models
│   ├── ragas_runner.py                # RAGAS metric computation (faithfulness, relevance, etc.)
│   ├── category_report.py             # Per-category breakdown reporting
│   └── report_renderer.py             # HTML/Markdown report generation
│
├── scripts/
│   └── ingest_batch.py                # CLI script for bulk document ingestion
│
├── tests/
│   ├── __init__.py
│   ├── unit/                          # Unit tests
│   └── integration/
│       └── test_pipeline.py           # Integration tests for full pipeline flows
│
├── data/
│   ├── raw/                           # Source documents (settings.data_dir)
│   ├── processed/                     # Post-extraction documents (settings.processed_dir)
│   └── index/                         # BM25 / local index files (settings.index_dir)
│
├── logs/                              # Application logs (settings.log_dir)
├── cache/                             # Local cache files (settings.cache_dir)
├── docs/                              # Project documentation
│
├── docker/                            # Docker service configs
│   ├── nginx/conf.d/                  # Nginx reverse proxy config
│   ├── prometheus/rules/              # Prometheus alerting rules
│   ├── grafana/provisioning/          # Grafana datasource + dashboard provisioning
│   ├── qdrant/                        # Qdrant config
│   ├── redis/                         # Redis config
│   ├── ollama/                        # Ollama model config
│   └── eval/                          # Eval container config
│
└── k8s/                               # Kubernetes manifests
    ├── rag-api/                       # API Deployment, Service, HPA
    ├── qdrant/                        # Qdrant StatefulSet
    ├── redis/                         # Redis Deployment
    ├── prometheus/                    # Prometheus RBAC + config
    ├── grafana/                       # Grafana Deployment
    └── blue-green/                    # Blue/green deployment manifests
```

## Key File Locations

**Entry Points:**
- `main.py`: FastAPI app instance, lifespan hooks, all middleware, Prometheus endpoint
- `controllers/api.py`: All HTTP route handlers under `/api/v1`
- `services/pipeline.py`: Pipeline orchestrators and singleton factories

**Configuration:**
- `config/settings.py`: Single `Settings` class (Pydantic BaseSettings); loaded from `.env`
- `.env`: Environment variable overrides (not committed)
- `docker-compose.yml`: Full local dev stack (Qdrant, Redis, Nginx, Prometheus, Grafana, Ollama)

**Core Logic:**
- `services/pipeline.py`: `IngestionPipeline._run_ingest()`, `QueryPipeline._run_query()`, `AgentQueryPipeline.run()`
- `services/retriever/retriever.py`: `rrf_fusion()`, `adaptive_rrf_fusion()`, `CrossEncoderReranker`, `Retriever.retrieve_multi_query()`
- `services/generator/generator.py`: RAG prompt builder, faithfulness scorer, streaming generator
- `services/generator/llm_client.py`: Unified LLM client abstraction (Anthropic/OpenAI/Ollama)

**Data Models:**
- `utils/models.py`: Source of truth for all DTOs shared across layers

**Testing:**
- `tests/unit/`: Unit tests for individual services
- `tests/integration/test_pipeline.py`: End-to-end pipeline integration tests
- `pytest.ini`: Test configuration, markers

## Naming Conventions

**Files:**
- Service files: `snake_case.py` named after their primary class (e.g., `embedder.py` contains `Embedder`)
- Each service subdirectory has an `__init__.py` (may re-export the `get_*()` factory)

**Directories:**
- Service subdirectories: `snake_case/` matching the domain name
- One domain per subdirectory; no cross-domain files within a subdirectory

**Classes:**
- Services: PascalCase (e.g., `IngestionPipeline`, `CrossEncoderReranker`, `KnowledgeService`)
- Singletons: module-level `_instance = None` + `get_<name>()` factory function

**Settings fields:**
- `snake_case` mapping to `UPPER_SNAKE_CASE` env vars (Pydantic BaseSettings auto-maps)

## Where to Add New Code

**New ingestion stage:**
- Create `services/<stage_name>/<stage_name>.py` with a singleton class + `get_<stage_name>()` factory
- Import and call in `services/pipeline.py` `IngestionPipeline.__init__()` and `_run_ingest()`

**New query stage:**
- Same pattern; wire into `QueryPipeline.__init__()` and `_run_query()`

**New API endpoint:**
- Add route handler to `controllers/api.py` using existing `router` — do NOT create a new router file
- Use `APIResponse` envelope for all responses
- Delegate immediately to a service or pipeline — no business logic in the controller

**New configuration option:**
- Add field to `config/settings.py` `Settings` class with default and description
- Access via imported `settings` singleton anywhere in the codebase

**New Pydantic model / DTO:**
- Add to `utils/models.py` — this is the single source of truth for shared types

**New utility:**
- Add to `utils/` if it is infrastructure (cache, metrics, logging, tracing)
- Do NOT add domain logic to `utils/`

**New Prometheus metric:**
- Define in `utils/metrics.py` alongside existing counters/histograms
- Import and increment/observe at the relevant pipeline step in `services/pipeline.py`

**New test:**
- Unit test: `tests/unit/test_<module>.py`
- Integration test: `tests/integration/test_<flow>.py`
- Use `pytest.mark.unit` / `pytest.mark.integration` markers (configured in `pytest.ini`)

## Special Directories

**`data/`:**
- Purpose: Runtime data files (raw docs, processed docs, BM25 index)
- Generated: Yes (populated by ingestion pipeline)
- Committed: No (data is runtime state)

**`logs/`:**
- Purpose: Loguru application logs
- Generated: Yes
- Committed: No

**`cache/`:**
- Purpose: Local file cache (non-Redis fallback)
- Generated: Yes
- Committed: No

**`eval/`:**
- Purpose: Offline RAGAS evaluation framework — separate from production code
- Generated: No (source code); `eval/datasets/` and `eval/{datasets,reports}/` are runtime outputs
- Committed: Source files yes; output files no

**`k8s/`:**
- Purpose: Production Kubernetes deployment manifests
- Generated: No
- Committed: Yes

**`docker/`:**
- Purpose: Per-service Docker and infrastructure configuration
- Generated: No
- Committed: Yes

---

## Sources

- `main.py`
- `controllers/api.py`
- `services/pipeline.py`
- `config/settings.py`
- Directory listing (all `.py` files, all subdirectories)
