---
phase: 24-pgvector-recalltool-semantic-recall-rewrite
plan: "01"
subsystem: agent-tools
tags: [settings, kill-switch, recall_tool_enabled, recall-tool-stub, classvars, base-tool, pydantic-v2, tdd]

# Dependency graph
requires: []
provides:
  - "recall_tool_enabled: bool = True field in config/settings.py (MEM-09 / D-B4 kill-switch)"
  - "RecallTool(BaseTool) stub in services/agent/tools/recall.py with 3 required ClassVars (MEM-08)"
  - "_RECALL_PARAMETERS_SCHEMA and _EMPTY_MARKER module constants as single sources of truth"
affects:
  - "24-03 — replaces recall.py stub run() body and adds @register decorator"
  - "24-04 — consumes recall_tool_enabled in services/agent/tools/__init__.py conditional import"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED/GREEN cycle: test-only commit (test(24-01)) followed by implementation commit (feat(24-01))"
    - "Module-level _*_PARAMETERS_SCHEMA constant as single source of truth for JSON Schema"
    - "Pydantic V2 BaseSettings bool field with auto env-var binding (RECALL_TOOL_ENABLED)"
    - "Stub run() returning _EMPTY_MARKER (not is_error) to unblock type-surface testing without Plan 02 dependency"
    - "No @get_tool_registry().register on stub — deferred to Plan 03 after real run body lands"

key-files:
  created:
    - "tests/unit/test_settings_recall_kill_switch.py — 3 presence tests: settings field default, Pydantic type introspection, RecallTool ClassVar shape"
    - "services/agent/tools/recall.py — RecallTool(BaseTool) stub with name/description/parameters_schema ClassVars + placeholder run()"
  modified:
    - "config/settings.py — appended recall_tool_enabled: bool = True field after Prometheus section"

key-decisions:
  - "Insertion point for recall_tool_enabled is after metrics_path field (end of Prometheus section), not after extractor_provider — extractor block does not exist in this worktree"
  - "No @get_tool_registry().register decorator on stub in Plan 01 — registration is a Plan 03 responsibility after real run body lands"
  - "Docstring references to @get_tool_registry removed to satisfy grep acceptance criterion (grep -v '^#' counts docstring lines)"
  - "_EMPTY_MARKER constant defined in Plan 01 for Plan 03 reuse (D-C2 single source of truth)"

patterns-established:
  - "Pattern: kill-switch field appended at end of last settings section, before @field_validator methods"
  - "Pattern: stub run() returns ToolResult(content=_EMPTY_MARKER, metadata={'stub': True}) — not is_error, exercising type surface cleanly"
  - "Pattern: all service imports inside test bodies (not module top) so pytest --collect-only succeeds before implementation lands"

requirements-completed: [MEM-08, MEM-09]

# Metrics
duration: 15min
completed: 2026-05-16
---

# Phase 24 Plan 01: Settings Kill-Switch + RecallTool Stub Summary

**recall_tool_enabled Pydantic V2 bool field + RecallTool(BaseTool) stub with D-C4 description and MEM-08 parameters_schema ClassVars, not yet registered (deferred to Plan 03)**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-05-16T00:00:00Z
- **Completed:** 2026-05-16
- **Tasks:** 2 (TDD RED + GREEN)
- **Files modified:** 3

## Accomplishments

- Created 3-test RED gate file with env-var pattern; all 3 fail on unmodified tree (AttributeError + ImportError)
- Appended `recall_tool_enabled: bool = True` to config/settings.py after Prometheus section
- Created services/agent/tools/recall.py: RecallTool stub with 3 mandatory ClassVars satisfying BaseTool.__init_subclass__ enforcement
- All 3 RED gates flip GREEN; ruff clean; 0 mypy errors on recall.py; stub absent from registry

## Task Commits

1. **Task 1: RED — settings field + RecallTool stub presence tests** - `00e78de` (test)
2. **Task 2: GREEN — append recall_tool_enabled field + create RecallTool stub** - `0329431` (feat)

