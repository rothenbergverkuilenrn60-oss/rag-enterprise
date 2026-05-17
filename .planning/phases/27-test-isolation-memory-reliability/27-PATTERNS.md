# Phase 27: Test Isolation + Memory Reliability — Pattern Map

**Mapped:** 2026-05-17
**Files analyzed:** 17 new/modified (4 source + 13 tests)
**Analogs found:** 16 / 17 (1 no-analog: `tests/factories/app.py` is greenfield)

> Per-file `file:line` citations let planner quote shapes verbatim. RESEARCH.md is authority on TD-* decisions; this file is the mapping layer.

---

## File Classification

| File (new/modified) | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `main.py` — extract `_configure_app`, add `create_app` | bootstrap | request-response | self (surgical) | refactor |
| `LongTermMemory.save_fact` (modify) | service | CRUD write+precheck | `get_relevant_facts` (`memory_service.py:290-357`) | exact mirror |
| `LongTermMemory.save_facts` (new) | service | CRUD batch | `vector_store.py:264` (executemany) + `save_fact` | role-match |
| `ShortTermMemory._get_client` (modify) | service | request-response | `utils/cache.py:19-37` (`get_redis`) | exact delegate |
| `extractor.py::_run_and_persist` | dispatch | event-driven | self (`extractor.py:247-266`) | refactor |
| `AuditAction` enum (append) | model | enum extension | `MEMORY_EVICT` (`audit_service.py:42`) | exact |
| `config/settings.py` (add threshold) | config | n/a | `memory_facts_cap_per_user` (`settings.py:498`) | exact |
| `tests/factories/__init__.py` + `app.py` (new) | test-infra | n/a | none — greenfield | **no analog** |
| `tests/conftest.py` extend | test-infra | n/a | `pg_pool`/`pg_store` (`conftest.py:36-79`) | exact |
| `tests/unit/test_app_factory.py` | test | unit | `tests/unit/test_memory_pool.py:14-79` | role-match |
| `tests/unit/test_parallel_contamination.py` | test | unit | `test_memory_forget_e2e.py:49-88` | role-match |
| `tests/unit/test_redis_mock_fixture.py` | test | unit | `test_memory_service.py:18-86` | exact |
| `tests/unit/test_singleton_inventory_complete.py` | test (lint) | unit | none in repo (RESEARCH §1) | role-match |
| `tests/unit/memory/test_save_fact_precheck.py` | test | unit | `test_memory_save_fact.py:87-122` | exact |
| `tests/unit/memory/test_save_fact_precheck_failure.py` | test | unit | `test_memory_save_fact.py:128-188` | exact |
| `tests/unit/memory/test_save_facts_batch.py` | test | unit | `test_memory_save_fact.py` + `test_audit_service_pool.py:36-66` | role-match |
| `tests/unit/memory/test_save_facts_batch_dedupe.py` | test | unit | same + RESEARCH §10 | role-match |
| `tests/unit/memory/test_save_facts_embed_batch_fallback.py` | test | unit | `test_memory_save_fact.py:128-163` | role-match |
| `tests/integration/audit/test_audit_suite_factory_migrated.py` | test | integration | `test_audit_log_auto_create.py:17-61` | exact |
| `tests/integration/memory/test_memory_suite_factory_migrated.py` | test | integration | `test_pgvector_filtered_recall.py` + `test_lifespan_shutdown_closes_pools.py` | role-match |
| `tests/benchmark/test_extractor_latency.py` | test | benchmark | `test_recall_latency.py:17-103` | exact |

---

## Source-File Pattern Assignments

### `main.py` — extract `_configure_app` + `create_app` shim

**Authority:** RESEARCH §2 lines 140-150 + §Theme 1 lines 308-388.

**Current import-time sequence** (`main.py`): L169 `app = FastAPI(... lifespan=lifespan)`; L181-183 `state.limiter`, `add_exception_handler`, `SlowAPIMiddleware`; L191-197 `CORSMiddleware`; L203/L292/L366 `@app.middleware("http")` decorators (trace/rate_limit/auth); L334 `@app.exception_handler(Exception)`; L351 `@app.get("/metrics")`; router/static mounts after.

