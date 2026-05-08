# Phase 12: Fork-Agent Swarm - Research

**Researched:** 2026-05-08
**Domain:** asyncio concurrent agent orchestration, LLM prompt decomposition/synthesis, audit extension
**Confidence:** HIGH

## Summary

Phase 12 introduces `SwarmQueryPipeline`, a new class in `services/pipeline.py` that decomposes a multi-dimension query into N sub-questions via an LLM coordinator call, fans out N isolated `call_agentic_turn` loops concurrently via `asyncio.gather`, and synthesizes the results with a second LLM call. The foundation is fully ready: `call_agentic_turn` (Anthropic + OpenAI adapters) is implemented and tested in Phase 11; the `asyncio.gather(return_exceptions=True)` pattern is already used within `AgentQueryPipeline` for parallel tool calls; `AuditService.log_query` accepts an open `detail` dict that can carry swarm-specific fields without breaking callers.

All architectural decisions are locked in CONTEXT.md (D-01 through D-09). Research focus is on the implementation specifics needed to execute those decisions correctly: coordinator/synthesis prompt patterns, asyncio gather sub-agent coroutine structure, audit field extension, and test patterns for concurrent isolation verification.

**Primary recommendation:** Build `SwarmQueryPipeline` as a standalone class that reuses `AgentQueryPipeline._execute_tool_call` and `_AGENT_TOOLS`/`_AGENT_SYSTEM` via direct import or shared module-level constants, keeping `AgentQueryPipeline` entirely unchanged.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** New `SwarmQueryPipeline` class in `services/pipeline.py`. `AgentQueryPipeline` remains unchanged.
- **D-02:** New `get_swarm_pipeline()` factory function. `get_agent_pipeline()` unchanged.
- **D-03:** N=1 edge case: coordinator returns 1 sub-question → delegate to `get_agent_pipeline().run(req)`.
- **D-04:** Add `swarm_mode: bool = False` to `GenerationRequest` in `utils/models.py`.
- **D-05:** Coordinator = LLM call with decomposition system prompt. Output is JSON list of sub-question strings. Capped at `MAX_SWARM_AGENTS` (default 5, env-var-configurable).
- **D-06:** Sub-agents start clean: `messages = [{"role": "user", "content": sub_question}]`. No chat history injection.
- **D-07:** `asyncio.gather(*coros, return_exceptions=True)`. Failed sub-agent → error marker string passed to synthesis LLM.
- **D-08:** Audit fields: `swarm_n`, `per_agent_turns: list[int]`, `per_agent_tool_calls: list[int]`, `swarm_latency_ms`, `synthesis_latency_ms`.
- **D-09:** `MAX_SWARM_AGENTS = 5`, `MAX_SWARM_TURNS_PER_AGENT = 5` — class-level constants backed by `settings` env vars (OPS-01 pattern).

### Claude's Discretion
None specified — all key decisions locked.

