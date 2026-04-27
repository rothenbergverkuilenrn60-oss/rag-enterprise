# Phase 3: Error Handling Sweep - Context

**Gathered:** 2026-04-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace all broad `except Exception` catches with specific exception types (ERR-01) and attach `done_callback` to every `asyncio.create_task()` call (ERR-02). No new features — purely a hardening sweep across existing service and utility code.

</domain>

<decisions>
## Implementation Decisions

### Exception Specificity (ERR-01)

- **D-01:** asyncpg DB call sites → catch `asyncpg.PostgresError` (covers connection, query, and constraint errors without swallowing non-DB exceptions).
- **D-02:** External service call sites (Redis, OpenAI, HTTP clients) → catch the library's own base exception class: `redis.RedisError`, `openai.APIError`, `httpx.HTTPError`, `python_jose.JWTError`, etc. Do not fall back to `OSError` or `Exception`.
- **D-03:** All other `except Exception` sites must be narrowed to the most specific type that makes sense for that call site. No site may remain as bare `except Exception` after this phase.

### Swallowed Error Policy (ERR-01)

- **D-04:** Startup/warmup failures (`VectorStore.ensure_collection`, `EventBus.start`, observability init, auto-scan scheduling in `main.py`) → keep `log+continue` pattern. These are genuinely non-fatal; app runs in degraded mode. Log at `logger.warning` level.
- **D-05:** In-request pipeline errors (retriever, NLU, memory service calls inside `IngestionPipeline` and `QueryPipeline`) → catch specific exception, log with `logger.error`, and return a structured error response (`IngestionResponse(success=False, error=...)` or `QueryResponse(success=False, error=...)`). Do not re-raise into the global handler.
- **D-06:** Shutdown flush errors (`audit.flush()`, `EventBus.stop()`, `obs_flush()` in lifespan shutdown) → keep `except Exception: pass` with no change — failures here cannot propagate meaningfully.

### create_task Callback Pattern (ERR-02)

- **D-07:** All three `asyncio.create_task()` call sites (`main.py:90`, `event_bus.py:130`, `event_bus.py:168`) must call `.add_done_callback(_log_task_error)` immediately after task creation.
- **D-08:** `_log_task_error` is a shared module-level helper — not duplicated inline. It checks `task.exception()` and logs at `logger.error` with the exception info. It does **not** re-raise.
- **D-09:** Helper location: `utils/tasks.py` (new file). Import path: `from utils.tasks import log_task_error` (public name, no underscore prefix, for external import clarity).

### Audit Log Routing

- **D-10:** Audit trail (`audit.log_ingest` / `audit.log_query`) is reserved for **business security events**: PII blocks, auth/authorization failures, tenant isolation violations, explicit document rejects. These go to audit AND `logger.warning/error`.
- **D-11:** Infrastructure errors (DB down, Redis timeout, model load failure, warmup fail) go to `logger.error` only — never to audit. Flooding the compliance trail with infrastructure noise is explicitly rejected.

### Claude's Discretion

- Exact exception type mappings for less common libraries (langdetect, sentence-transformers, pymupdf) — choose the most specific available type or `ValueError`/`RuntimeError` as appropriate.
- Whether to add a helper `_handle_pipeline_error(logger, exc, context)` to DRY up the structured-error pattern, or repeat the pattern inline per call site.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements
- `.planning/REQUIREMENTS.md` — ERR-01 and ERR-02 acceptance criteria
- `.planning/ROADMAP.md` — Phase 3 goal and scope boundary

### Key Source Files (50+ `except Exception` sites)
- `services/pipeline.py` — IngestionPipeline and QueryPipeline stage error handling
- `services/retriever/retriever.py` — retrieval call sites
- `services/auth/oidc_auth.py` — JWT verification error sites
- `services/knowledge/knowledge_service.py` — knowledge scanner errors
- `services/knowledge/summary_indexer.py` — summary indexer errors
- `services/knowledge/version_service.py` — version service errors
- `services/nlu/nlu_service.py` — NLU service errors
- `services/memory/memory_service.py` — memory service errors
- `services/annotation/annotation_service.py` — annotation service errors
- `services/vectorizer/indexer.py` — indexer errors
- `services/mcp_server.py` — MCP server errors
- `controllers/api.py` — route-level error handling
- `main.py` — lifespan startup/shutdown handlers

### create_task Sites (ERR-02)
- `main.py:90` — auto knowledge scan task
- `services/events/event_bus.py:130` — event dispatch task
- `services/events/event_bus.py:168` — event dispatch task

### New File to Create
- `utils/tasks.py` — shared `log_task_error` callback helper

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `utils/logger.py` — logger setup; `log_task_error` should import from this module's logger
- `services/audit/audit_service.py` — `AuditResult.BLOCKED` enum and `audit.log_ingest` signature already defined; use as-is
- `IngestionResponse`, `QueryResponse` in `services/pipeline.py` — structured error return types already exist

### Established Patterns
- Startup non-fatal pattern in `main.py` is already consistent (`try/except Exception as exc: logger.warning(f"... (non-fatal): {exc}")`). ERR-01 only needs to narrow the exception type here, not restructure.
- Pipeline stage returns already use `IngestionResponse(success=False, error=...)` pattern for PII blocks — extend this pattern to exception catch sites.

### Integration Points
- `utils/tasks.py` is a new file; no existing `utils/` file handles task lifecycle. Keep it minimal — one public function.
- `event_bus.py` imports from `utils/` already (logger) — adding `utils.tasks` import is consistent.

</code_context>

<specifics>
## Specific Ideas

- No external references cited during discussion.
- User confirmed default/recommended choices at every decision point — no unusual constraints.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-error-handling-sweep*
*Context gathered: 2026-04-22*