**Delta:** extract L181→end into `def _configure_app(app: FastAPI) -> None`. Decorator-bound middleware converts to plain functions then `app.middleware("http")(fn)` — required so they bind to whatever FastAPI instance `_configure_app` receives. `create_app()` does `FastAPI(lifespan=lifespan)` → `_configure_app(app)`. Module-level `app` keeps `_configure_app(app)` call for prod parity.

**Pitfall (RESEARCH lines 1073-1077):** lifespan side effects NOT re-entrant. `httpx.AsyncClient(transport=ASGITransport(app=...))` skips lifespan by default — fine for SC-1.

---

### `LongTermMemory.save_fact` — TD-04 precheck

**Analog:** `get_relevant_facts` at `memory_service.py:290-357` (exact mirror).

**Excerpt to reuse** (`memory_service.py:336-352`):
```python
async with pool.acquire() as conn:
    async with conn.transaction():
        ef = int(getattr(settings, "pgvector_ef_search_filtered", 200))
        await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
        await conn.execute(f"SET LOCAL hnsw.ef_search = {ef}")
        rows = await conn.fetch(
            """SELECT fact FROM long_term_facts
               WHERE user_id=$1 AND tenant_id=$2
               ORDER BY embedding <=> $3::vector, importance DESC, created_at DESC
               LIMIT $4""",
            user_id, tenant_id, q_vec, limit,
        )
```

**Lazy-import discipline** (`memory_service.py:316-320`): `import httpx; from config.settings import settings; from services.vectorizer.embedder import get_embedder` — inside method body. Apply identically.

**Current `save_fact` two-try shape** (`memory_service.py:359-396`): embed → INSERT. TD-04 inserts BETWEEN: precheck SELECT + audit emit. Order: embed → precheck → audit → INSERT.

**Failure-mode = fail-OPEN** (mirror `get_relevant_facts:353-357`): `asyncpg.PostgresError` on precheck → log warning, skip precheck, INSERT proceeds. Honors D-09.

**Narrow-exception tuple for embed step** (`memory_service.py:325-329`): `(httpx.HTTPError, RuntimeError, OSError)`. No new exception classes.

---

### `LongTermMemory.save_facts` (new) — TD-05 batch

**Analog A (executemany):** `services/vectorizer/vector_store.py:264` — only existing executemany in repo. Pattern: `rows: list[tuple]`, then `await conn.executemany(SQL, rows)`.

**Analog B (wrapper):** `save_fact` becomes `await self.save_facts([fact])` per D-12.

**Bulk dedupe SQL** (RESEARCH §10 empirically validated — pgvector codec quirk forces `text[]` not `vector[]`):
```python
vec_literals = ['[' + ','.join(str(x) for x in v) + ']' for v in embeddings]
# SQL:
"""SELECT (idx - 1) AS zero_idx
   FROM unnest($1::text[]) WITH ORDINALITY AS t(vec_txt, idx)
   WHERE EXISTS (
       SELECT 1 FROM long_term_facts
       WHERE user_id = $2 AND tenant_id = $3
       AND embedding <=> vec_txt::vector < $4
   )"""
```
**MUST inline `::vector` cast** inside EXISTS. Outer param binds as `list[str]`.

**embed_batch fallback (D-16 correction per RESEARCH §9):** current `OllamaEmbedder.embed_batch` (`embedder.py:61-70`) raises `RuntimeError` on first failure — does NOT return None-per-input. Wrap in try/except, fall back to `asyncio.gather(*embed_one calls, return_exceptions=True)`, treat exceptions as None.

**`SaveFactsResult` placement:** module top-level alongside `ConversationTurn`/`UserProfile` (`memory_service.py:43-81`). Frozen `@dataclass`. Fields: `saved_count`, `skipped_near_duplicates`, `skipped_embed_failures`.

**INSERT SQL (preserve verbatim, `memory_service.py:389-393`):**
```sql
INSERT INTO long_term_facts (user_id, tenant_id, fact, source_doc, importance, embedding)
VALUES ($1,$2,$3,$4,$5,$6::vector)
```

---

### `ShortTermMemory._get_client` — TD-06 bonus delegate

**Analog:** `utils/cache.py:19-37` (`get_redis`).