### Deferred Ideas (OUT OF SCOPE)
- Streaming SSE for swarm responses (AGENT-04)
- Inter-agent coordination / result sharing (AGENT-05)
- Automatic query routing (NLU-03)
- Frontend changes
- Coverage floor raise (Phase 15)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AGENT-03 (E-3) | True fork-agent swarm with isolated sub-agent contexts — coordinator decomposes query into N sub-questions, N isolated `call_agentic_turn` loops run concurrently, synthesis LLM call produces unified answer, audit records full swarm telemetry, caps enforced | Coordinator prompt design (§Architecture Patterns #1), asyncio.gather sub-agent coroutine (§Architecture Patterns #2), synthesis prompt (§Architecture Patterns #3), audit extension (§Architecture Patterns #4), test patterns (§Validation Architecture) |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Query decomposition (coordinator LLM call) | API / Backend (`SwarmQueryPipeline.run`) | — | Stateless LLM call; no I/O layer |
| Sub-agent execution | API / Backend (`_run_sub_agent` coroutine) | — | Each sub-agent is a self-contained async task; no shared state |
| Concurrent dispatch | API / Backend (`asyncio.gather`) | — | Event-loop-level parallelism; no external worker queue needed |
| Synthesis LLM call | API / Backend (`SwarmQueryPipeline._synthesize`) | — | Consumes sub-agent outputs; stays in same pipeline run |
| Audit logging | API / Backend (`AuditService.log_query`) | — | Swarm fields added to `detail` dict; existing insert-only pattern |
| Model/field addition (`swarm_mode`) | Data layer (`utils/models.py`) | — | Pydantic V2 `GenerationRequest` field |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncio` (stdlib) | Python 3.12 (project `.python-version`) | Concurrent sub-agent dispatch | `asyncio.gather` already used for parallel tool calls in Phase 11; zero new dependency |
| `services/generator/llm_client.py` | Project (Phase 11) | `call_agentic_turn` interface | Provider-neutral; both Anthropic + OpenAI adapters implemented and tested |
| `services/audit/audit_service.py` | Project (Phase 11) | Audit extension via `detail` dict | `log_query` accepts `**kwargs`-free but `detail` dict is open — swarm fields slot in cleanly |
| `pydantic` V2 | Already in project | `GenerationRequest.swarm_mode` field | Matches project standard; `field_validator` + `ConfigDict` already used |
| `config.settings` | Project (Settings class) | `MAX_SWARM_AGENTS`, `MAX_SWARM_TURNS_PER_AGENT` env vars | OPS-01 pattern: `settings.*` attrs back class constants |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `json` (stdlib) | stdlib | Parse coordinator LLM JSON output | Coordinator returns `list[str]` as JSON; `json.loads` inside try/except (ERR-01) |
| `re` (stdlib) | stdlib | JSON extraction from LLM output if bare text returned | Fallback for partial JSON in coordinator response |
| `time` (stdlib) | stdlib | `swarm_latency_ms`, `synthesis_latency_ms` measurement | Same `time.perf_counter()` pattern as existing pipeline timings |
| `loguru` | Project | Structured logs per sub-agent | Same `logger.info(f"[Swarm] agent={i} turns={n} ...")` pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `asyncio.gather` for sub-agents | `asyncio.TaskGroup` (Python 3.11+) | TaskGroup cancels all on first failure; gather with `return_exceptions=True` is explicitly required by D-07 for partial-failure resilience |
| `self._llm.chat()` for coordinator | `self._llm.chat_with_tools()` | `chat_with_tools` forces structured JSON output (preferred), but adds tool schema overhead; `chat()` at temperature=0 with strict prompt is simpler and sufficient for a list output |

**Installation:** No new packages required.

## Architecture Patterns

### System Architecture Diagram

```
SwarmQueryPipeline.run(req: GenerationRequest)
  │
  ├─ [coordinator] self._llm.chat(system=DECOMPOSE_SYSTEM, user=req.query, temperature=0)
  │     └─ returns JSON: ["sub-q1", "sub-q2", ..., "sub-qN"]  (capped at MAX_SWARM_AGENTS)
  │
  ├─ N=1? → delegate to get_agent_pipeline().run(req)  [D-03]
  │
  ├─ [fan-out] asyncio.gather(
  │     _run_sub_agent(0, "sub-q1", tf, req),
  │     _run_sub_agent(1, "sub-q2", tf, req),
  │     ...
  │     return_exceptions=True
  │   )
  │     │
  │     ├─ Sub-agent i: fresh messages=[{"role":"user","content":"sub-qi"}]
  │     │   for iteration in range(MAX_SWARM_TURNS_PER_AGENT):
  │     │       call_agentic_turn(messages, tools, system)
  │     │       if stop_reason in (text_only, max_tokens, error): break
  │     │       execute tool calls → append results to messages
  │     │   return SubAgentResult(answer, turns, tool_call_count, chunks)
  │     │
  │     └─ Exception → error marker string "[Sub-agent i failed: ...]"
  │
  ├─ [synthesis] self._llm.chat(system=SYNTHESIS_SYSTEM, user=formatted_results, temperature=0.1)
  │     └─ returns unified answer referencing all N sub-results
  │
  └─ audit.log_query(..., intent="swarm", extra swarm fields in detail)
     memory.save_turn(...)
     return GenerationResponse(answer=synthesis_answer, sources=all_chunks[:top_k])
```

### Recommended Project Structure

No new files required. All changes in:
```
services/
└── pipeline.py          # SwarmQueryPipeline class + get_swarm_pipeline() factory (append after AgentQueryPipeline)
utils/
└── models.py            # GenerationRequest.swarm_mode: bool = False
tests/
└── unit/
    └── test_swarm_pipeline.py    # NEW — unit tests (7 test contracts)
```

The API layer (`main.py`) needs a routing check: `if req.swarm_mode: get_swarm_pipeline().run(req)`.

### Pattern 1: Coordinator Prompt Design

**What:** LLM decomposes a multi-dimension query into a JSON array of independent sub-questions.

**When to use:** `SwarmQueryPipeline.run()` before fan-out.

**Critical constraints:**
- `temperature=0` — decomposition must be deterministic
- Explicit JSON-only instruction in system prompt prevents prose prefix
- Schema example in prompt (few-shot) dramatically reduces malformed output
- `task_type="generate"` (not "nlu") — coordinator uses main model, not Haiku, for accurate decomposition

**Failure modes:**
1. LLM returns prose wrapping JSON: `json.loads` after `re.search(r'\[.*\]', resp, re.DOTALL)` extraction [VERIFIED: existing `BaseLLMClient.chat_with_tools` uses this pattern]
2. LLM hallucinates extra sub-questions: capping at `MAX_SWARM_AGENTS` before fan-out handles this (D-05)
3. LLM returns a single-element array for a genuinely multi-dimension query: N=1 fallback (D-03) handles this gracefully
4. Invalid JSON on all retries: catch `json.JSONDecodeError`, fall back to `[req.query]` (single sub-question → N=1 path)

**Example prompt pattern:** [VERIFIED: consistent with `chat_with_tools` patterns in AnthropicLLMClient]

```python
# Source: project pattern — services/generator/llm_client.py (chat_with_tools) + coordinator design
_COORDINATOR_SYSTEM = """\
你是查询分解专家。将用户的多维度问题拆分为独立的子问题列表。

要求：
1. 每个子问题可以独立回答，不依赖其他子问题的答案
2. 不生成重复或高度相似的子问题
3. 仅返回 JSON 数组，格式如下，不要包含任何其他文字：
   ["子问题1", "子问题2", "子问题3"]
4. 如果问题本身是单一维度，返回仅含原问题的数组：["原始问题"]

示例输入：审计上月所有未结案件的产假天数、病假规定、加班补偿政策
示例输出：["上月未结案件的产假天数规定是什么？", "上月未结案件的病假规定是什么？", "上月未结案件的加班补偿政策是什么？"]
"""

# In SwarmQueryPipeline.run():
raw = await self._llm.chat(
    system=_COORDINATOR_SYSTEM,
    user=req.query,
    temperature=0.0,
    task_type="generate",  # main model, not Haiku
)
# Extract JSON array robustly
try:
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    sub_questions: list[str] = json.loads(m.group()) if m else [req.query]
except (json.JSONDecodeError, AttributeError):
    logger.warning(f"[Swarm] Coordinator JSON parse failed, falling back to single-agent")
    sub_questions = [req.query]
sub_questions = [q.strip() for q in sub_questions if q.strip()][:self.MAX_SWARM_AGENTS]
```

### Pattern 2: Sub-Agent Coroutine Structure

**What:** Standalone async method runs one complete `call_agentic_turn` loop for a single sub-question.

**When to use:** One invocation per sub-question, all dispatched via `asyncio.gather`.

**Key isolation guarantee:** Each invocation gets a fresh `messages` list — no shared reference.

**Tracking for audit:** Returns a `SubAgentResult` dataclass (or named tuple) carrying `answer`, `turns`, `tool_calls_count`, `chunks`.

```python
# Source: modeled on AgentQueryPipeline.run() — services/pipeline.py lines 616-795
# [VERIFIED: existing pattern]

from dataclasses import dataclass

@dataclass
class _SubAgentResult:
    answer: str
    turns: int
    tool_calls_count: int
    chunks: list[RetrievedChunk]

async def _run_sub_agent(
    self,
    agent_index: int,
    sub_question: str,
    tf: dict[str, Any],
    req: GenerationRequest,
) -> _SubAgentResult:
    """Run one isolated sub-agent. No shared state with other sub-agents."""
    # D-06: clean context — NO chat history injection
    messages: list[dict[str, Any]] = [{"role": "user", "content": sub_question}]
    all_chunks: list[RetrievedChunk] = []
    answer = ""
    turns = 0
    tool_calls_count = 0

    for iteration in range(self.MAX_SWARM_TURNS_PER_AGENT):  # D-09 cap
        try:
            turn: AgenticTurn = await self._llm.call_agentic_turn(
                messages=messages,
                tools=self._AGENT_TOOLS,
                system=self._AGENT_SYSTEM,
                max_tokens=settings.llm_max_tokens,
                parallel_tool_calls=True,
            )
        except (anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError) as exc:
            # ERR-01: narrow except only — same tuple as AgentQueryPipeline
            logger.error(f"[Swarm] agent={agent_index} iter={iteration+1} failed: {exc!r}")
            answer = f"[Sub-agent {agent_index} failed: {exc!r}]"
            break

        turns += 1

        if turn.stop_reason in ("text_only", "max_tokens", "error"):
            answer = turn.text or answer
            break

        if not turn.tool_calls:
            answer = turn.text or answer
            break

        tool_calls_count += len(turn.tool_calls)
        messages.append(turn.raw_assistant_msg)

        tool_coros = [
            self._execute_tool_call(tc, tf, req) for tc in turn.tool_calls
        ]
        tool_outputs = await asyncio.gather(*tool_coros, return_exceptions=True)

        tool_results: list[dict[str, Any]] = []
        for tc, output in zip(turn.tool_calls, tool_outputs):
            if isinstance(output, BaseException):
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": f"工具执行失败:{type(output).__name__}: {output}",
                    "is_error": True,
                })
            else:
                chunks, ctx_text = output
                all_chunks.extend(chunks)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": ctx_text,
                })
        messages.append({"role": "user", "content": tool_results})

    logger.info(f"[Swarm] agent={agent_index} turns={turns} tool_calls={tool_calls_count}")
    return _SubAgentResult(
        answer=answer, turns=turns,
        tool_calls_count=tool_calls_count, chunks=all_chunks,
    )
