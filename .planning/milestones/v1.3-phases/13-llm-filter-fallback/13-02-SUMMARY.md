---
phase: 13-llm-filter-fallback
plan: 02
subsystem: services/pipeline
tags: [nlu, async-migration, callsite-rewrite, filter-extractor, NLU-02]
requires:
  - services/nlu/filter_extractor.py::get_filter_extractor
  - services/nlu/filter_extractor.py::ExtractionResult
provides:
  - services/pipeline.py::QueryPipeline.run (async filter extraction)
  - services/pipeline.py::QueryPipeline.stream (async filter extraction)
  - services/pipeline.py::AgentQueryPipeline.run (async filter extraction)
  - services/pipeline.py::SwarmQueryPipeline.run (async filter extraction)
affects:
  - controllers/api.py (no change — pipelines are async-context already)
tech_stack:
  added: []
  patterns:
    - "Sync→async callsite migration via `await get_filter_extractor().extract(req.query)`"
    - "Singleton-factory accessor mirrors `get_query_pipeline()` / `get_agent_pipeline()` / `get_swarm_pipeline()` precedent"
key_files:
  created: []
  modified:
    - services/pipeline.py
decisions:
  - "D-07 implemented byte-exactly: 4 callsites migrated to `await get_filter_extractor().extract(req.query)` with no `asyncio.run` wrappers"
  - "D-04 truthiness compat preserved: `extraction.filters` and `extraction.semantic_query` access patterns unchanged at all 4 sites"
  - "AC#4 fallback_source NOT logged at callsites per RESEARCH Open Question #1 (out of scope; field exposure on returned dataclass satisfies AC)"
  - "No try/except wrapper around new callsite — D-14 guarantees `FilterExtractor.extract` never raises"
  - "Per-callsite cache_key NOT extended with `extraction.fallback_source` (T-13-02-03 mitigation: cache key remains a function of query+top_k+filters+tenant)"
metrics:
  duration_minutes: 5
  duration_seconds: 325
  tasks_completed: 1
  files_modified: 1
  lines_changed: 10  # 5 deletions + 5 insertions
  commits:
    - hash: ade413f
      task: 1
      message: "feat(13-02): migrate filter extractor callsites to async FilterExtractor"
  completed_date: 2026-05-09T03:28:00Z
---

# Phase 13 Plan 02: Pipeline Callsite Migration to Async FilterExtractor Summary

Migrated 4 sync `extract_filters(req.query)` callsites in `services/pipeline.py` to `await get_filter_extractor().extract(req.query)` and updated the import. Wave 2 of Phase 13 (NLU-02) wires the Wave-1 `FilterExtractor` into the production pipeline with zero behavior change for regex-extractable queries (regex-first composition preserves v1.1 contracts).

## What Was Built

`services/pipeline.py` modified in exactly 5 lines: 1 import line + 4 callsite lines. No surrounding code touched.

### Post-edit line numbers of the 5 modified lines

| # | Line | Before | After |
|---|------|--------|-------|
| 1 | 44 | `from services.nlu.filter_extractor import extract_filters` | `from services.nlu.filter_extractor import get_filter_extractor` |
| 2 | 317 | `extraction = extract_filters(req.query)` | `extraction = await get_filter_extractor().extract(req.query)` |
| 3 | 478 | `extraction = extract_filters(req.query)` | `extraction = await get_filter_extractor().extract(req.query)` |
| 4 | 674 | `extraction = extract_filters(req.query)` | `extraction = await get_filter_extractor().extract(req.query)` |
| 5 | 1166 | `extraction = extract_filters(req.query)` | `extraction = await get_filter_extractor().extract(req.query)` |

Line numbers are unchanged from pre-edit (identical replacements; no lines added/removed).

### Enclosing async function signatures (all 4 confirmed)

```python
# services/pipeline.py:299     async def run(self, req: GenerationRequest) -> GenerationResponse:        # QueryPipeline
# services/pipeline.py:457     async def stream(self, req: GenerationRequest, *, tenant_id: str = "", user_id: str = "") -> AsyncGenerator[str, None]:  # QueryPipeline
# services/pipeline.py:665     async def run(self, req: GenerationRequest) -> GenerationResponse:        # AgentQueryPipeline
# services/pipeline.py:1142    async def run(self, req: GenerationRequest) -> GenerationResponse:        # SwarmQueryPipeline
```

