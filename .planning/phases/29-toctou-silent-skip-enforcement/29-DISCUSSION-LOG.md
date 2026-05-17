# Phase 29 — Discussion Log

**Phase:** 29 — TOCTOU + Silent-Skip Enforcement
**Date:** 2026-05-17
**Mode:** default (no flags)
**Skills:** /gsd-discuss-phase

For human reference only. NOT consumed by downstream agents (researcher, planner, executor) — `29-CONTEXT.md` is the canonical decision record.

---

## Round 1 — Core strategy decisions

### Q1: TOC-01 strategy — close precheck/INSERT race?

**Options presented:**
1. Advisory lock (Recommended) — `pg_advisory_xact_lock(hashtext(user_id||tenant_id))` wraps precheck+INSERT atomically. Zero schema migration. Preserves cosine-semantic dedupe.
2. ON CONFLICT DO NOTHING — Add `UNIQUE(user_id, tenant_id, MD5(fact))` constraint + DB-enforced uniqueness. Schema migration + backfill. Only catches exact-text dups.
3. WITH ... INSERT RETURNING — Single CTE round-trip combining precheck SELECT + conditional INSERT. Awkward to express cosine-distance gate; loses executemany batching.

**Selection:** Advisory lock (Recommended)

**Notes:** Confirms project preference for low-migration paths. Cosine-semantic dedupe preservation is the deciding factor — ON CONFLICT would force a 2-layer guard (DB exact-text + app cosine). Single-layer lock-serialized precheck is cleaner.

### Q2: If ON CONFLICT path chosen — uniqueness key shape?

**Options presented:**
1. N/A — Advisory Lock chosen
2. `(user_id, tenant_id, MD5(fact))`
3. `(user_id, tenant_id, embedding)` approx-uniq
4. `(user_id, tenant_id, fact)` raw text

**Selection:** `(user_id, tenant_id, MD5(fact))`

**Notes:** User chose this DESPITE picking advisory_lock in Q1. Interpreted as a fallback preference: IF future migration to DB-enforced uniqueness becomes necessary (v1.9+ defense-in-depth), use this shape. Captured in CONTEXT.md > Deferred Ideas.

### Q3: SK-01 — does audit row still fire on silent skip?

**Options presented:**
1. Yes, keep `MEMORY_NEAR_DUPLICATE_SKIPPED` (Recommended) — ops-visibility carry-forward from v1.7 D-09.
2. No, drop audit on silent skip — reduce audit volume; lose dashboard signal.

**Selection:** Yes, keep `MEMORY_NEAR_DUPLICATE_SKIPPED` (Recommended)

**Notes:** Aligns with v1.6 EVICT-02 → v1.7 D-09 → v1.8 SK-01 lifecycle. Only the INSERT side changes between audit-mode and silent-skip.

### Q4: TEST-INFRA-02 — test file strategy?

**Options presented:**
1. Rewrite-in-place (Recommended) — modify existing `tests/unit/memory/test_save_facts_batch_dedupe.py`; rename v1.7 pin test.
2. New parallel test file — keep v1.7 tests until SK-01 ships, then delete.
3. Defer test choice to planner.

**Selection:** Rewrite-in-place (Recommended)

**Notes:** Cleaner git blame for v1.8 changes — file is the canonical test surface for dedupe behavior. v1.7 pin test renamed `..._inserts_all_rows` → `..._inserts_non_dup_rows_only`.

---

## Round 2 — Implementation detail decisions

### Q5: Advisory lock granularity?

**Options presented:**
1. Per `(user_id, tenant_id)` (Recommended) — `hashtext($1 || '|' || $2)`; concurrent (user, tenant) pairs run in parallel.
2. Per `user_id` only — `hashtext($1)`; cross-tenant for same user blocks.
3. Two-arg lock `(user_hash, tenant_hash)` — PG's two-int variant; finer-grained, harder to read.

**Selection:** Per `(user_id, tenant_id)` (Recommended)

**Notes:** Matches v1.6 RLS scope. `|` separator chosen to prevent collision between (`alice`, `tcorp`) and (`alicetcorp`, `''`).

### Q6: Add belt-and-suspenders DB UNIQUE constraint anyway?

**Options presented:**
1. No — advisory_lock alone is sufficient (Recommended)
2. Yes — add `UNIQUE(user_id, tenant_id, md5(fact))`

**Selection:** No — advisory_lock alone is sufficient (Recommended)

**Notes:** Scope discipline. Defense-in-depth deferred to v1.9+ if manual SQL writers become a real threat surface.

### Q7: Phase 29 plan structure — how to split work?

**Options presented:**
1. 3 plans, TDD per req (Recommended) — Wave 1: 29-00 TOC-01. Wave 2 parallel: 29-01 SK-01 + 29-02 TEST-INFRA-02.
2. 2 plans — TOC+SK combined.
3. Single plan, sequential tasks.

**Selection:** 3 plans, TDD per req (Recommended)

**Notes:** Per-req plan boundaries match v1.7 phase 27 pattern. Each plan has its own SUMMARY for traceability.

### Q8: TDD discipline for Phase 29?

**Options presented:**
1. Strict TDD (RED → GREEN → REFACTOR) (Recommended) — project standard from v1.6/v1.7.
2. Top-down (implement first, tests follow) — faster but no failing-test gate.

**Selection:** Strict TDD (RED → GREEN → REFACTOR) (Recommended)

**Notes:** Matches Plan 27-04 cadence (failing test commit → impl commit → optional refactor commit).

---

## Deferred Ideas (Noted for Later)

- **`UNIQUE(user_id, tenant_id, md5(fact))` defense-in-depth** — v1.9+ if manual SQL writers become a threat surface. Shape locked at v1.8 discussion per user pref.
- **pgvector `embedding_hash` column for binary-uniqueness** — academic until a real cosine-false-negative surfaces.
- **Lock contention metric** — emit `pg_stat_activity`-style timing for lock-wait events. Out of v1.8 scope.

## Claude's Discretion (no decision needed — captured in CONTEXT.md)

- TDD test file naming convention (existing `tests/unit/memory/test_*` pattern).
- Logger level for lock-contention diagnostics (`logger.debug`).
- `pool.acquire(timeout=...)` for lock wait (default asyncpg behavior).
- Commit message convention (existing `feat(29-NN):` / `test(29-NN):` / `docs(29-NN):` pattern).

## Scope Creep Surfaced

None. All proposed gray areas mapped directly to TOC-01 / SK-01 / TEST-INFRA-02 requirements.