**Current shape** (`memory_service.py:98-108`): direct `from redis.asyncio import from_url`. The one service bypassing `get_redis()` (RESEARCH §6).

**3-line replacement:**
```python
async def _get_client(self):
    if self._client is None:
        from utils.cache import get_redis
        self._client = await get_redis()
    return self._client
```

**Impact:** with delegate, `redis_mock` fixture needs one patch (`utils.cache.get_redis`); without, also needs `redis.asyncio.from_url` patch.

---

### `extractor.py::_run_and_persist` — D-17 inline migration

**Current loop** (`extractor.py:255-266`):
```python
mem = get_memory_service()
for f in facts:
    await mem._long.save_fact(
        user_id=user_id, tenant_id=tenant_id,
        fact=f.fact, source_doc="", importance=f.importance,
    )
```

**Replacement (single call):**
```python
mem = get_memory_service()
await mem._long.save_facts(facts, user_id=user_id, tenant_id=tenant_id, source_doc="")
```

**Preserved:** lazy `get_memory_service` import, `MemoryFactWriteError`→`log_task_error` callback path (`extractor.py:269`), `dispatch_extraction` signature.

---

### `AuditAction` enum — append `MEMORY_NEAR_DUPLICATE_SKIPPED`

**Current tail** (`audit_service.py:40-42`):
```python
# Phase 25 — D-2.1 — GDPR forget API + eviction job
MEMORY_FORGET     = "MEMORY_FORGET"
MEMORY_EVICT      = "MEMORY_EVICT"
```

**Add AFTER `MEMORY_EVICT`:**
```python
# Phase 27 — TD-04 — near-duplicate audit-mode-only metric (D-09: save NOT skipped in v1.7)
MEMORY_NEAR_DUPLICATE_SKIPPED = "MEMORY_NEAR_DUPLICATE_SKIPPED"
```

**DDL impact:** zero. `action VARCHAR(64)` (`audit_service.py:147-160`) accepts any string. No Postgres enum type.

---

### `config/settings.py` — add `memory_near_duplicate_threshold`

**Analog** (`settings.py:498`): `memory_facts_cap_per_user: int = Field(default=500, ge=1)`.

**Add immediately after for section locality:**
```python
# Phase 27 / TD-04 — cosine near-duplicate guard threshold.
# v1.7 audit-mode-only (D-09): save still happens; row emitted for ops visibility.
# Override via env APP_MEMORY_NEAR_DUPLICATE_THRESHOLD=<float>.
memory_near_duplicate_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
```

---

### `tests/factories/app.py` (new — RESEARCH §Theme 1 lines 308-388 is authoritative)

- Module tuple `_SINGLETON_INVENTORY: tuple[tuple[str, str], ...]` — ~32 entries from RESEARCH §1 (skip 4 non-services: `_tiktoken_enc`, `_anthropic_rate_limit_cls`, `_anthropic_overload_cls`, `_sem`).
- `_reset_singletons()`: `importlib.import_module` + `setattr(mod, attr, None)` with `hasattr` guard.
- `create_app(*, dependency_overrides=None) -> FastAPI`: (1) `_reset_singletons()`, (2) lazy `from main import _configure_app, lifespan`, (3) `app = FastAPI(lifespan=lifespan); _configure_app(app)`, (4) apply `dependency_overrides`.

---

### `tests/conftest.py` — extend

**Analog:** `pg_pool`/`pg_store` at `conftest.py:36-79` (function-scoped, autouse sparingly).

**`pg_store` shape to mirror** (`conftest.py:65-73`):
```python
@pytest.fixture
async def pg_store():
    import services.vectorizer.vector_store as vs_module
    vs_module._store_instance = None
    from services.vectorizer.vector_store import PgVectorStore
    store = PgVectorStore()
    yield store
    vs_module._store_instance = None
```

