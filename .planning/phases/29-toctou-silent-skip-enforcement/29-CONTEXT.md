# Phase 29 — TOCTOU + Silent-Skip Enforcement — Context

**Phase:** 29
**Milestone:** v1.8 Production Hardening Round 2
**Requirements:** TOC-01, SK-01, TEST-INFRA-02
**Status:** Discussed 2026-05-17 — ready for `/gsd-plan-phase 29`

## Phase Goal (from ROADMAP)

Close the precheck/INSERT race on `LongTermMemory.save_facts`, then promote v1.7 near-duplicate audit-mode (D-09) to silent-skip enforcement. Rewrite precheck unit tests against the bulk-SELECT shape (same code paths).

## Decisions Captured

### TOC-01: TOCTOU mitigation strategy

**Decision:** PostgreSQL advisory locks — `pg_advisory_xact_lock(hashtext($1 || '|' || $2))` where `$1 = user_id`, `$2 = tenant_id`. Wrap the existing precheck SELECT + `executemany` INSERT atomically inside the transaction holding the lock.

**Rationale:**
- Zero schema migration (no UNIQUE constraint, no backfill).
- Preserves cosine-semantic dedupe (vs `ON CONFLICT DO NOTHING` which only catches exact-text matches).
- Auto-released at txn end — no manual unlock bookkeeping.
- Per-user concurrency in this codebase is light; lock contention is acceptable.

**Rejected alternatives:**
- **`INSERT ... ON CONFLICT DO NOTHING`** — only catches exact-text duplicates; cosine precheck would still be needed for semantic dedupe. Requires schema migration + dedupe backfill. Doubles plan complexity for a strictly weaker guarantee.
- **`WITH ... SELECT ... INSERT ... RETURNING` single round-trip** — clean in theory, but expressing the cosine-distance precheck inside a CTE that gates `executemany` is awkward (loses batching). Hard to read.

### Lock granularity

**Decision:** Per `(user_id, tenant_id)` via `hashtext($1 || '|' || $2)`. The `|` separator prevents collision between (`alice`, `tcorp`) and (`alicetcorp`, `''`). Concurrent writes for different (user, tenant) pairs run in parallel.

**Rejected:** Per-`user_id`-only (cross-tenant blocks for same user_id — rare but possible). Two-arg `pg_advisory_xact_lock(int, int)` variant (marginal hashing benefit; harder to read).

### Belt-and-suspenders DB UNIQUE constraint

**Decision:** NO. Advisory lock alone satisfies TOC-01 acceptance (concurrent integration test). Adding `UNIQUE(user_id, tenant_id, md5(fact))` would add schema migration + backfill complexity for a redundant guarantee. Out of v1.8 scope.

**Future v1.9+ consideration:** If manual SQL writers (CLI scripts, ad-hoc admin ops) become a real threat surface, revisit.

### SK-01: Silent-skip audit semantics

**Decision:** When `_is_near_duplicate` returns `True` for a candidate, the candidate is filtered from `rows_to_insert` AND `MEMORY_NEAR_DUPLICATE_SKIPPED` audit row still fires.

**Rationale:** Carry-forward from v1.7 D-09 — audit-mode metric persists post-enforcement for ops dashboard signal (dup-rate visibility). Only the INSERT side changes between v1.7 audit-mode and v1.8 silent-skip.

### TEST-INFRA-02: Test file strategy

**Decision:** Rewrite-in-place in existing files. Primary target: `tests/unit/memory/test_save_facts_batch_dedupe.py`. The v1.7 pin test `test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows` is renamed to `..._inserts_non_dup_rows_only` and its assertion shape flips: `executemany` call args must contain only non-duplicate rows. Bulk-SELECT mock pattern + `nearest_distance=None` branch coverage added per req acceptance.

**Per-file LOC delta:** ≤ +150 (req acceptance bound).

### Plan structure

**Decision:** 3 plans across 2 waves with strict TDD per plan.

| Plan | Wave | Type | Requirement | Depends On |
|------|------|------|-------------|------------|
| 29-00 | 1 | TDD | TOC-01 | — |
| 29-01 | 2 | TDD | SK-01 | 29-00 |
| 29-02 | 2 | execute | TEST-INFRA-02 | 29-00 |

**Rationale:**
- Wave 1 ships TOC-01 first because SK-01's silent-skip becomes safe only after the race window closes.
- Wave 2 parallel: SK-01 (modifies INSERT-side filter) and TEST-INFRA-02 (rewrites tests against the same code paths) touch overlapping but non-conflicting surfaces. Plan 29-02 reads the new SK-01 shape via 29-01 file deltas at execution time; if 29-01 is incomplete when 29-02 starts, planner serializes them.
- TDD plans 29-00 and 29-01 follow RED → GREEN → REFACTOR. Each plan commits a failing test (RED), then the implementation that turns it green (GREEN), then optional refactor.

