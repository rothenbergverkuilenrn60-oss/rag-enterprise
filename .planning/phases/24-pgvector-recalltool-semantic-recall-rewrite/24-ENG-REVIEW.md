# Phase 24 Eng Review — 2026-05-16

**Reviewer:** `/plan-eng-review` (Claude Opus 4.7 + Claude subagent outside voice)
**Branch:** master
**Commit at review:** 5adcf19
**Phase plans reviewed:** 24-01..24-07 (7 plans, 4 waves)

## Decisions Applied (must land before /gsd-execute-phase 24)

Nine decisions captured during interactive review. Each amends one or more plan files.

| # | Decision | Plan(s) affected | Effort (human / CC) |
|---|----------|------------------|---------------------|
| 1 | **Drop `load_context()` `long_term_facts` injection.** Planner gets long-term facts via `RecallTool` opt-in only. Removes D-B1 double-fetch architecture wart. | 02, 05 | 2h / 15 min |
| 2 | Add `MemoryService.get_relevant_facts(...)` passthrough method. `RecallTool.run` calls `mem.get_relevant_facts(...)` not `mem._long.get_relevant_facts(...)`. Decouples tool from private internals. | 02, 03 | 30 min / 5 min |
| 3 | Plan 06 narrow `except Exception:  # noqa: BLE001` → `except asyncpg.Error as exc:`. Removes noqa, satisfies ERR-01. | 06 | 15 min / 3 min |
| 4 | Add 3 ASCII diagrams: (a) `MemoryService.load_context` 3-store gather (post-removal shape); (b) `RecallTool.run` 3-branch fan-out (auth / error / happy); (c) backfill cursor + chunked-commit + idempotent-skip loop. | 02, 03, 06 | 1h / 10 min |
| 5 | Plan 06 backfill UPDATE row-by-row → `UPDATE long_term_facts SET embedding=u.emb FROM unnest($1::uuid[], $2::vector[]) AS u(id, emb) WHERE long_term_facts.id = u.id`. 10–50× throughput, same txn semantics. Update acceptance-criteria grep gates. | 06 | 30 min / 5 min |
| 6 | Add `tests/integration/test_recall_latency.py` for ROADMAP SC-3 (<50ms p95 @ 10k rows). **SQL-only scope**: embed query ONCE outside timed loop, run SELECT 50× inside loop, measure p95 of SQL timings only. Skip-gated on PG_AVAILABLE. | 07 | 2h / 15 min |
| 7 | SC-2 planner-pick test: real-LLM path with `pytest.mark.real_llm` marker. Run nightly / pre-tag, not on every CI. Pick-rate gate (e.g., 4/5 picks for preference query, 0/5 for unrelated). Replaces Plan 04 Test 1 Option B (mocked planner). | 04 | 3h / 20 min |
| 8 | Plan 04 reload helper: add `sys.modules.pop('services.agent.tools.recall', None)` before `importlib.reload(tools_mod)`. Without it the cached module short-circuits the conditional import and the test asserts registry-singleton reset, not actual kill-switch behavior. | 04 | 30 min / 5 min |
| 9 | Plan 05 MEM-10 audit reshape: was popularity-vs-semantic token-delta JSON (methodologically broken — both paths use LIMIT 5 + same column → near-zero delta by construction). Repurpose to **4-site removal regression** asserting `mem_ctx.long_term_facts == []` (or field removed) post-Decision-1, plus optional end-to-end response-token measurement against v1.5 baseline. | 05 | 2h / 15 min |

## Plans Affected Summary

| Plan | Decisions | Net change |
|------|-----------|-----------|
| 01 | — | None |
| 02 | 1, 2, 4 | Add passthrough method; remove `long_term_facts` from `load_context` gather; add ASCII diagram in docstring |
| 03 | 2, 4 | Call `mem.get_relevant_facts` (not `mem._long.*`); update acceptance grep `mem._long.get_relevant_facts` → `mem.get_relevant_facts`; add ASCII fan-out diagram |
| 04 | 7, 8 | Real-LLM marker for SC-2 test; `sys.modules.pop` in reload helper |
| 05 | 1, 9 | Drop popularity-baseline SELECT + token-delta JSON; replace with 4-site removal regression test |
| 06 | 3, 4, 5 | Narrow except to `asyncpg.Error` (no noqa); batch UPDATE...FROM unnest skeleton + grep gates; ASCII cursor diagram |
| 07 | 6 | New `test_recall_latency.py` (SQL-only); SC-1 cosine test unchanged |

