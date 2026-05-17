---
phase: 24-pgvector-recalltool-semantic-recall-rewrite
plan: "02"
subsystem: memory
tags: [pgvector, hnsw, strict_order, ef_search, cosine-similarity, get_relevant_facts, semantic-recall, load_context, passthrough, narrow-exceptions, tdd]
dependency_graph:
  requires: []
  provides:
    - services/memory/memory_service.py::LongTermMemory.get_relevant_facts (semantic recall)
    - services/memory/memory_service.py::MemoryService.get_relevant_facts (public passthrough)
    - services/memory/memory_service.py::MemoryService.load_context (long_term_facts dropped, always [])
  affects:
    - Plan 03 (RecallTool calls MemoryService.get_relevant_facts passthrough)
    - Plan 05 (4-site load_context removal regression test)
tech_stack:
  added: []
  patterns:
    - pgvector cosine recall via embedding <=> $3::vector
    - HNSW strict_order + ef_search inside conn.transaction()
    - dual-path embedder mock (consumer + source paths)
    - separate try/except for embedder vs SQL failure
key_files:
  created:
    - tests/unit/test_memory_recall_semantic.py
    - tests/unit/test_memory_service_passthrough.py
  modified:
    - services/memory/memory_service.py
    - tests/unit/test_memory_service_extra.py
decisions:
  - "D-A1: strict_order chosen over relaxed_order for ROADMAP SC-1 cosine-quality contract"
  - "Decision-1 (T1): load_context drops long_term_facts gather; RecallTool is sole read path"
  - "Decision-2 (T2): public MemoryService.get_relevant_facts passthrough; decouples RecallTool from _long private attr"
  - "Decision-4 (T10): ASCII pre/post-removal gather diagram in load_context docstring"
  - "Rule-1 deviation: fixed 3 pre-existing tests in test_memory_service_extra.py broken by semantic recall change"
metrics:
  duration: "8m"
  completed: "2026-05-16T11:09:00Z"
  tasks: 4
  files: 4
---

# Phase 24 Plan 02: Semantic Recall Rewrite + load_context Drop Summary

**One-liner:** pgvector cosine recall with HNSW strict_order + ef_search in `get_relevant_facts`; `load_context` drops long_term_facts gather (RecallTool becomes sole reader); public passthrough method added.

## Objective Recap

Rewrite `LongTermMemory.get_relevant_facts` from popularity-ranked (ORDER BY importance DESC, created_at DESC) to semantic cosine recall (embedding <=> $3::vector) inside explicit `conn.transaction()` with SET LOCAL HNSW tuning. Add public `MemoryService.get_relevant_facts` passthrough. Drop `long_term_facts` from `load_context` gather (Decision-1). Add ASCII diagram (Decision-4).

## Tasks Completed

| Task | Name | Commit | Files | Tests |
|------|------|--------|-------|-------|
| 1 | RED — 9+2 unit tests | d65648a | tests/unit/test_memory_recall_semantic.py | 13 collected (11 unique + 2 parametrize variants) |
| 2 | GREEN — get_relevant_facts semantic rewrite | 65f8d7b | services/memory/memory_service.py | 11 GREEN |
| 3 | RED+GREEN — passthrough method | 8726bd0 + 6c4da39 | tests/unit/test_memory_service_passthrough.py, services/memory/memory_service.py | 3 GREEN |
| 4 | RED+GREEN — load_context drop + ASCII diagram | 5542d78 | services/memory/memory_service.py, tests/unit/test_memory_service_extra.py | 13 GREEN (all recall) |

## Acceptance Criteria Met

| Criterion | Verification |
|-----------|-------------|
| Semantic recall replaces popularity ranking | `grep -n "embedding <=> \$3::vector" services/memory/memory_service.py` → 1 match in SQL |
| Transaction wrap landed | `grep -n "async with conn.transaction()" services/memory/memory_service.py` → 1 match |
| SET LOCAL iterative_scan = 'strict_order' | `grep -n "SET LOCAL hnsw.iterative_scan = 'strict_order'" services/memory/memory_service.py` → 1 match |
| SET LOCAL ef_search | `grep -n "SET LOCAL hnsw.ef_search" services/memory/memory_service.py` → 1 match |
| operation=get_facts_embed | `grep -n 'operation="get_facts_embed"' services/memory/memory_service.py` → 1 match |
| operation=get_facts_semantic | `grep -n 'operation="get_facts_semantic"' services/memory/memory_service.py` → 1 match |
| 2 get_relevant_facts definitions | `grep -n "async def get_relevant_facts" services/memory/memory_service.py` → 2 (LongTermMemory + MemoryService) |
| load_context drops long_term_facts | `grep -c 'self._long.get_relevant_facts' services/memory/memory_service.py` → 1 (passthrough only) |
| long_term_facts=[] explicit | `grep -n 'long_term_facts=\[\]' services/memory/memory_service.py` → 1+ matches |
| ASCII diagram in docstring | `src contains 'Pre-removal shape' and 'Post-removal shape'` → True |
| query param retained | `'query' in inspect.signature(MemoryService.load_context).parameters` → True |
| No relaxed_order | grep returns 0 non-comment matches |
| No set_config RLS GUC | grep returns 0 matches |
| Signature unchanged | `list(sig.parameters) == ['self','user_id','tenant_id','query','limit']`; `limit.default == 5` |

## Coverage

