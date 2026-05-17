# Phase 27: Test Isolation + Memory Reliability - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Make per-test isolation cheap (kill ~20 module-level service singletons via a `create_app()` factory + roll out a Redis-mock fixture) AND make memory writes deduplicated + batched (cosine precheck near-duplicate guard + 1-RTT batch `save_facts`).

**In scope:** TD-02 + TD-04 + TD-05 + TD-06.
**Out of scope:** every other v1.7 requirement (TD-01 + TD-03 + TD-07 shipped in Phase 26; DOC-01 lands in Phase 28). No DI refactor (FastAPI `Depends()` rewrite is out — too big for v1.7). No migration of the 8 existing tests that do `from main import app` (they coexist with `create_app()`).

</domain>

<decisions>
## Implementation Decisions

### Theme 1 — TD-02 `create_app()` factory + singleton reset (brute-force strategy)

- **D-01:** New module `tests/factories/app.py` exports `create_app() -> FastAPI`. Each call (a) resets a curated list of ~20 module-level singletons to None and (b) constructs a fresh FastAPI instance via the existing `main.lifespan` factory. Returned app is independent of any other `create_app()` invocation in the test suite.
- **D-02:** Singleton inventory (curated list — verify exact set during planning by grepping `^_[a-z_]*_instance: \|^_[a-z_]* | None = None` under `services/`):
  - `services.nlu.nlu_service::_nlu_service`
  - `services.nlu.filter_extractor::_filter_extractor`
  - `services.nlu.entity_disambiguator::_disambiguator` + `_entity_lookup`
  - `services.retriever.retriever::_retriever`
  - `services.feedback.feedback_service::_feedback_service`
  - `services.auth.oidc_auth::_auth_service`
  - `services.agent.executor::_executor_instance`
  - `services.agent.tools.registry::_registry`
  - `services.agent.tools.web_search::_tavily_client`
  - `services.agent.extractor::_extractor`
  - `services.agent.planner::_planner_instance`
  - `services.memory.memory_service::_memory_service`
  - `services.annotation.annotation_service::_annotation_service`
  - `services.vectorizer.indexer::_vectorizer`
  - `services.audit.audit_service::_audit_service`
  - (extend during planning if grep finds more)
- **D-03:** **Lint test** at `tests/unit/test_singleton_inventory_complete.py` enumerates module-level singletons via grep + AST scan; fails CI if any `_X_instance` pattern under `services/` is NOT in the factory's curated list. Prevents the list going stale silently.
- **D-04:** `create_app()` accepts optional overrides keyword `dependency_overrides: dict[Callable, Callable] | None = None` forwarded to `app.dependency_overrides`. Tests can stub specific services without touching the singleton reset.
- **D-05:** **No forced migration** for the 8 existing `from main import app` tests (`test_pipeline.py`, `test_memory_forget_e2e.py`, `test_ui_static.py`, `test_agent_stream_route.py`, `test_memory_controller.py`, `test_rate_limiting.py`, `test_ingest_status.py`, `test_static_ui.py`). They coexist with the new factory. New tests opt in to `create_app()` for isolation.

### Theme 2 — TD-04 near-duplicate guard

- **D-06:** Precheck scope: **per-(user_id, tenant_id)**. SQL: `SELECT 1 FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2 AND embedding <=> $3::vector < $threshold LIMIT 1`. Matches v1.6 `get_relevant_facts` tenant-isolation contract; preserves RLS semantics.
- **D-07:** Threshold is a new Pydantic V2 settings field: `memory_near_duplicate_threshold: float = Field(default=0.05, ge=0.0, le=1.0)`. Tunable per-deploy without code change.
- **D-08:** Audit channel: extend `services.audit.audit_service.AuditAction` enum with `MEMORY_NEAR_DUPLICATE_SKIPPED = "MEMORY_NEAR_DUPLICATE_SKIPPED"` (appended AFTER `MEMORY_EVICT`, matching v1.6 Phase 25 EVICT-02 append-only pattern). One `audit_log` row per skip via `AuditService.log(...)` containing actor (user_id + tenant_id), the skipped fact content (truncated to 200 chars per existing Phase 25 RULE_BLOCKED convention), and the nearest-match similarity score (in `detail` JSONB).
- **D-09:** Audit-mode-before-enforce discipline per v1.6 EVICT-02: **v1.7 emits the audit row but DOES NOT SKIP THE SAVE.** Save still happens — duplicate row inserted. v1.8 promotion to silent-skip is a separate todo. This is the "metric only first, enforcement later" contract that allows ops to see the rate before flipping behavior.
- **D-10:** Precheck runs on EVERY save_fact call (not sampled). One PG round-trip added per save. Negligible (~1-2ms on local pgvector). TD-05 batch path collapses N round-trips to 1 for the dedupe query anyway.