## NOT in Scope (deferred, with rationale)

| Item | Rationale | When |
|------|-----------|------|
| RecallTool result metadata (`importance`, `recalled_days_ago`) | Defer until planner confidence-weighting evidence exists (CONTEXT C1) | v1.7+ |
| Dedup at planner-tool-result-merge | After Decision-1, no duplicates exist; obsolete | N/A |
| `load_context` K shrink to 1-2 | Decision-1 supersedes (K=0 now) | N/A |
| `--qps` rate-limit flag for backfill | tenacity in `embed_batch` handles 5xx/429; add if 429s become routine (CONTEXT D-D2) | v1.7+ |
| Configurable similarity threshold | Opt-in once eval data justifies a value (CONTEXT A3) | v1.7+ |
| CronJob template for ongoing backfill | Phase 23 `save_fact` embeds-on-write covers steady state | If a schema migration adds rows w/o embeddings |
| SSE `memory.recalled` event | Design doc Premise 5 — out of v1.6 | v1.7+ |
| Cross-user-within-tenant recall | REQUIREMENTS v1.6 Out of Scope | v1.7+ |
| RLS enforcement on `long_term_facts` | v1.0 Phase 2 carry-forward | v1.7+ |
| Per-tenant capacity overrides + importance decay | Phase 25 deferred items | v1.8+ |
| Live planner `save_memory` tool | Rejected in /office-hours D3 | Never (architectural choice) |
| Per-request query-embed cache | Vestigial after Decision-1; no double-fetch exists | N/A |
| `--batch-update` flag for backfill | Decision-5 makes batch UPDATE the default | N/A |

## What Already Exists (heavily reused, good)

| New thing | Built on |
|-----------|----------|
| `get_relevant_facts` semantic rewrite | `services/vectorizer/vector_store.py:316-326` HNSW filter pattern (swap `relaxed_order` → `strict_order`) |
| `RecallTool` | Phase 17 `BaseTool` ABC + `ToolRegistry`; Phase 20 `web_search.py` ClassVar/decorator shape |
| `recall_tool_enabled` settings field | Phase 23 `extractor_enabled` shape |
| Narrow-exception tuple | Phase 23 `save_fact` `(httpx.HTTPError, RuntimeError, OSError)` |
| Backfill pool reuse | Phase 23 `_get_pool` with `register_vector` codec init (Pitfall 1 mitigation) |
| Backfill CLI shape | `scripts/ingest_batch.py` argparse + asyncio.run |
| Test fixtures | Phase 23 `pgvector_pool`, `clean_long_term_facts`, `embedder_or_mock` |
| Integration test marker block | Phase 23 `test_extractor_e2e.py` skip-gracefully pattern |

## Failure Modes (one per new codepath)

| Codepath | Realistic failure | Test? | Error handling? | User signal? |
|----------|-------------------|-------|------------------|--------------|
| `get_relevant_facts` embedder timeout | Ollama/OpenAI/HF up to 30s timeout | ✓ Plan 02 T4 | Narrow `except` → `[]` | Silent (planner sees no facts → no recall result → user gets answer without memory) |
| `get_relevant_facts` SQL failure | DB unreachable / pgvector codec mismatch | ✓ Plan 02 T5 | `asyncpg.PostgresError` → `[]` | Silent |
| `RecallTool.run` error path | Either of above bubbles up to tool layer | ✓ Plan 03 T6 (4-exc parametrize) | `is_error=True` + stable marker | Planner sees `is_error=True` ToolResult; synthesizer audit log captures |
| Auth precondition (empty user_id/tenant_id/query) | Anonymous request reaches RecallTool | ✓ Plan 03 T7-9 | Early return empty marker | Silent (planner sees "No matching facts found.") |
| Kill-switch False | Operator emergency rollback | ✓ Plan 04 T5/T6 (post sys.modules.pop fix) | Registry returns KeyError → schemas_for omits | Planner LLM never sees tool schema |
| Backfill embedder failure mid-batch | OpenAI quota exhausted / Ollama down | ✓ Plan 06 T6 | Exit 1; idempotent re-run | Operator-visible (exit code + log) |
| Backfill txn rollback (SQL mid-batch) | pgvector dim mismatch / connection drop | ✓ Plan 06 T5 | Whole-batch rollback + exit 1 | Operator-visible |
| `load_context` failure (post-Decision-1) | `_short.get_history` or `_long.get_user_profile` raises | Existing v1.5 coverage | `asyncio.gather(return_exceptions=True)` + `isinstance` guards | Empty list / None |

