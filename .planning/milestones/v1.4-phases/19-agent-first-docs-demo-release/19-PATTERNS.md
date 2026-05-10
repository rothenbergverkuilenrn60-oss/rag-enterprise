# Phase 19: Agent-First Docs + Demo + Release - Pattern Map

**Mapped:** 2026-05-09
**Files analyzed:** 8
**Analogs found:** 6 / 8 (2 establish convention)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `README.md` (full rewrite) | docs | reference | `README.md` v1.3 (same file, RAG-first framing) | exact (preserve technicals, invert narrative) |
| `docs/agent-architecture.md` (+`## Planner / Executor Model` insert) | docs | reference | `docs/agent-architecture.md::## Authoring Tools` (line 7) + `## Event Schema Reference` (line 99) | exact (sibling section) |
| `Makefile` (+`demo-agent` target) | build | request-response | `Makefile::eval`/`eval-local`/`up`/`ingest` (lines 28-69) | exact (sibling target) |
| `docs/demo.cast` | docs | streaming (asciinema) | NO ANALOG — establish convention | none (first cast in repo) |
| `docs/v1.4-design.md` | docs | reference | `docs/agent-architecture.md` (top-level docs naming) + gstack source at `~/.gstack/projects/.../ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` | role-match (copy verbatim, no transform) |
| `CHANGELOG.md` | docs | reference | NO ANALOG — establish keep-a-changelog convention | none (first CHANGELOG in repo) |
| `services/agent/_demo_stubs.py` | service / fixture | event-driven (planner stub) | `tests/unit/test_agent_sse.py::_StubPlanner` + `_make_fake_tool` + `_stub_registry` (lines 69-107) | role-match (test fixture promoted to runtime artifact) |
| `tests/integration/test_demo_agent.py` | test | streaming + mock | `tests/unit/test_agent_sse.py::test_run_streaming_latency_bounded_by_max_not_sum_d14_sc4` (line 235) | exact (Phase 18 SC4 fixture pattern) |

---

## Pattern Assignments

### 1. `README.md` — full rewrite (D-01..D-04)

**Analog:** existing v1.3 `README.md` (same file). Preserve all technical detail; invert the narrative framing.

**Preserve verbatim** (technical content moves to `## Platform features` per D-02 section 5):
- `README.md` lines 7-16 — Multi-tenant RLS, hybrid retrieval, 6/10-stage pipelines, image extraction, async ingest, security, observability, streaming
- `README.md` lines 36-65 — Architecture box-list (controllers/services/utils layout) — keep but re-banner as "Tools + supporting services"
- `README.md` lines 67-165 — Quick Start sections (Docker + Local Dev) — preserve, move to `## Quick start` per D-02 section 7
- `README.md` lines 215-230 — Configuration table — preserve verbatim
- `README.md` lines 246-281 — Coverage section (TEST-04 + TEST-06) — preserve under `## Platform features` subhead
- `README.md` line 312 — License + PyMuPDF AGPL note — preserve at bottom

**Invert** (replace verbatim):
- `README.md` lines 1-3 — current opener "A production-grade Retrieval-Augmented Generation platform built on FastAPI..." → REPLACE with thesis from D-01: **"A Planner → Executor → Synthesizer agent. RAG is one of its tools."** + 2-line elaboration.
- `README.md` lines 5-16 (`## Features` heading + bullets) — REPLACE with D-02 section order (Quick demo → Architecture → Tools the agent calls → Platform features → Observability → Quick start → Project status).
- `README.md` lines 18-34 (`### Parallel agentic tool calls`) — RECAST under `## Tools the agent calls` — the parallel-fan-out story is now the headline mechanic, not a sub-feature.

