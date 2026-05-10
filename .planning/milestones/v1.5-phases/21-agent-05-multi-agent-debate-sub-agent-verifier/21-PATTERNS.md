# Phase 21: AGENT-05 Multi-Agent Debate / Sub-Agent Verifier — Pattern Map

**Mapped:** 2026-05-10
**Files analyzed:** 8 (2 NEW production + 4 MODIFY production + 2 NEW tests + 2 MODIFY tests + 1 doc)
**Analogs found:** 8 / 8 (100%)

All file targets cited in CONTEXT.md `<code_context>` Integration Points have a strong in-repo analog. No "no-analog" cases. Project standards (Pydantic V2 frozen, mypy --strict, no bare `except`, structured `loguru` logging) are uniformly satisfied by the cited analogs.

---

## File Classification

| New / Modified File | Status | Role | Data Flow | Closest Analog | Match Quality |
|---------------------|--------|------|-----------|----------------|---------------|
| `services/agent/verifier.py` | NEW | service (LLM-call wrapper) | request-response (single async LLM call → parse → return) | `services/pipeline.py::SwarmQueryPipeline._decompose` (lines 1018–1066) — same shape: system-prompt + LLM call + JSON regex + Pydantic validate + graceful fallback | exact (role + flow) |
| `utils/models.py` (4 new models + 1 modified `GenerationRequest`) | MODIFY | model (Pydantic V2) | transform (data shape) | `utils/models.py::AgentEvent` + 6 subclasses (lines 537–633) for events; `utils/models.py::ToolCall` (lines 244–258) for frozen verdict; `config/settings.py::_validate_security` (lines 410–448) for `model_validator` | exact (sibling extension) |
| `services/pipeline.py::SwarmQueryPipeline.run` (verifier hop) | MODIFY | pipeline orchestration | event-driven join (gather → verify → synth) | self — extension between line 1230 (`asyncio.gather`) and line 1252 (`synth_t0`); audit pattern at lines 1270–1288 | exact (in-place extension) |
| `services/pipeline.py::SwarmQueryPipeline._synthesize` (kwarg + helper) | MODIFY | pipeline composition | transform (str builder) | self — existing body at lines 1157–1190 (kwarg-default extension preserves byte-identity) | exact (in-place extension) |
| `config/settings.py` (2 fields) | MODIFY | config | n/a | `config/settings.py:271–283` provider/model field block | exact |
| `tests/unit/test_verifier.py` | NEW | test (unit) | mock LLM → assert verdict | `tests/unit/test_swarm_pipeline.py:73–111` (`mock_pipeline` fixture) — same `MagicMock`+`AsyncMock` seam | role-match |
| `tests/integration/test_swarm_debate_e2e.py` | NEW | test (integration / latency) | timing + SSE event sequence | `tests/unit/test_agent_sse.py:234–255` for latency-bound assertion + `tests/integration/test_swarm_pipeline_e2e.py` for credential-required integration shape | exact (latency mirror) |
| `tests/unit/test_models.py` (extend) | MODIFY | test (unit) | construct + validate | adjacent existing `AgentEvent` tests in same file | exact |
| `tests/unit/test_swarm_pipeline.py` (extend) | MODIFY | test (unit) | mock + assert | self — extend `mock_pipeline` fixture to add `pipe._verifier` mock | exact |
| `docs/agent-architecture.md` (3 new subsections at line 373) | MODIFY | docs | n/a | `docs/agent-architecture.md:292–347` (`tool.span.start/end/error` triple) | exact (sibling block) |

---

## Pattern Assignments

### `services/agent/verifier.py` (NEW — service, request-response)

**Primary analog:** `services/pipeline.py::SwarmQueryPipeline._decompose` (lines 1018–1066) — closest in-repo precedent for "single LLM call → JSON regex → Pydantic validate → graceful fallback". Verifier mirrors this shape against an OBJECT (`{...}`) instead of an ARRAY (`[...]`), and against `call_agentic_turn` instead of `chat`.

**Imports pattern** (mirror `services/pipeline.py:14–48`):

```python
from __future__ import annotations

import json
import re
import time
from typing import Any

from loguru import logger

from config.settings import settings
from services.generator.llm_client import (
    AnthropicLLMClient,
    BaseLLMClient,
    OpenAILLMClient,
    get_llm_client,
)
from utils.models import RetrievedChunk, VerifierVerdict
# Pattern 1 (RESEARCH §Patterns 1) — accept _SubAgentResult directly; do NOT
# introduce SubAgentAnswer alias (Open Question #1 recommendation).
from services.pipeline import _SubAgentResult
```

