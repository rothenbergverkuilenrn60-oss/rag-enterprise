---
phase: 24-pgvector-recalltool-semantic-recall-rewrite
verified: 2026-05-16T00:00:00Z
status: human_needed
score: 4/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "SC-2 planner-pick rate — real LLM path"
    expected: "recall_memory picked >=4/5 times for preference query; 0/5 for unrelated query"
    why_human: "Marked @pytest.mark.real_llm; excluded from CI by addopts; requires real LLM API key + quota"
  - test: "SC-3 HNSW latency p95 < 50ms @ 10k rows"
    expected: "test_recall_latency.py passes GREEN against live pgvector instance"
    why_human: "Marked @pytest.mark.pgvector; requires live PostgreSQL + pgvector >= 0.8.0; skips gracefully on CI"
  - test: "SC-1 cosine quality — React > 0.7, database <= 0.5"
    expected: "test_recall_offline_eval.py passes against real embedding model"
    why_human: "Marked @pytest.mark.pgvector + requires real embedding adapter (not mock); shape verified, quality unverifiable without live PG + embedder"
  - test: "32 pre-existing Redis-dependent test failures"
    expected: "All 32 pass against a host with Redis on localhost:6379 (unrelated to Phase 24)"
    why_human: "No Redis available in CI; these are pre-existing failures; need host-with-Redis confirmation"
---

# Phase 24: pgvector RecallTool + Semantic Recall Rewrite — Verification Report

**Phase Goal:** Wire the semantic read path. `LongTermMemory.get_relevant_facts()` rewrites from `ORDER BY importance DESC` to query-embedding + pgvector cosine similarity. `RecallTool` subclasses `BaseTool`; `"recall_memory"` added to `AGENT_TOOL_ALLOWLIST` (3→4). Backfill job ships to embed pre-existing rows idempotently. Semantic-shift audited at all 4 `load_context` call sites.

**Verified:** 2026-05-16
**Status:** PASS-WITH-WARNINGS (human verification required for SC-1/SC-2/SC-3 live integration gates)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `get_relevant_facts` uses cosine similarity + HNSW, not `ORDER BY importance DESC` | VERIFIED | `services/memory/memory_service.py:320-322` sets `iterative_scan=strict_order`, `ef_search`, then `ORDER BY embedding <=>` |
| 2 | `RecallTool` exists as `BaseTool` subclass, registered as `"recall_memory"` | VERIFIED | `services/agent/tools/recall.py` (5.9K), `__init__.py:30` conditional registration |
| 3 | `AGENT_TOOL_ALLOWLIST` length == 4 with `"recall_memory"` | VERIFIED | `services/pipeline.py:747-752` — 4-entry literal confirmed |
| 4 | Backfill idempotent (`WHERE embedding IS NULL`), chunked 100/txn, batch UPDATE via unnest | VERIFIED | `scripts/backfill_fact_embeddings.py`: unnest pattern at line 161, `WHERE embedding IS NULL` at line 49 |
| 5 | 4 `load_context` call sites audited; `long_term_facts=[]` always (Decision-1/T1) | VERIFIED | `memory_service.py:493`; integration test `test_pipeline_load_context_audit.py` asserts `== []` at lines 184, 235 |

**Score:** 5/5 truths verified (code-level). 3 truths require human/live-PG integration gate.

---

## ROADMAP Success Criteria

| SC | Description | Code Evidence | Status |
|----|-------------|---------------|--------|
| SC-1 | React query cos > 0.7; database query max_cos <= 0.5 | `tests/integration/test_recall_offline_eval.py` — thresholds at lines 122, 154; test shape VERIFIED | NEEDS HUMAN (live PG + embedder) |
| SC-2 | Planner picks `recall_memory` for preference query; skips for unrelated; allowlist length == 4 | `test_recall_tool_planner_pick.py` with `@pytest.mark.real_llm`; allowlist length 4 VERIFIED in code | NEEDS HUMAN (`real_llm` marker gated) |
| SC-3 | HNSW prefilter p95 < 50ms @ 10k rows (SQL-only, embed_one OUTSIDE loop) | `tests/integration/test_recall_latency.py:88-90` — embed_one called once BEFORE `for _ in range(50)` loop; assert at line 128 | NEEDS HUMAN (live PG) |
| SC-4 | Backfill idempotent on 2nd run; chunked 100/txn; resumable | `test_backfill_fact_embeddings.py::test_idempotent_second_run` PASSES (unit mock); `unnest` batch UPDATE confirmed | VERIFIED (unit) |
| SC-5 | 4-site `load_context` audit; `long_term_facts==[]`; v1.0-v1.5 baseline preserved | 4-site removal regression in `test_pipeline_load_context_audit.py`; Decision-9 explicitly repurposed token-delta JSON as methodologically moot | VERIFIED with WARNING (see note) |

