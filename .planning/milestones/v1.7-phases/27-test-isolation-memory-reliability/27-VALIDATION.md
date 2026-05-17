---
phase: 27
slug: test-isolation-memory-reliability
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-17
---

# Phase 27 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Themes: TD-02 (singleton kill + create_app factory) · TD-04 (Redis-mock rollout) · TD-05 (cosine-precheck near-dup guard) · TD-06 (executemany batch path).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio + fakeredis 2.35.1 (already in deps) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`), `tests/conftest.py` |
| **Quick run command** | `uv run pytest tests/unit -x -q` |
| **Full suite command** | `uv run pytest -x` |
| **Estimated runtime** | ~45s quick · ~180s full (pre-Phase 27 baseline) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit -x -q`
- **After every plan wave:** Run `uv run pytest -x` (full suite, including integration)
- **Before `/gsd:verify-work`:** Full suite green + parallel-contamination test green + mock-call-count test green + latency benchmark captured
- **Max feedback latency:** 60 seconds for unit; 300 seconds for full suite + benchmark

---

## Per-Task Verification Map

> Populated by gsd-planner. Each task in PLAN.md must map to one row here. Test types per SC:
>
> | SC | Theme | Test types required |
> |----|-------|---------------------|
> | SC-1 | create_app factory | unit (factory instantiation) + integration (audit + memory suite migrated) + parallel-contamination (deliberate cross-test mutation) |
> | SC-2 | Redis-mock | unit (fakeredis fixture works) + suite-delta (32 → 0 baseline failures) + boundary (real-Redis tests still gated correctly) |
> | SC-3 | Cosine-precheck | unit (precheck SQL fires) + audit-metric (`memory.save_fact.near_duplicate_skipped` emitted) + round-trip-count (≤+1 PG RTT) + failure-mode (fail-open on precheck timeout) |
> | SC-4 | Batch save_facts | mock-counting (1× embed_batch + 1× executemany for N=5) + dedupe-in-batch + ExtractorAgent dispatch migrated + embed_batch fallback (per RESEARCH §Theme 4 fail-fast correction) |
> | SC-5 | Latency benchmark | benchmark capture (v1.6 baseline + v1.7 result + delta ≥ embed-RTT × (N−1)) |

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| _populated by planner_ | — | — | — | — | — | — | — | — | ⬜ pending |

---

## Wave 0 Requirements

> Per RESEARCH §Validation Architecture — 13 new test files identified. Planner expands; baseline list:

- [ ] `tests/conftest.py` — central `app` fixture (function-scoped, uses `create_app()`), `client` fixture (httpx.AsyncClient + ASGITransport)
- [ ] `tests/fixtures/redis_mock.py` — `redis_mock` autouse-opt-in fixture wrapping `fakeredis.aioredis.FakeRedis()`
- [ ] `tests/unit/test_app_factory.py` — `create_app()` returns isolated FastAPI instance; dependency overrides scoped per-app
- [ ] `tests/unit/test_parallel_contamination.py` — two `create_app()` instances + deliberate counter/state mutation, asserts no cross-leak
- [ ] `tests/unit/test_redis_mock_fixture.py` — fixture surfaces match real Redis ops we use (GET/SET, list, hash, expiry)
- [ ] `tests/unit/memory/test_save_fact_precheck.py` — cosine `<=>` query fires; threshold 0.05; +1 PG RTT only
- [ ] `tests/unit/memory/test_save_fact_precheck_failure.py` — fail-open semantics when precheck SELECT errors
- [ ] `tests/unit/memory/test_save_facts_batch.py` — mock embedder + asyncpg conn: assert 1× embed_batch + 1× executemany for N=5
- [ ] `tests/unit/memory/test_save_facts_batch_dedupe.py` — near-dup-in-batch honored (bulk precheck filters insert list)
- [ ] `tests/unit/memory/test_save_facts_embed_batch_fallback.py` — embed_batch raises → fallback to gather(return_exceptions=True) per RESEARCH correction
- [ ] `tests/integration/audit/test_audit_suite_factory_migrated.py` — replaces Phase 23 monkeypatch-on-singletons pattern
- [ ] `tests/integration/memory/test_memory_suite_factory_migrated.py` — replaces Phase 24/25 monkeypatch pattern
- [ ] `tests/benchmark/test_extractor_latency.py` — captures per-turn ExtractorAgent latency, asserts v1.7 ≤ v1.6 baseline − embed_rtt × (N−1)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 32 → 0 Redis-baseline failure delta | TD-04 / SC-2 | Requires comparing against v1.6 Phase 24 baseline failure log (historical artifact, not in repo) | Run `uv run pytest tests/unit -v` on v1.7 tip; assert no test contains "redis.exceptions.ConnectionError" in failure output; cross-reference Phase 24 summary's failing-test list to confirm 32 named tests now pass |
| Latency baseline capture (SC-5) | TD-06 / SC-5 | Requires reproducible hardware + warm caches; ad-hoc on dev WSL is not portable | Document run on the canonical WSL2 dev host; record median of 20 runs in phase summary with hardware fingerprint (CPU, RAM, PG version) |

---

## Validation Sign-Off

- [ ] All tasks in PLAN.md have `<automated>` verify or appear in Wave 0
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all 13 new test files identified in RESEARCH §Validation Architecture
- [ ] No watch-mode flags (pytest is run-once)
- [ ] Feedback latency < 60s (unit), < 300s (full + benchmark)
- [ ] Three RESEARCH corrections threaded into plan:
  - [ ] D-13 SQL pattern uses `unnest($1::text[]) WITH ORDINALITY` + inline `::vector` cast (pgvector.asyncpg quirk)
  - [ ] D-16 fail-fast → fallback to `gather(return_exceptions=True)` documented in SC-4 plan
  - [ ] D-09 (audit-only, save still happens) overrides SC-3 wording in plan + verification asserts
- [ ] `nyquist_compliant: true` set in frontmatter after planner + plan-checker pass

**Approval:** pending