**Provider-resolve pattern** (mirror `services/generator/llm_client.py:1025–1049` `get_llm_client()` factory branching, but PER-INSTANCE — bypass singleton per Pitfall P-09):

```python
class Verifier:
    def __init__(self) -> None:
        self._llm: BaseLLMClient = self._resolve_llm()

    @staticmethod
    def _resolve_llm() -> BaseLLMClient:
        # P-09: cannot reuse get_llm_client() singleton when verifier_provider
        # differs from peer. Same instantiation pattern as the factory above.
        if settings.verifier_provider == "anthropic":
            return AnthropicLLMClient()
        if settings.verifier_provider == "openai":
            return OpenAILLMClient()
        return get_llm_client()
```

**Core LLM-call pattern** (mirror `services/generator/llm_client.py:226–250` signature + `_decompose` shape from `services/pipeline.py:1026–1031`):

```python
async def verify(
    self,
    *,
    peer_results: list[_SubAgentResult],
    evidence: list[RetrievedChunk],
    user_query: str,
) -> VerifierVerdict:
    user_prompt = self._build_prompt(user_query, peer_results, evidence)
    t0 = time.perf_counter()
    turn = await self._llm.call_agentic_turn(
        messages=[{"role": "user", "content": user_prompt}],
        tools=[],                                       # CF-03 text-only
        system=_VERIFIER_SYSTEM,
        max_tokens=settings.llm_max_tokens,
        parallel_tool_calls=False,                      # CF-09 explicit
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    verdict = self._parse(turn.text, evidence)
    verdict = verdict.model_copy(update={"latency_ms": latency_ms})
    # CF-04 forced-disagree (Pitfall P-02 — override INSIDE Verifier so
    # returned object is truthful before SwarmQueryPipeline.run sees it).
    if verdict.verdict == "agree" and not verdict.evidence_chunk_ids:
        verdict = verdict.model_copy(update={"verdict": "disagree"})
    return verdict
```

**JSON-extract + parse pattern** (verbatim mirror of `services/pipeline.py:1034–1043` `_decompose`, adapted from `[.*]` to `{.*}`):

```python
@staticmethod
def _parse(raw: str, evidence: list[RetrievedChunk]) -> VerifierVerdict:
    # Pattern 6 — first {...} block (analog at services/pipeline.py:1034).
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        raise ValueError(f"verifier returned no JSON object; raw={raw[:200]!r}")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"verifier JSON parse failed: {exc!r}") from exc
    # Defensive filter (Claude's-discretion bullet) — drop chunk_ids not
    # in the supplied evidence set. Mirrors the `seen` dedup pattern at
    # services/pipeline.py:1050–1059 in spirit (set-membership filter).
    valid_ids = {c.chunk_id for c in evidence}
    parsed["evidence_chunk_ids"] = [
        cid for cid in parsed.get("evidence_chunk_ids", []) if cid in valid_ids
    ]
    return VerifierVerdict.model_validate(parsed)        # raises ValidationError
```

**Error-handling pattern (NOT inside Verifier — at the caller per D-06/D-07):**
The verifier deliberately propagates `ValueError`, `pydantic.ValidationError`, `anthropic.APIError`, `openai.APIError` upwards. The `except BaseException` net lives in `SwarmQueryPipeline.run` (D-06). NO tenacity wrapper at `Verifier` level (D-07; provider-side retry on `OllamaLLMClient.chat` at `services/generator/llm_client.py:275–279` is the existing project pattern — verifier intentionally does NOT layer a second one).

**Structured logging pattern** (project standard from `services/pipeline.py:1036, 1042, 1046, 1062, 1147`):

```python
# Verifier itself stays quiet; the caller logs the failure (D-06). When
# Verifier needs to log a warning (e.g., evidence-filter dropped IDs), use:
logger.warning(f"[Verifier] dropped {n} chunk_ids not in supplied evidence")
```

---

### `utils/models.py` — `VerifierVerdict` (NEW — frozen Pydantic V2 model)

**Primary analog:** `utils/models.py::ToolCall` (lines 244–258) — closest frozen Pydantic V2 model with `Literal` field; supports `.model_copy(update=...)` for the CF-04 forced-disagree override (Pitfall P-02).

**Pattern to copy** (lines 244–258):

```python
class ToolCall(BaseModel):
    """A single tool invocation requested by the LLM in one assistant turn.
    ...
    ``id`` correlates the call to its result on the next turn (Anthropic
    ``tool_use_id``, OpenAI ``tool_call_id``). Frozen — adapters never mutate.
    """
    model_config = ConfigDict(frozen=True)

    id:        str
    name:      str
    arguments: dict[str, Any] = Field(default_factory=dict)
```