## Acceptance Criteria Met

- `uv run pytest tests/unit/test_settings_recall_kill_switch.py -x -q` exits 0 (3 GREEN)
- `settings.recall_tool_enabled is True` confirmed
- `issubclass(RecallTool, BaseTool)` confirmed
- `grep -n 'recall_tool_enabled: bool = True' config/settings.py` — 1 match at line 418
- `grep '@get_tool_registry' services/agent/tools/recall.py` — 0 matches
- `wc -l services/agent/tools/recall.py` — 61 lines (within 30-80 bound)
- `uv run ruff check config/settings.py services/agent/tools/recall.py` — All checks passed
- `'recall_memory' not in get_tool_registry().list()` — confirmed (stub not decorated)

## Files Created/Modified

- `/config/settings.py` — appended `recall_tool_enabled: bool = True` with D-B4 comment block
- `/services/agent/tools/recall.py` — RecallTool stub (61 LOC): 3 ClassVars + placeholder run()
- `/tests/unit/test_settings_recall_kill_switch.py` — 3 presence/type tests (TDD RED gate file)

## Decisions Made

- Insertion point: after `metrics_path` field (end of Prometheus section), not after `extractor_provider` — the extractor block referenced in plan does not exist in this worktree (deviation: auto-fixed insertion point)
- Removed `@get_tool_registry` text from docstring to satisfy grep acceptance criterion (docstring lines are not `^#`-prefixed so grep -v '^#' counts them)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Insertion point adjusted: extractor block absent from worktree**
- **Found during:** Task 2 (config/settings.py edit)
- **Issue:** Plan specified inserting after `extractor_provider` at line 302. That field does not exist in this worktree (no Phase 23 extractor block). The plan was written against a different state.
- **Fix:** Inserted `recall_tool_enabled` after `metrics_path` (the last settings field before `@field_validator`), which is semantically equivalent — a new section at end of fields.
- **Files modified:** config/settings.py
- **Verification:** `grep -n 'recall_tool_enabled: bool = True' config/settings.py` matches exactly 1 line; ruff clean; all 3 tests GREEN.
- **Committed in:** `0329431` (Task 2 commit)

**2. [Rule 1 - Bug] Removed @get_tool_registry text from module docstring**
- **Found during:** Task 2 acceptance criteria verification
- **Issue:** Docstring mentioned `@get_tool_registry().register decorator` in plain text. `grep -v '^#'` does not strip docstring lines, so the acceptance criterion `grep -v '^#' services/agent/tools/recall.py | grep -c '@get_tool_registry' equals 0` would fail.
- **Fix:** Rewrote docstring sentences to reference "registration decorator" without the literal `@get_tool_registry` symbol.
- **Files modified:** services/agent/tools/recall.py
- **Verification:** `grep '@get_tool_registry' services/agent/tools/recall.py` returns 0 matches.
- **Committed in:** `0329431` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 — factual mismatch between plan and worktree state)
**Impact on plan:** No scope change. Both fixes preserve plan intent exactly.

## Issues Encountered

None beyond the two auto-fixed deviations above.

## Next Plan Reference

**Plan 24-03** builds directly on this stub:
- Replaces `recall.py` stub `run()` body with the real pgvector cosine-similarity implementation
- Adds `@get_tool_registry().register` decorator to RecallTool
- Imports `get_memory_service`, `asyncpg`, `loguru.logger` (deferred from Plan 01 per scope boundary)

**Plan 24-04** consumes `recall_tool_enabled`:
- Adds conditional import `if settings.recall_tool_enabled: from services.agent.tools.recall import RecallTool` to `services/agent/tools/__init__.py`
- Adds kill-switch behavioral tests (importlib.reload + registry list assertions)

## User Setup Required

None - no external service configuration required.

---
*Phase: 24-pgvector-recalltool-semantic-recall-rewrite*
*Completed: 2026-05-16*
