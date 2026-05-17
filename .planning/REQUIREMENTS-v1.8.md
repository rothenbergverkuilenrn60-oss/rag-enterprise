# EnterpriseRAG — v1.8 Backlog Requirements (Scaffold)

**Milestone:** v1.8 (not yet opened)
**Goal:** TBD — set at v1.8 milestone discussion. Pre-seeded from v1.7 deferred items.
**Opened:** TBD (after v1.7 ships)
**Phase numbering:** Continues from v1.7 (last phase = 28); v1.8 will start at **Phase 29**.

This file is a **scaffold** — it locks the categorized ID schema and pre-seeds 7 items surfaced during v1.7 execution + verification. Additional items will be appended by `gsd-new-milestone` or grooming sessions. Implementation = v1.8 phases.

## Categorized ID Schema (locked per v1.7 D-06)

| Prefix | Category | Description |
|--------|----------|-------------|
| `SK-` | Silent-skip enforcement | Promote v1.7 audit-mode near-duplicate guards to silent-skip |
| `TOC-` | TOCTOU mitigation | Close race windows between precheck SELECT and INSERT |
| `OAI-` | openai SDK signature drift | Cleanup of openai SDK API surface drift exposing latent test failures |
| `EVT-` | Event-loop singleton leaks | Fix module-level singletons constructed under stale event loops (TD-02-style) |
| `MYPY-` | mypy --strict cleanup | Resolve accumulated pre-existing mypy --strict violations |
| `TEST-INFRA-` | Test infra fixes | Test fixture ordering, mock patterns, embedder lifecycle |

## Active Requirements (v1.8)

All requirements are scoped to this milestone. Phase assignments filled after v1.8 milestone opens.

### Silent-Skip Enforcement

- [ ] **SK-01**: Silent-skip near-duplicate enforcement for `save_fact` + `save_facts` batch path. v1.7 ships audit-mode (D-09: `MEMORY_NEAR_DUPLICATE_SKIPPED` audit row emitted AND `executemany` inserts all rows including dups). v1.8 promotes to silent skip — duplicates do NOT INSERT; only the audit row remains.
  - **Owner:** TBD — assigned at v1.8 grooming.
  - **Blocker:** Depends on **TOC-01** (must close TOCTOU race window before silent-skip becomes safe in concurrent writers).
  - **When:** v1.8 (first phase after milestone open).
  - **Acceptance:** When `_is_near_duplicate` returns `True` for a candidate, the candidate is NOT included in `rows_to_insert`; `executemany` inserts only non-duplicate rows; `MEMORY_NEAR_DUPLICATE_SKIPPED` audit row still emitted with original action shape. Unit test `test_dedupe_in_batch_fires_audit_AND_executemany_inserts_all_rows` (v1.7 pin per 27-VERIFICATION.md C3) must flip to `..._inserts_non_dup_rows_only` form. `save_fact` wrapper (D-12) inherits behavior via delegation.

### TOCTOU Mitigation

- [ ] **TOC-01**: Close TOCTOU race window between precheck SELECT and INSERT in `LongTermMemory.save_facts`. v1.7 cosine precheck runs as a separate SELECT before `executemany`; a concurrent writer can insert a duplicate between SELECT and INSERT, defeating the dedupe guarantee. v1.8 mitigates via either (a) `INSERT ... ON CONFLICT DO NOTHING` on a unique constraint over normalized `(user_id, tenant_id, embedding_hash)`, or (b) advisory-lock per `(user_id, tenant_id)` around the precheck+insert atomic block, or (c) `WITH ... SELECT ... INSERT ... RETURNING` in a single round-trip. Choice locked at v1.8 discussion.
  - **Owner:** TBD — assigned at v1.8 grooming.
  - **Blocker:** None (independent design decision; **SK-01** depends on this).
  - **When:** v1.8 (must ship before or with SK-01).
  - **Acceptance:** Concurrent integration test: 2 parallel `save_facts` writers, same `(user_id, tenant_id)`, same fact text — exactly 1 row in `long_term_facts`; either 1 or 2 `MEMORY_NEAR_DUPLICATE_SKIPPED` audit rows (depending on race interleaving, both interpretations acceptable as long as no duplicate row survives).

### openai SDK Drift Cleanup

- [ ] **OAI-01**: Fix 32 pre-existing unit-test failures stemming from openai SDK signature drift. Symptom: `APIError.__init__() missing 1 required positional argument: 'request'`. Affected files: `tests/unit/test_agent_pipeline_refactor.py` (11), `tests/unit/test_agent_sse.py` (9), `tests/unit/test_pipeline_coverage.py` (10), `tests/unit/test_feedback_ab_forward.py` (1), `tests/unit/test_memory_controller.py`, `tests/unit/test_recall_tool.py`. Has been latent on master since v1.5; lint gate masked it. Surfaced by Phase 26 PR #9 CI (run 25981918166 — first run where lint passed and unit tests actually executed). NOT introduced by Phase 26 — this is pre-existing.
  - **Owner:** TBD — assigned at v1.8 grooming.
  - **Blocker:** None.
  - **When:** v1.8 (high-value cleanup; unblocks CI gate tightening).
  - **Acceptance:** All 32 enumerated tests pass; new openai SDK `APIError` construction shape (with `request` arg) used throughout test fixtures. CI run on master post-fix shows `pytest tests/unit/ -m 'not benchmark'` green. No production-code changes (test-only fix unless test mirrors a production codepath).

### Event-Loop Singleton Leaks