**Required additions:**
1. `pytest_configure(config)` — register `uses_redis` + `benchmark` markers via `config.addinivalue_line`.
2. `pytest_collection_modifyitems(config, items)` — auto-append `redis_mock` to `item.fixturenames` for `uses_redis`-marked tests.
3. `redis_mock` fixture — function-scoped, `fakeredis.aioredis.FakeRedis(decode_responses=True)` (NOT `MagicMock(spec=...)` per RESEARCH §Theme 2). Patches `utils.cache.get_redis`, resets `utils.cache._redis_client`, `await fake.aclose()` teardown.
4. `app_factory` — yields callable; teardown calls `_reset_singletons()`.
5. `isolated_app` — `app_factory()` shorthand.
6. `isolated_client` — `httpx.AsyncClient(transport=ASGITransport(app=isolated_app), base_url="http://test")`. Skips lifespan (Pitfall 4) — adequate for SC-1.

---

## Test-File Pattern Assignments (compact)

All test files follow Patterns A+B+C+E (Shared Patterns section below) — env-var setdefault, autouse singleton reset, dual-path monkeypatch, pytestmark skip-gate.

### `tests/unit/test_app_factory.py`
**Analog:** `test_memory_pool.py:14-79`.
**Cases:** (1) two `create_app()` returns distinct instances. (2) pre-set singleton → sentinel; `create_app()` resets. (3) `dependency_overrides` kwarg applies. Skip lifespan (Pitfall 4).

### `tests/unit/test_parallel_contamination.py` — SC-1
**Analog:** `test_memory_forget_e2e.py:49-88` (manual reset; factory automates).
**Pattern from RESEARCH lines 429-453:**
```python
@pytest.mark.asyncio
async def test_two_apps_do_not_share_state(app_factory):
    app_a = app_factory()
    import services.agent.executor as exec_mod
    sentinel = object()
    exec_mod._executor_instance = sentinel
    app_b = app_factory()
    assert exec_mod._executor_instance is None
    assert app_a is not app_b
```

### `tests/unit/test_redis_mock_fixture.py`
**Analog:** `test_memory_service.py:18-86` (fakeredis self-test).
**Deviation:** consume new conftest `redis_mock` (not file-local). Mark every test `@pytest.mark.uses_redis`. Cover GET/SET/SETEX, RPUSH/LRANGE/EXPIRE/DELETE, ZADD/ZCOUNT/ZREMRANGEBYSCORE, `pipeline().execute()`.

### `tests/unit/test_singleton_inventory_complete.py` — D-03 lint
**Authority:** RESEARCH §Theme 1 lines 457-498.
- `Path("services").rglob("*.py")`.
- Regex `^(_[a-zA-Z_]+)\s*[:=].*= None`.
- Cross-check vs `_SINGLETON_INVENTORY`.
- `_SKIP` set for 4 non-services.
- `assert not missing` with diff.

### `tests/unit/memory/test_save_fact_precheck.py` — SC-3
**Analog:** `test_memory_save_fact.py:87-122`.
**Reusable helpers verbatim** (`test_memory_save_fact.py:50-80`):
```python
class _AcquireCtx:
    def __init__(self, conn): self._conn = conn
    async def __aenter__(self): return self._conn
    async def __aexit__(self, *a): return False

def _make_fake_pool(execute_mock):
    conn = MagicMock(execute=execute_mock)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AcquireCtx(conn))
    return pool, conn

def _make_long(pool):
    lt = LongTermMemory.__new__(LongTermMemory)
    lt._pool = pool
    async def _get_pool(): return pool
    lt._get_pool = _get_pool
    return lt
```
**Extension:** conn needs `fetchrow` + `transaction()`. Mirror `test_memory_recall_semantic.py:82-90`.
**Dual-path embedder patch** (`test_memory_save_fact.py:89-96`):
```python
monkeypatch.setattr("services.vectorizer.embedder.get_embedder", lambda: fake)
monkeypatch.setattr("services.memory.memory_service.get_embedder", lambda: fake, raising=False)
```
**SC-3/D-09 assertions:** audit-mode-only (INSERT still runs when `dist=0.02`), `+1 PG RTT` (`conn.fetchrow.await_count == 1`).

### `tests/unit/memory/test_save_fact_precheck_failure.py`
**Analog:** `test_memory_save_fact.py:128-188` (parametrize pattern).
**Phase 27 deviation:** precheck failure is fail-OPEN — NOT raise. Assert INSERT still runs + `logger.warning` called. Parametrize: `[asyncpg.PostgresError, asyncpg.ConnectionDoesNotExistError, asyncpg.InterfaceError]`.

