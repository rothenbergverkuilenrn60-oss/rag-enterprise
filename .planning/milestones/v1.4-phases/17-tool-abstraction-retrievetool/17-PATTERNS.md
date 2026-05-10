# Phase 17 — Pattern Map

> Each new module/file maps to its closest in-codebase analog. Planner uses this to keep Phase 17 architecturally consistent with Phase 16 + earlier work.

**Mapped:** 2026-05-09
**Files analyzed:** 10 (7 new, 2 modified, 1 new test)
**Analogs found:** 9 / 10 (docs stub has no analog)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/agent/tools/__init__.py` | package-init | re-export + side-effect | `services/agent/__init__.py` | exact |
| `services/agent/tools/base.py` | ABC / protocol | request-response | `services/agent/planner.py` (class shape) | role-match |
| `services/agent/tools/registry.py` | service / factory | request-response | `services/agent/executor.py` (singleton factory) | role-match |
| `services/agent/tools/retrieve.py` | service / tool impl | request-response | `services/agent/tool_executor.py` | exact |
| `services/agent/tools/web_search.py` | service / placeholder | request-response | `services/agent/tool_executor.py` (shape only) | partial |
| `utils/models.py` (ToolResult + ToolContext) | model | — | `utils/models.py` ToolCall / ToolPlan (lines 244-258, 291-349) | exact |
| `tests/unit/test_tool_registry.py` | test | unit | `tests/unit/test_planner.py` | exact |
| `tests/unit/test_retrieve_tool.py` | test | unit + async | `tests/unit/test_executor.py` | exact |
| `tests/unit/test_base_tool.py` | test | unit | `tests/unit/test_planner.py` (validator tests) | role-match |
| `docs/agent-architecture.md` | docs stub | — | none | no analog |

---

## Pattern Assignments

### `services/agent/tools/__init__.py`

**Analog:** `services/agent/__init__.py` (lines 1-20)

**Mirror this:** Copy the docstring + `__all__` + explicit named re-export style verbatim. Add side-effect import lines (`from services.agent.tools import retrieve as _retrieve_mod  # noqa: F401`) immediately after re-exporting `BaseTool` and `ToolRegistry` — this is the only difference from the Phase 16 `__init__` pattern. The `# noqa: F401` comment is mandatory; ruff flags unused side-effect imports without it.

**Imports pattern** (`services/agent/__init__.py` lines 1-20):
```python
"""services.agent — agent runtime: planner, executor, shared tool helper.
...
"""

from services.agent.executor import Executor, get_executor
from services.agent.planner import Planner, PlannerOutputError, get_planner
from services.agent.tool_executor import execute_tool_call

__all__ = [
    "Executor",
    "Planner",
    "PlannerOutputError",
    "execute_tool_call",
    "get_executor",
    "get_planner",
]
```

---

### `services/agent/tools/base.py`

**Analog:** `services/agent/planner.py` (lines 1-16 for header/import pattern; lines 37-151 for class shape)

**Mirror this:** Copy the `from __future__ import annotations` + stdlib → third-party → loguru → local import order from `planner.py` lines 12-20. The class body is pure Python ABC (not Pydantic) — `planner.py` shows the expected docstring depth, logger usage, and single-responsibility method layout. Use `__init_subclass__` to enforce ClassVar presence at class-definition time (RESEARCH.md verified pattern).

**Import block pattern** (`services/agent/planner.py` lines 12-20):
```python
from __future__ import annotations

import json
from typing import Any

from loguru import logger

from services.generator.llm_client import get_llm_client
from utils.models import AgenticTurn, ToolCall, ToolPlan
```

**Class docstring depth** (`services/agent/planner.py` lines 38-40):
```python
class Planner:
    """Wraps a single ``call_agentic_turn`` invocation, returns a ToolPlan."""
```

---

### `services/agent/tools/registry.py`

**Analog:** `services/agent/executor.py` (lines 27-104) — class + `__init__` + methods + module-level singleton pattern

**Mirror this:** Copy the `_executor_instance: Executor | None = None` / `get_executor()` pattern (lines 97-104) verbatim for `_registry: ToolRegistry | None = None` / `get_tool_registry()`. The `Executor.__init__` with optional-arg defaulting to `get_X()` (lines 33-36) shows the lazy-init convention Phase 17 should replicate for the singleton. Keep `ToolRegistry.__init__` simple (`self._tools: dict[str, type[BaseTool]] = {}`).

**Singleton pattern** (`services/agent/executor.py` lines 97-104):
```python
_executor_instance: Executor | None = None


def get_executor() -> Executor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = Executor()
    return _executor_instance
```