### Theme 3 — TD-05 `save_facts` batch path

- **D-11:** Canonical API: `LongTermMemory.save_facts(facts: list[ExtractedFact]) -> SaveFactsResult`. Returns `SaveFactsResult(saved_count: int, skipped_near_duplicates: int, skipped_embed_failures: int)`.
- **D-12:** `save_fact` (singular) becomes a thin wrapper: `await self.save_facts([fact])`. Existing callers unchanged. Single code path for dedupe + audit + embed + insert; future tweaks land in one place.
- **D-13:** Batch dedupe via **bulk SQL precheck** (1 RTT regardless of batch size). Pattern:
  ```sql
  SELECT idx FROM unnest($1::vector[]) WITH ORDINALITY AS t(vec, idx)
  WHERE EXISTS (
      SELECT 1 FROM long_term_facts
      WHERE user_id = $2 AND tenant_id = $3
      AND embedding <=> t.vec < $4
  )
  ```
  Returns list of 1-based indices that ARE duplicates. Caller skips those (audit log each), then `executemany` inserts the rest.
- **D-14:** Embed step uses `embedder.embed_batch([content_1, ..., content_N])` (already exists in `services/vectorizer/embedder.py`). 1 call for the whole batch.
- **D-15:** Total RTT shape per ExtractorAgent turn with N facts:
  - 1× embed_batch (LLM provider RTT)
  - 1× PG bulk dedupe query
  - 1× PG executemany insert
  - K× audit_log entries (where K = number of duplicates; usually 0)
  - Old shape: N× (embed + precheck + insert) = 3N RTT
  - New shape: ≤ 3 + K RTT
- **D-16:** Partial-failure semantics: **best-effort**. Per-fact embed failures get caught (`embedder.embed_batch` returns per-input result; failed inputs come back as None), dropped from the insert batch with a `logger.warning(...)`. Saved-count + skipped-embed-count returned in `SaveFactsResult`. Matches Phase 23 D-05 extractor adversarial-fixture tolerance.
- **D-17:** ExtractorAgent migration: inline edit at `services/agent/extractor.py:260`. Replace the for-loop (`for f in facts: await mem._long.save_fact(...)`) with a single `await mem._long.save_facts(facts)` call. Exception envelope around the call unchanged. Before/after benchmark recorded in Plan 27-0?-SUMMARY for SC-5 latency check.

### Theme 4 — TD-06 Redis-mock fixture rollout

- **D-18:** Fixture lives in `tests/conftest.py` (alongside `pg_pool`). Function-scoped, marker-opt-in via custom marker `@pytest.mark.uses_redis`. Fixture activates conditionally only when the marker is present on the test (or via `pytest_collection_modifyitems` hook that auto-applies when the marker is found).
- **D-19:** Mock target: **`utils.cache.get_redis`** (single canonical accessor). Every service that uses Redis lazy-imports through this function: `services/nlu/entity_disambiguator`, `services/annotation`, `services/ab_test`, `services/pipeline`, `services/ingest_worker`, `services/knowledge/version_service`, `services/memory/memory_service::ShortTermMemory`. **Plan-time audit required**: confirm no service imports `redis.asyncio` directly and bypasses `get_redis()`. If any do, add them to a v1.8+ todo (out of scope to refactor existing direct imports in this phase).
- **D-20:** Mock implementation: `MagicMock(spec=redis.asyncio.Redis)` with `AsyncMock` for `get`, `set`, `delete`, `expire`, `pipeline`, `eval`. Returns sensible defaults (e.g., `get` → None unless test overrides). Per-test in-memory dict-backed for tests that need state across get/set within a single test function.
- **D-21:** Integration tests bypass the mock automatically — they don't add `@pytest.mark.uses_redis`. Real Redis (if running on `localhost:6379` or per `settings.redis_url`) used as today.
- **D-22:** **Caveat acknowledged:** The "32 unit-test failures" Phase 26 PR #9 surfaced are `openai SDK signature drift` (`APIError.__init__() missing 'request' arg`), NOT Redis-dependent. TD-06 may close a SEPARATE set of 32 Redis-baseline failures mentioned in v1.6 Phase 24 SUMMARY, OR may close zero of the PR #9 failures. Plan 27-0?-Task 1 includes a diagnostic step: run the failing unit suite WITHOUT the Redis-mock fixture, then WITH it, to measure actual TD-06 impact on the 32 PR #9 failures. The openai SDK drift remediation stays as v1.8+ todo regardless.