**SC-5 WARNING:** ROADMAP wording says "prompt-budget impact (mean / p95 token delta vs popularity-ranked baseline) is measured and recorded in the phase audit." Decision-9 in `24-ENG-REVIEW.md` explicitly replaced this with the 4-site removal regression (rationale: token-delta was "methodologically moot — both paths use LIMIT 5 + same column → near-zero delta by construction"). The ROADMAP SC wording is superseded by the eng-review amendment. This is an accepted deviation, not a failure. No token-delta artifact exists or is required.

---

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| MEM-06 — `get_relevant_facts` cosine rewrite | VERIFIED | `memory_service.py:270-346`: embed query, `SET LOCAL hnsw.*`, `ORDER BY embedding <=>`, tie-break on importance then created_at |
| MEM-07 — Backfill idempotent + docs | VERIFIED | `scripts/backfill_fact_embeddings.py` + `docs/memory-eviction.md` (2.2K, includes cost table) |
| MEM-08 — `RecallTool` subclasses `BaseTool`, mirrors `web_search.py` | VERIFIED | `services/agent/tools/recall.py`: ClassVars, `run()` calls `mem.get_relevant_facts`, `ToolResult` returned; 100% unit coverage |
| MEM-09 — `"recall_memory"` in allowlist; conditional registration; planner-pick test | VERIFIED (code); NEEDS HUMAN (real_llm test) | `pipeline.py:751`, `__init__.py:30`, `test_settings_recall_kill_switch.py` (51 tests GREEN) |
| MEM-10 — 4-site audit; regression tests; no new failures in v1.0-v1.5 baseline | VERIFIED | `test_pipeline_load_context_audit.py` asserts `long_term_facts==[]`; v1.5 baseline test present in same file |

---

## Eng-Review Amendments (T1..T11)

| Task | Requirement | Code Evidence | Status |
|------|-------------|---------------|--------|
| T1 — Drop `long_term_facts` from `load_context()` | `memory_service.py:493` — `long_term_facts=[]` hardcoded; docstring at 455-478 | VERIFIED |
| T2 — `MemoryService.get_relevant_facts` passthrough | `grep -n 'def get_relevant_facts' memory_service.py` returns 2 hits (lines 270, 524) | VERIFIED |
| T3 — `RecallTool.run` calls `mem.get_relevant_facts`, not `mem._long.*` | `recall.py:103`; `grep '_long' recall.py` returns 0 live code hits (1 comment-only hit) | VERIFIED |
| T4 — `backfill` uses `FROM unnest($1::uuid[], $2::vector[])` | `backfill_fact_embeddings.py:161`; `grep 'unnest'` returns 4 hits | VERIFIED |
| T5 — No `# noqa: BLE001` in backfill | 1 `noqa` hit is in a docstring comment (`no # noqa directive`), not a suppression directive | VERIFIED |
| T6 — `sys.modules.pop('services.agent.tools.recall', None)` in kill-switch helper | `test_settings_recall_kill_switch.py:102` | VERIFIED |
| T7 — `@pytest.mark.real_llm` on SC-2 planner-pick test | `test_recall_tool_planner_pick.py:26`; marker registered in `pytest.ini` | VERIFIED (gate deferred to pre-tag run) |
| T8 — `test_pipeline_load_context_audit.py` asserts `long_term_facts==[]` | Lines 184, 235 VERIFIED | VERIFIED |
| T9 — `test_recall_latency.py` SQL-only; `embed_one` OUTSIDE `for` loop | Line 90 (`embed_one`) before line 96 (`for _ in range(50)`) | VERIFIED |
| T10 — ASCII diagrams in 3 docstrings | `memory_service.py:463-470`, `recall.py:82`, `backfill_fact_embeddings.py:67-69` — box-drawing characters confirmed | VERIFIED |
| T11 — `test_allowlist_length_constant_regardless_of_toggle` tests BOTH states | Lines 172-184 — tests `enabled=True` AND `enabled=False` states inline | VERIFIED |

---

## Coverage Gate

SUMMARY claimed: recall.py 100%, memory_service.py 93.8%, backfill 87.1%, TOTAL 93.2%

