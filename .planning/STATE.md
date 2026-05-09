---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Fork Swarm, NLU & Quality
status: Phase 14 context gathered — ready for `/gsd-plan-phase 14`
stopped_at: Phase 14 CONTEXT.md written (13 decisions D-01..D-13 locked across 6 categories)
last_updated: "2026-05-09T13:00:00.000Z"
last_activity: 2026-05-09 — Phase 14 discuss-phase complete (UI-02 design decisions locked)
progress:
  total_phases: 4
  completed_phases: 3
  total_plans: 6
  completed_plans: 6
  percent: 75
---

# STATE — EnterpriseRAG v1.3 Fork Swarm, NLU & Quality

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-08)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** Phase 13 — LLM Filter Fallback (NLU-02)

## Current Position

Phase: 14
Plan: Not started
Status: Ready to plan
Last activity: 2026-05-09

| Field | Value |
|-------|-------|
| Milestone | v1.3 Fork Swarm, NLU & Quality |
| Current phase | 13 — LLM Filter Fallback (complete; pending verify) |
| Current plan | 13-01 ✅ + 13-02 ✅ + 13-03 ✅ — all three plans complete |
| Phase status | All 3 plans complete; ready for `/gsd-verify-work 13` |
| Overall progress | 2/4 phases + 3/3 Phase-13 plans (Phase 12 closed; Phase 13 ready for verification) |

### Phase 13 Plan Summary

| Plan | Wave | Tasks | Files Modified | Depends On |
|------|------|-------|----------------|------------|
| 13-01 ✅ | 1 | 2 | `services/nlu/filter_extractor.py` (add FilterExtractor class) | — |
| 13-02 ✅ | 2 | 1 | `services/pipeline.py` (4 callsites → await) | 13-01 |
| 13-03 ✅ | 2-parallel | 2 | `tests/unit/test_filter_extractor.py` (extend +6 tests), `tests/integration/test_filter_extractor_llm.py` (new) | 13-01 |

All three plans complete; NLU-02 ready for `/gsd-verify-work 13`.

**Plan-checker findings:** PASS, 5 cosmetic flags (no blockers).

- 13-03 cache-hit test uses in-memory dict (not real Redis) — TTL covered by utils/cache.py own tests
- 13-02 explicitly skips per-callsite logger.info(fallback_source) — AC#4 satisfied via dataclass field
- Minor shell-escape oddity in 13-01 frozen-test acceptance — harmless

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 12 | Fork-Agent Swarm | AGENT-03 | Executed (verification pending) |
| 13 | LLM Filter Fallback | NLU-02 | Executed (verification pending) |
| 14 | Frontend Split and DOM Modernization | UI-02 | Context gathered |
| 15 | Coverage Combine and 70% Floor | TEST-04, TEST-06 | Not started |

## Accumulated Context

### Carry-Forward from v1.2 (key decisions still in force)

| Decision | Source | Why it matters in v1.3 |
|----------|--------|------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | All v1.3 work runs on this stack |
| Section heading text in embedded content; numeric IDs in metadata only | v1.1 Phase 8 D-02 | Any new chunker work must preserve this rule |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 | Pattern to reuse for any new filtered queries |
| Regex-first filter extractor in `services/nlu/filter_extractor.py` | v1.1 Phase 8 QUERY-01 | NLU-02 extends this module — regex path must remain the first branch |
| FastAPI StaticFiles mount at `/ui/`; `static/index.html → ui.html` symlink | v1.1 Phase 9 | UI-02 must preserve this; only add `ui.js` / `ui.css` alongside |
| `diff-cover ≥ 80%` gate on v1.1+ files | v1.1 Phase 10 TEST-03 | All v1.3 PRs MUST pass this gate |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | Sub-agents in Phase 12 reuse this interface — don't add `@abstractmethod` |
| `parallel_tool_calls=True` explicit in OpenAI; `disable_parallel_tool_use=False` explicit in Anthropic | v1.2 Phase 11 | Swarm coordinator inherits this pattern for sub-agent dispatch |
| `asyncio.gather` for concurrent tool execution | v1.2 Phase 11 | Phase 12 swarm uses `asyncio.gather` to run N sub-agents concurrently |