**Zero critical gaps.** Every failure mode has both a test AND error handling AND would not produce a silent crash to the user. The `get_relevant_facts` failures DO produce silent "no recall" behavior, but that's a deliberate design choice — recall is best-effort, not required for response generation.

## Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|------|----------------|------------|
| Plan 01 (settings field + stub) | config/, services/agent/tools/ | — |
| Plan 02 (get_relevant_facts rewrite + passthrough + load_context drop) | services/memory/ | — |
| Plan 03 (RecallTool body + decorator) | services/agent/tools/ | Plan 02 (calls passthrough), Plan 01 (stub) |
| Plan 04 (__init__.py + allowlist + kill-switch tests) | services/agent/tools/, services/pipeline.py | Plan 01, Plan 03 |
| Plan 05 (MEM-10 reshape: 4-site removal regression) | services/memory/, tests/integration/ | Plan 02 |
| Plan 06 (backfill CLI + docs + batch UPDATE) | scripts/, docs/ | Plan 02 |
| Plan 07 (SC-1 quality + SC-3 latency + coverage gate) | tests/integration/ | All prior |

**Parallel lanes** (matches existing wave plan + 1 wave-internal split):

- **Wave 1:** Lane A (Plan 01: config/, services/agent/tools/) || Lane B (Plan 02: services/memory/) — different modules, no shared files. **Run parallel.**
- **Wave 2:** Plan 03 only — sequential. Touches services/agent/tools/, depends on Plan 02's passthrough.
- **Wave 3:** Lane A (Plan 04: services/agent/tools/__init__.py + services/pipeline.py) || Lane B (Plan 05: services/memory/, tests/integration/) || Lane C (Plan 06: scripts/, docs/) — disjoint modules. **Run parallel.**
- **Wave 4:** Plan 07 only — sequential. Verification + coverage sweep across all prior.

**Conflict flags:** None. Wave-1 and Wave-3 parallel lanes touch disjoint module directories. Plan 05's `services/memory/memory_service.py` docstring edit and Plan 02's `services/memory/memory_service.py` body rewrite both touch the same file, but they're in different waves (sequential) so no concurrent-edit risk.

## Implementation Tasks

Synthesized from decisions above. Each task derives from a specific review finding. Each is bounded enough that an executor can land it without re-reading the full review.

- [ ] **T1 (P1, human: ~2h / CC: ~15 min)** — `services/memory/memory_service.py` — Drop `long_term_facts` from `load_context()` gather (Decision-1).
  - Surfaced by: Section 1 + outside voice — D-B1 double-path overcomplexity
  - Files: `services/memory/memory_service.py`, all 4 call sites in `services/pipeline.py:429,608,971,1062` if any code reads `mem_ctx.long_term_facts` (verify with grep)
  - Verify: `grep -rn 'long_term_facts' services/` shows no reads outside `RecallTool` and the audit test; `tests/integration/test_pipeline_load_context_audit.py` asserts `mem_ctx.long_term_facts == []`
- [ ] **T2 (P1, human: ~30 min / CC: ~5 min)** — `services/memory/memory_service.py` — Add public `MemoryService.get_relevant_facts(user_id, tenant_id, query, limit=5)` passthrough (Decision-2).
  - Surfaced by: Section 1 — `_long` private-attr reach in tool code
  - Files: `services/memory/memory_service.py`
  - Verify: `grep -n 'def get_relevant_facts' services/memory/memory_service.py | wc -l` returns 2 (LongTermMemory.get_relevant_facts + MemoryService.get_relevant_facts passthrough)
- [ ] **T3 (P1, human: ~15 min / CC: ~3 min)** — `services/agent/tools/recall.py` — Call `mem.get_relevant_facts(...)` not `mem._long.get_relevant_facts(...)` (Decision-2 follow-through).
  - Surfaced by: Section 1 — coupling
  - Files: `services/agent/tools/recall.py`, `.planning/phases/24-.../24-03-PLAN.md` acceptance grep gate
  - Verify: `grep -n '_long' services/agent/tools/recall.py | wc -l` returns 0
- [ ] **T4 (P1, human: ~30 min / CC: ~5 min)** — `scripts/backfill_fact_embeddings.py` — Switch UPDATE to `FROM unnest($1::uuid[], $2::vector[])` batch form (Decision-5).
  - Surfaced by: Section 4 — 10–50× backfill throughput
  - Files: `scripts/backfill_fact_embeddings.py`, `.planning/phases/24-.../24-06-PLAN.md` acceptance grep gate
  - Verify: `grep -n 'unnest' scripts/backfill_fact_embeddings.py | wc -l` returns ≥ 1; `grep -n 'WHERE id=\$2' scripts/backfill_fact_embeddings.py` returns 0