**ASCII diagram pattern** (D-02 section 3 + Claude's-Discretion "ASCII flow diagram syntax"). No analog inside README — use pure ASCII boxes ≤ 12 cols wide. Reference shape from `docs/agent-architecture.md` consumer snippet style (line 233-241, JS sample); but the README diagram is text-only:

```
Request ──▶ Planner ──ToolPlan──▶ Executor ──results──▶ Synthesizer ──▶ Response
                                     │
                              parallel dispatch
                              (asyncio.as_completed)
```

**cURL example pattern** — preserve from existing `README.md` lines 189-198 (Bearer-token + JSON body shape) but re-target `/agent/v1/run/stream` and add `--no-buffer` for SSE:

```bash
curl --no-buffer -X POST http://localhost:8000/api/v1/agent/v1/run/stream \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"query": "...", "session_id": "user-123", "tenant_id": "acme", "top_k": 5}'
```

**Adaptation notes:**
- README is one self-contained edit. No partial updates — write the full file once.
- Bilingual headers stay English-only (README is English-only per "Deferred: README internationalization" — Makefile bilingual-help convention is separate).
- No new badges (Claude's Discretion).
- Asciinema embed: HTML `<a><img src="https://asciinema.org/a/...">` (D-07) OR static gif fallback. Pick the HTML form first; the cast file lives at `docs/demo.cast` regardless.

---

### 2. `docs/agent-architecture.md` — additive insert of `## Planner / Executor Model` section (D-09, D-10, D-11)

**Analog:** existing sections in the same file.

**Heading-depth + table-style pattern** (lines 7-98 — `## Authoring Tools`):
```markdown
## Authoring Tools

The agent runtime dispatches tool calls through a static class registry
(`services/agent/tools/registry.py`). New tools subclass `BaseTool`,
declare three ClassVar attributes, implement an async `run` method, and
register themselves at module import time.

### Defining a Tool

1. Subclass `BaseTool` from `services.agent.tools.base`.
2. Declare three required ClassVar attributes:
   ...
```

**Runnable-snippet pattern** (lines 65-89 — `## Authoring Tools` runnable example):
```python
from typing import Any, ClassVar
from services.agent.tools.base import BaseTool
from services.agent.tools.registry import get_tool_registry
from utils.models import ToolContext, ToolResult

@get_tool_registry().register
class WebSearchTool(BaseTool):
    name:              ClassVar[str]            = "web_search"
    description:       ClassVar[str]            = (
        "Search the public web for current information. "
        "(Placeholder: v1.5+ implementation pending.)"
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Web search query"}},
        "required": ["query"],
    }

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(
            content="[WebSearchTool placeholder — v1.5+]",
            metadata={"placeholder": True, "args": args, "latency_ms": 0},
        )
```

**Field-table pattern** (lines 108-117 — `## Event Schema Reference` field tables):
```markdown
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `trace_id` | string (8-hex) | yes | Per-stream identifier; matches the orchestrator's `trace_id`. |
| `seq` | integer | yes | Monotonic counter; starts at 0; strictly increasing across all event types. |
| `ts_ms` | integer | yes | Unix epoch milliseconds at emit time. |
```

**Adaptation notes for `## Planner / Executor Model`:**
- Insert BEFORE current line 7 (`## Authoring Tools`). New section becomes lines 7..~150; existing sections shift down. Existing sections UNMODIFIED.
- Section order after insert: `## Planner / Executor Model` → `## Authoring Tools` → `## Event Schema Reference` (D-09).
- Update file header (lines 1-5) status line to reflect that Phase 19 closes the Concept → Tool authoring → Wire format trilogy.
- Section budget: ~120-150 lines (D-10), within the established ≤ 250-line per-section convention.
- Subsections to include (~25 lines each):
  - **Concept** — 2 paragraphs: Planner stateless `(messages, tools) → ToolPlan`; Executor consumes plan and dispatches each `parallel_group` via `asyncio.as_completed` with `BaseException` isolation; Synthesizer is the LLM's terminal `call_agentic_turn` after results.
  - **ASCII flow diagram** — boxes ≤ 12 cols, GitHub-renderable, no mermaid (Claude's Discretion). Pattern matches the README diagram shape but extends one level deeper (show `as_completed`, `BaseException` isolation arrow).
  - **Pydantic V2 signatures** — verbatim copy of `ToolPlan` (`utils/models.py` lines 291-315) and `ToolCall` (lines 244-258). Frozen, ConfigDict.
  - **Method signatures** — verbatim copy of `Planner.plan_from_messages` (`services/agent/planner.py` lines 43-48) and `Executor.execute_plan_streaming` (`services/agent/executor.py` lines 105-113).
  - **One runnable snippet** (~25-30 lines per D-11) — instantiate `AgentQueryPipeline`, call `run_streaming(req)`, iterate, log each event:
    ```python
    import asyncio
    from services.pipeline import AgentQueryPipeline
    from utils.models import GenerationRequest

    async def main() -> None:
        pipeline = AgentQueryPipeline()
        req = GenerationRequest(
            query="Across our compliance, finance, engineering, and HR knowledge bases, where do we mention 'data retention'?",
            session_id="demo-session", tenant_id="acme", user_id="demo", top_k=5,
        )
        async for evt in pipeline.run_streaming(req):
            print(f"{evt.event_type:>22}  seq={evt.seq:>3}  ts={evt.ts_ms}  payload={evt.model_dump_json()}")

    asyncio.run(main())
    ```
  - **Cross-references** — link to `## Authoring Tools` (how to add a tool) + `## Event Schema Reference` (wire format).

---

### 3. `Makefile` — new `demo-agent` target (D-06, D-08, Claude's-Discretion bilingual-help-string)

**Analog:** existing demo/eval targets in the same file.

**Bilingual help-string + grep-driven help** pattern (lines 13-15):
```makefile
help:  ## 显示帮助信息
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n",$$1,$$2}'
```
The `## <chinese-help>` suffix on each target is mandatory — `make help` greps these.

**Multi-step compose-up + exec target** pattern (lines 28-29 + 65-66):
```makefile
up:  ## 启动全栈（后台）
	$(COMPOSE) --env-file .env.docker up -d

eval:  ## 运行 RAGAS 评测（一次性任务）
	$(COMPOSE) --env-file .env.docker run --rm $(EVAL_SERVICE)
```

**Local (non-Docker) variant** pattern (lines 68-69):
```makefile
eval-local:  ## 本地（非Docker）运行评测
	conda run -n torch_env python -m eval.ragas_runner
```

**Section banner** convention (lines 17, 27, 53, 60, 64, 71, 78, 88, 106, 114) — group thematically with `# ── <section> ──` separators. The `demo-agent` target groups under a new `# ── Agent demo ──` separator near the existing `# ── RAGAS 评测 ──` block (line 64) per D-06 (group with demo/eval).

**Adaptation notes for `demo-agent`:**
- Add `demo-agent` to `.PHONY` line (line 7).
- New banner `# ── Agent 演示 (Phase 19) ──` after the RAGAS block (~line 70).
- Local-mode-first invocation (D-06 says "spins up Docker stack per ROADMAP SC3"; D-08 says contributors should not need asciinema). Resolution: `make demo-agent` runs the demo in-process via `conda run -n torch_env python -m services.agent._demo_runner` (no asciinema dependency); a separate `demo-agent-record` target wraps with `asciinema rec docs/demo.cast -- make demo-agent` for the one-shot maintenance task.
- Bilingual help-string format: `demo-agent:  ## 演示 Planner→Executor→Synthesizer 4 路并行 (Phase 19)`.

Concrete shape (planner reference):
```makefile
# ── Agent 演示 (Phase 19) ──────────────────────────────────────────────────────
demo-agent:  ## 演示 Planner→Executor→Synthesizer 4 路并行 (Phase 19)
	conda run -n torch_env python -m services.agent._demo_runner

demo-agent-record:  ## 录制 docs/demo.cast (维护任务，需要 asciinema)
	asciinema rec docs/demo.cast --overwrite \
		--command "conda run -n torch_env python -m services.agent._demo_runner"
```

---

### 4. `docs/demo.cast` — NEW asciinema cast file

**Analog:** NO ANALOG IN REPO — establish convention here.

**Reference convention:** asciinema cast v2 format (https://docs.asciinema.org/manual/asciicast/v2/). Generated by `asciinema rec` wrapping the demo invocation (D-07). Lives at `docs/demo.cast` (in-repo, per D-07).

**Adaptation notes:**
- File is generated, not hand-authored: `make demo-agent-record` (target above) produces it.
- README embeds via the asciinema-uploaded URL pattern: `<a href="https://asciinema.org/a/<id>"><img src="https://asciinema.org/a/<id>.svg"></a>`. Cast is also committed in-repo so the file is offline-readable.
- One-shot recording cadence (Claude's Discretion). Future milestones may re-record only if event-stream surface changes.
- Phase 19 plan picks: HTML embed if GitHub renders inline; else `agg docs/demo.cast docs/demo.gif` static-gif fallback (D-07).

---

### 5. `docs/v1.4-design.md` — copy of gstack milestone-design markdown (D-13, D-16)

**Analog (naming convention):** existing top-level docs at `docs/agent-architecture.md`, `docs/DOCKER_DEPLOY.md`. Lowercase-with-hyphens, single `.md` per topic, no frontmatter (`docs/agent-architecture.md` lines 1-5 use a plain `# Title` + italic status block):
```markdown
# Agent Architecture

*Status: Phase 18 (v1.4) — Tool abstraction + SSE event schemas shipped. This
document is the tool-author quick-start AND the SSE event-schema reference.
Historical intent mapping (Phase 19) extends this file later.*
```

**Source content:** verbatim copy of `~/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-v1.3-milestone-design-20260509-163809.md` (already follows the same `# Title` + status convention — see source lines 1-7).

**Adaptation notes:**
- Single docs commit (CONTEXT.md `<code_context>` Integration Points). No transform needed beyond:
  1. Path: write to `docs/v1.4-design.md` (the canonical path per D-16; leave the gstack-projects original untouched).
  2. Status banner: keep "Status: DRAFT" or update to "Status: SHIPPED in v1.4" — Phase 19 plan picks. Recommendation: update to "SHIPPED" since the doc is being committed AS the milestone artifact.
  3. Internal links: source uses bare path-like references (e.g., `services/pipeline.py`); these resolve correctly relative to repo root since `docs/v1.4-design.md` sits one level deep — adjust to `../services/pipeline.py` if any links exist, OR leave as repo-root-relative paths (GitHub renders both).
- README links to this from `## Project status` per D-16.

---

### 6. `CHANGELOG.md` — NEW at repo root (D-14, D-15)

**Analog:** NO ANALOG IN REPO — establish keep-a-changelog convention.

**Reference spec:** keep-a-changelog 1.1.0 (https://keepachangelog.com/en/1.1.0/). Categories: Added / Changed / Deprecated / Removed / Fixed / Security.

**Format pattern** (from spec):
```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.4.0] - 2026-05-09

### Added
- Phase 16 — Planner / Executor extraction. See [SUMMARY](.planning/phases/16-planner-executor-extraction/16-03-SUMMARY.md).
- Phase 17 — ToolRegistry + RetrieveTool. See [SUMMARY](.planning/phases/17-tool-abstraction-retrievetool/17-03-SUMMARY.md).
- Phase 18 — SSE event stream (`POST /agent/v1/run/stream`). See [SUMMARY](.planning/phases/18-sse-planner-trace-event-stream/18-03-SUMMARY.md).
- Phase 19 — Agent-first docs + demo + release. See [SUMMARY](.planning/phases/19-agent-first-docs-demo-release/19-XX-SUMMARY.md).

### Changed
- Architectural inversion: agent is the core, RAG is one tool. See [v1.4 design](docs/v1.4-design.md).

## [1.3.0] - 2026-05-09
...

[Unreleased]: https://github.com/<owner>/<repo>/compare/v1.4.0...HEAD
[1.4.0]:      https://github.com/<owner>/<repo>/compare/v1.3.0...v1.4.0
[1.3.0]:      https://github.com/<owner>/<repo>/compare/v1.2.0...v1.3.0
```

**Existing milestone-roadmap link targets** (verified):
- `.planning/milestones/v1.0-ROADMAP.md` (9.9K)
- `.planning/milestones/v1.1-ROADMAP.md` (10.7K)
- `.planning/milestones/v1.2-ROADMAP.md` (4.6K)
- `.planning/milestones/v1.3-ROADMAP.md` (9.3K)

**Adaptation notes:**
- Reverse-chronological order (newest first), per D-14 + spec.
- Each version section: `## [X.Y.Z] - YYYY-MM-DD` heading.
- v1.4 entry: formal Added/Changed categories per Claude's Discretion strictness default ("formal categories only for v1.4 entry").
- v1.0..v1.3 entries: free-form bullets per version (Claude's Discretion default), each linking the archived `.planning/milestones/vX.Y-ROADMAP.md` per D-14.
- Each phase bullet links to its phase SUMMARY (citation surface convention from Phases 16/17/18 — Established Patterns in CONTEXT.md `<code_context>`).
- Compare-link footer at bottom (keep-a-changelog convention) — but use repo-relative `[1.4.0]: <repo-url>/compare/v1.3.0...v1.4.0`. Phase 19 plan picks the repo URL placeholder if not yet known.

---

### 7. `services/agent/_demo_stubs.py` — NEW stub Planner + tool registry for `make demo-agent` (D-06)

**Analog:** test fixtures in `tests/unit/test_agent_sse.py`. The demo stub IS the test fixture promoted to a runtime artifact (CONTEXT.md `<code_context>` Reusable Assets bullet 1).

**Stub planner pattern** (`tests/unit/test_agent_sse.py` lines 99-106):
```python
class _StubPlanner:
    """Returns a queue of pre-canned ToolPlans, one per call."""

    def __init__(self, plans: list[ToolPlan]) -> None:
        self._plans = list(plans)

    async def plan_from_messages(self, *args: Any, **kwargs: Any) -> ToolPlan:
        return self._plans.pop(0)
```

**Fake tool with controlled latency** pattern (`tests/unit/test_agent_sse.py` lines 69-89):
```python
def _make_fake_tool(
    tool_name: str,
    content: str = "ctx",
    sleep_s: float = 0.0,
) -> type[BaseTool]:
    class _Fake(BaseTool):
        name:              ClassVar[str]            = tool_name
        description:       ClassVar[str]            = "fake"
        parameters_schema: ClassVar[dict[str, Any]] = {"type": "object"}

        async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
            if sleep_s > 0:
                await asyncio.sleep(sleep_s)
            return ToolResult(
                content=content,
                chunks=[],
                metadata={"latency_ms": int(sleep_s * 1000), "chunk_count": 0},
            )

    _Fake.__name__ = f"FakeTool_{tool_name}"
    return _Fake
```

**Stub registry** pattern (`tests/unit/test_agent_sse.py` lines 92-96):
```python
def _stub_registry(*classes: type[BaseTool]) -> ToolRegistry:
    reg = ToolRegistry()
    for cls in classes:
        reg.register(cls)
    return reg
```

**Mock-at-consumer-path discipline** (`tests/unit/test_agent_sse.py` lines 141-169 — mandatory; v1.3 D-16 convention):
```python
monkeypatch.setattr("services.pipeline.get_memory_service",   lambda: _NoMem())
monkeypatch.setattr("services.pipeline.get_audit_service",    lambda: _NoAudit())
monkeypatch.setattr("services.pipeline.get_tenant_service",   lambda: _NoTenant())
monkeypatch.setattr("services.pipeline.get_filter_extractor", lambda: _NoFilter())
monkeypatch.setattr("services.pipeline.get_planner",          lambda: planner)
monkeypatch.setattr(
    "services.agent.executor.get_tool_registry",
    lambda: _stub_registry(*tool_classes),
)
monkeypatch.setattr("services.pipeline.get_executor", lambda: executor)
monkeypatch.setattr(
    "services.pipeline.get_tool_registry",
    lambda: _stub_registry(*tool_classes),
)
monkeypatch.setattr("services.pipeline.get_llm_client", lambda: _LLM())
monkeypatch.setattr("services.pipeline.get_retriever",  lambda: object())
```

**Demo-query plan shape** (D-05 — same as `tests/unit/test_agent_sse.py` SC4 latency test, lines 235-255):
```python
Tool = _make_fake_tool("search_knowledge_base", sleep_s=0.5)
steps = [
    ToolCall(id=f"c{i}", name="search_knowledge_base", arguments={"i": i})
    for i in range(4)
]
plans = [
    _plan(steps=steps, groups=[[0, 1, 2, 3]]),  # 4-way parallel group
    _terminal_plan("done"),
]
```

**Adaptation notes for `services/agent/_demo_stubs.py`:**
- Location: `services/agent/_demo_stubs.py` (CONTEXT.md `<code_context>` Integration Points names this exact path; alternative `scripts/` or `tests/fixtures/` rejected because the stub is a runtime artifact — `make demo-agent` invokes it without pytest).
- Underscore-prefix (`_demo_stubs`) signals "internal — not part of the public agent surface."
- ~50-80 lines target (CONTEXT.md `<code_context>`).
- Module exports: `DemoStubPlanner`, `make_fake_retrieve_tool(name, sleep_s, content)`, `build_demo_registry(*tools) -> ToolRegistry`. Drop the underscore prefix from class names since the module itself is `_`-prefixed (avoids `_Stub_X` double-private noise).
- Each fake `RetrieveTool` returns a fixture `ToolResult` with 2-3 chunks per shard (D-06) — `metadata={"latency_ms": int(sleep_s*1000), "chunk_count": 3}` to populate the SSE event correctly.
- Demo query verbatim from CONTEXT.md `<specifics>`: "Across our compliance, finance, engineering, and HR knowledge bases, where do we mention 'data retention'?".
- Stub Synthesizer: not a separate class — leverage the `_terminal_plan(rationale="...composed answer...")` pattern (line 61 of test file). The orchestrator's terminal-plan path treats `rationale` as the final answer (D-06).

**Companion runner module** `services/agent/_demo_runner.py` (or `__main__.py` inside the same module):
- Wires `monkeypatch`-equivalent runtime patches (use `unittest.mock.patch` context managers or direct attribute assignment in a try/finally) — NOT pytest-only `monkeypatch`. The patch surface is identical to the test fixture; the dispatch mechanism differs.
- Iterates `pipeline.run_streaming(req)`, prints each event as `event: <type>\ndata: <json>\n` (mirror the SSE wire format from `controllers/api.py` line 282) so the asciinema recording shows the exact wire shape.
- Exit code 0 on success; non-zero if observed event sequence does not match the expected shape (D-06: "Non-zero exit on any event-shape mismatch").

---

### 8. `tests/integration/test_demo_agent.py` — end-to-end demo test (SC3 + SC4 verification)

**Analog:** `tests/unit/test_agent_sse.py::test_run_streaming_latency_bounded_by_max_not_sum_d14_sc4` (lines 234-255). The Phase 18 SC4 latency test is the structural twin — same 4-tool-0.5s parallel-group fixture, same latency assertion bounds.

**Phase 18 SC4 reference test** (verbatim, lines 234-255):
```python
@pytest.mark.asyncio
async def test_run_streaming_latency_bounded_by_max_not_sum_d14_sc4(patch_pipeline_singletons) -> None:
    """ROADMAP SC4 — 4 tools x 0.5s each finish in max(0.5)+overhead, not 4x0.5."""
    Tool = _make_fake_tool("search_knowledge_base", sleep_s=0.5)
    steps = [
        ToolCall(id=f"c{i}", name="search_knowledge_base", arguments={"i": i})
        for i in range(4)
    ]
    plans = [
        _plan(steps=steps, groups=[[0, 1, 2, 3]]),
        _terminal_plan("done"),
    ]
    pipeline = patch_pipeline_singletons(_StubPlanner(plans), Tool)
    t0 = time.perf_counter()
    events = [evt async for evt in pipeline.run_streaming(_req())]
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    assert 450 < elapsed_ms < 700, f"expected 450 < elapsed_ms < 700, got {elapsed_ms}"
    types = [type(e).__name__ for e in events]
    assert types.count("ToolSpanStartEvent") == 4
    assert types.count("ToolSpanEndEvent")   == 4
    parallel = [e for e in events if isinstance(e, ExecutorParallelEvent)]
    assert parallel[0].fan_out == 4
```

**Adaptation notes for `tests/integration/test_demo_agent.py`:**
- Location: `tests/integration/` (CONTEXT.md `<code_context>` Integration Points names `tests/integration/test_demo_agent.py` OR `tests/unit/`). Recommendation: `tests/integration/` because the test invokes `make demo-agent` end-to-end (subprocess) — that crosses module boundaries and exercises the runner, not just the pipeline.
- Use `subprocess.run(["make", "demo-agent"], capture_output=True, ...)` to invoke the Make target; assert exit code == 0; parse stdout to validate the SSE event sequence.
- Event-sequence assertion (D-06): expect `planner.plan` × 1 → `tool.span.start` × 4 → `tool.span.end` × 4 → `executor.parallel` × 1 (`fan_out=4`, `group_latency_ms < 700`) → `synthesizer.final` × 1.
- Latency bound from D-05 + SC4: total elapsed ∈ (450, 700) ms.
- Import the same `services.agent._demo_stubs` symbols (file 7 above) for an in-process variant assertion if the subprocess invocation is too brittle for CI — Phase 19 plan picks the variant.
- Do NOT duplicate the test_agent_sse.py fixtures here — import from `services.agent._demo_stubs` (single source of truth: the stubs ARE the demo fixture, the test consumes them).

---

## Shared Patterns

### Frozen Pydantic V2 model literal-quoting

**Source:** `utils/models.py::ToolPlan` (lines 291-315), `ToolCall` (lines 244-258), `AgentEvent` + 6 subclasses (lines 537-608).

**Apply to:** `docs/agent-architecture.md::## Planner / Executor Model` (verbatim copy of `ToolPlan` / `ToolCall` definitions per D-10 + D-11).

```python
class ToolPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    steps:             list[ToolCall]  = Field(default_factory=list)
    parallel_groups:   list[list[int]] = Field(default_factory=list)
    rationale:         str             = ""
    raw_assistant_msg: dict[str, Any]  = Field(default_factory=dict)
    stop_reason:       str             = "text_only"
```

The aligned-colon style (column-aligned `name: type = default`) is uniform across `utils/models.py` Stage 6/7 — preserve when copying into the docs.

### ASCII flow diagram (no mermaid)

**Source:** Claude's Discretion; no existing diagrams in repo (the `## Architecture` block in `README.md` lines 38-61 is a directory tree, not a flow diagram).

**Apply to:** `README.md::## Architecture` (D-02 section 3) AND `docs/agent-architecture.md::## Planner / Executor Model` ASCII subsection.

Convention: ≤ 12 cols wide per box, use `──▶` arrows (UTF-8) for horizontal flow, `│` + `▼` for vertical, monospace-fenced. Pattern:

```
Request ──▶ Planner ──ToolPlan──▶ Executor ──▶ Synthesizer ──▶ Response
                                     │
                              parallel dispatch
                              asyncio.as_completed
                              (BaseException isolation)
```

### Mock-at-consumer-path discipline (v1.3 D-16)

**Source:** `tests/unit/test_agent_sse.py` lines 141-169.

**Apply to:** `services/agent/_demo_stubs.py` runtime patching AND `tests/integration/test_demo_agent.py` (when running the in-process variant).

Patch the consumer's import path, not the source module's symbol:
```python
monkeypatch.setattr("services.pipeline.get_planner",          lambda: planner)
monkeypatch.setattr("services.agent.executor.get_tool_registry", lambda: registry)
monkeypatch.setattr("services.pipeline.get_executor",         lambda: executor)
monkeypatch.setattr("services.pipeline.get_tool_registry",    lambda: registry)
```

Note the belt-and-braces patch on BOTH `services.pipeline.get_tool_registry` AND `services.agent.executor.get_tool_registry` — the pipeline reads it for the planner-tools schema list, the executor reads it for dispatch (test_agent_sse.py lines 156-162).

### SSE wire-format frame

**Source:** `controllers/api.py` lines 280-294.

**Apply to:** `services/agent/_demo_stubs.py` (companion runner) when printing events to stdout for the asciinema recording. Match wire format verbatim so the cast shows the same bytes a real `curl --no-buffer` invocation would see.

```python
yield f"event: {evt.event_type}\ndata: {evt.model_dump_json()}\n\n"
```

### Bilingual Makefile help-string

**Source:** `Makefile` lines 13-15 (the `help` target greps `## ...` suffixes).

**Apply to:** `Makefile::demo-agent` and any new sibling targets in Phase 19. Help-string in Chinese (matching existing convention — every target lines 18-128 has a Chinese help-string). Phase identifier in parentheses (Phase 19) for traceability.

```makefile
demo-agent:  ## 演示 Planner→Executor→Synthesizer 4 路并行 (Phase 19)
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `docs/demo.cast` | docs / asciinema cast | streaming binary (cast v2 JSON-lines) | First asciinema artifact in repo. Generated by `asciinema rec`, not hand-authored. Convention established by spec (https://docs.asciinema.org/manual/asciicast/v2/) and by the `make demo-agent-record` target wrapping the demo invocation. |
| `CHANGELOG.md` | docs / version history | reference | First CHANGELOG in repo. Convention established by keep-a-changelog 1.1.0 spec (https://keepachangelog.com/en/1.1.0/). Version-link footer pattern + reverse-chronological + Added/Changed/Deprecated/Removed/Fixed/Security categories per spec. |

For both: planner should reference the external spec verbatim and the structural skeleton given in §4 + §6 above, not search for an in-repo analog.

---

## Metadata

**Analog search scope:**
- `README.md` (root)
- `Makefile` (root)
- `docs/` — `agent-architecture.md`, `DOCKER_DEPLOY.md`
- `services/pipeline.py` — `AgentQueryPipeline.run_streaming` (line 822)
- `services/agent/executor.py` — `Executor.execute_plan_streaming` (line 105)
- `services/agent/planner.py` — `Planner.plan_from_messages` (line 43)
- `controllers/api.py` — `/agent/v1/run/stream` route (line 259)
- `utils/models.py` — `ToolPlan`/`ToolCall`/`AgentEvent` + 6 subclasses (lines 244-608)
- `tests/unit/test_agent_sse.py` — fixtures + SC4 latency test
- `tests/unit/test_executor_streaming.py` — Executor streaming tests
- `.planning/phases/16-planner-executor-extraction/`, `17-tool-abstraction-retrievetool/`, `18-sse-planner-trace-event-stream/` — SUMMARYs (citation surface)
- `.planning/milestones/v1.0..v1.3-ROADMAP.md` — CHANGELOG link targets

**Files scanned:** ~15 source files, 4 milestone roadmaps, 8 phase summaries.

**Pattern extraction date:** 2026-05-09.
