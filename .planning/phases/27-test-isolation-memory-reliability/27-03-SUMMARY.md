---
phase: 27-test-isolation-memory-reliability
plan: 03
subsystem: memory
tags: [pgvector, asyncpg, cosine, hnsw, audit-mode, fail-open, tdd]

requires:
  - phase: 23-memory-extractor-agent
    provides: "LongTermMemory.save_fact embed-on-write contract + MemoryFactWriteError typed exception"
  - phase: 24-pgvector-recall
    provides: "HNSW iterative_scan='strict_order' + ef_search GUC discipline (mirrored for precheck)"
  - phase: 25-eviction-gdpr
    provides: "Audit-mode-before-enforce discipline (EVICT-02) — D-09 carry-forward; RULE_BLOCKED 200-char truncation convention"
  - phase: 26-memory-infra-hygiene
    provides: "AuditService lazy pool + INSERT-ONLY audit_log auto-create (Plan 26-04); ShortTermMemory.get_redis delegate (27-02 follow-on)"
provides:
  - "config/settings.py:memory_near_duplicate_threshold (default 0.05, bounds [0.0, 1.0])"
  - "services/audit/audit_service.py:AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED enum value (appended after MEMORY_EVICT)"
  - "services/audit/audit_service.py:AUDIT_DETAIL_TRUNCATE_LEN=200 project-wide constant (CQ3)"
  - "LongTermMemory._is_near_duplicate(conn, *, user_id, tenant_id, embedding, threshold) -> (bool, float|None)"
  - "LongTermMemory._fire_near_duplicate_audit(user_id, tenant_id, fact, dist) staticmethod"
  - "LongTermMemory.save_fact body: embed → precheck (fail-OPEN on PostgresError|InterfaceError) → audit emit (best-effort) → INSERT (unconditional, D-09 audit-mode-only)"
affects:
  - "27-04 save_facts batch path (builds dedupe SQL on top of this; D-12 makes save_fact a thin wrapper after 27-04 ships)"
  - "v1.8 silent-skip promotion (this plan ships metric-only; v1.8 flips to skip with TOCTOU mitigation per A2 / plan notes)"
  - "Ops dashboards consuming audit_log.action=MEMORY_NEAR_DUPLICATE_SKIPPED metric"

tech-stack:
  added: []
  patterns:
    - "Cosine precheck inside SET LOCAL GUC transaction (mirrors get_relevant_facts:336-352)"
    - "Fail-OPEN on data-query failure: catch (PostgresError, InterfaceError), log warning, proceed with primary write"
    - "Project-wide AUDIT_DETAIL_TRUNCATE_LEN constant for user-controlled audit_log.detail fields"
    - "Test-helper extension via optional kwarg (fetchrow_mock=None) preserves backward-compatible call sites"

key-files:
  created:
    - "tests/unit/memory/__init__.py — package marker"
    - "tests/unit/memory/test_save_fact_precheck.py — 5 SC-3 D-09 audit-mode-only contract tests"
    - "tests/unit/memory/test_save_fact_precheck_failure.py — 5 fail-OPEN + Pattern D tests"
  modified:
    - "config/settings.py — +5 lines: memory_near_duplicate_threshold field"
    - "services/audit/audit_service.py — AUDIT_DETAIL_TRUNCATE_LEN constant + MEMORY_NEAR_DUPLICATE_SKIPPED enum entry + 1 hardcoded-200 refactor"
    - "services/memory/memory_service.py — +113 lines: _is_near_duplicate + _fire_near_duplicate_audit + save_fact body restructure"
    - "tests/unit/test_memory_save_fact.py — extend _make_fake_pool with fetchrow+transaction mocks; update happy-path assertion shape"

key-decisions:
  - "D-09 audit-mode-only WINS over ROADMAP SC-3 wording: precheck hit emits MEMORY_NEAR_DUPLICATE_SKIPPED AND INSERT still runs. Tests pin this so v1.8 silent-skip promotion cannot quietly regress."
  - "Fail-OPEN catch broadened beyond plan's PostgresError-only spec to (PostgresError, InterfaceError) — Rule 2 correctness fix. InterfaceError is a SIBLING (not subclass) of PostgresError; client-side connection drops during precheck must NOT block the save."
  - "_fire_near_duplicate_audit placed as @staticmethod on LongTermMemory class per CQ3 — tightly coupled to save_fact's audit emission; lives next to its only caller."
  - "AUDIT_DETAIL_TRUNCATE_LEN=200 constant added per CQ3 and back-applied to log_rule_blocked() (single existing hardcoded 200 in repo). Future audit emits should import + use this constant."
  - "Precheck uses ORDER BY ... LIMIT 1 (not WHERE <threshold LIMIT 1) so audit row carries actual nearest distance (D-08)."

