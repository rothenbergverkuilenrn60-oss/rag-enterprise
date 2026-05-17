# Phase 27: Test Isolation + Memory Reliability - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.

**Date:** 2026-05-17
**Phase:** 27-test-isolation-memory-reliability
**Areas discussed:** TD-02 create_app() factory, TD-04 near-duplicate guard, TD-05 save_facts batch path, TD-06 Redis-mock fixture

---

## Area 1 — TD-02 create_app() singleton reset strategy

### Sub-question 1a — Reset strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Brute-force: factory resets ALL ~20 singletons to None on each call | Curated list iterated each call; lint test guards inventory completeness | ✓ |
| DI refactor: convert to FastAPI Depends() | Idiomatic but 3-5 day scope; out of phase | |
| Hybrid: reset only audit + memory + planner + executor | Narrower but error-prone | |

### Sub-question 1b — Existing test migration

| Option | Description | Selected |
|--------|-------------|----------|
| Coexist — leave existing 8 tests on shared app; new tests use create_app() | Zero forced migration; minimal Phase 27 churn | ✓ |
| Migrate all 8 existing tests to create_app() | Uniform isolation but risky for working tests | |

---

## Area 2 — TD-04 near-duplicate guard

### Sub-question 2a — Precheck scope

| Option | Description | Selected |
|--------|-------------|----------|
| Per-(user_id, tenant_id) | Matches v1.6 RLS contract | ✓ |
| Per-user (cross-tenant) | Violates RLS isolation | |
| Per-tenant (cross-user) | Changes recall semantics | |

### Sub-question 2b — Threshold

| Option | Description | Selected |
|--------|-------------|----------|
| `settings.memory_near_duplicate_threshold: float = 0.05` | Pydantic Field(ge=0.0, le=1.0); per-deploy tunable | ✓ |
| Hardcoded 0.05 constant | Simpler but rigid | |

### Sub-question 2c — Audit channel

| Option | Description | Selected |
|--------|-------------|----------|
| New AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED + audit_log row per skip | Unified audit trail; per-event forensics | ✓ |
| Prometheus counter only | Low overhead but no per-event detail | |

### Sub-question 2d — Sample or every call

| Option | Description | Selected |
|--------|-------------|----------|
| Every save_fact call | Deterministic; +1 RTT negligible (TD-05 batch collapses) | ✓ |
| Sample every Nth call | Misses 90% of duplicates | |

---

## Area 3 — TD-05 save_facts batch path

### Sub-question 3a — API shape

| Option | Description | Selected |
|--------|-------------|----------|
| save_fact() delegates to save_facts([fact]) | Single code path; existing callers unchanged | ✓ |
| Keep save_fact + save_facts as separate methods | Surgical but duplicates dedupe + audit logic | |

### Sub-question 3b — Batch dedupe

| Option | Description | Selected |
|--------|-------------|----------|
| Bulk SQL precheck (unnest + WITH ORDINALITY) | 1 RTT regardless of batch size | ✓ |
| N individual prechecks then one insert | Simpler SQL but N+1 RTT | |
| No dedupe in batch path | Contradicts TD-04 scope | |

### Sub-question 3c — Partial-failure semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Best-effort: skip failed embeds, commit successful ones | Matches Phase 23 D-05 adversarial-fixture tolerance | ✓ |
| All-or-nothing: rollback all if any embed fails | Atomic but aggressive | |

### Sub-question 3d — ExtractorAgent migration

| Option | Description | Selected |
|--------|-------------|----------|
| Inline migration at services/agent/extractor.py:260 | Trivial diff; clear benchmark | ✓ |
| Add adapter layer in MemoryService | Cleaner encapsulation but extra method | |

---

## Area 4 — TD-06 Redis-mock fixture rollout

### Sub-question 4a — Fixture location

| Option | Description | Selected |
|--------|-------------|----------|
| tests/conftest.py | Auto-discovered; matches pg_pool convention | ✓ |
| tests/fixtures/redis_mock.py | Opt-in import; cleaner conftest | |

### Sub-question 4b — Autouse policy

| Option | Description | Selected |
|--------|-------------|----------|
| Marker-opt-in via `@pytest.mark.uses_redis` | Explicit; integration tests bypass naturally | ✓ |
| autouse=True for all unit tests | Auto-closes 32 baseline but heavy-handed | |
| Opt-in fixture parameter (no marker) | Explicit per-test but 32 edits | |

### Sub-question 4c — Mock surface

| Option | Description | Selected |
|--------|-------------|----------|
| Mock `utils.cache.get_redis` (canonical accessor) | 1 mock target; high leverage | ✓ |
| Mock both get_redis AND redis.asyncio.Redis | Belt + suspenders but brittle | |

### Sub-question 4d — Integration bypass

| Option | Description | Selected |
|--------|-------------|----------|
| Integration tests don't add `@pytest.mark.uses_redis` (auto-bypass per Q2) | Zero extra mechanism | ✓ |
| Add `@pytest.mark.real_redis` opt-out | Only needed if Q2=autouse | |

---

## Claude's Discretion

- Singleton inventory list — verified at plan-time via fresh grep (current list from 2026-05-17 scan)
- TD-04 ops dashboard alerts — Phase 27 ships metric, alerting deferred to v1.8
- `SaveFactsResult` shape — dataclass (symmetric with ExtractedFact)
- AuditAction enum name — `MEMORY_NEAR_DUPLICATE_SKIPPED` proposed default
- `pytest_collection_modifyitems` hook auto-apply pattern for redis_mock fixture
- Opportunistic P1 backport to LongTermMemory._get_pool during TD-04/TD-05 work (zero-risk per D-Plan-26-04)

## Deferred Ideas

- TD-02 full DI refactor — v1.8+
- TD-04 silent-skip promotion — v1.8 (currently audit-mode-only per EVICT-02 discipline)
- TD-04 audit dashboard / Grafana panel — v1.8 ops
- openai SDK signature drift cleanup (32 PR #9 failures) — v1.8+ separate todo
- TD-06 direct-redis-import audit + refactor of bypassing services — v1.8+
- LongTermMemory `_get_pool` P1 backport (if not bonus-delivered in Phase 27) — v1.8
- DOC-01 — Phase 28
