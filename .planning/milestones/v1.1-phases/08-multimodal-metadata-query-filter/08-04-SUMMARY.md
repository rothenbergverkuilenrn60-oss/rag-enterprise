---
phase: 08-multimodal-metadata-query-filter
plan: 04
subsystem: vector-store
type: execute
wave: 2
requirements:
  - META-02
tags:
  - phase-8
  - vector-store
  - pgvector
  - hnsw
  - filtered-recall
  - meta-02
dependency_graph:
  requires:
    - "08-01: ChunkMetadata.section_id/section_title fields, settings.pgvector_ef_search_filtered, RED test scaffolds"
  provides:
    - "PgVectorStore.search(filters={…}) with HNSW iterative_scan + parameterised JSONB WHERE"
    - "Module-level _build_filter_where(filters, start_param) helper"
    - "B-tree partial expression indexes on metadata->>'page_number' and metadata->>'section_id'"
  affects:
    - "services/retriever/* (downstream caller — unchanged API; gains filtered recall when filters dict is passed)"
    - "services/pipeline.py (no signature change; query path can pass filters from 08-02 extractor once 08-05 wiring lands)"
tech_stack:
  added: []
  patterns:
    - "asyncpg $N parameterisation for filter VALUES (T-08-01 mitigation)"
    - "Python repr() of trusted-string KEY for JSONB extraction expression (no user-controlled key path)"
    - "SET LOCAL inside conn.transaction() for per-transaction GUC scope (Pitfall #5)"
    - "Partial B-tree indexes WHERE … IS NOT NULL — legacy chunks free of index footprint"
    - "page_number=0 sentinel strip — image_extractor 'unknown' page does not broadcast-match (T-08-09)"
key_files:
  created: []
  modified:
    - "services/vectorizer/vector_store.py"
decisions:
  - "Pre-existing F401 (utils.logger.log_latency unused import) left in place — pre-dates Phase 8 (commit e9601c9, Phase 01); fixing it is out-of-scope for META-02 and would touch a Phase 1 line. Logged as deferred."
  - "Wave 0 RED tests (tests/integration/test_pgvector_filtered_recall.py) hardcode embedding=[0.1*…]*384 but the live PgVectorStore is built at settings.embedding_dim=1024. The tests fail on upsert with `expected 1024 dimensions, not 384` BEFORE search is exercised. Fixing the test fixtures is out-of-scope per orchestrator hard rule 'Do NOT modify tests'. Instead, GREEN status was verified end-to-end via a temporary smoke harness (/tmp/smoke_08_04.py — not committed) that exercises the same store path with dim=64 (mirroring the existing test_pgvector_recall.py pattern at line 32+70). All 6 META-02 behaviours verified live. The RED→GREEN handoff for those 3 RED tests is deferred to a subsequent test-fixup commit (out of plan 08-04 scope)."
  - "EXPLAIN output captured against a 50-row table shows Seq Scan rather than HNSW index scan — pgvector's planner correctly avoids the index for tiny tables. The iterative_scan + ef_search GUCs are accepted by the server (no error) and the parameterised WHERE clause renders correctly. Production-scale recall benefit will activate naturally when the table exceeds the planner's HNSW threshold."
metrics:
  duration: "8m 1s"
  completed: "2026-05-08T03:33:49Z"
  tasks_completed: 2
  files_modified: 1
  commits: 2
---

# Phase 8 Plan 04: PgVectorStore Filter WHERE + Session GUC (META-02) Summary

JSONB-filtered HNSW search lands in `PgVectorStore`: `_build_filter_where` helper, three partial B-tree expression indexes, and `search()` extended with `SET LOCAL hnsw.iterative_scan = 'relaxed_order'` plus `SET LOCAL hnsw.ef_search = settings.pgvector_ef_search_filtered`. Filter VALUES travel as asyncpg `$N` parameters; KEYS are `repr`'d from trusted string literals only.

## What Landed

### Task 1 — `_build_filter_where` helper + B-tree expression indexes

Module-level pure function added above `class PgVectorStore`:

```python
def _build_filter_where(
    filters: dict[str, int | str],
    start_param: int = 3,
) -> tuple[str, list[int | str]]:
```

Behaviour:

| Input | Output |
|-------|--------|
| `{}` | `("", [])` |
| `{"page_number": 63}` | `("WHERE (metadata->>'page_number')::int = $3", [63])` |
| `{"section_id": "3.10"}` | `("WHERE metadata->>'section_id' = $3", ["3.10"])` |
| `{"page_number": 63, "section_id": "3.10"}` | `("WHERE … AND …", [63, "3.10"])` |
| `{"x": True}` | `("", [])` (bool guard prevents int branch routing) |
| `{"x": object()}` | `("", [])` (unknown types skipped silently) |

`create_collection` now creates three new partial indexes after the RLS policy block:

```sql
CREATE INDEX IF NOT EXISTS {table}_page_idx
    ON {table} USING btree ((metadata->>'page_number'))
    WHERE metadata->>'page_number' IS NOT NULL;
CREATE INDEX IF NOT EXISTS {table}_page_int_idx
    ON {table} USING btree (((metadata->>'page_number')::int))
    WHERE metadata->>'page_number' IS NOT NULL;
CREATE INDEX IF NOT EXISTS {table}_section_idx
    ON {table} USING btree ((metadata->>'section_id'))
    WHERE metadata->>'section_id' IS NOT NULL;
```

Verified via `pg_indexes` query in smoke harness — all three present on a freshly-created table.

### Task 2 — `PgVectorStore.search` extended

```python
@retry(stop=stop_after_attempt(3), wait=wait_random_exponential(multiplier=1, max=8))
async def search(self, query_vector, top_k, tenant_id="", filters=None):
    # T-08-09: strip page_number=0 sentinel (unknown-page broadcast guard)
    effective_filters = {k: v for k, v in (filters or {}).items()
                         if not (k == "page_number" and v == 0)}
    where_clause, filter_params = _build_filter_where(effective_filters, start_param=3)
    has_filter = bool(where_clause)

    pool = await self._get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # D-02: tenant scope FIRST — must precede the GUC + SELECT.
            await conn.execute("SELECT set_config('app.current_tenant', $1, true)", tenant_id)
            if has_filter:
                ef_search = int(getattr(settings, "pgvector_ef_search_filtered", 200))
                await conn.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
                await conn.execute(f"SET LOCAL hnsw.ef_search = {ef_search}")
            rows = await conn.fetch(
                f"""
                SELECT chunk_id, doc_id, content, metadata,
                       1 - (embedding <=> $1::vector) AS score
                FROM {self._table}
                {where_clause}
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                query_vector, top_k, *filter_params,
            )
    # … existing JSONB string→dict mapping unchanged …
```

## SQL Shape — Filtered vs Unfiltered

**Unfiltered** (`filters=None`, or `filters={"page_number": 0}` after sentinel strip):

```sql
-- inside conn.transaction()
SELECT set_config('app.current_tenant', $1, true);
SELECT chunk_id, doc_id, content, metadata,
       1 - (embedding <=> $1::vector) AS score
FROM {table}

ORDER BY embedding <=> $1::vector
LIMIT $2;
```

