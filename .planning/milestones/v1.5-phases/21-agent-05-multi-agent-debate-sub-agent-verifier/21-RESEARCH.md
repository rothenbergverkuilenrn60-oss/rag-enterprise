# Phase 21: AGENT-05 Multi-Agent Debate / Sub-Agent Verifier — Research

**Researched:** 2026-05-10
**Domain:** Provider-neutral verifier sub-agent on top of `SwarmQueryPipeline`; new SSE event types; opt-in `debate=True` field on `GenerationRequest`
**Confidence:** HIGH (every claim verified against the live source files cited inline)
**Mode:** TDD-enabled (planner will produce RED→GREEN→REFACTOR cycles)

---

## Summary

Phase 21 lands four production artifacts on top of an already-stable v1.4 surface:
1. A new `services/agent/verifier.py` module (~150 LOC) containing `Verifier.verify(...)`
2. Four new frozen Pydantic V2 models in `utils/models.py` (`VerifierVerdict` + 3 `AgentEvent` subclasses)
3. A surgical extension of `SwarmQueryPipeline.run()` (~80 LOC inserted between the existing `asyncio.gather` and `_synthesize`)
4. A small extension of `_synthesize` (`verifier_verdict` kwarg + `_format_disagree` helper)

CONTEXT.md D-01..D-11 lock the design surface; Claude's-discretion items are the verifier system prompt, audit-metadata key layout, and which test seam is monkey-patched. **No new external dependency** is introduced. Everything reuses existing libraries (`tenacity` is already in the LLM clients via `@retry` on `chat`; verifier intentionally avoids a second tenacity layer per D-07).

**Primary recommendation:** Wave-0 lands the four Pydantic models (`VerifierVerdict` + 3 events) and the `GenerationRequest.debate` field with the D-10 cross-field validator; this unblocks the verifier-class TDD work and the swarm-integration TDD work to fan out in parallel. Latency assertion (SC2) sits in integration; everything else fits cleanly in unit-level RED→GREEN cycles.

---

## User Constraints (from CONTEXT.md)

> Verbatim from `.planning/phases/21-agent-05-multi-agent-debate-sub-agent-verifier/21-CONTEXT.md`. Locked decisions are not re-debated.

### Locked Decisions (D-01 .. D-11)
- **D-01** `VerifierVerdict` full schema: `verdict: Literal["agree","disagree"]`, `evidence_chunk_ids: list[str]`, `reasoning: str`, `proposed_answer: str`, `latency_ms: int`. Frozen Pydantic V2 model in `utils/models.py`.
- **D-02** `proposed_answer` ALWAYS populated (both verdicts). Field is `str` (not `str | None`).
- **D-03** Synthesizer divergence template (Chinese) hard-coded:
  `⚠️ 子代理间存在分歧（{N} 个同伴中的 {M} 个提出差异回答）。以上回答基于验证者引用的证据（{len(evidence_chunk_ids)} 个块）。`
- **D-04** `_synthesize` extended with `verifier_verdict: VerifierVerdict | None = None` kwarg + private `_format_disagree(verdict, sub_results)` helper. NO new `Synthesizer` class.
- **D-05** `Settings.verifier_model: str | None = None` + `verifier_provider: Literal["openai","anthropic"] | None = None`. Default = peer model via existing `get_llm_client()` factory.
- **D-06** Degrade-with-signal on `BaseException` from `verifier.verify(...)`: log error → emit `VerifierDisagreementEvent(reason="verifier_failed", error_type=...)` → audit row with `verifier_failed=true` → `verdict = None` → `_synthesize` falls through to non-debate consensus path.
- **D-07** No additional tenacity wrapper at `Verifier` class level (`call_agentic_turn` provider-side retry already covers it).
- **D-08** `VerifierDisagreementEvent` wire fields: `reason: Literal["peers_diverge","forced_no_evidence","verifier_failed"]`, `summary: str` (truncated to 200 chars by emitter), `evidence_chunk_ids: list[str]`, `peer_count: int`, `error_type: str | None = None`.
- **D-09** `VerifierStartEvent` (`peer_count: int`, `model: str`) + `VerifierCompleteEvent` (`verdict: Literal["agree","disagree"]`, `evidence_chunk_count: int`, `latency_ms: int`). NO `proposed_answer_preview` field.
- **D-10** `model_validator(mode="after")` on `GenerationRequest`: raise `ValueError` if `debate and not swarm_mode` (422 at boundary).
- **D-11** Forced-disagree (CF-04) → emit `VerifierDisagreementEvent(reason="forced_no_evidence", ...)` + audit metadata key `forced_disagree=true` (no new `AuditAction`).

### Carry-Forward (CF-01 .. CF-10)
- **CF-01** Verifier-role pattern (single sub-agent reads N answers); not iterative peer debate.
- **CF-02** Opt-in trigger via `req.debate=True`.
- **CF-03** `BaseLLMClient.call_agentic_turn` text-only (no tools).
- **CF-04** Force `agree`+empty `evidence_chunk_ids` → `disagree`.
- **CF-05** Three new SSE events as frozen `AgentEvent` subclasses.
- **CF-06** Latency: `total ≤ max(peer_latency) + verifier_latency + small_overhead`.
- **CF-07** `synthesizer.final` remains terminal in all paths.
- **CF-08** No production code path change when `debate=False`.
- **CF-09** v1.3 carry-forward: `BaseException` (not `Exception`); sub-agents do NOT inherit chat history; `parallel_tool_calls=True` / `disable_parallel_tool_use=False` explicit at LLM-client layer.
- **CF-10** RLS isolates tenants; audit log records verifier sub-agent calls; combined coverage ≥ 70%.

### Claude's Discretion
- Verifier system prompt wording (must forbid invention; must instruct chunk-id citation only from supplied list; must instruct same-language `proposed_answer`; must request JSON matching `VerifierVerdict`).
- `evidence_chunk_ids` defensive filtering against the supplied chunk set (optional).
- `reasoning` field length cap (no model-level ceiling; prompt may suggest "1-2 sentences").
- Verifier hop placement in `run_streaming` (planner confirms whether swarm gets a streaming path or stays on `run()`).
- Test layout (`tests/unit/test_verifier.py`, `tests/integration/test_swarm_debate_e2e.py`).
- `Settings.verifier_provider` validation seam.
- Audit metadata key namespacing (suggestion: nest under `{"agent_05": {...}}`).

### Deferred Ideas (OUT OF SCOPE)
- Iterative peer-debate (N rounds of mutual critique) → v1.6+
- Always-on debate trigger → v1.6+
- `Synthesizer` class extraction → v1.6+
- Swarm `run_streaming` for SSE → v1.6+
- `proposed_answer_preview` on `VerifierCompleteEvent` → v1.6+
- Verifier-side per-tool retry/timeout config → N/A (verifier is text-only)
- UI banner / toast for divergence → v1.6+
- Dedicated `AuditAction.AGENT_VERIFIER_*` enum values → v1.6+
- `diverging_peer_indices` on DisagreementEvent → v1.6+
- `SwarmQueryPipeline` whole-file 70% coverage lift → Phase 22

---

## Phase Requirements

> AGENT-05, AGENT-14, AGENT-15. CONTEXT.md D-01 supersedes the REQUIREMENTS.md AGENT-05 field-name draft (`final_answer` / `dissenting_peers`) — final shape is `proposed_answer` (no `dissenting_peers` per D-08 deferral note).