AST verification confirms all 4 callsite lines (317, 478, 674, 1166) are descendants of `AsyncFunctionDef` nodes — `await` is the correct primitive at every site.

### Adjacent comment blocks preserved verbatim

| Site | Lines | Status |
|------|-------|--------|
| Callsite #1 | 313–316 (QUERY-01 regex-first comment) | unchanged |
| Callsite #2 | 475–477 (QUERY-01 mirror comment) | unchanged |
| Callsite #3 | 671–673 (v1.1 QUERY-01 carry-forward comment) | unchanged |
| Callsite #4 | (no preceding comment block) | n/a |

## Verification

| Check | Result |
|-------|--------|
| `from services.nlu.filter_extractor import get_filter_extractor` present | 1 occurrence (correct) |
| `from services.nlu.filter_extractor import extract_filters` removed | 0 occurrences (correct) |
| `await get_filter_extractor().extract(req.query)` count | 4 occurrences (correct) |
| `extract_filters(req.query)` in code (excluding comments) | 0 occurrences (correct) |
| AST: every callsite enclosed by `AsyncFunctionDef` | all 4 verified |
| `asyncio.run` introduced in diff | 0 (correct — `await` is sufficient) |
| `try/except` introduced around new callsite | 0 (correct — D-14 graceful degradation) |
| `ruff check services/pipeline.py` | All checks passed |
| `mypy --strict services/pipeline.py` | 11 errors (identical to pre-edit baseline; **0 new errors**) |
| `pytest tests/unit/test_swarm_pipeline.py tests/unit/test_filter_extractor.py tests/unit/test_agent_pipeline_refactor.py -x -q` | 26 passed |
| Full unit suite: `pytest tests/unit/ -x -q --ignore=tests/unit/test_pgvector_store.py` | 349 passed, 1 skipped, 0 failed |
| Module imports + parses: `from services.pipeline import QueryPipeline, AgentQueryPipeline, SwarmQueryPipeline` | OK |

### mypy baseline confirmation

Pre-edit baseline (via `git stash` + run): 11 errors in `services/pipeline.py`.
Post-edit: 11 errors.
**Zero new errors introduced** by the migration. The 11 errors are pre-existing (lines 454, 716, 818, 894, 900, 906, 1180, 1223, 1260) and documented in Phase 12 SUMMARY as out-of-scope per SCOPE BOUNDARY rule.

### Acceptance criteria — all 11 pass

| # | Check | Expected | Actual |
|---|-------|----------|--------|
| 1 | `grep -c '^from services.nlu.filter_extractor import get_filter_extractor$'` | =1 | 1 |
| 2 | `grep -c '^from services.nlu.filter_extractor import extract_filters$'` | =0 | 0 |
| 3 | `grep -c 'await get_filter_extractor().extract(req.query)'` | =4 | 4 |
| 4 | Sync callsite removed (excluding comment lines) | =0 | 0 |
| 5 | Per-line-range presence (310-325, 470-490, 665-685, 1155-1175) | each ≥1 | each =1 |
| 6 | All 4 callsites inside `async def` (AST check) | pass | pass |
| 7 | No `asyncio.run` introduced | =0 | 0 |
| 8 | `mypy --strict services/pipeline.py` no new errors vs baseline | yes | 11 ↔ 11 |
| 9 | `ruff check services/pipeline.py` clean | exit 0 | exit 0 |
| 10 | `pytest tests/unit/test_swarm_pipeline.py tests/unit/test_filter_extractor.py -x -q` | pass | 19 passed |
| 11 | Full default unit suite green | pass | 349 passed, 1 skipped |

## Deviations from Plan

