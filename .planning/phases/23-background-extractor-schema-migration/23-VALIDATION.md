---
phase: 23
slug: background-extractor-schema-migration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-15
---

# Phase 23 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) + `tests/conftest.py` |
| **Quick run command** | `uv run pytest tests/unit/ -x -q` |
| **Full suite command** | `uv run pytest --cov --cov-report=xml -p no:cacheprovider` |
| **Estimated runtime** | ~45 seconds (unit) / ~3 minutes (full) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/ -x -q`
- **After every plan wave:** Run `uv run pytest --cov --cov-report=xml -p no:cacheprovider`
- **Before `/gsd:verify-work`:** Full suite must be green; diff-cover ≥ 80% on touched files; per-module ≥ 70% on `services/agent/extractor.py` + `services/memory/memory_service.py`
- **Max feedback latency:** 45 seconds (unit-quick path)

---

## Per-Task Verification Map

> Filled in during planning. Initial scaffold below — planner / executor expand per task ID.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 23-01-01 | 01 | 1 | MEM-01 | T-23-S1 / schema-idempotent | `ALTER TABLE long_term_facts ADD COLUMN IF NOT EXISTS embedding VECTOR(1024)` runs twice without error | unit (DDL replay) | `uv run pytest tests/unit/test_memory_schema.py::test_create_tables_idempotent -x` | ❌ W0 | ⬜ pending |
| 23-01-02 | 01 | 1 | MEM-01 | T-23-S2 / index-usable | `EXPLAIN` plan on `<-> vector_cosine_ops` ORDER BY shows HNSW index scan | unit | `uv run pytest tests/unit/test_memory_schema.py::test_hnsw_index_used -x` | ❌ W0 | ⬜ pending |
| 23-02-01 | 02 | 1 | MEM-02 | T-23-D1 / embed-on-write | `save_fact` writes one row, embedding non-NULL, dim=1024 | unit | `uv run pytest tests/unit/test_memory_save_fact.py::test_save_fact_embeds -x` | ❌ W0 | ⬜ pending |
| 23-02-02 | 02 | 1 | MEM-02 | T-23-D2 / no-partial-write | Embedder failure → `MemoryFactWriteError`, row count unchanged | unit | `uv run pytest tests/unit/test_memory_save_fact.py::test_embedder_failure_no_partial -x` | ❌ W0 | ⬜ pending |
| 23-02-03 | 02 | 1 | MEM-02 | T-23-D3 / register_vector | `_get_pool` registers pgvector codec on connect | unit | `uv run pytest tests/unit/test_memory_pool.py::test_register_vector_init -x` | ❌ W0 | ⬜ pending |
| 23-03-01 | 03 | 2 | MEM-03 | T-23-X1 / schema-frozen | `ExtractedFact` is Pydantic V2 frozen + `Literal` category | unit | `uv run pytest tests/unit/test_extractor_schema.py -x` | ❌ W0 | ⬜ pending |
| 23-03-02 | 03 | 2 | MEM-03 | T-23-X2 / cap-N3 | Extractor truncates to ≤ 3 facts ranked by importance | unit | `uv run pytest tests/unit/test_extractor.py::test_truncate_top3 -x` | ❌ W0 | ⬜ pending |
| 23-03-03 | 03 | 2 | MEM-03 | T-23-X3 / bucket-pinning | Every emitted importance ∈ {0.2, 0.5, 0.8} | unit | `uv run pytest tests/unit/test_extractor.py::test_importance_buckets -x` | ❌ W0 | ⬜ pending |
| 23-04-01 | 04 | 2 | MEM-05 | T-23-A1 / refusal-policy | Adversarial fixture set (≥ 8 prompts) → `Extractor.run() == []` | unit | `uv run pytest tests/unit/test_extractor_adversarial.py -x` | ❌ W0 | ⬜ pending |
| 23-04-02 | 04 | 2 | MEM-05 | T-23-A2 / refusal-validation | Pydantic `model_validator` rejects category/importance mismatch | unit | `uv run pytest tests/unit/test_extractor_adversarial.py::test_category_validator -x` | ❌ W0 | ⬜ pending |
| 23-05-01 | 05 | 3 | MEM-04 | T-23-P1 / background-dispatch | Post-turn extractor dispatched via `asyncio.create_task` + `log_task_error` | unit (pipeline) | `uv run pytest tests/unit/test_agent_pipeline_extractor.py::test_post_turn_dispatch -x` | ❌ W0 | ⬜ pending |
| 23-05-02 | 05 | 3 | MEM-04 | T-23-P2 / latency-isolated | Extractor failure does NOT affect user response (p95 delta < 50ms; raises swallowed) | unit | `uv run pytest tests/unit/test_agent_pipeline_extractor.py::test_failure_isolated -x` | ❌ W0 | ⬜ pending |
| 23-05-03 | 05 | 3 | MEM-04 | T-23-P3 / swarm-wired | `SwarmQueryPipeline.run` post-`save_turn` block also dispatches extractor | unit | `uv run pytest tests/unit/test_swarm_pipeline_extractor.py -x` | ❌ W0 | ⬜ pending |
| 23-06-01 | 06 | 3 | MEM-04 | T-23-I1 / e2e-recall-write | Integration: stable preference in user turn → row appears within 2s | integration | `uv run pytest tests/integration/test_extractor_e2e.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_memory_schema.py` — stubs for MEM-01 (DDL replay + HNSW EXPLAIN)
- [ ] `tests/unit/test_memory_save_fact.py` — stubs for MEM-02 (embed-on-write + no-partial-write + register_vector)
- [ ] `tests/unit/test_memory_pool.py` — stubs for `_get_pool` `register_vector` init callback
- [ ] `tests/unit/test_extractor_schema.py` — stubs for `ExtractedFact` Pydantic V2 frozen contract
- [ ] `tests/unit/test_extractor.py` — stubs for cap-N=3 + bucket-pinning
- [ ] `tests/unit/test_extractor_adversarial.py` — adversarial fixture set (policy-shaped, role-redefinition, system-prompt-leak)
- [ ] `tests/unit/test_agent_pipeline_extractor.py` — stubs for `AgentQueryPipeline._persist_turn` extractor dispatch
- [ ] `tests/unit/test_swarm_pipeline_extractor.py` — stubs for `SwarmQueryPipeline.run` extractor dispatch
- [ ] `tests/integration/test_extractor_e2e.py` — async e2e fixture (uses `pgvector` + `BaseLLMClient` mock at consumer path)
- [ ] `tests/conftest.py` — extend with `extractor_llm_mock`, `embedder_mock`, `memory_pool` fixtures (mock at `services.agent.extractor.<dep>` consumer path per v1.3 D-08)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Latency p95 delta < 50ms vs baseline turn (ROADMAP SC-4) | MEM-04 | Real LLM + DB needed; jitter in CI | Run `scripts/bench_extractor_latency.py` locally with real OpenAI/HF embedder; compare `--with-extractor` vs `--baseline` p95 over 100 turns |
| HNSW index actually populated in prod-history tenant (Research Q2) | MEM-01 | Existing-row cost; depends on tenant data | Deploy to staging tenant with > 10k existing facts; observe `CREATE INDEX` runtime; document in OPS log |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (9 stubs above)
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s (unit-quick path)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