### `tests/unit/memory/test_save_facts_batch.py` — SC-4 mock counting
**Analog A:** `test_memory_save_fact.py` helpers.
**Analog B (call_count):** `test_audit_service_pool.py:36-44`.
**Assertions (from RESEARCH lines 866-915):** `embed_spy.call_count == 1`, `bulk_check_spy.call_count == 1`, `executemany_spy.call_count == 1`, `result.saved_count == 5`. Extend conn mock with `executemany = AsyncMock()`.

### `tests/unit/memory/test_save_facts_batch_dedupe.py`
**Shape:** 5 facts; mock `_bulk_near_duplicate_check` → `{1, 3}`. Assert (a) `executemany` called with all 5 (D-09 audit-mode), (b) audit `log` called 2×, (c) `result.skipped_near_duplicates == 2 AND result.saved_count == 5`.
**Audit mock pattern** (mirror `test_extractor_dispatch.py:73-77`):
```python
mock_audit = MagicMock(log=AsyncMock())
monkeypatch.setattr("services.audit.audit_service.get_audit_service", lambda: mock_audit)
```

### `tests/unit/memory/test_save_facts_embed_batch_fallback.py`
**Pattern:** `embed_batch_spy.side_effect = RuntimeError; embed_one_spy.return_value = vec; assert embed_batch_spy.call_count == 1; assert embed_one_spy.call_count == N`. Parametrize one `embed_one` to also raise → `skipped_embed_failures == 1`. Honors D-16 correction (RESEARCH §9 lines 266-279).

### `tests/integration/audit/test_audit_suite_factory_migrated.py`
**Analog:** `test_audit_log_auto_create.py:17-61`.
**Existing pattern:**
```python
@pytest.mark.asyncio
async def test_audit_log_auto_creates_on_first_flush(pg_pool, monkeypatch):
    async with pg_pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS audit_log CASCADE;")
    monkeypatch.setattr("services.audit.audit_service.settings.audit_db_enabled", True, raising=False)
    import services.audit.audit_service as audit_mod
    audit_mod._audit_service = None
    svc = audit_mod.get_audit_service()
    # ... use real PG via pg_pool ...
```
**Phase 27 deviation:** replace manual reset with `app = app_factory()` (resets all 32). Demonstrates "audit suite migrated to factory" per CONTEXT SC-1.
**Skip-gate:** `pytestmark = [pytest.mark.integration, pytest.mark.skipif(not PG_AVAILABLE, ...)]`.

### `tests/integration/memory/test_memory_suite_factory_migrated.py`
**Analog A:** `test_pgvector_filtered_recall.py` (PG-gated `pg_store`).
**Analog B:** `test_lifespan_shutdown_closes_pools.py` (reset before each).
**Shape:** uses `app_factory` + `pg_pool` + `clean_long_term_facts` (`conftest.py:178-195`). Construct 5 `ExtractedFact`s, call `save_facts(...)`, assert result + `SELECT COUNT(*) FROM long_term_facts`.

### `tests/benchmark/test_extractor_latency.py` — SC-5
**Analog:** `test_recall_latency.py:17-103` (p95 timing loop).
**Timing-loop pattern** (`test_recall_latency.py:95-103`):
```python
timings_ms: list[float] = []
for _ in range(_TRIALS):
    t0 = time.perf_counter()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            # ... timed operation ...
    timings_ms.append((time.perf_counter() - t0) * 1000)
```
**Phase 27 deviation (RESEARCH lines 919-926):** SC-5 is RELATIVE. Two loops: (A) 5× `save_fact` baseline. (B) 1× `save_facts([5 facts])`. Assert `(median(A) - median(B)) >= 4 × embed_rtt_ms × 0.8` (~80ms tolerant floor). Record p50/p95 + delta to `27-SUMMARY.md`. Marker `pytest.mark.benchmark`.

---

## Shared Patterns

### Pattern A — Env-var setdefault at module top
**Source:** `test_memory_save_fact.py:25-28` (used by ~80% of test files).
```python
import os
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")
```
**Apply to:** every new test file. MUST precede any `from services.*` import (settings reads `APP_MODEL_DIR` at import time).

