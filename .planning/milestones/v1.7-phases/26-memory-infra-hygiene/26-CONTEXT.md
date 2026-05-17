# Phase 26: Memory Infra Hygiene - Context

**Gathered:** 2026-05-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Production-clean startup for the memory subsystem. Three deferred items from v1.6 ship land together because they touch the same surface (`services/audit/`, `services/memory/`, `config/settings.py`):

- **TD-01** — `audit_log` table auto-creates on first `AuditService` DB write (DDL currently lives in a docstring only).
- **TD-03** — `?ssl=disable` URL-param strip + `postgresql+asyncpg://` scheme strip centralized in a new `utils/asyncpg_helper.py`; both `memory_service.py` and `audit_service.py` consume it.
- **TD-07** — bge-m3 (and bge-m3-rerank) model loading resolves multiple directory layouts natively; no symlink workaround required for fresh installs that use the HF cache.

**In scope:** TD-01 + TD-03 + TD-07.
**Out of scope:** every other v1.7 requirement (TD-02, TD-04, TD-05, TD-06 → Phase 27; DOC-01 → Phase 28). No changes to v1.6 audit semantics, INSERT-ONLY invariant, or `LongTermMemory` write path beyond the DSN helper swap.

</domain>

<decisions>
## Implementation Decisions

### Theme 1 — `utils/asyncpg_helper.py` API surface (TD-03)

- **D-01:** Single pure function: `prepare_dsn(dsn: str) -> tuple[str, dict[str, str]]`. Returns `(clean_dsn, ssl_kwargs)`. Callers own the asyncpg lifecycle (no `create_pool` / `connect` wrapper in the helper). Rationale: doesn't dictate pool sizing, init callbacks, or connection lifecycle; easy to unit-test as a pure function.
- **D-02:** Helper bundles BOTH transformations currently duplicated: (a) `postgresql+asyncpg://` → `postgresql://` scheme strip and (b) `?ssl=disable` / `&ssl=disable` token strip → `{"ssl": "disable"}` kwarg. Bundling avoids leaving half the dedup behind.
- **D-03:** Helper has zero dependencies beyond stdlib. No asyncpg import; no logging side effects. Pure string-in / tuple-out.
- **D-04:** Call-site shape both consumers adopt:
  ```python
  from utils.asyncpg_helper import prepare_dsn
  dsn, ssl_kwarg = prepare_dsn(settings.pg_dsn)
  self._pool = await asyncpg.create_pool(dsn, min_size=..., init=..., **ssl_kwarg)
  # OR
  conn = await asyncpg.connect(dsn, **ssl_kwarg)
  ```

### Theme 2 — `AuditService` pool migration (TD-01 ∩ TD-03)

- **D-05:** `AuditService` migrates from per-flush `asyncpg.connect()` (current `_flush` line 260-280) to a singleton pool mirroring `LongTermMemory._get_pool`. Pool size: `min_size=1, max_size=4` (audit volume is low — batch flush every 10s or 50 events).
- **D-06:** Pool init callback is empty (no `register_vector` needed — audit table has no vector columns).
- **D-07:** `_get_pool()` is lazy: first call builds the pool, then awaits `_create_tables()` before returning. Subsequent calls return the cached pool. Matches `LongTermMemory._get_pool` verbatim — same idempotency guarantees.
- **D-08:** `AuditService.close()` method added: drains the buffer (`await self._flush()` if non-empty), then `await self._pool.close()` if pool exists. Idempotent (close a closed pool = no-op).

### Theme 3 — TD-01 `_create_tables` trigger point + DDL semantics

- **D-09:** `_create_tables` fires lazily at the end of `_get_pool`'s first-acquire branch (verbatim `LongTermMemory` pattern). First audit write pays the schema-check round-trip; later writes don't. No FastAPI lifespan dependency, no startup ordering refactor.
- **D-10:** DDL is the verbatim port of the existing docstring on `audit_service.py:76-90`:
  ```sql
  CREATE TABLE IF NOT EXISTS audit_log (
      event_id    VARCHAR(32)  PRIMARY KEY,
      timestamp   DOUBLE PRECISION NOT NULL,
      user_id     VARCHAR(128),
      tenant_id   VARCHAR(128),
      action      VARCHAR(64)  NOT NULL,
      resource_id VARCHAR(256),
      ip_address  VARCHAR(64),
      result      VARCHAR(32)  NOT NULL,
      detail      JSONB,
      trace_id    VARCHAR(32),
      created_at  TIMESTAMPTZ  DEFAULT NOW()
  );
  REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;
  ```
  Both statements are idempotent. INSERT-ONLY invariant preserved (carry-forward from v1.0 Phase 2).
- **D-11:** No GRANT statements added. v1.7 assumes the existing role/connection has INSERT privileges (Phase 25 already validated this end-to-end on real PG). New roles are an ops concern, not an app concern.
- **D-12:** Docstring on `AuditService` updated: replace "应用首次部署时执行" (run at first deploy) with "由 `_get_pool()` 首次调用时自动执行" (automatically executed on first `_get_pool()` call). Otherwise leave the structural docstring intact.