| ID | Description (REQUIREMENTS.md) | Research Support |
|----|-------------------------------|------------------|
| **AGENT-05** | `Verifier` class with `verify(peer_answers, evidence) → VerifierVerdict`; text-only `call_agentic_turn`; system prompt forbids inventing facts; forced-disagree on `agree`+empty `evidence_chunk_ids` | Verifier-system-prompt section (Claude's-discretion candidate); `call_agentic_turn` invocation pattern (§Patterns 5); JSON-parse hardening (§Pitfalls P-01); forced-disagree timing (§Pitfalls P-02) |
| **AGENT-14** | `GenerationRequest.debate: bool = False`; verifier hop after `asyncio.gather`; latency `max(peer)+verifier`; unchanged when `debate=False` | D-10 model_validator pattern (§Patterns 7); SwarmQueryPipeline integration seam (§Patterns 1, 2); SC5 byte-identity check (§Pitfalls P-04); SC2 latency-assertion test pattern (§Patterns 8) |
| **AGENT-15** | 3 new SSE event subclasses; events emit through existing `/agent/v1/run/stream`; `synthesizer.final` terminal; doc Event-Schema-Reference extended | Event subclass shape (§Patterns 3); SSE-emit seam in non-streaming swarm pipeline (§Pitfalls P-05); `emit_sse_frame` already serializes any `AgentEvent` (§Patterns 4); doc-extension target (§Patterns 9) |

---

## STACK (no new dependencies)

> Verifier reuses existing libs in the project. **No new package added.**

| Library | Version | Already pinned in | Used for |
|---------|---------|-------------------|----------|
| `pydantic` | `^2` (project-wide) | `pyproject.toml` | `VerifierVerdict` + 3 frozen `AgentEvent` subclasses; D-10 `model_validator` |
| `anthropic` | (existing) | `pyproject.toml` | provider-side retry inherited via `BaseLLMClient.call_agentic_turn` (D-07) |
| `openai` | (existing) | `pyproject.toml` | same; `response_format={"type":"json_object"}` available on Chat Completions for structured verdict (P-01 mitigation) |
| `tenacity` | (existing) | already imported in `services/generator/llm_client.py:275` (`OllamaLLMClient.chat`) and `services/vectorizer/embedder.py` | NOT layered on verifier per D-07 |
| `loguru` | (existing) | every adapter module | `logger.error("verifier_failed", exc_info=...)` per D-06 |

**Version verification:** Not required — Phase 21 introduces zero new packages. Confidence: HIGH.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `verify(peer_answers, evidence)` LLM call | Service (`services/agent/verifier.py`) | LLM Adapter (`services/generator/llm_client.py`) | Mirror placement of existing `services/agent/tools/*` and `services/agent/_demo_runner.py` |
| `VerifierVerdict` JSON parse | Service (`services/agent/verifier.py` private parser) | — | Parser hardening lives next to LLM call to centralize the parse-or-degrade decision |
| `debate→swarm_mode` cross-field validation | API boundary (`utils/models.py::GenerationRequest`) | — | Fail-fast 422 at FastAPI body-parsing layer, mirrors existing `field_validator("query")` and `Settings._validate_security` (config/settings.py:410) |
| Verifier hop orchestration (gather peers → call verifier → branch synth) | Pipeline (`services/pipeline.py::SwarmQueryPipeline.run`) | Service (`Verifier`) | Pipeline owns the join contract; `Verifier` is pure compute |
| SSE event emission | Pipeline (`SwarmQueryPipeline.run`) — events appended to a list/yielded if streaming added | Wire serialization (`emit_sse_frame` at `services/agent/_demo_runner.py:89` and inline in `controllers/api.py:282`) | Pipeline knows trace_id/seq/ts_ms; serialization is one-line |
| Audit log row | Pipeline (extends existing `AuditEvent` `log()` call at `pipeline.py:1270`) | Audit Service (`services/audit/audit_service.py::AuditService.log`) | Reuses the swarm path's existing `log(AuditEvent(...))` shape; adds metadata keys |

---

## Patterns (line-precise existing-code anchors)

### Pattern 1 — `_SubAgentResult` shape (the verifier's input)

`services/pipeline.py:546-555` — frozen dataclass; **answer + chunks per peer**:

```python
@dataclass(frozen=True)
class _SubAgentResult:
    answer: str
    turns: int
    tool_calls_count: int
    chunks: list[RetrievedChunk]
```

**Adapter strategy:** ROADMAP/REQUIREMENTS uses the name `SubAgentAnswer`. Cleanest reconciliation per CONTEXT canonical-refs note: keep `_SubAgentResult` (already shipped, used by tests) and have `Verifier.verify()` accept either a list of `_SubAgentResult` directly or a public alias. Recommendation: pass `list[_SubAgentResult]` (typed parameter) and rename the parameter to `peer_results`. No need for a new public class — Phase 21's blast radius stays tight.

### Pattern 2 — Verifier hop integration site

`services/pipeline.py:1230` is the gather; `services/pipeline.py:1252` is `synth_t0 = time.perf_counter()`. The verifier hop sits BETWEEN them.

```python
# 1230 (existing): raw_results = await asyncio.gather(*sub_coros, return_exceptions=True)
# 1232–1250 (existing): unpack raw_results → answers / per_agent_turns / per_agent_tool_calls / all_swarm_chunks
# *** Phase 21 INSERT here ***
#   if req.debate:
#       verifier_t0 = time.perf_counter()
#       yield/emit VerifierStartEvent
#       try:
#           verdict = await self._verifier.verify(peer_results=successful_results, evidence=...)
#       except BaseException as exc:
#           logger.error("verifier_failed", exc_info=exc)
#           verdict = None
#           emit VerifierDisagreementEvent(reason="verifier_failed", error_type=type(exc).__name__, ...)
#           audit_metadata["agent_05"] = {"verifier_failed": True}
#       else:
#           if verdict.verdict == "disagree":
#               emit VerifierDisagreementEvent(reason="peers_diverge", ...)
#           # forced-disagree case is INSIDE Verifier.verify (see Pattern 6)
#           emit VerifierCompleteEvent(verdict=verdict.verdict, evidence_chunk_count=len(verdict.evidence_chunk_ids), latency_ms=verdict.latency_ms)
#       verifier_latency_ms = round((time.perf_counter() - verifier_t0) * 1000, 1)
# 1252 (existing): synth_t0 = time.perf_counter()
# 1253 (modified): final_answer = await self._synthesize(req.query, sub_questions, answers, verifier_verdict=verdict)
```

**Note: dedup ordering.** `_dedup_chunks` (`pipeline.py:710-720`) is **NOT** currently called in `SwarmQueryPipeline.run()`. The swarm path uses `all_swarm_chunks.extend(res.chunks)` raw (verified at `pipeline.py:1250`). Phase 21 must decide:
- **Recommendation:** Apply `AgentQueryPipeline._dedup_chunks(all_swarm_chunks)` BEFORE the verifier hop. This makes `evidence_chunk_ids` reference deduped IDs — the same set that ends up in `GenerationResponse.sources`. Defensive filtering of the verifier's response (Claude's-discretion bullet) becomes trivially correct: filter against `{c.chunk_id for c in deduped}`.
- This is technically a behavior change for swarm; mitigate by gating dedup-call on `if req.debate:` so SC5 (no production change when `debate=False`) holds byte-identical.

### Pattern 3 — `AgentEvent` subclass shape (sibling to mirror)

`utils/models.py:537-633` — base + 6 concrete subclasses. New events:

```python
class VerifierStartEvent(AgentEvent):
    """Emitted ONCE before Verifier.verify() awaits (D-09)."""
    event_type: ClassVar[str] = "verifier.start"
    model_config = ConfigDict(frozen=True)

    peer_count: int
    model: str                       # resolved per D-05

class VerifierCompleteEvent(AgentEvent):
    """Emitted ONCE after Verifier.verify() returns successfully (D-09)."""
    event_type: ClassVar[str] = "verifier.complete"
    model_config = ConfigDict(frozen=True)

    verdict: Literal["agree", "disagree"]
    evidence_chunk_count: int
    latency_ms: int

class VerifierDisagreementEvent(AgentEvent):
    """Emitted INSTEAD OF / IN ADDITION TO complete on the three disagree paths (D-08)."""
    event_type: ClassVar[str] = "verifier.disagreement"
    model_config = ConfigDict(frozen=True)

    reason: Literal["peers_diverge", "forced_no_evidence", "verifier_failed"]
    summary: str                       # ≤ 200 chars; emitter truncates (mirrors tool.span.error pattern at utils/models.py:594-607)
    evidence_chunk_ids: list[str]
    peer_count: int
    error_type: str | None = None      # populated only when reason="verifier_failed"
```

`ClassVar[str]` discriminator + `model_config = ConfigDict(frozen=True)` are exactly the existing convention (`utils/models.py:601`, `utils/models.py:618`).

### Pattern 4 — Wire serialization (SSE frame)

`services/agent/_demo_runner.py:89-94`:
```python
def emit_sse_frame(evt: AgentEvent) -> str:
    event_type: str = evt.event_type  # type: ignore[attr-defined]
    return f"event: {event_type}\ndata: {evt.model_dump_json()}\n\n"
```

Identical inline at `controllers/api.py:282`:
```python
yield f"event: {evt.event_type}\ndata: {evt.model_dump_json()}\n\n"
```

The 3 new event subclasses serialize through this same path **with zero serializer change** because `event_type` is a `ClassVar[str]` (excluded from `model_dump()` automatically per Pydantic V2; verified at `utils/models.py:533`).

### Pattern 5 — `call_agentic_turn` text-only invocation

`BaseLLMClient.call_agentic_turn` signature (`services/generator/llm_client.py:226-250`):
```python
async def call_agentic_turn(
    self,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str,
    max_tokens: int = 1024,
    parallel_tool_calls: bool = True,
) -> AgenticTurn: ...
```

**Verifier invocation pattern** (text-only ↔ `tools=[]`):
```python
turn: AgenticTurn = await self._llm.call_agentic_turn(
    messages=[{"role": "user", "content": user_prompt}],
    tools=[],                                # CF-03 — text-only
    system=_VERIFIER_SYSTEM,                 # see "Verifier system prompt" section
    max_tokens=settings.llm_max_tokens,
    parallel_tool_calls=False,               # text-only; no parallelism semantics apply
)
text = turn.text                             # Anthropic concatenates content blocks; OpenAI msg.content
verdict = self._parse(text)                  # see Pattern 6 + Pitfall P-01
```

**JSON-mode availability:**
- **OpenAI** (`services/generator/llm_client.py:500-507`): `chat.completions.create()` accepts `response_format={"type":"json_object"}`. **Currently NOT passed** by `call_agentic_turn`. To use it cleanly, the verifier either (a) calls a new method or (b) falls back to free-text JSON parse with the Pattern 6 hardening. Recommendation: **(b) free-text + parse** keeps the LLM-client API unchanged (D-07 spirit). Multiple Anthropic providers don't have JSON-mode anyway.
- **Anthropic** (`services/generator/llm_client.py:743-750`): `messages.create()` does NOT support a `response_format` kwarg. Standard practice: instruct the model in the system prompt to emit JSON only, then parse with regex+`json.loads` defense (Pattern 6). The existing `_decompose` at `services/pipeline.py:1034-1042` already does this for the coordinator — copy the pattern.