- [ ] **EVT-01**: Fix +14 module-level singleton leaks newly exposed by Phase 27-02 `@pytest.mark.uses_redis` marker rollout. Symptom: integration tests fail with "There is no current event loop in thread 'MainThread'" after the marker auto-applies the `redis_mock` fixture. Diagnosis: singletons constructed under a stale loop survive into the next test's loop. Same root cause as TD-02 (which fixed app + main singleton); EVT-01 extends the fix to the +14 newly-exposed singletons. Pattern: use `create_app()` factory from `tests/factories/app.py` (Phase 27 SC-1 evidence).
  - **Owner:** TBD — assigned at v1.8 grooming.
  - **Blocker:** None (pattern source — Phase 27 SC-1 — already shipped).
  - **When:** v1.8 (first phase after milestone open; bundle with TD-02 carry-over).
  - **Acceptance:** Each of the +14 leak sites (enumerate during v1.8 discussion via `pytest tests/integration/ -v 2>&1 | grep "no current event loop" | sort -u`) either migrates to the `create_app()` factory pattern or adds an explicit per-test loop fixture. Marker rollout (`@pytest.mark.uses_redis`) does not introduce regressions in integration suite. Curated `_SINGLETON_INVENTORY` in `tests/factories/app.py` (v1.7 had 34 entries) grows to cover the +14.

### mypy --strict Cleanup

- [ ] **MYPY-01**: Resolve `config/settings.py:154` mypy --strict violation: `embedding_ensemble: list[dict] = []` is missing parametric type annotation. Fix: `embedding_ensemble: list[dict[str, Any]] = []` (or a more specific Pydantic V2 sub-model if upstream consumers permit). Surface scan during v1.7 may reveal additional accumulated pre-existing mypy --strict violations; bundle into this item or split per file.
  - **Owner:** TBD — assigned at v1.8 grooming.
  - **Blocker:** None.
  - **When:** v1.8 (low-cost cleanup; can be done in any phase).
  - **Acceptance:** `uv run mypy --strict config/settings.py` returns "Success: no issues found in 1 source file"; any additional mypy --strict violations surfaced by a full-repo scan are either fixed or explicitly silenced with `# type: ignore[error-code]` + comment justifying.

### Test Infra Fixes

- [ ] **TEST-INFRA-01**: Fix `tests/integration/test_extractor_e2e.py` `FileNotFoundError: Path /tmp/embedding_models/bge-m3 not found`. Root cause: `embedder_or_mock` fixture monkeypatch reaches the consumer AFTER `AgentQueryPipeline.__init__` calls `get_embedder()` → `HuggingFaceEmbedder.__init__` raises before test body. Three candidate fixes: (a) move `embedder_or_mock` patch earlier in pipeline construction, (b) pre-download bge-m3 model in CI fixtures, (c) mock `services.vectorizer.embedder.HuggingFaceEmbedder.__init__` directly. Pre-existing bug (would fail on v1.6 master tip in same env); not v1.7-caused.
  - **Owner:** TBD — assigned at v1.8 grooming.
  - **Blocker:** None.
  - **When:** v1.8 (closes a known-flaky integration test).
  - **Acceptance:** `uv run pytest tests/integration/test_extractor_e2e.py -v` passes on a clean checkout without manual bge-m3 pre-download (option a or c chosen) OR with documented CI pre-download step (option b). Fix path documented in plan SUMMARY.

- [ ] **TEST-INFRA-02**: Rewrite `save_facts` precheck unit tests to use the bulk-SELECT mock pattern with `nearest_distance=None` handling. v1.7 ships a per-fact test pattern that does NOT exercise the C1 bulk SQL shape directly. v1.8 rewrites approximately 150 lines per affected test file to assert against the bulk-SELECT shape with `nearest_distance=None` for the no-existing-rows branch.
  - **Owner:** TBD — assigned at v1.8 grooming.
  - **Blocker:** None.
  - **When:** v1.8 (test refactor; can be done in same phase as SK-01 since it touches the same code paths).
  - **Acceptance:** Tests assert the C1 SQL shape (`unnest($1::text[]) WITH ORDINALITY` + `vec_txt::vector` cast); `nearest_distance=None` branch covered explicitly; per-file LOC delta ≤ +150; no production-code changes.

## Out of Scope (deferred to v1.9+ or rejected)

(Empty placeholder — populated at v1.8 milestone open.)

## Future Requirements (post-v1.8 candidates surfaced during this milestone)

(Empty placeholder — populated during v1.8 execution.)

## Traceability

| REQ-ID | Title | Phase |
|--------|-------|-------|
| SK-01 | Silent-skip near-duplicate enforcement | TBD (v1.8) |
| TOC-01 | TOCTOU mitigation | TBD (v1.8) |
| OAI-01 | openai SDK signature drift cleanup | TBD (v1.8) |
| EVT-01 | Event-loop singleton leaks (+14 sites) | TBD (v1.8) |
| MYPY-01 | mypy --strict cleanup (config/settings.py:154 + sweep) | TBD (v1.8) |
| TEST-INFRA-01 | extractor_e2e embedder fixture ordering | TBD (v1.8) |
| TEST-INFRA-02 | save_facts precheck test rewrite (bulk-SELECT mock + nearest_distance=None) | TBD (v1.8) |

**Coverage check:** 7/7 requirements mapped; phase assignments TBD at v1.8 open.

---
*Last updated: 2026-05-17 — v1.7 Phase 28 plan 28-03 scaffold; phase assignments TBD at v1.8 open.*
