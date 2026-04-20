# Architecture

**Analysis Date:** 2026-04-20

## Summary

EnterpriseRAG v3.0.0 is a FastAPI-based RAG (Retrieval-Augmented Generation) system with two primary pipelines: an ingestion pipeline (document processing → vector storage) and a query pipeline (NLU → hybrid retrieval → generation). The system is multi-tenant, supports both standard and agentic (tool-use) query modes, and exposes a full enterprise feature set including A/B testing, human annotation, audit logging, and streaming SSE responses.

## Pattern Overview

**Overall:** Layered pipeline architecture with service singletons

**Key Characteristics:**
- Two independent pipelines orchestrated by `services/pipeline.py`: `IngestionPipeline` and `QueryPipeline`
- Services are module-level singletons accessed via `get_*()` factory functions
- FastAPI router (`controllers/api.py`) is thin — delegates immediately to pipeline singletons
- Cross-cutting concerns (auth, rate-limit, metrics, tracing) handled in `main.py` middleware stack
- All inter-service communication is in-process (no message broker); async event publishing via `EventBus`

## Layers

**HTTP Layer:**
- Purpose: Request ingestion, middleware enforcement, routing
- Location: `main.py`, `controllers/api.py`
- Contains: FastAPI app, CORS/GZip middleware, rate-limit middleware, auth middleware, trace-ID injection, Prometheus metrics endpoint, all route handlers
- Depends on: Pipeline singletons, cache utilities
- Used by: External clients (HTTP)

**Pipeline Orchestration Layer:**
- Purpose: Full end-to-end pipeline coordination for ingestion and querying
- Location: `services/pipeline.py`
- Contains: `IngestionPipeline`, `QueryPipeline`, `AgentQueryPipeline`, singleton factory functions
- Depends on: All stage services, core services, enterprise services
- Used by: `controllers/api.py`

**Stage Services (Ingestion):**
- Purpose: Each discrete processing step in document ingestion
- Location: `services/preprocessor/`, `services/extractor/`, `services/doc_processor/`, `services/vectorizer/`
- Contains: Text cleaning, PII detection, document extraction (multi-format), chunking (four-layer), embedding, BM25 indexing, vector store write
- Depends on: `utils/models.py`, `config/settings.py`, external vector store (Qdrant)
- Used by: `IngestionPipeline`

**Stage Services (Query):**
- Purpose: Each discrete processing step in query handling
- Location: `services/nlu/`, `services/retriever/`, `services/generator/`
- Contains: Intent classification, entity extraction, query rewriting, dense+sparse+hybrid retrieval, RRF fusion, cross-encoder reranking, LLM generation
- Depends on: `services/vectorizer/vector_store.py`, LLM client, embedder
- Used by: `QueryPipeline`, `AgentQueryPipeline`

**Core Services:**
- Purpose: Cross-pipeline stateful services
- Location: `services/memory/`, `services/rules/`, `services/tenant/`, `services/events/`, `services/knowledge/`
- Contains: Conversation memory, business rules engine, multi-tenant access control, async event bus, knowledge versioning and quality validation
- Depends on: Redis (memory/cache), SQLite or similar (audit, versions)
- Used by: Both pipelines

**Enterprise Feature Services:**
- Purpose: Advanced operational capabilities
- Location: `services/audit/`, `services/feedback/`, `services/annotation/`, `services/ab_test/`, `services/auth/`
- Contains: Audit logging with flush buffer, user feedback and reindex triggering, human annotation task queue, A/B experiment management, OIDC/JWT auth
- Depends on: Core services, event bus
- Used by: Both pipelines + `controllers/api.py` directly

**Utilities:**
- Purpose: Shared infrastructure
- Location: `utils/`
- Contains: Pydantic models (`models.py`), Redis cache helpers (`cache.py`), Prometheus metrics (`metrics.py`), structured logging (`logger.py`), observability/tracing (`observability.py`)
- Depends on: Redis, Prometheus client, Langfuse/OpenTelemetry (optional)
- Used by: All layers

## Data Flow

**Ingestion Pipeline:**

1. HTTP POST `/api/v1/ingest` → `controllers/api.py` → `IngestionPipeline.run(IngestionRequest)`
2. `Preprocessor.process(RawDocument)` — text cleaning, duplicate detection
3. `PIIDetector.detect()` — scan and optionally mask PII; audit log if found
4. `Extractor.extract()` — parse file format (PDF/DOCX/XLSX/HTML/JSON/TXT/MD) into structured `ExtractedDocument`
5. `KnowledgeService.validate_document()` — quality gate (min length, structure checks)
6. `DocProcessor.process()` — four-layer chunking (semantic, fixed, hierarchical, contextual); optionally calls LLM for contextual retrieval enrichment
7. `Vectorizer.vectorize_and_store()` — embed chunks, write to Qdrant, update BM25 index
8. `SummaryIndexer.build_summaries()` — optional LLM-generated document-level summaries indexed separately
9. `VersionService.record_version()` — record checksum + chunk count
10. `EventBus.emit_doc_ingested()` — publish async event; `AuditService.log_ingest()` — write audit record

**Query Pipeline (standard):**

