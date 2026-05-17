---
phase: 27-test-isolation-memory-reliability
plan: 00
subsystem: testing
tags: [pytest, fakeredis, fastapi, factory, conftest, fixtures, mypy-strict, ruff]

# Dependency graph
requires:
  - phase: 26-memory-infra-hygiene
    provides: pg_pool / pg_store / extractor_llm_mock / embedder_or_mock conftest fixtures (extended here, not replaced)
provides:
  - tests/factories/ package with create_app() + _SINGLETON_INVENTORY (34 entries) + _reset_singletons()
  - tests/conftest.py: uses_redis + benchmark markers, pytest_collection_modifyitems hook, redis_mock (fakeredis-backed), app_factory, isolated_app, isolated_client fixtures
  - fakeredis 2.35.1 in dev deps (pyproject.toml + uv.lock)
  - 2 self-test files validating fixture behavior (test_app_factory.py, test_redis_mock_fixture.py)
affects: [27-01, 27-02, 27-03, 27-04]  # Wave 1+ plans consume app_factory / redis_mock / create_app

# Tech tracking
tech-stack:
  added: [fakeredis==2.35.1, sortedcontainers==2.4.0]
  patterns:
    - "Brute-force singleton reset via importlib + setattr-with-hasattr-guard (TD-02 D-01)"
    - "Marker-opt-in auto-fixture (D-18) via pytest_collection_modifyitems hook"
    - "Dual-path Redis patch (utils.cache.get_redis + redis.asyncio.from_url) covers Pitfall 6 ShortTermMemory bypass"
    - "Lazy 'from main import _configure_app' inside factory body to avoid module-load singleton instantiation"
    - "pytest.importorskip / getattr gate for tests that depend on Wave 1 prerequisites"

key-files:
  created:
    - tests/factories/__init__.py
    - tests/factories/app.py
    - tests/unit/test_app_factory.py
    - tests/unit/test_redis_mock_fixture.py
    - .planning/phases/27-test-isolation-memory-reliability/27-00-SUMMARY.md
  modified:
    - tests/conftest.py (additive — appended Phase 27 section after Phase 23 fixtures)
    - pyproject.toml (added fakeredis dev dep)
    - uv.lock (resolved fakeredis 2.35.1 + sortedcontainers 2.4.0)

key-decisions:
  - "Overrode CONTEXT D-20 (MagicMock(spec=...)) in favor of fakeredis.aioredis.FakeRedis per RESEARCH §Theme 2 — codebase exercises hashes/sorted-sets/lists/pipelines/Lua-eval, and fakeredis provides real semantics for all of them out of the box"
  - "Patched BOTH utils.cache.get_redis AND redis.asyncio.from_url in redis_mock fixture because services.memory.memory_service.ShortTermMemory._get_client bypasses get_redis (RESEARCH §6 Pitfall 6). The from_url patch is a safety belt that remains useful even after the 27-02 bonus refactor"
  - "Final _SINGLETON_INVENTORY size = 34 (CONTEXT D-02 listed 15; RESEARCH §1 grep found 38; minus 4 non-service cached primitives = 34 — see Inventory Diff below)"
  - "Tests 4-5 of test_app_factory.py + Test 9 of test_redis_mock_fixture.py are gated via getattr / importorskip checks on main._configure_app, which is introduced in plan 27-01. They report SKIPPED (not failure) on this Wave 0 run"

patterns-established:
  - "Singleton inventory enumeration pattern: tuple of (module_path, attr_name) pairs + importlib + setattr-with-hasattr-guard"
  - "FastAPI factory pattern: lazy import + _reset_singletons() prelude + FastAPI(lifespan=lifespan) + _configure_app(app) + dependency_overrides apply"
  - "Marker-auto-fixture pattern: pytest_configure + pytest_collection_modifyitems to opt-in fixtures via @pytest.mark.X without explicit arg-name listing"

requirements-completed: [TD-02, TD-06]  # Wave 0 scaffolding portion; consumer migration tracked in 27-01 (TD-02) + 27-02 (TD-06)

# Metrics
duration: 11min
completed: 2026-05-17
---

# Phase 27 Plan 00: Test Infra Prep Summary

**Scaffolded TD-02 create_app() factory (34-entry singleton inventory + brute-force reset) and TD-06 fakeredis-backed redis_mock fixture (dual-path patched for ShortTermMemory bypass), with marker-auto-fixture hook — zero production source touched.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-05-17T06:34:32Z
- **Completed:** 2026-05-17T06:46:01Z
- **Tasks:** 2 (executed in TDD RED→GREEN cycles → 4 atomic commits)
- **Files modified:** 6 (5 created + 1 extended; +2 dep manifests)

## Accomplishments

