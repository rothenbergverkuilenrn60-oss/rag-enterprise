---
phase: 24
slug: pgvector-recalltool-semantic-recall-rewrite
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-05-16
---

# Phase 24 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Mirrors Phase 23 23-VALIDATION.md shape; extended with Plan 04-07 surfaces.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + pytest-asyncio ≥ 1.3.0 (verified pyproject.toml) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) + `tests/conftest.py` |
| **Quick run command** | `uv run pytest tests/unit/ -x -q` |
| **Full suite command** | `uv run pytest --cov --cov-report=xml -p no:cacheprovider` |
| **Estimated runtime** | ~50 seconds (unit) / ~3 minutes (full, no integration) / ~5 minutes (full + integration with PG) |

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/unit/ -x -q` (~50s feedback)
- **After every plan wave merge:** `uv run pytest --cov --cov-report=xml -p no:cacheprovider`
- **Before `/gsd:verify-work 24`:**
  - Full unit suite GREEN
  - Per-module coverage ≥ 70% on `services/agent/tools/recall.py`, `services/memory/memory_service.py`, `scripts/backfill_fact_embeddings.py`
  - Diff-cover ≥ 80% on touched files
  - Integration suite GREEN where PG available (skip-gating acceptable on CI per Phase 23 precedent)
  - v1.0-v1.5 baseline unit suite still GREEN (MEM-10 SC-5)
- **Max feedback latency:** 50 seconds (unit-quick path)

---

## Per-Task Verification Map

> One row per task. Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 24-01-01 | 01 | 1 | MEM-08, MEM-09 | T-24-01-T1 / classvars-frozen | settings field + RecallTool stub three ClassVars + D-C4 description verbatim | unit | `uv run pytest tests/unit/test_settings_recall_kill_switch.py::test_recall_tool_classvars_present -x` | ❌ W0 | ⬜ pending |
| 24-01-02 | 01 | 1 | MEM-09 / D-B4 | T-24-01-S1 / kill-switch-default-true | `settings.recall_tool_enabled is True` default | unit | `uv run pytest tests/unit/test_settings_recall_kill_switch.py::test_recall_tool_enabled_default_true -x` | ❌ W0 | ⬜ pending |
| 24-02-01 | 02 | 1 | MEM-06 | T-24-02-T1 / set-local-txn-wrap | `SET LOCAL hnsw.ef_search` issued inside `async with conn.transaction()` (Pitfall 2) | unit | `uv run pytest tests/unit/test_memory_recall_semantic.py::test_get_relevant_facts_uses_transaction -x` | ❌ W0 | ⬜ pending |
| 24-02-02 | 02 | 1 | MEM-06 | T-24-02-I1 / where-prefilter | Recall SQL includes `WHERE user_id=$1 AND tenant_id=$2` + `ORDER BY embedding <=> $3::vector` + tie-break + LIMIT $4 | unit | `uv run pytest tests/unit/test_memory_recall_semantic.py::test_tie_break_sql_includes_importance_and_created_at -x` | ❌ W0 | ⬜ pending |
| 24-02-03 | 02 | 1 | MEM-06 | T-24-02-D1 / embedder-failure-isolated | Embedder failure → returns `[]`, never raises (Pitfall 6) | unit | `uv run pytest tests/unit/test_memory_recall_semantic.py::test_embedder_failure_returns_empty -x` | ❌ W0 | ⬜ pending |
| 24-02-04 | 02 | 1 | MEM-06 | T-24-02-T2 / bare-strings | Returns `list[str]` with no `- ` prefix (Pitfall 3) | unit | `uv run pytest tests/unit/test_memory_recall_semantic.py::test_returns_bare_strings_no_prefix -x` | ❌ W0 | ⬜ pending |
| 24-02-05 | 02 | 1 | MEM-06 | T-24-02-R1 / signature-preserved | `inspect.signature(get_relevant_facts)` unchanged | unit | `uv run pytest tests/unit/test_memory_recall_semantic.py::test_signature_unchanged -x` | ❌ W0 | ⬜ pending |
| 24-03-01 | 03 | 2 | MEM-08 | T-24-03-T1 / registered-exactly-once | `get_tool_registry().list().count("recall_memory") == 1` (Pitfall 4) | unit | `uv run pytest tests/unit/test_recall_tool.py::test_recall_tool_registered_once -x` | ❌ W0 | ⬜ pending |
| 24-03-02 | 03 | 2 | MEM-08 | T-24-03-D1 / bullets-happy-path | `ToolResult.content == "- f1\\n- f2\\n- f3"`; `is_error=False`; latency metadata present | unit | `uv run pytest tests/unit/test_recall_tool.py::test_happy_path_bullets -x` | ❌ W0 | ⬜ pending |
| 24-03-03 | 03 | 2 | MEM-08 | T-24-03-I2 / empty-marker-not-error | `[]` facts → `_EMPTY_MARKER`; `is_error=False` (D-C2) | unit | `uv run pytest tests/unit/test_recall_tool.py::test_empty_marker -x` | ❌ W0 | ⬜ pending |
| 24-03-04 | 03 | 2 | MEM-08 | T-24-03-D2 / best-effort-isolation | Exception → `_ERROR_MARKER`; `is_error=True`; never raises (D-C3) | unit | `uv run pytest tests/unit/test_recall_tool.py::test_error_isolation_parametrized -x` | ❌ W0 | ⬜ pending |
| 24-03-05 | 03 | 2 | MEM-08 | T-24-03-S1 / missing-auth-empty | empty `user_id` / `tenant_id` → empty marker; `get_memory_service` not called | unit | `uv run pytest tests/unit/test_recall_tool.py::test_missing_user_id_returns_empty -x` | ❌ W0 | ⬜ pending |
| 24-04-01 | 04 | 3 | MEM-09 / D-B4 | T-24-04-T2 / kill-switch-enabled | `enabled=True` → `recall_memory` in registry list | unit | `uv run pytest tests/unit/test_settings_recall_kill_switch.py::test_enabled_registers_recall_memory -x` | ❌ W0 | ⬜ pending |
| 24-04-02 | 04 | 3 | MEM-09 / D-B4 | T-24-04-T2 / kill-switch-disabled | `enabled=False` → `KeyError` on `registry.get("recall_memory")` | unit | `uv run pytest tests/unit/test_settings_recall_kill_switch.py::test_disabled_registry_lookup_raises_keyerror -x` | ❌ W0 | ⬜ pending |
| 24-04-03 | 04 | 3 | MEM-09 | T-24-04-T1 / allowlist-constant | `AGENT_TOOL_ALLOWLIST length == 4` regardless of toggle | unit | `uv run pytest tests/unit/test_settings_recall_kill_switch.py::test_allowlist_length_constant_regardless_of_toggle -x` | ❌ W0 | ⬜ pending |
| 24-04-04 | 04 | 3 | MEM-09 | T-24-04-T2 / schemas-omits-disabled | `schemas_for(..., names=ALLOWLIST)` returns 3 when disabled | unit | `uv run pytest tests/unit/test_settings_recall_kill_switch.py::test_schemas_for_omits_when_disabled -x` | ❌ W0 | ⬜ pending |
| 24-04-05 | 04 | 3 | MEM-09 | T-24-04-I1 / planner-pick-preference | Planner picks `recall_memory` for preference query | integration | `uv run pytest tests/integration/test_recall_tool_planner_pick.py::test_planner_picks_recall_for_preference_query -m pgvector -x` | ❌ W0 | ⬜ pending |
| 24-04-06 | 04 | 3 | MEM-09 | T-24-04-I1 / planner-skip-unrelated | Planner skips `recall_memory` for unrelated query | integration | `uv run pytest tests/integration/test_recall_tool_planner_pick.py::test_planner_skips_recall_for_unrelated_query -m pgvector -x` | ❌ W0 | ⬜ pending |
| 24-05-01 | 05 | 3 | MEM-10 | T-24-05-T1 / length-4-callsites | `len(mem_ctx.long_term_facts) <= 5` at each of 4 call sites | integration | `uv run pytest tests/integration/test_pipeline_load_context_audit.py::test_load_context_facts_length_le_5_all_four_callsites -m pgvector -x` | ❌ W0 | ⬜ pending |
| 24-05-02 | 05 | 3 | MEM-10 | T-24-05-T1 / no-bullet-prefix | Returned facts are bare strings (Pitfall 3) | integration | `uv run pytest tests/integration/test_pipeline_load_context_audit.py::test_load_context_returns_list_of_str_no_prefix -m pgvector -x` | ❌ W0 | ⬜ pending |
| 24-05-03 | 05 | 3 | MEM-10 / D-B3 | T-24-05-D2 / token-delta-artifact | Audit artifact written to `.planning/phases/24-.../24-MEM10-AUDIT.json` | integration | `uv run pytest tests/integration/test_pipeline_load_context_audit.py::test_writes_token_delta_artifact -m pgvector -x` | ❌ W0 | ⬜ pending |
| 24-05-04 | 05 | 3 | MEM-10 | T-24-05-D1 / no-v1-5-regression | v1.5 baseline integration test still passes | integration | `uv run pytest tests/integration/test_pipeline_load_context_audit.py::test_no_v1_5_regression -m pgvector -x` | ❌ W0 | ⬜ pending |
| 24-06-01 | 06 | 3 | MEM-07 | T-24-06-D1 / dry-run-no-api | `--dry-run` → 0 API calls, exit 0, log contains "Would embed" | unit | `uv run pytest tests/unit/test_backfill_fact_embeddings.py::test_dry_run_no_api_calls -x` | ❌ W0 | ⬜ pending |
| 24-06-02 | 06 | 3 | MEM-07 | T-24-06-D2 / batch-rollback-atomic | UPDATE raise on row 47 → txn rollback; exit 1 (Pitfall 7) | unit | `uv run pytest tests/unit/test_backfill_fact_embeddings.py::test_batch_rollback_on_failure -x` | ❌ W0 | ⬜ pending |
| 24-06-03 | 06 | 3 | MEM-07 | T-24-06-T1 / idempotent-rerun | Second run → 0 API calls, exit 0, total_done=0 | unit | `uv run pytest tests/unit/test_backfill_fact_embeddings.py::test_idempotent_second_run -x` | ❌ W0 | ⬜ pending |
| 24-06-04 | 06 | 3 | MEM-07 | T-24-06-T2 / pool-reuse | Reuses `LongTermMemory._get_pool` (Pitfall 1) | unit | `uv run pytest tests/unit/test_backfill_fact_embeddings.py::test_reuses_long_term_memory_pool -x` | ❌ W0 | ⬜ pending |
| 24-06-05 | 06 | 3 | MEM-07 | T-24-06-T1 / resume-cursor | `--resume-from-id` adds `AND id > $1` filter | unit | `uv run pytest tests/unit/test_backfill_fact_embeddings.py::test_resume_from_id_uses_cursor_filter -x` | ❌ W0 | ⬜ pending |
| 24-07-01 | 07 | 4 | MEM-06 / SC-1 | T-24-07-T1 / cosine-quality | "frontend?" query recalls React fact at cosine > 0.7 | integration | `uv run pytest tests/integration/test_recall_offline_eval.py::test_react_preference_recalled_with_high_cosine -m pgvector -x` | ❌ W0 | ⬜ pending |
| 24-07-02 | 07 | 4 | MEM-06 / SC-1 | T-24-07-T1 / cosine-negative | "database?" query returns no fact above cosine 0.5 | integration | `uv run pytest tests/integration/test_recall_offline_eval.py::test_database_query_returns_no_relevant_fact -m pgvector -x` | ❌ W0 | ⬜ pending |
| 24-07-03 | 07 | 4 | MEM-06+ | T-24-07-D1 / per-module-coverage | per-module ≥ 70% on recall.py / memory_service.py / backfill_fact_embeddings.py | coverage | `uv run pytest --cov=services/agent/tools/recall --cov=services/memory/memory_service --cov=scripts/backfill_fact_embeddings --cov-fail-under=70` | ❌ W0 | ⬜ pending |
| 24-07-04 | 07 | 4 | MEM-06+ | T-24-07-D1 / diff-cover | diff-cover ≥ 80% on Phase 24 diff against master | coverage | `uv run diff-cover coverage.xml --compare-branch=master --fail-under=80` | ❌ W0 | ⬜ pending |
| 24-07-05 | 07 | 4 | MEM-10 / SC-5 | T-24-07-R1 / v1-5-baseline | Full unit suite (all v1.0-v1.5 tests) GREEN | regression | `uv run pytest tests/unit/ -x -q` | ❌ W0 | ⬜ pending |

---

## Wave 0 Requirements

These test scaffolds MUST exist before each plan's GREEN production step is gated. Each entry maps to one or more Wave-0 tests in the Per-Task Verification Map above.

- [ ] `tests/unit/test_settings_recall_kill_switch.py` — Plan 01 (3 presence) + Plan 04 (5 importlib.reload) tests; SINGLE file extended across two plans
- [ ] `tests/unit/test_memory_recall_semantic.py` — Plan 02 (9 tests: txn-wrap, SET LOCAL, bare-strings + cosine ordering, embedder-failure, pg-failure, limit, signature, no-prefix, tie-break SQL)
- [ ] `tests/unit/test_recall_tool.py` — Plan 03 (13 tests: registered-once, classvars, parameters_schema, happy-path bullets, empty marker, error isolation parametrized over 4 exception types, missing-auth, args-overrides, latency-metadata, error-stable-marker)
- [ ] `tests/unit/test_backfill_fact_embeddings.py` — Plan 06 (9 tests: dry-run-no-api, dry-run-cost-format, happy-path batch commit, idempotent second run, batch rollback on failure, embedder failure exit 1, resume-from-id cursor, batch-size respected, pool reuse)
- [ ] `tests/integration/test_recall_tool_planner_pick.py` — Plan 04 (3 tests: planner picks for preference, skips for unrelated, RecallTool returns seeded React fact)
- [ ] `tests/integration/test_pipeline_load_context_audit.py` — Plan 05 (4 tests: 4-call-site length regression parametrized, bare-str-no-prefix regression, token-delta artifact writer, v1.5 baseline green-check)
- [ ] `tests/integration/test_recall_offline_eval.py` — Plan 07 (2 tests: React recall cosine > 0.7, database query max-cos ≤ 0.5)
- [ ] `tests/conftest.py` — OPTIONAL extension (Plan 07 may add `recall_offline_seed` fixture; default skip if local-to-test fixture suffices)

*(Framework install: not needed — pytest+asyncio+cov already in pyproject.toml; verified per RESEARCH §Environment Availability)*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| ROADMAP SC-3: HNSW prefilter performance — `WHERE user_id=$1 AND tenant_id=$2` recall against 10k-row seeded `long_term_facts` < 50ms p95 | MEM-06 | Bench tool not in scope per CONTEXT D-A2; existing tests run on small seeds; ASSUMED A2 latency budget needs real-data validation | Operator runs (one-off, optional): seed 10k facts under one (user_id, tenant_id) bucket via a fixture script; time 100 recall calls; record p95 to STATE.md notes |
| ROADMAP SC-1 cosine threshold drift across embedder model versions | MEM-06 / SC-1 | Different embedder providers (OpenAI vs HF vs Ollama) produce different cosine scales; Plan 07 tests assert > 0.7 under the deployed embedder; threshold may need adjustment if provider changes | Run Plan 07 tests after any `EMBEDDING_PROVIDER` change; if `cos > 0.7` fails by < 0.05, document A2-Assumption follow-up; if > 0.05, revise Plan 02 |
| MEM-10 token-delta interpretation | MEM-10 / D-B3 | Audit artifact is observational; operator decides if delta is acceptable for prompt budget at production scale | Operator reviews `.planning/phases/24-pgvector-recalltool-semantic-recall-rewrite/24-MEM10-AUDIT.json` after first production deploy; if delta > 30%, consider v1.7+ remediation paths from CONTEXT (B1 option 2: shrink K; B2 option 2: dedup at merge) |
| Backfill cost-formula accuracy at deploy | MEM-07 / D-D4 / A3-Assumption | Docs assume ~40 tokens/fact; actual distribution depends on tenant data | Run `uv run python scripts/backfill_fact_embeddings.py --dry-run` against staging tenant before production; compare estimated cost to actual after backfill; update `docs/memory-eviction.md` if formula is off by > 2x |
| OpenAI text-embedding pricing | MEM-07 / D-D4 / A3-Assumption | OpenAI pricing changes over time; docs verbatim at 2026-05-16 | Operator verifies pricing on platform.openai.com/docs/pricing before publishing docs externally |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify OR Wave 0 dependencies (every row in the per-task map has an automated command)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (8 stubs above; one file per Plan + 1 conftest optional)
- [x] No watch-mode flags
- [x] Feedback latency < 50s (unit-quick path)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending (auto-approved post-plan-creation; revisable during execution if RED gates surface uncovered surfaces)