None. Task implementation matches plan spec exactly:
- Edit 1 (import line) — replaced verbatim per Edit 1 spec.
- Edit 2 (callsite #1 with `effective_query` line) — replaced exactly per Edit 2; preserved comment block at 313–316.
- Edit 3 (callsite #2 with `effective_query` line) — replaced exactly per Edit 3; preserved comment block at 475–477.
- Edit 4 (callsite #3, single-line) — replaced exactly per Edit 4; preserved comment block at 671–673.
- Edit 5 (callsite #4, single-line) — replaced exactly per Edit 5.

No `asyncio.run`, no `try/except`, no `logger.info(fallback_source=...)`, no cache-key extension, no `extract_filters` re-import, no caching of `get_filter_extractor()` to a local variable, no `semantic_query` rewrite — every "Do NOT" item in the plan was honored.

### Authentication Gates

None.

## Threat-Model Alignment

The plan listed 4 STRIDE threats (T-13-02-01 .. T-13-02-04). All 2 with `mitigate` disposition are honored by the as-built code:

| Threat ID | Disposition | Mitigation in code |
|-----------|-------------|---------------------|
| T-13-02-02 (subtle `asyncio.run` regression on a future move) | mitigate | AST-validated acceptance test confirms every `await get_filter_extractor().extract(req.query)` line is enclosed by `AsyncFunctionDef`; diff grep gate against `asyncio.run` introduction returned 0 |
| T-13-02-03 (cache-key side channel via `fallback_source`) | mitigate | Plan explicitly forbade extending `cache_key = {...}` at line 343 with `extraction.fallback_source`; verified diff touched only the 5 specified lines (cache_key construction unchanged) |

`accept`-disposition threats:
- **T-13-02-01** (LLM-path tail latency): regex-first composition (D-11) keeps the zero-cost path for regex-extractable queries; only first-occurrence regex misses hit the LLM (bounded by Redis cache TTL=3600s). No SLA regression for the hot path.
- **T-13-02-04** (audit log opacity): AC#4 satisfied by field exposure on `ExtractionResult` (delivered by Wave 1); per-callsite logging is OPTIONAL future work.

## Key Decisions Made During Execution

1. **AC#4 implementation choice** — Honored plan instruction to NOT add per-callsite `logger.info(filter_source=extraction.fallback_source)`. The dataclass field exposure satisfies the AC; logging is a future enhancement (Open Question #1 in RESEARCH).
2. **mypy baseline comparison method** — Used `git stash` + run pre-edit, then `git stash pop` to confirm error-count parity (11 ↔ 11). Cleaner than ad-hoc baseline file.
3. **Test environment** — Used `.venv/bin/python` with `APP_MODEL_DIR=/tmp/models` (OPS-01 env-var pattern); same pattern as Wave 1 verification.
4. **No new tests added in Wave 2** — Wave 3 (Plan 13-03) owns test coverage extension; Wave 2 is a pure migration. Existing pipeline tests (`test_swarm_pipeline.py`, `test_agent_pipeline_refactor.py`, `test_filter_extractor.py`) exercise the new path via real `get_filter_extractor()` singleton (which uses real `extract_filters` regex on hit, never reaching the LLM in unit tests).

## Self-Check: PASSED

- File modified: `services/pipeline.py` — verified post-Edit (5 line changes, no surrounding modifications)
- Commit `ade413f` (Task 1) found in `git log` — verified
- `services/pipeline.py` imports `get_filter_extractor`, no longer imports `extract_filters` — verified via `grep`
- All 4 callsites use `await get_filter_extractor().extract(req.query)` — verified via `grep -c` (=4)
- All 4 callsites enclosed by `AsyncFunctionDef` — verified via Python AST walk
- No `asyncio.run` in diff — verified via `git diff | grep`
- mypy --strict zero new errors — verified via `git stash` baseline comparison
- ruff clean on modified file — verified
- Pipeline unit tests pass: 26 passed (test_swarm_pipeline + test_agent_pipeline_refactor + test_filter_extractor)
- Full unit suite green: 349 passed, 1 skipped

## Wave 3 Readiness

Plan 13-03 (test coverage extension) can now proceed against a fully-wired pipeline. The async `FilterExtractor` is reachable from all 4 production query paths. Test plan can monkeypatch `services.nlu.filter_extractor.cache_get` / `cache_set` / `_filter_extractor._llm.chat` to exercise the LLM-fallback path end-to-end through `await get_filter_extractor().extract()`.

No carry-forward blockers. No deferred items.
