# TODOS

Project-level tech-debt and future-work tracker. Each entry traces back to a
surfacing context (phase, review, incident). v1.8+ planners must read this
file when scoping new milestones.

---

## v1.8+ Follow-ups

### Silent-skip enforcement for near-duplicate memory writes (from Phase 27 / TD-04)

**What:** Promote `LongTermMemory.save_fact` near-duplicate guard from audit-mode-only (v1.7 D-09: emit metric + still INSERT) to silent-skip enforcement (v1.8: emit metric + SKIP INSERT).

**Why:** v1.6 EVICT-02 "Audit-Mode-Before-Enforce" discipline says we observe for one release before flipping the behavior switch. v1.7 ships the precheck + metric; v1.8 should flip to enforcement once production data confirms the threshold (0.05 cosine) is right.

**Pros:** Reduces duplicate fact accumulation in long-term memory. Improves recall precision (less noise from near-identical entries).

**Cons:** Behavioral change for callers — `save_fact` becomes lossy. Some callers may rely on "every call inserts a row" semantics for audit/traceability purposes.

**Context for the v1.8 planner:**
- Phase 27 emits `AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED` whenever the precheck `<embedding> <=> $vec < 0.05` fires. The audit row captures the would-skip intent (`result=AuditResult.SKIPPED`) but the INSERT still runs.
- v1.8 work: change `save_fact` to early-return the existing row's id (or a sentinel) instead of running the INSERT after `_is_near_duplicate` returns `(True, dist)`.
- v1.8 work: change `save_facts` (batch) to filter `rows_to_insert` by the bulk-dedupe result before `executemany` — currently `rows_to_insert` includes near-dups intentionally per D-09.
- v1.8 work: update tests in `tests/unit/memory/test_save_fact_precheck.py` and `test_save_facts_batch_dedupe.py` — they currently assert row count IS incremented on near-dup hit. v1.8 must flip those assertions.

**TOCTOU consideration (raised by Phase 27 plan-eng-review A2):**
Two parallel `save_fact` calls with near-identical embeddings can both see "no dup" before either commits its INSERT, then both INSERT — bypassing the silent skip. v1.8 must address this. Options:
1. Postgres advisory lock per `(user_id, tenant_id)` around the SELECT + INSERT pair (simplest; serializes writes per user, acceptable for memory writes).
2. `INSERT ... ON CONFLICT` with a unique constraint — hard with pgvector cosine distance (no exact-match constraint possible without an LSH hash).
3. Accept the race and treat the precheck as best-effort silent-skip (callers must still tolerate occasional duplicates).

Decide at v1.8 planning time. Option 1 is the boring/safe default.

**Depends on / blocked by:** Phase 27 ship to master + at least one release of audit-mode data to validate the 0.05 threshold against production traffic.

**Surfacing context:** Phase 27 PLAN.md (27-03 frontmatter notes), `/plan-eng-review` finding A2 (2026-05-17).

---

### openai SDK signature drift cleanup (from Phase 27 / TD-06)

**What:** Resolve the ~32 pre-existing unit test failures attributed to `openai.APIError.__init__() missing 'request'` argument — distinct from the Redis-mock-related failures that Phase 27 / TD-06 closes.

**Why:** Phase 27 D-22 diagnostic step explicitly separates Redis-mode failures (closed by TD-06) from openai-SDK signature drift (orthogonal, persists). These should not block ship but need cleanup.

**Context:** likely caused by an openai SDK version bump where mock-construction sites in tests pass `request=` arg in a position that no longer matches the new signature. Grep for `APIError(` in tests/ to find the call sites.

**Surfacing context:** Phase 27 27-02-PLAN.md acceptance criterion (documents the orthogonal failure count in SUMMARY.md).

---