**Apply to `VerifierVerdict`** (D-01, append after `utils/models.py:633`):

```python
class VerifierVerdict(BaseModel):
    """Verifier sub-agent verdict (AGENT-05).

    Frozen — Verifier emits once; SwarmQueryPipeline reads (and may .model_copy
    for CF-04 forced-disagree override per Pitfall P-02).
    """
    model_config = ConfigDict(frozen=True)

    verdict:            Literal["agree", "disagree"]
    evidence_chunk_ids: list[str]
    reasoning:          str
    proposed_answer:    str                        # D-02 ALWAYS populated
    latency_ms:         int
```

---

### `utils/models.py` — 3 new `AgentEvent` subclasses (NEW)

**Primary analog:** `utils/models.py::ToolSpanStartEvent` / `ToolSpanEndEvent` / `ToolSpanErrorEvent` (lines 561–607) — three sibling events mirroring exactly what Phase 21 needs (start / complete / error-or-disagreement). The 200-char truncation contract (D-08 `summary`) mirrors `tool.span.error.error_message` at lines 594–607.

**ClassVar discriminator pattern** (verbatim from lines 561–607):

```python
class ToolSpanStartEvent(AgentEvent):
    """Emitted ONCE per tool dispatch BEFORE the coroutine awaits (D-05)."""
    event_type: ClassVar[str] = "tool.span.start"
    model_config = ConfigDict(frozen=True)

    span_id: str
    name:    str
    args:    dict[str, Any] = Field(default_factory=dict)


class ToolSpanErrorEvent(AgentEvent):
    """Emitted INSTEAD OF ``tool.span.end`` when a tool dispatch raises
    ``BaseException`` (D-12).

    ``error_message`` is ``str(exc)[:200]`` — the emitter truncates.
    """
    event_type: ClassVar[str] = "tool.span.error"
    model_config = ConfigDict(frozen=True)

    span_id:       str
    latency_ms:    int
    error_type:    str
    error_message: str
```

**Apply to 3 new events** (D-08, D-09, append after `utils/models.py:633`):

```python
class VerifierStartEvent(AgentEvent):
    """Emitted ONCE before Verifier.verify() awaits (D-09)."""
    event_type: ClassVar[str] = "verifier.start"
    model_config = ConfigDict(frozen=True)

    peer_count: int
    model:      str                                # resolved per D-05


class VerifierCompleteEvent(AgentEvent):
    """Emitted ONCE after Verifier.verify() returns successfully (D-09)."""
    event_type: ClassVar[str] = "verifier.complete"
    model_config = ConfigDict(frozen=True)

    verdict:              Literal["agree", "disagree"]
    evidence_chunk_count: int
    latency_ms:           int


class VerifierDisagreementEvent(AgentEvent):
    """Emitted on the three disagree paths (D-08).

    ``summary`` truncated to 200 chars at the emitter, mirroring
    ``ToolSpanErrorEvent.error_message`` (utils/models.py:594-607).
    """
    event_type: ClassVar[str] = "verifier.disagreement"
    model_config = ConfigDict(frozen=True)

    reason:             Literal["peers_diverge", "forced_no_evidence", "verifier_failed"]
    summary:            str
    evidence_chunk_ids: list[str]
    peer_count:         int
    error_type:         str | None = None          # populated only on verifier_failed
```

---

### `utils/models.py` — `GenerationRequest.debate` field + `model_validator` (MODIFY)

**Primary analog:** `config/settings.py::Settings._validate_security` (lines 410–448) — closest existing `@model_validator(mode="after")` pattern raising `ValueError` (which Pydantic V2 surfaces as 422 at the FastAPI body-parsing layer). Field-add pattern next to existing `swarm_mode` at `utils/models.py:215`.

**`model_validator` pattern** (verbatim from `config/settings.py:410–419`):

```python
@model_validator(mode="after")
def _validate_security(self) -> "Settings":
    secret = self.secret_key
    if len(secret) < 32:
        raise ValueError(
            "secret_key must be at least 32 characters. "
            "Run: python -c \"import secrets; print(secrets.token_hex(32))\" "
            "and set SECRET_KEY env var. Server will not start."
        )
    ...
    return self
```

**Apply to `GenerationRequest`** (D-10, modify `utils/models.py:205–224`):

```python
class GenerationRequest(BaseModel):
    """用户查询请求，通过 POST /query 接收。"""
    query:        str                           = Field(..., min_length=1, max_length=2000)
    ...
    swarm_mode:   bool                          = False
    debate:       bool                          = False   # AGENT-14 opt-in (CF-02)
    include_images: bool                        = False
    ...

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _check_debate_requires_swarm(self) -> "GenerationRequest":
        if self.debate and not self.swarm_mode:
            raise ValueError(
                "debate=True requires swarm_mode=True (verifier runs after peer fan-out)"
            )
        return self
```

