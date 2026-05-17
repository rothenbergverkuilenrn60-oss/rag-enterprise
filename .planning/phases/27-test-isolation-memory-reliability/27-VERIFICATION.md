---
phase: 27-test-isolation-memory-reliability
verified: 2026-05-17T08:05:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
must_haves:
  truths:
    - "SC-1: create_app() factory exists; audit + memory integration suites use it; parallel cross-contamination test green; Phase 23/24/25 monkeypatch pattern removed (NEW tests via factory, existing tests left per D-05)."
    - "SC-2: redis_mock fixture lives in tests/conftest.py; unit suite passes without live Redis; D-22 diagnostic separates Redis-mode from openai-SDK-mode failures; no integration test force-mocked."
    - "SC-3: LongTermMemory.save_fact runs <embedding> <=> $vec < 0.05 cosine precheck and emits MEMORY_NEAR_DUPLICATE_SKIPPED audit row; per D-09 the INSERT STILL RUNS (audit-mode-only) — ROADMAP SC-3 wording 'save is skipped' is explicitly overridden in v1.7."
    - "SC-4: LongTermMemory.save_facts(list[ExtractedFact]) uses 1× embed_batch + 1× bulk dedupe SELECT + 1× executemany for N=5; bulk dedupe uses C1 SQL (unnest($1::text[]) WITH ORDINALITY + vec_txt::vector); C2 fail-fast fallback via gather(return_exceptions=True); C3 D-09 inserts ALL rows including dups; D-17 ExtractorAgent migrated."
    - "SC-5: Latency benchmark exists (tests/benchmark/test_extractor_latency.py) + 27-BENCHMARK.md artifact captured (p50/p95 baseline + new + speedup)."
---

# Phase 27: Test Isolation + Memory Reliability — Verification Report

**Phase Goal:** Make per-test isolation cheap (kill module-level singletons + roll out Redis-mock); make memory writes deduplicated and batched (cosine-precheck near-duplicate guard + `executemany` batch path).

**Verified:** 2026-05-17T08:05:00Z
**Verifier:** Claude (goal-backward)
**Re-verification:** No — initial verification.
**Status:** PASSED (5/5 SCs satisfied)

---

## Goal Achievement — Success Criteria