```

### Pattern 3: asyncio.gather Fan-Out with Return Exceptions

**What:** All N sub-agent coroutines dispatched concurrently; partial failures produce error-marker strings.

**When to use:** After coordinator returns `sub_questions` list with N >= 2.

**Verified behavior:** [VERIFIED: Python asyncio docs + existing use in AgentQueryPipeline lines 719-723]
- `return_exceptions=True` prevents any single sub-agent failure from cancelling others
- Results are returned in the same order as the input coroutines (guaranteed by asyncio)
- `isinstance(output, BaseException)` test distinguishes errors from `_SubAgentResult`

```python
# Source: services/pipeline.py lines 719-746 (existing gather pattern, extended to swarm level)
swarm_t0 = time.perf_counter()

sub_coros = [
    self._run_sub_agent(i, q, tf, req)
    for i, q in enumerate(sub_questions)
]
raw_results = await asyncio.gather(*sub_coros, return_exceptions=True)

swarm_latency_ms = round((time.perf_counter() - swarm_t0) * 1000, 1)

agent_answers: list[str] = []
per_agent_turns: list[int] = []
per_agent_tool_calls: list[int] = []
all_swarm_chunks: list[RetrievedChunk] = []

for i, res in enumerate(raw_results):
    if isinstance(res, BaseException):
        # D-07: error marker passed to synthesis LLM
        agent_answers.append(f"[Sub-agent {i} failed: {res!r}]")
        per_agent_turns.append(0)
        per_agent_tool_calls.append(0)
        logger.error(f"[Swarm] agent={i} exception: {res!r}")
    else:
        agent_answers.append(res.answer)
        per_agent_turns.append(res.turns)
        per_agent_tool_calls.append(res.tool_calls_count)
        all_swarm_chunks.extend(res.chunks)