**Import note:** `model_validator` is NOT currently imported in `utils/models.py:12`. Add to existing import line:
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
```

---

### `services/pipeline.py::SwarmQueryPipeline.run` — verifier hop (MODIFY)

**Primary analog:** Self — `SwarmQueryPipeline.run` lines 1192–1298. The verifier hop is INSERTED between the existing `asyncio.gather` (line 1230) and the existing `synth_t0` block (line 1252). All new code is gated `if req.debate:` to preserve SC5 byte-identity for `debate=False`.

**Existing `asyncio.gather` join pattern** (lines 1226–1250) — verifier hop sits AFTER the per-result unpack:

```python
sub_coros = [
    self._run_sub_agent(i, q, tf or {}, req)
    for i, q in enumerate(sub_questions)
]
raw_results = await asyncio.gather(*sub_coros, return_exceptions=True)
swarm_latency_ms = round((time.perf_counter() - swarm_t0) * 1000, 1)

answers: list[str] = []
per_agent_turns: list[int] = []
per_agent_tool_calls: list[int] = []
all_swarm_chunks: list[RetrievedChunk] = []
for i, res in enumerate(raw_results):
    # Pitfall 2: BaseException (covers asyncio.CancelledError, TimeoutError),
    # NOT Exception.
    if isinstance(res, BaseException):
        logger.error(f"[Swarm] sub-agent {i} raised: {res!r}")
        answers.append(f"[Sub-agent {i} failed: {res!r}]")
        ...
        continue
    answers.append(res.answer)
    ...
    all_swarm_chunks.extend(res.chunks)

# *** Phase 21 INSERT: verifier hop, gated on req.debate ***
synth_t0 = time.perf_counter()
final_answer = await self._synthesize(req.query, sub_questions, answers)  # +verifier_verdict kwarg
```

**Insert pattern** (between line 1250 and line 1252; mirror of existing audit-detail dict construction at lines 1276–1286):

```python
# Phase 21 — verifier hop, gated on req.debate (SC5: zero change when False).
verifier_events: list[AgentEvent] = []
verdict: VerifierVerdict | None = None
verifier_latency_ms = 0.0
audit_agent_05: dict[str, Any] = {}
if req.debate:
    verifier_t0 = time.perf_counter()
    # Pitfall P-03 — dedup BEFORE verifier sees evidence; gated on debate.
    deduped_evidence = AgentQueryPipeline._dedup_chunks(all_swarm_chunks)
    successful = [r for r in raw_results if not isinstance(r, BaseException)]
    model_label = settings.verifier_model or settings.active_model
    verifier_events.append(VerifierStartEvent(
        trace_id=trace_id, seq=len(verifier_events),
        ts_ms=int(time.time() * 1000),
        peer_count=len(successful), model=model_label,
    ))
    try:
        verdict = await self._verifier.verify(
            peer_results=successful, evidence=deduped_evidence,
            user_query=req.query,
        )
    except BaseException as exc:                       # CF-09 — NOT bare Exception
        logger.error("verifier_failed", exc_info=exc)  # full traceback to log only
        audit_agent_05["verifier_failed"] = True
        verifier_events.append(VerifierDisagreementEvent(
            trace_id=trace_id, seq=len(verifier_events),
            ts_ms=int(time.time() * 1000),
            reason="verifier_failed",
            summary=str(exc)[:200],                    # 200-char truncate (D-08)
            evidence_chunk_ids=[],
            peer_count=len(successful),
            error_type=type(exc).__name__,
        ))
    else:
        audit_agent_05["verifier_used"] = True
        audit_agent_05["evidence_chunk_count"] = len(verdict.evidence_chunk_ids)
        if verdict.verdict == "disagree":
            reason = "forced_no_evidence" if not verdict.evidence_chunk_ids else "peers_diverge"
            audit_agent_05["forced_disagree"] = (reason == "forced_no_evidence")
            verifier_events.append(VerifierDisagreementEvent(
                trace_id=trace_id, seq=len(verifier_events),
                ts_ms=int(time.time() * 1000),
                reason=reason, summary=verdict.reasoning[:200],
                evidence_chunk_ids=list(verdict.evidence_chunk_ids),
                peer_count=len(successful),
            ))
        verifier_events.append(VerifierCompleteEvent(
            trace_id=trace_id, seq=len(verifier_events),
            ts_ms=int(time.time() * 1000),
            verdict=verdict.verdict,
            evidence_chunk_count=len(verdict.evidence_chunk_ids),
            latency_ms=verdict.latency_ms,
        ))
    verifier_latency_ms = round((time.perf_counter() - verifier_t0) * 1000, 1)
    audit_agent_05["verifier_latency_ms"] = verifier_latency_ms
    audit_agent_05["verifier_model"] = model_label