### Pattern B — Autouse singleton-reset fixture
**Source:** `test_memory_save_fact.py:43-47`.
```python
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    import services.memory.memory_service as mod
    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)
```
**Apply to:** unit tests under `tests/unit/memory/*`. Integration tests use `app_factory` (resets all 32) instead.

### Pattern C — Mock at consumer path (v1.3 D-04)
**Source:** `test_memory_save_fact.py:89-96`.
```python
monkeypatch.setattr("services.vectorizer.embedder.get_embedder", lambda: stub)
monkeypatch.setattr("services.memory.memory_service.get_embedder", lambda: stub, raising=False)
```
**Why dual-path:** `get_embedder` lazy-imported inside method bodies. `raising=False` because not bound at memory_service module top.

### Pattern D — Audit-write non-fatal boundary
**Source:** `audit_service.py:183-194` — file write wrapped `try/except Exception: logger.warning(...)`.
**Apply to:** TD-04 `_fire_near_duplicate_audit` (RESEARCH §Theme 3 lines 685-699). Bare `except Exception` permitted ONLY here (v1.6 GDPR T1 carry-forward). Rest of code: narrow exceptions per CLAUDE.md.

### Pattern E — Integration pytestmark skip-gate
**Source:** `test_pgvector_filtered_recall.py:22-29`.
```python
from tests.conftest import PG_AVAILABLE
pytestmark = [
    pytest.mark.integration,
    pytest.mark.pgvector,
    pytest.mark.skipif(not PG_AVAILABLE, reason="..."),
]
```
**Apply to:** every Phase 27 integration test. Add `pytest.mark.benchmark` (file) + `pytest.mark.uses_redis` (function) where relevant.

### Pattern F — Pydantic bounded numeric setting
**Source:** `settings.py:498` — `Field(default=500, ge=1)`. TD-04: `Field(default=0.05, ge=0.0, le=1.0)`. Uniform across `settings.py`.

---

## Adapter Pattern (Embedder)

`BaseEmbedder` ABC at `embedder.py:27-34` — `embed_batch` abstract, `embed_one` delegates.

| Adapter | File:Line | `embed_batch` failure |
|---|---|---|
| `OllamaEmbedder` | `embedder.py:61-70` | gather + per-item check → `raise RuntimeError(f"Embedding failed for text[{i}]")` |
| `OpenAIEmbedder` | `embedder.py:85-99` | single API call — raises httpx/openai errors |
| `HuggingFaceEmbedder` | `embedder.py:115-126` | single torch call — raises OSError/RuntimeError |

Wired via singleton at `embedder.py:236` (`_embedder_instance`). `get_embedder()` returns the configured impl per `settings.embedding_provider`.

**Phase 27 obligation:** `save_facts` wraps `embed_batch` in try/except per RESEARCH §9 — fallback to per-item `embed_one` gathered with `return_exceptions=True`. Do NOT modify embedders (out of scope; v1.8+ todo per RESEARCH lines 277-279).

---

## Test Fixture Conventions

**Scope:** function-scoped is canonical. Only `pg_available` is module-scoped (`conftest.py:76`). Session-scope is wrong — `InterfaceError: cannot perform operation: another operation is in progress` documented at `conftest.py:39-46`.

**Autouse:** sparingly. Existing: `extractor_llm_mock`/`embedder_or_mock` (`conftest.py:105, 132`) + per-file `reset_X_singleton`. Phase 27 new (`redis_mock`, `app_factory`, `isolated_app`, `isolated_client`) are explicit. `redis_mock` is auto-applied ONLY via marker hook (D-18).

**Naming:** snake_case verb-or-noun. Phase 27 adds: `redis_mock`, `app_factory`, `isolated_app`, `isolated_client`.

**Parametrize:** test-level. Canonical: `test_memory_save_fact.py:128-135`.

---

## Singleton Pattern Audit — 3 Representative Migrations

### Singleton 1 — `_memory_service` (clean accessor)
**Shape** (`memory_service.py:625-631`):
```python
_memory_service: MemoryService | None = None

def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
```
**After Phase 27:** ZERO source change. Factory sets `setattr(mod, "_memory_service", None)`. Next call constructs fresh on current event loop. **Canonical pattern for ~30 of 32 singletons.**