### Claude's Discretion

- Exact list of services in the TD-02 singleton inventory — verify at plan-time via fresh grep; current list above is from a 2026-05-17 scan.
- Whether to ship the TD-04 audit_log dashboard alert as part of Phase 27 or as a v1.8 ops todo (default: defer — Phase 27 ships the metric; alerting is ops territory).
- Whether `SaveFactsResult` is a Pydantic model, a dataclass, or a NamedTuple (default: dataclass for symmetry with `ExtractedFact`).
- Exact wording of the AuditAction enum value (proposed: `MEMORY_NEAR_DUPLICATE_SKIPPED`). Bikeshed-free if user doesn't push back.
- Whether the `pytest_collection_modifyitems` hook auto-applies the redis_mock fixture to marked tests OR tests explicitly request it via fixture parameter. Default: auto-apply via hook for ergonomics; explicit param is fallback if hook conflicts with existing pytest infra.
- Whether to extend Plan 26-04 P1 fix (try/except wrapping `_create_tables` with pool reset) to `LongTermMemory._get_pool` opportunistically during TD-04/TD-05 work, since those touch `LongTermMemory` heavily. Default: yes if zero-risk (just add the same try/except shape); track as bonus delivery in plan summary.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope + requirements
- `.planning/REQUIREMENTS.md` §"Test Isolation" (TD-02, TD-06) + §"Memory Service Reliability" (TD-04, TD-05)
- `.planning/ROADMAP.md` §"Phase 27: Test Isolation + Memory Reliability" — 5 success criteria
- `.planning/PROJECT.md` §"Current Milestone: v1.7"

### Phase 26 carry-forward (PRECEDENT — DO NOT renegotiate)
- `.planning/phases/26-memory-infra-hygiene/26-CONTEXT.md` — Theme 2 (AuditService pool migration), Theme 3 (DDL conventions), Theme 4 (lifespan close())
- `.planning/phases/26-memory-infra-hygiene/26-VERIFICATION.md` — Phase 26 closed TD-01 + TD-03 + TD-07; new artifacts (utils/asyncpg_helper.py, resolve_embedding_model_path, AuditService.close(), MemoryService.close()) are LIVE in services/

### Reference implementations to mirror
- `services/memory/memory_service.py:290` — `LongTermMemory.get_relevant_facts` — cosine `<=>` query pattern; mirror for TD-04 precheck (per-(user,tenant) filter + iterative_scan + ef_search)
- `services/memory/memory_service.py:359` — `LongTermMemory.save_fact` — current singular API; TD-05 wraps this via batch
- `services/agent/extractor.py:260` — ExtractorAgent save_fact call site; TD-05 inline-migration target
- `services/audit/audit_service.py:25-40` — `AuditAction` enum (append-only convention from v1.6 Phase 25)
- `services/vectorizer/embedder.py` — `embed_batch` already exists (TD-05 D-14)
- `utils/cache.py::get_redis` — single canonical Redis accessor (TD-06 D-19)
- `tests/conftest.py::pg_pool` — function-scope fixture pattern; TD-06 `redis_mock` mirrors location + scope

### Carry-forward decisions (still in force from earlier phases)
- INSERT-ONLY `audit_log` invariant — v1.0 Phase 2 (TD-04 adds rows; REVOKE UPDATE/DELETE still binding)
- Audit-mode-before-enforce — v1.6 Phase 25 EVICT-02 (TD-04 D-09: v1.7 metric-only; v1.8 silent-skip promotion)
- Audit-write failure must NOT block — v1.6 GDPR T1 (TD-04 audit log write is best-effort; save still succeeds)
- Mock at consumer path, not source — v1.3 Phase 13 (TD-06 mock target is `services.X.get_redis` import path)
- pgvector `hnsw.iterative_scan = strict_order` + raised `ef_search` when filter active — v1.1 Phase 8 / v1.6 Phase 24 (TD-04 dedupe query inherits)
- diff-cover ≥ 80% on touched files — v1.1 Phase 10 (Phase 27 PRs subject to gate)

