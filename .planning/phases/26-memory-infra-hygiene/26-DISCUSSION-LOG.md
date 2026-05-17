# Phase 26: Memory Infra Hygiene - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-17
**Phase:** 26-memory-infra-hygiene
**Areas discussed:** asyncpg_helper API surface, audit_service pool migration (TD-01 ∩ TD-03), TD-01 _create_tables trigger point + pool lifecycle, TD-07 bge-m3 path resolution

---

## Area 1 — `utils/asyncpg_helper.py` API surface (TD-03)

| Option | Description | Selected |
|--------|-------------|----------|
| `prepare_dsn(dsn) -> (clean_dsn, ssl_kwargs)` | Pure transformation. Callers own asyncpg lifecycle. Minimal surface; easy to unit-test. | ✓ |
| Two wrapper fns: `create_pool_from_dsn()` + `connect_from_dsn()` | Helper owns the asyncpg call. Less code at call sites but couples to asyncpg call shape. | |
| Single `connect_from_dsn(pool=True)` flag | One entry point, branches internally. Flag overloads return type — harder to type-check. | |

**User's choice:** `prepare_dsn(dsn) -> (clean_dsn, ssl_kwargs)`
**Notes:** Also bundle the `postgresql+asyncpg://` → `postgresql://` scheme strip into the helper — both call sites do that strip too; not bundling would leave half the dedup behind. Helper is stdlib-only, no asyncpg dependency, no logging side effects.

---

## Area 2 — `audit_service` pool migration (TD-01 ∩ TD-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Singleton pool (LongTermMemory pattern) | Match v1.6 reference pattern. Pool `min_size=1, max_size=4`. Lazy `_create_tables` on first acquire. | ✓ |
| One-shot connect + `_tables_initialized` flag | Minimal blast radius (one extra block in `_flush`). Drifts from v1.6 pattern; flag is process-local; concurrent first-flushes race the create. | |

**User's choice:** Singleton pool
**Notes:** Pool size reflects existing audit cadence (50-event batch flush every 10s). Shutdown handling deferred to Area 3.

---

## Area 3 — TD-01 `_create_tables` trigger point + pool lifecycle

### Sub-question 3a — Trigger point

| Option | Description | Selected |
|--------|-------------|----------|
| Lazy on first `_get_pool()` acquire | Verbatim match of `LongTermMemory._get_pool`. Idempotent CREATE TABLE IF NOT EXISTS. First write pays schema-check round-trip. | ✓ |
| FastAPI lifespan startup event | Deterministic ordering; visible in startup logs. Introduces startup-time DB dependency; if PG down at boot, app fails to start. | |
| Explicit `AuditService.initialize()` from main.py | Caller-driven init outside lifespan. Same costs as (b) + more verbose; loses v1.6 symmetry. | |

**User's choice:** Lazy on first `_get_pool()` acquire

### Sub-question 3b — Pool lifecycle (shutdown)

| Option | Description | Selected |
|--------|-------------|----------|
| FastAPI lifespan shutdown closes both audit + memory pools | Deterministic cleanup; mirrors production uvicorn SIGTERM. Small refactor to add `close()` methods. | ✓ |
| Rely on process exit (no explicit close) | Zero code change. Pending writes may be lost; loud warnings on pytest finalize. | |

**User's choice:** FastAPI lifespan shutdown closes both pools
**Notes:** Order: audit close first (drains buffer to PG), then memory close. Reverse of startup. Add `close()` to `MemoryContext` + `LongTermMemory` if not already present.

---

## Area 4 — TD-07 bge-m3 path resolution

### Sub-question 4a — Resolution strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Resolver function; multi-layout search; first hit wins | `resolve_embedding_model_path(name)` searches env override → HF flat → legacy → HF hub cache. Zero migration burden; env var escape hatch. | ✓ |
| Env-var-only override; no auto-search | Explicit; no magic. User has to know the env var; HF cache layout still not the default. | |
| Migration script only (no code change) | Keeps `settings.py` simple. Still manual step; doesn't fix the root asymmetry; bug bites on first install. | |

**User's choice:** Resolver function; multi-layout search

### Sub-question 4b — Reranker (`bge-m3-rerank`) scope

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — same resolver covers both | Single PR delivers symmetry; negligible extra scope. | ✓ |
| No — embedding only; reranker defers | Narrower blast radius; tracked as v1.8 todo for a 5-line change. | |

**User's choice:** Yes — same resolver covers both
**Notes:** Resolver returns the legacy path on miss (option 3 in search order) so existing "lazy crash at model-load time" semantics are preserved. `tests/conftest.py:134-160` model-dir guard rewrites to call the resolver.

---

## Claude's Discretion

- Exact env var names (`APP_EMBEDDING_MODEL_PATH`, `APP_RERANKER_MODEL_PATH` proposed).
- Whether resolver stays in `config/settings.py` or moves to `config/model_paths.py` if it grows beyond ~30 lines. Default: `settings.py` for v1.7.
- Unit-test layout (`tests/unit/test_asyncpg_helper.py`, `tests/unit/config/test_resolve_embedding_model_path.py`).
- Whether AuditService pool needs `application_name=audit_service` init (deferred to v1.8 if dashboards need it).
- Whether to keep existing one-shot connect path as guarded fallback for `audit_db_enabled = False`. Default: yes, settings flag still bypasses pool.

## Deferred Ideas

- `audit_service` pool `application_name` for `pg_stat_activity` — v1.8 ops todo.
- `config/model_paths.py` extraction — only if resolver grows beyond ~30 lines.
- HF hub cache snapshot SHA-pinning — reproducibility concern for a future phase.
- TD-02 / TD-04 / TD-05 / TD-06 — Phase 27 scope; do not bundle into Phase 26 PR.
- DOC-01 — Phase 28 scope; doc updates land end-of-milestone.
