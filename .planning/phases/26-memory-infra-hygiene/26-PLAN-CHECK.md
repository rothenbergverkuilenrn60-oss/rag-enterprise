# Phase 26: Memory Infra Hygiene — Plan-Eng-Review

**Reviewed:** 2026-05-17
**Reviewer:** /plan-eng-review (Claude inline; agents_installed=false → no codex outside voice executed by tooling)
**Plans reviewed:** 26-01, 26-02, 26-03, 26-04, 26-05 (1501 LOC of plan markdown across 12 files of code touched)
**Verdict:** CLEAR after 5 fixes applied (A1, A2, C1, P1, T1)

---

## Step 0 — Scope Challenge

**Complexity gate:** Tripped (12 files touched > 8 threshold).
**Decision:** Proceed as-is. 6 of 12 files are net-new test files (1:1 test:production parity required by v1.0 ERR-01 + v1.3 TEST-04 carry-forward gates). The file count is inflated by test discipline, not scope sprawl.

**Existing assets reused (vs rebuilt):**
- `LongTermMemory._get_pool` + `_create_tables` pattern — Plan 26-04 ports verbatim for AuditService (TD-01 ∩ TD-03).
- `services/memory/memory_service.py:163-172` inline `?ssl=disable` strip — Plan 26-01 extracts to `utils/asyncpg_helper.prepare_dsn`, Plans 26-03 + 26-04 consume.
- FastAPI `@asynccontextmanager lifespan` (already present in main.py) — Plan 26-05 only adds two close() calls to the existing shutdown block. No lifespan refactor needed.
- `tests/conftest.py::pg_pool` function-scope fixture (v1.6 Phase 25 hotfix) — Plans 26-04 + 26-05 integration tests consume.

**Layer attribution:** Layer 1 throughout (asyncpg pool, Pydantic V2 computed_field, FastAPI lifespan, pytest fixtures, mock-at-consumer-path). Zero first-principles invention. Zero new frameworks.

**Search check:** Not run via WebSearch (offline). All patterns are project-internal Layer 1 — no need to validate against external best-practice guides.

---

## Section 1 — Architecture Review (2 findings, both fixed)

### Finding A1 (confidence: 9/10) — DSN scheme strip divergence

**Where:** Plan 26-01 `prepare_dsn` body vs `services/audit/audit_service.py:261` current `dsn.replace("+asyncpg", "")` substring strip.

**Problem:** v1.6 audit code strips only `+asyncpg` (substring); `prepare_dsn` does a literal `postgresql+asyncpg://` → `postgresql://` replace. For `postgres+asyncpg://u@h/d` (rare short scheme), audit currently produces working `postgres://u@h/d`; new helper produces broken `postgres+asyncpg://u@h/d`.

**Decision:** Add explicit unit test for both schemes (test 8 in Plan 26-01) AND extend `prepare_dsn` body to handle both `postgresql+asyncpg://` and `postgres+asyncpg://` scheme prefixes (order matters — longer prefix first).

**Applied to:** `.planning/phases/26-memory-infra-hygiene/26-01-PLAN.md` Task 1 (added `test_strips_postgres_short_asyncpg_scheme`) + Task 2 (added second `.replace()` call to helper body + ordering comment).

### Finding A2 (confidence: 8/10) — AuditService.close() drains buffer without acquiring self._lock

**Where:** Plan 26-04 Task 2 proposed `close()` method.

**Problem:** Existing `flush()` (line 298-302) wraps `_flush_to_db()` in `async with self._lock`; buffer-overflow path (line 134-140) also acquires lock. Proposed `close()` calls `_flush_to_db()` directly. Concurrent buffer-overflow flush + close() race on `self._buffer` (copy + clear is not atomic across awaits) → audit events lost or double-written on shutdown.

**Decision:** Wrap close()'s drain in `async with self._lock` to match the existing locking contract verbatim.

**Applied to:** `.planning/phases/26-memory-infra-hygiene/26-04-PLAN.md` Task 2 (close() code updated with `async with self._lock`) + Task 1 (added `test_close_acquires_lock_during_drain` unit test).

### Architecture notes (not raised as findings)

- **Concurrent first-acquire race on `_get_pool`:** AuditService's `self._lock` already serializes all `_flush_to_db` callers, so the lazy `_get_pool` build is single-flight in practice. Verified at line 99/134/301. No issue.
- **MemoryService.close() cascade pattern:** Plan 26-05 Task 1 explicitly specifies Branch B(i) as default. Adequate locking-down for executor.
- **Graceful-shutdown re-entry (close-then-reuse):** After `audit_service.close()`, background tasks still in flight could call `log_event` which lazily re-builds the pool. Not Phase 26 scope (affects every pool-bearing service, not just audit). Added to deferred ideas below.