```

**Audit-extension pattern** (mirror `services/pipeline.py:1270–1288` — add `agent_05` namespace key only when `req.debate`):

```python
await self._audit.log(AuditEvent(
    action=AuditAction.QUERY,
    user_id=user_id,
    tenant_id=tenant_id,
    resource_id=hashlib.sha256(req.query.encode()).hexdigest()[:16],
    result=AuditResult.SUCCESS,
    detail={
        "latency_ms":           total_ms,
        "sources_count":        len(all_swarm_chunks),
        "query_len":            len(req.query),
        "intent":               "swarm",
        "swarm_n":              len(sub_questions),
        "per_agent_turns":      per_agent_turns,
        "per_agent_tool_calls": per_agent_tool_calls,
        "swarm_latency_ms":     swarm_latency_ms,
        "synthesis_latency_ms": synthesis_latency_ms,
        # Phase 21 — namespaced under agent_05; absent when req.debate=False.
        **({"agent_05": audit_agent_05} if req.debate else {}),
    },
    trace_id=trace_id,
))
```

**`__init__` extension** (mirror lines 1010–1016 — add `self._verifier = Verifier()` at the end; cost paid once, only used when `req.debate=True`):

```python
def __init__(self) -> None:
    self._retriever        = get_retriever()
    self._llm              = get_llm_client()
    self._memory           = get_memory_service()
    self._audit            = get_audit_service()
    self._tenant_svc       = get_tenant_service()
    self._filter_extractor = get_filter_extractor()
    self._verifier         = Verifier()             # Phase 21 — Open Question #2 recommendation
```

---

### `services/pipeline.py::SwarmQueryPipeline._synthesize` — kwarg + helper (MODIFY)

**Primary analog:** Self — existing `_synthesize` body at lines 1157–1190. Extension preserves SC5 byte-identity (`verifier_verdict=None` default short-circuits to existing path).

**Existing body to preserve byte-identical** (lines 1157–1190):

```python
async def _synthesize(
    self,
    original_query: str,
    sub_questions: list[str],
    answers: list[str],
) -> str:
    """Synthesize sub-agent answers into final response (D-04, Pitfall 5)."""
    # Pitfall 5: skip LLM if every sub-agent failed.
    if answers and all(
        a.startswith("[Sub-agent ") and " failed:" in a
        for a in answers
    ):
        logger.error("[Swarm] all sub-agents failed; returning graceful degradation string without synthesis call")
        return "抱歉，所有子代理处理失败，无法生成答案。"

    sections: list[str] = [f"原始查询：{original_query}", ""]
    ...
    return await self._llm.chat(
        system=_SYNTHESIS_SYSTEM,
        user=formatted,
        temperature=0.1,
        task_type="generate",
    )
```

**Apply D-04 extension** (kwarg added BEFORE existing graceful-degradation guard so disagree path takes precedence):

```python
async def _synthesize(
    self,
    original_query: str,
    sub_questions: list[str],
    answers: list[str],
    *,
    verifier_verdict: VerifierVerdict | None = None,   # Phase 21 D-04
) -> str:
    # D-04: disagree path uses verifier.proposed_answer verbatim — ZERO LLM calls.
    if verifier_verdict is not None and verifier_verdict.verdict == "disagree":
        return self._format_disagree(verifier_verdict, len(answers))
    # ... existing body unchanged below ...

@staticmethod
def _format_disagree(verdict: VerifierVerdict, peer_count: int) -> str:
    """D-03 — exact banner template (locked-string contract; Pitfall P-08)."""
    # Module-level constant per Pitfall P-08 future-proofing recommendation:
    banner = _DISAGREE_BANNER_TEMPLATE.format(
        N=peer_count,
        M=peer_count,                              # planner picks M; default M=N
        chunk_count=len(verdict.evidence_chunk_ids),
    )
    return f"{verdict.proposed_answer}\n\n{banner}"