**Class init with optional deps** (`services/agent/executor.py` lines 33-36):
```python
def __init__(
    self,
    retriever: Any | None = None,
    llm: Any | None = None,
) -> None:
    self._retriever = retriever if retriever is not None else get_retriever()
    self._llm = llm if llm is not None else get_llm_client()
```

---

### `services/agent/tools/retrieve.py`

**Analog:** `services/agent/tool_executor.py` (lines 1-67) — this IS the body being migrated

**Mirror this:** The entire `execute_tool_call` body (lines 38-66 of `tool_executor.py`) moves verbatim into `_retrieve_impl` / `retrieve_impl`. Preserve the XML doc-block format string exactly (`<search_results><document index=...>` — consumed by planner LLM). Preserve the `args.get("query") or args.get("refined_query", req.query)` fallback chain (line 39) — this is the parity gate for v1.3 unit tests. The `RetrieveTool.run()` and `RefinedRetrieveTool.run()` are thin wrappers that construct a `ToolResult` from the `(chunks, ctx_text)` tuple returned by `_retrieve_impl`.

**Body to migrate verbatim** (`services/agent/tool_executor.py` lines 38-66):
```python
args       = tc.arguments or {}
query_str  = args.get("query") or args.get("refined_query", req.query)
top_k      = min(int(args.get("top_k", 5)), 10)
src_filter = args.get("source_filter")

effective_filter = dict(tf or {})
if src_filter:
    effective_filter["source"] = src_filter

chunks, _ = await retriever.retrieve(
    query=query_str,
    top_k=top_k,
    filters=effective_filter or None,
    llm_client=llm,
)

if chunks:
    doc_blocks = "\n\n".join(
        f'<document index="{i+1}" title="{c.metadata.title or c.doc_id}">\n'
        f"{c.content}\n"
        f"</document>"
        for i, c in enumerate(chunks)
    )
    ctx_text = f"<search_results>\n{doc_blocks}\n</search_results>"
else:
    ctx_text = "未找到相关内容"

return chunks, ctx_text
```

Also expose `retrieve_impl` (public, same signature as old `execute_tool_call`) so `SwarmQueryPipeline` can switch its import without a behavior change (RESEARCH.md Swarm Compatibility section).

---

### `services/agent/tools/web_search.py`

**Analog:** `services/agent/tool_executor.py` (lines 1-16 for module header; lines 24-30 for function signature shape)

**Mirror this:** Module header (docstring noting placeholder / deferral version) follows `tool_executor.py` lines 1-15 convention. The class body follows `retrieve.py` shape — same ClassVar annotation pattern, same `@get_tool_registry().register` decorator. `run()` returns immediately with a canned `ToolResult`; populate `metadata["latency_ms"]`, `metadata["placeholder"] = True`, and `metadata["args"] = args` (RESEARCH.md Phase 18 forward-compat requirement). No network calls, no secrets.

**Module docstring pattern** (`services/agent/tool_executor.py` lines 1-15):
```python
"""Shared tool-execution helper extracted from v1.3 AgentQueryPipeline + SwarmQueryPipeline (AGENT-09).

The body is a verbatim extract of `_execute_tool_call` at the v1.3 baseline ...
Wave 1 of Phase 16 (Plan 16-01) introduces this helper ...
"""
```

---

### `utils/models.py` — additions: `ToolResult` + `ToolContext`

**Analog:** `utils/models.py` `ToolCall` (lines 244-258) and `ToolPlan` (lines 291-315)

**Mirror this:** Place both new models in the existing `# STAGE 6 — Agentic Tool Use` section immediately after `ToolPlan`. Use `ConfigDict(frozen=True)` for both, exactly as `ToolCall` (line 254) and `ToolPlan` (line 305) do. `ToolContext` additionally needs `arbitrary_types_allowed=True` because `retriever` and `llm` fields hold non-Pydantic instances (RESEARCH.md Pitfall 3). `ToolResult.chunks` default `[]` and `metadata` default `{}` use `Field(default_factory=list)` / `Field(default_factory=dict)` matching the `ToolPlan.steps` / `AgenticTurn.tool_calls` pattern (lines 307, 283).

**Frozen model pattern** (`utils/models.py` lines 244-258):
```python
class ToolCall(BaseModel):
    """A single tool invocation requested by the LLM in one assistant turn.
    ...
    Frozen — adapters never mutate.
    """
    model_config = ConfigDict(frozen=True)

    id:        str
    name:      str
    arguments: dict[str, Any] = Field(default_factory=dict)
```

