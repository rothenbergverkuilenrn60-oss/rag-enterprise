---
phase: 24-pgvector-recalltool-semantic-recall-rewrite
plan: "06"
subsystem: memory
tags: [backfill, cli, idempotent, chunked-commit, asyncpg, batch-update-unnest, dry-run, txn-rollback, cost-docs, MEM-07]
dependency_graph:
  requires: [24-02]
  provides: [MEM-07]
  affects: [long_term_facts.embedding, docs/memory-eviction.md]
tech_stack:
  added: []
  patterns: [argparse+asyncio.run CLI, chunked-commit cursor loop, batch UPDATE via unnest, LongTermMemory pool reuse]
key_files:
  created:
    - scripts/backfill_fact_embeddings.py
    - docs/memory-eviction.md
    - tests/unit/test_backfill_fact_embeddings.py
  modified: []
decisions:
  - "T4 (Decision-5): batch UPDATE via unnest($1::uuid[], $2::vector[]) — one execute per batch, not row-by-row"
  - "T5 (Decision-3): except (asyncpg.PostgresError, asyncpg.InterfaceError) — asyncpg.Error does not exist in this asyncpg version; tuple catch is equivalent and satisfies ERR-01"
  - "T10 (Decision-4): ASCII loop diagram in backfill() docstring"
  - "Pool reuse via LongTermMemory()._get_pool() inherits register_vector codec (Pitfall 1)"
metrics:
  duration_seconds: 325
  completed_date: "2026-05-16"
  tasks_completed: 2
  files_created: 3
---

# Phase 24 Plan 06: MEM-07 Backfill CLI + Cost Docs Summary

MEM-07 backfill script — idempotent chunked-commit CLI using batch UPDATE via unnest with narrow asyncpg exception handling and ASCII docstring diagram.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RED: 9 unit tests for backfill CLI | a4f33cb | tests/unit/test_backfill_fact_embeddings.py |
| 2 | GREEN: backfill CLI + docs companion | 9aaf03e | scripts/backfill_fact_embeddings.py, docs/memory-eviction.md, tests/unit/test_backfill_fact_embeddings.py |

## Test Results

- 10/10 unit tests GREEN (9 unique + 1 parametrize expansion for T5)
- 30/30 regression tests GREEN (test_memory_recall_semantic.py + test_recall_tool.py)
- ruff check: 0 violations
- mypy --strict: 0 new violations (pre-existing baseline from asyncpg missing stubs + untyped memory_service.py dependencies)

## Acceptance Gates Verified

- `grep -n 'UPDATE long_term_facts'` → 3 matches (SQL in code + docstring)
- `grep -n 'FROM unnest'` → 4 matches (T4 batch UPDATE form present)
- Row-by-row form (`SET embedding=$1::vector WHERE id=$2`) → 0 matches
- `grep -n 'except.*asyncpg'` → 6 matches (T5 narrow catch present)
- noqa BLE001 → 0 matches
- bare `except Exception` → 0 matches
- T10 ASCII diagram: `┌` present in backfill() docstring (exits 0)
- `grep -n 'LongTermMemory()'` → 1 match at line 92 (Pitfall 1 pool reuse)
- `asyncpg.create_pool` in non-comment lines → 0 matches
- LOC: scripts/backfill_fact_embeddings.py = 219 (within 100-250)
- LOC: docs/memory-eviction.md = 49 (within 25-80)
- `grep -n 'uv run python'` in docs → 6 matches (≥3 required)
- CronJob/systemd/cron in docs → 0 matches
- conda in docs → 0 matches

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] asyncpg.Error does not exist in this asyncpg version**
- **Found during:** Task 2, first GREEN test run
- **Issue:** Plan T5 spec says `except asyncpg.Error as exc:` but `asyncpg.Error` is not an attribute of the asyncpg module. `asyncpg.PostgresError` and `asyncpg.InterfaceError` have no common `asyncpg.Error` ancestor — they both inherit from `Exception` directly.
- **Fix:** Changed catch to `except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:` — a tuple catch covering both subclasses. Semantically equivalent to the intended narrow catch; satisfies ERR-01; no bare Exception; no noqa.
- **Files modified:** scripts/backfill_fact_embeddings.py (line ~166)
- **Commit:** 9aaf03e

**2. [Rule 1 - Bug] Fake pool harness missing pool.fetch binding**
- **Found during:** Task 2, first test run after GREEN implementation
- **Issue:** `_make_fake_pool` set `conn.fetch = fetch_mock` but the backfill script calls `pool.fetch(...)` (direct pool method, not via acquire/conn). Pool's `fetch` mock was a MagicMock, causing `TypeError: object MagicMock can't be used in 'await' expression`.
- **Fix:** Added `pool.fetch = fetch_mock` to the harness — the fetch_mock AsyncMock is now bound on both `conn` and `pool`.
- **Files modified:** tests/unit/test_backfill_fact_embeddings.py
- **Commit:** 9aaf03e

## Known Stubs

None. The script fetches real data from `long_term_facts` via parameterized queries; no hardcoded empty values flow to output.

## Threat Flags

None. All new SQL uses parameterized bindings (`$1`, `$2`). No new network endpoints introduced. No DSN logged (pool reused from LongTermMemory). Threat model in PLAN.md fully honored.

## Self-Check: PASSED

- `tests/unit/test_backfill_fact_embeddings.py` — FOUND
- `scripts/backfill_fact_embeddings.py` — FOUND
- `docs/memory-eviction.md` — FOUND
- commit a4f33cb — FOUND (RED gate)
- commit 9aaf03e — FOUND (GREEN implementation)