```

**Module-level constant** (Pitfall P-08 — single-symbol edit for v1.6+ i18n):

```python
# Phase 21 D-03 locked Chinese banner. Pitfall P-08: Phase 20 P-11 carry-forward
# (English query → Chinese banner is accepted limitation for v1.5).
_DISAGREE_BANNER_TEMPLATE = (
    "⚠️ 子代理间存在分歧（{N} 个同伴中的 {M} 个提出差异回答）。"
    "以上回答基于验证者引用的证据（{chunk_count} 个块）。"
)
```

---

### `config/settings.py` — `verifier_model` / `verifier_provider` fields (MODIFY)

**Primary analog:** `config/settings.py:271–283` — provider/model field block (`openai_api_key`, `openai_model`, `anthropic_api_key`, `anthropic_model`). Same `Literal` pattern, same `str | None = None` optional shape.

**Pattern to copy** (lines 267–275 for `Literal` field; lines 271–275 for default-empty providers):

```python
llm_provider:       Literal["ollama", "openai", "anthropic", "azure"] = "openai"
ollama_base_url:    str   = "http://localhost:11434"
ollama_model:       str   = "qwen2.5:14b"
...
openai_api_key:     str   = ""
openai_model:       str   = "gpt-4o"
anthropic_api_key:  str   = ""
anthropic_model:    str   = "claude-sonnet-4-6"
```

**Apply** (D-05; append after line 285 `llm_max_tokens` — keeps related-fields-together convention):

```python
# Verifier sub-agent (Phase 21 / AGENT-05) — None = reuse peer model/provider.
verifier_model:    str | None = None
verifier_provider: Literal["openai", "anthropic"] | None = None
```

**No validator added** — Pitfall P-09: `AnthropicLLMClient.__init__` already fails when `ANTHROPIC_API_KEY=""` via the `anthropic.AsyncAnthropic(api_key=...)` SDK constructor at `services/generator/llm_client.py:597–598`. No new validation logic needed.

---

### `tests/unit/test_verifier.py` (NEW — unit, mock LLM)

**Primary analog:** `tests/unit/test_swarm_pipeline.py:73–111` (`mock_pipeline` fixture) — same `MagicMock`+`AsyncMock` seam pattern; same `_chunk()`/`_turn()` helper shape.

**Helper-fixture pattern** (verbatim from `tests/unit/test_swarm_pipeline.py:34–61`):

```python
def _chunk(chunk_id: str, doc_id: str = "d1", title: str = "t") -> RetrievedChunk:
    """Make a minimal RetrievedChunk with deterministic chunk_id."""
    md = ChunkMetadata(doc_id=doc_id, title=title)
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        content=f"content-{chunk_id}",
        metadata=md,
    )


def _turn(*, stop_reason: str = "text_only", text: str = "") -> AgenticTurn:
    return AgenticTurn(
        text=text,
        tool_calls=[],
        stop_reason=stop_reason,
        raw_assistant_msg={"role": "assistant", "content": text},
        usage_input_tokens=0,
        usage_output_tokens=0,
    )
```

**Mock-seam pattern** (mirror `tests/unit/test_swarm_pipeline.py:84–86` — patch at the consumer module path per CONTEXT "established patterns"):

```python
@pytest.fixture
def mock_verifier(monkeypatch: pytest.MonkeyPatch) -> Verifier:
    """Patch services.agent.verifier.get_llm_client (consumer path, NOT the SDK)."""
    fake_llm = MagicMock()
    fake_llm.call_agentic_turn = AsyncMock()
    monkeypatch.setattr("services.agent.verifier.get_llm_client", lambda: fake_llm)
    v = Verifier()
    v._llm = fake_llm                                 # ensure
    return v
```

**Assertion pattern** — mock returns `AgenticTurn` whose `.text` is the JSON; assert on `Verifier.verify()` return value. See RESEARCH.md `tdd-2` for the full 11 cases.

---

### `tests/integration/test_swarm_debate_e2e.py` (NEW — integration, latency assertion)

**Primary analog:** `tests/unit/test_agent_sse.py:234–255` for the latency-bound assertion shape; `tests/integration/test_swarm_pipeline_e2e.py` for the credential-required integration shape.

**Latency-bound assertion pattern** (verbatim from `tests/unit/test_agent_sse.py:247–250`):

```python
t0 = time.perf_counter()
events = [evt async for evt in pipeline.run_streaming(_req())]
elapsed_ms = int((time.perf_counter() - t0) * 1000)
assert 450 < elapsed_ms < 700, f"expected 450 < elapsed_ms < 700, got {elapsed_ms}"
```

**Apply for SC2 latency** (3 peers × 0.3s + verifier × 0.2s ≤ ~500ms + overhead):

```python
@pytest.mark.asyncio
async def test_swarm_debate_latency_bounded_by_max_peer_plus_verifier(
    mock_pipeline,
    gen_req,
) -> None:
    PEER_DELAY_S, VERIFIER_DELAY_S = 0.3, 0.2

    async def slow_peer_turn(**_kw: Any) -> AgenticTurn:
        await asyncio.sleep(PEER_DELAY_S)
        return _turn(stop_reason="text_only", text="ans")

    async def slow_verifier_call(**_kw: Any) -> AgenticTurn:
        await asyncio.sleep(VERIFIER_DELAY_S)
        return _turn(
            stop_reason="text_only",
            text='{"verdict":"agree","evidence_chunk_ids":["c1"],'
                 '"reasoning":"ok","proposed_answer":"ans","latency_ms":200}',
        )

    # Discriminate verifier vs peer call by the empty-tools signature (CF-03).
    mock_pipeline._llm.call_agentic_turn = AsyncMock(
        side_effect=lambda **kw: slow_verifier_call(**kw) if kw.get("tools") == []
        else slow_peer_turn(**kw)
    )
    mock_pipeline._llm.chat = AsyncMock(side_effect=['["q1","q2","q3"]', "synth"])

    debate_req = gen_req.model_copy(update={"debate": True})
    t0 = time.perf_counter()
    await mock_pipeline.run(debate_req)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert 450 < elapsed_ms < 700, (
        f"max(peer)+verifier=500ms; got {elapsed_ms}ms (sum would be 1100ms)"
    )