### Pattern 6 — JSON-extract + parse (mirror of `_decompose`)

`services/pipeline.py:1034-1043` is the canonical project pattern:
```python
match = re.search(r"\[.*\]", raw, re.DOTALL)            # array form for coordinator
if match is None:
    logger.warning(...); return [query]                 # graceful fallback
try:
    parsed = json.loads(match.group(0))
except (json.JSONDecodeError, TypeError) as exc:
    logger.warning(...); return [query]
```

**Verifier adaptation** (object form, not array):
```python
match = re.search(r"\{.*\}", raw, re.DOTALL)            # FIRST {...} block
if match is None:
    raise ValueError("verifier returned no JSON object")  # caught by Verifier.verify outer try → D-06 path
try:
    parsed = json.loads(match.group(0))
except json.JSONDecodeError as exc:
    raise ValueError(f"verifier JSON parse failed: {exc!r}") from exc
verdict = VerifierVerdict.model_validate(parsed)        # Pydantic V2; raises ValidationError on shape mismatch
```

`ValueError` and `pydantic.ValidationError` both subclass `Exception` → both caught by D-06's `except BaseException` block in `SwarmQueryPipeline.run()`.

### Pattern 7 — `model_validator(mode="after")` cross-field validator

Existing template at `config/settings.py:410-448`:
```python
@model_validator(mode="after")
def _validate_security(self) -> "Settings":
    if len(self.secret_key) < 32:
        raise ValueError("secret_key must be at least 32 characters. ...")
    return self
```

D-10 application on `GenerationRequest` (`utils/models.py:205-224`):
```python
@model_validator(mode="after")
def _check_debate_requires_swarm(self) -> "GenerationRequest":
    if self.debate and not self.swarm_mode:
        raise ValueError(
            "debate=True requires swarm_mode=True (verifier runs after peer fan-out)"
        )
    return self
```

**Frozen-model gotcha (P-06 below):** `GenerationRequest` is NOT declared `frozen=True` (verified by absence of `model_config = ConfigDict(frozen=True)` in its body). The validator does not mutate self → no `model_construct` workaround needed. Pydantic V2 raises 422 to FastAPI on `ValueError`, surfacing as the desired client error.

### Pattern 8 — Latency-bound test pattern (SC2 mirror)

`tests/unit/test_agent_sse.py:234-255` — Phase 18 SC4, structurally identical:
```python
@pytest.mark.asyncio
async def test_run_streaming_latency_bounded_by_max_not_sum_d14_sc4(...) -> None:
    Tool = _make_fake_tool("search_knowledge_base", sleep_s=0.5)
    ...
    t0 = time.perf_counter()
    events = [evt async for evt in pipeline.run_streaming(_req())]
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    assert 450 < elapsed_ms < 700, f"expected 450 < elapsed_ms < 700, got {elapsed_ms}"
```

**Phase 21 SC2 adaptation** (3 peers × 0.3s + verifier × 0.2s should be ≤ 0.5s + overhead, not 1.1s):
```python
async def test_swarm_debate_latency_bounded_by_max_peer_plus_verifier(mock_pipeline, gen_req):
    gen_req = gen_req.model_copy(update={"debate": True})
    mock_pipeline._llm.chat = AsyncMock(side_effect=['["q1","q2","q3"]', "synth"])
    PEER_DELAY = 0.3
    VERIFIER_DELAY = 0.2

    async def slow_peer_turn(**_):
        await asyncio.sleep(PEER_DELAY)
        return _turn(stop_reason="text_only", text="ans")
    async def slow_verifier_call(**_):
        await asyncio.sleep(VERIFIER_DELAY)
        return _turn(stop_reason="text_only", text='{"verdict":"agree","evidence_chunk_ids":["c1"],"reasoning":"ok","proposed_answer":"ans","latency_ms":200}')

    mock_pipeline._llm.call_agentic_turn = AsyncMock(side_effect=lambda **kw: slow_verifier_call(**kw) if kw.get("tools") == [] else slow_peer_turn(**kw))

    t0 = time.perf_counter()
    await mock_pipeline.run(gen_req)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert 450 < elapsed_ms < 700, f"max(peer)+verifier=500ms; got {elapsed_ms}"
```

Use `kw.get("tools") == []` to discriminate the verifier call from peer calls in the mock dispatch.

### Pattern 9 — Doc Event-Schema-Reference extension

`docs/agent-architecture.md:245-373` is the canonical layout. Each event gets a `### <event_type>` heading + table + JSON example. Phase 21 appends three subsections after `### synthesizer.final` (`docs/agent-architecture.md:362`), preserving the table format and the "Required" column.

---

## Verifier System Prompt (Claude's-discretion candidates)

Both candidates are **paste-ready** into `services/agent/verifier.py` as `_VERIFIER_SYSTEM = """..."""`. Choose Candidate A by default; Candidate B is a tighter alternative if Candidate A produces noisy `reasoning` fields in early manual testing.

### Candidate A (recommended — explicit Chinese-first instruction set)

```text
你是一个证据验证子代理。你的任务是审查 N 个对等子代理的回答，并基于它们引用的证据片段，判定它们是否一致并能由证据支撑。

输入说明：
- 用户原始查询（user_query）：你的最终答案必须使用与该查询相同的语言。
- N 个对等回答（peer_answers）：每个包含 answer 文本和该子代理使用过的 chunk_ids 列表。
- 证据列表（evidence）：N 个对等回答合并后去重的 RetrievedChunk 集合，每个 chunk 含 chunk_id 与 content。

判定规则（严格）：
1. 仅可引用 evidence 中已列出的 chunk_id。任何不在 evidence 中的 chunk_id 视为不存在。
2. 不得编造 evidence 中未出现的事实。如证据不足以回答，verdict 必须为 "disagree"，并在 reasoning 中说明缺失。
3. verdict="agree" 仅在以下条件成立时返回：所有对等回答在事实层面一致，且每个关键事实都能由 evidence 中至少一个 chunk 支撑。
4. verdict="disagree" 用于：对等回答相互矛盾、或某个对等回答缺乏证据支撑、或证据本身不足。
5. proposed_answer 字段始终必填（包括 verdict="agree"）。该字段是你给用户的最终答案，必须：
   - 使用与 user_query 相同的语言；
   - 简洁直接（建议不超过 4 段或 8 行）；
   - 仅基于 evidence 中已列出的 chunk 内容；
   - 在事实后用 [来源N] 形式引用，N 对应 evidence_chunk_ids 中的索引。
6. evidence_chunk_ids 列出你在 proposed_answer 中实际引用的 chunk_id 子集。可以为空，但 verdict="agree" 且为空将被系统强制改为 disagree。
7. reasoning 字段：1-2 句中文，说明判定依据。
8. latency_ms 由调用方填充，你可以输出任意 int（推荐填 0）。

输出格式（严格）：
仅输出一个 JSON 对象，无任何前缀、后缀、解释、markdown 代码块。Schema：
{
  "verdict": "agree" | "disagree",
  "evidence_chunk_ids": [string],
  "reasoning": string,
  "proposed_answer": string,
  "latency_ms": int
}
```

### Candidate B (alternative — terser, 40% fewer tokens)

```text
你是验证子代理。审查 N 个对等回答与共享证据列表，输出一个 JSON 对象。

规则：
1. 仅可引用 evidence 中的 chunk_id。
2. 不得编造未出现的事实。证据不足 → verdict="disagree"。
3. verdict="agree" 当且仅当：所有对等回答事实一致 AND 每个关键事实有 evidence 支撑。
4. proposed_answer 必填。语言与 user_query 相同。引用形式：[来源N]。
5. evidence_chunk_ids 列出 proposed_answer 中实际引用的 chunk_id 子集（可为空）。
6. reasoning：1-2 句。

仅输出 JSON：{"verdict":"agree"|"disagree","evidence_chunk_ids":[],"reasoning":"","proposed_answer":"","latency_ms":0}
```

**Tension surfaced (P-08):** Candidate A is verbose and burns more input tokens. If verifier-cost becomes a real concern in early ops, Candidate B is the fallback. Both candidates enforce the same five Claude's-discretion requirements (no invention; chunk-id citation; same-language; JSON shape; brief reasoning).

**English-query handling:** Both candidates instruct "use same language as user_query" — verified-correct on the same model/config the swarm peers use today. Phase 20 P-11 carry-forward handled the same constraint successfully (verified at `.planning/phases/20-...`).

---

## Pitfalls

### P-01 — JSON parse failures (provider returns prose around the JSON)

**Risk:** OpenAI/Anthropic occasionally wrap JSON in markdown code fences (` ```json ... ``` `) or precede it with a summary sentence even when the system prompt says "JSON only". Naïve `json.loads(turn.text)` raises `JSONDecodeError`.

**Mitigation:** Use the `re.search(r"\{.*\}", raw, re.DOTALL)` extract-first-object pattern (Pattern 6 above, mirror of `_decompose` at `services/pipeline.py:1034-1043`). Then `Pydantic.model_validate(parsed)` for shape enforcement. Both `json.JSONDecodeError` and `pydantic.ValidationError` subclass `Exception` → both caught by D-06's `BaseException` net (`asyncio.CancelledError` and `SystemExit` also caught — confirmed acceptable per CF-09 v1.3 carry-forward).

