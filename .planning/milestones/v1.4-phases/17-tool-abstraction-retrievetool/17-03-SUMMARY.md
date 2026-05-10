---
phase: 17-tool-abstraction-retrievetool
plan: 03
subsystem: agent-runtime
tags: [seam-swap, tool-registry, cleanup, AGENT-07]
dependency_graph:
  requires: [17-01, 17-02]
  provides: [AGENT-07-closed, tool-registry-active, tool_executor-deleted]
  affects: [services/agent/executor.py, services/pipeline.py, services/agent/__init__.py]
tech_stack:
  added: []
  patterns: [registry-dispatch, consumer-path-mock, ToolResult-return-type]
key_files:
  created: [docs/agent-architecture.md]
  modified:
    - services/agent/executor.py
    - services/agent/__init__.py
    - services/pipeline.py
    - tests/unit/test_executor.py
    - tests/unit/test_agent_parity.py
    - tests/unit/test_agent_pipeline_refactor.py
    - tests/unit/test_swarm_pipeline.py
  deleted: [services/agent/tool_executor.py]
decisions:
  - "SwarmQueryPipeline._run_sub_agent also switches from AgentQueryPipeline._AGENT_TOOLS to registry.schemas_for() — necessary because _AGENT_TOOLS was deleted (Rule 3 auto-fix)"
  - "test_agent_pipeline_refactor.py + test_swarm_pipeline.py mock fixtures gain provider_name='anthropic' on _llm — MagicMock attribute is not a string, schemas_for() raises ValueError (Rule 1 auto-fix)"
  - "test_agent_parity.py updated with _make_fake_tool_cls registry factory pattern consistent with test_executor.py"
metrics:
  duration_minutes: 15
  completed_date: "2026-05-09"
  tasks_completed: 7
  files_changed: 9
---

# Phase 17 Plan 03: Seam Swap to ToolRegistry + Delete tool_executor.py + Docs Stub (Wave 3) Summary

Wave 3 completed the AGENT-07 seam swap: `Executor._dispatch_one` now routes through `get_tool_registry().get(name).run(args, ctx)`; `_AGENT_TOOLS` literal is gone from `pipeline.py`; `services/agent/tool_executor.py` is deleted; `docs/agent-architecture.md#authoring-tools` exists with one runnable example. All 729 baseline unit tests pass with 0 regressions.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| T1 | Swap Executor._dispatch_one to registry | ac23340 | services/agent/executor.py |
| T2 | Update test_executor.py for registry mock + ToolResult | 6c343ce | tests/unit/test_executor.py |
| T3 | Pipeline edits — _AGENT_TOOLS→AGENT_TOOL_ALLOWLIST, swarm import | fd6cb5a | services/pipeline.py |
| T4 | Update __init__.py + delete tool_executor.py | 243f358 | services/agent/__init__.py, services/agent/tool_executor.py (deleted) |
| T5 | Update agent_pipeline_refactor + swarm pipeline test fixtures | 988f890 | test_agent_pipeline_refactor.py, test_swarm_pipeline.py |
| T5b | Update test_agent_parity.py parity tests | 7d4beeb | tests/unit/test_agent_parity.py |
| T6 | Create docs/agent-architecture.md#authoring-tools stub | 8291ce8 | docs/agent-architecture.md |
| T7 | Final integration sweep | ed9bc67 | (verification only) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] SwarmQueryPipeline._run_sub_agent referenced AgentQueryPipeline._AGENT_TOOLS**
- **Found during:** T3
- **Issue:** Line 945 in pipeline.py called `tools=AgentQueryPipeline._AGENT_TOOLS` inside SwarmQueryPipeline._run_sub_agent. When `_AGENT_TOOLS` was deleted, this would raise AttributeError at runtime.
- **Fix:** Updated to `tools=get_tool_registry().schemas_for(self._llm.provider_name, names=AGENT_TOOL_ALLOWLIST)` — semantically identical since registry output is byte-identical to the deleted literal (proven in Phase 17-02 Test 16).
- **Files modified:** services/pipeline.py
- **Commit:** fd6cb5a

**2. [Rule 1 - Bug] MagicMock._llm.provider_name not set — schemas_for() raised ValueError**
- **Found during:** T5
- **Issue:** `test_agent_pipeline_refactor.py` and `test_swarm_pipeline.py` mock fixtures created `pipe._llm = MagicMock()` without setting `provider_name`. When `AgentQueryPipeline.run` called `get_tool_registry().schemas_for(self._llm.provider_name, ...)`, the MagicMock attribute (not a string) caused `ValueError: Unknown provider: <MagicMock ...>`.
- **Fix:** Added `pipe._llm.provider_name = "anthropic"` to both fixtures.
- **Files modified:** tests/unit/test_agent_pipeline_refactor.py, tests/unit/test_swarm_pipeline.py
- **Commit:** 988f890

**3. [Rule 1 - Bug] test_agent_parity.py still patched services.agent.executor.execute_tool_call**
- **Found during:** T7 (full suite run)
- **Issue:** The parity tests monkeypatched `services.agent.executor.execute_tool_call` which no longer exists in executor.py (T1 deleted that import), causing `AttributeError`.
- **Fix:** Updated to `_make_fake_tool_cls` factory pattern using `get_tool_registry` mock — same consumer-path convention as test_executor.py. Assertions updated to `isinstance(r, ToolResult)` + dispatch count check.
- **Files modified:** tests/unit/test_agent_parity.py
- **Commit:** 7d4beeb

