---
phase: 17-tool-abstraction-retrievetool
plan: "02"
subsystem: services/agent/tools
tags: [tools, rag, retrieval, tdd, wave-2]
dependency_graph:
  requires: [17-01]
  provides: [RetrieveTool, RefinedRetrieveTool, WebSearchTool, retrieve_impl]
  affects: [services/agent/tools/__init__.py, ToolRegistry singleton]
tech_stack:
  added: []
  patterns: [BaseTool-subclass-decorator-registration, module-private-helper, swarm-compat-shim]
key_files:
  created:
    - services/agent/tools/retrieve.py
    - services/agent/tools/web_search.py
    - tests/unit/test_retrieve_tool.py
    - tests/unit/test_web_search_tool.py
  modified:
    - services/agent/tools/__init__.py
decisions:
  - "_retrieve_impl body verbatim-migrated from tool_executor.py:38-66; XML doc-block format preserved byte-identically"
  - "retrieve_impl public shim exposes Wave 3 import-switch entry point for SwarmQueryPipeline"
  - "_RETRIEVE_RUNTIME_ERRORS tuple: narrow exception types per ERR-01 (no bare except)"
  - "WebSearchTool registered but not in any allowlist — planner LLM never sees its schema until Wave 3"
  - "T6 uses empty commit to record sweep results — no code changes needed in REFACTOR phase"
metrics:
  duration: "6 minutes"
  completed: "2026-05-09"
  tasks: 6
  files: 5
---

# Phase 17 Plan 02: RetrieveTool + RefinedRetrieveTool + WebSearchTool (Wave 2, TDD) Summary

RetrieveTool + RefinedRetrieveTool classes registered in ToolRegistry with byte-identical parameter schemas and XML doc-block format migrated verbatim from v1.3 tool_executor.py; WebSearchTool placeholder proves registry pluggability.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| T1 | RED: test_retrieve_tool.py | d9d3fc3 | tests/unit/test_retrieve_tool.py |
| T2 | RED: test_web_search_tool.py | 5c6c736 | tests/unit/test_web_search_tool.py |
| T3 | GREEN: _retrieve_impl + retrieve_impl | 2000be1 | services/agent/tools/retrieve.py |
| T4 | GREEN: __init__.py retrieve imports | a64caad | services/agent/tools/__init__.py |
| T5 | GREEN: WebSearchTool + __init__.py update | 661e1ba | services/agent/tools/web_search.py, __init__.py |
| T6 | REFACTOR: full sweep | 8413ccc | (empty commit — no code changes needed) |

## TDD Gate Compliance

RED phase (T1, T2): Both test files collected with ImportError before any implementation. Confirmed non-zero exit with expected error messages.

GREEN phase (T3-T5): Tests transitioned to 45/45 passing after implementation. No tests skipped.

REFACTOR phase (T6): Coverage, ruff, mypy, full suite verified clean. No code changes required.

Gate sequence:
1. `test(17-02-T1)` commit d9d3fc3 — RED gate confirmed
2. `test(17-02-T2)` commit 5c6c736 — RED gate confirmed
3. `feat(17-02-T3/T4/T5)` commits — GREEN gates confirmed
4. `feat(17-02-T6)` commit — REFACTOR gate confirmed

## Acceptance Gates Verified

- [x] All RED tests in test_retrieve_tool.py + test_web_search_tool.py pass after GREEN steps
- [x] `_retrieve_impl` body BYTE-IDENTICAL to tool_executor.py:38-66 (XML format string, args.get fallback, sentinel)
- [x] `RetrieveTool.parameters_schema` BYTE-IDENTICAL to pipeline.py:_AGENT_TOOLS[0]["input_schema"]
- [x] `RefinedRetrieveTool.parameters_schema` BYTE-IDENTICAL to pipeline.py:_AGENT_TOOLS[1]["input_schema"]
- [x] `get_tool_registry().list()` == `['refine_search', 'search_knowledge_base', 'web_search']`
- [x] `schemas_for("anthropic", names=["search_knowledge_base","refine_search"])` BYTE-IDENTICAL to _AGENT_TOOLS
- [x] WebSearchTool.run returns placeholder ToolResult — no network call
- [x] `pytest tests/unit/test_retrieve_tool.py tests/unit/test_web_search_tool.py -q` exits 0 (45 tests)
- [x] Full unit suite: 729 passed, 1 skipped — 0 regressions vs Wave 1 baseline
- [x] `ruff check services/agent/tools/ tests/unit/test_retrieve_tool.py tests/unit/test_web_search_tool.py` clean
- [x] `mypy --strict services/agent/tools/` — 0 NEW errors vs baseline