### Phase 12 Implementation Notes

- Build on `AgentQueryPipeline` or introduce `SwarmQueryPipeline` in `services/pipeline.py`
- Coordinator decomposition is itself an LLM call (prompt: "split this query into N independent sub-questions")
- Each sub-agent is a standalone coroutine calling `call_agentic_turn` with its own fresh `messages` list
- `MAX_SWARM_AGENTS = 5`, `MAX_SWARM_TURNS_PER_AGENT = 5` must be env-var-configurable (OPS-01 pattern)
- Synthesis call is a second LLM call: receives all N sub-agent final answers, returns one unified response
- Audit log fields: `swarm_n`, `per_agent_turns: list[int]`, `per_agent_tool_calls: list[int]`, `swarm_latency_ms`, `synthesis_latency_ms`
- N = 1 must fall back to single-agent path without spawning swarm machinery

### Phase 13 Implementation Notes

- Extend `FilterExtractor` in `services/nlu/filter_extractor.py` — keep existing regex logic untouched as first branch
- Cache: prefer `functools.lru_cache` for simplicity if Redis TTL not needed at this layer; revisit if multi-process needed
- `fallback_source: Literal["regex", "llm"] | None` — add to `QueryFilter` model or as wrapper field on extractor return
- LLM prompt must specify strict JSON schema; parse with `json.loads` inside try/except; return `None` on any parse failure
- Unit test must mock the LLM client and assert call count (not called on regex hit; called once on cache miss)

### Phase 14 Implementation Notes

- Extract CSS first (simpler, no logic), then JS (event wiring, DOM refs)
- `addEventListener` wiring: document-level `DOMContentLoaded` or module-level initialization in `ui.js`
- No bundler unless ES module splits are clearly beneficial — decide at implementation time per acceptance criterion 5
- Visual regression check: manual smoke test of upload + query + result flows; no automated visual diff required

### Phase 15 Implementation Notes

- TEST-04 (CI plumbing) must be done first within this phase; TEST-06 tests come second
- `coverage run --data-file=.coverage.unit` for unit suite; `coverage run --data-file=.coverage.integration` for integration suite
- `coverage combine .coverage.unit .coverage.integration` → `.coverage` → `coverage report --fail-under=70`
- Identify undercovered modules by running `coverage report` at v1.2 close; prioritize service modules over utils
- New tests must themselves pass the `diff-cover ≥ 80%` gate on the test file lines they introduce

### Blockers

None.

### Todos (carry-forward, not v1.3-scoped but tracked)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10 live PR through CI confirms `coverage-diff` step + HTML artifact (natural confirmation on first PR)
- [ ] Push tags `v1.1` and `v1.2` to origin (currently local-only)
- [ ] PR #1 + PR #2 review + merge

## Session Continuity

**Last updated:** 2026-05-09 — Plan 13-03 executed (Wave 3 complete; FilterExtractor unit + integration test coverage delivered)
**Stopped at:** Completed 13-03-PLAN.md (2/2 tasks; 363 unit tests pass; 1 integration test deselected by default)
**Next action:** Run `/gsd-verify-work 13` to verify NLU-02 acceptance criteria coverage.

### Plan 13-03 Execution Notes (Wave 3)