patterns-established:
  - "Cosine precheck + GUC discipline + per-(user,tenant) RLS pre-filter: services/memory/memory_service.py::_is_near_duplicate is the canonical analog for any future audit-mode duplicate-detection guard."
  - "Fail-OPEN around data-query helpers: catch (asyncpg.PostgresError, asyncpg.InterfaceError) tuple at the caller boundary, log warning, return non-blocking default; mirrors the (PostgresError, InterfaceError) tuple in 27-04 batch path."
  - "Test-helper backward compatibility via optional kwarg defaults: _make_fake_pool grew fetchrow_mock=None so all existing call sites kept working while new precheck tests received an explicit mock."

requirements-completed: [TD-04]

duration: 7min
completed: 2026-05-17
---

# Phase 27 Plan 03: save_fact Cosine Precheck (D-09 Audit-Mode-Only) Summary

**LongTermMemory.save_fact now runs a per-(user,tenant) cosine precheck before INSERT and emits `MEMORY_NEAR_DUPLICATE_SKIPPED` to audit_log when distance < 0.05 — but the INSERT still runs (v1.7 audit-mode-only per D-09).**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-05-17T07:16:00Z
- **Completed:** 2026-05-17T07:23:21Z
- **Tasks:** 3 (all TDD: RED → GREEN, no REFACTOR commits needed)
- **Files modified:** 7 (3 production, 4 test/marker)
- **LOC delta:** +600 / −8

## Accomplishments

- Phase 27 SC-3 landed per D-09 corrected semantics: audit metric emitted, save NOT skipped.
- 10 new unit tests pin the audit-mode-only contract so v1.8 silent-skip promotion cannot silently regress without flipping explicit "INSERT-still-ran" assertions.
- Pre-existing `tests/unit/test_memory_save_fact.py` regression suite stays green (6/6).
- Project-wide audit-detail truncation constant centralized in `services/audit/audit_service.py` (CQ3).
- One bug surfaced and fixed: fail-OPEN catch broadened to also cover `asyncpg.InterfaceError` (Rule 2).

## Task Commits

Each task was committed atomically:

1. **Task 1: settings field + AuditAction enum + AUDIT_DETAIL_TRUNCATE_LEN constant** — `bc00a29` (feat)
2. **Task 2: LongTermMemory._is_near_duplicate + _fire_near_duplicate_audit + save_fact wiring** — `897318f` (feat) — TDD red→green; also patched `tests/unit/test_memory_save_fact.py::_make_fake_pool` for forward-compat
3. **Task 3: New precheck unit test suite (5 + 5 tests) + InterfaceError fail-OPEN fix** — `dd53033` (test)

_Plan metadata commit (this SUMMARY) follows._

## Files Created/Modified

### Created
- `tests/unit/memory/__init__.py` — package marker for new memory test package
- `tests/unit/memory/test_save_fact_precheck.py` — 5 tests: D-09 audit-mode-only contract (audit+INSERT), no-audit happy paths (empty table, dist>=threshold), +1 PG RTT bound, per-(user,tenant) filter in precheck SQL
- `tests/unit/memory/test_save_fact_precheck_failure.py` — 5 tests: fail-OPEN parametrize [PostgresError, ConnectionDoesNotExistError, InterfaceError], audit-write RuntimeError non-fatal, INSERT-failure-still-raises sanity gate

### Modified
- `config/settings.py` — appended `memory_near_duplicate_threshold: float = Field(default=0.05, ge=0.0, le=1.0)` after `memory_facts_cap_per_user` (memory-section locality per D-07)
- `services/audit/audit_service.py` — added module-level `AUDIT_DETAIL_TRUNCATE_LEN = 200` constant; appended `MEMORY_NEAR_DUPLICATE_SKIPPED = "MEMORY_NEAR_DUPLICATE_SKIPPED"` to `AuditAction` after `MEMORY_EVICT` (D-08); refactored `log_rule_blocked` `message[:200]` → `message[:AUDIT_DETAIL_TRUNCATE_LEN]`
- `services/memory/memory_service.py` — +113 lines: new `_is_near_duplicate` async method, new `_fire_near_duplicate_audit` staticmethod, restructured `save_fact` body to thread precheck between embed and INSERT (fail-OPEN catches `(asyncpg.PostgresError, asyncpg.InterfaceError)`)
- `tests/unit/test_memory_save_fact.py` — extended `_make_fake_pool(execute_mock, fetchrow_mock=None)`; conn mock now also provides `fetchrow` + `transaction()`; happy-path test now asserts 2 SET LOCAL + 1 INSERT shape (was 1 INSERT) + `fetchrow.await_count == 1`