- `tests/factories/app.py` shipped with **34-entry _SINGLETON_INVENTORY**, idempotent `_reset_singletons()`, and `create_app(*, dependency_overrides=None)` factory (lazy-imports `main._configure_app` — gated until plan 27-01 lands the extraction).
- `tests/conftest.py` extended with `pytest_configure` (markers), `pytest_collection_modifyitems` (auto-attach `redis_mock` to `@pytest.mark.uses_redis` tests per D-18), `redis_mock` fixture backed by **fakeredis.aioredis.FakeRedis** (D-20 override per RESEARCH §Theme 2), plus `app_factory`, `isolated_app`, `isolated_client` fixtures.
- Dual-path Redis patch (`utils.cache.get_redis` + `redis.asyncio.from_url`) closes Pitfall 6 (ShortTermMemory direct-from_url bypass) preemptively, so the fixture works whether or not 27-02's bonus refactor migrates ShortTermMemory through `get_redis`.
- 11 self-tests pass (test_app_factory.py: 3 pass + 2 gated skip; test_redis_mock_fixture.py: 8 pass + 1 gated skip — gates skip cleanly until 27-01 ships `_configure_app`).
- fakeredis 2.35.1 added to dev deps (pyproject.toml + uv.lock).
- Zero production-source touches: `git diff --name-only 8746de9..HEAD` returns only `tests/`, `pyproject.toml`, and `uv.lock`.

## Task Commits

Each task ran TDD RED→GREEN; commits are atomic per phase:

1. **Task 1 RED:** test_app_factory.py failing tests — `0953938` (test)
2. **Task 1 GREEN:** tests/factories/app.py create_app + inventory — `60b92c4` (feat)
3. **Task 2 RED:** test_redis_mock_fixture.py failing tests — `0793ab1` (test)
4. **Task 2 GREEN:** conftest.py fixtures + markers + hook + fakeredis dep — `7ee83bf` (feat)

**Plan metadata:** to be committed after this SUMMARY.md write.

## Files Created/Modified

- `tests/factories/__init__.py` — empty package marker (follows `tests/integration/__init__.py` precedent)
- `tests/factories/app.py` — `_SINGLETON_INVENTORY` (34 services), `_reset_singletons()` (idempotent importlib+setattr), `create_app(*, dependency_overrides=None)` (lazy main import + FastAPI factory)
- `tests/conftest.py` — appended Phase 27 section (~130 lines): markers, hook, 4 new fixtures
- `tests/unit/test_app_factory.py` — 5 tests (3 ungated + 2 gated on main._configure_app)
- `tests/unit/test_redis_mock_fixture.py` — 9 tests covering GET/SET/RPUSH/LRANGE/ZADD/ZCOUNT/EXPIRE/pipeline/HGET/HSET/HGETALL/HDEL/get_redis-patch/from_url-patch/app_factory
- `pyproject.toml` — added fakeredis dev dep
- `uv.lock` — fakeredis 2.35.1 + sortedcontainers 2.4.0 resolved

## _SINGLETON_INVENTORY Diff vs CONTEXT D-02

| Source                          | Count |
|---------------------------------|-------|
| CONTEXT D-02 curated            | 15    |
| RESEARCH §1 live-grep total     | 38    |
| Skipped (non-service primitives)| 4     |
| **Final inventory shipped**     | **34**|

**The 4 explicitly skipped (cached primitives, not service instances):**
- `services.generator.generator._tiktoken_enc` — tokenizer cache (RESEARCH §1 entry 24)
- `services.generator.llm_client._anthropic_rate_limit_cls` — exception class cache (entry 26)
- `services.generator.llm_client._anthropic_overload_cls` — exception class cache (entry 27)
- `services.extractor.ocr_engine._sem` — asyncio.Semaphore, not a singleton service (entry 38)

**19 additions vs CONTEXT D-02** (the "✗ (add)" rows from RESEARCH §1): `_ner_pipeline`, `_reranker`, `_store_instance`, `_embedder_instance`, `_knowledge_service`, `_version_service`, `_summary_indexer`, `_generator`, `_llm_instance`, `_ingest_pipeline`, `_query_pipeline`, `_agent_pipeline`, `_swarm_pipeline`, `_tenant_service`, `_rules_engine`, `_event_bus`, `_pii_detector`, `_ab_service`, plus the `_store_instance` / `_embedder_instance` previously reset only in narrow fixtures.

No singletons were discovered at plan-time beyond RESEARCH §1's enumeration — the live grep was already current.

## fakeredis Version Pin Verification

```
$ uv run python -c "import fakeredis; print(fakeredis.__version__)"
2.35.1
```

Matches RESEARCH §Theme 2's recommended pin (`fakeredis>=2.35`). `FakeRedis` class importable from `fakeredis.aioredis` confirmed.

## Decisions Made