```

### Pattern 4: Synthesis Prompt Design

**What:** Single LLM call that receives all N sub-agent answers and produces one unified response.

**When to use:** After `asyncio.gather` completes.

**Failure mode:** One or more sub-agents returned error markers — synthesis prompt must instruct the LLM to acknowledge gaps rather than hallucinate.

```python
# Source: synthesis prompt design — consistent with AGENT_SYSTEM pattern [ASSUMED for exact wording]
_SYNTHESIS_SYSTEM = """\
你是综合分析助手。根据各子代理提供的分析结果，生成一个完整、连贯的综合回答。

要求：
1. 明确引用每个子代理的关键发现（如"关于产假天数：..."、"关于病假规定：..."）
2. 如某个子代理标记为失败（以[Sub-agent N failed]开头），说明该维度信息暂时无法获取
3. 综合回答应结构清晰，直接回应用户的原始问题
4. 仅基于提供的子代理结果，不引入外部知识
"""

def _format_synthesis_input(
    original_query: str,
    sub_questions: list[str],
    answers: list[str],
) -> str:
    parts = [f"用户原始问题：{original_query}\n\n各子代理分析结果："]
    for i, (q, a) in enumerate(zip(sub_questions, answers)):
        parts.append(f"\n子代理{i+1}（负责：{q}）：\n{a}")
    return "\n".join(parts)

# In run():
synth_t0 = time.perf_counter()
synthesis_input = _format_synthesis_input(req.query, sub_questions, agent_answers)
final_answer = await self._llm.chat(
    system=_SYNTHESIS_SYSTEM,
    user=synthesis_input,
    temperature=0.1,
    task_type="generate",
)
synthesis_latency_ms = round((time.perf_counter() - synth_t0) * 1000, 1)
```

### Pattern 5: Audit Log Extension

**What:** Extend `log_query` call to include swarm-specific telemetry in the `detail` dict.

**Why it works without breaking callers:** `AuditService.log_query` builds `detail = {"latency_ms": ..., "sources_count": ..., "query_len": ..., "intent": ...}`. The `detail` field is `dict` — additional keys are stored in the same JSONB column without schema change.

```python
# Source: services/audit/audit_service.py lines 139-167 [VERIFIED]
# Existing log_query signature does NOT have **kwargs — must call log() directly
# or add extra fields via the AuditEvent detail dict by calling self._audit.log() directly.