## Test Counts

| File | RED (collected) | GREEN (passed) |
|------|-----------------|----------------|
| test_retrieve_tool.py | collection ERROR (ImportError) | 30 tests |
| test_web_search_tool.py | collection ERROR (ImportError) | 15 tests |
| **Total new tests** | — | **45** |

Full suite: 729 passed, 1 skipped (was ~684 in Wave 1).

## Coverage Report

```
Name                                 Stmts   Miss  Cover
---------------------------------------------------------
services/agent/tools/base.py            18      0  100%
services/agent/tools/registry.py        32      0  100%
services/agent/tools/retrieve.py        67      9   87%
services/agent/tools/web_search.py      16      0  100%
---------------------------------------------------------
TOTAL                                  133      9   93%
```

retrieve.py missed lines: 89-93 (the `_RETRIEVE_RUNTIME_ERRORS` tuple body), 224-227 (RefinedRetrieveTool error path — mirrors RetrieveTool's tested error path). Both acceptable.

## Byte-Identical Parity Verification

`registry.schemas_for("anthropic", names=["search_knowledge_base","refine_search"])` output:
```json
[
  {
    "name": "search_knowledge_base",
    "description": "在企业知识库中搜索相关信息",
    "input_schema": {"type":"object","properties":{"query":{"type":"string","description":"搜索查询词，应精确描述需要找到的信息"},"top_k":{"type":"integer","description":"返回结果数量（1-10）","default":5}},"required":["query"]}
  },
  {
    "name": "refine_search",
    "description": "用更精确的关键词细化搜索，适用于初次搜索结果不够具体时",
    "input_schema": {"type":"object","properties":{"refined_query":{"type":"string","description":"更精确的搜索词"},"source_filter":{"type":"string","description":"限定搜索的文档来源（可选）"}},"required":["refined_query"]}
  }
]
```

Identical to services/pipeline.py:602-640 _AGENT_TOOLS. Wave 3 deletion gate: ARMED.

## Swarm-Compat Shim Verified

```
retrieve_impl signature OK: ['tc', 'tf', 'req', 'retriever', 'llm']
```

SwarmQueryPipeline Wave 3 import switch is a single line:
```python
from services.agent.tools.retrieve import retrieve_impl as execute_tool_call
```

## Scope Boundary Verified

Consumer files UNCHANGED (git diff --stat 2fdb765..HEAD):
- services/pipeline.py: 0 changes
- services/agent/executor.py: 0 changes
- services/agent/tool_executor.py: 0 changes
- services/agent/__init__.py: 0 changes

## Deviations from Plan

None — plan executed exactly as written.

The T6 "REFACTOR" task required no code changes (all quality gates passed on first run). An empty commit was used to preserve the conventional-commit history structure.

Test counts exceeded the plan minimums (30 vs planned 16 for test_retrieve_tool.py; 15 vs planned 7 for test_web_search_tool.py) because the registration ClassVar tests were written individually for completeness. This is a minor positive deviation.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries introduced. All code is internal tool dispatch, no external surface added.

## Known Stubs

WebSearchTool.run always returns `ToolResult(content="[WebSearchTool placeholder — v1.5+]", metadata={"placeholder": True, ...})`. This is intentional and documented — the stub is the plan's stated goal. Wave 3 (Plan 17-03) establishes the AGENT_TOOL_ALLOWLIST that excludes WebSearchTool from the planner LLM. Real implementation is v1.5+.

## Self-Check: PASSED

Files verified:
- FOUND: services/agent/tools/retrieve.py
- FOUND: services/agent/tools/web_search.py
- FOUND: services/agent/tools/__init__.py
- FOUND: tests/unit/test_retrieve_tool.py
- FOUND: tests/unit/test_web_search_tool.py
- FOUND: .planning/phases/17-tool-abstraction-retrievetool/17-02-SUMMARY.md

Commits verified:
- FOUND: d9d3fc3 (T1 RED)
- FOUND: 5c6c736 (T2 RED)
- FOUND: 2000be1 (T3 GREEN helpers)
- FOUND: a64caad (T4 GREEN __init__.py)
- FOUND: 661e1ba (T5 GREEN WebSearchTool)
- FOUND: 8413ccc (T6 REFACTOR sweep)