Actual re-run (with full Phase 24 + pre-existing memory test suite as SUMMARY used):
- `services/agent/tools/recall.py`: **100%** (38/38 stmts)
- `services/memory/memory_service.py`: **93.8%** (193 stmts, 12 miss)
- `scripts/backfill_fact_embeddings.py`: **87.1%** (62 stmts, 8 miss — argparse `__main__` block)
- **TOTAL: 93.2%** — confirmed, gate PASSED

Note: Running only the 5 Phase-24-specific test files against memory_service.py produces 47.7% because it misses pre-existing memory tests (test_memory_save_fact.py, test_memory_schema.py, test_memory_pool.py, test_memory_service.py, test_memory_service_extra.py). SUMMARY correctly included those pre-existing tests as part of the coverage baseline. Gate result is valid.

---

## Unit Test Results

```
51 passed in 1.29s
```
(test_settings_recall_kill_switch.py + test_memory_recall_semantic.py + test_memory_service_passthrough.py + test_recall_tool.py + test_backfill_fact_embeddings.py)

Full gate with pre-existing memory tests: **85 passed, 20 warnings** — matches SUMMARY claim.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `scripts/backfill_fact_embeddings.py:14` | "no # noqa directive" (in comment/docstring, not code) | INFO | Not a suppression; T5 compliant |

No `TBD`, `FIXME`, or `XXX` markers found in Phase 24 files. No bare `except Exception`. No stub return values in production paths.

---

## Human Verification Required

### 1. SC-1 Cosine Quality Gate

**Test:** `uv run pytest -m pgvector tests/integration/test_recall_offline_eval.py -x -q` against live PostgreSQL + pgvector with real embedding model configured.

**Expected:** `test_react_preference_recalled_above_threshold` asserts cosine > 0.7; `test_unrelated_query_not_recalled` asserts max_cos <= 0.5.

**Why human:** Requires live pgvector instance + real embedder (Ollama/OpenAI). CI has neither. Test shape and thresholds are code-verified.

### 2. SC-2 Planner Pick Rate

**Test:** `uv run pytest -m real_llm tests/integration/test_recall_tool_planner_pick.py -x -q` with real LLM API key.

**Expected:** Planner picks `recall_memory` >= 4/5 times for preference query; 0/5 for unrelated. AGENT_TOOL_ALLOWLIST length == 4 (already code-verified).

**Why human:** `@pytest.mark.real_llm` excluded from CI by `addopts = -m "not integration"`. Requires real LLM quota.

### 3. SC-3 HNSW Latency p95 < 50ms

**Test:** `uv run pytest -m pgvector tests/integration/test_recall_latency.py -x -q` against live pgvector with 10k seeded rows.

**Expected:** p95 of 50 SQL-only SELECT trials < 50ms. embed_one called once outside loop (code-verified).

**Why human:** Requires live pgvector. Will SKIP gracefully without it.

### 4. Redis-Dependent Pre-existing Test Suite

**Test:** `uv run pytest tests/unit/ -k "agent_pipeline_refactor or agent_sse or feedback_ab_forward or pipeline_coverage"` against host with Redis on localhost:6379.

**Expected:** 32 tests that currently fail due to `ConnectionError: Error 111 connecting to localhost:6379` pass at baseline (unrelated to Phase 24; no Phase 24 code touches Redis).

**Why human:** No Redis in current environment.

---

## Gaps Summary

No structural gaps found. All 11 eng-review amendments landed. All 5 must-have truths verified at code level. Coverage gate confirmed. The 3 SC items requiring human verification (SC-1, SC-2, SC-3) are correctly gated behind `pgvector`/`real_llm` markers and designed to skip gracefully on CI.

**SC-5 token-delta deviation is accepted:** Decision-9 in `24-ENG-REVIEW.md` explicitly replaced the ROADMAP's token-delta audit requirement with the 4-site removal regression, with documented rationale. This is a pre-approved plan amendment, not a gap.

---

## Phase Ready for `/gsd-ship`?

**Conditional YES.** All automated unit tests pass (85/85). All code-verifiable amendments landed. Coverage gate confirmed. Phase 24 is ready to ship subject to the following pre-tag steps:

1. Run SC-1 eval + SC-3 latency against live pgvector (or accept as deferred-to-staging)
2. Run SC-2 real_llm planner-pick test nightly or pre-tag
3. Confirm 32 Redis-dependent tests pass on a host with Redis (pre-existing issue, not Phase 24 regression)

---

_Verified: 2026-05-16_
_Verifier: Claude (gsd-verifier)_