**Field(default_factory=...) pattern** (`utils/models.py` lines 307-308):
```python
    steps:             list[ToolCall]  = Field(default_factory=list)
    parallel_groups:   list[list[int]] = Field(default_factory=list)
```

---

### `tests/unit/test_tool_registry.py`

**Analog:** `tests/unit/test_planner.py` (full file — 19-test structure, stub class, helper factories, class-based grouping)

**Mirror this:** Copy the `_StubLLM`-style inline stub class pattern (test_planner.py lines 19-34) for `_FakeTool` — a minimal concrete `BaseTool` subclass used only in tests. Use `_tc()` / `_req()` factory helper functions (lines 37-48) for concise fixture creation. Group tests in classes by feature (`TestToolRegistryRegister`, `TestToolRegistrySchemas`, `TestProviderMapping`). Mock target for executor integration tests: `monkeypatch.setattr("services.agent.executor.get_tool_registry", ...)` — NOT `services.agent.tools.registry.get_tool_registry` (CONTEXT.md code_context + RESEARCH.md Pitfall 1).

**Stub + factory pattern** (`tests/unit/test_planner.py` lines 19-48):
```python
class _StubLLM:
    """Minimal LLM stub: returns canned AgenticTurns in sequence."""
    def __init__(self, turns: list[AgenticTurn]) -> None:
        self._turns = list(turns)
        self.calls: list[tuple[Any, Any]] = []

    async def call_agentic_turn(self, ...) -> AgenticTurn:
        self.calls.append((messages, tools))
        return self._turns.pop(0)


def _tc(call_id: str, name: str = "search_knowledge_base", **args: Any) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args)
```

---

### `tests/unit/test_retrieve_tool.py`

**Analog:** `tests/unit/test_executor.py` (full file — async dispatch, monkeypatch consumer-path, `return_exceptions` isolation pattern)

**Mirror this:** Copy the `@pytest.mark.asyncio` + `monkeypatch.setattr("services.agent.executor.get_tool_registry", ...)` consumer-path mock convention from `test_executor.py` lines 27-35. Assert on `ToolResult.content`, `ToolResult.chunks`, `ToolResult.is_error`, and `ToolResult.metadata["latency_ms"]` — same assertion depth as `test_executor.py` lines 44-46. Add a parity test that calls `registry.schemas_for("anthropic", names=["search_knowledge_base", "refine_search"])` and asserts the output is byte-identical to the deleted `_AGENT_TOOLS` literal from `services/pipeline.py` lines 602-639.

**Consumer-path mock pattern** (`tests/unit/test_executor.py` lines 35-45):
```python
monkeypatch.setattr("services.agent.executor.execute_tool_call", fake_exec)

plan = ToolPlan(steps=[_tc("a")], parallel_groups=[[0]])
executor = Executor(retriever=object(), llm=object())
results = await executor.execute_plan(plan, {}, _req())

assert len(results) == 1
assert results[0][1] == "ctx_a"
```

**`return_exceptions` isolation assertion** (`tests/unit/test_executor.py` lines 109-140):
```python
results = await executor.execute_plan(plan, {}, _req())
assert results[0] == ([], "ok")
assert isinstance(results[1], RuntimeError)
assert "tool failure" in str(results[1])
```

---

### `tests/unit/test_base_tool.py`

**Analog:** `tests/unit/test_planner.py` `TestToolPlanValidators` class (lines 53-99) — validator/guard enforcement tests

**Mirror this:** Use the same `pytest.raises(TypeError, ...)` pattern that `test_planner.py` uses for `pytest.raises(ValidationError, match=...)` (lines 84-89) — same structure, different exception. Test three guards: (1) missing `name` ClassVar raises `TypeError` at class-definition time (not instantiation), (2) missing `description` raises, (3) concrete subclass with all three ClassVars instantiates cleanly. Also test `@abstractmethod async def run` is enforced: `BaseTool()` raises `TypeError: Can't instantiate abstract class`.

**Validator enforcement pattern** (`tests/unit/test_planner.py` lines 84-89):
```python
def test_reject_empty_groups_when_steps_present(self) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        ToolPlan(steps=[_tc("a")], parallel_groups=[])
```

---

### `docs/agent-architecture.md`

**Analog:** None — no existing docs in `docs/` for agent architecture.

**No analog.** Minimum content per CONTEXT.md D-12 / Claude's Discretion: (1) "How to define a Tool" — subclass `BaseTool`, set 3 ClassVars, implement `async def run`; (2) "How to register" — `@registry.register` decorator at module top; (3) "parameters_schema shape" — JSON Schema dict; (4) one runnable `RetrieveTool`-style example. Keep it to ~50 lines. Historical intent mapping table (Query/Agent/Swarm → ToolPlan shape) is deferred to Phase 19 per D-13 carry-forward — do NOT add it here.