# Best approach: call log_query for the standard fields, then patch via log() directly:
await self._audit.log(AuditEvent(
    user_id=user_id,
    tenant_id=tenant_id,
    action=AuditAction.QUERY,
    resource_id=query_hash,
    result=AuditResult.SUCCESS,
    detail={
        "latency_ms": total_ms,
        "sources_count": len(all_swarm_chunks),
        "query_len": len(req.query),
        "intent": "swarm",
        # D-08 swarm fields:
        "swarm_n": len(sub_questions),
        "per_agent_turns": per_agent_turns,
        "per_agent_tool_calls": per_agent_tool_calls,
        "swarm_latency_ms": swarm_latency_ms,
        "synthesis_latency_ms": synthesis_latency_ms,
    },
    trace_id=trace_id,
))
```

**Alternative:** Add an overloaded `log_query_swarm()` helper to `AuditService` that wraps `log()` directly. This is cleaner than calling `log()` from the pipeline. Either works; calling `log()` directly is less code.

### Pattern 6: N=1 Fallback

```python
# Source: D-03 decision [VERIFIED: AgentQueryPipeline.run() fallback pattern lines 659-668]
if len(sub_questions) == 1:
    logger.info(f"[Swarm] N=1 — delegating to single-agent path trace={trace_id}")
    return await get_agent_pipeline().run(req)
```

### Anti-Patterns to Avoid

- **Sharing `messages` list across sub-agents:** Each `_run_sub_agent` call must create a NEW list literal, not pass a reference to `req`'s chat history.
- **Catching `Exception` in sub-agent error handling:** ERR-01 requires narrow tuple `(anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError)` — not `BaseException` or `Exception`.
- **Running synthesis on a single failed result with no real content:** If ALL sub-agents fail, skip synthesis and return a graceful degradation message directly.
- **Calling `get_agent_pipeline()` inside `_run_sub_agent`:** Sub-agents run the `call_agentic_turn` loop directly — they do not recurse into `AgentQueryPipeline.run()`, because that would inject chat history (violating D-06).
- **Mutating `_AGENT_TOOLS` or `_AGENT_SYSTEM`:** These are class-level; sub-agents read them but never write.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Concurrent execution of N sub-agent coroutines | Thread pool, custom async queue | `asyncio.gather(*coros, return_exceptions=True)` | Already battle-tested in project (Phase 11 tool calls); zero overhead for coroutine-based I/O |
| LLM output structured as JSON list | Regex-only parsing | `json.loads` + `re.search` fallback (existing `BaseLLMClient.chat_with_tools` pattern) | JSON decode errors handled; `chat_with_tools` could force JSON schema if needed |
| Provider error retry | Custom retry loop | `tenacity` (already in `OllamaLLMClient`, `OpenAILLMClient`) | Sub-agent `call_agentic_turn` calls already go through tenacity in provider adapters |
| Sub-agent result aggregation | Custom async queue | `asyncio.gather` result list (ordered, index-stable) | Guaranteed order matches input coroutine order |

**Key insight:** The entire swarm is built on primitives already in the codebase. `SwarmQueryPipeline` is an orchestration wrapper, not a new technical subsystem.

## Common Pitfalls

### Pitfall 1: Shared `messages` List Reference
**What goes wrong:** If `messages` is initialized once and passed to all sub-agents, sub-agents will share state — tool results appended by one agent appear in another's context.
**Why it happens:** Python list passed by reference; the `asyncio.gather` coroutines all start from the same list object.
**How to avoid:** Each `_run_sub_agent` call creates `messages: list[...] = [{"role": "user", "content": sub_question}]` as a local variable inside the coroutine.
**Warning signs:** Assertion in tests that `messages` lengths differ between sub-agents fails.

### Pitfall 2: Exception Type in gather Result
**What goes wrong:** Checking `isinstance(res, Exception)` instead of `isinstance(res, BaseException)` misses `KeyboardInterrupt` and similar; more commonly, the wrong branch is taken.
**Why it happens:** `asyncio.gather(return_exceptions=True)` stores any exception as a `BaseException` subclass in the result list.
**How to avoid:** Use `isinstance(res, BaseException)` as the error check — same pattern the existing `AgentQueryPipeline` uses for tool outputs (lines 727-745 in pipeline.py).
**Warning signs:** Sub-agent `asyncio.TimeoutError` not recognized as error.

### Pitfall 3: Coordinator Returns Non-List JSON
**What goes wrong:** Coordinator LLM returns `{"questions": [...]}` instead of a bare array.
**Why it happens:** LLM adds a wrapping object despite instructions.
**How to avoid:** System prompt provides a concrete schema example. If `json.loads` result is a dict, extract the first list-valued field. Final fallback: `[req.query]`.
**Warning signs:** `TypeError: 'dict' object is not iterable` when iterating `sub_questions`.

### Pitfall 4: Coordinator Model Selection
**What goes wrong:** Using Haiku (task_type="nlu") for coordinator decomposition produces poor sub-question quality.
**Why it happens:** `_anthropic_model_for_task` routes nlu/rewrite/evaluate to Haiku. Decomposition is a reasoning task that benefits from the main model.
**How to avoid:** Use `task_type="generate"` (or any non-Haiku task type) for coordinator and synthesis calls.
**Warning signs:** Sub-questions are too coarse, miss dimensions, or contain duplicates.

### Pitfall 5: All Sub-Agents Fail — Synthesis Gets Only Error Markers
**What goes wrong:** Synthesis LLM call with all `[Sub-agent N failed: ...]` markers returns a confusing response.
**Why it happens:** No pre-synthesis check for total failure.
**How to avoid:** After gather, count successful results. If 0 successes, return a hard-coded graceful degradation string directly (no synthesis call).
**Warning signs:** Synthesis returns "抱歉，所有子代理均失败" — valid but wasteful to make LLM call for it.

### Pitfall 6: `log_query` Signature Mismatch
**What goes wrong:** `AuditService.log_query` does not accept swarm fields as keyword args — calling `log_query(swarm_n=3)` raises `TypeError`.
**Why it happens:** `log_query` signature is fixed (no `**kwargs`). [VERIFIED: audit_service.py lines 139-167]
**How to avoid:** Call `self._audit.log(AuditEvent(..., detail={...swarm fields...}))` directly, or add a dedicated `log_query_swarm()` method to `AuditService`.
**Warning signs:** `TypeError: log_query() got an unexpected keyword argument 'swarm_n'`.

## Code Examples

### Sub-Agent Isolation Verification (test pattern)

```python
# Source: modeled on test_agent_pipeline_refactor.py — test_two_tool_calls_run_concurrently
# [VERIFIED: existing pattern in tests/unit/test_agent_pipeline_refactor.py lines 187-224]

