---
phase: 03-error-handling-sweep
plan: "01"
subsystem: async-error-handling
tags:
  - error-handling
  - async
  - background-tasks
  - ERR-02
dependency_graph:
  requires: []
  provides:
    - utils.tasks.log_task_error
  affects:
    - main.py
    - services/events/event_bus.py
tech_stack:
  added: []
  patterns:
    - asyncio done_callback error surfacing
key_files:
  created:
    - utils/tasks.py
    - tests/unit/test_tasks.py
  modified:
    - main.py
    - services/events/event_bus.py
decisions:
  - "Use add_done_callback(log_task_error) rather than try/except around create_task — per D-08/D-09"
  - "log_task_error never re-raises to avoid 'exception never retrieved' loop degradation — per D-08"
  - "Public function name (no leading underscore) for external import — per D-09"
  - "Assign task to named variable before attaching callback for readability"
metrics:
  duration: "~8 minutes"
  completed: "2026-04-24T02:26:45Z"
  tasks_completed: 3
  files_changed: 4
---

# Phase 3 Plan 01: log_task_error Done-Callback Wiring Summary

One-liner: asyncio `log_task_error` done-callback helper created and wired to all 3 `create_task` sites to close ERR-02 silent task exception dropping.

## Commits

| Task | Hash | Description |
|------|------|-------------|
| Task 1 | `95435e6` | feat(03-01): add log_task_error done_callback helper and unit tests |
| Task 2 | `24009f0` | feat(03-01): wire log_task_error callback into main.py auto-scan task |
| Task 3 | `d7645b1` | feat(03-01): wire log_task_error callback into both event_bus.py create_task sites |

## Implemented Files

### utils/tasks.py (new)

Defines `log_task_error(task: asyncio.Task) -> None`:
- Calls `task.exception()` to retrieve any unhandled exception
- Catches `asyncio.CancelledError` and `asyncio.InvalidStateError` silently (returns early)
- Calls `logger.error(...)` with `task_name=task.get_name()` and `exc_info=exc`
- Never re-raises — done_callbacks that raise surface only as a secondary warning

### Updated create_task Sites

| File | Line | Task Name | Callback |
|------|------|-----------|----------|
| `main.py` | 91 | `"auto-knowledge-scan"` | `add_done_callback(log_task_error)` |
| `services/events/event_bus.py` | 132 | `"event-dispatch"` | `add_done_callback(log_task_error)` |
| `services/events/event_bus.py` | 171 | `"event-handler"` | `add_done_callback(log_task_error)` |

## Confirmed grep Counts (Acceptance Criteria)

| Check | Expected | Actual |
|-------|----------|--------|
| `grep -c '^def log_task_error' utils/tasks.py` | 1 | 1 |
| `grep -c 'from utils.logger import logger' utils/tasks.py` | 1 | 1 |
| `grep -c 'asyncio.CancelledError' utils/tasks.py` | 1 | 1 |
| `grep -c '^\s*raise' utils/tasks.py` | 0 | 0 |
| `grep -c 'from utils.tasks import log_task_error' main.py` | 1 | 1 |
| `grep -c 'add_done_callback(log_task_error)' main.py` | 1 | 1 |
| `grep -c 'name="auto-knowledge-scan"' main.py` | 1 | 1 |
| `grep -c 'from utils.tasks import log_task_error' services/events/event_bus.py` | 1 | 1 |
| `grep -c 'add_done_callback(log_task_error)' services/events/event_bus.py` | 2 | 2 |
| `grep -Ec 'name="event-(dispatch\|handler)"' services/events/event_bus.py` | 2 | 2 |
| `grep -c 'def test_' tests/unit/test_tasks.py` | ≥4 | 4 |
| All unit tests pass | yes | 4/4 passed |

## Deviations from Plan

None — plan executed exactly as written.

## Threat Surface Scan

No new network endpoints, auth paths, or file access patterns introduced. The `log_task_error` helper only reads `task.exception()` and `task.get_name()` — no PII serialized from coroutine args (satisfies T-03-02). Silent-drop gap for audit/event dispatch tasks closed (satisfies T-03-01).

## Self-Check

```
[ -f utils/tasks.py ]                        → FOUND
[ -f tests/unit/test_tasks.py ]              → FOUND
git log --oneline | grep 95435e6             → FOUND
git log --oneline | grep 24009f0             → FOUND
git log --oneline | grep d7645b1             → FOUND
pytest tests/unit/test_tasks.py              → 4 passed
```

## Self-Check: PASSED