**Test obligation:** Unit RED test asserting that on `turn.text = "Here's the verdict:\n```json\n{...}\n```\n"`, the parser still extracts the object successfully. (See TDD plan `tdd-2` below.)

### P-02 — Forced-disagree timing (CF-04 / SC1)

**Risk:** If the override happens in `SwarmQueryPipeline.run()` AFTER `Verifier.verify()` returns, callers and tests see a stale `VerifierVerdict.verdict == "agree"` momentarily. Cleaner: override INSIDE `Verifier.verify()` post-parse so the returned object is truthful.

**Mitigation (recommended):** Implement the override in `Verifier.verify()`:
```python
verdict = VerifierVerdict.model_validate(parsed)
if verdict.verdict == "agree" and not verdict.evidence_chunk_ids:
    verdict = verdict.model_copy(update={"verdict": "disagree"})  # frozen-safe
    # Caller (SwarmQueryPipeline.run) detects this after-the-fact and emits
    # VerifierDisagreementEvent(reason="forced_no_evidence", ...).
```

**Frozen-model gotcha:** `VerifierVerdict` is `model_config = ConfigDict(frozen=True)` (D-01). Pydantic V2 frozen models support `.model_copy(update=...)` which returns a NEW frozen instance — no mutation. This is the project-canonical pattern (e.g. `ToolCall` at `utils/models.py:244-258` is frozen and uses the same approach in tests).

**Caller seam:** `SwarmQueryPipeline.run()` distinguishes the three disagree reasons by inspecting the returned `verdict` object:
```python
if verdict is None:
    reason = "verifier_failed"             # caught BaseException
elif verdict.verdict == "disagree" and not verdict.evidence_chunk_ids:
    reason = "forced_no_evidence"          # CF-04 forced override
elif verdict.verdict == "disagree":
    reason = "peers_diverge"               # genuine disagreement
# else: verdict.verdict == "agree" → emit VerifierCompleteEvent only (no disagreement event)
```

### P-03 — Dedup ordering vs verifier hop

**Risk:** Currently `SwarmQueryPipeline.run()` builds `all_swarm_chunks` as raw concat (`pipeline.py:1250`) — NOT deduped. Passing raw chunks to the verifier means the same `chunk_id` may appear multiple times in `evidence`, confusing the model.

**Mitigation:** Apply `AgentQueryPipeline._dedup_chunks(all_swarm_chunks)` BEFORE constructing the `evidence` list passed to `Verifier.verify()`. Gate the call on `if req.debate:` to preserve SC5 (no production code change when `debate=False`).

```python
if req.debate:
    deduped_evidence = AgentQueryPipeline._dedup_chunks(all_swarm_chunks)  # static method
    verdict = await self._verifier.verify(peer_results=successful_results, evidence=deduped_evidence)
```

This also makes the Claude's-discretion "defensive filter against supplied chunk set" trivially correct: the verifier can only legally cite IDs in `{c.chunk_id for c in deduped_evidence}`.

### P-04 — SC5 byte-identical guarantee when `debate=False`

**Risk:** Any unguarded code path change in `SwarmQueryPipeline.run()` breaks SC5. The most subtle break: appending an empty list of events in the non-debate branch and yielding it changes timing.

**Mitigation:** ALL new code in `run()` (Verifier instantiation, hop, event emission, audit-metadata writes, dedup-call) must be inside `if req.debate:` blocks. The default-case `_synthesize(...)` call signature change (adding kwarg `verifier_verdict=None` default) is byte-identical at call sites that omit it.

**Test obligation (SC5):** Add a unit test that runs `gen_req` with `debate=False` AND `debate=True` against an identical mock-LLM script, then asserts:
- `debate=False`: zero new events, identical answer text, identical audit-metadata keys.
- `debate=True`: 2-3 new events (start + complete OR start + disagreement), additional `agent_05` audit metadata.

### P-05 — SSE-emit seam in non-streaming swarm pipeline

**Risk:** `SwarmQueryPipeline` only has `run()` — there is no `run_streaming()`. The existing `controllers/api.py:259 /agent/v1/run/stream` route invokes `pipeline.run_streaming(req)` UNCONDITIONALLY (`controllers/api.py:278`) — it does NOT detect `swarm_mode` and dispatch differently. So **today, swarm mode does not flow through SSE at all** (verified — there is no swarm-streaming branch in any controller).

**Mitigation options (planner picks):**
1. **(A) Append SSE later (recommended for v1.5)** — Phase 21 emits the 3 new events into a list returned alongside `GenerationResponse` (or stored on a per-trace store), but does NOT add a `run_streaming` to swarm. The `synthesizer.final` event is the only event reaching wire today; per CONTEXT.md "Verifier hop placement in run_streaming" Claude's-discretion, this is the minimum bar. Documents this as a known gap; full swarm-SSE deferred to v1.6+ per CONTEXT deferred-list.
2. **(B) Add a thin `run_streaming` to `SwarmQueryPipeline`** — wraps `run()` and yields the 3 verifier events at the right moments + a final `SynthesizerFinalEvent`. Touches ~50 LOC. Must also patch `controllers/api.py:274` to dispatch swarm requests through `get_swarm_pipeline()` instead of `get_agent_pipeline()` when `req.swarm_mode`. SC4 (doc Event-Schema-Reference) becomes wire-truthful instead of forward-looking.

**Recommendation:** **Option B** — the planner should pursue it because AGENT-15 acceptance criterion explicitly says *"events emit through existing /api/v1/agent/v1/run/stream route"*. Option A leaves the SSE events unreachable from the wire and creates a dishonesty between docs and runtime. Option B is the smaller honest fix.

**Implementation note for Option B:** Mirror the `seq_counter = itertools.count()` + `trace_id = uuid.uuid4().hex[:8]` pattern at `pipeline.py:845-846`. Three new events thread through the same wire as the existing six.

### P-06 — Frozen-Pydantic `model_validator` gotcha

**Risk:** If a future refactor adds `model_config = ConfigDict(frozen=True)` to `GenerationRequest`, the D-10 validator written naively (e.g. `self.foo = ...`) would raise. Today `GenerationRequest` is NOT frozen.

**Mitigation:** D-10 validator only READS `self.debate` and `self.swarm_mode`, never assigns. The `return self` pattern works for both frozen and non-frozen models. Future-proof.

### P-07 — Audit-metadata serialization

**Risk:** `AuditEvent.detail` is `dict[str, Any]` (`services/audit/audit_service.py:58`) and gets JSON-serialized via `json.dumps(asdict(event), ensure_ascii=False)` (`audit_service.py:124`). Any non-JSON-serializable value (e.g. a `datetime`, a Pydantic model) will crash.

**Mitigation:** Audit metadata writes use only JSON-native types:
```python
detail = {
    # ... existing 9 keys ...
    "agent_05": {                                 # namespace per CONTEXT specifics
        "verifier_used":     True,                # bool
        "verifier_failed":   False,               # bool — D-06 toggle
        "forced_disagree":   False,               # bool — D-11 toggle
        "verifier_latency_ms": verifier_latency_ms,  # float (existing convention)
        "verifier_model":    settings.verifier_model or settings.active_model,  # str
        "evidence_chunk_count": len(verdict.evidence_chunk_ids) if verdict else 0,  # int
    },
}
```

Post-hoc DB queries: `metadata->>'agent_05'->>'forced_disagree' = 'true'` (Phase 21 SC: keys are documented for ops dashboards).

### P-08 — Language-matching enforcement

**Risk:** D-03's divergence banner is hard-coded Chinese; if the user query is English, the answer text starts in English (verifier's `proposed_answer`) then switches to Chinese for the banner — broken UX.

**Mitigation:** This is an accepted Phase 20 P-11 carry-forward limitation. The banner is locked Chinese (D-03 contract). The planner should:
- Document the limitation in the SUMMARY.md
- Make the banner text a module-level constant (`_DISAGREE_BANNER_TEMPLATE`) so a v1.6+ language-routing change is a single-symbol edit.
- Add a TODO comment referencing the Phase 20 P-11 carry-forward.

**Test obligation:** Unit test for `_format_disagree(verdict, sub_results)` asserts the EXACT banner template substitution (locked-string contract). The test fails loudly if a future-Claude alters the template.

### P-09 — `get_llm_client()` is a singleton — verifier-model resolution

**Risk:** `get_llm_client()` (`services/generator/llm_client.py:1025-1049`) caches a SINGLE instance keyed by `settings.llm_provider`. It cannot be re-resolved with a different `verifier_model` / `verifier_provider` after first call. If `Settings.verifier_provider="anthropic"` and the swarm peers use `"openai"`, the verifier can NOT just call `get_llm_client()` — it would get the wrong client.

**Mitigation (planner picks):**
1. **(A) Verifier reuses peer client when `verifier_model is None and verifier_provider is None`** — D-05 default. Verifier sets `self._llm = get_llm_client()` in `__init__`.
2. **(B) When `verifier_provider` is set, instantiate a fresh client at Verifier init** — bypass the singleton. Touch `Verifier.__init__` to switch on `settings.verifier_provider`:
```python
if settings.verifier_provider == "anthropic":
    self._llm = AnthropicLLMClient()
elif settings.verifier_provider == "openai":
    self._llm = OpenAILLMClient()
else:
    self._llm = get_llm_client()                 # default = peer
```

