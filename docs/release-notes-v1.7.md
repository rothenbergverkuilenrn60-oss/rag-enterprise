# v1.7.0 Release Notes — Memory Tech-Debt Burn-Down

*Shipped: 2026-05-17. Phases 26–28.*
*Pure refactor + reliability — zero new user-facing capabilities.*

---

## Highlights

v1.7 is a refactor + reliability milestone. The memory subsystem (write path,
schema bootstrap, asyncpg DSN handling, model-cache layout, test isolation) is
now production-clean. Zero new user-facing capabilities; zero upgrade steps
required.

---

## Shipped Items

All per-Phase / per-TD detail is anchored in
[MILESTONES.md#v17](../MILESTONES.md#v17) — that section holds the per-Phase
pointers to SUMMARY.md files and survives `.planning/` reorganization.

### Phase 26 — Memory Infra Hygiene (TD-01, TD-03, TD-07)

- **TD-01** — `audit_log` PostgreSQL table auto-creates on first call into
  `services/audit/audit_service.py`. Cold-start no longer requires manual
  DDL. INSERT-ONLY invariant (`REVOKE UPDATE, DELETE ON audit_log FROM
  PUBLIC`) preserved.

- **TD-03** — `utils/asyncpg_helper.prepare_dsn(dsn)` centralizes the
  `?ssl=disable` URL-param strip (asyncpg URL parser misreads the literal).
  Both memory and audit services consume the helper.

- **TD-07** — bge-m3 loads from vanilla HuggingFace cache
  `{MODEL_DIR}/BAAI/bge-m3/`. Legacy
  `{MODEL_DIR}/embedding_models/bge-m3/` path still resolved
  (backwards-compat).

### Phase 27 — Test Isolation + Memory Reliability (TD-02, TD-04, TD-05, TD-06)

- **TD-02** — `tests/factories/app.py::create_app()` factory +
  `main._configure_app(app)` extraction. Per-test isolated FastAPI app
  construction; parallel cross-contamination test green. 34-entry singleton
  inventory + completeness lint.

- **TD-06** — `redis_mock` fixture (fakeredis-backed) auto-applied via
  `@pytest.mark.uses_redis` marker. `ShortTermMemory._get_client` delegates
  to `utils.cache.get_redis` (single mock target). Unit suite runs without
  live Redis.

- **TD-04** — `LongTermMemory._is_near_duplicate` cosine precheck
  (`<embedding> <=> $vec < 0.05`); near-duplicate hits emit
  `MEMORY_NEAR_DUPLICATE_SKIPPED` audit row. New `AuditAction` enum value;
  new `MEMORY_NEAR_DUPLICATE_THRESHOLD` setting. **Audit-mode-only in v1.7**
  per D-09 — the INSERT still runs.

- **TD-05** — `LongTermMemory.save_facts(list[ExtractedFact])` batch path:
  1× `embed_batch` + 1× bulk dedupe SELECT
  (`unnest($1::text[]) WITH ORDINALITY` + `vec_txt::vector` cast) +
  1× `executemany`. `save_fact` retained as D-12 wrapper.
  ExtractorAgent migrated. Benchmark: p50 25.31 ms → 5.51 ms with MagicMock
  embedder (speedup 19.80 ms; ~123 ms expected on real bge-m3).

### Phase 28 — Doc Sweep + v1.7 Release (DOC-01)

- **DOC-01** — `docs/RUNBOOK.md` (new operational reference); this release
  notes file; `.planning/REQUIREMENTS-v1.8.md` scaffold (7 backlog items
  pre-seeded); README + ARCHITECTURE + memory-eviction.md surgically
  refreshed; v1.7 archive + MILESTONES.md backfill.

---

## Ops Impact

What changes in a running deployment:

**TD-01 — `audit_log` self-bootstraps on cold start.**
Fresh PostgreSQL cluster operators no longer need to run manual DDL before
starting the service. The table is created on the first audit-write.
INSERT-ONLY invariant is enforced at bootstrap; no UPDATE or DELETE grants
are issued.

**TD-03 — asyncpg DSN `?ssl=disable` strip is centralized.**
All modules that open asyncpg pools now go through
`utils/asyncpg_helper.prepare_dsn`. Any new module that opens its own
asyncpg pool should import the helper rather than stripping the parameter
inline.

**TD-07 — bge-m3 loads from the vanilla HuggingFace cache layout.**
Pre-download with:
```bash
huggingface-cli download BAAI/bge-m3 --local-dir "$MODEL_DIR/BAAI/bge-m3"
```
Or rely on first-use auto-download. The legacy symlink workaround
(`{MODEL_DIR}/embedding_models/bge-m3/` → vanilla cache) is no longer
required; the resolver handles both paths.

**TD-06 — Unit suite runs without live Redis.**
The `redis_mock` fixture in `tests/conftest.py` intercepts all
`utils.cache.get_redis` calls when `@pytest.mark.uses_redis` is present.
Integration tests that genuinely need Redis remain un-mocked.

**TD-04 — Near-duplicate save audit metric (audit-mode only in v1.7).**
`save_fact` / `save_facts` emit a `MEMORY_NEAR_DUPLICATE_SKIPPED` audit row
when an embedding is within cosine distance `MEMORY_NEAR_DUPLICATE_THRESHOLD`
(default 0.05) of an existing fact. **Critical: the INSERT still runs in v1.7
— this is audit-mode only**, applying the v1.6 EVICT-02 audit-mode-before-enforce
discipline to the deduplication path (v1.7 D-09). v1.8 will promote this to
silent-skip with TOCTOU mitigation — see
[SK-01](../.planning/REQUIREMENTS-v1.8.md) and
[TOC-01](../.planning/REQUIREMENTS-v1.8.md).

Operators tuning the threshold should observe the audit-row volume first
before assuming v1.8 silent-skip will drop the same fraction.

---

## Upgrade Notes

**None required.** v1.7 is a zero-prod-behavior-change milestone. Existing
deployments upgrade by pulling the v1.7.0 tag; no database migration, no
config change, no API change required.

Optional: rebuild your test base image with `fakeredis` available if your CI
runs the unit suite without a live Redis instance (see `pyproject.toml` dev
deps for the `fakeredis` entry added in Phase 27).

---

## Breaking Changes

**None.** Public API surface unchanged:

| Endpoint | Status |
|----------|--------|
| `POST /api/v1/query` | unchanged |
| `GET /query/stream` | unchanged |
| `POST /agent/v1/run/stream` | unchanged |
| `POST /ingest` | unchanged |
| `POST /ingest/async` | unchanged |
| `GET /ingest/status/{task_id}` | unchanged |
| `POST /memory/forget` | unchanged |

`LongTermMemory.save_fact` signature unchanged — it is now a thin wrapper
around `save_facts([...])`. The embed-failure raise contract is preserved.

---

> Full diff: [v1.6.0...v1.7.0](https://github.com/rothenbergverkuilenrn60-oss/rag-enterprise/compare/v1.6.0...v1.7.0).
> Changelog: [CHANGELOG.md](../CHANGELOG.md).
> Tag ceremony: [.planning/milestones/v1.7-release-tag.md](../.planning/milestones/v1.7-release-tag.md) (planning-internal).