- [ ] **T5 (P1, human: ~15 min / CC: ~3 min)** — `scripts/backfill_fact_embeddings.py` — Replace `# noqa: BLE001` catch with `except asyncpg.Error as exc:` (Decision-3).
  - Surfaced by: Section 2 — ERR-01 compliance
  - Files: `scripts/backfill_fact_embeddings.py`
  - Verify: `grep -c '# noqa' scripts/backfill_fact_embeddings.py` returns 0
- [ ] **T6 (P2, human: ~30 min / CC: ~5 min)** — `tests/unit/test_settings_recall_kill_switch.py` — Add `sys.modules.pop('services.agent.tools.recall', None)` to `_reset_registry_and_reimport` helper (Decision-8).
  - Surfaced by: Outside voice — reload caches module, kill-switch test passes for wrong reason
  - Files: `tests/unit/test_settings_recall_kill_switch.py`
  - Verify: `grep -n 'sys.modules.pop' tests/unit/test_settings_recall_kill_switch.py` returns ≥ 1; toggle-False test actually exercises import path
- [ ] **T7 (P1, human: ~3h / CC: ~20 min)** — `tests/integration/test_recall_tool_planner_pick.py` — Convert Plan 04 SC-2 test to real-LLM path with `@pytest.mark.real_llm` marker; pick-rate gate (≥4/5 for preference, 0/5 for unrelated) over fixed seed (Decision-7).
  - Surfaced by: Outside voice — mocked planner doesn't test SC-2
  - Files: `tests/integration/test_recall_tool_planner_pick.py`, `pytest.ini` (add `real_llm` marker)
  - Verify: pre-tag run `uv run pytest -m real_llm tests/integration/test_recall_tool_planner_pick.py` GREEN; CI run `uv run pytest -m 'not real_llm'` excludes
- [ ] **T8 (P1, human: ~2h / CC: ~15 min)** — `tests/integration/test_pipeline_load_context_audit.py` — Reshape to 4-site removal regression (Decision-9). Plus optional end-to-end response-token measurement against v1.5 baseline.
  - Surfaced by: Outside voice — Plan 05 token-delta methodologically moot
  - Files: `tests/integration/test_pipeline_load_context_audit.py`, optional `24-MEM10-AUDIT.json` schema change
  - Verify: tests assert `mem_ctx.long_term_facts == []` at all 4 sites; audit JSON shape documented in test docstring
- [ ] **T9 (P1, human: ~2h / CC: ~15 min)** — `tests/integration/test_recall_latency.py` (NEW) — SC-3 SQL-only latency benchmark. Seed 10k rows for one (user, tenant); embed query once; run SELECT 50× timed via `time.perf_counter`; assert p95 < 50ms (Decision-6).
  - Surfaced by: Section 3 + outside voice — SC-3 had no automated check; embed timing must be excluded
  - Files: `tests/integration/test_recall_latency.py`
  - Verify: `pytest -m pgvector tests/integration/test_recall_latency.py -x -q` GREEN where PG available
- [ ] **T10 (P2, human: ~1h / CC: ~10 min)** — Three ASCII diagrams embedded in code (Decision-4):
  - `services/memory/memory_service.py::load_context` docstring → 3-store gather diagram (post-removal: only `_short` + `_long.get_user_profile`)
  - `services/agent/tools/recall.py::RecallTool.run` docstring → 3-branch fan-out (auth precondition / error / happy)
  - `scripts/backfill_fact_embeddings.py::backfill` docstring → cursor + chunked-commit + idempotent-skip loop
  - Surfaced by: Section 2 — CLAUDE.md preference for ASCII diagrams in processing-pipeline code
  - Files: 3 modules above
  - Verify: each function/method docstring contains an ASCII diagram block bounded by `--` or similar
- [ ] **T11 (P3, human: ~10 min / CC: ~2 min)** — `tests/unit/test_settings_recall_kill_switch.py::test_allowlist_length_constant_regardless_of_toggle` — currently a tautology (asserts hardcoded `len == 4`). Either toggle within the test to demonstrate actual invariance or delete it.
  - Surfaced by: Outside voice — dead-code test
  - Files: `tests/unit/test_settings_recall_kill_switch.py`
  - Verify: test asserts behavior under both toggle states OR test is removed

## TODOs.md proposed

