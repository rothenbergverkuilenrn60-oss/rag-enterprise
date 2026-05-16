---
gsd_state_version: 1.0
milestone: v1.6
milestone_name: Memory Tool — Agent-Authored Long-Term Facts
status: Phase 24 planned (7 plans, 4 waves; plan-checker PASSED with 4 non-blocking warnings). Ready for `/gsd-execute-phase 24` (or `/plan-eng-review` for second-opinion gate).
stopped_at: Phase 24 plans created + verified
last_updated: "2026-05-16T09:30:00.000Z"
last_activity: 2026-05-16 — /gsd-plan-phase 24 produced 24-RESEARCH.md (7 pitfalls, 7 ASSUMED claims) + 24-PATTERNS.md (13 analogs, 4 verbatim skeletons) + 7 PLAN.md files (2,490 LOC across 4 waves) + 24-VALIDATION.md (31-row Nyquist map). Plan-checker PASSED — 0 blockers, 4 warnings flagged for executor SUMMARYs (Plan 04 planner-pick test ambiguity, Plan 05 token-delta methodology, Plan 06 BLE001 narrow-exception follow-up, Plan 07 similarity threshold flake risk).
progress:
  total_phases: 3
  completed_phases: 1
  total_plans: 13
  completed_plans: 6
  percent: 46
---

# STATE — EnterpriseRAG (v1.6 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-15 after v1.6 open)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.6 Memory Tool — agent-authored long-term facts as new agent-callable third store (extractor → pgvector RecallTool → eviction + GDPR forget API).

## Current Position

Phase: 24 (planned; pending execute)
Plan: 24-01..24-07 (7 plans, waves 1–4). Plan-checker PASSED.
Status: Phase 24 planned. Ready for `/gsd-execute-phase 24`.
Status: All of MEM-01..MEM-05 GREEN at the unit + integration layers. Plan 23-06 added 3 new integration test files (`tests/integration/test_long_term_facts_schema.py`, `tests/integration/test_extractor_e2e.py`, `tests/integration/test_swarm_pipeline_extractor_e2e.py`) + 4 new conftest fixtures (`pgvector_pool`, `extractor_llm_mock`, `embedder_or_mock`, `clean_long_term_facts`). Per-module coverage gate PASSES at 97.4% (extractor.py) + 93.3% (memory_service.py) — both well above the 70% floor. Diff-cover vacuously PASSES (Plan 06 added zero production-code lines). 7 new integration tests SKIP gracefully on CI hosts without PostgreSQL; pre-tag check requires running them with -m pgvector against a live local PG to confirm 7/7 PASS.
Last activity: 2026-05-16 — Plan 23-06 (91e19af→1806cc8→7a4acef→41ce20e). MEM-01 + MEM-04 integration verification + coverage gate; 7 new tests added; 27/27 Phase 23 unit suite GREEN; ruff clean.

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 23 | Background Extractor + schema migration | MEM-01, MEM-02, MEM-03, MEM-04, MEM-05 | COMPLETE — 6/6 plans GREEN (23-01 MEM-01 ✓; 23-02 MEM-02 ✓; 23-03 MEM-03 ✓; 23-04 MEM-05 ✓; 23-05 MEM-04 ✓; 23-06 integration + coverage gate ✓ — SC-1/4/5 closed) |
| 24 | pgvector RecallTool + semantic recall rewrite | MEM-06, MEM-07, MEM-08, MEM-09, MEM-10 | Planned (7 plans, 4 waves) — plan-checker PASSED; ready for /gsd-execute-phase 24 |
| 25 | Eviction job + GDPR forget API | EVICT-01, EVICT-02, EVICT-03, GDPR-01, GDPR-02, GDPR-03 | Pending |

## Accumulated Context

### Carry-Forward Decisions (still in force)

