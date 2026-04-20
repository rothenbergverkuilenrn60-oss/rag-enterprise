# Codebase Concerns

**Analysis Date:** 2026-04-20

## Summary

The RAG Enterprise codebase is architecturally comprehensive but has several incomplete implementations, a critical default-secret-key security risk, a missing rate-limiter enforcement layer in the API controller, and near-zero unit test coverage for the majority of services. The evaluation framework exists but runs against a tiny synthetic dataset (10 QA pairs), limiting its signal value for production readiness.

---

## Critical Issues

### Default JWT Secret Key Shipped in Code

- Risk: `settings.secret_key` defaults to the literal string `"CHANGE-ME-IN-PRODUCTION-USE-256BIT-KEY"` in `config/settings.py` line 76–79. A validator raises only in `ENVIRONMENT=production`; non-production deployments (staging, dev containers) silently use the weak key.
- Files: `config/settings.py:76-79`, `services/auth/oidc_auth.py:99-101`
- Impact: Any JWT signed with this key can be forged by anyone who reads the source code.
- Fix: Fail at startup if `secret_key` matches the default string in ALL environments, not just production.

### Rate Limiter Configured but Not Wired to API Controller

- Risk: `rate_limit_rpm`, `rate_limit_burst`, and `rate_limit_redis` are defined in `config/settings.py`, and middleware logic exists in `main.py`. However, the `controllers/api.py` router applies no per-endpoint rate-limit decorator. The middleware in `main.py` gates on a Redis key check but the controller itself has no fallback.
- Files: `main.py:218-272`, `controllers/api.py` (entire file)
- Impact: If `main.py` middleware is bypassed or Redis is unavailable, all endpoints are unprotected.
- Fix: Add explicit rate-limit decorators on `/ingest`, `/query`, and `/generate` endpoints; ensure `rate_limit_redis=False` path uses a robust in-process token bucket.

### `Rule.check()` is an Unimplemented Abstract Method

- Risk: `services/rules/rules_engine.py:41` defines `Rule.check()` with `raise NotImplementedError`. The `PromptInjectionRule` subclass overrides it, but custom rules added at runtime that omit `check()` will crash in production with an unhandled exception.
- Files: `services/rules/rules_engine.py:40-41`
- Fix: Convert `Rule` to an `ABC` with `@abstractmethod` so missing implementations fail at class-definition time, not at request time.

---

## Technical Debt

### Broad `except Exception` Swallowing Throughout

- Pattern: Nearly every service and utility catches `except Exception as exc` or bare `except Exception:` and logs/continues. Counted across: `controllers/api.py`, `services/extractor/extractor.py` (5 sites), `services/doc_processor/chunker.py` (3 sites), `services/retriever/retriever.py` (6 sites), `eval/ragas_runner.py` (5 sites), `utils/observability.py` (4 sites), `services/knowledge/version_service.py` (4 sites), `services/auth/oidc_auth.py`.
- Impact: Errors are silently absorbed as log entries; upstream callers cannot distinguish transient failures from permanent ones, making circuit-breaking and retry logic unreliable.
- Fix: Define typed exception hierarchy (`RAGError`, `ExtractionError`, `RetrievalError`, etc.) and catch narrowly. Reserve broad catches only at the top-level request handler.

### Single Global Singleton Pattern for All Services

- Pattern: Every service module exposes a `get_<service>()` function that initialises a module-level global and returns it. Examples: `get_retriever()`, `get_generator()`, `get_event_bus()`, `get_vectorizer()`.
- Files: `services/pipeline.py`, `services/retriever/retriever.py`, `services/generator/generator.py`, `services/events/event_bus.py`
- Impact: No lifecycle management; singletons are never closed or reset between tests, making test isolation fragile. Concurrent re-initialisation is not thread-safe.
- Fix: Use FastAPI's `lifespan` dependency injection or a DI container; pass services as constructor arguments in tests.

### `uvicorn_workers` Defaults to 1

- Issue: `config/settings.py:56` defaults `uvicorn_workers=1` with a comment saying production should use `CPU*2+1`. This default will silently deploy single-worker in production if the env var is not explicitly set.
- Files: `config/settings.py:56`
- Fix: Document or enforce a validator that warns when `environment=production` and `uvicorn_workers < 2`.

### WSL2 Path Hard-Coded in Default Model Dir

- Issue: `config/settings.py:16` sets `MODEL_DIR` default to `/mnt/f/my_models`, a WSL2-specific path. In Docker, CI, or Linux bare-metal deployments this path does not exist; the service silently uses a non-existent model directory.
- Files: `config/settings.py:16`
- Fix: Default to a path relative to `BASE_DIR` (e.g. `BASE_DIR / "models"`), configurable via `APP_MODEL_DIR`.