| # | Success Criterion | Verdict | Evidence (file:line) | Test Command + Result |
|---|-------------------|---------|----------------------|------------------------|
| SC-1 | `create_app()` factory + ≥1 audit suite + ≥1 memory suite go through it; parallel-contamination test green; Phase 23/24/25 monkeypatch pattern removed from migrated suites | PASS | `tests/factories/app.py:69-112` (factory + reset, 34-entry inventory); `main.py:370-428` (`_configure_app`); `main.py:445` (prod calls it); `tests/integration/audit/test_audit_suite_factory_migrated.py` (2 tests, uses app_factory); `tests/integration/memory/test_memory_suite_factory_migrated.py` (2 tests, uses app_factory); `tests/unit/test_parallel_contamination.py:1-end` (3 isolation tests incl. asyncio.gather variant) | `pytest tests/unit/test_app_factory.py tests/unit/test_parallel_contamination.py tests/unit/test_singleton_inventory_complete.py tests/unit/test_main_middleware_order.py` → 13/13 PASS; integration → 4/4 PASS |
| SC-2 | `redis_mock` fixture in `tests/conftest.py`; unit suite passes without live Redis; baseline Redis-ConnectionError failures → 0 (or already 0, contract-protected via subprocess gate); no integration force-mocked | PASS | `tests/conftest.py` (fakeredis-backed redis_mock fixture + `pytest_collection_modifyitems` hook); `services/memory/memory_service.py:181-183` (ShortTermMemory delegates to `utils.cache.get_redis` — single mock target); `27-02-DIAGNOSTIC.md` (D-22 pre/post counts: 0 → 0 Redis-CE on Redis-up host; subprocess gate validates Redis-down contract); `tests/unit/test_redis_mock_baseline_diagnostic.py` (subprocess regression gate test PASS) | `pytest tests/unit/test_redis_mock_fixture.py tests/unit/test_short_term_memory_get_redis.py tests/unit/test_redis_mock_baseline_diagnostic.py` → 15/15 PASS |
| SC-3 | save_fact runs `<=> $vec < 0.05` cosine precheck; near-dup → audit row emitted; **D-09 audit-mode-only — save still happens (ROADMAP wording overridden)**; ≤1 extra PG RTT; existing save tests green | PASS | `services/memory/memory_service.py:435-478` (`_is_near_duplicate` cosine + GUC discipline + ORDER BY/LIMIT 1); `services/memory/memory_service.py:480-514` (`_fire_near_duplicate_audit` staticmethod, best-effort, swallows audit-write failure); `services/memory/memory_service.py:719-759` (`save_fact` is D-12 wrapper delegating to `save_facts`); **D-09 audit-mode confirmed in batch path at 681-704** (audit fires for dups via `_fire_near_duplicate_audit`, then `executemany` INSERTs ALL rows incl. dups — `rows_to_insert` built from `indexed`, NOT filtered by `dup_zero_idxs`); `config/settings.py:503` (`memory_near_duplicate_threshold: float = Field(default=0.05, ge=0.0, le=1.0)`); `services/audit/audit_service.py:51` (`MEMORY_NEAR_DUPLICATE_SKIPPED = "MEMORY_NEAR_DUPLICATE_SKIPPED"`); `services/audit/audit_service.py:31` (`AUDIT_DETAIL_TRUNCATE_LEN = 200`) | `pytest tests/unit/memory/test_save_fact_precheck.py tests/unit/memory/test_save_fact_precheck_failure.py tests/unit/test_memory_save_fact.py` → 16/16 PASS (incl. `test_precheck_emits_audit_when_near_duplicate_and_still_inserts` which pins D-09) |
| SC-4 | `save_facts(list[...])` uses 1× embed_batch + 1× executemany for N=5; ExtractorAgent migrated; near-dup guard honored in batch | PASS | `services/memory/memory_service.py:566-717` (`save_facts` body); **C1 SQL verified at lines 553-563**: `unnest($1::text[]) WITH ORDINALITY AS t(vec_txt, idx)` + `embedding <=> vec_txt::vector < $4` (NOT the broken `unnest($1::vector[])` form); **C2 fallback verified at lines 619-644**: `except (httpx.HTTPError, RuntimeError, OSError)` → `asyncio.gather(*embed_one, return_exceptions=True)` with per-item BaseException partitioning + per-text `logger.warning` (A3); **C3 D-09 batch-side verified at lines 694-704**: `rows_to_insert` built from `indexed` (all post-embed-filter), `executemany` inserts all, audit fired separately for dups at 681-688; **D-12 wrapper verified at lines 719-759**: `save_fact` is thin delegate (`_round_importance_to_literal` produces matching category+importance, calls `save_facts([extracted])`, preserves embed-failure raise contract); **D-17 ExtractorAgent migration verified at `services/agent/extractor.py:261-266`**: single `await mem._long.save_facts(facts, ...)` replaces the per-fact for-loop | `pytest tests/unit/memory/test_save_facts_batch.py tests/unit/memory/test_save_facts_batch_dedupe.py tests/unit/memory/test_save_facts_embed_batch_fallback.py tests/unit/test_extractor_dispatch.py` → 15/15 PASS (incl. `test_save_facts_bulk_dedupe_sql_uses_text_array_pattern_c1` pinning the C1 SQL shape and `test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows` pinning C3 D-09) |
| SC-5 | Per-turn extractor latency benchmark captured in phase summary | PASS | `tests/benchmark/test_extractor_latency.py` (~218 LOC, marker `benchmark`, hard floor ≥80ms real or >0 mock); `27-BENCHMARK.md` (artifact present: baseline p50=25.31ms, new p50=5.51ms, speedup=19.80ms, MagicMock embedder run 2026-05-17T07:43:43Z) | `pytest tests/benchmark/test_extractor_latency.py --collect-only -m benchmark` → 1 test collected (file imports clean, CI uses `-m 'not benchmark'` per plan) |

**Score:** 5/5 SCs verified.

---

## Critical Correctness Spot-Checks (Goal-Backward, Falsified Against Code)

Goal-backward verification went beyond SC table to falsify the riskiest correctness claims directly in master HEAD.