| Test file | Tests | Status |
|-----------|-------|--------|
| test_memory_recall_semantic.py | 13 (11 unique + 2 param) | ALL GREEN |
| test_memory_service_passthrough.py | 3 | ALL GREEN |
| test_memory_save_fact.py | 7 (Phase-23 regression) | ALL GREEN |
| test_memory_schema.py | 3 (Phase-23 regression) | ALL GREEN |
| test_memory_pool.py | 1 (Phase-23 regression) | ALL GREEN |
| test_memory_service.py | 3 | ALL GREEN |
| test_memory_service_extra.py | 20 (2 updated + 1 updated) | ALL GREEN |

**Total: 50 tests GREEN**

## MEM-06 + T1 + T2 + T10 Traceability

| Requirement | Landing | Test Gate |
|-------------|---------|-----------|
| MEM-06: semantic recall (cosine similarity) | `get_relevant_facts` body: `embedding <=> $3::vector, importance DESC, created_at DESC` | test_returns_bare_strings_sorted_by_cosine, test_tie_break_sql_includes_importance_and_created_at |
| MEM-06: HNSW strict_order + ef_search | SET LOCAL in conn.transaction() | test_set_local_executed_before_fetch, test_get_relevant_facts_uses_transaction |
| MEM-06: narrow exceptions | (httpx.HTTPError, RuntimeError, OSError) + asyncpg.PostgresError | test_embedder_failure_returns_empty[x3], test_pg_failure_returns_empty |
| MEM-06: signature preserved | list(params) == ['self','user_id','tenant_id','query','limit'], default 5 | test_signature_unchanged |
| MEM-06: bare string return | no '- ' or '* ' prefix | test_returns_bare_strings_no_prefix |
| T1 (Decision-1): load_context drops long_term_facts | 3-gather → 2-gather; long_term_facts=[] | test_load_context_drops_long_term_facts, test_load_context_does_not_call_get_relevant_facts |
| T2 (Decision-2): public passthrough method | MemoryService.get_relevant_facts delegates to self._long | test_memory_service_get_relevant_facts_delegates_to_long, test_memory_service_get_relevant_facts_signature |
| T10 (Decision-4): ASCII diagram | Pre-removal / Post-removal shape in docstring | inspect.getsource assertion in acceptance criteria |

## Next Plan Reference

- **Plan 03** (RecallTool body): consumes `MemoryService.get_relevant_facts` public passthrough (T2); builds `RecallTool.run` with 3-branch fan-out (auth / error / happy) ASCII diagram.
- **Plan 05** (MEM-10 audit): 4-site load_context removal regression gate asserting `mem_ctx.long_term_facts == []` post-Decision-1.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-existing tests in test_memory_service_extra.py broke after semantic rewrite**
- **Found during:** Task 4 full-suite regression run
- **Issue:** 3 tests relied on old `get_relevant_facts` (no embedder call, no conn.transaction) and old `load_context` (long_term_facts from gather). After semantic rewrite + Decision-1, all 3 failed.
  - `test_long_term_get_relevant_facts_returns_strings` — no embedder mock, no txn stub
  - `test_long_term_get_relevant_facts_pg_error_returns_empty` — no embedder mock, no txn stub
  - `test_memory_service_load_context_aggregates` — asserted `long_term_facts == ["fact-1"]` (old behavior)
- **Fix:** Added dual-path embedder mock + `_TxnCtx` stub to the two `get_relevant_facts` tests. Updated `load_context` test to assert `long_term_facts == []` (Decision-1 behavior). Added explanatory comment referencing Phase 24 / T1.
- **Files modified:** `tests/unit/test_memory_service_extra.py`
- **Commit:** 5542d78 (bundled with Task 4)

**2. [Rule 1 - Bug] Test annotation check failed with PEP-563 deferred evaluation**
- **Found during:** Task 3 GREEN run
- **Issue:** `test_memory_service_get_relevant_facts_signature` asserted `ann == list[str]` but `from __future__ import annotations` makes `inspect.signature` return annotations as strings (`'list[str]'`), not resolved types.
- **Fix:** Updated assertion to `ann in ("list[str]", list[str])`.
- **Files modified:** `tests/unit/test_memory_service_passthrough.py`
- **Commit:** 6c4da39

### mypy Note

Pre-existing 24 mypy --strict errors in the file (untyped `_get_pool`, `_get_client`, `get_embedder` calls). Our change adds 1 matching error (same pattern as pre-existing `save_fact` line 304 `get_embedder` call). No new logic errors introduced; structural pattern matches Phase 23 baseline.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. The SQL surface is fully parameterized ($1..$4 for user_id, tenant_id, q_vec, limit). The f-string interpolation for `hnsw.ef_search` uses `int(settings.pgvector_ef_search_filtered)` — typed int from Pydantic BaseSettings, not user input (matches T-24-02-T1 mitigation in threat register). No new threat surface beyond what the plan's threat model covers.

## Self-Check: PASSED

- [x] `tests/unit/test_memory_recall_semantic.py` exists — FOUND
- [x] `tests/unit/test_memory_service_passthrough.py` exists — FOUND
- [x] Commit d65648a exists — FOUND
- [x] Commit 65f8d7b exists — FOUND
- [x] Commit 8726bd0 exists — FOUND
- [x] Commit 6c4da39 exists — FOUND
- [x] Commit 5542d78 exists — FOUND
- [x] 50 memory unit tests GREEN
- [x] ruff check passes on services/memory/memory_service.py