### Theme 4 — FastAPI lifespan shutdown (pool cleanup)

- **D-13:** `main.py` lifespan handler's shutdown branch gains `await audit_service.close()` and `await memory_context.close()` (the latter added in this phase if not already present on `MemoryContext`).
- **D-14:** `LongTermMemory.close()` also added — symmetry with `MemoryContext.close()`. Both call `await self._pool.close()` guarded by `if self._pool is not None`.
- **D-15:** Order of shutdown: audit first (so any draining writes have somewhere to go), then memory. Reverse of startup ordering.
- **D-16:** If `main.py` doesn't currently use a FastAPI `lifespan=` context manager, that refactor lands in this phase (small — wraps existing startup/shutdown event handlers if any, or adds a fresh `@asynccontextmanager` if none). Researcher confirms current shape during planning.

### Theme 5 — TD-07 bge-m3 path resolution

- **D-17:** New function `config/settings.py::resolve_embedding_model_path(name: str) -> Path`. Search order, first hit wins:
  1. Env-var override (`APP_EMBEDDING_MODEL_PATH` for `bge-m3`, `APP_RERANKER_MODEL_PATH` for `bge-m3-rerank`).
  2. `MODEL_DIR / "BAAI" / name` (HF flat layout — current bug source).
  3. `MODEL_DIR / "embedding_models" / name` (legacy layout — current default in code).
  4. `MODEL_DIR / f"models--BAAI--{name}" / "snapshots"` — return first existing snapshot subdir if present (HF hub cache structure).
- **D-18:** If no path exists, resolver returns the **legacy path** (option 3) as fallback. This preserves the current "lazy crash at model-load time" behavior — no breaking change for the missing-model case. Documented inline.
- **D-19:** `embedding_model_path` and `reranker_model_path` become `@property` (or `@cached_property`) delegating to the resolver. Existing callers that read `settings.embedding_model_path` need no change.
- **D-20:** Reranker (`bge-m3-rerank`) is in scope — same resolver covers both. Negligible extra scope for what would otherwise become a v1.8 follow-up.
- **D-21:** `tests/conftest.py:134-160` model-dir guard updated: replace the hardcoded `os.path.join(model_dir, "embedding_models", "bge-m3")` check with a call to `resolve_embedding_model_path("bge-m3")` + `.exists()` check. Pytest fixture continues to skip integration suites when the model is genuinely absent.

### Claude's Discretion