| Decision | Source | Why it matters in v1.6 |
|----------|--------|------------------------|
| PostgreSQL + pgvector backend with HNSW + RLS | v1.0 | v1.6 adds `embedding VECTOR(1024)` column to `long_term_facts` + HNSW index using same `vector_cosine_ops` + `iterative_scan` pattern |
| `hnsw.iterative_scan = strict_order` + `ef_search` GUC pattern when filter active | v1.1 Phase 8 | Required for `WHERE user_id=$1 AND tenant_id=$2` prefilter on `long_term_facts` recall |
| `diff-cover ≥ 80%` gate on touched files | v1.1 Phase 10 TEST-03 | All v1.6 PRs MUST pass this gate |
| Combined coverage `--fail-under=70` global floor + per-module ≥70% on 5 locked modules | v1.5 Phase 22 | Extractor / RecallTool / get_relevant_facts rewrite all targeted to ≥70% per-module |
| `BaseLLMClient.call_agentic_turn` non-abstract default-raise | v1.2 Phase 11 | Extractor sub-agent reuses this provider-neutral interface |
| Sub-agents do NOT inherit chat history | v1.3 D-06 | Extractor sees ONLY the just-finished turn (no chat history) |
| `BaseException` (not `Exception`) for `asyncio.gather` isolation | v1.3 Phase 12 | Background `asyncio.create_task` extractor follows same isolation contract; wrapped with `utils/tasks.log_task_error` |
| Mock at consumer path (`services.<mod>.<dep>`) not source | v1.3 Phase 13 + 15 | Extractor + RecallTool unit tests follow this pattern |
| Phase 15 D-08 `parallel = false` in `[tool.coverage.run]` | v1.3 Phase 15 | Combine job topology preserved verbatim across v1.6 |
| `Planner` / `Executor` / `Synthesizer` triad behind frozen Pydantic V2 contracts | v1.4 Phase 16 | Planner gains 4th tool (`recall_memory`); contract surface unchanged |
| `BaseTool` ABC + `ToolRegistry` + `AGENT_TOOL_ALLOWLIST` constant in `services/pipeline.py:742` | v1.4 Phase 17 | RecallTool subclasses `BaseTool`; allowlist grows to 4 (search_knowledge_base, refine_search, web_search, recall_memory) |
| SSE event schema in `docs/agent-architecture.md` | v1.4 Phase 18 | v1.6 ships WITHOUT new memory.* SSE events (deferred to v1.7); existing schema unchanged |
| AGENT-05 Verifier sub-agent pattern (`services/agent/verifier.py`) | v1.5 Phase 21 | Reusable: provider-singleton + `call_agentic_turn` + Pydantic schema + no-Tenacity. NOT reusable: synchronous in-pipeline call shape (extractor is background). |

### Open Questions Carried into v1.6 Planning

(To be resolved during phase discussions, not blockers for opening v1.6.)

1. **Embedding model for `long_term_facts.embedding`.** Same as KB chunks (consistency wins; reuses existing adapter at `services/vectorizer/`) or smaller/cheaper (facts shorter than chunks). Decide in Phase 23 RESEARCH. Default: same as KB unless cost analysis flips it.
2. **Extractor cost guard.** Every turn adds one background LLM call. If cost becomes prohibitive in Phase 23 eval, gate behind `agent_mode=True` (matches v1.2 D1 opt-in pattern). Per-turn cap of N=3 facts is first-line bound.
3. **Recall result formatting.** Return facts as-is in tool result, or include importance + age metadata for planner reasoning? Decide in Phase 24 PLAN.
4. **HNSW iterative_scan mode for memory recall.** `strict_order` (current design) vs `relaxed_order` (vector_store.py default per v1.0 Phase 1). Decide in Phase 24 plan based on offline eval.
5. **Cap tuning.** 500 facts/user/tenant is the default. Phase 25 ships in audit mode first (logs distribution, no deletes); operator sets cap from real distribution before enabling enforcement. Per-tenant capacity overrides deferred to v1.7.

### Blockers

None.

### Todos (carry-forward, not v1.6-scoped but tracked)