No GUC mutation. SQL shape and result ordering identical to pre-Phase-8 baseline (REQ A-4 #5 satisfied).

**Filtered** (`filters={"page_number": 63}`):

```sql
-- inside conn.transaction()
SELECT set_config('app.current_tenant', $1, true);
SET LOCAL hnsw.iterative_scan = 'relaxed_order';
SET LOCAL hnsw.ef_search = 200;        -- value from settings.pgvector_ef_search_filtered
SELECT chunk_id, doc_id, content, metadata,
       1 - (embedding <=> $1::vector) AS score
FROM {table}
WHERE (metadata->>'page_number')::int = $3
ORDER BY embedding <=> $1::vector
LIMIT $2;                              -- args: query_vector, top_k, 63
```

## Index Plan (EXPLAIN ANALYZE on 50-row test fixture)

Captured via temporary harness `/tmp/explain_08_04.py` (not committed):

```
Filtered query (page_number=85) WITH iterative_scan + ef_search=200:
  Limit  (cost=6.01..6.02 rows=1)
    -> Sort
      Sort Key: ((embedding <=> '[…]'::vector))
      -> Seq Scan on phase8_explain_meta02
            Filter: (((metadata ->> 'page_number'::text))::integer = 85)
            Rows Removed by Filter: 49
  Execution Time: 0.018 ms
```

Note: pgvector's planner selects Seq Scan rather than the HNSW index because the table is only 50 rows; the cost model favors a full scan at this size. With production-scale data the HNSW path activates and the iterative_scan GUC bounds expansion via the configured `ef_search`. The GUCs are accepted by the server with no error and the parameterised WHERE renders correctly — both confirmed in the same EXPLAIN run.

## RLS-Precedence Verification

Statement order inside the search transaction (verified by code inspection at `services/vectorizer/vector_store.py` lines 248-291):

1. `set_config('app.current_tenant', $1, true)` — D-02 tenant scope (RLS policy attaches to `tenant_id = current_setting('app.current_tenant', true)`)
2. `SET LOCAL hnsw.iterative_scan = 'relaxed_order'` — only when `has_filter` (META-02)
3. `SET LOCAL hnsw.ef_search = {int(settings.pgvector_ef_search_filtered)}` — only when `has_filter` (META-02)
4. `SELECT … FROM {table} {where_clause} ORDER BY embedding <=> $1 LIMIT $2`

The RLS predicate is implicitly ANDed by the planner into every SELECT against `{table}`. The user-supplied filter WHERE is appended AFTER the table reference, so the planner sees:

```
WHERE tenant_id_isolation_predicate AND (metadata->>'page_number')::int = $3
```

No ordering of `SET LOCAL` can remove the RLS predicate (it is a stored policy on the table, not a session GUC). T-08-05 mitigated.

## Filter Injection Surface (T-08-01) — Audit

| Surface | Source | Sanitisation |
|---------|--------|--------------|
| Filter VALUE | caller (extractor / tenant merge) | asyncpg `$N` parameter. Never string-interpolated. |
| Filter KEY | code-internal literal in `_build_filter_where` | `repr(key)` of a Python str literal — keys are `'page_number'` / `'section_id'` only, never sourced from user input. |
| `ef_search` value | `settings.pgvector_ef_search_filtered` (config-loaded int) | `int(...)` cast — only safe f-string surface in the entire search path. |
| Table name | `self._table` (constructed from `settings.qdrant_collection`) | Pre-existing pattern — same surface as Phase 1 baseline. |

## Verification

### Automated (run locally with PG available)

```bash
.venv/bin/pytest tests/unit/test_pgvector_store.py -x -q
# 8 passed in 0.07s — no regression

.venv/bin/ruff check services/vectorizer/vector_store.py
# 1 pre-existing F401 (utils.logger.log_latency); no new errors. See Deferred Issues.

.venv/bin/mypy --strict services/vectorizer/vector_store.py
# 21 errors — IDENTICAL to pre-edit baseline. No new type errors introduced.
```

### Live-PG smoke (temporary `/tmp/smoke_08_04.py`, dim=64; not committed)

| Behaviour | Result |
|-----------|--------|
| Three new B-tree indexes present in `pg_indexes` after `create_collection` | PASS |
| `filters={"page_number": 63}` returns only `sm2`, all rows page=63 | PASS |
| `filters={"section_id": "3.10"}` returns sm2 | PASS |
| `filters={"page_number": 0}` (sentinel) behaves identically to `filters=None` (5 rows) | PASS |
| `filters=None` returns all 5 chunks (unfiltered baseline unchanged) | PASS |
| `filters={"page_number": 63, "section_id": "3.10"}` returns sm2 with both fields matching | PASS |
| Legacy chunk (no section_id) excluded from `filters={"section_id": "3.10"}` | PASS |
| Same legacy chunk returned by `filters=None` | PASS |

### Verification — Deferred

- **`tests/integration/test_pgvector_filtered_recall.py` (3 RED tests, Wave 0):** the test fixtures hardcode `embedding=[0.1 * (i + 1)] * 384` but the live `PgVectorStore` builds the table at `vector(1024)` from `settings.embedding_dim=1024`. The upsert call raises `DataError: expected 1024 dimensions, not 384` BEFORE `search()` is exercised. The orchestrator hard rule "Do NOT modify tests" prevents fixing the dim in this plan. Recommended follow-up commit: align the three fixtures with the existing `test_pgvector_recall.py` pattern (set `store._dim = DIM_TEST` and use `[…] * DIM_TEST` for embeddings). Once that lands, the three tests will GREEN against the existing META-02 implementation — verified equivalent behaviour via the smoke harness above.
- **`tests/integration/test_pgvector_recall.py::test_recall_at_10`:** pre-existing failure (asserts `0.0 >= 0.95` because `recall_test_table` keeps stale dim=1024 data across runs). Reproduced on master pre-edit. Out of scope.

### Manual — when PG is reachable

```python
await store.create_collection()
# psql -c "\d {store._table}" shows three new index entries:
#   {table}_page_idx, {table}_page_int_idx, {table}_section_idx
# Plus the original _vec_idx (HNSW), _doc_idx, _pkey.

await store.search([0.1]*1024, top_k=3, filters={"page_number": 63})
# Returns ≤3 rows whose metadata.page_number == 63.
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Mypy strict generic typing on helper signatures**

- **Found during:** Task 1 verification (`mypy --strict` showed 23 errors vs pre-edit baseline of 21)
- **Issue:** Plan-specified return type `tuple[str, list]` and local var `params: list = []` triggered `Missing type parameters for generic type "list" [type-arg]` under `mypy --strict`.
- **Fix:** Parameterised both as `list[int | str]` to match the input dict's value union. Behaviour identical; the change only narrows the inferred type.
- **Files modified:** services/vectorizer/vector_store.py (helper signature + local var)
- **Commit:** `7d7529c`

### Asked / Out of Scope

**1. Wave 0 RED test dim mismatch (test fixtures use 384 against a 1024-dim live table)**

- Not auto-fixed: orchestrator hard rule forbids modifying tests in this plan.
- Verified the META-02 implementation works via temporary smoke harness with dim=64 (matching the existing recall test pattern). Documented in **Verification — Deferred**.

## Deferred Issues

### Pre-existing F401 in `services/vectorizer/vector_store.py:15`

```
from utils.logger import log_latency
```

`log_latency` was imported in commit `e9601c9` (Phase 01-02 PgVectorStore implementation, 2026-04-21) and never used. `ruff check` reports it as `F401 unused import`. The plan acceptance criterion "ruff exits 0" is therefore impossible without touching a Phase 1 line that is unrelated to META-02. Per scope-boundary rule (only auto-fix issues directly caused by current task's changes), the import is left in place. Recommended cleanup: a separate `chore(vector_store): drop unused log_latency import` commit not coupled to a feature plan.

## Threat Surface Scan

No new trust-boundary surface introduced beyond what the plan's `<threat_model>` already addresses. The implementation tracks every threat:

- T-08-01 — value parameterisation + key repr — VERIFIED (audit table above)
- T-08-02 — `iterative_scan='relaxed_order'` + bounded `ef_search` — VERIFIED (SET LOCAL inside transaction)
- T-08-05 — RLS precedence — VERIFIED (statement order audit above)
- T-08-09 — page_number=0 sentinel strip — VERIFIED (smoke test #4 above)
- T-08-10 — pgvector < 0.8.0 propagates via tenacity — INHERITED (deployment gate from 08-01)

No `## Threat Flags` section needed.

## Self-Check: PASSED

**Files claimed modified:**

- `services/vectorizer/vector_store.py` — FOUND (commits `7d7529c` and `b2ff175`).

**Commits claimed:**

- `7d7529c feat(08-04): add _build_filter_where helper + B-tree expression indexes` — FOUND in `git log --all`.
- `b2ff175 feat(08-04): extend PgVectorStore.search with HNSW iterative_scan + WHERE filter` — FOUND in `git log --all`.

**Acceptance criteria from plan:**

- `_build_filter_where def` (== 1) — 1 ✓
- `_page_int_idx` DDL (== 1) — 1 ✓
- `_section_idx` DDL (== 1) — 1 ✓
- `::int = $` pattern (≥ 1) — 3 ✓
- `SET LOCAL hnsw.iterative_scan = 'relaxed_order'` (== 1) — 1 ✓
- `SET LOCAL hnsw.ef_search` (== 1) — 1 ✓
- `_build_filter_where(effective_filters` (== 1) — 1 ✓
- `page_number == 0` (≥ 1) — 1 ✓
- `set_config('app.current_tenant'` (≥ 1) — 3 ✓
- `@retry(stop=stop_after_attempt(3)` on search — 1 ✓
- `except Exception` count (unchanged) — 0 (pre-edit 0) ✓
- `mypy --strict` error count (unchanged) — 21 (pre-edit 21) ✓
- `pytest tests/unit/test_pgvector_store.py` — 8 passed ✓