## Decisions Made

- **D-09 override pinned in tests, not just comments.** Plan was explicit: ROADMAP SC-3 reads "save is skipped" — wrong for v1.7. Test 1 (`test_precheck_emits_audit_when_near_duplicate_and_still_inserts`) explicitly asserts the INSERT call count == 1 even when fetchrow returns `{"dist": 0.02}`. Future v1.8 author MUST flip this assertion (not just delete it) — the test name documents the v1.7 contract.
- **InterfaceError added to fail-OPEN tuple.** Plan called for `except asyncpg.PostgresError` only, but the parametrize matrix in plan Task 3 listed `[PostgresError, ConnectionDoesNotExistError, InterfaceError]`. asyncpg's `InterfaceError` is a SIBLING (not subclass) of `PostgresError`. Tests would have failed with InterfaceError leaking through. Broadened catch to `(asyncpg.PostgresError, asyncpg.InterfaceError)` — see Deviations §1.
- **AUDIT_DETAIL_TRUNCATE_LEN constant introduced and back-applied.** CQ3 in plan asked for this. Found exactly 1 hardcoded `200` in audit_service.py (`log_rule_blocked.message[:200]`); refactored to use the constant. Future audit emits should import + use it.
- **Test-helper backward compatibility via optional kwarg.** Rather than introducing a new helper, extended `_make_fake_pool` in the existing test file with `fetchrow_mock=None` default → all existing call sites kept working while new precheck tests pass explicit mocks. New test files inline a fresh copy of the helper (per PATTERNS.md guidance) for isolation.
- **NO architectural changes.** No new tables, no new services, no DI rewrite. Stays inside the 27-03 scope envelope.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Broadened fail-OPEN except clause to also catch `asyncpg.InterfaceError`**

- **Found during:** Task 3 (`test_precheck_postgres_error_is_fail_open[InterfaceError]` failed under the plan-specified `except asyncpg.PostgresError` only)
- **Issue:** asyncpg's exception tree puts `InterfaceError` and `PostgresError` as SIBLINGS, not parent/child. The plan listed `[PostgresError, ConnectionDoesNotExistError, InterfaceError]` in the parametrize matrix as the spec for fail-OPEN behavior, but the production code only caught `PostgresError`. `InterfaceError` (and any other client-side protocol/connection failure during the precheck) would have leaked all the way to the caller of `save_fact`, breaking the fail-OPEN contract.
- **Fix:** Changed `except asyncpg.PostgresError as exc:` to `except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:` in `save_fact` around the precheck call. Added a comment in `memory_service.py` documenting the sibling-not-subclass relationship for future readers.
- **Files modified:** services/memory/memory_service.py (1 line + comment)
- **Verification:** All 10 new tests pass, including the `InterfaceError` parametrization; pre-existing 6 `test_memory_save_fact.py` tests still green; ruff clean; mypy per-file error count UNCHANGED vs baseline.
- **Committed in:** dd53033 (Task 3 commit)

**2. [Rule 3 - Blocking] Extended `tests/unit/test_memory_save_fact.py::_make_fake_pool` with fetchrow + transaction() mocks**