---

## Shared Patterns (cross-cutting)

### Singleton factory

**Source:** `services/agent/executor.py` lines 97-104 + `services/agent/planner.py` lines 144-151
**Apply to:** `services/agent/tools/registry.py` (`get_tool_registry`)

```python
_instance: T | None = None

def get_X() -> T:
    global _instance
    if _instance is None:
        _instance = T()
    return _instance
```

### `from __future__ import annotations` + import ordering

**Source:** `services/agent/executor.py` lines 12-24, `services/agent/planner.py` lines 12-20
**Apply to:** ALL new `services/agent/tools/*.py` modules

Order: `from __future__ import annotations` → blank → stdlib → blank → third-party (`loguru`) → blank → local (`utils.models`, `services.*`).

```python
from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from utils.models import GenerationRequest, RetrievedChunk, ToolCall
```

### Pydantic V2 frozen model with `ConfigDict`

**Source:** `utils/models.py` lines 244-258 (`ToolCall`), lines 291-315 (`ToolPlan`)
**Apply to:** `ToolResult` and `ToolContext` additions in `utils/models.py`

```python
model_config = ConfigDict(frozen=True)
# ToolContext additionally:
model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
```

### Consumer-path monkeypatch mock target

**Source:** `tests/unit/test_executor.py` line 35
**Apply to:** ALL Phase 17 test files that exercise registry or tool dispatch through `Executor`

Mock at `services.agent.executor.get_tool_registry` (the consumer import path), NOT at `services.agent.tools.registry.get_tool_registry`. This is the v1.3 Phase 13/15 convention; CONTEXT.md code_context and RESEARCH.md Pitfall 1 both enforce it.

### `ClassVar` annotation on concrete subclasses (mypy --strict)

**Source:** RESEARCH.md Pitfall 6
**Apply to:** `RetrieveTool`, `RefinedRetrieveTool`, `WebSearchTool` in Phase 17

Even though `BaseTool` declares `name: ClassVar[str]`, each concrete subclass must repeat the annotation:
```python
class RetrieveTool(BaseTool):
    name: ClassVar[str] = "search_knowledge_base"
    description: ClassVar[str] = "..."
    parameters_schema: ClassVar[dict[str, Any]] = {...}
```
Omitting `ClassVar[str]` on the subclass causes mypy --strict to warn.

---

## Pattern Constraints (cross-cutting)

1. **`frozen=True` on every Pydantic model.** `ToolResult` and `ToolContext` must use `ConfigDict(frozen=True)`, matching `ToolCall` (line 254) and `ToolPlan` (line 305). No mutable models in Phase 17.

2. **Import order: stdlib → third-party → loguru → local, with `from __future__ import annotations` at top.** All four existing Phase 16 files (`planner.py`, `executor.py`, `tool_executor.py`, `__init__.py`) follow this order. All Phase 17 files must match.

3. **No direct tool-class imports in `services/pipeline.py` or `services/agent/executor.py`.** Per CONTEXT.md D-09 / ROADMAP SC4: only `get_tool_registry` may be imported in those files. A CI `grep` check enforces this. Any `from services.agent.tools.retrieve import RetrieveTool` in pipeline/executor is a hard violation.

4. **XML doc-block format string in `_retrieve_impl` is immutable.** The `<search_results><document index=...>` shape (tool_executor.py lines 55-63) is consumed verbatim by the planner LLM prompt. Any change to the format string is a parity-break that invalidates the 19 v1.3 unit tests and two Phase 16 parity fixtures.

5. **`metadata["latency_ms"]` must be populated in every `ToolResult` returned by Phase 17 tools.** This is a Phase 18 forward-compatibility contract (RESEARCH.md Phase 18 SSE section). `RetrieveTool._retrieve_impl`, `WebSearchTool.run()`, and `BaseTool._build_error_result()` must all set `latency_ms` — use `int((time.perf_counter() - t0) * 1000)` with a `t0 = time.perf_counter()` at function entry.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `docs/agent-architecture.md` | documentation | — | No existing `docs/` agent architecture reference; stub from scratch per CONTEXT.md Claude's Discretion |

---

## Metadata

**Analog search scope:** `services/agent/`, `utils/models.py`, `tests/unit/`, `services/pipeline.py`, `services/retriever/retriever.py`
**Files scanned:** 10 source files read in full
**Pattern extraction date:** 2026-05-09