1. HTTP POST `/api/v1/query` → `controllers/api.py` → `QueryPipeline.run(GenerationRequest)`
2. `TenantService.check_permission()` — multi-tenant access gate
3. `RulesEngine.run("pre_query")` — keyword/pattern rules, may BLOCK request
4. `MemoryService.load_context()` — load short-term (last 6 turns) + long-term facts for session
5. `NLUService.analyze()` — intent classification (FACTUAL/CHITCHAT/COMPLEX/AMBIGUOUS), entity extraction, query rewriting (multi-query), dynamic top_k recommendation
6. Cache lookup (`cache_get`) — return cached `GenerationResponse` if hit
7. `SummaryIndexer.search_summaries()` — optional pre-retrieval to narrow candidate set
8. `Retriever.retrieve_multi_query()` — parallel dense (Qdrant ANN) + sparse (BM25) retrieval across rewritten queries; adaptive RRF fusion; cross-encoder reranking; parent-chunk lookback
9. `Generator.generate()` — build RAG prompt with retrieved chunks + memory context; call LLM; compute faithfulness score
10. `RulesEngine.run("post_answer")` + `run("quality_check")` — may MODIFY answer
11. `cache_set` — cache result; metrics emit; `AuditService.log_query()`; `MemoryService.save_turn()`; `EventBus.emit_query_completed()`

**Query Pipeline (agentic):**

1. `AgentQueryPipeline.run()` — requires Anthropic provider with native Tool Use
2. Multi-turn tool loop (max 5 iterations): Claude autonomously calls `search_knowledge_base` or `refine_search` tools
3. Each tool call → `Retriever.retrieve()` → results serialized as XML `<search_results>` blocks back to Claude
4. Loop ends when `stop_reason == "end_turn"`; final answer extracted from `content` blocks
5. Memory save + audit log same as standard pipeline

**Streaming Query:**

1. HTTP POST `/api/v1/query/stream` → `StreamingResponse` with `text/event-stream` media type
2. Calls `QueryPipeline.stream()` — same retrieval path as `run()` but `Generator.stream_generate()` yields tokens
3. Each token yielded as `data: {token}\n\n`; ends with `data: [DONE]\n\n`
4. Memory and events saved after stream completes

**State Management:**
- Session memory stored in `MemoryService` (Redis-backed short-term, persistent long-term facts)
- Query results cached in Redis with key `rag:query:{hash(query+filters+tenant)}`
- Rate limit counters in Redis (Sorted Set sliding window); fallback to in-process dict

## Key Abstractions

**`IngestionRequest` / `GenerationRequest` / `GenerationResponse`:**
- Purpose: Typed DTOs for pipeline I/O
- Location: `utils/models.py`
- Pattern: Pydantic v2 models with `model_dump()` serialization

**Pipeline Singletons:**
- Purpose: Single shared instance per process for each pipeline
- Location: `services/pipeline.py` (`get_ingest_pipeline()`, `get_query_pipeline()`, `get_agent_pipeline()`)
- Pattern: Module-level `_pipeline = None` with lazy init on first call

**Service Singletons:**
- Purpose: Stateful service instances (embedder, vector store, LLM client, etc.)
- Pattern: Each service module exposes a `get_<service_name>()` function with module-level `_instance = None`

**`APIResponse` envelope:**
- Purpose: Consistent HTTP response wrapper
- Location: `utils/models.py`
- Pattern: `{"success": bool, "data": Any, "trace_id": str, "error": str | None}`

## Entry Points

**HTTP API:**
- Location: `main.py` (FastAPI `app`) + `controllers/api.py` (`router`)
- Triggers: Uvicorn HTTP server
- Responsibilities: Route all `/api/v1/*` requests to pipelines

**Batch Ingestion Script:**
- Location: `scripts/ingest_batch.py`
- Triggers: CLI invocation
- Responsibilities: Bulk-ingest documents from `data_dir` at startup or on demand

**Startup Auto-scan:**
- Location: `main.py` `lifespan()` — `asyncio.create_task(knowledge_service.scan_and_update(...))`
- Triggers: App startup if `auto_update_on_startup=True`

**MCP Server:**
- Location: `services/mcp_server.py`
- Triggers: External MCP client connection
- Responsibilities: Expose RAG tools to Claude agent via Model Context Protocol

## Error Handling

**Strategy:** Fail-fast with audit trail; non-fatal failures for optional enrichment steps

**Patterns:**
- Pipeline stages that fail extraction or produce no chunks return `IngestionResponse(success=False, error=...)` — never raise
- Optional features (PII detection, summary indexing, version recording, observability) wrapped in `try/except` with `logger.warning()` — non-fatal
- Controllers catch pipeline exceptions and raise `HTTPException(500)` with sanitized message
- Global `@app.exception_handler(Exception)` in `main.py` catches any unhandled exception, returns `{"success": false, "trace_id": ...}` without leaking stack trace
- Redis rate limiter is fail-open: if Redis is unavailable, request is allowed through

## Cross-Cutting Concerns

**Tracing:** Every HTTP request gets a `trace_id` (UUID[:8]) injected via `trace_middleware`; propagated in response headers (`X-Trace-ID`) and all log lines

**Metrics:** Prometheus counters/histograms exposed at `/metrics` via `utils/metrics.py`; covers HTTP requests, query latency, faithfulness scores, cache hits, PII detections, rule triggers, auth attempts

**Logging:** `loguru` via `utils/logger.py`; structured with trace_id on every pipeline log line

**Authentication:** Optional Bearer token middleware in `main.py`; sets `request.state.user`; routes can check for `None` to enforce auth. Supports OIDC (via `services/auth/oidc_auth.py`) and local JWT

**Observability:** Langfuse LLM tracing + OpenTelemetry spans via `utils/observability.py`; initialized in `lifespan()`, flushed on shutdown

**Caching:** Redis-backed with `utils/cache.py`; `cache_get`/`cache_set`/`cache_invalidate` helpers; TTL and namespace-prefixed keys (`rag:query:*`)

---

## Sources

- `main.py`
- `controllers/api.py`
- `services/pipeline.py`
- `config/settings.py`
- `services/retriever/retriever.py` (partial)