- **Duration:** ~4 min, 2/2 tasks, 2 task commits + SUMMARY commit
- **Edits:** 1 file modified (`tests/unit/test_filter_extractor.py` — +182 lines), 1 file created (`tests/integration/test_filter_extractor_llm.py` — 67 lines)
- **D-02 freeze honored:** 7 existing regex tests preserved verbatim under renamed `class TestExtractFiltersRegex` (no body changes; only class name changed)
- **D-15 6-contract enumeration implemented:** every contract maps to a distinct test under `class TestFilterExtractor` with `@pytest.mark.unit @pytest.mark.asyncio` markers
- **Cache patching at consumer path:** `monkeypatch.setattr("services.nlu.filter_extractor.cache_get", …)` — not `utils.cache.cache_get` import source (per RESEARCH §Common Pitfalls #6)
- **Cache-hit test uses stateful in-memory dict** (not real Redis) per plan-checker flag — TTL semantics belong to `utils/cache.py` own tests
- **Integration test mirrors `test_swarm_pipeline_e2e.py` exactly:** `LLM_PROVIDER=openai` monkeypatch + dual singleton reset (`_llm_instance`, `_filter_extractor`) + `pytestmark = [pytest.mark.integration]` gating
- **Haiku type drift tolerated:** integration test asserts `section in {"3", 3}` (A2 string-vs-int tolerance)
- **No deviations:** plan executed exactly as written; no Rule 1-3 auto-fixes
- **Verification:** 13/13 unit tests pass; integration test collects 1 / deselected 1 by default; full unit suite 363 passed (Wave 2 baseline 349 + 14 net new tests including 6 D-15 contracts); ruff clean on both files; pre-existing mypy baseline preserved

### Plan 13-02 Execution Notes (Wave 2)

- **Duration:** ~5 min, 1/1 task, 1 task commit + SUMMARY commit
- **Edits:** Single file (`services/pipeline.py`) — 5 line changes total: 1 import line (44) + 4 callsite lines (317, 478, 674, 1166)
- **D-07 implementation:** All 4 callsites migrated to `await get_filter_extractor().extract(req.query)` — AST-verified each enclosing function is `async def`; no `asyncio.run` wrappers, no `try/except`, no `logger.info` per-callsite (AC#4 satisfied via Wave 1 dataclass field)
- **D-04 truthiness compat preserved:** `extraction.filters` and `extraction.semantic_query` access patterns unchanged — `ExtractionResult` exposes both fields with same names/types as `FilterExtractionResult`
- **No deviations:** Every "Do NOT" item in plan honored (no asyncio.run, no try/except, no fallback_source logging at callsites, no cache_key extension, no extract_filters re-import, no caching of get_filter_extractor() result, no semantic_query rewrite)
- **Verification:** All 11 acceptance criteria pass; 26 pipeline tests pass (test_swarm_pipeline.py, test_agent_pipeline_refactor.py, test_filter_extractor.py); full unit suite 349 passed/0 failed; ruff clean; mypy --strict baseline preserved (11 errors ↔ 11 errors via git-stash comparison)
- **Wave 3 readiness:** Pipeline fully wired to async FilterExtractor; Plan 13-03 can monkeypatch the singleton to exercise LLM-fallback path end-to-end through any of the 4 production query paths

### Plan 13-01 Execution Notes (Wave 1)

- **Duration:** ~4 min, 2/2 tasks, 2 task commits + 1 SUMMARY commit
- **Edits:** Single file (`services/nlu/filter_extractor.py`) modified in two passes — Task 1 (imports + prompt + `ExtractionResult`), Task 2 (`FilterExtractor` class + singleton)
- **D-02 freeze verification:** `git show ae06fb1:services/nlu/filter_extractor.py` extracted via 3 awk-boundary blocks (regex patterns / `FilterExtractionResult` / `extract_filters` body) — all `Files are identical`
- **Plan deviation (Rule 1):** mypy `union-attr` false positive on `m.group(0)` (re.search returning Optional[Match]) suppressed with inline `# type: ignore[union-attr]` comment. The `AttributeError` is intentional control flow per D-13 parse-domain narrow tuple. Matches project convention at `services/generator/llm_client.py:615`. No other deviations.
- **Acceptance criteria:** All 22 grep checks pass; 7 existing regex tests pass; full unit suite 357 passed/0 failed; ruff clean; 0 new mypy errors in modified file (pre-existing baseline in cache.py / llm_client.py / settings.py is out of scope per SCOPE BOUNDARY rule)
- **Wave 2 / Wave 3 readiness:** Module shape stable. Public exports `ExtractionResult`, `FilterExtractor`, `get_filter_extractor` ready for pipeline callsite migration (13-02) and test coverage (13-03)

### Phase 12 Plan Summary

| Plan | Wave | Tasks | Files Modified | Depends On |
|------|------|-------|----------------|------------|
| 12-01 | 1 | 2 | `utils/models.py`, `config/settings.py` | — |
| 12-02 | 2 | 9 | `services/pipeline.py` (append `SwarmQueryPipeline`) ✅ | 12-01 |
| 12-03 | 3 | 3 | `controllers/api.py`, `tests/unit/test_swarm_pipeline.py`, `tests/integration/test_swarm_pipeline_e2e.py` ✅ | 12-01, 12-02 |

**Plan-checker findings:** PASS, 3 cosmetic flags (no blockers).

- Cosmetic typo in 12-03 Task 3 verify command (duplicate suffix; self-correcting)
- `_execute_tool_call` copy-by-design per D-01 (drift risk if agent edits — accepted)
- Coordinator silently degrades to N=1 if LLM returns single-element array (accepted per D-03)

### Plan 12-02 Execution Notes (Wave 2)

- **Duration:** ~12 min, 9/9 tasks, 9 task commits + 1 SUMMARY commit
- **One-line edit to existing code**: `services/audit/audit_service` import line extended to include `AuditAction`, `AuditEvent` (Task 8 needs `log()` direct path because `log_query()` cannot carry swarm fields)
- **AgentQueryPipeline body byte-identical** vs Plan 12-01 endpoint (3aa035e) — verified via awk-extracted-range diff
- **`_execute_tool_call` verbatim copy** verified by `inspect.getsource` + token-equivalent normalized-string equality test
- **Plan deviation (Rule 1)**: Plan example used `actor_id=user_id`; corrected to `user_id=user_id` (actual `AuditEvent` dataclass field name at audit_service.py:53). All 9 audit detail keys present: `swarm_n`, `per_agent_turns`, `per_agent_tool_calls`, `swarm_latency_ms`, `synthesis_latency_ms`, `latency_ms`, `sources_count`, `query_len`, `intent='swarm'`.
- **mypy --strict drift**: pipeline.py errors went from 7 → 11. The 4 "new" errors are exact pattern-mirrors of pre-existing baseline (`get_query_pipeline()` untyped factory at line 716, `save_turn(intent=None)` at line 818, factory functions without return annotations at 894/900/906). All required by plan instructions ("Match the exact spacing/style of `_agent_pipeline = None` / `def get_agent_pipeline()`"). SCOPE BOUNDARY applies.
- **Agent unit tests (`tests/unit/test_agent_pipeline_refactor.py`): 11 passed, 0 regressions.**
- **Future-work flag**: any change to `AgentQueryPipeline._execute_tool_call` MUST be mirrored into `SwarmQueryPipeline._execute_tool_call` in lockstep (or extracted to module level — out of Phase 12 scope).

### Plan 12-03 Execution Notes (Wave 3)

- **Duration:** ~8 min, 3/3 tasks, 3 task commits.
- **Routing edit (Task 1):** controllers/api.py — added `get_swarm_pipeline` to import block (line 25) + replaced ternary one-liner at former line 208 with explicit `if/elif/else` (8 lines, swarm > agent > default). Source-order acceptance test confirms `req.swarm_mode` precedes `req.agent_mode` (T-12-03-01).
- **Unit tests (Task 2):** 8/8 pass on first run. Mirrors fixture/helpers verbatim from `tests/unit/test_agent_pipeline_refactor.py` — diverging structure would create maintenance drift. Concurrency test uses `asyncio.Event + counter` pattern (analog lines 185–224).
- **Integration test (Task 3):** 1 test, gated by `pytestmark = [pytest.mark.integration]`. Provider override matches analog exactly: `monkeypatch.setenv("LLM_PROVIDER", "openai")` (NOT ANTHROPIC_API_KEY skipif — D-05/W-6 unconditional-run policy). Resets both `_llm_instance` and `_swarm_pipeline` singletons.
- **No regressions:** `tests/unit/test_agent_pipeline_refactor.py` 11 passed; full default suite (361 passed when excluding pre-existing pgvector + ragas failures).
- **Pre-existing flake noted (NOT introduced):** `tests/unit/test_ingest_status.py::test_async_ingest_returns_task_id` 200ms latency budget — reproduces with `git stash` (no Plan 12-03 changes), out of scope.
- **AGENT-03 closure:** every acceptance criterion 1–7 maps to a unit test; integration smoke gates real-LLM verification. Phase 12 ready for `/gsd-verify-work 12`.