### Project standards
- `CLAUDE.md` — Pydantic V2, mypy --strict on new modules, ruff, no bare except, no blocking I/O in async, adapter pattern, structured logging.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LongTermMemory._get_pool` + `_create_tables` lazy-init pattern (v1.6 — also got P1 partial-init reset in `AuditService._get_pool` Plan 26-04; opportunistic backport candidate noted in Claude's Discretion)
- `LongTermMemory.get_relevant_facts` cosine SQL (v1.6 Phase 24) — pattern for TD-04 precheck
- `AuditService` (post-Phase-26): pool-backed, lazy `_create_tables`, audit-mode-friendly `log()` method — TD-04 consumes for MEMORY_NEAR_DUPLICATE_SKIPPED events
- `utils.cache.get_redis` (single accessor used by ~7 services) — TD-06 single mock target
- `pg_pool` function-scope async fixture — TD-06 `redis_mock` mirrors shape
- `services/vectorizer/embedder.py::embed_batch` (already exists per v1.6 baseline) — TD-05 D-14 consumer

### Established Patterns
- Module-level singleton + lazy `get_X_service()` factory across ~20 services
- Tests mock at consumer path (`monkeypatch.setattr("services.X.dep", ...)`)
- `AuditEvent(action=AuditAction.X, detail={...}, ...)` for audit_log rows; truncate user-data fields to 200 chars (RULE_BLOCKED convention)
- Pydantic V2 `Field(ge=, le=)` validators for setting bounds (e.g., `memory_facts_cap_per_user: int = Field(default=500, ge=1)`)

### Integration Points
- `services/agent/extractor.py:260` — sole save_fact callsite; TD-05 inline migration
- `services/audit/audit_service.py::AuditAction` enum — TD-04 append target (after `MEMORY_EVICT`)
- `config/settings.py` — TD-04 adds `memory_near_duplicate_threshold` field; place alongside `memory_facts_cap_per_user` (Phase 25 EVICT-01) for memory-section locality
- `tests/conftest.py` — TD-06 adds `redis_mock` fixture + `pytest_collection_modifyitems` hook (or `pytest_configure` for marker registration)
- `main.py::lifespan` — TD-02 `create_app()` reuses this lifespan handler verbatim (no main.py touches required)

</code_context>

<specifics>
## Specific Ideas

- `SaveFactsResult` dataclass returned by `save_facts` carries 3 counters so callers can observe dedupe rate without log-scraping.
- `pytest.mark.uses_redis` registered in `tests/conftest.py` via `pytest_configure(config)` hook with the marker description "test exercises Redis path; redis_mock fixture auto-applied".
- TD-02 brute-force factory adds at most ~50 LOC: list of 20 `(module, attr)` pairs + a `_reset_singletons()` helper + a `create_app() -> FastAPI` wrapper.
- TD-04 dedupe precheck reuses the same `hnsw.iterative_scan = strict_order` + raised `ef_search` GUC discipline as `get_relevant_facts` (per CONTEXT carry-forward — v1.1 Phase 8 / v1.6 Phase 24).
- The "32 failures" caveat (D-22) is important for setting Phase 27 success criteria: VERIFICATION.md SC for TD-06 should be "redis-dependent baseline failures go to 0" — measured by running tests/unit/ with and without the fixture. NOT "the 32 PR #9 failures go to 0" because those are openai SDK, separate problem.

</specifics>

<deferred>
## Deferred Ideas

- **TD-02 full DI refactor** — converting all 20 singletons to FastAPI `Depends()` is a v1.8+ candidate (≥3-5 days, touches every controller + service).
- **TD-04 silent-skip promotion** — flip behavior from "metric-only" to "actually skip the save" in v1.8. v1.7 ships audit-mode-only per audit-mode-before-enforce discipline.
- **TD-04 audit-log alerting dashboard** — ops-side; not Phase 27 scope.
- **openai SDK signature drift cleanup** (the 32 PR #9 unit failures) — separate v1.8+ todo already in STATE.md. TD-06 may or may not overlap; D-22 diagnostic during Plan 27-0? execution will measure.
- **TD-06 direct-redis-import audit + refactor** — if Plan-time audit finds services that import `redis.asyncio` directly bypassing `get_redis()`, refactor those to use `get_redis()` is v1.8+ scope (avoid expanding Phase 27).
- **TD-04 dedupe rate dashboards** — once the audit_log starts collecting rows, build a Grafana panel; v1.8.
- **`LongTermMemory._get_pool` P1 backport** — if not opportunistically delivered as bonus in TD-04/TD-05 plan (Claude's Discretion), stays as v1.8 todo.
- **DOC-01** — Phase 28 scope; sweeps README + ARCHITECTURE.md + dev runbook + CHANGELOG for v1.7 changes.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 27-test-isolation-memory-reliability*
*Context gathered: 2026-05-17*