1. **D-20 override (CONTEXT → RESEARCH §Theme 2):** Use `fakeredis.aioredis.FakeRedis(decode_responses=True)` instead of `MagicMock(spec=redis.asyncio.Redis)`. Rationale: codebase exercises sorted sets (rate limiter), hashes (entity_disambiguator + ab_test_service), lists (ShortTermMemory), pipelines (multiple services), and Lua eval. Hand-rolling MagicMock semantics for all of these is hours of work; fakeredis provides correct semantics natively.
2. **Dual-path Redis patch:** Patch BOTH `utils.cache.get_redis` AND `redis.asyncio.from_url`. The latter is required because `ShortTermMemory._get_client` (services/memory/memory_service.py:87-108) bypasses `get_redis` and calls `redis.asyncio.from_url` directly (Pitfall 6). The patch stays as a safety belt even after 27-02's bonus refactor migrates ShortTermMemory through `get_redis`.
3. **Gate-not-fail pattern:** Tests that depend on `main._configure_app` (from plan 27-01) use `getattr(main, '_configure_app', None) is None` skip checks rather than failing — keeps Wave 0 green while Wave 1 work proceeds in parallel.
4. **T-G1 hash-ops test included unconditionally:** Plan-time grep confirmed `services/nlu/entity_disambiguator.py` and `services/ab_test/ab_test_service.py` use HSET/HGET/HGETALL/HDEL — so `test_redis_mock_hash_ops` is required (not skipped).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing fakeredis dev dependency**
- **Found during:** Pre-Task 2 environment check
- **Issue:** RESEARCH §Theme 2 line 514 stated "`fakeredis==2.35.1` is already in the project dependency set" — live `uv run python -c "import fakeredis"` proved otherwise (`ModuleNotFoundError`). Task 2's redis_mock fixture cannot construct `FakeRedis` without the package.
- **Fix:** `uv add --dev fakeredis` (per plan_specific_notes line 38 explicit fallback instruction). Resolved fakeredis 2.35.1 + transitive sortedcontainers 2.4.0.
- **Files modified:** `pyproject.toml`, `uv.lock`
- **Verification:** `uv run python -c "import fakeredis, fakeredis.aioredis; print(fakeredis.__version__)"` → `2.35.1`
- **Committed in:** `7ee83bf` (Task 2 commit — committed atomically per plan_specific_notes guidance)

---

**Total deviations:** 1 auto-fixed (Rule 3 blocking install)
**Impact on plan:** Zero scope change — plan explicitly anticipated this exact case ("If fakeredis is not in pyproject.toml, add via `uv add --dev fakeredis` and commit pyproject.toml + uv.lock with the same plan-task commit"). The install was deterministic and matched the version pin in RESEARCH.

## Issues Encountered

- **mypy --strict noise from `from main import _configure_app, lifespan`:** The lazy import inside `create_app()` causes mypy to descend into `main.py` (which has 369 pre-existing strict-mode errors). Resolved by running mypy with `--follow-imports=silent` for the factory-only check; per project scope-boundary rule, pre-existing main.py errors are out of scope for plan 27-00. Plan 27-01 (which extracts `_configure_app`) will face the same noise; addressing project-wide mypy --strict compliance is a separate v1.8+ todo.
- **RTK output suppression on piped greps:** Plan acceptance grep `grep -v '^#' tests/conftest.py | grep -c "monkeypatch.setattr(.redis.asyncio.from_url"` returned 0 under default shell wrapping due to RTK output filtering. `rtk proxy bash -c '...'` returned 1 (the correct count). The fixture code at conftest.py:283 is correct; the grep was a test-of-the-grep issue, not a code issue.

## User Setup Required

None — Wave 0 is test infrastructure scaffolding; no env vars, no external services, no dashboards.

## Next Phase Readiness

**Wave 1 (parallel) consumers ready:**
- **Plan 27-01** can now extract `main._configure_app` and import it from `tests.factories.app.create_app`. Tests 4-5 in `test_app_factory.py` + Test 9 in `test_redis_mock_fixture.py` will auto-un-skip and pass once `_configure_app` exists.
- **Plan 27-02** can now apply `@pytest.mark.uses_redis` to the unit-test files that currently fail with `ConnectionError: Error 111 connecting to localhost:6379`. The fixture auto-attaches via the `pytest_collection_modifyitems` hook — no per-test fixture argument needed.

**Carry-forward to 27-02:**
- D-22 diagnostic (Redis-ConnectionError vs openai-SDK-drift failure attribution) is owned by 27-02 SC-2, not this plan.
- ShortTermMemory `_get_client` direct-from_url is preemptively neutralized by the dual-path redis_mock patch. 27-02 can still ship the bonus delegate-to-get_redis refactor (D-19 follow-on); the test path is unaffected either way.

**Blockers:** None.

## Self-Check

Verified before SUMMARY commit:

```
FOUND: tests/factories/__init__.py
FOUND: tests/factories/app.py
FOUND: tests/conftest.py (modified)
FOUND: tests/unit/test_app_factory.py
FOUND: tests/unit/test_redis_mock_fixture.py
FOUND: pyproject.toml (modified)
FOUND: uv.lock (modified)

FOUND: 0953938 (test 27-00 task 1 RED)
FOUND: 60b92c4 (feat 27-00 task 1 GREEN)
FOUND: 0793ab1 (test 27-00 task 2 RED)
FOUND: 7ee83bf (feat 27-00 task 2 GREEN)
```

## Self-Check: PASSED

---
*Phase: 27-test-isolation-memory-reliability*
*Plan: 00*
*Completed: 2026-05-17*