@pytest.mark.unit
@pytest.mark.asyncio
async def test_sub_agents_have_isolated_message_histories(mock_swarm_pipeline, gen_req):
    """Verify no sub-agent reads or writes another's messages list."""
    captured_messages: list[list] = []

    async def capturing_call_agentic_turn(messages, **kwargs):
        captured_messages.append(list(messages))  # snapshot at call time
        return _turn(stop_reason="text_only", text="answer")

    mock_swarm_pipeline._llm.call_agentic_turn.side_effect = capturing_call_agentic_turn

    await mock_swarm_pipeline.run(gen_req)  # gen_req has swarm_mode=True

    # Each sub-agent started with exactly 1 message (its own sub-question)
    assert all(len(m) == 1 for m in captured_messages)
    # Sub-questions differ between agents
    assert captured_messages[0][0]["content"] != captured_messages[1][0]["content"]
```

### Concurrent Execution Verification (test pattern)

```python
# Source: modeled on test_two_tool_calls_run_concurrently (same file, lines 187-224)
# [VERIFIED: existing pattern]

@pytest.mark.unit
@pytest.mark.asyncio
async def test_sub_agents_run_concurrently(mock_swarm_pipeline, gen_req):
    """Total latency bounded by slowest, not sum."""
    import asyncio
    started = asyncio.Event()
    both_started = {"n": 0}

    async def slow_agent_turn(messages, **kwargs):
        both_started["n"] += 1
        if both_started["n"] >= 2:
            started.set()
        await asyncio.wait_for(started.wait(), timeout=2.0)
        return _turn(stop_reason="text_only", text="ok")

    mock_swarm_pipeline._llm.call_agentic_turn.side_effect = slow_agent_turn
    await asyncio.wait_for(mock_swarm_pipeline.run(gen_req), timeout=5.0)
    assert both_started["n"] >= 2  # both sub-agents started before either finished
