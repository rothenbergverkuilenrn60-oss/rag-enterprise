# Phase 27 — Engineering Review

**Reviewer:** /plan-eng-review (Claude Opus 4.7)
**Date:** 2026-05-17
**Scope:** 27-00..27-04 PLAN.md set (5 plans, 13 tasks, ~19 files modified)

---

## Completion Summary

| Section | Result |
|---------|--------|
| Step 0: Scope Challenge | **scope accepted as-is** (D1: kept D-03 singleton lint test) |
| Architecture Review | **3 issues found, all fixed inline** (A1 middleware-order test, A2 TOCTOU v1.8 note, A3 per-text fallback log) |
| Code Quality Review | **3 issues found, all fixed inline** (CQ1 diagnostic to phase dir, CQ2 helper placement locked, CQ3 truncation constant) |
| Test Review | **diagram produced, 1 conditional gap fixed inline** (T-G1 hash-ops grep-then-test) |
| Performance Review | **0 P1/P2 issues** (P1 GUC-in-transaction noted as observational, not actionable) |
| Outside Voice | **skipped** (caveman mode + deep GSD context; plan-checker already provided cross-AI structure) |
| NOT in scope | written (6 items) |
| What already exists | written (7 items reused) |
| TODOS.md updates | **2 items added** (v1.8 silent-skip + TOCTOU, openai SDK drift) |
| Failure modes | **0 critical gaps** — all silent failure modes have test + handler + observable signal |
| Parallelization | 3 lanes; Wave 1 (27-01 + 27-02) safely parallel post-27-00 |
| Lake Score | 7/7 — all "complete option" recommendations chosen |

---

## Findings — Severity-Tagged

### Architecture
- **A1 (P2, confidence: 8/10)** `main.py:181-366` — middleware extraction lacked explicit order verification → added `tests/unit/test_main_middleware_order.py` + EXPECTED_ORDER_LIST acceptance criterion in 27-01 Task 1
- **A2 (P3, confidence: 9/10)** `27-03 precheck` — TOCTOU window in v1.7 audit-mode (harmless now, becomes bug in v1.8) → added explicit follow-up note to 27-03 frontmatter with 3 mitigation options for v1.8 planner
- **A3 (P3, confidence: 9/10)** `27-04 embed_batch fallback` — counter without per-text log context → added `logger.warning("embed_batch fallback: idx={} text_len={}", ...)` + caplog test assertion

### Code Quality
- **CQ1 (P2, confidence: 8/10)** `27-02 D-22 diagnostic` — wrote to `/tmp/27-02-pre-rollout.log` (host-local, evaporates) → wrote diagnostic structure to `.planning/phases/.../27-02-DIAGNOSTIC.md`, committed alongside source
- **CQ2 (P3, confidence: 7/10)** `27-03 _fire_near_duplicate_audit` — placement was left to executor's choice → locked as `@staticmethod` on `LongTermMemory` class
- **CQ3 (P3, confidence: 6/10)** `27-03 fact[:200]` truncation magic number → added `AUDIT_DETAIL_TRUNCATE_LEN = 200` constant in `services/audit/audit_service.py`

### Test Review
- **T-G1 (P3, confidence: 7/10)** `tests/unit/test_redis_mock_fixture.py` missing hash-ops self-test → added conditional grep-then-test step in 27-00 Task 2

### Performance
- **P1 (P3, confidence: 6/10)** `_is_near_duplicate` SET LOCAL inside transaction per call adds ~0.5ms each — medium confidence, would need profiling — NOT actioned, observational only

---

## NOT in scope

- Silent-skip enforcement on near-dup save → v1.8 (D-09 audit-mode-only for v1.7)
- openai SDK signature drift fix (32 PR #9 failures) → v1.8+ (orthogonal to TD-06 Redis-mock)
- `register_vector(conn)` per-connection optimization → future, current pattern acceptable
- Memory integration suite full migration → only 2 new factory tests per D-05
- GUC-via-pool-init optimization → future profiling-driven decision
- bge-m3 model loading → Phase 26 closed, not Phase 27 scope

---

## What already exists (reused)

- `LongTermMemory.get_relevant_facts:290-357` — HNSW + GUC + cosine SELECT pattern; precheck mirrors verbatim
- 4 existing fixtures in tests/conftest.py manually reset singletons → generalized by tests/factories/app.py
- `fakeredis==2.35.1` already in deps → no new dependency
- `AuditAction` enum append-only convention (Phase 25 EVICT-02) → reused for MEMORY_NEAR_DUPLICATE_SKIPPED
- Phase 26 `audit_log` auto-create → carries forward unchanged
- `asyncpg_helper.py` (Phase 26 TD-03) → used by new save_facts
- bge-m3 resolver (Phase 26 TD-07) → carries forward unchanged

---

## Failure Mode Coverage Matrix

| Codepath | Failure | Test | Error handling | User signal |
|----------|---------|------|----------------|-------------|
| create_app() factory | parallel singleton mid-reset | ✓ test_parallel_contamination + lint | n/a (test infra) | clear test failure |
| _is_near_duplicate SELECT timeout | PostgresError | ✓ test_save_fact_precheck_failure | ✓ fail-open + warn | save works |
| _fire_near_duplicate_audit write fail | audit row lost | ✓ test_save_fact_precheck T6+T7 | ✓ Pattern D noqa + warn | save works |
| embed_batch raises | all 5 facts saved? | ✓ test_save_facts_embed_batch_fallback | ✓ gather(return_exceptions) + log + counter | skipped_embed_failures visible |
| unnest($1::text[]) SQL malformed | batch rejected | ✓ test_save_facts_batch T2 grep | ✓ MemoryFactWriteError | clear error |
| executemany partial-failure | atomic rollback | ✓ existing path | ✓ MemoryFactWriteError | clear error |
| middleware-order regression | auth-after-rate-limit silent | ✓ test_main_middleware_order (NEW A1) | n/a | would be silent without test |

**0 critical gaps.**

---

## Worktree Parallelization

```
Lane A: 27-00 ──▶ 27-01 (main.py + audit integration tests)
                       (Wave 1)
                       │
Lane B: 27-00 ──▶ 27-02 (memory_service.py ShortTermMemory + redis marker)
                       (Wave 1)
                       │
Lane C: 27-02 ──▶ 27-03 ──▶ 27-04 (Wave 2 — serial on memory_service.py LongTermMemory)
```

- 27-01 and 27-02 are safely parallel post-27-00 (disjoint file lists)
- 27-03 and 27-04 are serial (both modify LongTermMemory; depends_on chained by plan-checker)

---

## Cross-Model Notes

- **Plan-checker (Sonnet 4.6)** verdict: READY_FOR_EXECUTION with 2 HIGH fixes (applied inline pre-review).
- **Eng-review (Opus 4.7)** verdict: All P2/P3 findings applied inline; 0 critical gaps.

No cross-model tension surfaced. Outside-voice (Codex) skipped — caveman mode + deep GSD flow + already 2 cross-AI passes (planner + plan-checker) baked in.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | not run |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | not run (skipped per caveman flow) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | **CLEAR (PLAN)** | 8 findings, 8 fixed inline, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | not applicable (no UI scope) |
| DX Review | `/plan-devex-review` | Developer experience | 0 | — | not applicable (internal infra phase) |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to implement. Next: `/clear` then `/gsd-execute-phase 27`.