| Check | Falsification Attempted | Result | Evidence |
|-------|--------------------------|--------|----------|
| **D-09 audit-mode-only, single path** | "Is there a silent-skip code path in `save_fact` that drops the INSERT when near-dup?" | NEGATIVE — no silent skip. `save_fact` is a thin wrapper (`memory_service.py:719-759`) delegating to `save_facts`; the batch path (`memory_service.py:566-717`) always builds `rows_to_insert` from `indexed` (post-embed-filter) and runs `executemany` regardless of `dup_zero_idxs`. | `memory_service.py:694-704` |
| **D-09 audit-mode-only, batch path** | "Does any branch filter `rows_to_insert` by `dup_zero_idxs`?" | NEGATIVE — `rows_to_insert` is derived from `indexed` (line 694), and `indexed` is built from the post-embed-filter zip (line 649-653), never narrowed by dup-indices. Pinned by unit test `test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows` AND integration test `test_save_facts_with_near_duplicate_emits_audit_and_still_inserts_real_pg`. | `memory_service.py:694-704` + `tests/unit/memory/test_save_facts_batch_dedupe.py:1-end` |
| **C1 SQL — text[] not vector[]** | "Does the bulk dedupe SQL use the broken `unnest($1::vector[])` form anywhere?" | NEGATIVE — only `unnest($1::text[]) WITH ORDINALITY` at line 555, with `vec_txt::vector` inline cast at line 560. Pinned by `test_save_facts_bulk_dedupe_sql_uses_text_array_pattern_c1`. | `memory_service.py:553-563` |
| **C2 embed_batch fallback** | "Does the fallback raise on first failure, or does it use return_exceptions?" | NEGATIVE on raising — `asyncio.gather(*embed_one, return_exceptions=True)` at line 627-630, with `isinstance(result, BaseException)` partition at 634. Per-text `logger.warning` at 637-640 (A3 eng-review). Parametrized over `(RuntimeError, HTTPError, OSError)`. | `memory_service.py:619-644` |
| **D-12 wrapper** | "Does `save_fact` retain its original embed/INSERT body, or does it delegate?" | DELEGATES — wrapper at lines 719-759 calls `save_facts([extracted])`. Signature unchanged. Embed-failure raise contract preserved (lines 758-759). | `memory_service.py:719-759` |
| **TD-06 D-22 diagnostic exists** | "Is the diagnostic file with pre/post counts present and committed?" | POSITIVE — `27-02-DIAGNOSTIC.md` exists with: pre=0 / post=0 Redis-CE counts, +14 newly-exposed TD-02 event-loop failures (correctly attributed to parallel 27-01 scope, not TD-06 regression), failure-mode table by category. | `27-02-DIAGNOSTIC.md:21-32` |
| **Singleton inventory completeness** | "Did the curated 34-entry inventory miss any module-level `_X = None` in `services/`?" | NEGATIVE — `tests/unit/test_singleton_inventory_complete.py` walks `services/**/*.py` with regex, cross-checks against `_SINGLETON_INVENTORY` + 4 documented `_SKIP` non-service primitives. Lint test PASSES. | `tests/factories/app.py:31-66` + lint test |
| **D-17 ExtractorAgent migration** | "Does extractor still call per-fact `save_fact` in a for-loop?" | NEGATIVE — `_run_and_persist` at `services/agent/extractor.py:247-266` is a single `await mem._long.save_facts(facts, ...)` call. No `for f in facts: ... save_fact` loop anywhere in the file. | `services/agent/extractor.py:247-266` |
| **ShortTermMemory bypass closed (D-19 bonus)** | "Does `ShortTermMemory._get_client` still call `redis.asyncio.from_url` directly?" | NEGATIVE — now `await get_redis()` at `services/memory/memory_service.py:183`. Pinned by static-source guard `test_memory_service_module_no_longer_imports_from_url` (PASS). | `services/memory/memory_service.py:181-183` |

All 9 spot-checks corroborate the SUMMARY narrative. No SUMMARY-vs-code drift detected.

---

## Required Artifacts (Existence + Substantive)

