---
phase: 23-background-extractor-schema-migration
plan: 05
subsystem: agent-pipeline-integration
tags: [asyncio-create-task, log_task_error, dispatch-wrapper, pipeline-wire-in, log-then-skip, swarm, agent-query, MEM-04]

# Dependency graph
requires:
  - phase: 23-02
    provides: "LongTermMemory.save_fact embed-on-write contract + typed MemoryFactWriteError (consumed inside _run_and_persist where save_fact failure bubbles to log_task_error)."
  - phase: 23-03
    provides: "services/agent/extractor.py — Extractor class + get_extractor() singleton + dispatch_extraction stub (A2 signature: user_turn + ai_turn + user_id + tenant_id) + settings.extractor_enabled flag."
  - phase: 23-04
    provides: "Adversarial fixture proof that Extractor.run returns [] on jailbreak/policy-injection (consumed indirectly — dispatch wrapper trusts the extractor's fail-closed contract)."
provides:
  - "services/agent/extractor.py::dispatch_extraction body — kill-switch + 2 log-then-skip auth gates + asyncio.create_task('extractor') + log_task_error done-callback + lazy _run_and_persist coroutine that iterates extracted facts into LongTermMemory.save_fact."
  - "services/pipeline.py wire-in at TWO sites (AgentQueryPipeline._persist_turn + SwarmQueryPipeline._run_with_state) — both refactor existing save_turn to hoist ConversationTurn locals and pass the SAME instances to both save_turn AND dispatch_extraction (A2 no-parallel-objects contract)."
  - "QueryPipeline.run intentionally NOT wired — verified by anti-wire structural test (CONTEXT D / RESEARCH §Pattern 5)."