### Singleton 2 — `_audit_service` (pool-bound state)
Same accessor shape at `audit_service.py:386-393`. BUT instance holds `self._pool` (asyncpg) bound to prior event loop. **Reset alone is insufficient** — prior pool stays live until GC. PROD handled by `main.py:131-135` lifespan close. In tests, factory pairs with **either** lifespan execution **or** explicit `svc.close()` in fixture teardown. Tests on real pool must close explicitly before factory reset (RESEARCH Pitfall 4).

### Singleton 3 — `_executor_instance` (heavy dep graph)
Shape at `executor.py:252`. Constructs ToolRegistry, calls `get_X` for many services. After Phase 27: zero source change. Transitive graph also reset because every singleton is in `_SINGLETON_INVENTORY`. Next `get_executor()` rebuilds cleanly.

**Planner takeaway:** brute-force reset is correct precisely BECAUSE inventory is comprehensive. D-03 lint enforces — new singletons without entries fail CI.

---

## Audit-Mode Metric Naming

**Existing `AuditAction` convention** — SCREAMING_SNAKE_CASE verb/noun: `QUERY`, `INGEST`, `DELETE_DOC`, `LOGIN`, `LOGOUT`, `PERMISSION_DENIED`, `RATE_LIMITED`, `PII_DETECTED`, `RULE_BLOCKED`, `FEEDBACK`, `KB_UPDATE`, `TOKEN_VERIFIED`, `MEMORY_FORGET`, `MEMORY_EVICT`.

**`MEMORY_NEAR_DUPLICATE_SKIPPED`:** prefix matches Phase 25 (`MEMORY_*`). Suffix `_SKIPPED` matches `AuditResult.SKIPPED` (`audit_service.py:49`) — semantic intent (would-skip in v1.8; audit-mode-only in v1.7 per D-09). **Verdict:** conventional, no drift.

**Prometheus counter:** repo uses `rag_*_total` prefix (`utils/metrics.py:43-141`). If added, convention is `rag_memory_near_duplicate_skipped_total` with `labels=["tenant_id"]`. **However:** RESEARCH SC-3 only requires audit_log row. Prometheus counter is OUT OF SCOPE for Phase 27 (deferred to v1.8 ops dashboard per CONTEXT deferred §"TD-04 dedupe rate dashboards"). Planner should NOT add the counter.

---

## No Analog Found

| File | Why |
|---|---|
| `tests/factories/app.py` | First factory module in repo. Authority: RESEARCH §Theme 1 lines 308-388. |
| `tests/factories/__init__.py` | Empty marker — follows `tests/integration/__init__.py`. |

---

## Metadata

**Analog search scope:** `services/`, `tests/unit/`, `tests/integration/`, `tests/conftest.py`, `utils/cache.py`, `utils/metrics.py`, `config/settings.py`, `main.py`.

**Files read in full:** `tests/conftest.py`, `utils/cache.py`, `embedder.py` 1-150, `memory_service.py` 1-180/280-396/615-631, `audit_service.py` 1-220/380-393, `main.py` 1-389, `test_memory_save_fact.py`, `test_memory_service.py`, `test_memory_pool.py`, `test_extractor_dispatch.py` 1-120, `test_audit_service_pool.py` 1-150, `test_pgvector_filtered_recall.py` 1-120, `test_audit_log_auto_create.py`, `test_recall_latency.py` 1-100, `test_lifespan_shutdown_closes_pools.py`, `test_extractor_e2e.py` 1-100, `test_memory_recall_semantic.py` 1-90, `test_memory_forget_e2e.py` 1-100, `extractor.py` 170-270, `settings.py` 490-520, `utils/models.py` 675-723.

**Key insight:** the codebase already has every pattern Phase 27 needs except the factory itself. 16/17 new files have direct analogs. Singleton reset in fixtures is already idiomatic (`pg_store:69`, `extractor_llm_mock:124`, `embedder_or_mock:162`, `test_memory_forget_e2e:73-84`). The factory generalizes the pattern across all 32 services; D-03 lint prevents drift.