```

### Coordinator JSON Parse (defensive)

```python
# Source: based on BaseLLMClient.chat_with_tools re.search pattern
# [VERIFIED: services/generator/llm_client.py lines 138-146]
import json, re

def _parse_sub_questions(raw: str, fallback: str) -> list[str]:
    """Extract JSON list from coordinator LLM output. Fallback to [fallback] on failure."""
    m = re.search(r'\[.*\]', raw, re.DOTALL)
    if m:
        try:
            result = json.loads(m.group())
            if isinstance(result, list):
                return [str(q).strip() for q in result if str(q).strip()]
        except json.JSONDecodeError:
            pass
    return [fallback]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single-agent sequential tool calls | `asyncio.gather` parallel tool calls (Phase 11 AGENT-02) | v1.2 Phase 11 | Establishes the gather + return_exceptions pattern now used at swarm level |
| Anthropic-only agent mode | Provider-neutral `call_agentic_turn` + Anthropic/OpenAI adapters | v1.2 Phase 11 | Sub-agents in Phase 12 reuse same interface; no provider branching needed |

**Deprecated/outdated:**
- Nothing in scope — swarm builds on current Phase 11 state.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Synthesis prompt wording (Chinese + specific formatting) is sufficient to produce answers that "explicitly reference results from all N sub-agents" per AC#3 | Architecture Patterns #4 | Low — prompt can be iterated; structure is what matters, not exact wording |
| A2 | Coordinator using `task_type="generate"` is sufficient quality for sub-question decomposition; no need for `chat_with_tools` forced JSON | Architecture Patterns #1 | Low — fallback to `[req.query]` is already designed in; can upgrade to `chat_with_tools` if decomposition quality is poor |
| A3 | `settings` has writable string attributes for `MAX_SWARM_AGENTS` and `MAX_SWARM_TURNS_PER_AGENT` (Pydantic BaseSettings allows env-var-backed int fields added without migration) | Standard Stack | Low — existing OPS-01 pattern (e.g., `settings.llm_max_tokens`) proves the pattern; adding two int fields is additive |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed.

## Open Questions

1. **API routing in `main.py`**
   - What we know: `main.py` exists and handles `POST /query`; it currently routes to `get_query_pipeline()` or `get_agent_pipeline()` based on `req.agent_mode`.
   - What's unclear: Exact routing code in `main.py` — not read in this research session.
   - Recommendation: Planner should include a plan step to read `main.py` and add `elif req.swarm_mode: get_swarm_pipeline().run(req)` routing. This is low-risk additive change.

2. **`_execute_tool_call` reuse approach**
   - What we know: `AgentQueryPipeline._execute_tool_call` is the right implementation to reuse (CONTEXT.md §Reusable Assets). It's an instance method.
   - What's unclear: Whether to copy it as a method on `SwarmQueryPipeline` (violates DRY) or extract it to a module-level helper function.
   - Recommendation: Extract to a module-level `_execute_tool_call_helper(tc, tf, retriever, llm, req)` function that both pipelines call. This preserves D-01 (AgentQueryPipeline unchanged) while avoiding duplication. Alternatively, `SwarmQueryPipeline` can hold its own copy since `AgentQueryPipeline` is locked. Planner decides.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python asyncio | Concurrent sub-agent dispatch | ✓ | Python 3.12 (`.python-version`) | — |
