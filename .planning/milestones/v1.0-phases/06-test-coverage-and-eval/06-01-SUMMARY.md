---
phase: 06-test-coverage-and-eval
plan: "01"
subsystem: testing
tags:
  - testing
  - pytest
  - fakeredis
  - unit-tests
  - TEST-01

dependency_graph:
  requires:
    - services/tenant/tenant_service.py
    - services/nlu/nlu_service.py
    - services/memory/memory_service.py
    - services/ab_test/ab_test_service.py
    - services/vectorizer/embedder.py
  provides:
    - tests/unit/test_tenant_service.py
    - tests/unit/test_nlu_service.py
    - tests/unit/test_memory_service.py
    - tests/unit/test_ab_test_service.py
    - tests/unit/test_embedder.py
  affects: []

tech_stack:
  added:
    - fakeredis (FakeAsyncRedis for in-process Redis simulation)
  patterns:
    - env-bootstrap header (os.environ.setdefault before service imports)
    - autouse singleton-reset fixture
    - monkeypatch._client / ._redis for service isolation
    - pytest_asyncio.fixture for async fixtures

key_files:
  created:
    - tests/unit/test_tenant_service.py
    - tests/unit/test_nlu_service.py
    - tests/unit/test_memory_service.py
    - tests/unit/test_ab_test_service.py
    - tests/unit/test_embedder.py
  modified: []

decisions:
  - "OllamaEmbedder tests monkeypatch self._client directly (not httpx.AsyncClient class) because the client is stored at __init__ time — class-level monkeypatching would not intercept calls to the already-constructed instance"
  - "_rule_based_intent returns None (not a default QueryIntent) for unmatched queries — test asserts None per source contract"
  - "ABTestService.assign_variant used instead of get_variant (which does not exist) — plan interface description was slightly inaccurate; assign_variant is the actual routing method"
  - "ShortTermMemory has no MAX_HISTORY cap constant — get_history uses max_turns parameter; window truncation test uses max_turns=3 rather than a fixed cap"

metrics:
  duration: "~6 minutes"
  completed_date: "2026-04-27T08:15:45Z"
  tasks_completed: 3
  files_created: 5
  tests_added: 25
---

# Phase 6 Plan 01: Unit Test Coverage (Tenant, NLU, Memory, AB Test, Embedder) Summary

**One-liner:** 25 pytest unit tests across 5 service modules using fakeredis and httpx mocks — zero real network or DB calls, all offline.

## Commits

| Hash | Message |
|------|---------|
| 410f131 | test(06-01): add tenant_service and NLU rule-based unit tests |
| a69832c | test(06-01): add memory_service and ab_test_service unit tests (fakeredis) |
| 9c9574f | test(06-01): add OllamaEmbedder unit tests (httpx mock, no network) |

## Test Files Delivered

| File | Tests | Key Coverage |
|------|-------|-------------|
| tests/unit/test_tenant_service.py | 7 | register/get, permission checks (open+restricted), set_tenant_context SQL arg, tenant filter |
| tests/unit/test_nlu_service.py | 7 | CHITCHAT/PROCEDURAL/COMPARISON intent, entity extraction (number, policy_term), None fallback, LLM analyze mock |
| tests/unit/test_memory_service.py | 4 | append+get, window truncation via max_turns, empty session, singleton identity |
| tests/unit/test_ab_test_service.py | 3 | assign_variant determinism, multi-user distribution, redis key persistence |
| tests/unit/test_embedder.py | 4 | embed_batch happy path, multi-text, ConnectError retry (3 attempts), model name in payload |

## Deviations from Plan

### Auto-discovered and handled

**1. [Rule 1 - Deviation] ABTestService has no `get_variant` method**
- **Found during:** Task 2 (reading ab_test_service.py source)
- **Issue:** Plan interface description listed `get_variant(user_id, experiment_id)` but the actual method is `assign_variant(session_id, tenant_id)` which also requires a running experiment in Redis.
- **Fix:** Tests use `assign_variant` with helper that creates and starts an experiment first. Tested determinism, distribution, and Redis key presence. Behavior is equivalent to the plan's intent.
- **Files modified:** tests/unit/test_ab_test_service.py

**2. [Rule 2 - Observation] OllamaEmbedder constructor takes no args**
- **Found during:** Task 3 (reading embedder.py source)
- **Issue:** Plan's action block showed `OllamaEmbedder(base_url="...", model="bge-m3")` but the class reads from `settings` at `__init__` with no parameters.
- **Fix:** Tests construct `OllamaEmbedder()` with no args; model name assertion reads `settings.embedding_model` dynamically instead of hardcoding `"bge-m3"`. Monkeypatching `self._client` directly (not via class-level httpx mock) because the client is stored at construction time.
- **Files modified:** tests/unit/test_embedder.py

**3. [Rule 1 - Deviation] ShortTermMemory has no MAX_HISTORY cap**
- **Found during:** Task 2 (reading memory_service.py source)
- **Issue:** Plan's action block said "read source for actual window value (e.g. `MAX_HISTORY = 20`)". No such constant exists. The history is capped by the `max_turns` parameter at query time.
- **Fix:** Window truncation test appends 10 turns and requests `max_turns=3`, asserting `len(history) <= 6` and the last turn is the most recent. Correctly exercises the window behavior.
- **Files modified:** tests/unit/test_memory_service.py

## Success Criteria Verification

| Criterion | Result |
|-----------|--------|
| 5 new test files exist in tests/unit/ | PASS |
| All 25 tests pass (exit 0) | PASS |
| All files include SECRET_KEY env bootstrap | PASS |
| No bare `except Exception` | PASS |
| Test count ≥ 20 (collected) | PASS — 25 collected |

## Threat Model Compliance

| Threat ID | Mitigation Applied |
|-----------|-------------------|
| T-06-01 | All 5 files use `os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")` |
| T-06-02 | autouse singleton-reset fixtures in test_nlu_service.py, test_memory_service.py, test_ab_test_service.py |
| T-06-03 | pytest-timeout=30 enforced; fakeredis aclose() called in all async fixture teardowns |
| T-06-04 | httpx monkeypatched on instance (not class) before any HTTP call; no network access needed |

## Self-Check

### Files exist:
- tests/unit/test_tenant_service.py — FOUND
- tests/unit/test_nlu_service.py — FOUND
- tests/unit/test_memory_service.py — FOUND
- tests/unit/test_ab_test_service.py — FOUND
- tests/unit/test_embedder.py — FOUND

### Commits exist:
- 410f131 — FOUND
- a69832c — FOUND
- 9c9574f — FOUND

## Self-Check: PASSED