---

## Missing Features / Gaps

### Image Extraction Not Implemented

- What's missing: `config/settings.py:111` defines `extractor_image_extract: bool = False` with the comment "暂未实现，留作扩展" (not yet implemented, reserved for extension). The extractor service has no image-extraction code path.
- Files: `config/settings.py:111`, `services/extractor/extractor.py`
- Impact: PDFs with embedded images (diagrams, charts) yield no extracted content.

### No Unit Tests for Most Services

- What's missing: Only 4 unit test files exist: `test_chunker.py`, `test_generator_mock.py`, `test_preprocessor.py`, `test_retriever.py`. No unit tests cover: `services/auth/`, `services/audit/`, `services/rules/`, `services/memory/`, `services/events/`, `services/nlu/`, `services/knowledge/`, `services/tenant/`, `services/ab_test/`, `services/annotation/`, `services/feedback/`, `services/vectorizer/`.
- Files: `tests/unit/` (4 files total)
- Risk: Regressions in auth, rules engine, memory, and tenant isolation go undetected.
- Priority: High

### Evaluation Dataset is Minimal (10 QA Pairs)

- What's missing: `eval/datasets/qa_pairs.json` contains only 10 synthetic QA pairs. The RAGAS runner in `eval/ragas_runner.py` evaluates faithfulness, context precision, and answer relevance against this tiny set.
- Files: `eval/datasets/qa_pairs.json`, `eval/ragas_runner.py`
- Impact: Evaluation scores have no statistical significance; a 10% RAGAS score change may be noise, not signal.
- Fix: Expand to at least 200 domain-representative QA pairs before treating eval output as a quality gate.

### No CI/CD Pipeline Configuration

- What's missing: `.github/` directory exists in git status as untracked but has no confirmed workflow files visible. The `Makefile` `test` target uses `conda run -n torch_env` which requires a local Conda environment — not reproducible in GitHub Actions without additional setup.
- Files: `Makefile:80`, `.github/` (contents unknown)
- Impact: No automated testing on pull requests.

### Kafka Integration is Disabled by Default with No Migration Path

- What's missing: `kafka_bootstrap_servers: str = ""` disables Kafka; the event bus falls back to in-memory. There is no documented migration path from in-memory to Kafka for production.
- Files: `config/settings.py:279`, `services/events/event_bus.py`
- Impact: Events emitted in single-node dev mode are not persisted; switching to Kafka in production will lose historical events.

### Async Background Ingest Has No Status Tracking

- What's missing: `POST /ingest/async` (`controllers/api.py:92-100`) enqueues a background task via FastAPI's `BackgroundTasks` but returns no task ID. There is no endpoint to poll task status or retrieve errors from background ingestion.
- Files: `controllers/api.py:92-100`
- Impact: Callers cannot determine if async ingestion succeeded or failed.

---

## Security Concerns

### CORS Allows Localhost Origins in Default Config

- Risk: `cors_origins` defaults to `["http://localhost:3000", "http://localhost:8080"]` in `config/settings.py:51`. If this value is not overridden in production, any page served on those localhost ports (e.g. a compromised developer machine) could make credentialed requests.
- Files: `config/settings.py:51`
- Recommendation: Default to `[]` (deny all); require explicit configuration.

### OIDC JWKS Fetched Without Certificate Pinning

- Risk: `services/auth/oidc_auth.py:173` fetches JWKS over HTTPS using `httpx.AsyncClient` with no additional TLS verification beyond the default CA bundle. A compromised CA or misconfigured system could allow MITM attacks on JWKS fetch.
- Files: `services/auth/oidc_auth.py:162-183`
- Current mitigation: Default HTTPS CA verification via httpx.
- Recommendation: Consider certificate pinning or at minimum log the JWKS URI being fetched for auditability.

### Auth is Optional (OIDC Disabled by Default)

- Risk: `oidc_enabled: bool = False` means the API runs with no external identity provider by default. Local JWT tokens can be created by any caller who knows the `secret_key` (which defaults to a known string — see Critical Issues).
- Files: `config/settings.py:336`, `services/auth/oidc_auth.py:73-74`
- Recommendation: Require explicit opt-in config to disable auth; warn loudly at startup when running with local JWT and default secret key.

### PII Detector in Non-Blocking Mode by Default

