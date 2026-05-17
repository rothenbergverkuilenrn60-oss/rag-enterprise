---
phase: 24-pgvector-recalltool-semantic-recall-rewrite
plan: "04"
subsystem: agent-tool-allowlist
requirements: [MEM-09]
tags: [conditional-registration, kill-switch, allowlist, planner-pick, importlib-reload, real-llm-marker, pgvector]

dependency_graph:
  requires:
    - 24-01  # settings.recall_tool_enabled field + recall.py stub
    - 24-03  # RecallTool.run body + @register decorator
  provides:
    - recall_memory visible to planner LLM via AGENT_TOOL_ALLOWLIST (length 4)
    - conditional registration kill-switch via __init__.py guard
    - real_llm pytest marker for SC-2 pre-tag gate
  affects:
    - services/agent/tools/__init__.py
    - services/pipeline.py
    - pytest.ini

tech_stack:
  added: []
  patterns:
    - D-B4 Pattern 3 — conditional registration via if settings.recall_tool_enabled
    - importlib.reload + sys.modules save/restore for kill-switch test isolation
    - pytest.mark.real_llm file-level marker for SC-2 pre-tag gate (T7)
    - W3 file split: planner-pick (real_llm) vs e2e (no real_llm)

key_files:
  created:
    - tests/integration/test_recall_tool_planner_pick.py
    - tests/integration/test_recall_tool_e2e.py
  modified:
    - tests/unit/test_settings_recall_kill_switch.py
    - services/agent/tools/__init__.py
    - services/pipeline.py
    - pytest.ini

decisions:
  - D-B4 Pattern 3 — conditional registration (not allowlist filter) gates planner visibility
  - T6 (Decision-8) — sys.modules save/restore required for correct kill-switch test isolation
  - T7 (Decision-7) — real_llm marker file-scoped to planner_pick; e2e has no real_llm marker (W3)
  - T11 — allowlist invariant tested across both toggle states (not tautology)

metrics:
  duration: "~15 minutes"
  tasks_completed: 3
  files_modified: 6
  completed_date: "2026-05-16"
---

# Phase 24 Plan 04: RecallTool Wiring + Kill-Switch Tests Summary

Conditional registration of RecallTool in `__init__.py` + allowlist growth 3→4 via `AGENT_TOOL_ALLOWLIST` in `pipeline.py`. Real-LLM planner-pick tests (T7) + tool-body e2e test (W3 split) + `real_llm` pytest marker registered.

## What Was Built

**Production edits (2 files):**

1. `services/agent/tools/__init__.py` — added `from config.settings import settings` (first import) + conditional `if settings.recall_tool_enabled: from services.agent.tools.recall import RecallTool # noqa: F401` block per D-B4 Pattern 3. `__all__` unchanged (RecallTool not exported — consumers use registry).

2. `services/pipeline.py:744` — `AGENT_TOOL_ALLOWLIST` grown from 3 to 4 entries with `"recall_memory"` appended. List stays length 4 regardless of toggle (D-B4 invariant). Comment block updated with Phase 24 / MEM-09 context.

**Test files (3 files):**

3. `tests/unit/test_settings_recall_kill_switch.py` — extended from 3 (Plan 01) to 8 tests. 5 new kill-switch tests using `_reset_registry_and_reimport` helper with T6 fix (sys.modules save/restore pattern) and T11 both-toggle-state invariant test.

4. `tests/integration/test_recall_tool_planner_pick.py` — 2 tests with `pytest.mark.real_llm` file-level marker (T7 / Decision-7): planner picks recall_memory ≥4/5 trials for preference query; planner skips 0/5 for arithmetic query.

5. `tests/integration/test_recall_tool_e2e.py` — 1 test without real_llm marker (W3 fix): RecallTool.run() body against real PG asserts seeded "React" fact returned.

**Config (1 file):**

6. `pytest.ini` — `real_llm` marker registered for nightly / pre-tag selective runs.

## Commits

| Hash | Message |
|------|---------|
| `e895023` | test(24-04): RED gates for conditional registration + planner-pick split (MEM-09, T6+T7+T11+W3) |
| `07d24e0` | feat(24-04): MEM-09 wire RecallTool — conditional registration + allowlist 3→4 |
| `9dd03af` | chore(24-04): register pytest real_llm marker for SC-2 pre-tag gate (T7) |
| `688f745` | fix(24-04): fix sys.modules state leak in kill-switch helper (Rule 1 — registry contamination) |

## Green Counts

- Unit: 38/38 pass (8 kill-switch + 17 recall_tool + 13 memory_recall_semantic)
- Integration: SKIP (PG unavailable in execution environment — Phase 23 precedent)
- Ruff: 0 new violations on modified files

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] sys.modules state leak caused double-registration in cross-file test runs**

- **Found during:** Task 2 GREEN gate — `test_recall_tool_registered_once` failed with `ValueError: Tool 'recall_memory' already registered` when run after kill-switch tests.
- **Issue:** `sys.modules.pop("services.agent.tools.recall", None)` in `_reset_registry_and_reimport` removed the module from cache. On monkeypatch teardown, `_registry` was restored to the pre-test singleton (which already had recall_memory). The next `import services.agent.tools.recall` re-ran `@register` on this already-populated registry → ValueError.
- **Fix:** Changed to save/restore pattern: capture `_prior_recall_mod = sys.modules.pop(...)` before reload, then `sys.modules.setdefault("services.agent.tools.recall", _prior_recall_mod)` after reload. This ensures sys.modules points to the original (pre-test) module object after each test, making subsequent imports no-ops.
- **T6 constraint preserved:** The pop still happens before reload (so the reload actually re-evaluates the conditional import), but the prior module is restored after so the registry-singleton restore on teardown stays consistent.
- **Files modified:** `tests/unit/test_settings_recall_kill_switch.py`
- **Commit:** `688f745`

## Known Stubs

None — no stubs in modified production files. Integration tests skip gracefully when PG unavailable.

## Threat Flags

No new trust boundaries introduced. AGENT_TOOL_ALLOWLIST is a static list literal (no runtime mutation). Registration path is single-file (no secondary import of recall.py confirmed).

## Self-Check: PASSED

- `tests/unit/test_settings_recall_kill_switch.py` — 8 tests GREEN
- `tests/integration/test_recall_tool_planner_pick.py` — 2 tests SKIP (no PG)
- `tests/integration/test_recall_tool_e2e.py` — 1 test SKIP (no PG)
- `services/agent/tools/__init__.py` — conditional import present
- `services/pipeline.py` — AGENT_TOOL_ALLOWLIST length 4 with "recall_memory"
- `pytest.ini` — real_llm marker registered
- Commits: e895023, 07d24e0, 9dd03af, 688f745 — all exist in git log