```

**Integration marker pattern** (project standard from `tests/integration/test_swarm_pipeline_e2e.py`):

```python
import pytest
pytestmark = [pytest.mark.integration]                # skipped by default; CI opts in
```

---

### `docs/agent-architecture.md` — 3 new event subsections (MODIFY)

**Primary analog:** `docs/agent-architecture.md:292–347` — `tool.span.start` / `tool.span.end` / `tool.span.error` triple. Same `### <event_type>` heading + table + JSON example layout.

**Pattern to copy** (lines 309–327 — `tool.span.end`):

```markdown
### tool.span.end

Emitted when a tool dispatch resolves to `ToolResult`; replaced by
`tool.span.error` when the dispatch raises `BaseException`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `span_id` | string (8-hex) | yes | Matches the prior `tool.span.start`. |
| `latency_ms` | integer | yes | Wall-clock ms for this single dispatch (per-tool, not per-group). |
| `chunk_count` | integer | yes | From `ToolResult.metadata["chunk_count"]` ... |
| `is_error` | boolean | yes | `True` if the tool returned a controlled error result ... |
| `content_preview` | string | yes | First 200 characters of `ToolResult.content`. |

Example payload:

\`\`\`json
{"span_id": "9f3c1e2a", "latency_ms": 412, "chunk_count": 3, "is_error": false,
 "content_preview": "<context>\n[来源1] 员工产假为98天..."}
\`\`\`
```

**Apply** — append three subsections after `docs/agent-architecture.md:373` (after `### synthesizer.final`). Each new subsection: `### verifier.start` / `### verifier.complete` / `### verifier.disagreement` with the same table layout + a JSON example. Per `exec-2`, prepend a backward-compat note:

```markdown
> The three event types below are emitted ONLY when `req.debate=True`. Non-debate
> flows are unchanged — the existing six event types remain the complete event
> surface for `debate=False` requests. `synthesizer.final` remains the terminal
> event in all paths (CF-07).
```

---

## Shared Patterns

These cross-cutting patterns apply to multiple Phase 21 files. Plans should reference them once here rather than duplicating in each plan action.

### Frozen Pydantic V2 model + ClassVar discriminator

**Source:** `utils/models.py:537–633` (`AgentEvent` base + 6 subclasses); `utils/models.py:244–258` (`ToolCall` for non-event frozen models).

**Apply to:** `VerifierVerdict`, `VerifierStartEvent`, `VerifierCompleteEvent`, `VerifierDisagreementEvent`.

**Pattern** (canonical):
```python
class FooEvent(AgentEvent):
    """Docstring."""
    event_type: ClassVar[str] = "foo.bar"             # discriminator; excluded from model_dump
    model_config = ConfigDict(frozen=True)            # explicit even though parent has it
    # ... payload fields ...
```

The double `model_config` declaration on the subclass is the existing convention (lines 556, 569, 585, 602, 619, 629) — do not drop it.

### `@model_validator(mode="after")` cross-field validation

**Source:** `config/settings.py:410–448` (`_validate_security`).

**Apply to:** `GenerationRequest._check_debate_requires_swarm` (D-10).

**Pattern:** Read `self.field_a` + `self.field_b`; raise `ValueError` with actionable message; `return self`. Pydantic V2 surfaces the `ValueError` as 422 at FastAPI body-parsing.

### JSON-extract-then-validate (LLM-output hardening)

**Source:** `services/pipeline.py:1034–1043` (`SwarmQueryPipeline._decompose`).