- Risk: `pii_block_on_detect: bool = False` means PII detected in ingested documents is redacted but ingestion proceeds. Depending on compliance requirements (GDPR, HIPAA), this may not be sufficient.
- Files: `config/settings.py:294`
- Recommendation: Document this setting prominently; provide a compliance-mode preset.

---

## Performance Risks

### Reranker Model Loaded Per Worker

- Problem: The reranker cross-encoder (`reranker_model_path`) is loaded as a module-level singleton. With `uvicorn_workers > 1`, each worker process loads the full model into memory independently.
- Files: `config/settings.py:217`, `services/retriever/retriever.py`
- Impact: With a 14B-parameter BGE-M3-rerank model, 4 workers could consume 4x the VRAM/RAM.
- Improvement: Use the `reranker_service_url` microservice path (`services/reranker_service/app.py`) to share one model instance across workers.

### HyDE + Multi-Query Doubles/Triples LLM Calls Per Request

- Problem: When `hyde_enabled=True` and `query_rewrite_enabled=True` (both default), each user query triggers 1 HyDE call + 3 multi-query rewrite calls before retrieval — 4 LLM round-trips minimum.
- Files: `config/settings.py:207-213`, `services/retriever/retriever.py`
- Impact: Latency multiplier of 4x on the retrieval stage; adds significant cost when using OpenAI API.
- Improvement: Document the latency/cost trade-off clearly; consider a `fast_mode` preset that disables HyDE and multi-query.

### `request_timeout_sec: 120` with Streaming Enabled

- Problem: `llm_stream: bool = True` enables streaming, but `request_timeout_sec=120` applies globally. Long-running streams close at 120 s regardless of whether data is still flowing.
- Files: `config/settings.py:55, 243`
- Impact: Large document generation queries may time out mid-stream.

---

## Dependencies at Risk

### `milvus` Listed as Vector Store Option but No Client in Requirements

- Risk: `vector_store: Literal["qdrant", "milvus", "pgvector", "chroma"]` includes `milvus`, but `requirements.txt` does not list `pymilvus`. Selecting `milvus` will fail at runtime with an import error.
- Files: `config/settings.py:191`, `requirements.txt`
- Fix: Either add `pymilvus` to requirements with an optional extras marker, or remove `milvus` from the Literal until it is implemented.

### `extractor_image_extract` Config with No Implementation

- Risk: Setting `extractor_image_extract=True` will have no effect — the code path is not implemented. No warning is emitted.
- Files: `config/settings.py:111`
- Fix: Add a startup warning if `extractor_image_extract=True` is set.

---

## Test Coverage Gaps

### No Tests for Auth Service

- What's not tested: Token verification, OIDC flow, JWKS caching, role extraction, permission checks.
- Files: `services/auth/oidc_auth.py`
- Risk: Auth regressions (e.g., expiry bypass, role mapping errors) ship silently.
- Priority: High

### No Tests for Rules Engine

- What's not tested: `PromptInjectionRule` pattern matching, `RuleAction` routing, custom rule registration.
- Files: `services/rules/rules_engine.py`
- Risk: Prompt injection patterns may fail to match new attack variants without detection.
- Priority: High

### No Tests for Multi-Tenant Isolation

- What's not tested: Tenant-scoped retrieval, cross-tenant data leakage, tenant config override.
- Files: `services/tenant/tenant_service.py`
- Risk: A misconfigured tenant filter could expose another tenant's documents.
- Priority: High

### Integration Tests Require Live External Services

- What's not tested in isolation: `tests/integration/test_pipeline.py` and `test_ragas_eval.py` require running Qdrant, Redis, and an LLM endpoint. No mocking layer exists; tests will silently skip or fail if services are absent.
- Files: `tests/integration/test_pipeline.py`, `tests/integration/test_ragas_eval.py`
- Fix: Add `pytest.mark.integration` skip markers and document required service prerequisites.

---

## Sources

Files examined:
- `config/settings.py`
- `controllers/api.py`
- `main.py` (rate limiter, middleware)
- `services/auth/oidc_auth.py`
- `services/rules/rules_engine.py`
- `services/pipeline.py`
- `services/extractor/extractor.py` (grep)
- `services/retriever/retriever.py` (grep)
- `services/doc_processor/chunker.py` (grep)
- `services/events/event_bus.py` (grep)
- `services/knowledge/version_service.py` (grep)
- `utils/observability.py` (grep)
- `eval/ragas_runner.py` (grep)
- `eval/datasets/qa_pairs.json` (existence)
- `k8s/rag-api/deployment.yaml`
- `Makefile`
- `tests/unit/` (file listing)
- `tests/integration/` (file listing)
- `requirements.txt` (grep for milvus)