---

## Section 2 — Code Quality Review (1 finding, fixed)

### Finding C1 (confidence: 9/10) — Inherited URL-strip bug: `?ssl=disable&other=1` produces malformed DSN

**Where:** v1.6 `services/memory/memory_service.py:168` token loop (inherited pattern) + Plan 26-01 verbatim port.

**Problem:** Token loop replaces `?ssl=disable` and `&ssl=disable` as literal strings. For input `postgresql://u@h/d?ssl=disable&other=1`:
- `?ssl=disable` matches → replaced with `""` → result `postgresql://u@h/d&other=1`
- Leading `&` with no `?` — asyncpg URL parser rejects.

Untested in v1.6 production (nobody hits this DSN shape) but the verbatim port inherits the bug. Plan 26-01's 7 baseline tests cover `?ssl=disable` alone and `?other=1&ssl=disable` (ssl at end) but NOT `?ssl=disable&other=1` (ssl at start with following params).

**Decision:** Fix in `prepare_dsn` body via ordered try sequence (`&ssl=disable` first, then `?ssl=disable&` for prefix-with-delimiter form, then `?ssl=disable` for sole-param case). Add test 9 `test_strips_ssl_disable_with_following_params`.

**Applied to:** `.planning/phases/26-memory-infra-hygiene/26-01-PLAN.md` Task 1 (added test) + Task 2 (helper body rewritten with ordered ssl strip + 4-case discipline comment).

### Code quality notes (not raised)

- **Plan 26-04 narrow-then-broad except clauses:** Plan body has `except asyncpg.PostgresError` then `except Exception`, both with identical recovery (warning log + buffer prepend). Letter-of-law satisfies v1.0 ERR-01 (no bare except, narrow type first). Functionally a single broad except. Acceptable as written — the narrow type is informational for log greppability.

---

## Section 3 — Test Review

See coverage diagram in the eng-review chat transcript. Summary:

- **28/30 paths covered** (93%) after A1/A2/C1/P1/T1 fixes applied.
- **Quality:** 23 ★★★, 5 ★★, 1 ★, 0 GAPS remaining.
- **No LLM/eval gaps:** Phase 26 is pure infra; no prompt changes; no AGENT_TOOL_ALLOWLIST mutations.
- **No UI/UX surface:** Backend-only; no `qa`/`qa-only` test plan artifact needed.

### Regression tests added (IRON RULE)

- **R1 (T1 above):** `test_close_vs_overflow_flush_no_event_loss` in Plan 26-04 Task 1. Proves A2 lock fix prevents event loss/duplication under concurrent close() + buffer-overflow flush.

### Integration tests already in plans

- `tests/integration/test_audit_log_auto_create.py` (Plan 26-04 Task 3) — 2 tests: cold-start auto-create, INSERT-ONLY grants enforced. Closes TD-01 SC-1 from REQUIREMENTS.md.
- `tests/integration/test_lifespan_shutdown_closes_pools.py` (Plan 26-05 Task 4) — 3 tests: audit pool closes, memory pool closes, ordering audit-before-memory. Closes TD-01 SC-4 from REQUIREMENTS.md.

---

## Section 4 — Performance Review (1 finding, fixed)

### Finding P1 (confidence: 7/10) — Pool cached before `_create_tables` succeeds; partial-init becomes permanent

**Where:** Plan 26-04 Task 2 proposed `_get_pool` (also affects v1.6 `LongTermMemory._get_pool` — inherited pattern).

**Problem:** `self._pool = await asyncpg.create_pool(...)` runs BEFORE `await self._create_tables()`. If `_create_tables` raises (transient PG error, network blip, role lacks CREATE privilege the first time), pool is already cached. Caller's try/except recovers, but next `_get_pool()` call short-circuits on the `if self._pool is None` check, returns the cached pool, **never retries `_create_tables`**. Subsequent INSERTs into the un-created table fail forever until process restart.

**Decision:** Wrap `_create_tables` in try/except inside `_get_pool`. On failure: `pool.close()`, `self._pool = None`, re-raise. Add `test_create_tables_failure_resets_pool` unit test.

**Applied to:** `.planning/phases/26-memory-infra-hygiene/26-04-PLAN.md` Task 1 (added test) + Task 2 (`_get_pool` body rewritten with try/except + reset).

**Deferred:** Same bug exists in v1.6 `LongTermMemory._get_pool`. Tracked as v1.8 todo (out of TD-* scope; modifying a v1.6-shipped MEM-* path would surprise verifier). See STATE.md deferred ideas update below.

---

## NOT in Scope

Items considered and explicitly deferred from Phase 26:

- **`LongTermMemory._get_pool` P1 backport** — same partial-init bug in the v1.6-shipped memory path. Touches a non-TD-* path; defer to v1.8 to avoid scope confusion in verifier review.
- **Graceful-shutdown close-then-reuse race** — after `audit_service.close()`, in-flight background tasks may call `log_event` and lazily re-build the pool. Affects every pool-bearing service; needs project-wide `_closed: bool` discipline. v1.8+ candidate.
- **`AuditService.close()` `application_name=audit_service` for `pg_stat_activity`** — already noted in CONTEXT.md Theme 2 Claude's Discretion as v1.8 ops todo.
- **`config/model_paths.py` module extraction** — only if resolver grows beyond ~30 lines (more model families).
- **HF hub cache snapshot SHA-pinning** — reproducibility concern for a future phase.
- **TD-02 / TD-04 / TD-05 / TD-06** — Phase 27 scope.
- **DOC-01** — Phase 28 scope.

## What Already Exists

Existing code that partially or fully solves Phase 26 sub-problems (reused, not rebuilt):

| Sub-problem | Existing asset | Plan reuses it? |
|-------------|----------------|-----------------|
| Lazy singleton pool init | `services/memory/memory_service.py::LongTermMemory._get_pool` (v1.6) | YES — Plan 26-04 ports verbatim for AuditService |
| Idempotent `CREATE TABLE IF NOT EXISTS` + invariant grants | `LongTermMemory._create_tables` (v1.6) | YES — Plan 26-04 mirrors structure; INSERT-ONLY REVOKE preserved |
| `?ssl=disable` URL strip | `memory_service.py:163-172` + `audit_service.py:261-270` (duplicated) | YES — Plan 26-01 extracts; Plans 26-03 + 26-04 consume |
| FastAPI lifespan handler | `main.py:46` `@asynccontextmanager lifespan` (modern pattern) | YES — Plan 26-05 only adds 2 close() calls to existing shutdown block |
| Function-scope `pg_pool` fixture | `tests/conftest.py` (v1.6 Phase 25 PR #7 hotfix) | YES — Plans 26-04 + 26-05 integration tests consume |
| Mock-at-consumer-path test discipline | `.planning/milestones/v1.6-phases/25-*/25-CONTEXT.md` carry-forward | YES — all plans use `monkeypatch.setattr("services.<mod>.<dep>", ...)` |

## TODOS to STATE.md

Three deferred items surfaced during this review will be appended to `.planning/STATE.md` Todos (carry-forward) section:

1. **v1.8+ follow-up: P1 backport to LongTermMemory** — `services/memory/memory_service.py::LongTermMemory._get_pool` has the same partial-init bug as the AuditService pre-fix version. Fix landed in Plan 26-04 only; backport in v1.8 for symmetry.
2. **v1.8+ follow-up: graceful-shutdown close-then-reuse discipline** — after `audit_service.close()` / `memory_service.close()`, in-flight background tasks may lazily re-build the pool. Needs project-wide `_closed: bool` guard pattern. Affects audit + memory + (future) any pool-bearing service.
3. **v1.8+ follow-up: AuditService `application_name=audit_service` for `pg_stat_activity` visibility** — ops dashboards would benefit; not blocking.

## Failure Modes

| New codepath | Realistic prod failure | Test covers? | Error visible? |
|--------------|------------------------|--------------|----------------|
| `prepare_dsn` returns malformed DSN | C1 case (`?ssl=disable&other=1`) | YES after C1 fix | asyncpg URL-parse error at first pool build |
| `AuditService._get_pool` partial init | `_create_tables` raises mid-execution | YES after P1 fix | Pool re-builds clean on next attempt |
| `AuditService.close()` race with overflow flush | Concurrent flush during shutdown | YES via R1 regression test | Events lost silently → R1 detects via mock assertion |
| `resolve_embedding_model_path` returns non-existent path | Fresh install, no model anywhere | YES (test 5 returns legacy fallback) | Lazy crash at model-load time (preserves current semantics) |
| `LongTermMemory.close()` called before pool ever built | Test/CI without PG access | YES (Plan 26-03 test 5) | No raise — close is no-op |
| `main.py` lifespan shutdown re-entry | Background task survives request drain | NO — deferred to v1.8 (see deferred ideas) | Pool lazily rebuilds; teardown-immediately-rebuild is wasteful but harmless |

No critical gaps (no failure mode that has no test AND no error handling AND would be silent).

## Worktree Parallelization

Phase 26 has a natural wave structure already:

| Wave | Plans | Modules touched | Depends on |
|------|-------|-----------------|------------|
| 1 | 26-01, 26-02 | `utils/`, `config/`, `tests/conftest.py`, new test files | — |
| 2 | 26-03, 26-04 | `services/memory/`, `services/audit/`, new test files | Wave 1 |
| 3 | 26-05 | `main.py`, revisits `services/memory/`, new test files | Wave 2 |

**Execution order:** Lane A (26-01) + Lane B (26-02) launch in parallel worktrees → merge both → Lane C (26-03) + Lane D (26-04) launch in parallel → merge both → Lane E (26-05).

**Conflict flags:**
- Lane C (26-03) and Lane E (26-05) both touch `services/memory/memory_service.py` — sequential by design (E depends on C). No conflict.
- Lanes A + B touch no shared files. Truly parallel.
- Lanes C + D touch different modules. Truly parallel.

## Implementation Tasks

Synthesized from review findings. Land alongside Plan 26-01 / 26-04 execution.

- [ ] **T1 (P1, human: ~10min / CC: ~5min)** — Plan 26-01 — add A1 + C1 unit tests + fix `prepare_dsn` body
  - Surfaced by: Architecture review A1 (DSN scheme divergence) + Code quality review C1 (URL-strip malformation)
  - Files: `.planning/phases/26-memory-infra-hygiene/26-01-PLAN.md` (already updated)
  - Verify: `uv run pytest tests/unit/test_asyncpg_helper.py -v` → 9/9 after Plan 26-01 Task 2

- [ ] **T2 (P1, human: ~10min / CC: ~5min)** — Plan 26-04 — wrap close() in self._lock + add A2 unit test
  - Surfaced by: Architecture review A2 (close() race with overflow flush)
  - Files: `.planning/phases/26-memory-infra-hygiene/26-04-PLAN.md` (already updated)
  - Verify: `uv run pytest tests/unit/test_audit_service_pool.py::test_close_acquires_lock_during_drain -v`

- [ ] **T3 (P1, human: ~15min / CC: ~5min)** — Plan 26-04 — try/except wrap `_create_tables` in `_get_pool` + P1 unit test
  - Surfaced by: Performance review P1 (partial-init permanent breakage)
  - Files: `.planning/phases/26-memory-infra-hygiene/26-04-PLAN.md` (already updated)
  - Verify: `uv run pytest tests/unit/test_audit_service_pool.py::test_create_tables_failure_resets_pool -v`

- [ ] **T4 (P1, human: ~20min / CC: ~10min)** — Plan 26-04 — R1 regression test for close-vs-overflow race
  - Surfaced by: Test review IRON RULE (regression test mandatory for race fixes)
  - Files: `.planning/phases/26-memory-infra-hygiene/26-04-PLAN.md` (already updated)
  - Verify: `uv run pytest tests/unit/test_audit_service_pool.py::test_close_vs_overflow_flush_no_event_loss -v`

- [ ] **T5 (P3, human: ~30min / CC: ~10min) — DEFERRED to v1.8** — backport P1 fix to `LongTermMemory._get_pool`
  - Surfaced by: Performance review P1 (inherited from v1.6 path)
  - Files: `services/memory/memory_service.py` (v1.8 scope; STATE.md todo updated)
  - Verify: same test pattern as P1, applied to LongTermMemory

## Completion Summary

- Step 0 Scope Challenge: 12 files (above 8-file threshold) → user chose proceed as-is. Reason: 6/12 are required test files (test:production parity per v1.0 ERR-01 + v1.3 TEST-04).
- Architecture Review: 2 issues found (A1 DSN scheme divergence, A2 close() lock missing) — both FIXED.
- Code Quality Review: 1 issue found (C1 URL-strip malformed-output bug, inherited from v1.6) — FIXED.
- Test Review: diagram produced. 0 gaps after fixes. R1 regression test added per IRON RULE.
- Performance Review: 1 issue found (P1 partial-init permanent breakage) — FIXED in 26-04; LongTermMemory backport deferred to v1.8.
- NOT in scope: written above.
- What already exists: written above.
- TODOS.md updates: 3 v1.8+ items to be appended to STATE.md Todos section.
- Failure modes: 0 critical gaps (no untested-AND-silent-AND-unhandled failure mode).
- Outside voice: skipped (no codex tool available in this session).
- Parallelization: 3 lanes (W1 parallel, W2 parallel, W3 sequential — already in plan).
- Lake Score: 5/5 — every finding picked the complete option (fix + test, not defer).

## Unresolved decisions

None. All 5 questions answered.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 4 issues found (A1, A2, C1, P1), 4 fixed; 1 regression test added (R1); 0 critical gaps; 3 v1.8+ todos surfaced |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — (backend-only) | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to implement Phase 26 once plan updates committed. CEO + Design + DX not required (pure backend refactor; no scope or product changes; no UI surface).