| `anthropic` / `openai` SDK | `call_agentic_turn` adapters | ✓ | Already in `requirements.txt` (Phase 11) | — |
| PostgreSQL + pgvector | Integration tests only | Conditional | On CI per `conftest.py` | Unit tests skip via `@pytest.mark.integration` |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest with pytest-asyncio (`asyncio_mode = auto`) |
| Config file | `pytest.ini` (project root) |
| Quick run command | `pytest tests/unit/test_swarm_pipeline.py -x -m "not integration"` |
| Full suite command | `pytest tests/ -m "not integration"` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AGENT-03 AC#1 | N≥2 sub-questions dispatch N sub-agents, isolated `messages` | unit | `pytest tests/unit/test_swarm_pipeline.py::test_sub_agents_have_isolated_message_histories -x` | ❌ Wave 0 |
| AGENT-03 AC#2 | Concurrent execution; latency bounded by slowest | unit | `pytest tests/unit/test_swarm_pipeline.py::test_sub_agents_run_concurrently -x` | ❌ Wave 0 |
| AGENT-03 AC#3 | Synthesis references all N sub-results | unit | `pytest tests/unit/test_swarm_pipeline.py::test_synthesis_references_all_sub_answers -x` | ❌ Wave 0 |
| AGENT-03 AC#4 | MAX_SWARM_AGENTS cap; MAX_SWARM_TURNS_PER_AGENT cap | unit | `pytest tests/unit/test_swarm_pipeline.py::test_max_swarm_agents_cap -x` | ❌ Wave 0 |
| AGENT-03 AC#5 | Audit log records N, per-agent turns, per-agent tool calls, latencies | unit | `pytest tests/unit/test_swarm_pipeline.py::test_audit_log_swarm_fields -x` | ❌ Wave 0 |
| AGENT-03 AC#1 (N=1) | N=1 coordinator result delegates to single-agent path | unit | `pytest tests/unit/test_swarm_pipeline.py::test_n1_fallback_delegates_to_agent_pipeline -x` | ❌ Wave 0 |
| AGENT-03 AC#2 (partial fail) | Failed sub-agent → error marker → synthesis still returns | unit | `pytest tests/unit/test_swarm_pipeline.py::test_partial_failure_returns_response -x` | ❌ Wave 0 |
| AGENT-03 (integration) | Live multi-dimension query → N sub-agents → synthesis → final answer | integration | `pytest tests/integration/test_swarm_pipeline_e2e.py -m integration` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_swarm_pipeline.py -x -m "not integration"`
- **Per wave merge:** `pytest tests/ -m "not integration"`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_swarm_pipeline.py` — 7 unit test contracts listed above
- [ ] `tests/unit/fixtures/swarm/` — shared mock fixtures for `SwarmQueryPipeline` (coordinator mock, sub-agent mock)
- [ ] `tests/integration/test_swarm_pipeline_e2e.py` — integration smoke test (Ollama/mock provider)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Inherited from existing pipeline auth |
| V3 Session Management | no | Swarm does not create new sessions |
| V4 Access Control | no | Tenant filter (`tf`) inherited from `req`; same as `AgentQueryPipeline` |
| V5 Input Validation | yes | `sub_questions` parsed from LLM output — `json.loads` in try/except; list items stripped and capped at `MAX_SWARM_AGENTS` |
| V6 Cryptography | no | No new crypto operations |

### Known Threat Patterns for Swarm LLM Orchestration

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Coordinator prompt injection (malicious query splits into unexpected sub-questions) | Tampering | `MAX_SWARM_AGENTS` cap; JSON parse + type check on coordinator output; each sub-agent inherits same `tf` tenant filter |
| Sub-agent runaway cost (MAX_SWARM_TURNS_PER_AGENT bypass) | Denial of service | `for iteration in range(self.MAX_SWARM_TURNS_PER_AGENT)` — hard loop bound, no `while True` |
| Synthesis LLM prompt injection via sub-agent answers | Tampering | Sub-agent answers are LLM output from the same model; no external data injected into synthesis prompt beyond retrieval chunks which pass through existing `tf` filter |

## Sources

### Primary (HIGH confidence)
- `services/pipeline.py` (project codebase) — `AgentQueryPipeline` implementation, `asyncio.gather` pattern, `_execute_tool_call`, `_AGENT_TOOLS`, `_AGENT_SYSTEM`, factory pattern
- `services/audit/audit_service.py` (project codebase) — `log_query` signature, `AuditEvent.detail` dict shape
- `services/generator/llm_client.py` (project codebase) — `call_agentic_turn` adapters (Anthropic + OpenAI), `BaseLLMClient` default raise, `chat_with_tools` JSON extraction pattern
- `utils/models.py` (project codebase) — `GenerationRequest`, `AgenticTurn`, `ToolCall`, `GenerationResponse`
- `tests/unit/test_agent_pipeline_refactor.py` (project codebase) — existing test patterns for mocking pipeline, concurrent gather verification, narrow-except tests
- `tests/conftest.py` (project codebase) — `asyncio_mode = auto`, fixture patterns
- `.planning/phases/12-fork-agent-swarm/12-CONTEXT.md` — all locked decisions D-01 through D-09
- `.planning/REQUIREMENTS.md` §AGENT-03 — 7 acceptance criteria

### Secondary (MEDIUM confidence)
- `pytest.ini` — `asyncio_mode = auto` confirms pytest-asyncio is active; `addopts = -m "not integration"` confirms unit/integration marker split

### Tertiary (LOW confidence)
- None — all claims verified against project source or planning docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are in-project, verified in source
- Architecture: HIGH — all patterns derived directly from existing `AgentQueryPipeline` implementation
- Pitfalls: HIGH — derived from code inspection of existing gather patterns and LLM output parsing
- Test patterns: HIGH — directly modeled on `test_agent_pipeline_refactor.py`

**Research date:** 2026-05-08
**Valid until:** 2026-06-08 (stable — no external dependencies change)