No `TODOS.md` exists in the repo. Recommend deferring TODO file creation. Two items worth tracking elsewhere:

1. **D-B4 "kill-switch" naming is misleading** (outside voice #9) — module-import-time setting requires process restart; the term "kill-switch" implies runtime flip. Cosmetic doc fix. Update `docs/memory-eviction.md` operator playbook to say "config flag (requires process restart)" rather than "kill-switch."
2. **v1.7 evaluation paths** — once Phase 25 ships eviction + capacity caps and real production traffic accumulates: revisit (a) whether to surface recall metadata in ToolResult (importance + age); (b) whether to add SSE `memory.recalled` event; (c) whether to add per-tenant overrides.

Recommend capturing both in `.planning/STATE.md §Open Questions` as v1.7 carry-forwards (matches Phase 23 pattern).

## Outside Voice (Claude subagent) — Cross-Model Tension Summary

| Tension | Eng review stance | Outside voice stance | Resolution (user-decided) |
|---------|-------------------|----------------------|---------------------------|
| D-B1 double-fetch | Cache mitigates | Architectural overcomplexity — kill one path | **Drop `load_context` long_term_facts** (outside voice won) |
| SC-2 test mode | Accepted as-planned | Mocked planner ≠ SC-2 | **Real-LLM with marker** (outside voice won) |
| SC-3 latency scope | Add test wrapping `get_relevant_facts` | Should be SQL-only; embed_one alone exceeds 50ms | **SQL-only test** (outside voice won) |
| Plan 05 token-delta | Observational audit | Methodologically moot | **Repurpose to 4-site removal regression** (outside voice won) |
| Plan 04 reload helper | Helper as-specified | sys.modules cache breaks test | **Add sys.modules.pop** (outside voice won) |
| Plan 04 Test 7 tautology | Not flagged | Tautological assertion | **TODO T11: toggle or delete** |

Outside voice was decisively right on 5 of 6 substantive points. Eng review missed the SC-2 mock-vs-real distinction and the Plan 05 methodology hole.

## Completion Summary

- **Step 0: Scope Challenge** — scope accepted as-is (7 production/docs files, below 8-file/2-class threshold)
- **Architecture Review** — 2 issues found, both addressed (later expanded by outside voice + Decision-7)
- **Code Quality Review** — 2 issues found, both addressed
- **Test Review** — diagram produced, 1 SC-3 gap identified + filled; +3 gaps from outside voice (SC-2 mock, MEM-10 methodology, reload helper)
- **Performance Review** — 1 issue found, addressed (batch UPDATE)
- **Outside Voice** — Claude subagent (Codex unavailable). 9 points raised; 5 substantive new findings absorbed
- **NOT in scope** — written (12 items, all with rationale + when-to-revisit)
- **What already exists** — written (8 reuse mappings)
- **TODOS.md updates** — 0 items added to TODOS.md (file doesn't exist); 2 items proposed for STATE.md §Open Questions
- **Failure modes** — 8 codepaths × test + handling + user-signal mapping; **0 critical gaps**
- **Parallelization** — 4 waves, 6 parallel-lane opportunities flagged (matches existing Phase 24 wave plan)
- **Implementation Tasks** — 11 tasks (8 P1, 2 P2, 1 P3)

## Unresolved Decisions

None. All decisions confirmed via AskUserQuestion.

## VERDICT

**ISSUES_OPEN** — 9 plan amendments required before `/gsd-execute-phase 24`. Update Plans 02, 03, 04, 05, 06, 07 per the Decisions table + Implementation Tasks. Plan 01 unchanged.

After amendments land, re-run plan-checker; if PASSED, proceed to execution.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 3 | ISSUES_OPEN | 9 issues, 0 critical gaps, mode FULL_REVIEW |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**OUTSIDE VOICE (Claude subagent — Codex unavailable):** 9 points raised, 5 substantive findings absorbed (D-B1 architecture, SC-2 mocked planner, SC-3 measurement scope, Plan 05 methodology, Plan 04 reload helper). 1 cosmetic (kill-switch naming). 1 dead-code test flagged (T11).
**CROSS-MODEL:** Outside voice + eng review converged on all 6 substantive findings; outside voice decisively expanded the architecture concern from "double-fetch latency" (eng review) to "remove redundant path entirely" (outside voice).
**UNRESOLVED:** 0
**VERDICT:** **NOT CLEARED** — 9 plan amendments required. Re-run plan-checker after Plans 02/03/04/05/06/07 are updated, then proceed to `/gsd-execute-phase 24`.