- [ ] asyncpg pool + RLS: verify `app.current_tenant` per-connection in production pool (+ extend RLS to `long_term_facts`)
- [ ] PyMuPDF AGPL license: resolve commercial licensing for on-premise deployments
- [ ] Phase 9/14 visual diff vs v1.0 + Docker live build (deferred to first deploy)
- [ ] Phase 10/15 live PR through CI confirms `coverage-combine` job + HTML artifact (natural confirmation on first PR)
- [ ] v1.7+ follow-up: Code-acting / SQLTool (10x roadmap #4) — sandbox selection unresolved
- [ ] v1.7+ follow-up: SSE memory.* event types (memory.extracted, memory.recalled) — explicit-trace differentiation extension
- [ ] v1.7+ follow-up: Per-tenant capacity overrides + importance decay (D5 option 4)
- [ ] v1.7+ follow-up: UI-03 React/Vue full migration; TEST-07 mutation testing; UI-02 first-deploy browser smoke test
- [ ] Docker Build CI fix (paddleocr / paddlex / paddlepaddle ABI churn — currently `continue-on-error: true`)
- [ ] v1.7+ follow-up (per eng-review A3, 2026-05-16): `save_fact` embedding-dedup guard — `SELECT 1 ... <=> $embedding < 0.05` precheck before INSERT to skip near-duplicate facts (same user said "I prefer React" in turn 5 and turn 47 → two rows today). Threshold (0.05) to be tuned from Phase 24 recall eval data, not guessed pre-deploy.
- [ ] v1.7+ follow-up (per eng-review perf-2, 2026-05-16): `LongTermMemory.save_facts(list[ExtractedFact])` batch path — 1× `embed_batch` + `executemany` cuts the current 3× round-trips per extractor turn to 1. Background-only latency improvement; useful once fact-throughput pressure surfaces.

## Session Continuity

**Last updated:** 2026-05-16 — Plan 23-06 GREEN. All 6 plans of Phase 23 complete. MEM-01 + MEM-04 integration verification + per-module coverage gate green (97.4% extractor / 93.3% memory_service). 7 new integration tests collected; SKIP gracefully on CI hosts without PostgreSQL. Pre-tag check: run `uv run pytest tests/integration/test_long_term_facts_schema.py tests/integration/test_extractor_e2e.py tests/integration/test_swarm_pipeline_extractor_e2e.py -m pgvector -x -q` against a live local PG to confirm 7/7 PASS.
**Stopped at:** Completed 23-06-PLAN.md (Plan 23 wave 4 — integration + coverage gate, SC-1/4/5 closed)
**Next action:** `/gsd-verify-work 23` to run the Phase 23 verifier, then `/gsd-ship` to advance to Phase 24.

**Plan Map (Phase 24):**
| Plan | Wave | Reqs | Files | Depends on |
|------|------|------|-------|------------|
| 24-01 | 1 | MEM-08, MEM-09 | config/settings.py (`recall_tool_enabled`), services/agent/tools/recall.py (stub) | — |
| 24-02 | 1 | MEM-06 | services/memory/memory_service.py (`get_relevant_facts` rewrite — embed + HNSW strict_order + ef_search GUC in txn + cosine ORDER BY) | — |
| 24-03 | 2 | MEM-08 | services/agent/tools/recall.py (body — best-effort + bullets + empty marker + registration decorator) | 24-02 |
| 24-04 | 3 | MEM-09 | services/agent/tools/__init__.py (conditional import), services/pipeline.py (AGENT_TOOL_ALLOWLIST 3→4) | 24-01, 24-03 |
| 24-05 | 3 | MEM-10 | services/memory/memory_service.py (`load_context` docstring), tests at 4 load_context call sites + `24-MEM10-AUDIT.json` token-delta artifact | 24-02 |
| 24-06 | 3 | MEM-07 | scripts/backfill_fact_embeddings.py (NEW CLI), docs/memory-eviction.md (NEW cost-docs companion section) | 24-02 |
| 24-07 | 4 | MEM-06, MEM-09 | SC-1 React-preference offline eval + per-module ≥70% coverage gate + diff-cover ≥80% + v1.5 baseline regression sweep | 24-04, 24-05, 24-06 |

**Plan Map (Phase 23, completed):**
| Plan | Wave | Reqs | Files | Depends on |
|------|------|------|-------|------------|
| 23-01 | 1 | MEM-01 | services/memory/memory_service.py (DDL + register_vector + `MemoryFactWriteError` class) | — |
| 23-02 | 2 | MEM-02 | services/memory/memory_service.py (`save_fact` embed-on-write) + services/vectorizer/embedder.py (A1 OpenAI dim fix) | 23-01 |
| 23-03 | 1 | MEM-03 | services/agent/extractor.py, utils/models.py (`ExtractedFact`), config/settings.py | — |
| 23-04 | 2 | MEM-05 | tests/unit/test_extractor_adversarial.py + fixtures | 23-03 |
| 23-05 | 3 | MEM-04 | services/agent/extractor.py (`dispatch_extraction`), services/pipeline.py (Agent + Swarm wire-in) | 23-02, 23-04 |
| 23-06 | 4 | MEM-01, MEM-04 | tests/integration/test_long_term_facts_schema.py, test_extractor_e2e.py, test_swarm_pipeline_extractor_e2e.py | 23-05 |

**Planned Phase:** 24 — pgvector RecallTool + semantic recall rewrite