## Grep Evidence (ROADMAP SC1-5 + Phase 16 Carry-forward)

```
# SC1: BaseTool ABC declared
grep -nE "class BaseTool\(abc\.ABC\)" services/agent/tools/base.py
→ 24:class BaseTool(abc.ABC):   [1 match ✓]

# SC2: RetrieveTool wraps retrieval
grep -nE "class RetrieveTool\(BaseTool\)" services/agent/tools/retrieve.py
→ 146:class RetrieveTool(BaseTool):   [1 match ✓]

# SC3: WebSearchTool registered
grep -nE "class WebSearchTool\(BaseTool\)" services/agent/tools/web_search.py
→ 35:class WebSearchTool(BaseTool):   [1 match ✓]

# SC4: executor.py + pipeline.py tool-class-import-free
grep -rnE "import RetrieveTool|import RefinedRetrieveTool|import WebSearchTool" services/pipeline.py services/agent/executor.py
→ 0 matches ✓

# SC5: docs/agent-architecture.md#authoring-tools exists
grep -nE "## Authoring Tools" docs/agent-architecture.md
→ 7:## Authoring Tools   [1 match ✓]

# tool_executor.py deleted
ls services/agent/tool_executor.py → No such file ✓

# No straggler imports
grep -rnE "from services\.agent\.tool_executor" services/ tests/ → 0 matches ✓

# _execute_tool_call def count (Phase 16 carry-forward)
grep -rnE "def _execute_tool_call" services/ → 0 matches ✓

# _AGENT_TOOLS deleted
grep -n "_AGENT_TOOLS" services/pipeline.py → 0 matches ✓

# AGENT_TOOL_ALLOWLIST present
grep -n "AGENT_TOOL_ALLOWLIST" services/pipeline.py
→ 590: declaration, 781: AgentQueryPipeline.run callsite, 933: SwarmQueryPipeline callsite   [3 matches ✓]

# _AGENT_SYSTEM preserved
grep -n "_AGENT_SYSTEM" services/pipeline.py
→ 609: declaration, 783: AgentQueryPipeline callsite, 935: SwarmQueryPipeline callsite   [3 matches ✓]

# IntentRouter (NLU-03 carry-forward — must be 0)
grep -n "class IntentRouter" services/ tests/ utils/ → 0 matches ✓
```

## Test Results

```
pytest tests/unit -q
→ 729 passed, 1 skipped, 310 warnings (0 regressions vs Phase 16 baseline)

coverage report --fail-under=70
→ TOTAL 72.6% ✓

ruff check services/ tests/
→ Ruff: No issues found ✓

mypy --strict services/agent/ services/pipeline.py utils/models.py services/generator/llm_client.py
→ mypy: No issues found (0 new errors) ✓
```

## End-to-End Smoke Test

```python
from services.agent import BaseTool, Executor, Planner, get_tool_registry
r = get_tool_registry()
assert sorted(r.list()) == ['refine_search', 'search_knowledge_base', 'web_search']
anth = r.schemas_for('anthropic', names=['search_knowledge_base', 'refine_search'])
assert len(anth) == 2
assert anth[0]['name'] == 'search_knowledge_base'
assert anth[1]['name'] == 'refine_search'
open_ai = r.schemas_for('openai', names=['search_knowledge_base'])
assert open_ai[0]['type'] == 'function'
assert open_ai[0]['function']['name'] == 'search_knowledge_base'
→ "all gates pass"
```

## ROADMAP SC Status

| SC | Description | Status |
|----|-------------|--------|
| SC1 | BaseTool ABC with 3 ClassVars + async run | PASS |
| SC2 | RetrieveTool wraps v1.3 retrieval; 19+2 tests pass | PASS |
| SC3 | WebSearchTool registered; excluded from AGENT_TOOL_ALLOWLIST | PASS |
| SC4 | executor.py + pipeline.py have 0 direct tool-class imports | PASS |
| SC5 | docs/agent-architecture.md#authoring-tools with runnable example | PASS |

## v1.3 Invariants Maintained

- PostgreSQL RLS: `ToolContext.tf` carries `tenant_id` end-to-end (Phase 16 unchanged)
- JWT: untouched (OIDC auth layer not touched)
- `audit_service.log()` callsite in `_persist_turn`: unchanged
- Pydantic V2 frozen + mypy --strict + ruff clean: all pass
- No bare `except`: RetrieveTool/RefinedRetrieveTool use `_RETRIEVE_RUNTIME_ERRORS` narrow tuple
- BaseException scope on `asyncio.gather(return_exceptions=True)`: preserved (Phase 16 D-01)

## Phase 17 Closure

AGENT-07 closed. Phase 17 (Tool Abstraction + RetrieveTool) is complete.
Next phase: 18 (SSE Planner Trace Event Stream — depends on the registry surface finalized here).

## Self-Check: PASSED

- FOUND: .planning/phases/17-tool-abstraction-retrievetool/17-03-SUMMARY.md
- FOUND: docs/agent-architecture.md
- FOUND: services/agent/tool_executor.py is deleted (confirmed)
- FOUND: All 8 commits in git log (ac23340, 6c343ce, fd6cb5a, 243f358, 988f890, 7d4beeb, 8291ce8, ed9bc67)