- Exact name of the env vars (`APP_EMBEDDING_MODEL_PATH` is the proposed default — bikeshed-free if the user doesn't push back).
- Whether the resolver function is exported from `config.settings` or moved to a separate `config/model_paths.py` if it grows beyond ~30 lines. Default: keep in `settings.py` for v1.7; revisit if Phase 27/28 adds more model paths.
- Unit-test layout — colocate `tests/unit/test_asyncpg_helper.py` next to existing utility tests; colocate `tests/unit/test_resolve_embedding_model_path.py` under `tests/unit/config/`.
- Whether `AuditService` pool needs an `init=` callback that sets `application_name=audit_service` for PG `pg_stat_activity` visibility. Default: skip in v1.7, add as v1.8 ops todo if dashboards need it.
- Whether to keep audit's existing one-shot connect path as a guarded fallback for `audit_db_enabled = False` mode. Default: yes — settings flag still bypasses pool entirely.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope + requirements
- `.planning/REQUIREMENTS.md` §"Schema & Infra Hygiene" — TD-01, TD-03, TD-07 acceptance criteria
- `.planning/ROADMAP.md` §"Phase 26: Memory Infra Hygiene" — 4 success criteria
- `.planning/PROJECT.md` §"Current Milestone: v1.7" — milestone-level constraints

### Reference implementations to mirror
- `services/memory/long_term_memory.py` — `LongTermMemory._get_pool` + `_create_tables` lazy-init pattern that TD-01 must mirror in `AuditService`. Source of D-07, D-09, D-14.
- `services/memory/memory_service.py:140-200` — `MemoryContext._get_pool` includes the `?ssl=disable` strip duplicated logic; reference for what `prepare_dsn` extracts.
- `services/audit/audit_service.py:65-95` — current DDL docstring on `AuditService` (the verbatim DDL TD-01 ports into `_create_tables`).
- `services/audit/audit_service.py:245-295` — current one-shot `asyncpg.connect()` flush block being replaced by pool acquire.

### Carry-forward decisions still in force (do NOT renegotiate)
- INSERT-ONLY `audit_log` invariant — v1.0 Phase 2. TD-01 DDL must keep `REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;`.
- Audit-write failure must NOT block destructive action — v1.6 Phase 25 T1. TD-01 changes nothing about caller error handling.
- `OPS-01` — `APP_MODEL_DIR` is required, no hardcoded fallback. TD-07 env-var defaults must not violate this.
- Mock at consumer path (`services.<mod>.<dep>`), not source — v1.3 Phase 13. Unit tests for new helpers mock `services.audit.audit_service.asyncpg` / `services.memory.memory_service.asyncpg` etc.
- `tests/conftest.py::pg_pool` function-scope fixture — v1.6 Phase 25 hotfix (PR #7). Do NOT regress to session-scope.

### Project standards
- `CLAUDE.md` (repo root) — project rules (Pydantic V2, mypy --strict, ruff, no bare except, no blocking I/O in async, adapter pattern, structured logging).

### Prior phase context (read-only — for pattern reference)
- `.planning/milestones/v1.6-phases/23-background-extractor-schema-migration/23-CONTEXT.md` — Phase 23 (`LongTermMemory` schema + extractor) — origin of the pool pattern reused here.
- `.planning/milestones/v1.6-phases/25-eviction-job-gdpr-forget-api/25-CONTEXT.md` — Phase 25 (audit-log shape + audit-mode-before-enforce) — origin of D-11 (no GRANT statements) and the audit-write-no-block discipline.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LongTermMemory._get_pool` / `_create_tables` — verbatim template for `AuditService` migration. Idempotent CREATE TABLE IF NOT EXISTS; pool cached on `self._pool`; pgvector codec init pattern (audit doesn't need vector codec — see D-06).
- `MemoryContext._get_pool` (in `services/memory/memory_service.py:140-200`) — the `?ssl=disable` and scheme strip logic that `prepare_dsn` extracts.
- `tests/conftest.py::pg_pool` (function-scope) — usable by new integration tests for TD-01 cold-start path.
- `config/settings.py::settings.pg_dsn` — single source of truth for DSN; both consumers already read this.

### Established Patterns
- Lazy-init pool with cached singleton (`self._pool is None` guard). Used by `LongTermMemory` and `MemoryContext`. TD-01 mirrors.
- `CREATE TABLE IF NOT EXISTS` + `REVOKE` for INSERT-ONLY tables. Both idempotent — safe to re-run on every cold start.
- Function-scope async fixtures for PG-gated tests (PR #7 lesson from v1.6 ship — never session-scope).
- Mock-at-consumer-path test discipline (v1.3 Phase 13). New unit tests for `prepare_dsn` are pure-function tests; no mocking needed.

### Integration Points
- `main.py` lifespan handler — receives shutdown calls to `audit_service.close()` + `memory_context.close()` (+ `long_term_memory.close()`). Need to read current `main.py` shape during planning to confirm lifespan vs deprecated startup/shutdown event handlers.
- `tests/conftest.py:134-160` — `bge-m3` directory existence check is rewritten to call `resolve_embedding_model_path` so the fixture honors the resolver's search order.
- All existing `settings.embedding_model_path` / `settings.reranker_model_path` call sites (audit during research — `grep -rn 'embedding_model_path\|reranker_model_path' services/ tests/`) — these continue to work unchanged because the fields become properties.

</code_context>

<specifics>
## Specific Ideas

- DSN helper: pure function, stdlib-only, returns `tuple[str, dict[str, str]]`. No logging, no asyncpg import. Drop-in for both `MemoryContext._get_pool` (line 163-172) and `AuditService._flush` (line 261-270).
- AuditService pool sizing reflects the existing buffer cadence: 50-event batches every 10s = ≤6 connections/min sustained. `min_size=1, max_size=4` is sized for burst absorption, not steady-state.
- bge-m3 resolver search order is deliberately HF-flat-FIRST so the bug fix is the default for HF cache users; legacy users (currently the only working layout) still resolve because legacy is in the search path.
- Resolver returns the legacy path on miss so test fixtures + production loaders see the same "model missing" surface they see today — no semantics change for the absent-model case.

</specifics>

<deferred>
## Deferred Ideas

These came up during discussion or codebase scout but belong in other phases / milestones:

- **`audit_service` pool `application_name` setting** — for `pg_stat_activity` visibility. v1.8 ops todo if dashboards need it.
- **`config/model_paths.py` module extraction** — if the resolver grows beyond ~30 lines (more model families in v1.8+), split out then. v1.7 keeps it in `settings.py`.
- **HF hub cache snapshot pinning** — `models--BAAI--<name>/snapshots/<sha>/` resolves the latest existing snapshot today; SHA-pinning is a reproducibility concern for a future phase, not v1.7.
- **TD-02 / TD-04 / TD-05 / TD-06** — these are Phase 27 scope. Even though they touch the same `services/memory/` directory, do NOT bundle into Phase 26 PR. Keeps the diff reviewable + the per-phase verify cycle honest.
- **DOC-01** — Phase 28. Doc updates land at end of milestone, not per-phase.

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 26-memory-infra-hygiene*
*Context gathered: 2026-05-17*