**Apply to:** `Verifier._parse` (mirror with `\{.*\}` instead of `\[.*\]`).

**Pattern:** `re.search(r"\{.*\}", raw, re.DOTALL)` → `json.loads(match.group(0))` → `pydantic.model_validate(parsed)`. All three failure modes (no match / `JSONDecodeError` / `ValidationError`) become exceptions caught by D-06's `except BaseException` at the caller.

### `BaseException` (NOT `Exception`) failure isolation

**Source:** `services/pipeline.py:1240–1245` (existing swarm pattern); CF-09 v1.3 carry-forward.

**Apply to:** `SwarmQueryPipeline.run` verifier hop (D-06).

**Pattern:**
```python
except BaseException as exc:                          # covers CancelledError, TimeoutError
    logger.error("verifier_failed", exc_info=exc)     # full traceback to log only
    # ... emit event with summary truncated to 200 chars ...
```

This honors project rule ERR-01 (no bare `except`) AND CF-09 (use `BaseException` for swarm-style isolation).

### Audit-row extension (metadata key, no enum migration)

**Source:** `services/pipeline.py:1270–1288` (existing swarm `AuditEvent.log()` call); `services/audit/audit_service.py:48–59` (`AuditEvent` dataclass with `detail: dict`).

**Apply to:** Phase 21 D-06 (`verifier_failed`) + D-11 (`forced_disagree`) audit metadata writes.

**Pattern:** Reuse `AuditAction.QUERY` (existing); add new keys under namespaced sub-dict:
```python
detail = {
    # ... existing 9 keys ...
    "agent_05": {                                     # namespace per CONTEXT specifics
        "verifier_used":         True,
        "verifier_failed":       False,
        "forced_disagree":       False,
        "verifier_latency_ms":   verifier_latency_ms,
        "verifier_model":        model_label,
        "evidence_chunk_count":  n,
    },
}
```

All values JSON-native (Pitfall P-07): `bool` / `int` / `float` / `str`.

### Mock-at-consumer-path test seam

**Source:** `tests/unit/test_swarm_pipeline.py:73–111` (`mock_pipeline` fixture); CONTEXT "established patterns" v1.3 Phase 13/15.

**Apply to:** All Phase 21 unit tests (`tests/unit/test_verifier.py`, extensions to `tests/unit/test_swarm_pipeline.py`).

**Pattern:** Patch the consumer path (`services.agent.verifier.get_llm_client`), NOT the SDK (`anthropic.AsyncAnthropic`). Use `MagicMock` for collaborators, `AsyncMock` for awaited methods.

### Structured `loguru` logging (no print, no stdlib logger)

**Source:** Every `services/pipeline.py` line touching errors (e.g. lines 1036, 1042, 1103, 1147, 1241, 1273).

**Apply to:** `Verifier` warnings (e.g., evidence-filter drops); `SwarmQueryPipeline.run` verifier-failure logging.

**Pattern:**
```python
from loguru import logger
logger.warning(f"[Verifier] dropped {n} chunk_ids not in supplied evidence")
logger.error("verifier_failed", exc_info=exc)        # exc_info=exc keeps full traceback
```

---

## No Analog Found

None. Every file target in CONTEXT.md `<code_context>` Integration Points has a strong in-repo analog. The closest "weak" case is `services/agent/verifier.py` (NEW file, NEW module path) — but its shape is a near-verbatim mirror of `SwarmQueryPipeline._decompose` (LLM call → JSON regex → Pydantic validate → fallback), and `services/agent/_demo_runner.py` already establishes the `services/agent/<X>.py` module placement convention.

---

## Metadata

**Analog search scope:**
- `services/pipeline.py` (full file, 1306 lines — read in 4 ranges: 1–50, 540–600, 700–725, 997–1306)
- `utils/models.py` (lines 1–30, 170–240, 525–633)
- `services/generator/llm_client.py` (lines 220–280, 1015–1050)
- `services/audit/audit_service.py` (lines 20–90)
- `services/agent/_demo_runner.py` (lines 85–100)
- `config/settings.py` (lines 260–295, 405–450)
- `tests/unit/test_swarm_pipeline.py` (lines 1–120)
- `tests/unit/test_agent_sse.py` (lines 220–260)
- `tests/integration/test_swarm_pipeline_e2e.py` (file presence verified)
- `docs/agent-architecture.md` (lines 240–375)

**Files scanned:** 10 production / test / docs files (no Glob/Grep needed — RESEARCH.md provided line-precise anchors).

**Pattern extraction date:** 2026-05-10

---

*Phase: 21-AGENT-05 Multi-Agent Debate / Sub-Agent Verifier*
*Pattern map written: 2026-05-10*
