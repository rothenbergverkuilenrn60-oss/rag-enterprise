---
gsd_state_version: 1.0
milestone: v1.6
milestone_name: Memory Tool — Agent-Authored Long-Term Facts
status: Roadmap generated; ready for `/gsd-discuss-phase 23`
stopped_at: Phase 23 context gathered
last_updated: "2026-05-15T14:18:37.854Z"
last_activity: 2026-05-15 — v1.6 ROADMAP.md generated via gsd-roadmapper from approved /office-hours design doc
progress:
  total_phases: 3
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
---

# STATE — EnterpriseRAG (v1.6 planning)

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-15 after v1.6 open)

**Core value:** Every query returns a grounded, auditable answer — no hallucinations, no silent failures, no security gaps.
**Current focus:** v1.6 Memory Tool — agent-authored long-term facts as new agent-callable third store (extractor → pgvector RecallTool → eviction + GDPR forget API).

## Current Position

Phase: 23 (not yet discussed)
Plan: —
Status: Roadmap generated; ready for `/gsd-discuss-phase 23`
Last activity: 2026-05-15 — v1.6 ROADMAP.md generated via gsd-roadmapper from approved /office-hours design doc

## Phase Overview

| Phase | Name | REQ-IDs | Status |
|-------|------|---------|--------|
| 23 | Background Extractor + schema migration | MEM-01, MEM-02, MEM-03, MEM-04, MEM-05 | Pending — ready for /gsd-discuss-phase 23 |
| 24 | pgvector RecallTool + semantic recall rewrite | MEM-06, MEM-07, MEM-08, MEM-09, MEM-10 | Pending |
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

## Session Continuity

**Last updated:** 2026-05-15 — v1.6 ROADMAP.md generated via gsd-roadmapper from approved /office-hours design doc; phases 23/24/25 each have 5 observable success criteria; 16/16 requirement coverage validated.
**Stopped at:** Phase 23 context gathered
**Next action:** `/gsd-discuss-phase 23`

**Planned Phase:** 23 — Background Extractor sub-agent + schema migration