| Artifact | Expected | Status | Notes |
|----------|----------|--------|-------|
| `tests/factories/__init__.py` + `tests/factories/app.py` | TD-02 factory module | ✓ VERIFIED | 113 LOC, 34-entry inventory + reset + factory |
| `main.py::_configure_app` | TD-02 extraction | ✓ VERIFIED | Lines 370-428, prod calls at line 445 |
| `tests/conftest.py` redis_mock + app_factory + isolated_app + isolated_client | TD-02/TD-06 fixtures | ✓ VERIFIED | All 4 fixtures present + marker hook |
| `tests/unit/test_app_factory.py` | factory unit tests | ✓ VERIFIED | 5 tests, all PASS |
| `tests/unit/test_parallel_contamination.py` | SC-1 contamination test | ✓ VERIFIED | 3 tests (sentinel + override + gather) |
| `tests/unit/test_singleton_inventory_complete.py` | D-03 lint | ✓ VERIFIED | PASS — covers `services/**/*.py` |
| `tests/unit/test_main_middleware_order.py` | middleware-order baseline | ✓ VERIFIED | 4 tests PASS (equality not >=) |
| `tests/unit/test_redis_mock_fixture.py` | fixture self-test | ✓ VERIFIED | 9 tests PASS (GET/SET/list/hash/sorted-set/pipeline/dual-target) |
| `tests/unit/test_short_term_memory_get_redis.py` | D-19 delegate proof | ✓ VERIFIED | 4 tests PASS incl. static-source guard |
| `tests/unit/test_redis_mock_baseline_diagnostic.py` | D-22 subprocess regression gate | ✓ VERIFIED | 2 tests PASS |
| `tests/unit/memory/test_save_fact_precheck.py` | SC-3 D-09 contract | ✓ VERIFIED | 5 tests PASS |
| `tests/unit/memory/test_save_fact_precheck_failure.py` | SC-3 fail-open + InterfaceError | ✓ VERIFIED | 5 tests PASS (parametrized) |
| `tests/unit/memory/test_save_facts_batch.py` | SC-4 C1 SQL + mock count | ✓ VERIFIED | 3 tests PASS |
| `tests/unit/memory/test_save_facts_batch_dedupe.py` | SC-4 C3 D-09 batch + fail-open | ✓ VERIFIED | 2 tests PASS |
| `tests/unit/memory/test_save_facts_embed_batch_fallback.py` | SC-4 C2 fallback (A3 logging) | ✓ VERIFIED | 5 tests PASS (parametrized × 3) |
| `tests/integration/audit/test_audit_suite_factory_migrated.py` | SC-1 audit side | ✓ VERIFIED | 2 tests PASS via app_factory + live PG |
| `tests/integration/memory/test_memory_suite_factory_migrated.py` | SC-1 memory side | ✓ VERIFIED | 2 tests PASS via app_factory + live PG (incl. C3 D-09 integration check) |
| `tests/benchmark/test_extractor_latency.py` | SC-5 benchmark | ✓ VERIFIED | Collects (1 test, marker `benchmark`) |
| `27-BENCHMARK.md` | SC-5 artifact | ✓ VERIFIED | p50/p95 baseline + new + speedup recorded |
| `27-02-DIAGNOSTIC.md` | D-22 diagnostic | ✓ VERIFIED | Pre/post counts + attribution by mode |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TD-02 + TD-06 test suite | `uv run pytest tests/unit/test_app_factory.py tests/unit/test_parallel_contamination.py tests/unit/test_singleton_inventory_complete.py tests/unit/test_main_middleware_order.py tests/unit/test_redis_mock_fixture.py tests/unit/test_short_term_memory_get_redis.py tests/unit/test_redis_mock_baseline_diagnostic.py -q --timeout=60` | 28 passed in 3.93s | ✓ PASS |
| TD-04 + TD-05 unit suite | `uv run pytest tests/unit/memory/ tests/unit/test_memory_save_fact.py tests/unit/test_extractor_dispatch.py -q --timeout=60` | 33 passed in 0.94s | ✓ PASS |
| SC-1 integration suite (factory-migrated) | `uv run pytest tests/integration/audit/test_audit_suite_factory_migrated.py tests/integration/memory/test_memory_suite_factory_migrated.py -q -m 'integration or not integration' --timeout=120` | 4 passed in 1.27s | ✓ PASS |
| SC-5 benchmark collectable | `uv run pytest tests/benchmark/test_extractor_latency.py --collect-only -m benchmark` | 1 test collected | ✓ PASS |

**Total automated tests passing for this phase: 66/66 (61 unit + 4 integration + 1 benchmark collectable).**

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| TD-02 | 27-00, 27-01, 27-04 | Per-test `create_app()` factory replaces module-level singleton graph | ✓ SATISFIED | factory module + 34-entry inventory + audit/memory integration suites migrated; parallel-contamination test green |
| TD-04 | 27-03 | save_fact near-duplicate guard via cosine precheck (D-09 audit-mode-only) | ✓ SATISFIED | `_is_near_duplicate` + `_fire_near_duplicate_audit` + INSERT still runs; 10 unit tests pin contract |
| TD-05 | 27-04 | `save_facts` batch path 1× embed_batch + 1× executemany; ExtractorAgent migrated | ✓ SATISFIED | save_facts body + C1 SQL + C2 fallback + C3 D-09 + D-12 wrapper + D-17 extractor migration |
| TD-06 | 27-00, 27-02 | Redis-mock fixture rollout closes Redis-ConnectionError unit failures | ✓ SATISFIED | fakeredis-backed `redis_mock` fixture + marker-auto-fixture hook + ShortTermMemory bypass closed + D-22 diagnostic + subprocess regression gate |

No ORPHANED requirements.

---

## Anti-Pattern Scan

Modified production files: `main.py`, `config/settings.py`, `services/audit/audit_service.py`, `services/memory/memory_service.py`, `services/agent/extractor.py`, `tests/factories/app.py`.

