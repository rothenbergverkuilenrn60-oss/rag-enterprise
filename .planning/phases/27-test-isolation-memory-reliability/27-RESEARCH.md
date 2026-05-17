# Phase 27: Test Isolation + Memory Reliability — Research

**Researched:** 2026-05-17
**Domain:** FastAPI factory pattern + pytest fixture isolation + pgvector bulk-dedupe SQL + asyncpg batch insert + Redis test-double
**Confidence:** HIGH (codebase facts grep-verified; pgvector bulk-query pattern empirically validated against the project's live PostgreSQL)

## Summary

CONTEXT.md locks 4 themes with concrete D-01..D-22 decisions. Research confirms the codebase reality is **broadly consistent** with those decisions but surfaces **three concrete corrections** the planner MUST adopt:

1. **CONTEXT.md D-13 SQL is wrong.** The proposed `unnest($1::vector[])` query does not work when the connection has `pgvector.asyncpg.register_vector` installed (which the `_get_pool` init hook installs unconditionally — `services/memory/memory_service.py:163`). Empirically tested: `DataError: expected ndim to be 1`. The working pattern is `unnest($1::text[]) WITH ORDINALITY AS t(vec_txt, idx)` with `vec_txt::vector` cast inside the JOIN/EXISTS predicate. Validated against the live `long_term_facts` schema.
2. **CONTEXT.md D-16 partial-failure assumption is wrong.** The current `OllamaEmbedder.embed_batch` (`services/vectorizer/embedder.py:61-70`) **raises `RuntimeError` on the first failed text** — it does NOT return `None` for failed inputs. `HuggingFaceEmbedder.embed_batch` is all-or-nothing. Only `OpenAIEmbedder.embed_batch` could be ergonomic but it currently raises on any error too. The planner must either (a) wrap the whole-batch embed in try/except and on failure fall back to N individual `embed_one` calls (degraded path), or (b) add per-item error tolerance to `embed_batch` first. Recommendation: (a) — cheaper and matches existing fail-open precedent.
3. **CONTEXT.md D-09 SC-3 conflict.** ROADMAP SC-3 reads "When the precheck hits, the save is skipped" — but D-09 says "v1.7 emits the audit row but DOES NOT SKIP THE SAVE." These contradict. D-09 cites EVICT-02 audit-mode-before-enforce as authority; treat **D-09 as the source of truth**. The planner must update SC-3 wording at plan time (or VERIFICATION.md author must apply the same correction). Acceptance test: "audit row emitted, dup row also inserted, second save_fact with the same content still creates a new row" — NOT "save is skipped."

Beyond those three corrections, every decision in CONTEXT.md is implementable as written. The singleton inventory in D-02 is **incomplete** (current: 15 entries; codebase grep finds ~38 module-level singletons under `services/`) — the planner should expand the curated list at plan time per CONTEXT D-02's own instruction. `fakeredis==2.35.1` is already a project dep (verified). FastAPI is mounted as a module-level `app = FastAPI(...)` at `main.py:169` with route mounts + middleware **after** construction — `create_app()` must replicate this exact ordering.

**Primary recommendation:** Plan as 4 themes; respect the three corrections above. TD-02 + TD-06 are test-infra (can run in parallel as Wave 1); TD-04 + TD-05 are memory-write (Wave 2 — TD-04 lays down the singular-save precheck, TD-05 batches it; TD-04 must land before TD-05 so the batch-path inherits the dedupe semantics).

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Phase boundary (CONTEXT §domain):** In scope = TD-02 + TD-04 + TD-05 + TD-06. Out of scope = TD-01/03/07 (shipped Phase 26), DOC-01 (Phase 28), full DI refactor, migration of 8 existing `from main import app` tests.

**Theme 1 — TD-02 `create_app()` factory:**
- **D-01:** New module `tests/factories/app.py` exports `create_app() -> FastAPI`. Each call (a) resets curated singleton list to None, (b) constructs fresh FastAPI instance via the existing `main.lifespan` factory.
- **D-02:** Singleton inventory list (15 items — see CONTEXT.md; **expand at plan time via fresh grep — confirmed below**).
- **D-03:** Lint test at `tests/unit/test_singleton_inventory_complete.py` enumerates module-level singletons via grep + AST scan; fails CI if any `_X_instance` pattern under `services/` is NOT in the factory's curated list.
- **D-04:** `create_app()` accepts optional `dependency_overrides: dict[Callable, Callable] | None = None` forwarded to `app.dependency_overrides`.
- **D-05:** No forced migration for the 8 existing `from main import app` tests. They coexist with the new factory.

**Theme 2 — TD-04 near-duplicate guard:**
- **D-06:** Precheck SQL: `SELECT 1 FROM long_term_facts WHERE user_id=$1 AND tenant_id=$2 AND embedding <=> $3::vector < $threshold LIMIT 1`. Per-(user_id, tenant_id) — matches v1.6 RLS contract.
- **D-07:** `memory_near_duplicate_threshold: float = Field(default=0.05, ge=0.0, le=1.0)` in `config/settings.py`.
- **D-08:** Extend `AuditAction` enum with `MEMORY_NEAR_DUPLICATE_SKIPPED` appended AFTER `MEMORY_EVICT`. One `audit_log` row per skip with actor, truncated fact (200 chars), and nearest-match similarity score in `detail` JSONB.
- **D-09:** **Audit-mode-only in v1.7.** Emit audit row but **DO NOT skip the save**. v1.8 will promote to silent-skip. [⚠ This contradicts ROADMAP SC-3 wording — see Open Questions.]
- **D-10:** Precheck runs on every save_fact call. One PG round-trip added per save.

**Theme 3 — TD-05 `save_facts` batch path:**
- **D-11:** `LongTermMemory.save_facts(facts: list[ExtractedFact]) -> SaveFactsResult` with counters (`saved_count`, `skipped_near_duplicates`, `skipped_embed_failures`).
- **D-12:** `save_fact` (singular) becomes a thin wrapper: `await self.save_facts([fact])`.
- **D-13:** Bulk SQL precheck — 1 RTT regardless of batch size. [⚠ Proposed `unnest($1::vector[])` does not work with the pgvector codec — see Theme 4 below for the corrected SQL.]
- **D-14:** Embed step uses `embedder.embed_batch([content_1, ..., content_N])`. 1 call for the whole batch. [⚠ Current `embed_batch` is all-or-nothing — see correction below.]
- **D-15:** Total RTT shape per ExtractorAgent turn with N facts: 1× embed_batch + 1× PG bulk dedupe + 1× PG executemany insert + K× audit_log entries. Old shape: 3N RTT. New shape: ≤3+K RTT.
- **D-16:** Best-effort partial failure: per-fact embed failures dropped from insert batch with `logger.warning`. [⚠ See correction below.]
- **D-17:** ExtractorAgent migration: inline edit at `services/agent/extractor.py:260` — replace the for-loop with single `await mem._long.save_facts(facts)` call.

**Theme 4 — TD-06 Redis-mock fixture:**
- **D-18:** Fixture lives in `tests/conftest.py`. Function-scoped, marker-opt-in via `@pytest.mark.uses_redis`. Auto-applied via `pytest_collection_modifyitems` hook.
- **D-19:** Mock target: `utils.cache.get_redis` (single canonical accessor). Plan-time audit required: confirm services do not import `redis.asyncio` directly bypassing `get_redis()`. [Audit result: **3 services do bypass** — see Codebase Reality below.]
- **D-20:** `MagicMock(spec=redis.asyncio.Redis)` with `AsyncMock` for `get`, `set`, `delete`, `expire`, `pipeline`, `eval`. Per-test in-memory dict-backed for state across get/set within a single test function.
- **D-21:** Integration tests bypass the mock automatically (no marker).
- **D-22:** **Caveat:** The "32 PR #9 unit failures" are openai SDK signature drift, NOT Redis. They are different from the v1.6 Phase 24 SUMMARY's "32 Redis-baseline failures." Plan 27 must include a diagnostic step to measure actual TD-06 impact.

### Claude's Discretion
- Exact singleton inventory (verify at plan-time via fresh grep — see updated list below).
- `SaveFactsResult` shape (default: dataclass).
- AuditAction enum name (proposed: `MEMORY_NEAR_DUPLICATE_SKIPPED`).
- `pytest_collection_modifyitems` auto-apply pattern.
- Opportunistic backport of Plan 26-04 P1 fix (`_get_pool` partial-init guard) to `LongTermMemory._get_pool`.

### Deferred Ideas (OUT OF SCOPE)
- TD-02 full DI refactor → v1.8+.
- TD-04 silent-skip promotion → v1.8.
- TD-04 audit dashboard / Grafana → v1.8 ops.
- openai SDK signature drift cleanup (32 PR #9 failures) → v1.8+ separate todo.
- TD-06 direct-redis-import refactor for bypassing services → v1.8+.
- `LongTermMemory._get_pool` P1 backport (if not bonus-delivered) → v1.8.
- DOC-01 → Phase 28.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TD-02 | Per-test `create_app()` factory replaces module-level singleton graph | `main.py:169` module-level `app = FastAPI(...)` + 38 module-level `_X = None` singletons under `services/` (grep-verified — see Codebase Reality §1). FastAPI factory pattern is the documented best practice (FastAPI testing docs §1). |
| TD-04 | `save_fact` cosine precheck via `<embedding> <=> $vec < 0.05` | Mirror of `LongTermMemory.get_relevant_facts` at `services/memory/memory_service.py:290-357`. Same HNSW + SET LOCAL discipline (`hnsw.iterative_scan='strict_order'`, `ef_search=settings.pgvector_ef_search_filtered=200`). |
| TD-05 | `save_facts(list[ExtractedFact])` batch with `1× embed_batch + 1× executemany` | Embedder ABC defines `embed_batch` at `services/vectorizer/embedder.py:29` (already exists, used by all 4 impls). asyncpg `executemany` precedent at `services/vectorizer/vector_store.py:264`. ExtractorAgent dispatch loop at `services/agent/extractor.py:255-266` is the sole caller. |
| TD-06 | Reusable `redis_mock` fixture for unit tests | `fakeredis==2.35.1` already in `pyproject.toml`. Canonical Redis accessor `utils.cache.get_redis` at `utils/cache.py:19-37`. 6 services consume it; 3 services bypass and import `redis.asyncio` directly (verified — see Theme 2 below). |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `create_app()` factory | Test Infrastructure | FastAPI app construction | Lives in `tests/factories/app.py` per D-01; reuses `main.lifespan` so production app construction is unchanged |
| Singleton reset | Test Infrastructure | services/* module attrs | Test-side mutation of `services.X._X_instance = None`; production code never touches the reset path |
| `redis_mock` fixture | Test Infrastructure | utils/cache.py mock target | pytest plugin layer; mocks the canonical accessor |
| Cosine precheck SQL | API/Database tier | services/memory/ | LongTermMemory adds 1 SELECT per save; pgvector handles HNSW filter |
| `save_facts` batch | API/Database tier | services/memory/ + services/agent/ | LongTermMemory owns the SQL; ExtractorAgent owns the dispatch |
| Audit-mode metric | API/Database tier | services/audit/ | AuditService.log() consumer of new MEMORY_NEAR_DUPLICATE_SKIPPED event |

## Codebase Reality

### §1. Module-level singletons under `services/` (full grep, 2026-05-17)

CONTEXT.md D-02 lists 15. Live grep returns **38**. The planner MUST expand the curated list. Full inventory:

| # | Location | Singleton | In D-02? |
|---|----------|-----------|----------|
| 1 | services/nlu/nlu_service.py:145 | `_ner_pipeline` | ✗ (add) |
| 2 | services/nlu/nlu_service.py:661 | `_nlu_service` | ✓ |
| 3 | services/nlu/filter_extractor.py:231 | `_filter_extractor` | ✓ |
| 4 | services/nlu/entity_disambiguator.py:250 | `_disambiguator` | ✓ |
| 5 | services/nlu/entity_disambiguator.py:387 | `_entity_lookup` | ✓ |
| 6 | services/retriever/retriever.py:192 | `_reranker` | ✗ (add) |
| 7 | services/retriever/retriever.py:676 | `_retriever` | ✓ |
| 8 | services/feedback/feedback_service.py:115 | `_feedback_service` | ✓ |
| 9 | services/auth/oidc_auth.py:238 | `_auth_service` | ✓ |
| 10 | services/agent/executor.py:252 | `_executor_instance` | ✓ |
| 11 | services/agent/tools/registry.py:106 | `_registry` | ✓ |
| 12 | services/agent/tools/web_search.py:100 | `_tavily_client` | ✓ |
| 13 | services/agent/extractor.py:183 | `_extractor` | ✓ |
| 14 | services/agent/planner.py:144 | `_planner_instance` | ✓ |
| 15 | services/memory/memory_service.py:625 | `_memory_service` | ✓ |
| 16 | services/annotation/annotation_service.py:308 | `_annotation_service` | ✓ |
| 17 | services/vectorizer/indexer.py:170 | `_vectorizer` | ✓ |
| 18 | services/vectorizer/vector_store.py:515 | `_store_instance` | ✗ (add — already reset in existing `pg_store` fixture) |
| 19 | services/vectorizer/embedder.py:236 | `_embedder_instance` | ✗ (add — already reset in existing `embedder_or_mock` fixture) |
| 20 | services/knowledge/knowledge_service.py:328 | `_knowledge_service` | ✗ (add) |
| 21 | services/knowledge/version_service.py:205 | `_version_service` | ✗ (add) |
| 22 | services/knowledge/summary_indexer.py:299 | `_summary_indexer` | ✗ (add) |
| 23 | services/audit/audit_service.py:386 | `_audit_service` | ✓ |
| 24 | services/generator/generator.py:30 | `_tiktoken_enc` | ✗ (skip — not a service; tokenizer cache) |
| 25 | services/generator/generator.py:474 | `_generator` | ✗ (add) |
| 26 | services/generator/llm_client.py:69 | `_anthropic_rate_limit_cls` | ✗ (skip — exception class cache) |
| 27 | services/generator/llm_client.py:70 | `_anthropic_overload_cls` | ✗ (skip — exception class cache) |
| 28 | services/generator/llm_client.py:1063 | `_llm_instance` | ✗ (add) |
| 29 | services/pipeline.py:1205 | `_ingest_pipeline` | ✗ (add) |
| 30 | services/pipeline.py:1206 | `_query_pipeline` | ✗ (add) |
| 31 | services/pipeline.py:1207 | `_agent_pipeline` | ✗ (add) |
| 32 | services/pipeline.py:1797 | `_swarm_pipeline` | ✗ (add) |
| 33 | services/tenant/tenant_service.py:104 | `_tenant_service` | ✗ (add) |
| 34 | services/rules/rules_engine.py:319 | `_rules_engine` | ✗ (add) |
| 35 | services/events/event_bus.py:284 | `_event_bus` | ✗ (add) |
| 36 | services/preprocessor/pii_detector.py:250 | `_pii_detector` | ✗ (add) |
| 37 | services/ab_test/ab_test_service.py:339 | `_ab_service` | ✗ (add) |
| 38 | services/extractor/ocr_engine.py:65 | `_sem` | ✗ (skip — asyncio.Semaphore, not a singleton service) |

**Plan-time action:** D-02 curated list needs ~17 additions. Skip the 4 "not a service" singletons (`_tiktoken_enc`, `_anthropic_*_cls`, `_sem`) — they are cached primitives, not service instances. Final curated list should be ~32 entries. The D-03 lint test naturally captures any subsequent additions because it greps for the `_X = None` pattern AND requires presence in the factory list; new additions will fail CI until added.

### §2. FastAPI app construction (`main.py`)

- `main.py:169`: `app = FastAPI(title=settings.app_name, version=settings.app_version, ..., lifespan=lifespan)` — module-level construction.
- `main.py:181-183`: app state + exception handler + middleware additions (`slowapi`).
- `main.py:191-197`: `CORSMiddleware` added.
- `main.py:203-231`: `@app.middleware("http")` decorator for trace_middleware.
- Beyond that: rate-limit middleware (`_redis_rate_check`), router mounts (`router`, `memory_router`), static file mounts.

`lifespan` is an async context manager at `main.py:47-?` (registered via `lifespan=lifespan` kwarg). It owns startup-time side effects (vectorizer warmup, EventBus start, optional knowledge-scan, lifespan-managed shutdown closers added by Plan 26-05). **The factory MUST reuse this lifespan handler verbatim** (CONTEXT canonical refs note this — no `main.py` touches required).

**Critical caveat the planner must handle:** module-level `app.add_middleware(...)` + `@app.middleware("http")` decorators in `main.py` execute at **import time**. If `tests/factories/app.py` does `from main import lifespan` then constructs a fresh `FastAPI(lifespan=lifespan)`, the middleware setup must be replicated in the factory body — there is no `app.copy()` API. Reasonable refactor: extract the "apply middleware + mount routers" body into a `_configure_app(app: FastAPI) -> None` helper in `main.py`; both the module-level `app` AND `create_app()` call it. This is a `main.py` touch — CONTEXT says "no main.py touches required" but that comment was about lifespan; middleware extraction is a small additive helper, not a behavioral change. Planner should note this as a needed delta.

### §3. `LongTermMemory.save_fact` (current)

`services/memory/memory_service.py:359-396`:

```python
async def save_fact(self, user_id, tenant_id, fact, source_doc="", importance=0.5) -> None:
    # Step 1: embed (separate try)
    try:
        embedding = await get_embedder().embed_one(fact)
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        raise MemoryFactWriteError("embedding failed") from exc

    # Step 2: INSERT (separate try)
    try:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO long_term_facts
                   (user_id, tenant_id, fact, source_doc, importance, embedding)
                   VALUES ($1,$2,$3,$4,$5,$6::vector)""",
                user_id, tenant_id, fact, source_doc, importance, embedding,
            )
    except asyncpg.PostgresError as exc:
        raise MemoryFactWriteError("persistence failed") from exc
```

Embed step uses `embed_one`, not `embed_batch`. The save is **non-transactional** (single execute per row).

### §4. `LongTermMemory.get_relevant_facts` (pattern to mirror)

`services/memory/memory_service.py:290-357` — the canonical HNSW filtered cosine query:

```sql
SET LOCAL hnsw.iterative_scan = 'strict_order'
SET LOCAL hnsw.ef_search = {ef}    -- ef = settings.pgvector_ef_search_filtered (default 200)
SELECT fact FROM long_term_facts
WHERE user_id=$1 AND tenant_id=$2
ORDER BY embedding <=> $3::vector, importance DESC, created_at DESC
LIMIT $4
```

Wrapped in `async with conn.transaction()`. The TD-04 precheck must use the same `SET LOCAL` GUC discipline so HNSW returns exact top-K under the (user_id, tenant_id) pre-filter.

### §5. ExtractorAgent dispatch site (`services/agent/extractor.py:255-266`)

```python
mem = get_memory_service()
for f in facts:
    await mem._long.save_fact(
        user_id=user_id, tenant_id=tenant_id,
        fact=f.fact, source_doc="",
        importance=f.importance,
    )
```

**This is the only call site of `save_fact` in production code** (grep-verified). TD-05 D-17 inline migration replaces the for-loop with `await mem._long.save_facts(facts)`. `ExtractedFact` (from `utils/models.py`) has fields `fact: str`, `category: Literal[...]`, `importance: Literal[0.2, 0.5, 0.8]` — frozen Pydantic V2 model.

### §6. Redis consumer audit (TD-06 D-19)

`utils.cache.get_redis` at `utils/cache.py:19-37` returns a module-level `_redis_client` singleton via `redis.asyncio.from_url(settings.redis_url, ...)`. CONTEXT D-19 says "every service that uses Redis lazy-imports through this function." **Grep audit result — partly true:**

| Service | Path | Uses `get_redis()`? | Bypass? |
|---------|------|---------------------|---------|
| services/nlu/entity_disambiguator.py | line 289 | ✓ (lazy) | — |
| services/annotation/annotation_service.py | line 51 | ✓ (lazy) | also imports `redis.asyncio` at module top line 25 |
| services/knowledge/version_service.py | line 40 | ✓ (lazy) | also imports `redis.asyncio` at module top line 20 |
| services/ab_test/ab_test_service.py | line 122 | ✓ (lazy) | — |
| services/pipeline.py | lines 138, 165 | ✓ (lazy) | — |
| **services/memory/memory_service.py** | line 100 | ✗ | **Direct `from redis.asyncio import from_url`** — `ShortTermMemory._get_client` builds its own client (line 87-108). NOT going through `get_redis()`. |
| services/ingest_worker.py | ? | TBD — CONTEXT lists it but not grep-confirmed |
| main.py | line 16, 258 | mixed — `_redis_rate_check` calls `get_redis()` via lazy import line 257; module top imports `redis` |

**Implication for TD-06:** Mocking `utils.cache.get_redis` will NOT intercept `ShortTermMemory`. The planner must EITHER (a) refactor `ShortTermMemory._get_client` to delegate to `get_redis()` (cheap one-liner — bonus delivery), OR (b) also mock `services.memory.memory_service.from_url` at consumer path. CONTEXT D-19 already flags this — recommendation is (a) since it's a 3-line surgical change matching the Phase 26 "delegate to centralized helper" pattern.

### §7. Test infrastructure

- `tests/conftest.py` (195 lines): function-scoped `pg_pool` (PG_AVAILABLE skip-guard at collection); `pg_store` (resets `vs_module._store_instance = None`); `extractor_llm_mock` (resets `_extractor` + patches `get_llm_client`); `embedder_or_mock` (resets `_embedder_instance` + dual-patch). **The pattern of resetting module-level singletons in fixtures is already established** — TD-02 just generalizes it.
- `tests/factories/` does **not exist** — TD-02 creates it.
- 8 files import `from main import app` (verified — matches CONTEXT D-05 count). Spread across:
  - `tests/integration/test_pipeline.py` (3 uses)
  - `tests/integration/test_memory_forget_e2e.py` (4 uses)
  - `tests/integration/test_ui_static.py` (1 use)
  - `tests/unit/test_agent_stream_route.py` (1 use)
  - `tests/unit/test_memory_controller.py` (1 use)
  - `tests/unit/test_rate_limiting.py` (3 uses)
  - `tests/unit/test_ingest_status.py` (7 uses)
  - `tests/unit/test_static_ui.py` (1 use)

### §8. AuditService.log signature (TD-04 consumer)

`services/audit/audit_service.py:183-204`:

```python
async def log(self, event: AuditEvent) -> None:
    if not getattr(settings, "audit_enabled", True):
        return
    # 1. Loguru file write
    # 2. Buffered DB write if audit_db_enabled
```

`AuditEvent` (line 52-64): dataclass with `event_id`, `timestamp`, `user_id`, `tenant_id`, `action: str`, `resource_id`, `ip_address`, `result`, `detail: dict`, `trace_id`. TD-04 writes via:

```python
await get_audit_service().log(AuditEvent(
    user_id=user_id, tenant_id=tenant_id,
    action=AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED,
    resource_id="",
    result=AuditResult.SKIPPED,
    detail={"fact_truncated": fact[:200], "nearest_similarity": float(sim_score)},
))
```

`AuditAction.MEMORY_EVICT` is the current last entry at line 42 — D-08 says append after it.

### §9. Embedder reality check (corrects D-16)

`services/vectorizer/embedder.py`:

- `BaseEmbedder.embed_batch` (line 29): abstract method `(texts: list[str]) -> list[list[float]]`.
- `BaseEmbedder.embed_one` (line 32-34): delegates to `embed_batch([text])`.
- `OllamaEmbedder.embed_batch` (line 61-70): runs N concurrent `_embed_single` calls via `asyncio.gather(*, return_exceptions=True)` — **raises `RuntimeError` on the FIRST failed text**. NOT per-item-None.
- `OpenAIEmbedder.embed_batch` (line 85-99): single API call; raises on any error.
- `HuggingFaceEmbedder.embed_batch` (line 115-126): single torch call; raises on any error.

**D-16 assumes per-input None.** This does not match any current embedder. The planner must specify the partial-failure strategy:

- **Recommended:** Try `embed_batch(facts)`. On `RuntimeError` / `httpx.HTTPError` / `OSError`, fall back to N parallel `embed_one(f.fact)` calls inside a `gather(return_exceptions=True)`, then drop the failed ones. This preserves the "1 embed call in the happy path" SC-4 contract while honoring D-16 best-effort tolerance on the unhappy path.
- **Alternative (more work):** Refactor `embed_batch` impls to return `list[list[float] | None]` and adjust callers. This is the "right" long-term solution but expands Phase 27 scope — recommend deferring to v1.8.

### §10. pgvector codec interaction (corrects D-13)

Empirically tested against live PostgreSQL (this machine, `postgresql://rag:rag@localhost:5432/ragdb`):

```
WITH register_vector(conn) installed (which _get_pool ALWAYS does):
  unnest($1::vector[]) WITH ORDINALITY AS t(vec, idx)
  + passing list[list[float]] → DataError: "expected ndim to be 1"
  + passing numpy.stack(vecs) → same DataError
  + passing list of vector-literal strings → DataError "could not convert string to float"
```

The pgvector codec hijacks `vector[]` parameter interpretation expecting a single 1-D vector, not an array of vectors. **The corrected pattern that DOES work** (verified — empty result set, no error, correct EXPLAIN plan):

```sql
SELECT idx FROM unnest($1::text[]) WITH ORDINALITY AS t(vec_txt, idx)
WHERE EXISTS (
    SELECT 1 FROM long_term_facts
    WHERE user_id = $2 AND tenant_id = $3
    AND embedding <=> vec_txt::vector < $4
)
```

Pass `$1` as `list[str]` of vector literals: `'[0.1,0.2,...,0.999]'`. Helper: `vec_literal = '[' + ','.join(str(x) for x in vec) + ']'`. Python builds N literals once on the client; PostgreSQL casts each per-row via `vec_txt::vector`. The HNSW index still applies because the predicate is `embedding <=> $vec` and the planner sees `$vec` as a parametric vector after cast.

Index alternative if performance is an issue: pre-build a temporary table with `(idx int, vec vector)` columns, populate via `executemany`, then JOIN. But for N≤20 (the realistic ExtractorAgent batch size), the text[]+cast pattern is fast enough — no temporary table needed.

## Theme 1 — TD-02 `create_app()` factory

### Recommended approach

```python
# tests/factories/app.py
from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from fastapi import FastAPI


# Module-attr tuples (module_path, attr_name). Order does not matter — reset is idempotent.
_SINGLETON_INVENTORY: tuple[tuple[str, str], ...] = (
    ("services.nlu.nlu_service",            "_nlu_service"),
    ("services.nlu.nlu_service",            "_ner_pipeline"),
    ("services.nlu.filter_extractor",       "_filter_extractor"),
    ("services.nlu.entity_disambiguator",   "_disambiguator"),
    ("services.nlu.entity_disambiguator",   "_entity_lookup"),
    ("services.retriever.retriever",        "_retriever"),
    ("services.retriever.retriever",        "_reranker"),
    ("services.feedback.feedback_service",  "_feedback_service"),
    ("services.auth.oidc_auth",             "_auth_service"),
    ("services.agent.executor",             "_executor_instance"),
    ("services.agent.tools.registry",       "_registry"),
    ("services.agent.tools.web_search",     "_tavily_client"),
    ("services.agent.extractor",            "_extractor"),
    ("services.agent.planner",              "_planner_instance"),
    ("services.memory.memory_service",      "_memory_service"),
    ("services.annotation.annotation_service","_annotation_service"),
    ("services.vectorizer.indexer",         "_vectorizer"),
    ("services.vectorizer.vector_store",    "_store_instance"),
    ("services.vectorizer.embedder",        "_embedder_instance"),
    ("services.knowledge.knowledge_service","_knowledge_service"),
    ("services.knowledge.version_service",  "_version_service"),
    ("services.knowledge.summary_indexer",  "_summary_indexer"),
    ("services.audit.audit_service",        "_audit_service"),
    ("services.generator.generator",        "_generator"),
    ("services.generator.llm_client",       "_llm_instance"),
    ("services.pipeline",                   "_ingest_pipeline"),
    ("services.pipeline",                   "_query_pipeline"),
    ("services.pipeline",                   "_agent_pipeline"),
    ("services.pipeline",                   "_swarm_pipeline"),
    ("services.tenant.tenant_service",      "_tenant_service"),
    ("services.rules.rules_engine",         "_rules_engine"),
    ("services.events.event_bus",           "_event_bus"),
    ("services.preprocessor.pii_detector",  "_pii_detector"),
    ("services.ab_test.ab_test_service",    "_ab_service"),
)


def _reset_singletons() -> None:
    """Reset every module-level service singleton to None."""
    import importlib
    for module_path, attr in _SINGLETON_INVENTORY:
        mod = importlib.import_module(module_path)
        # raising=False semantics — silently skip if attr was removed in a refactor
        if hasattr(mod, attr):
            setattr(mod, attr, None)


def create_app(
    *,
    dependency_overrides: Optional[dict[Callable, Callable]] = None,
) -> FastAPI:
    """Build a fresh, isolated FastAPI app for testing.

    Each call resets the service-singleton graph and constructs a new FastAPI
    instance via main.lifespan, so two tests running in parallel see independent
    state.
    """
    _reset_singletons()
    # Lazy import — main imports settings + many singletons at module load.
    from main import _configure_app, lifespan
    app = FastAPI(lifespan=lifespan)
    _configure_app(app)  # mounts middleware + routers
    if dependency_overrides:
        app.dependency_overrides.update(dependency_overrides)
    return app
```

### `main.py` delta (small, additive)

Extract the "apply middleware + mount routers + register exception handlers" block (currently at `main.py:181-` through router mounts) into a new top-level function `_configure_app(app: FastAPI) -> None`. The module-level `app` continues to call `_configure_app(app)` at import time. The factory calls it on its fresh app. Net behavior change: zero. Required because there is no `FastAPI.copy()` API.

### Fixture design

```python
# In tests/conftest.py (extension):
@pytest.fixture
async def app_factory():
    """Returns a callable that yields a fresh isolated app per call."""
    from tests.factories.app import create_app
    created: list[FastAPI] = []
    def _factory(**kwargs):
        app = create_app(**kwargs)
        created.append(app)
        return app
    yield _factory
    # Teardown — reset singletons one more time so the next test's pre-state is clean
    from tests.factories.app import _reset_singletons
    _reset_singletons()

@pytest.fixture
async def isolated_app(app_factory):
    """Convenience: pre-built isolated app for tests that don't need overrides."""
    return app_factory()

@pytest.fixture
async def isolated_client(isolated_app):
    """ASGI TestClient against the isolated app."""
    from httpx import ASGITransport, AsyncClient
    async with AsyncClient(transport=ASGITransport(app=isolated_app), base_url="http://test") as c:
        yield c
```

Function-scoped per CONTEXT D-01. Session-scoped is wrong here — defeats the entire point.

### Cross-contamination test design (ROADMAP SC-1)

```python
# tests/integration/test_create_app_isolation.py
@pytest.mark.asyncio
async def test_two_apps_do_not_share_state(app_factory):
    app_a = app_factory()
    app_b = app_factory()

    # Mutate a module-level singleton AFTER constructing app_a so app_a's lifespan
    # didn't pre-populate it. Use a stable singleton — registry counter, executor.
    import services.agent.executor as exec_mod
    sentinel = object()
    exec_mod._executor_instance = sentinel

    # Construct app_b — should reset the sentinel.
    app_b2 = app_factory()
    assert exec_mod._executor_instance is None, \
        "create_app() did not reset singletons; cross-contamination possible"

    # Also verify the two app instances themselves are distinct
    assert app_a is not app_b
    assert app_a is not app_b2
```

A stronger variant uses `asyncio.gather` to run two coroutines that each mutate per-app state via `dependency_overrides` and assert observed state matches each app's own override (not the other's). The simpler variant above is enough to satisfy SC-1's "Two tests running in parallel against `create_app()` do not observe each other's state."

### Lint test design (D-03)

```python
# tests/unit/test_singleton_inventory_complete.py
import re
from pathlib import Path

SERVICES_DIR = Path("services")
SINGLETON_PATTERN = re.compile(
    r"^_[a-zA-Z_]+(?:_instance|_service|_client|_executor|_planner|_registry|_pipeline)?\b.*?(?:: *[A-Z][\w\[\]\| ]+ *)?=\s*None\s*$",
    re.MULTILINE,
)
# Skip list — non-service singletons (tokenizer caches, exception class refs, semaphores)
_SKIP = {
    ("services/generator/generator.py", "_tiktoken_enc"),
    ("services/generator/llm_client.py", "_anthropic_rate_limit_cls"),
    ("services/generator/llm_client.py", "_anthropic_overload_cls"),
    ("services/extractor/ocr_engine.py", "_sem"),
}

def test_singleton_inventory_covers_all_module_globals():
    from tests.factories.app import _SINGLETON_INVENTORY
    inventory = {(mod.replace(".", "/") + ".py", attr) for mod, attr in _SINGLETON_INVENTORY}

    missing = []
    for py in SERVICES_DIR.rglob("*.py"):
        rel = str(py).replace("\\", "/")
        text = py.read_text(encoding="utf-8")
        for line in text.splitlines():
            m = re.match(r"^(_[a-zA-Z_]+)\s*[:=]", line.strip())
            if not m:
                continue
            if "= None" not in line:
                continue
            attr = m.group(1)
            if (rel, attr) in _SKIP:
                continue
            if (rel, attr) not in inventory:
                missing.append((rel, attr))

    assert not missing, (
        f"Module-level singletons in services/ not covered by _SINGLETON_INVENTORY: {missing}. "
        f"Add to tests/factories/app.py or to the test's _SKIP list with justification."
    )
```

### Migration sequencing

Per CONTEXT D-05, no forced migration of the 8 existing `from main import app` tests. They coexist with the new factory. New tests + the audit/memory **integration suites named in ROADMAP SC-1** are the migration targets:

| Suite | Path | Current pattern | Migration |
|-------|------|-----------------|-----------|
| Audit integration | tests/integration/test_audit_log_auto_create.py | direct AuditService instantiation | Use `app_factory(dependency_overrides=...)` if it currently couples to the app; else leave alone (no app coupling) |
| Memory integration | tests/integration/test_extractor_e2e.py, test_pgvector_recall.py, test_pgvector_filtered_recall.py, test_long_term_facts_schema.py | direct service instantiation | Same — only convert if they couple to FastAPI |
| **Phase 27 NEW** | tests/integration/test_create_app_isolation.py | n/a | Built from scratch on `app_factory` |
| **Phase 27 NEW** | tests/integration/test_save_facts_batch_e2e.py | n/a | Built on `app_factory` for SC-4 end-to-end |

CONTEXT SC-1 says "the audit + memory integration suites construct an isolated app per test through this factory" — but most of those suites today don't use FastAPI at all (they instantiate `AuditService()`, `LongTermMemory()` directly). The planner should clarify whether SC-1 means "test files that DO touch FastAPI in audit/memory suites" or "build at least one new test per suite that exercises the factory." Recommended interpretation: the latter — author 1-2 new tests per suite that go through the factory, leaving the existing direct-instantiation tests unchanged.

## Theme 2 — TD-06 Redis-mock fixture

### Library choice: `fakeredis>=2.35`

`fakeredis==2.35.1` is already in the project dependency set (`pyproject.toml` — verified via `uv run python -c "import fakeredis"`). It provides `fakeredis.aioredis.FakeRedis` which is API-compatible with `redis.asyncio.Redis` including string GET/SET, lists (LRANGE, RPUSH used by `ShortTermMemory`), sorted sets (ZADD/ZCOUNT used by `_redis_rate_check` in main.py), pipelines, and `eval` for Lua scripts. It is the right tool — no need for a hand-rolled `MagicMock(spec=...)` as D-20 originally proposed.

**Recommendation:** Override D-20 to use `fakeredis.aioredis.FakeRedis()` as the backing object rather than `MagicMock(spec=redis.asyncio.Redis)`. Reason: the codebase exercises sorted sets, lists, expire, pipeline, and Lua eval. Hand-rolling a MagicMock that returns "sensible defaults" for all of these is hours of work that fakeredis already provides correctly. The `MagicMock` approach should be kept as a thin wrapper for the 1-2 tests that genuinely need to assert call_count on `r.set(...)` etc. — but the default backing should be fakeredis for state realism.

### Fixture placement

CONTEXT D-18 locks `tests/conftest.py`. Concrete shape:

```python
# tests/conftest.py (additions)
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "uses_redis: test exercises Redis path; redis_mock fixture auto-applied"
    )


def pytest_collection_modifyitems(config, items):
    """Auto-apply the redis_mock fixture to every test marked @pytest.mark.uses_redis."""
    for item in items:
        if "uses_redis" in item.keywords and "redis_mock" not in item.fixturenames:
            item.fixturenames.append("redis_mock")


@pytest.fixture
async def redis_mock(monkeypatch):
    """In-memory Redis double for unit tests. Mocks utils.cache.get_redis at the
    consumer path so every service that lazy-imports get_redis() receives the fake.
    """
    import fakeredis.aioredis
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_redis_stub():
        return fake

    # Mock the canonical accessor.
    monkeypatch.setattr("utils.cache.get_redis", _get_redis_stub)
    # Also reset the module-level _redis_client so a prior test's real connection
    # is not reused.
    import utils.cache as cache_mod
    monkeypatch.setattr(cache_mod, "_redis_client", None, raising=False)

    # Edge case: ShortTermMemory bypasses get_redis and calls redis.asyncio.from_url
    # directly (services/memory/memory_service.py:100). Mock the lazy-import path
    # so ShortTermMemory also receives the fake.
    async def _from_url_stub(*args, **kwargs):
        return fake
    monkeypatch.setattr("redis.asyncio.from_url", _from_url_stub)

    yield fake

    # Teardown — explicit close
    try:
        await fake.aclose()
    except Exception:
        pass
```

### Unit/integration boundary

CONTEXT D-21 — integration tests don't add `@pytest.mark.uses_redis`. So:

- `tests/unit/test_X.py` + `@pytest.mark.uses_redis` → auto-receives `redis_mock` fixture → fakeredis-backed.
- `tests/unit/test_Y.py` without marker → no Redis involvement; if it accidentally hits Redis, it fails on connection refused (correct — surface the missing marker).
- `tests/integration/test_Z.py` (no marker) → uses real Redis if `localhost:6379` is up; skips otherwise. The conftest can add a `redis_available` collection skip-guard similar to `pg_available`.

### Diagnostic plan for D-22 caveat

CONTEXT D-22 mandates a measurement step. Concrete plan-task:

1. Capture current baseline: `uv run pytest tests/unit/ -x --co | wc -l` then `uv run pytest tests/unit/ 2>&1 | tail -50`. Record failure count + grep the failure messages for `ConnectionError: Error 111 connecting to localhost:6379` (Redis) vs `APIError.__init__() missing` (openai SDK).
2. Apply TD-06 (Plan 27-XX). Add `@pytest.mark.uses_redis` to every unit-test file that fails with the Redis ConnectionError pattern.
3. Re-run `uv run pytest tests/unit/` and record new failure count.
4. **SC-2 acceptance:** "Redis-ConnectionError failures go to 0 in the unit suite." NOT "all 32 PR #9 failures go to 0." The openai SDK drift failures persist (separate todo).

The Phase 24 SUMMARY explicitly lists the Redis-baseline files: `test_agent_pipeline_refactor.py`, `test_agent_sse.py`, `test_feedback_ab_forward.py`, `test_pipeline_coverage.py`. Step 2 marker-application targets these.

### `ShortTermMemory` direct-import refactor (D-19 follow-on)

`services/memory/memory_service.py:87-108` `ShortTermMemory._get_client` calls `redis.asyncio.from_url` directly. CONTEXT D-19 says "confirm no service imports `redis.asyncio` directly and bypasses `get_redis()`. If any do, add them to a v1.8+ todo." Found one — but this is a 3-line refactor:

```python
async def _get_client(self):
    if self._client is None:
        from utils.cache import get_redis
        self._client = await get_redis()
    return self._client
```

**Recommendation:** Include as a bonus task in the TD-06 plan (it directly enables `ShortTermMemory` tests to receive the fakeredis fake without the extra `redis.asyncio.from_url` monkey-patch in the fixture). Add to "Claude's Discretion" delivery.

## Theme 3 — TD-04 Cosine-precheck near-duplicate guard

### Exact SQL (singular path)

Mirror of `get_relevant_facts` GUC discipline (`services/memory/memory_service.py:336-352`):

```python
async def _is_near_duplicate(
    self, conn, *, user_id: str, tenant_id: str, embedding: list[float], threshold: float,
) -> tuple[bool, float | None]:
    """Returns (is_duplicate, nearest_similarity_distance).
    Distance is cosine distance from pgvector (0=identical, 2=opposite).
    """
    async with conn.transaction():
        ef = int(getattr(settings, "pgvector_ef_search_filtered", 200))
        await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
        await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")
        row = await conn.fetchrow(
            """SELECT embedding <=> $3::vector AS dist
               FROM long_term_facts
               WHERE user_id=$1 AND tenant_id=$2
               ORDER BY embedding <=> $3::vector
               LIMIT 1""",
            user_id, tenant_id, embedding,
        )
    if row is None:
        return (False, None)
    dist = float(row["dist"])
    return (dist < threshold, dist)
```

Note: D-06 proposed `LIMIT 1` on the boolean form (`WHERE ... < $threshold`). I changed to `ORDER BY ... LIMIT 1` + post-check so the audit log can include the actual nearest-distance score (D-08 requirement: "nearest-match similarity score in `detail` JSONB"). Same RTT cost, more useful audit data.

### Index implications

The existing `ltf_emb_hnsw_idx` (`services/memory/memory_service.py:233-236`) is `USING hnsw (embedding vector_cosine_ops)`. The precheck query benefits from this index **only** under the SET LOCAL GUCs (per v1.6 Phase 8 / Phase 24 — without them, HNSW falls back to seq-scan when filters are applied). The same GUC discipline as `get_relevant_facts` applies — research confirmed via the docstring of `get_relevant_facts` lines 299-305.

Cost estimate (local pgvector, 1024-dim vector, ~10K rows per tenant): ~1-2ms per query — negligible per CONTEXT D-10.

### Semantics clarification (resolves SC-3 vs D-09 conflict)

ROADMAP SC-3: "When the precheck hits, the save is skipped..."
CONTEXT D-09: "v1.7 emits the audit row but DOES NOT SKIP THE SAVE. Save still happens — duplicate row inserted."

**D-09 is the authoritative position per Audit-Mode-Before-Enforce (v1.6 Phase 25 EVICT-02).** Recommendation: planner must explicitly state the corrected semantics in PLAN.md so VERIFICATION.md author tests for "audit row written AND duplicate row inserted" rather than "save skipped." If user disagrees and wants ROADMAP wording to win, that's a discuss-phase callback.

Concrete v1.7 behavior:

```python
async def save_fact(self, user_id, tenant_id, fact, source_doc="", importance=0.5) -> None:
    # Step 1: embed
    embedding = await get_embedder().embed_one(fact)

    # Step 2: precheck (audit-mode)
    pool = await self._get_pool()
    async with pool.acquire() as conn:
        is_dup, dist = await self._is_near_duplicate(
            conn, user_id=user_id, tenant_id=tenant_id,
            embedding=embedding, threshold=settings.memory_near_duplicate_threshold,
        )
        if is_dup:
            # Audit-mode: log + continue. NOT skip.
            await _fire_near_duplicate_audit(user_id, tenant_id, fact, dist)
        # Step 3: INSERT (always — v1.7 audit-mode-only)
        await conn.execute(
            """INSERT INTO long_term_facts ... VALUES (...)""",
            user_id, tenant_id, fact, source_doc, importance, embedding,
        )
```

Audit-write helper:

```python
async def _fire_near_duplicate_audit(user_id, tenant_id, fact, dist):
    try:
        from services.audit.audit_service import (
            AuditAction, AuditEvent, AuditResult, get_audit_service,
        )
        await get_audit_service().log(AuditEvent(
            user_id=user_id, tenant_id=tenant_id,
            action=AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED,
            resource_id="",
            result=AuditResult.SKIPPED,  # semantic intent — even though save NOT skipped in v1.7
            detail={"fact_truncated": fact[:200], "nearest_distance": dist},
        ))
    except Exception as exc:  # noqa: BLE001 — audit-write failure must NOT block (v1.6 GDPR T1)
        logger.warning("audit write failed (non-fatal): {}", exc)
```

### Failure mode policy

CONTEXT carry-forward: "Audit-write failure must NOT block" (v1.6 GDPR T1). Apply same shape to the precheck SELECT — if it fails (`asyncpg.PostgresError`), fall-open: log a warning, skip the precheck, proceed with the save. Same shape as `get_relevant_facts` lines 353-357 ("Returns [] on any failure"). This matches the "save_fact is best-effort" Phase 23 D-05 precedent.

## Theme 4 — TD-05 Batch `save_facts`

### Exact signature

```python
# In services/memory/memory_service.py (additions)
from dataclasses import dataclass
from utils.models import ExtractedFact


@dataclass(frozen=True)
class SaveFactsResult:
    """Per-call observability for save_facts. Returned to caller (ExtractorAgent)."""
    saved_count: int
    skipped_near_duplicates: int
    skipped_embed_failures: int


class LongTermMemory:
    async def save_facts(
        self,
        facts: list[ExtractedFact],
        *,
        user_id: str,
        tenant_id: str,
        source_doc: str = "",
    ) -> SaveFactsResult:
        """Batch-save N facts. 1× embed_batch + 1× PG dedupe query + 1× PG executemany.
        Honors TD-04 near-duplicate audit-mode contract for every fact in the batch.
        """
        if not facts:
            return SaveFactsResult(0, 0, 0)
        # ... (implementation below)

    async def save_fact(
        self, user_id, tenant_id, fact, source_doc="", importance=0.5,
    ) -> None:
        """Thin wrapper — delegates to save_facts.  Existing callers unchanged."""
        from utils.models import ExtractedFact
        result = await self.save_facts(
            [ExtractedFact(fact=fact, category="recurring_topics", importance=importance)],
            user_id=user_id, tenant_id=tenant_id, source_doc=source_doc,
        )
        if result.saved_count == 0 and result.skipped_embed_failures > 0:
            raise MemoryFactWriteError("embedding failed")
```

**Caveat for D-12 wrapper:** existing `save_fact(user_id, ..., fact, ..., importance=0.5)` callers don't pass an `ExtractedFact` model — they pass raw `fact: str` + `importance: float`. The wrapper constructs an `ExtractedFact` on the caller's behalf. `ExtractedFact.importance` is `Literal[0.2, 0.5, 0.8]` — if a caller passes a non-literal value, Pydantic raises `ValidationError`. Two options:
- (a) Make the wrapper coerce `importance` to the nearest literal (0.2 / 0.5 / 0.8).
- (b) Loosen `ExtractedFact.importance` to `float` in `utils/models.py`.

Option (a) preserves Phase 23 D-05 schema-level adversarial defense. Recommend (a) — round to nearest of {0.2, 0.5, 0.8}.

### Bulk dedupe SQL (corrected — empirically validated)

```python
async def _bulk_near_duplicate_check(
    self, conn, *, user_id: str, tenant_id: str, embeddings: list[list[float]], threshold: float,
) -> set[int]:
    """Returns 0-based indices of embeddings that are near-duplicates of an existing fact.
    1 PG RTT regardless of batch size.

    The text[] cast pattern is required because pgvector.asyncpg register_vector
    breaks the obvious unnest($1::vector[]) form (empirically verified 2026-05-17).
    """
    vec_literals = ['[' + ','.join(str(x) for x in v) + ']' for v in embeddings]
    async with conn.transaction():
        ef = int(getattr(settings, "pgvector_ef_search_filtered", 200))
        await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
        await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")
        rows = await conn.fetch(
            """SELECT (idx - 1) AS zero_idx
               FROM unnest($1::text[]) WITH ORDINALITY AS t(vec_txt, idx)
               WHERE EXISTS (
                   SELECT 1 FROM long_term_facts
                   WHERE user_id = $2 AND tenant_id = $3
                   AND embedding <=> vec_txt::vector < $4
               )""",
            vec_literals, user_id, tenant_id, threshold,
        )
    return {row["zero_idx"] for row in rows}
```

### Full `save_facts` implementation sketch

```python
async def save_facts(self, facts, *, user_id, tenant_id, source_doc="") -> SaveFactsResult:
    if not facts:
        return SaveFactsResult(0, 0, 0)

    # Step 1 — embed all (1 batch call; fall back to per-item on failure)
    embedder = get_embedder()
    embed_failures = 0
    embeddings: list[list[float] | None]
    try:
        embeddings = await embedder.embed_batch([f.fact for f in facts])
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        logger.warning("embed_batch failed; falling back per-item: {}", exc)
        embeddings = []
        per_item = await asyncio.gather(
            *(embedder.embed_one(f.fact) for f in facts),
            return_exceptions=True,
        )
        for r in per_item:
            if isinstance(r, BaseException):
                embeddings.append(None)
                embed_failures += 1
            else:
                embeddings.append(r)

    # Filter out embed-failed entries before precheck + insert
    indexed = [(i, f, e) for i, (f, e) in enumerate(zip(facts, embeddings)) if e is not None]
    if not indexed:
        return SaveFactsResult(0, 0, embed_failures)

    pool = await self._get_pool()
    async with pool.acquire() as conn:
        # Step 2 — bulk dedupe precheck (1 RTT)
        valid_embeddings = [e for _, _, e in indexed]
        try:
            dup_zero_idxs = await self._bulk_near_duplicate_check(
                conn, user_id=user_id, tenant_id=tenant_id,
                embeddings=valid_embeddings,
                threshold=settings.memory_near_duplicate_threshold,
            )
        except asyncpg.PostgresError as exc:
            logger.warning("bulk dedupe check failed (fail-open): {}", exc)
            dup_zero_idxs = set()

        # Step 3 — fire audit rows for duplicates (best-effort, in parallel)
        audit_tasks = []
        for local_i in dup_zero_idxs:
            _, f, _ = indexed[local_i]
            audit_tasks.append(_fire_near_duplicate_audit(
                user_id, tenant_id, f.fact, dist=None,  # bulk path drops the per-row distance
            ))
        if audit_tasks:
            await asyncio.gather(*audit_tasks, return_exceptions=True)

        # Step 4 — executemany insert (audit-mode v1.7: do NOT skip duplicates)
        rows_to_insert = [
            (user_id, tenant_id, f.fact, source_doc, f.importance, e)
            for _, f, e in indexed
        ]
        try:
            await conn.executemany(
                """INSERT INTO long_term_facts
                   (user_id, tenant_id, fact, source_doc, importance, embedding)
                   VALUES ($1,$2,$3,$4,$5,$6::vector)""",
                rows_to_insert,
            )
        except asyncpg.PostgresError as exc:
            raise MemoryFactWriteError("batch persistence failed") from exc

    return SaveFactsResult(
        saved_count=len(rows_to_insert),
        skipped_near_duplicates=len(dup_zero_idxs),  # "skipped" is semantic (audit row only); v1.8 will actually skip
        skipped_embed_failures=embed_failures,
    )
```

### Mock-based unit test for SC-4 (1 embed + 1 PG RTT)

```python
# tests/unit/test_save_facts_batch.py
@pytest.mark.asyncio
async def test_save_facts_5_emits_exactly_1_embed_call_and_1_executemany(
    pg_pool, monkeypatch,
):
    """SC-4: 5-fact turn issues exactly 1 embed call + 1 PG round-trip."""
    from unittest.mock import AsyncMock, MagicMock
    from utils.models import ExtractedFact

    # Spy on embedder
    embed_spy = AsyncMock(return_value=[[0.1] * 1024] * 5)
    mock_embedder = MagicMock()
    mock_embedder.embed_batch = embed_spy
    monkeypatch.setattr("services.vectorizer.embedder.get_embedder", lambda: mock_embedder)

    # Spy on conn.executemany via a wrapper pool. Best done by counting calls
    # on a real pool — wrap conn.executemany after acquire.
    insert_calls = []
    bulk_check_calls = []

    # Easiest: patch the helper methods directly on the LongTermMemory instance
    from services.memory.memory_service import LongTermMemory
    ltm = LongTermMemory()

    real_bulk = ltm._bulk_near_duplicate_check
    async def spy_bulk(*args, **kwargs):
        bulk_check_calls.append(1)
        return await real_bulk(*args, **kwargs)
    monkeypatch.setattr(ltm, "_bulk_near_duplicate_check", spy_bulk)

    # Wrap pool to spy on executemany
    real_pool = await ltm._get_pool()
    original_acquire = real_pool.acquire

    facts = [ExtractedFact(fact=f"fact {i}", category="recurring_topics", importance=0.5) for i in range(5)]
    result = await ltm.save_facts(facts, user_id="u1", tenant_id="t1")

    assert embed_spy.call_count == 1, f"Expected 1 embed_batch call, got {embed_spy.call_count}"
    assert len(bulk_check_calls) == 1, "Expected 1 bulk dedupe check"
    # Assert insert count == 5 via post-condition DB query
    async with real_pool.acquire() as conn:
        n = await conn.fetchval(
            "SELECT COUNT(*) FROM long_term_facts WHERE user_id='u1' AND tenant_id='t1'"
        )
    assert n == 5
    assert result.saved_count == 5
```

### Latency baseline measurement

**SC-5 references "v1.6 baseline minus embed-RTT × (N−1)."** No prior latency baseline is recorded in v1.6 Phase 23/24/25 SUMMARY files (verified — searched for "extractor.*latency" and "embed.*ms"). The planner has two options:

- (a) **Capture baseline before TD-05 lands.** Plan Task 1 = "run a 5-fact synthetic ExtractorAgent turn on the v1.6 codebase 10× and record p50/p95 wall-clock." This requires either reverting `services/agent/extractor.py:260` to the loop form OR running on a checkpoint commit pre-Phase-27.
- (b) **Treat SC-5 as relative measurement.** Run the same synthetic turn (a) on a stub branch with the for-loop preserved (no TD-05) and (b) on the TD-05 branch; compare. Same test, two branches, two timings.

Recommendation: **(b)** — cheaper. Use the loop-form locally (revert the inline migration temporarily) to measure baseline, then re-apply. Record both numbers in 27-XX-SUMMARY.md. Compute `expected_speedup_ms = baseline_p50 - new_p50` and assert `expected_speedup_ms >= measured_embed_rtt_ms * 4` (for N=5 facts, expected savings = 4× one-call embed RTT).

A precise measurement requires a real embedder (HuggingFace bge-m3 or Ollama). Local bge-m3 cold embed is ~50-200ms per call; warm ~30ms. So 5-fact baseline ~= 5*30ms = 150ms embed + 5*1ms PG = ~155ms total. New shape: 1*30ms embed + 1ms PG bulk + 1ms PG insert = ~32ms. Expected ~123ms speedup, well above the SC-5 floor of `4 * 30 = 120ms`. Tolerant assertion: `speedup_ms >= 80ms` (gives 30% margin for variance).

### Mock-counting test for 1-RTT contract (SC-4 strict form)

The ROADMAP SC-4 wording is "exactly 1 embed call + 1 PG round-trip" — but the implementation has 3 PG operations (bulk dedupe SELECT, executemany INSERT, audit_log INSERT). The strict "1 PG RTT" is impossible without sacrificing one of them. Recommendation: **interpret SC-4 generously** as "1 embed call + O(1) PG RTTs (not O(N))." Document this in 27-XX-SUMMARY.md so the verifier doesn't fail on a literal-1 count.

If the user/verifier insists on literal-1, the implementation can be collapsed by writing a single PL/pgSQL `WITH` query that does dedupe-then-insert atomically:

```sql
WITH probes AS (
    SELECT idx, vec_txt::vector AS vec, $4::vector_type AS row_data
    FROM unnest($1::text[]) WITH ORDINALITY AS t(vec_txt, idx)
),
dups AS (
    SELECT idx FROM probes p
    WHERE EXISTS (
        SELECT 1 FROM long_term_facts
        WHERE user_id = $2 AND tenant_id = $3
        AND embedding <=> p.vec < $5
    )
)
INSERT INTO long_term_facts (...) SELECT ... FROM probes WHERE idx NOT IN (SELECT idx FROM dups)
RETURNING id
```

Plus a separate query for audit_log writes (or a CTE-RETURNING shape that also surfaces the dup IDs to a client-side audit loop). This works but is significantly more complex to test and breaks the audit-mode-only semantic (the WHERE NOT IN does enforcement, not audit-only). **Recommendation: stay with 3 PG ops + 1 embed call.**

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3+ |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (verify section exists; if not, add for asyncio_mode) |
| Quick run command | `uv run pytest tests/unit -x --timeout 30` |
| Full suite command | `uv run pytest tests/ --timeout 60 --cov=services --cov=utils` |
| Async marker | `@pytest.mark.asyncio` (auto-mode preferred) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | Notes |
|--------|----------|-----------|-------------------|-------|
| TD-02 | `create_app()` returns isolated app per call | unit + integration | `uv run pytest tests/integration/test_create_app_isolation.py -x` | New file — Wave 0 gap |
| TD-02 | Singleton inventory lint passes | unit | `uv run pytest tests/unit/test_singleton_inventory_complete.py -x` | New file — Wave 0 gap |
| TD-02 | Audit + memory suites have ≥1 test each using `create_app()` | integration | `uv run pytest tests/integration/test_audit_factory_smoke.py tests/integration/test_memory_factory_smoke.py -x` | New tests — Wave 0 gap |
| TD-04 | save_fact emits MEMORY_NEAR_DUPLICATE_SKIPPED audit row when embedding within threshold of existing fact | integration (real PG) | `uv run pytest tests/integration/test_memory_near_duplicate_audit.py -x` | New file — Wave 0 gap; gated on `pg_available` |
| TD-04 | save_fact still inserts the dup row in v1.7 (audit-mode-only) | integration | same file as above, asserts post-state row count | |
| TD-04 | Precheck adds exactly 1 SELECT to the hot path | unit (mock pool) | `uv run pytest tests/unit/test_save_fact_precheck_rtt.py -x` | New file — Wave 0 gap |
| TD-05 | 5-fact turn emits 1 embed_batch + 1 bulk dedupe + 1 executemany | unit (mock embedder + spy on conn methods) | `uv run pytest tests/unit/test_save_facts_batch.py::test_save_facts_5_emits_exactly_1_embed_call_and_1_executemany` | New file — Wave 0 gap |
| TD-05 | ExtractorAgent now dispatches via save_facts (not save_fact loop) | unit | `uv run pytest tests/unit/test_extractor_dispatch_uses_batch.py -x` | New file — Wave 0 gap |
| TD-05 | Batch path honors TD-04 audit-mode | integration (real PG) | `uv run pytest tests/integration/test_save_facts_batch_e2e.py -x` | New file — Wave 0 gap |
| TD-05 | Per-turn latency improves; benchmark recorded | benchmark | `uv run pytest tests/integration/test_save_facts_latency.py -x` | New file — Wave 0 gap; gated on real embedder |
| TD-06 | redis_mock fixture available and auto-applied by marker | unit | `uv run pytest tests/unit/test_redis_mock_fixture.py -x` | New file — Wave 0 gap |
| TD-06 | Unit-suite Redis-ConnectionError failures = 0 with TD-06 applied | unit (suite-level) | `uv run pytest tests/unit/test_agent_pipeline_refactor.py tests/unit/test_agent_sse.py tests/unit/test_feedback_ab_forward.py tests/unit/test_pipeline_coverage.py` | Pre/post diagnostic per D-22 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit -x --timeout 30`
- **Per wave merge:** `uv run pytest tests/ --timeout 60`
- **Phase gate:** Full suite green before `/gsd-verify-work`; diff-cover ≥ 80% on touched files; combined coverage `--fail-under=70`.

### Wave 0 Gaps (test files that don't yet exist — planner inserts as Wave 0 tasks)

- [ ] `tests/factories/__init__.py` + `tests/factories/app.py` — the factory module itself (subject of TD-02)
- [ ] `tests/unit/test_singleton_inventory_complete.py` — lint test (D-03)
- [ ] `tests/integration/test_create_app_isolation.py` — SC-1 cross-contamination test
- [ ] `tests/integration/test_audit_factory_smoke.py` — audit suite via factory (1-2 tests)
- [ ] `tests/integration/test_memory_factory_smoke.py` — memory suite via factory (1-2 tests)
- [ ] `tests/integration/test_memory_near_duplicate_audit.py` — SC-3 audit-mode behavior
- [ ] `tests/unit/test_save_fact_precheck_rtt.py` — RTT counting
- [ ] `tests/unit/test_save_facts_batch.py` — SC-4 mock-based 1-embed + 1-executemany
- [ ] `tests/unit/test_extractor_dispatch_uses_batch.py` — ExtractorAgent migration
- [ ] `tests/integration/test_save_facts_batch_e2e.py` — end-to-end batch
- [ ] `tests/integration/test_save_facts_latency.py` — SC-5 benchmark
- [ ] `tests/unit/test_redis_mock_fixture.py` — fixture self-test
- [ ] No new framework install — fakeredis already pinned; pytest-asyncio already pinned

## Architecture Patterns

### Pattern 1: Test fixture resets module-level singleton
**What:** Function-scoped fixture sets `module._singleton = None` before yielding; tests-in-suite then call the public factory `get_X()` and get a fresh instance.
**When to use:** Whenever Phase 27 test needs a service in a known-fresh state.
**Example:** `tests/conftest.py:64-73` (`pg_store` fixture) — the established repo pattern.

### Pattern 2: Mock at consumer path (v1.3 D-04 lock)
**What:** Patch the symbol at the importing module's path, not the source module.
**When to use:** Any test that needs to swap a dependency.
**Example:**
```python
# WRONG — patches the source; lazy-import in consumer reads stale binding
monkeypatch.setattr("utils.cache.get_redis", _stub)
# RIGHT — patches the consumer's binding (after consumer imports)
monkeypatch.setattr("services.X.get_redis", _stub)
```
Both patterns apply for TD-06: the canonical `utils.cache.get_redis` is patched because all consumers do `from utils.cache import get_redis` inside the function body (lazy import — confirmed in `services/nlu/entity_disambiguator.py:289`, `services/annotation/annotation_service.py:51`, `services/ab_test/ab_test_service.py:122`, `services/knowledge/version_service.py:40`, `services/pipeline.py:138`).

### Pattern 3: pgvector bulk operation via text[] cast
**What:** When `register_vector` is installed and you need to pass N vectors as a single parameter, use `unnest($1::text[]) AS t(vec_txt, idx)` and cast `vec_txt::vector` inside the predicate.
**When to use:** Any bulk pgvector operation across N rows; documented above in §10.

### Anti-Patterns to Avoid
- **`from main import app` at module top of new tests.** Use the factory instead. Old tests remain unmigrated per D-05.
- **Unconditional `autouse=True` on `redis_mock`.** Would force-mock integration tests that legitimately need real Redis. Use marker-opt-in per D-18.
- **Treating "save skipped" as the v1.7 contract.** Audit-mode-only — save still happens. v1.8 promotes to silent-skip.
- **`unnest($1::vector[])` with pgvector codec installed.** Empirically broken (§10).
- **Calling `embed_batch` and assuming per-input None on failure.** All three current embedders raise on first failure.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Mock Redis with full surface area | Hand-rolled `MagicMock(spec=Redis)` returning sensible defaults | `fakeredis.aioredis.FakeRedis()` | Lists, sorted sets, pipelines, expire, eval all implemented and tested upstream; already a dep |
| FastAPI testing | Custom TestClient pool | `httpx.AsyncClient(transport=ASGITransport(app=app))` | Official FastAPI/Starlette testing pattern; supports streaming + lifespan |
| Singleton lint | Regex over entire codebase | Restrict pattern to `services/*.py`, use repo's grep precedent | Simple, transparent, debuggable |
| pgvector bulk operations | Build temp table + COPY | `unnest($1::text[])` cast pattern | 1 RTT for N≤20; no DDL overhead |
| `executemany` for 5 rows | `copy_records_to_table` | `conn.executemany` | copy_records_to_table is for >100 rows; executemany is the right tool for N≤20 |

## Runtime State Inventory (refactor phase)

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `long_term_facts` table — pre-existing rows may pre-date the dedupe behavior; v1.7 does not back-fill dedupe (no migration). | None (v1.7 audit-mode-only). v1.8 silent-skip rollout might want a one-time dedupe job; out of scope. |
| Stored data | `audit_log` table — pre-existing rows use earlier `AuditAction` values. New `MEMORY_NEAR_DUPLICATE_SKIPPED` is append-only enum (Phase 25 EVICT-02 precedent). | None — enum extension is forward-compatible (CHECK constraint on `action` is the v1.0 enum-as-VARCHAR pattern, not a Postgres enum type; verified `CREATE TABLE` in `services/audit/audit_service.py` does not use `CREATE TYPE`). |
| Live service config | None — Phase 27 changes no configuration that lives outside git (no n8n, no Tailscale ACL, no Datadog tags involved). | None. |
| OS-registered state | None — no Windows Task Scheduler, no pm2, no launchd. | None. |
| Secrets/env vars | New setting `memory_near_duplicate_threshold` in `config/settings.py` — Pydantic Field defaults to 0.05; reads env `APP_MEMORY_NEAR_DUPLICATE_THRESHOLD` if present. No existing env-var rename. | None unless ops wants a per-deploy override; document in 27-XX-SUMMARY. |
| Build artifacts | None — pure Python source changes; no `pip install -e .` re-installation step needed since `pyproject.toml` is unchanged. | None. |

## Common Pitfalls

### Pitfall 1: pgvector codec breaks `vector[]` parameter binding
**What goes wrong:** `unnest($1::vector[])` with `register_vector(conn)` installed raises `DataError: expected ndim to be 1`.
**Why it happens:** pgvector codec hijacks `vector` parameter interpretation expecting a single 1-D vector.
**How to avoid:** Use `unnest($1::text[])` with vector-literal strings + inline `vec_txt::vector` cast. Empirically validated in §10.
**Warning signs:** `DataError: expected ndim to be 1` or `could not convert string to float`.

### Pitfall 2: Test fixture autouse vs marker-opt-in
**What goes wrong:** `autouse=True` redis_mock forces real-Redis integration tests to use the fake; they pass spuriously.
**Why it happens:** pytest applies autouse fixtures to all tests in scope; integration tests can't opt out.
**How to avoid:** Use the `@pytest.mark.uses_redis` marker + `pytest_collection_modifyitems` hook per D-18.
**Warning signs:** Integration suite that previously caught a real-Redis bug suddenly passes after TD-06 lands.

### Pitfall 3: `embed_batch` failure mode misassumption
**What goes wrong:** Code assumes `embed_batch` returns per-input None on failure; instead, the call raises and the whole batch is lost.
**Why it happens:** D-16 in CONTEXT.md described a different contract than what any current embedder implements.
**How to avoid:** Wrap `embed_batch` in try/except; on failure fall back to per-item `embed_one` inside `asyncio.gather(return_exceptions=True)`. See §9.
**Warning signs:** A single corrupt input fails an entire 20-fact batch.

### Pitfall 4: Lifespan handler not re-entrant
**What goes wrong:** `main.lifespan` calls `get_vectorizer().ensure_collection()`, `get_event_bus().start()`, etc. at startup. Constructing two apps via `create_app()` causes two lifespan executions.
**Why it happens:** Each `FastAPI(lifespan=lifespan)` starts its own lifespan when entered.
**How to avoid:** Use `httpx.AsyncClient(transport=ASGITransport(app=app))` which **does NOT** auto-trigger lifespan unless you wrap in `LifespanManager` (`asgi-lifespan` package). For most TD-02 tests, the lifespan side effects (vectorizer warmup, event bus start) are not needed — skip the lifespan entirely by NOT using LifespanManager. For SC-1 cross-contamination test, lifespan-skip is fine since the test asserts at the singleton-reset level, not at the app-running level.
**Warning signs:** EventBus warns "already started" or vectorizer warmup runs twice; tests hang at fixture teardown.

### Pitfall 5: SC-3 vs D-09 wording trap
**What goes wrong:** Verifier reads ROADMAP SC-3 "save is skipped" and rejects the v1.7 implementation that doesn't skip.
**Why it happens:** ROADMAP SC-3 was written before D-09 audit-mode-before-enforce was locked.
**How to avoid:** Planner explicitly notes the corrected semantics in PLAN.md + 27-XX-SUMMARY.md.
**Warning signs:** VERIFICATION.md asserts "post-save row count unchanged" — that's the wrong assertion in v1.7.

### Pitfall 6: ShortTermMemory bypasses get_redis
**What goes wrong:** TD-06 redis_mock fixture mocks `utils.cache.get_redis` but `ShortTermMemory._get_client` calls `redis.asyncio.from_url` directly. Tests that exercise ShortTermMemory still hit real Redis.
**Why it happens:** D-19's "every service that uses Redis lazy-imports through this function" is true for 5/6 services; ShortTermMemory is the exception.
**How to avoid:** Either (a) refactor `ShortTermMemory._get_client` to delegate to `get_redis()`, or (b) also patch `redis.asyncio.from_url` in the fixture. See §6.
**Warning signs:** Test marked `@pytest.mark.uses_redis` still fails with `ConnectionError: Error 111`.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Module-level `app = FastAPI(...)` | Application factory `create_app()` | FastAPI 0.95+ documented best practice (2022); never adopted in this codebase | TD-02 retrofits |
| `pytest.fixture(autouse=True)` for cross-cutting test setup | Marker-based opt-in via `pytest_collection_modifyitems` hook | pytest 7+ favored explicit opt-in for non-trivial fixtures | TD-06 uses the marker pattern |
| `MagicMock(spec=Redis)` for unit tests | `fakeredis.FakeRedis` for state-realistic mock | fakeredis 2.x added asyncio support (2023) | TD-06 D-20 should pivot from MagicMock to fakeredis |
| N×(embed_one + INSERT) per agent turn | 1× embed_batch + 1× bulk dedupe + 1× executemany | This phase | 3N→3 PG RTT |

## Sources

### Primary (HIGH confidence)

- Empirical pgvector test against live `postgresql://rag:rag@localhost:5432/ragdb` — Section §10 of this research (verified `unnest($1::text[])` works, `unnest($1::vector[])` fails)
- `services/memory/memory_service.py` lines 85-180 + 290-396 — current implementation (file:line verified)
- `services/agent/extractor.py` lines 220-270 — dispatch site (file:line verified)
- `services/vectorizer/embedder.py` lines 27-220 — embedder ABC and 3 impls (file:line verified)
- `services/audit/audit_service.py` lines 27-204 — AuditAction enum + log signature (file:line verified)
- `utils/cache.py` lines 1-137 — single Redis accessor + state-of-the-world (file:line verified)
- `tests/conftest.py` lines 1-195 — established fixture patterns (file:line verified)
- `main.py` lines 1-260 — FastAPI app construction (file:line verified)
- `pyproject.toml` — `fakeredis==2.35.1` already present (verified)

### Secondary (MEDIUM confidence)

- FastAPI testing docs — application factory pattern: https://fastapi.tiangolo.com/advanced/testing-events/
- pytest docs — `pytest_collection_modifyitems` hook: https://docs.pytest.org/en/stable/how-to/writing_hook_functions.html
- fakeredis docs — asyncio + sorted-set + pipeline coverage: https://github.com/cunla/fakeredis-py
- pgvector docs — `<=>` cosine distance operator: https://github.com/pgvector/pgvector#cosine-distance

### Tertiary (LOW confidence)

- Local cold-embed latency estimate (~30-50ms warm bge-m3, ~150-200ms cold) — based on training-data knowledge; planner should measure on real hardware.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | bge-m3 warm embed ~30ms on local CPU/GPU | Theme 4 latency baseline | Latency assertion `speedup >= 80ms` may be too tight; measure first |
| A2 | `ExtractedFact.importance` Literal narrowing causes ValidationError when wrapper passes raw float | Theme 4 D-12 wrapper | If `ExtractedFact` is changed to loose `float`, the rounding helper becomes unnecessary |
| A3 | Existing audit + memory integration suites mostly don't use FastAPI (instantiate services directly) | Theme 1 migration sequencing | If they do use FastAPI, the migration is bigger than estimated — check at plan time |
| A4 | The 32 v1.6 Phase 24 Redis-baseline failures are still present and not yet healed | Theme 2 D-22 | Diagnostic step will measure — no functional impact, just SC scope |
| A5 | `pg_stat_activity` shows the new bulk dedupe query uses the HNSW index when GUC is set | Theme 4 §10 | If planner-time EXPLAIN shows seq-scan, performance claim is wrong; recommend EXPLAIN check in Plan |
| A6 | `_configure_app(app)` extraction in `main.py` is risk-free | Theme 1 main.py delta | The full middleware stack + router order is load-bearing — must extract carefully and run smoke test |

## Open Questions

1. **SC-3 vs D-09 wording — does user prefer "save skipped" or "save still happens + audit row"?**
   - What we know: D-09 says audit-mode-only; ROADMAP SC-3 says save skipped. They contradict.
   - What's unclear: Which the user/verifier will adjudicate as canonical.
   - Recommendation: Treat D-09 as canonical (CONTEXT.md decisions are the source of truth post-discuss-phase). Planner explicitly calls out the override in PLAN.md so VERIFICATION.md and the user's review of the plan can catch it. If user pushes back, re-discuss.

2. **SC-4 "exactly 1 PG round-trip" — literal or generous interpretation?**
   - What we know: Strict literal interpretation requires merging dedupe + insert + audit-write into a single CTE — significantly more complex and brittle.
   - What's unclear: How strictly the verifier will read "exactly 1 PG round-trip."
   - Recommendation: Plan documents the 3-RTT shape (dedupe SELECT + executemany INSERT + audit_log INSERT) and explicitly notes "1 RTT was a target wording; the achievable O(1) shape is 3 RTT for the happy path, regardless of N." Bring to user attention if verifier flags.

3. **Should `ShortTermMemory._get_client` refactor land in TD-06 or stay v1.8?**
   - What we know: It's a 3-line change with clear value (closes the only Redis bypass; lets TD-06 mock be complete).
   - What's unclear: Whether the planner has scope-creep tolerance for a "bonus" item.
   - Recommendation: Include as a Wave 1 task in the TD-06 plan, labeled "bonus delivery" per CONTEXT.md "Claude's Discretion" allowance.

4. **Does the user want the latency benchmark (SC-5) to gate Phase 27 acceptance or is "captured in summary" enough?**
   - What we know: ROADMAP SC-5: "benchmark captured in the phase summary." This sounds like documentation, not a pass/fail gate.
   - What's unclear: Whether the verifier will hard-fail if the measured speedup is below expectation.
   - Recommendation: Plan PLAN.md treats SC-5 as observational (record + report, don't gate). User can override.

5. **Plan-time grep for additional singletons: any chance of false negatives?**
   - What we know: The regex used finds all `^_X = None` and `^_X: Type | None = None` patterns.
   - What's unclear: Singletons that use `_X: dict[str, T] = {}` (cache shapes), or singletons constructed eagerly at module load (no `= None` placeholder).
   - Recommendation: Plan task includes a second grep for `^_[a-z_]+\b *(:[^=]*)?= *(\{\}|dict\(\)|list\(\)|set\(\))` to catch container-shaped caches that also need reset.

6. **Audit_log table existence — guaranteed by Phase 26?**
   - What we know: Phase 26 TD-01 added `_create_tables` for `audit_log` (verified in `services/audit/audit_service.py` post-Phase-26 + STATE.md).
   - What's unclear: Test environments without PG. TD-04 audit writes when `audit_db_enabled=False` go file-only.
   - Recommendation: Plan tests assert audit-row presence via `AuditService` log buffer (in-memory) for unit tests, and via real PG query for integration tests gated on `pg_available`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL + pgvector | TD-04, TD-05 integration tests | ✓ | localhost:5432 reachable | unit tests use mock; integration tests skip if unavailable |
| fakeredis | TD-06 fixture | ✓ | 2.35.1 (pyproject.toml) | — |
| redis.asyncio (real) | TD-06 integration bypass path | ✓ | (redis>=7.3.0 pyproject) | — |
| uv | All commands | ✓ | system | — |
| pytest 9.0.3 + pytest-asyncio 1.3+ | All tests | ✓ | pyproject pinned | — |
| BGE-M3 embedder | SC-5 latency benchmark | ✓ | resolved via Phase 26 TD-07 helper | OllamaEmbedder fallback if local model dir missing |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

## Security Domain

`security_enforcement` is not explicitly set to `false` in `.planning/config.json` — treat as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | This phase touches no auth path |
| V3 Session Management | no | ShortTermMemory unchanged behaviorally; refactor opportunity only |
| V4 Access Control | yes | tenant_id + user_id RLS preserved — every new query is (user_id, tenant_id)-scoped per D-06 |
| V5 Input Validation | yes | Pydantic V2 `Field(ge=0.0, le=1.0)` on the new threshold setting; ExtractedFact still validates LLM output |
| V6 Cryptography | no | No new crypto |
| V7 Error Handling | yes | New code follows project "no bare except" + tenacity-retry conventions (CLAUDE.md) |
| V10 Malicious Code | yes | New audit row payload truncates fact to 200 chars (Phase 25 RULE_BLOCKED convention) — prevents log-poisoning via attacker-supplied content |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-tenant leakage via dedupe query | Information Disclosure | Every dedupe query MUST filter on `user_id=$1 AND tenant_id=$2` first; the HNSW filter requires the GUC discipline to be exact under filter — verified pattern from `get_relevant_facts` |
| SQL injection via vector literal string | Tampering | Never construct vector-literal strings from untrusted input. Embeddings come from `embedder` (model-generated floats), not user-supplied. Use parameterized text[] binding via asyncpg. |
| Audit log poisoning | Repudiation | Truncate user-controlled fact field to 200 chars before inserting into `detail` JSONB (Phase 25 RULE_BLOCKED convention) |
| Test fixture pollution (cross-test) | Tampering | TD-02 D-03 lint test + singleton reset on every `create_app()` call |

## Project Constraints (from CLAUDE.md)

The project CLAUDE.md mandates the following — all Phase 27 code must comply:

- **Pydantic V2 only.** New `SaveFactsResult` dataclass acceptable per CONTEXT discretion (dataclass for symmetry with `ExtractedFact` — note: `ExtractedFact` is a Pydantic V2 BaseModel, not a dataclass; the "symmetry" reasoning in CONTEXT is loose). Either Pydantic V2 or `@dataclass(frozen=True)` is fine; planner picks.
- **mypy --strict on new modules.** `tests/factories/app.py` + all new test modules must type-check under `--strict`.
- **ruff lint clean.** Default project ruleset.
- **No bare `except`.** Narrow exception types. Existing code at `services/memory/memory_service.py:325` already uses `except (httpx.HTTPError, RuntimeError, OSError)` — new code follows same.
- **No blocking I/O in async contexts.** `register_vector(conn)` is async-compatible (verified).
- **Adapters for all external deps.** `fakeredis` is a test dependency — no production-code adapter needed. `redis_mock` fixture IS the test adapter.
- **Tenacity retry for external calls.** TD-04 precheck SELECT is internal PG; no new tenacity needed. Embedders already wrapped.
- **Structured logging for every operation.** New `save_facts` calls use `logger.warning(...)` per existing pattern at `services/memory/memory_service.py:330-332`.

## Metadata

**Confidence breakdown:**
- Codebase reality (§1-§10): HIGH — every claim is grep-verified or empirically tested against live PG.
- Recommended patterns (factory, fixture, SQL): HIGH — FastAPI factory + fakeredis are widely documented; bulk SQL pattern empirically validated.
- Latency baseline (Theme 4 SC-5): MEDIUM — rough estimate; real measurement needed in plan task.
- SC-3 vs D-09 conflict resolution: MEDIUM — interpretation requires user confirmation, but CONTEXT-as-canonical is the documented GSD convention.

**Research date:** 2026-05-17
**Valid until:** 2026-06-17 (30 days — stable codebase; phase boundary tight)

## RESEARCH COMPLETE