- **Found during:** Task 2 GREEN (regression check)
- **Issue:** Existing happy-path test injected a `conn = MagicMock(execute=execute_mock)` with no `fetchrow` or `transaction()`. Adding the precheck SELECT to `save_fact` made `await conn.fetchrow(...)` blow up with `TypeError: object MagicMock can't be used in 'await' expression`. Plan acceptance criterion explicitly requires existing save tests stay green.
- **Fix:** Extended helper with optional `fetchrow_mock=None` kwarg (defaults to `AsyncMock(return_value=None)` → empty-table path → no audit, INSERT proceeds), added `conn.transaction = MagicMock(return_value=_AcquireCtx(conn))` so SET LOCAL execute calls hit the same mock. Updated the happy-path assertion shape: now expects 2 SET LOCAL + 1 INSERT executes (was 1 INSERT) and `fetchrow.await_count == 1`.
- **Files modified:** tests/unit/test_memory_save_fact.py (~25 lines)
- **Verification:** All 6 pre-existing tests pass.
- **Committed in:** 897318f (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 missing critical / Rule 2, 1 blocking / Rule 3)
**Impact on plan:** Both auto-fixes essential for satisfying the plan's own acceptance criteria. No scope creep — both fixes stay inside the 27-03 scope envelope (no new files beyond plan, no architectural changes).

## Issues Encountered

- **Worktree branch was stale** at session start (branched from 85ca25f, way behind master). Fast-forwarded with `git merge --ff-only master` before starting work — no merge commits, no conflicts. This was a setup-time issue from the worktree creation, not an execution issue.

## D-09 Override Callout (FOR VERIFICATION.md AUTHOR)

This is the SC-3 wording trap. The plan's `<notes>` section and `<execution_context>` made it explicit, but it MUST be re-stated in VERIFICATION.md so it doesn't get lost across phase boundaries:

> ROADMAP §"Phase 27" SC-3 reads: "When the precheck hits, the save is skipped..."
> CONTEXT D-09 (canonical): "v1.7 emits the audit row but DOES NOT SKIP THE SAVE. Save still happens — duplicate row inserted."
>
> **VERIFICATION MUST test for "audit row written AND duplicate row inserted" — NOT "save skipped."**
> The test `tests/unit/memory/test_save_fact_precheck.py::test_precheck_emits_audit_when_near_duplicate_and_still_inserts` already pins this contract. v1.8 silent-skip promotion will flip the assertion; do not pre-emptively flip in v1.7 verification.

## Audit-Row vs INSERT-Still-Runs Assertion List

Concrete test references for the D-09 contract:

| Assertion | Test | What it pins |
|-----------|------|--------------|
| `audit.log.await_count == 1` | test_save_fact_precheck.py::test_precheck_emits_audit_when_near_duplicate_and_still_inserts | Audit row IS emitted on near-dup hit (dist=0.02) |
| `event.action == AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED` | same test | Correct action enum value |
| `event.detail["nearest_distance"] == pytest.approx(0.02)` | same test | D-08 nearest_distance carried into detail JSONB |
| `event.detail["fact_truncated"] == "user prefers React"` | same test | D-08 fact_truncated carried into detail JSONB |
| `len(insert_calls) == 1` (INSERT call count) | same test | **D-09: INSERT runs even on near-dup hit (audit-mode-only)** |
| `audit.log.await_count == 0` (not near-dup) | test_precheck_no_audit_when_not_near_duplicate | No audit when dist >= threshold |
| `audit.log.await_count == 0` (empty table) | test_precheck_no_audit_when_table_empty | No audit when table empty |
| `conn.fetchrow.await_count == 1` | test_precheck_adds_exactly_one_pg_rtt | +1 PG RTT bound (D-10) |
| `"user_id=$1 AND tenant_id=$2" in sql` | test_precheck_uses_per_user_tenant_filter | T-27-03-01 mitigation: per-(user,tenant) filter present in SQL |
| `call.args[1] == "alice", call.args[2] == "acme"` | same test | Test IDs bound as positional params $1/$2 |

## Precheck SQL Shape (CONFIRMED ORDER BY ... LIMIT 1 per D-08)

```sql
SELECT embedding <=> $3::vector AS dist
FROM long_term_facts
WHERE user_id=$1 AND tenant_id=$2
ORDER BY embedding <=> $3::vector
LIMIT 1
```

Wrapped inside `async with conn.transaction():` with `SET LOCAL hnsw.iterative_scan = 'strict_order'` + `SET LOCAL hnsw.ef_search = {pgvector_ef_search_filtered}` (GUC discipline mirror of `get_relevant_facts:336-352`).

**NOT** the `WHERE ... < $threshold LIMIT 1` boolean form. ORDER BY + LIMIT 1 + post-check enables the audit row to carry the actual nearest distance per D-08.

## v1.8+ Follow-Ups (TO PROPAGATE TO STATE.md)

The orchestrator owns STATE.md writes, but these MUST land there when this phase ships:

1. **"v1.8+ follow-up: silent-skip rollout for MEMORY_NEAR_DUPLICATE_SKIPPED"** — flip `save_fact` body to actually skip the INSERT when `is_dup` is true. The test `test_precheck_emits_audit_when_near_duplicate_and_still_inserts` will need its `INSERT count == 1` assertion changed to `INSERT count == 0` at that time. Track the v1.7 contract reference in the v1.8 plan.
2. **"v1.8+ follow-up: TOCTOU mitigation for cosine precheck"** — when silent-skip is enforced, the SELECT-then-INSERT pattern has a TOCTOU race: two parallel `save_fact` calls with near-identical embeddings can both see "no dup" before either commits, then both INSERT. v1.7 is unaffected because INSERT is unconditional. v1.8 options: (a) advisory lock per (user, tenant), (b) `INSERT ... ON CONFLICT` with a cosine-distance unique-ish index (hard with pgvector), or (c) accept the race and rely on the precheck only being a "good-faith" guard.
3. **"v1.8+ follow-up: openai SDK signature drift (32 PR #9 unit failures)"** — pre-existing v1.8 todo, unaffected by this plan. Already in STATE.md per `85ca25f docs(state): record PR #9 merge + openai SDK drift v1.8+ todo`.

## Stub & Threat Surface Scan

- **Known stubs:** None. All wired code paths execute real logic (precheck SELECT, audit emit, INSERT). The `AuditResult.SKIPPED` value used in the audit row is *semantic* (the v1.8 silent-skip intent) — not a stub.
- **Threat flags:** None new beyond the plan's `<threat_model>` (T-27-03-01..T-27-03-05). All mitigations landed:
  - T-27-03-01 (cross-tenant leak via precheck): per-(user,tenant) filter in SQL + test 5 asserts presence
  - T-27-03-02 (audit-write repudiation): Pattern D try/except wraps audit emit; logged warning; save still proceeds; test `test_audit_log_failure_is_non_fatal` pins this
  - T-27-03-03 (audit log poisoning via fact content): `fact[:AUDIT_DETAIL_TRUNCATE_LEN]` truncation
  - T-27-03-04 (precheck DoS): unchanged; accepted per plan
  - T-27-03-05 (nearest_distance disclosure): unchanged; accepted per plan

## Next Phase Readiness

- **27-04 unblocked.** Plan 27-04 builds `save_facts(facts: list[...])` on top of `save_fact` per D-12 (after 27-04, `save_fact` becomes a thin wrapper). The cosine-distance helper signature `_is_near_duplicate(conn, *, user_id, tenant_id, embedding, threshold) -> (bool, float|None)` is stable; 27-04's bulk dedupe path can either reuse `_is_near_duplicate` per-row or call its bulk SQL analog (D-13). The static `_fire_near_duplicate_audit(user_id, tenant_id, fact, dist)` helper is also stable and can be reused for per-row audit emission inside the batch path.
- **No blockers.** All plan acceptance criteria met. Pre-existing test suite green. ruff clean. mypy --strict per-file error counts UNCHANGED vs baseline.

## Self-Check: PASSED

- `config/settings.py:memory_near_duplicate_threshold` present, default 0.05, bounds [0.0, 1.0]: FOUND
- `services/audit/audit_service.py:AuditAction.MEMORY_NEAR_DUPLICATE_SKIPPED` appended after MEMORY_EVICT: FOUND
- `services/memory/memory_service.py:_is_near_duplicate` (definition + 1 call site): FOUND (2 occurrences)
- `services/memory/memory_service.py:_fire_near_duplicate_audit` staticmethod: FOUND
- `tests/unit/memory/__init__.py`: FOUND
- `tests/unit/memory/test_save_fact_precheck.py` (5 tests): FOUND
- `tests/unit/memory/test_save_fact_precheck_failure.py` (5 tests, includes parametrize): FOUND
- Commit bc00a29 (Task 1): FOUND
- Commit 897318f (Task 2): FOUND
- Commit dd53033 (Task 3): FOUND
- All 16 (10 new + 6 existing) save_fact-related unit tests pass: PASSED
- ruff config/settings.py services/audit/audit_service.py services/memory/memory_service.py tests/unit/memory/: PASSED
- mypy --strict per-file error counts unchanged vs baseline (settings: 1==1, audit: 3==3, memory: 21==21): PASSED

---
*Phase: 27-test-isolation-memory-reliability*
*Completed: 2026-05-17*