- Debt markers (TBD/FIXME/XXX) in modified production files: **0**.
- TODO/HACK/PLACEHOLDER in modified production files: **0** (only doc-grade comments referencing v1.8 follow-up plans).
- Empty-return stubs (`return null|return {}|return []`) in new code paths: **0** (one early return `SaveFactsResult(0, 0, 0)` for empty input — correct semantics, NOT a stub).
- Hardcoded empty data: none in production paths.

---

## v1.8+ Follow-Ups Carried Forward (from SUMMARY files)

These are NOT gaps in Phase 27 — they are explicitly deferred items the planner + plans flagged for v1.8+:

1. **Silent-skip enforcement** for `MEMORY_NEAR_DUPLICATE_SKIPPED` (D-09 promotion): flip `save_facts` to filter `rows_to_insert` by `dup_zero_idxs`. Unit + integration tests already pin the v1.7 "still inserted" behavior, so v1.8 PRs must flip those assertions explicitly. (Plans 27-03 §"D-09 Override", 27-04 §"v1.8 Follow-up Reminders".)
2. **TOCTOU mitigation** for cosine precheck once silent-skip lands: SELECT-then-INSERT race between two parallel save_facts calls. Options: advisory lock per `(user, tenant)`, `INSERT ... ON CONFLICT` with a cosine-distance unique-ish index, or accept the race. (Plan 27-03 §"v1.8+ Follow-Ups".)
3. **openai SDK signature drift** (`APIError.__init__() missing 'request'`): pre-existing v1.8+ todo (already in STATE.md per commit `85ca25f`). 0 occurrences observed during this phase's diagnostic runs. Orthogonal to TD-06.
4. **Per-tenant `memory_near_duplicate_threshold` override** via TenantConfig (mirrors v1.6 GDPR per-tenant policies). Currently global. (Plan 27-04 §"v1.8 Follow-up Reminders".)
5. **Distance-in-bulk-audit-detail**: bulk dedupe SELECT returns only `zero_idx`; v1.7 batch-path audit rows have `nearest_distance: None`. v1.8 could add a second pass to surface distances. (Plan 27-04.)
6. **14 newly-exposed event-loop singleton-leak failures** (`test_agent_pipeline_refactor.py`, `test_agent_sse.py`, `test_pipeline_coverage.py`): documented in `27-02-DIAGNOSTIC.md`. Architecturally owned by 27-01's `_reset_singletons()` — `_SINGLETON_INVENTORY` already contains the relevant entries. Recommended follow-up: add a regression test that wraps the 4 marked files in `isolated_app` and asserts recovery. (Plan 27-02 §"Carry-Forward to Plan 27-01".)
7. **dual-path redis_mock safety belt simplification**: now that ShortTermMemory uses `get_redis`, the `redis.asyncio.from_url` patch in `tests/conftest.py:283` is redundant; future cleanup PR can simplify to single-target. (Plan 27-02 §"Wave 2 / Plan 27-03 / 27-04".)
8. **`LongTermMemory._get_pool` P1 backport** of the AuditService 26-04 partial-init reset pattern: opportunistically NOT delivered this phase. Standalone v1.8 todo. (CONTEXT D-22 Claude's Discretion.)

---

## Human Verification Required

None — every Phase 27 SC has automated + grep-verifiable evidence. The "Manual-Only Verifications" listed in `27-VALIDATION.md` (32 → 0 Redis-baseline failure delta on Redis-down host; benchmark hardware fingerprint) are addressed by:
- **32 → 0 delta**: subprocess gate `test_no_pre_existing_redis_connection_error_in_marked_files` PASSES (contract validation regardless of host Redis state); D-22 diagnostic confirms pre=0/post=0 on this Redis-up host with attribution that the contract is preserved.
- **Benchmark hardware fingerprint**: `27-BENCHMARK.md` documents MagicMock embedder + acknowledges floor is local-dev tripwire (`>0` for mock, `≥80ms` for real bge-m3). The SC-5 acceptance criterion ("benchmark captured in phase summary") is satisfied by the file's existence with the 4 numbers.

---

## Gaps Summary

**None.** All 5 success criteria PASS with codebase evidence; D-09 override correctly applied (audit emitted, INSERT still runs — verified by direct code inspection AND by passing unit + integration tests that explicitly pin `insert_calls == 1` for near-dup hits); C1/C2/C3 RESEARCH corrections present in production code with test enforcement; D-12 wrapper retains singular API; D-17 extractor migration eliminates the per-fact loop; D-22 diagnostic file committed with pre/post counts.

**Phase 27 is ready to ship.**

---

*Verified: 2026-05-17T08:05:00Z*
*Verifier: Claude (gsd-verifier, goal-backward methodology)*