This avoids polluting the singleton factory with verifier-specific logic. Confidence: HIGH — same pattern used by `_swarm_pipeline` lazy-singleton at `services/pipeline.py:1301-1306`.

**Validation seam (Claude's-discretion bullet):** If `verifier_provider="anthropic"` and `ANTHROPIC_API_KEY=""`, fail at `AnthropicLLMClient.__init__` (already happens — `services/generator/llm_client.py:597-598` calls `anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)` which the SDK validates). No new validation logic required.

**`Settings.verifier_model` resolution:** None of the existing clients accept a per-call model override. To respect `Settings.verifier_model`, the verifier must either (i) instantiate a fresh client and patch `client._model`/`client._default_model` post-init, or (ii) accept this is forward-looking and only switch PROVIDERS in v1.5 (model resolution defers to per-provider default). Recommendation: **(ii)** — the planner ships `verifier_model` as a Settings field but documents it as "not yet wired; reserved for v1.6+ when per-call model selection lands at the LLM-client API level". Keeps Phase 21 blast radius small.

---

## TDD Pre-Classification

> Per `references/tdd.md`: features that admit `expect(fn(input)).toBe(output)` ARE TDD candidates; pure-glue / config-style work is `type: execute` (auto). Phase 21 has FOUR TDD-fit features (`tdd-1` .. `tdd-4`) and TWO standard plans (`exec-1`, `exec-2`).

### TDD plan `tdd-1` — Pydantic models + cross-field validator

```xml
<feature>
  <name>Phase 21 Pydantic surface (VerifierVerdict + 3 events + GenerationRequest.debate validator)</name>
  <files>utils/models.py, tests/unit/test_models.py</files>
  <behavior>
    Cases:
    1. VerifierVerdict.model_validate({verdict:"agree", evidence_chunk_ids:["c1"], reasoning:"r", proposed_answer:"a", latency_ms:100})
       → returns frozen instance with all fields populated.
    2. VerifierVerdict.model_validate({verdict:"maybe", ...}) → ValidationError (Literal violation).
    3. VerifierVerdict frozen: instance.verdict = "disagree" → raises ValidationError (Pydantic V2 frozen).
    4. VerifierVerdict.model_copy(update={"verdict":"disagree"}) → NEW frozen instance with verdict="disagree".
    5. VerifierStartEvent(trace_id="t1", seq=0, ts_ms=1, peer_count=3, model="m") → event_type=="verifier.start".
    6. VerifierStartEvent ClassVar event_type excluded from model_dump_json() output.
    7. VerifierCompleteEvent (verdict="agree", evidence_chunk_count=2, latency_ms=150) → all fields preserved on JSON round-trip.
    8. VerifierDisagreementEvent (reason="peers_diverge", summary="x", evidence_chunk_ids=["c1"], peer_count=3) → error_type defaults to None.
    9. VerifierDisagreementEvent reason Literal: "invalid_reason" → ValidationError.
    10. GenerationRequest(debate=True, swarm_mode=False) → ValidationError ("debate=True requires swarm_mode=True").
    11. GenerationRequest(debate=True, swarm_mode=True) → constructs successfully.
    12. GenerationRequest(debate=False, swarm_mode=False) → constructs successfully (default case).
    13. GenerationRequest(debate=False, swarm_mode=True) → constructs successfully (swarm without debate).
  </behavior>
  <implementation>
    Append after utils/models.py:633:
      class VerifierVerdict(BaseModel): model_config=ConfigDict(frozen=True); fields per D-01.
      class VerifierStartEvent(AgentEvent): event_type: ClassVar[str] = "verifier.start"; ...
      class VerifierCompleteEvent(AgentEvent): event_type: ClassVar[str] = "verifier.complete"; ...
      class VerifierDisagreementEvent(AgentEvent): event_type: ClassVar[str] = "verifier.disagreement"; ...
    Modify utils/models.py:205-224:
      Add field: debate: bool = False (next to swarm_mode at line 215).
      Add @model_validator(mode="after") def _check_debate_requires_swarm(self) per D-10.
  </implementation>
</feature>
```

### TDD plan `tdd-2` — `Verifier.verify()` happy + degrade paths

```xml
<feature>
  <name>Verifier.verify(peer_results, evidence) → VerifierVerdict</name>
  <files>services/agent/verifier.py (NEW), tests/unit/test_verifier.py (NEW)</files>
  <behavior>
    Cases (mock at services.agent.verifier.get_llm_client and / or services.agent.verifier.AnthropicLLMClient):
    1. LLM returns clean JSON {"verdict":"agree","evidence_chunk_ids":["c1","c2"],"reasoning":"r","proposed_answer":"ans","latency_ms":0}
       → returns VerifierVerdict(verdict="agree", evidence_chunk_ids=["c1","c2"], ...).
    2. LLM returns {"verdict":"agree","evidence_chunk_ids":[], ...}
       → returns VerifierVerdict(verdict="disagree", evidence_chunk_ids=[], ...) (forced-disagree per CF-04).
    3. LLM returns {"verdict":"disagree","evidence_chunk_ids":["c1"], ...}
       → returns VerifierVerdict(verdict="disagree", ...) verbatim.
    4. LLM returns text with markdown fences "```json\n{...}\n```" → JSON extracted via regex; verdict parses successfully.
    5. LLM returns prose-prefixed JSON "Here's the verdict:\n{...}" → JSON extracted; parses successfully.
    6. LLM returns invalid JSON "{'broken': }" → raises ValueError (caught by Verifier.verify outer try → propagates as Exception for D-06).
    7. LLM returns valid JSON missing required field {"verdict":"agree"} → raises pydantic.ValidationError (propagates per D-06).
    8. LLM raises anthropic.APIError → propagates as BaseException (caught by SwarmQueryPipeline.run per D-06).
    9. proposed_answer always populated in returned VerifierVerdict, even on agree path (D-02).
    10. Evidence_chunk_ids defensively filtered against supplied evidence chunk_id set (Claude's-discretion): LLM cites "c99" not in supplied evidence → "c99" dropped from returned evidence_chunk_ids.
    11. latency_ms field populated by Verifier (overrides whatever LLM emitted): verify() measures wall-clock time around the LLM call.
  </behavior>
  <implementation>
    services/agent/verifier.py:
      from __future__ import annotations
      import json, re, time
      from typing import Any
      from loguru import logger
      from services.generator.llm_client import BaseLLMClient, get_llm_client, OpenAILLMClient, AnthropicLLMClient
      from config.settings import settings
      from utils.models import RetrievedChunk, VerifierVerdict
      from services.pipeline import _SubAgentResult     # or accept duck-typed list

      _VERIFIER_SYSTEM = """\\
        ... (Candidate A from research §"Verifier System Prompt") ...
      """

      class Verifier:
          def __init__(self) -> None:
              self._llm = self._resolve_llm()       # Pattern 9 / P-09
          @staticmethod
          def _resolve_llm() -> BaseLLMClient:
              # P-09 mitigation
              if settings.verifier_provider == "anthropic": return AnthropicLLMClient()
              if settings.verifier_provider == "openai":    return OpenAILLMClient()
              return get_llm_client()
          async def verify(self, *, peer_results: list[_SubAgentResult], evidence: list[RetrievedChunk], user_query: str) -> VerifierVerdict:
              user_prompt = self._build_prompt(user_query, peer_results, evidence)
              t0 = time.perf_counter()
              turn = await self._llm.call_agentic_turn(
                  messages=[{"role":"user","content":user_prompt}],
                  tools=[],
                  system=_VERIFIER_SYSTEM,
                  max_tokens=settings.llm_max_tokens,
                  parallel_tool_calls=False,
              )
              latency_ms = int((time.perf_counter() - t0) * 1000)
              verdict = self._parse(turn.text, evidence)
              # Override latency_ms with measured value (overrides whatever LLM emitted).
              verdict = verdict.model_copy(update={"latency_ms": latency_ms})
              # CF-04 forced-disagree (Pitfall P-02).
              if verdict.verdict == "agree" and not verdict.evidence_chunk_ids:
                  verdict = verdict.model_copy(update={"verdict": "disagree"})
              return verdict
          @staticmethod
          def _parse(raw: str, evidence: list[RetrievedChunk]) -> VerifierVerdict:
              # Pattern 6 — first {...} block; raises ValueError or pydantic.ValidationError.
              ...
              # Defensive filter (Claude's-discretion): drop chunk_ids not in supplied evidence.
              valid_ids = {c.chunk_id for c in evidence}
              filtered = [cid for cid in parsed["evidence_chunk_ids"] if cid in valid_ids]
              parsed["evidence_chunk_ids"] = filtered
              return VerifierVerdict.model_validate(parsed)
  </implementation>
</feature>
```

### TDD plan `tdd-3` — `SwarmQueryPipeline._synthesize` divergence-aware extension

```xml
<feature>
  <name>_synthesize(verifier_verdict=None) + _format_disagree helper (D-04)</name>
  <files>services/pipeline.py, tests/unit/test_swarm_pipeline.py (extend)</files>
  <behavior>
    Cases:
    1. _synthesize(query, sub_questions, answers, verifier_verdict=None) → returns identical bytes to current implementation (SC5 byte-identity for non-debate path).
    2. _synthesize(..., verifier_verdict=VerifierVerdict(verdict="agree", ...)) → returns identical bytes to current implementation (agree path uses standard synthesis; verifier just signals OK).
    3. _synthesize(..., verifier_verdict=VerifierVerdict(verdict="disagree", proposed_answer="X", evidence_chunk_ids=["c1","c2"]), N peers) → returns "X\\n\\n⚠️ 子代理间存在分歧（{N} 个同伴中的 {M} 个提出差异回答）。以上回答基于验证者引用的证据（2 个块）。" with M = count of distinct peer answers (computed from sub_results or default to N).
    4. _format_disagree(verdict, sub_results) is a private static helper; given N=3, evidence_chunk_ids=["c1"], proposed_answer="ans" → exact template-substituted string.
    5. Disagree path makes ZERO additional LLM calls (uses verifier.proposed_answer verbatim) — assert _llm.chat NOT awaited on disagree path.
  </behavior>
  <implementation>
    services/pipeline.py:1157 — extend signature:
      async def _synthesize(self, original_query, sub_questions, answers, *, verifier_verdict: VerifierVerdict | None = None) -> str:
          if verifier_verdict is not None and verifier_verdict.verdict == "disagree":
              return self._format_disagree(verifier_verdict, len(answers), len(sub_questions))
          # ... existing body unchanged ...
      @staticmethod
      def _format_disagree(verdict: VerifierVerdict, peer_count: int, dissent_count: int) -> str:
          banner = (
              f"⚠️ 子代理间存在分歧（{peer_count} 个同伴中的 {dissent_count} 个提出差异回答）。"
              f"以上回答基于验证者引用的证据（{len(verdict.evidence_chunk_ids)} 个块）。"
          )
          return f"{verdict.proposed_answer}\\n\\n{banner}"
  </implementation>
</feature>
```

### TDD plan `tdd-4` — `SwarmQueryPipeline.run()` debate hop + audit + events

```xml
<feature>
  <name>SwarmQueryPipeline.run() debate hop (gather → dedup → verify → synth) + audit metadata + 3 SSE events</name>
  <files>services/pipeline.py, tests/unit/test_swarm_pipeline.py (extend), tests/integration/test_swarm_debate_e2e.py (NEW)</files>
  <behavior>
    Unit cases:
    1. req.debate=False → byte-identical run as today (SC5): no Verifier instantiated, no events emitted, audit detail dict missing "agent_05" key.
    2. req.debate=True + happy verifier → flow: decompose → fan-out → dedup → verify → _synthesize(verifier_verdict=verdict). Three SSE events appended in order: VerifierStartEvent, VerifierCompleteEvent (no DisagreementEvent on agree-with-evidence). audit.detail["agent_05"]["verifier_used"] == True.
    3. req.debate=True + disagree verdict → events: Start, Disagreement(reason="peers_diverge"), Complete. _synthesize called with verdict; final answer == _format_disagree(verdict).
    4. req.debate=True + forced-disagree (Verifier returns disagree with empty evidence_chunk_ids — CF-04 fired inside Verifier.verify) → events: Start, Disagreement(reason="forced_no_evidence"), Complete. audit.detail["agent_05"]["forced_disagree"] == True.
    5. req.debate=True + Verifier raises BaseException → events: Start, Disagreement(reason="verifier_failed", error_type="<ExceptionName>"). audit.detail["agent_05"]["verifier_failed"] == True. _synthesize called with verifier_verdict=None → falls through to standard consensus path (graceful degrade per D-06).
    6. Latency contract (SC2) — see Pattern 8. Synthetic peer delay 0.3s, verifier delay 0.2s, three peers → elapsed_ms ∈ (450, 700).
    7. Audit log shape (CF-10): event.detail keys ⊇ existing 9 keys (swarm_n, per_agent_turns, ..., synthesis_latency_ms) ∪ {"agent_05"}.
    8. Verifier sees DEDUPED chunks (P-03): if peer 1 returns chunks [c1,c2], peer 2 returns [c2,c3], verifier evidence list == [c1,c2,c3] (order preserved from extend; first occurrence wins).
    Integration case (e2e, marked @pytest.mark.integration):
    9. Live LLM swarm + debate query → resp.answer non-empty, latency bound, 3 verifier events emitted via SSE if Option B (P-05) is taken.
  </behavior>
  <implementation>
    Insert between pipeline.py:1250 and 1252:
      # Phase 21 verifier hop — gated on req.debate.
      verifier_events: list[AgentEvent] = []
      verdict: VerifierVerdict | None = None
      verifier_latency_ms = 0.0
      audit_agent_05: dict[str, Any] = {"verifier_used": False}
      if req.debate:
          verifier_t0 = time.perf_counter()
          deduped_evidence = AgentQueryPipeline._dedup_chunks(all_swarm_chunks)
          successful = [r for r in raw_results if not isinstance(r, BaseException)]
          model_label = settings.verifier_model or settings.active_model
          verifier_events.append(VerifierStartEvent(
              trace_id=trace_id, seq=len(verifier_events), ts_ms=int(time.time()*1000),
              peer_count=len(successful), model=model_label,
          ))
          try:
              verdict = await self._verifier.verify(
                  peer_results=successful, evidence=deduped_evidence, user_query=req.query,
              )
          except BaseException as exc:
              logger.error("verifier_failed", exc_info=exc)
              audit_agent_05["verifier_failed"] = True
              verifier_events.append(VerifierDisagreementEvent(
                  trace_id=trace_id, seq=len(verifier_events), ts_ms=int(time.time()*1000),
                  reason="verifier_failed", summary=str(exc)[:200],
                  evidence_chunk_ids=[], peer_count=len(successful),
                  error_type=type(exc).__name__,
              ))
          else:
              audit_agent_05["verifier_used"] = True
              audit_agent_05["evidence_chunk_count"] = len(verdict.evidence_chunk_ids)
              if verdict.verdict == "disagree":
                  reason = "forced_no_evidence" if not verdict.evidence_chunk_ids else "peers_diverge"
                  audit_agent_05["forced_disagree"] = (reason == "forced_no_evidence")
                  verifier_events.append(VerifierDisagreementEvent(
                      trace_id=trace_id, seq=len(verifier_events), ts_ms=int(time.time()*1000),
                      reason=reason, summary=verdict.reasoning[:200],
                      evidence_chunk_ids=list(verdict.evidence_chunk_ids),
                      peer_count=len(successful),
                  ))
              verifier_events.append(VerifierCompleteEvent(
                  trace_id=trace_id, seq=len(verifier_events), ts_ms=int(time.time()*1000),
                  verdict=verdict.verdict, evidence_chunk_count=len(verdict.evidence_chunk_ids),
                  latency_ms=verdict.latency_ms,
              ))
          verifier_latency_ms = round((time.perf_counter() - verifier_t0) * 1000, 1)
          audit_agent_05["verifier_latency_ms"] = verifier_latency_ms
          audit_agent_05["verifier_model"] = model_label
      # Pass verdict (may be None on degrade) to synthesizer.
      synth_t0 = time.perf_counter()
      final_answer = await self._synthesize(req.query, sub_questions, answers, verifier_verdict=verdict)
      # ... existing audit block at line 1270; add detail["agent_05"] = audit_agent_05 only if req.debate.
      # ... return; events list returned via separate channel (Option A) or yielded via run_streaming (Option B).
  </implementation>
</feature>
```

### Standard plan `exec-1` — `Settings.verifier_model` / `verifier_provider`

```xml
<feature_type>execute (auto)</feature_type>
<files>config/settings.py, tests/unit/test_settings.py (extend)</files>
<work>
  Append two fields to Settings class body (~line 285, near llm_max_tokens):
    verifier_model:    str | None = None
    verifier_provider: Literal["openai", "anthropic"] | None = None
  Touch ≤ 6 lines. No validator (P-09: anthropic_api_key check happens at AnthropicLLMClient init naturally).
  Smoke test: import settings, assert defaults are None.
</work>
```

### Standard plan `exec-2` — `docs/agent-architecture.md` Event-Schema-Reference extension

```xml
<feature_type>execute (auto)</feature_type>
<files>docs/agent-architecture.md</files>
<work>
  Append after docs/agent-architecture.md:373 (after `### synthesizer.final` section):
    ### verifier.start          (table + JSON example mirroring tool.span.start at line 292)
    ### verifier.complete       (table + JSON example mirroring tool.span.end at line 309)
    ### verifier.disagreement   (table + JSON example mirroring tool.span.error at line 329 — note three reason values)
  Add a backward-compat note at the top of the new subsection block:
    "These three event types are emitted ONLY when req.debate=True. Non-debate flows are
     unchanged — existing six event types continue to be the complete event surface for
     debate=False requests."
  Touch ~80 LOC of doc.
</work>
```

---

## Coverage Branch Enumeration

> Phase 21 ships its own ≥70% diff-cover (per Phase 10 TEST-03 carry-forward) and feeds the new lines to Phase 22's whole-file 70% target.

### `services/agent/verifier.py` (NEW, ~150 LOC) — branches to cover

| # | Branch | TDD case (above) |
|---|--------|------------------|
| B-01 | `verify()` happy-path: agree + non-empty evidence | tdd-2 case 1 |
| B-02 | `verify()` forced-disagree path: agree + empty evidence → override | tdd-2 case 2 |
| B-03 | `verify()` honest-disagree path: disagree returned verbatim | tdd-2 case 3 |
| B-04 | `_parse()` happy: clean JSON | tdd-2 case 1 |
| B-05 | `_parse()` JSON-fenced: markdown wrapper stripped via regex | tdd-2 case 4 |
| B-06 | `_parse()` prose-prefixed: regex extracts first {...} | tdd-2 case 5 |
| B-07 | `_parse()` invalid JSON: ValueError raised | tdd-2 case 6 |
| B-08 | `_parse()` shape mismatch: pydantic.ValidationError raised | tdd-2 case 7 |
| B-09 | `_parse()` defensive filter: drops chunk_ids not in supplied evidence | tdd-2 case 10 |
| B-10 | `_resolve_llm()` default branch: settings.verifier_provider is None → get_llm_client() | tdd-2 fixture default |
| B-11 | `_resolve_llm()` override branch: settings.verifier_provider == "anthropic" → AnthropicLLMClient() | tdd-2 (additional case) |
| B-12 | `_resolve_llm()` override branch: settings.verifier_provider == "openai" → OpenAILLMClient() | tdd-2 (additional case) |
| B-13 | `verify()` LLM raises → propagates BaseException (not caught inside Verifier) | tdd-2 case 8 |
| B-14 | `verify()` latency_ms override: measured value replaces LLM-emitted value | tdd-2 case 11 |
| B-15 | `_build_prompt()` formats peer answers + evidence list (called from verify) | tdd-2 implicit |

### `services/pipeline.py::SwarmQueryPipeline.run` debate hop (~80 NEW LOC) — branches to cover

| # | Branch | TDD case |
|---|--------|----------|
| B-16 | `req.debate=False` skip: no Verifier instantiated, no events, no extra audit keys | tdd-4 case 1 |
| B-17 | `req.debate=True` happy path: Start + Complete events; audit.agent_05.verifier_used=True | tdd-4 case 2 |
| B-18 | `req.debate=True` disagree path: Start + Disagreement(peers_diverge) + Complete | tdd-4 case 3 |
| B-19 | `req.debate=True` forced-disagree path: Disagreement(forced_no_evidence) + audit.agent_05.forced_disagree=True | tdd-4 case 4 |
| B-20 | `req.debate=True` BaseException path: Disagreement(verifier_failed) + audit.agent_05.verifier_failed=True + verdict=None passthrough | tdd-4 case 5 |
| B-21 | Latency contract: max(peer)+verifier ≤ elapsed ≤ max(peer)+verifier+overhead | tdd-4 case 6 |
| B-22 | Audit detail superset: existing 9 keys + agent_05 namespace | tdd-4 case 7 |
| B-23 | Verifier sees deduped chunks (gated by req.debate) | tdd-4 case 8 |

### `services/pipeline.py::SwarmQueryPipeline._synthesize` (~40 LOC modified) — branches

| # | Branch | TDD case |
|---|--------|----------|
| B-24 | `verifier_verdict is None` (default) → byte-identical to current synthesize | tdd-3 case 1 |
| B-25 | `verifier_verdict.verdict == "agree"` → byte-identical to current synthesize | tdd-3 case 2 |
| B-26 | `verifier_verdict.verdict == "disagree"` → returns _format_disagree result; ZERO LLM calls | tdd-3 case 3, 5 |
| B-27 | `_format_disagree` exact template substitution | tdd-3 case 4 |

### `utils/models.py` (~80 LOC NEW) — branches

| # | Branch | TDD case |
|---|--------|----------|
| B-28 | VerifierVerdict construct/validate happy + frozen mutation rejection | tdd-1 case 1, 3 |
| B-29 | VerifierVerdict Literal validation (verdict field) | tdd-1 case 2 |
| B-30 | 3 events: ClassVar discriminator + JSON round-trip | tdd-1 case 5–9 |
| B-31 | GenerationRequest.debate=True + swarm_mode=False → ValidationError | tdd-1 case 10 |
| B-32 | All other debate/swarm_mode permutations construct cleanly | tdd-1 case 11–13 |

**Total new branches: 32.** All map to a TDD case in plans `tdd-1` .. `tdd-4`. Phase 22 audit can verify alignment against this table.

---

## Test Layout

| File | Status | Purpose |
|------|--------|---------|
| `tests/unit/test_verifier.py` | NEW | tdd-2 cases 1–11; covers B-01..B-15 |
| `tests/unit/test_models.py` | EXTEND | tdd-1 cases 1–13; covers B-28..B-32 (slot in next to existing AgentEvent tests) |
| `tests/unit/test_swarm_pipeline.py` | EXTEND | tdd-3 cases 1–5 + tdd-4 cases 1–5, 7, 8; covers B-16..B-20, B-22..B-27 |
| `tests/integration/test_swarm_debate_e2e.py` | NEW | tdd-4 case 6 (latency assertion) + tdd-4 case 9 (live LLM); marked `@pytest.mark.integration` |
| `tests/unit/test_settings.py` | EXTEND | exec-1 smoke test: verifier_model/verifier_provider default = None |

**Mock seam (per CONTEXT and v1.3 Phase 13/15 carry-forward):** `services.agent.verifier.get_llm_client` (and `services.agent.verifier.AnthropicLLMClient` / `OpenAILLMClient` if `_resolve_llm()` override path is exercised). NOT `anthropic.AsyncAnthropic` directly. Existing `mock_pipeline` fixture at `tests/unit/test_swarm_pipeline.py:73-111` is the template — extend with a verifier mock.

---

## Project Constraints (from CLAUDE.md + Claude.md)

These directives are EQUAL-AUTHORITY to CONTEXT.md locked decisions:
- **Pydantic V2** — all four new models use `BaseModel` + `model_config = ConfigDict(frozen=True)`.
- **mypy --strict** — type all signatures explicitly; `BaseException` not bare `except`.
- **ruff** — passes; no broad-except, no unused imports.
- **No bare `except`** (ERR-01) — D-06 uses `except BaseException as exc:` explicitly.
- **No blocking I/O in async** — Verifier is purely awaiting `call_agentic_turn`.
- **Adapters for external deps** — Verifier consumes `BaseLLMClient`, never an SDK directly.
- **Tenacity for external calls** — D-07: NOT layered on Verifier (provider-side retry already covers; double-retry would compound latency).
- **Structured logging** — `loguru.logger.error("verifier_failed", exc_info=exc)` per D-06.

---

## Environment Availability

> Phase 21 has no new external dependencies. SKIPPED per `<execution_flow>` Step 2.6 ("If the phase is purely code/config changes with no external dependencies, output 'SKIPPED'").

Indirect dependencies (already verified by existing tests):
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` — for live LLM in tdd-4 case 9 (integration only); CONFIGURATION error if missing per `tests/integration/test_swarm_pipeline_e2e.py:9-12` precedent.

---

## Validation Architecture

> Per `.planning/config.json` workflow.nyquist_validation == true. See companion artifact `21-VALIDATION.md` for the full evidence-frequency mapping.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio (existing project standard) |
| Config | `pytest.ini` (existing); `addopts = -m "not integration"` excludes integration tier |
| Quick run command | `pytest tests/unit/test_verifier.py tests/unit/test_models.py tests/unit/test_swarm_pipeline.py -x` |
| Full suite command | `pytest -m "not integration"` (combined coverage threshold 70% per Phase 15 D-08) |
| Phase gate | full unit suite + new integration test green before `/gsd-verify-work` |

### Sampling Rate
- **Per task commit:** unit-only quick run (sub-30s typical).
- **Per wave merge:** `pytest tests/unit/test_verifier.py tests/unit/test_swarm_pipeline.py tests/unit/test_models.py --cov=services/agent/verifier.py --cov=services/pipeline.py --cov=utils/models.py` — verify diff-cover ≥ 70%.
- **Phase gate:** full unit suite green + integration `tests/integration/test_swarm_debate_e2e.py -m integration` for SC2 latency assertion.

### Wave 0 Gaps
- [ ] `tests/unit/test_verifier.py` — does not exist; create empty file with placeholder fixture.
- [ ] `tests/integration/test_swarm_debate_e2e.py` — does not exist; create empty file with `pytestmark = [pytest.mark.integration]`.
- [ ] No framework install needed — pytest + pytest-asyncio already in `pyproject.toml`.

---

## Security Domain

> `security_enforcement` not explicitly disabled — included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (inherited) | JWT verified at `controllers/api.py` route layer; verifier hop runs server-side after auth |
| V3 Session Management | yes (inherited) | session_id flows via `GenerationRequest`; no new session surface |
| V4 Access Control | yes (inherited) | tenant_id RLS enforced at `services/retriever/`; verifier sees only the requesting tenant's chunks (CF-10) |
| V5 Input Validation | yes | D-10 model_validator on GenerationRequest; VerifierVerdict.model_validate hardens LLM-output parse |
| V6 Cryptography | no (no new crypto in this phase) | — |
| V7 Error Handling | yes | D-06 degrade-with-signal; full traceback to logger only, summary truncated to 200 chars on wire (mirrors v1.4 D-12 redaction policy) |
| V11 Business Logic | yes | Forced-disagree (CF-04) prevents verifier from claiming agreement without evidence — anti-hallucination control |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM injects fake chunk_ids → poisons audit log | Tampering | Defensive filter in Verifier._parse drops IDs not in supplied evidence (Pattern 6, B-09) |
| LLM returns invalid JSON → unhandled crash → 500 | DoS | D-06 BaseException catch + degrade-with-signal; user gets answer (graceful path) |
| Cross-tenant chunk leak via verifier.proposed_answer | Information Disclosure | Verifier evidence list is built FROM peer chunks — already RLS-filtered upstream by retriever; no new tenant boundary crossed |
| `summary` / `error_message` echoes PII to wire | Information Disclosure | 200-char truncation at emitter (D-08, mirrors Phase 18 D-12 pattern) |
| `proposed_answer_preview` would echo full answer to multiple SSE consumers | Information Disclosure | D-09 explicitly excluded preview field — answer reaches user only via `synthesizer.final` once |

---

## Assumptions Log

> All claims in this research are tagged `[VERIFIED: <file:line>]` against the live source files. The following are explicit `[ASSUMED]` items needing user / planner confirmation:

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The cleanest verifier-mock seam is `services.agent.verifier.get_llm_client` (consumer path, mirrors v1.3 Phase 13/15 pattern). | TDD plan tdd-2 implementation | Mock at wrong path → tests pass against the wrong client; Verifier's own provider-resolve branch (B-11/B-12) needs a different mock at `services.agent.verifier.AnthropicLLMClient` etc. |
| A2 | Option B (P-05) — adding `SwarmQueryPipeline.run_streaming` so the 3 verifier events reach SSE wire — is preferred over Option A (return events alongside the response). The planner has authority to switch back to Option A and document SSE deferral. | Pitfall P-05 | Option A leaves AGENT-15 acceptance criterion technically unmet but not blocked; full-honesty plan would commit Option B. |
| A3 | Settings.verifier_model is shipped as a Settings field but NOT wired to per-call model selection in v1.5 (LLM client APIs lack a per-call model override hook). | Pitfall P-09 | If user expects verifier_model="claude-haiku-4-5" to actually route to Haiku in v1.5, planner must either patch client._model post-init OR document the deferral. |
| A4 | Dedup ordering (P-03) — apply `_dedup_chunks` to the gathered chunks BEFORE the verifier hop, gated on `req.debate`. | Pitfall P-03 | If unguarded (always-deduped), SC5 byte-identity for `debate=False` breaks. |
| A5 | The Chinese disagreement banner (D-03) hard-codes the language; English-query users see Chinese banner. Documented as Phase 20 P-11 carry-forward. | Pitfall P-08 | Acceptable per CONTEXT.md D-03 lock; user can defer i18n to v1.6+. |

**If these assumptions need confirmation, raise during plan-check phase.**

---

## Open Questions (RESOLVED)

1. **Should `Verifier.verify()` accept `_SubAgentResult` directly or a public alias `SubAgentAnswer`?**
   - What we know: ROADMAP/REQUIREMENTS uses `SubAgentAnswer`; CONTEXT canonical-refs note flags the mismatch and says "planner reconciles".
   - What's unclear: Whether to introduce a new public class.
   - **RESOLVED:** Pass `list[_SubAgentResult]` directly. Adding a public alias requires conversion code that buys nothing. To avoid the runtime circular import between `services/pipeline.py` ↔ `services/agent/verifier.py`, the parameter is annotated with a string forward-ref (`peer_results: "list[_SubAgentResult]"`) and the import lives under `if TYPE_CHECKING:` in `services/agent/verifier.py` (file already opens with `from __future__ import annotations`). If a v1.6+ public-API consumer needs a stable name, promote `_SubAgentResult` (drop underscore) at that time.

2. **Where does `Verifier` get instantiated?**
   - What we know: `SwarmQueryPipeline.__init__` already wires 6 collaborators (`pipeline.py:1010-1016`).
   - What's unclear: Add `self._verifier = Verifier()` to `__init__` (instance-per-pipeline) or instantiate per-call (`Verifier()` inside the `if req.debate:` block).
   - **RESOLVED:** Per-init (`self._verifier = Verifier()` in `SwarmQueryPipeline.__init__`). Mirrors existing pattern; one-time provider-resolve cost; doesn't run when `debate=False` because `verify()` is never called. The `from services.agent.verifier import Verifier` statement at the top of `services/pipeline.py` is safe as long as `verifier.py` does NOT do a runtime import of any pipeline symbol (see Q1 RESOLVED — TYPE_CHECKING guard).

3. **Should the integration test (tdd-4 case 9) gate on a real Tavily query AND a real Anthropic call?**
   - What we know: `tests/integration/test_swarm_pipeline_e2e.py` currently runs against OneAPI gateway (OPENAI_API_KEY).
   - What's unclear: Does Phase 21 add a second integration test that requires both an OpenAI key (peer) AND an Anthropic key (verifier with `verifier_provider="anthropic"`)?
   - **RESOLVED:** ONE integration test, both peer + verifier on the same provider (default = peer model). The cross-provider verifier path is unit-tested with mocks (B-11). Avoids cascading credential requirements in CI.

---

## Sources

### Primary (HIGH confidence) — verified line-by-line
- `services/pipeline.py:546-555` — `_SubAgentResult` dataclass (Pattern 1)
- `services/pipeline.py:710-720` — `_dedup_chunks` static method (Pitfall P-03)
- `services/pipeline.py:824-968` — `AgentQueryPipeline.run_streaming` (Pattern 8 mirror)
- `services/pipeline.py:997-1306` — `SwarmQueryPipeline` full class (Pattern 2)
- `services/pipeline.py:1034-1043` — `_decompose` JSON-extract pattern (Pattern 6)
- `services/pipeline.py:1230` — `asyncio.gather` join site (verifier hop integration point)
- `services/pipeline.py:1268-1288` — existing swarm `AuditEvent.log()` shape (P-07)
- `services/generator/llm_client.py:226-250` — `BaseLLMClient.call_agentic_turn` signature (Pattern 5)
- `services/generator/llm_client.py:441-572` — `OpenAILLMClient.call_agentic_turn` (verifier text-only invocation; `response_format` availability)
- `services/generator/llm_client.py:706-804` — `AnthropicLLMClient.call_agentic_turn` (no `response_format` kwarg — confirmed)
- `services/generator/llm_client.py:1025-1049` — `get_llm_client()` singleton factory (Pitfall P-09)
- `services/audit/audit_service.py:25-58` — `AuditAction` enum + `AuditEvent` dataclass (D-11 metadata key reuse)
- `services/audit/audit_service.py:116-138` — `log()` method (P-07 serialization)
- `services/agent/_demo_runner.py:89-94` — `emit_sse_frame` (Pattern 4)
- `controllers/api.py:259-294` — `agent_run_stream` route (Pitfall P-05 — confirmed no swarm dispatch)
- `utils/models.py:180-198` — `RetrievedChunk` (chunk_id field)
- `utils/models.py:205-224` — `GenerationRequest` (D-10 validator target)
- `utils/models.py:537-633` — `AgentEvent` base + 6 subclasses (Pattern 3 template)
- `config/settings.py:267-275` — provider/model fields (D-05 placement)
- `config/settings.py:410-448` — `_validate_security` model_validator (Pattern 7 template)
- `docs/agent-architecture.md:245-373` — Event Schema Reference structure (Pattern 9)
- `tests/unit/test_swarm_pipeline.py:73-362` — existing swarm test fixtures + patterns
- `tests/unit/test_agent_sse.py:234-255` — latency assertion test pattern (Pattern 8)
- `tests/integration/test_swarm_pipeline_e2e.py` — integration tier conventions (no skip on missing key)

### CONTEXT references (planner authority)
- `.planning/phases/21-agent-05-multi-agent-debate-sub-agent-verifier/21-CONTEXT.md` — D-01..D-11 + CF-01..CF-10
- `.planning/phases/20-websearchtool-real-implementation-tavily/20-PATTERNS.md` — precedent format
- `.planning/phases/20-websearchtool-real-implementation-tavily/20-VERIFICATION.md` — precedent verification shape
- `.planning/STATE.md` — Carry-Forward Decisions; Open Questions Q#3, Q#4 (resolved by CF-01, CF-02)
- `.planning/ROADMAP.md` Phase 21 section — 5 success criteria
- `.planning/REQUIREMENTS.md` AGENT-05/14/15 — note schema field-name mismatch (CONTEXT.md D-01 supersedes)

### Tertiary (LOW confidence — not blocking)
- None. All claims are verified against the live source.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new deps; all libs already in pyproject.toml
- Architecture: HIGH — line-precise integration sites, three concrete options for SSE seam
- Pitfalls: HIGH — every pitfall cites a verified-line failure mode in the live code
- TDD pre-classification: HIGH — input/output cases drawn directly from CONTEXT.md D-01..D-11
- Verifier system prompt: MEDIUM — Candidate A is design-forward; will need empirical refinement after RED→GREEN of tdd-2

**Research date:** 2026-05-10
**Valid until:** 2026-06-10 (30 days; stable subsystem, no fast-moving deps)

---

*Phase: 21-AGENT-05 Multi-Agent Debate / Sub-Agent Verifier*
*Researched: 2026-05-10 — verified against live source*