### TDD discipline

**Decision:** Strict TDD (RED → GREEN → REFACTOR) per project standard. Matches v1.6 / v1.7 phases (Plan 27-04 baseline). Each TDD plan commits at minimum: test-RED commit + impl-GREEN commit; refactor optional.

## Carry-Forward Decisions (still in force)

These bind Phase 29 implementation regardless of fresh decisions above:

| Decision | Source | Why it matters going forward |
|----------|--------|------------------------------|
| INSERT-ONLY `audit_log` invariant | v1.0 Phase 2 | `MEMORY_NEAR_DUPLICATE_SKIPPED` write must NOT add UPDATE/DELETE grants |
| Audit-mode-before-enforce | v1.6 Phase 25 EVICT-02 | Pre-Phase 29 state IS audit-mode; SK-01 promotes to enforce per this discipline (full lifecycle: v1.6 EVICT-02 → v1.7 D-09 → v1.8 SK-01) |
| Audit-write failure must NOT block destructive action | v1.6 Phase 25 T1 | Silent-skip enforcement = destructive (we're suppressing rows); audit-write failure here still must not block the skip |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC | v1.1 Phase 8 / v1.6 Phase 24 | Bulk-SELECT precheck inside advisory lock keeps the GUC discipline |
| Mock at consumer path (`services.<mod>.<dep>`) | v1.3 Phase 13+15 | TEST-INFRA-02 mocks at `services.memory.memory_service.<dep>` not at source |
| `diff-cover ≥ 80%` on touched files | v1.1 Phase 10 TEST-03 | All 3 plans must clear gate |
| Combined coverage `--fail-under=70` global floor | v1.3 Phase 15 / v1.5 Phase 22 | Phase 29 must not regress global floor |
| `create_app()` factory pattern for tests | v1.7 Phase 27 TD-02 | Integration test for TOC-01 (concurrent writers) constructs isolated app via `tests/factories/app.py::create_app()` |
| Narrow exception types (no bare `except`) | v1.0 ERR-01 | Lock acquisition errors caught as `asyncpg.PostgresError`, not bare |
| Pydantic V2 + mypy --strict + ruff | CLAUDE.md | Any new module conforms |

## Codebase Anchors

| Asset | Path / Line | Why it matters |
|-------|-------------|----------------|
| `LongTermMemory.save_facts` | `services/memory/memory_service.py:566-717` | Body where lock wraps precheck+INSERT |
| `LongTermMemory._is_near_duplicate` | `services/memory/memory_service.py:435-528` | Precheck SELECT — bulk variant at lines 530-563 (C1 SQL `unnest($1::text[]) WITH ORDINALITY`) |
| `executemany` INSERT call | `services/memory/memory_service.py:699` | INSERT-side filter for SK-01 happens upstream of this line |
| C3 D-09 audit fire | `services/memory/memory_service.py:505` (action=`MEMORY_NEAR_DUPLICATE_SKIPPED`) | Audit row emission — kept by SK-01 decision |
| v1.7 pin test (audit + insert ALL) | `tests/unit/memory/test_save_facts_batch_dedupe.py::test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows` | TEST-INFRA-02 rewrites this; rename to `..._inserts_non_dup_rows_only` |
| `save_fact` D-12 wrapper | `services/memory/memory_service.py:719-759` | Inherits SK-01 behavior via `save_facts([extracted])` delegation — no separate change needed |
| `long_term_facts` schema | `services/memory/memory_service.py:276-285` | UUID PK, no UNIQUE constraint, embedding vector(1024), HNSW cosine index |
| `create_app()` factory | `tests/factories/app.py` | TOC-01 integration test uses this for parallel writers |
| ON CONFLICT precedent (audit) | `services/audit/audit_service.py:346` (`ON CONFLICT (event_id) DO NOTHING`) | Reference pattern for any future schema-UNIQUE move |
| ON CONFLICT precedent (memory) | `services/memory/memory_service.py:347` (user_profiles `ON CONFLICT (user_id) DO UPDATE`) | Reference pattern (not adopted here) |

## Canonical Refs

- `.planning/ROADMAP.md` (Phase 29 SC-1..3 + v1.8 carry-forward gates)
- `.planning/REQUIREMENTS.md` (TOC-01 / SK-01 / TEST-INFRA-02 acceptance bullets)
- `.planning/PROJECT.md` (v1.8 milestone goal + carried context)
- `.planning/milestones/v1.7-phases/27-test-isolation-memory-reliability/27-04-SUMMARY.md` (v1.7 save_facts batch path — baseline this phase modifies)
- `.planning/milestones/v1.7-phases/27-test-isolation-memory-reliability/27-VERIFICATION.md` (C1/C2/C3/D-09 pinning evidence; verifier nominated `test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows` as the v1.7 audit-mode pin)
- `.planning/milestones/v1.7-phases/27-test-isolation-memory-reliability/deferred-items.md` (TEST-INFRA-01 root cause; not in scope for Phase 29 — that's Phase 30)
- `./CLAUDE.md` + `Claude.md` (production standards — Pydantic V2 / mypy --strict / no bare except / tenacity / structured logging)

## Acceptance (Phase Success Criteria — from ROADMAP)

1. **TOC-01 concurrent-test:** Two parallel `save_facts` writers with same `(user_id, tenant_id)` + fact text → exactly 1 row in `long_term_facts`. Either 1 or 2 `MEMORY_NEAR_DUPLICATE_SKIPPED` audit rows (depending on race interleaving — both interpretations acceptable).
2. **SK-01 silent skip:** When `_is_near_duplicate` returns `True`, candidate excluded from `rows_to_insert`; `executemany` inserts only non-duplicate rows; `MEMORY_NEAR_DUPLICATE_SKIPPED` audit row still emitted with original action shape. v1.7 pin test renamed + assertion flipped.
3. **TEST-INFRA-02 test rewrite:** Tests assert C1 SQL shape (`unnest($1::text[]) WITH ORDINALITY` + `vec_txt::vector` cast); `nearest_distance=None` branch covered explicitly; per-file LOC delta ≤ +150; no production-code changes from this plan alone.

## Constraints

- **No schema migration** (advisory_lock path chosen).
- **No production-code change in plan 29-02** (test-only).
- **Carry-forward gates** apply (diff-cover ≥ 80%, --fail-under=70, INSERT-ONLY audit_log).
- **No bare `except`** (narrow `asyncpg.PostgresError` etc.).
- **mypy --strict** on every new/touched file (note: Phase 30 will sweep accumulated violations; Phase 29 must not ADD new ones).
- **Mock at consumer path** for unit tests.

## Open Risks / Watch-outs

- **Lock acquisition during long-running embed_batch**: `embed_batch` is the slow step (~100ms+ for 5 facts). Lock must be acquired AFTER embedding completes, not before — otherwise per-user write throughput drops to 1/embed_time. Plan: embed first (no lock), then acquire lock, then precheck+INSERT inside lock.
- **Test concurrency mechanism**: integration test for TOC-01 needs real PG + 2 connections from the same pool. Use `asyncio.gather` with 2 `create_app()` instances (each owning its own pool) to simulate cross-worker race. Single-pool variant won't trigger the race because asyncpg pool may serialize.
- **`save_fact` wrapper edge cases**: D-12 delegation means `save_fact` automatically inherits silent-skip. Existing `save_fact` unit tests at `tests/unit/test_memory_save_fact.py` may break — verify before commit. Expected behavior: `save_fact` with a duplicate-text returns `saved_count=0` (was `saved_count=1` in v1.7 audit-mode); update assertion or wrap in a v1.7-vs-v1.8 fixture.
- **Audit-write failure handling**: keep v1.6 T1 discipline — `MEMORY_NEAR_DUPLICATE_SKIPPED` audit-write failure does NOT block the skip-INSERT path. Log + continue.

## Claude's Discretion (no decision needed)

- TDD test file naming (use `tests/unit/memory/test_*` convention per v1.7).
- Logger level for lock-contention info (use `logger.debug` — high-frequency in busy tenants).
- Whether to add a `pool.acquire(timeout=...)` for lock wait (default asyncpg behavior is acceptable; revisit if integration test surfaces hangs).
- Commit message convention (existing `feat(29-NN):` / `test(29-NN):` / `docs(29-NN):` pattern).

## Deferred Ideas (Noted for Later)

- Defense-in-depth `UNIQUE(user_id, tenant_id, md5(fact))` constraint (v1.9+ if manual writers become a threat surface).
- pgvector `embedding_hash` column for binary-uniqueness across cosine-equal vectors (academic; not actionable until we see a real false-negative).

## Next Action

```
/clear
/gsd-plan-phase 29
```

Optional pre-plan: `/gsd-plan-phase 29 --research` to spawn `gsd-phase-researcher` first (default for this project's config). Skip with `--skip-research` if the codebase anchors above are sufficient — likely yes given the surgical scope.