affects: [23-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fire-and-forget background task: asyncio.create_task(coro, name=...) + add_done_callback(log_task_error) — verbatim event_bus.py:132-133 pattern."
    - "Hoist-ConversationTurn-then-share pattern: build user_turn + ai_turn into locals, pass the SAME instances to save_turn AND dispatch_extraction to satisfy eng-review A2 no-parallel-objects contract."
    - "Mock-at-consumer-path for pipeline wire-in: patch services.pipeline.dispatch_extraction (the import site), NOT services.agent.extractor.dispatch_extraction (the definition site)."
    - "Structural-fallback test pattern for >50-LOC orchestration methods: inspect.getsource containment check (call shape + relative ordering), deferring real-path verification to integration plan."

key-files:
  created:
    - tests/unit/test_extractor_dispatch.py
    - tests/unit/test_agent_pipeline_extractor.py
    - tests/unit/test_swarm_pipeline_extractor.py
  modified:
    - services/agent/extractor.py
    - services/pipeline.py

key-decisions:
  - "Skip-path ordering: kill-switch FIRST (cheapest), then user_id, then tenant_id. Diagnostic clarity: when both auth fields are missing, user_id reason wins (single source-of-truth for the missing-auth log)."
  - "Pipeline target rebind (deviation Rule 1): wire SwarmQueryPipeline._run_with_state, NOT .run as plan narrative said. .run is a thin dispatcher; the save_turn block at line 1619 actually lives in _run_with_state. Line-number guide was authoritative."
  - "Direct-mock-logger pattern for skip-path assertions (in lieu of caplog plumbing): monkeypatch services.agent.extractor.logger with MagicMock, inspect .info.call_args.kwargs. Simpler than loguru-caplog adapter; no project conftest pattern exists."
  - "Lazy import of get_memory_service inside _run_and_persist — avoids top-level circular (agent.* → memory_service → agent.*)."
  - "Structural fallback for swarm wire-in test (allowed by plan §implementation realism caveat): _run_with_state mocking exceeds 50-LOC fixture budget; integration verification deferred to Plan 23-06."

patterns-established:
  - "dispatch_extraction call shape: kwargs form `dispatch_extraction(user_turn=user_turn, ai_turn=ai_turn, user_id=user_id, tenant_id=tenant_id)` — the grep-gateable canonical wire-in signature."
  - "_run_and_persist body shape: get_extractor() → await .run(user_turn, ai_turn) → early-return on empty → lazy import get_memory_service → for f in facts: await mem._long.save_fact(...) per-fact with positional+kwarg correctness."

metrics:
  duration_minutes: 22
  completed_date: 2026-05-16
  tasks_total: 3
  tasks_completed: 3
  files_created: 3
  files_modified: 2
  commits: 4
  test_count_added: 10
  test_pass_rate: "45/45 (Plans 01-05 sweep, no regression in scope)"
---

# Phase 23 Plan 05: MEM-04 Dispatch Wrapper + Pipeline Wire-in Summary

## One-Liner

Filled `dispatch_extraction` body with kill-switch + auth-precondition skips + `asyncio.create_task` + `log_task_error` done-callback, then wired it into both agent-tier pipelines (`AgentQueryPipeline._persist_turn` + `SwarmQueryPipeline._run_with_state`) using the A2 hoist-ConversationTurn-then-share pattern.

## Commits

| # | Hash | Type | Description |
|---|------|------|-------------|
| 1 | cc6e370 | test | MEM-04 dispatch wrapper RED gates (7 tests) |
| 2 | f533ea4 | feat | MEM-04 dispatch_extraction body — kill-switch + log-then-skip + create_task + log_task_error |
| 3 | 6335959 | test | MEM-04 pipeline wire-in RED gates (3 tests) |
| 4 | 01095e6 | feat | MEM-04 wire dispatch_extraction into AgentQueryPipeline._persist_turn + SwarmQueryPipeline._run_with_state |

## Verification

- **Plan 05 tests (10):** 10/10 GREEN — 7 dispatch + 2 pipeline + 1 anti-wire.
- **Plans 01-05 sweep:** 45/45 GREEN (`test_memory_service.py` + `test_extractor*.py` + Plan 05's three files).
- **Acceptance grep gates:**
  - `grep -c 'dispatch_extraction(' services/pipeline.py` = **2** ✓
  - `grep -c 'user_turn=user_turn, ai_turn=ai_turn' services/pipeline.py` = **2** ✓
  - `grep -n 'add_done_callback(log_task_error)' services/agent/extractor.py` = 1 line ✓
  - `grep -n 'name="extractor"' services/agent/extractor.py` = 1 line ✓
  - All three `reason=` skip-path strings present (`disabled`, `missing_user_id`, `missing_tenant_id`).
- **Structural assertion:** `dispatch_extraction` present in `AgentQueryPipeline._persist_turn` AND `SwarmQueryPipeline._run_with_state`, absent from `QueryPipeline.run`. ✓
- **Lint:** `uv run ruff check services/agent/extractor.py services/pipeline.py` — All checks passed (one pre-existing noqa-format warning at line 1771 — not introduced by Plan 05).
- **Import-cycle check:** `python -c "from services.agent.extractor import dispatch_extraction"` OK (lazy `get_memory_service` import preserves boundary).

## Deviations from Plan

### [Rule 1 - Plan-narrative bug] SwarmQueryPipeline wire-in target rebound

- **Found during:** Task 3 STEP B (writing the swarm wire-in edit).
- **Issue:** Plan narrative said "SwarmQueryPipeline.run post-save_turn block (~line 1619–1626)". On the working tree, `SwarmQueryPipeline.run` (line 1698) is a 25-LOC dispatcher that delegates to `_run_with_state` (line 1463). The `save_turn` block at line 1619 actually lives inside `_run_with_state`. The line-number guide was correct; the method name was stale.
- **Fix:** Wired `_run_with_state` (which `run` invokes for N>1) and updated `test_swarm_pipeline_extractor.py` to inspect `_run_with_state.__doc__/source` instead of `run`. Test docstring documents the rebind explicitly so future readers see the discrepancy.
- **Files modified:** `services/pipeline.py:1618-1646`, `tests/unit/test_swarm_pipeline_extractor.py:1-22,33-35`.
- **Commits:** 6335959, 01095e6.

### [Rule 1 - Test fixture bug] RetrievedChunk MagicMock → real Pydantic instances

- **Found during:** Task 3 first GREEN run (`test_persist_turn_dispatches_extractor`).
- **Issue:** Initial test used `MagicMock(doc_id="d1")` for `all_chunks`. Pipeline's downstream `GenerationResponse` construction validates `sources` against `RetrievedChunk` (Pydantic V2 model_type) and rejects MagicMocks.
- **Fix:** Added a `_chunk(doc_id) -> RetrievedChunk` helper that constructs real Pydantic instances with `ChunkMetadata`. The mock-at-the-boundary still holds; only the typed-container fixture changed.
- **Commit:** 01095e6.

### [Cosmetic] dispatch_extraction kwarg formatting

- The plan acceptance gate required `grep 'user_turn=user_turn, ai_turn=ai_turn'` to match — initial multi-line formatting put each kwarg on its own line. Reformatted both dispatch sites to single-line `user_turn=user_turn, ai_turn=ai_turn,` to satisfy the literal grep gate without changing semantics.

## Auth Gates

None. No new credentials, env vars, or external services touched.

## Deferred Issues

- 32 pre-existing `test_pipeline_coverage.py` failures (Redis-localhost-required tests) — diff vs. baseline shows ZERO new failures introduced by Plan 05. Out of scope.
- One pre-existing noqa-format ruff warning at `services/pipeline.py:1771` (a `# noqa-typing:` comment not matching ruff's `# noqa:` format). Pre-existing; not in Plan 05's modified region.

## Threat Mitigations Applied

| Threat ID | Disposition | Mitigation in this plan |
|-----------|-------------|------------------------|
| T-23-05-A1 | mitigate | Empty-string `tenant_id` rejected via explicit `if not tenant_id` check. `test_dispatch_skips_on_missing_tenant_id` covers both `""` and `None`. |
| T-23-05-D1 | mitigate | `dispatch_extraction` returns synchronously. `_run_and_persist` runs on the event loop without await-in-caller. `test_dispatch_extraction_failure_isolated` verifies a raising extractor never re-raises into the caller. |
| T-23-05-D2 | mitigate | Multi-fact partial-write acceptable by design (each fact = single row; Plan 02 zero-partial-write is per-row). Failure of fact N propagates to `log_task_error` for ops review; facts 0..N-1 already committed. |
| T-23-05-R1 | mitigate | `log_task_error` callback fires on every task completion (success or failure). Three skip paths emit structured logs with `operation="extractor_skipped"`. |

## Self-Check: PASSED

- `[ -f tests/unit/test_extractor_dispatch.py ]` → FOUND
- `[ -f tests/unit/test_agent_pipeline_extractor.py ]` → FOUND
- `[ -f tests/unit/test_swarm_pipeline_extractor.py ]` → FOUND
- `git log --oneline | grep cc6e370` → FOUND
- `git log --oneline | grep f533ea4` → FOUND
- `git log --oneline | grep 6335959` → FOUND
- `git log --oneline | grep 01095e6` → FOUND
- All grep-gateable claims (`dispatch_extraction(` count, A2 kwarg form count, callback wiring) verified above.
