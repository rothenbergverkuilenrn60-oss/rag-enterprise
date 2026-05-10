# Phase 21: AGENT-05 Multi-Agent Debate / Sub-Agent Verifier - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Introduce a single-pass **verifier sub-agent** that runs **after** `SwarmQueryPipeline`'s
`asyncio.gather` peer fan-out **when `req.debate=True`**. The verifier reads the N peer
answers + their cited evidence chunks and emits a structured `VerifierVerdict`
(`agree` / `disagree`). On disagreement, the synthesizer composes a final response that
surfaces the divergence and the evidence-supported answer. Three new SSE event types
extend the v1.4 schema (`verifier.start`, `verifier.complete`, `verifier.disagreement`);
`synthesizer.final` remains terminal. Latency stays bounded by `max(peer) + verifier`,
NOT `sum`.

**In scope:**
- `services/agent/verifier.py::Verifier` class + `VerifierVerdict` Pydantic V2 frozen model
- `GenerationRequest.debate: bool = False` opt-in field + `debate→swarm_mode` cross-field validator
- `SwarmQueryPipeline.run()` verifier hop after peer `asyncio.gather` (only when `debate=True`)
- 3 new `AgentEvent` subclasses (`VerifierStartEvent`, `VerifierCompleteEvent`, `VerifierDisagreementEvent`)
- `SwarmQueryPipeline._synthesize` debate branch (uses `verifier.proposed_answer` on disagree)
- Optional `Settings.verifier_model` / `verifier_provider` (defaults to peer model)
- `docs/agent-architecture.md` Event Schema Reference extension
- v1.3 invariants intact (RLS, audit log, combined coverage ≥ 70%, no production change when `debate=False`)

**Out of scope:**
- Iterative peer-debate (N rounds of mutual critique) — STATE Q#3 chose verifier role pattern (a)
- Always-on debate trigger — STATE Q#4 chose opt-in `req.debate=True`
- Verifier tool use — SC1 locks text-only `call_agentic_turn` (no tools)
- Refactor to extract `Synthesizer` class — keeps blast radius minimal; defer to v1.6+
- New per-tool retry/timeout config on `BaseTool` — Phase 17/20 deferred; not in v1.5
- UI changes for divergence display — text-only banner in answer prose; future UX deferred to v1.6+
- New audit `AuditAction` enum value — reuse existing `AGENT` action with metadata key

</domain>

<decisions>
## Implementation Decisions

### VerifierVerdict schema

- **D-01:** **Full schema** — `verdict: Literal["agree","disagree"]`, `evidence_chunk_ids: list[str]`,
  `reasoning: str`, `proposed_answer: str`, `latency_ms: int`. Frozen Pydantic V2 model.
  Lives in `utils/models.py` next to `RetrievedChunk` / `GenerationRequest` (matches Phase 16/17
  D-01 placement convention). Verifier emits its own evidence-supported answer text so the
  synthesizer does NOT need a second LLM hop on disagree.
- **D-02:** **`proposed_answer` always populated** — both `agree` and `disagree` verdicts.
  Field is `str` (not `str | None`). Even on agree, verifier states the consensus answer.
  Forces verifier to commit and gives synthesizer an unconditional fallback. No `max_length`
  ceiling at the model level (verifier system prompt enforces brevity).

### Synthesizer divergence composition

- **D-03:** **Verifier `proposed_answer` + divergence note** — On disagree, the synthesizer
  emits `verifier.proposed_answer` as primary, then appends a short note:
  `⚠️ 子代理间存在分歧（{N} 个同伴中的 {M} 个提出差异回答）。以上回答基于验证者引用的证据（{len(evidence_chunk_ids)} 个块）。`
  Compact, evidence-led, decisive. Final answer text language matches user query language
  (Phase 20 deferred P-11 carry-forward).
- **D-04:** **Composition lives in `SwarmQueryPipeline._synthesize`** — extend the existing
  method with optional `verifier_verdict: VerifierVerdict | None = None` keyword. If present
  and `verdict == "disagree"`, route through a new private `_format_disagree(verdict, sub_results)`
  helper. SC5 holds: when `debate=False`, `verifier_verdict` defaults to `None` and the
  consensus path is byte-identical. NO new `Synthesizer` class (deferred to v1.6+).

### Verifier LLM model choice

- **D-05:** **Configurable via Settings, default = peer model** —
  ```
  verifier_model:    str | None = Field(default=None, description="...")
  verifier_provider: Literal["openai", "anthropic"] | None = None
  ```
  When both are `None`, the verifier reuses the same provider/model the swarm peers use
  (resolved through the existing `get_llm_client()` factory). Gives a cost-control knob
  without forcing a choice now; matches v1.0+ env-driven model selection pattern.

### Verifier failure isolation

- **D-06:** **Degrade-with-signal** — On `BaseException` from
  `verifier.verify(...)`:
    1. `log.error("verifier_failed", exc_info=exc)` (full traceback to logger only).
    2. Emit `VerifierDisagreementEvent(reason="verifier_failed", error_type=type(exc).__name__, ...)`.
    3. Audit row records the failure (reuse `AGENT` action; metadata key
       `verifier_failed=true`).
    4. Set `verdict = None` so `_synthesize` falls through to the standard
       (non-debate) consensus path. User still gets an answer.
  Latency stays bounded; observers can tell debate degraded vs ran cleanly.
- **D-07:** **No additional tenacity wrapper at the `Verifier` class level** —
  `BaseLLMClient.call_agentic_turn` already has provider-side retry built into the
  underlying provider clients. Layering another retry compounds latency on bad-provider
  days. The D-06 failure path catches whatever falls out.

### VerifierDisagreementEvent payload

- **D-08:** **Wire fields:**
  ```
  class VerifierDisagreementEvent(AgentEvent):
      event_type: ClassVar[str] = "verifier.disagreement"
      model_config = ConfigDict(frozen=True)
      reason: Literal["peers_diverge", "forced_no_evidence", "verifier_failed"]
      summary: str                      # ≤ 200 chars, truncated by emitter (mirrors tool.span.error)
      evidence_chunk_ids: list[str]
      peer_count: int
      error_type: str | None = None     # populated only on reason="verifier_failed"
  ```
  Three `reason` values exhaust the disagreement triggers: real divergence, forced override
  (D-12), runtime failure (D-06). `summary` truncation mirrors the Phase 18 D-12
  `tool.span.error` 200-char rule.

### Sibling event shapes

- **D-09:** **VerifierStartEvent + VerifierCompleteEvent shapes** — mirror `tool.span.start/end`
  pattern:
  ```
  class VerifierStartEvent(AgentEvent):
      event_type: ClassVar[str] = "verifier.start"
      peer_count: int
      model: str                       # which LLM model was selected (after D-05 resolution)

  class VerifierCompleteEvent(AgentEvent):
      event_type: ClassVar[str] = "verifier.complete"
      verdict: Literal["agree", "disagree"]
      evidence_chunk_count: int
      latency_ms: int
  ```
  No `proposed_answer_preview` field (kept off the wire to avoid PII echo and frame bloat;
  full text reaches users only via `synthesizer.final`).

### `debate=True` validation

- **D-10:** **422 at Pydantic boundary** — add a `model_validator(mode="after")` on
  `GenerationRequest`:
  ```
  @model_validator(mode="after")
  def _check_debate_requires_swarm(self) -> "GenerationRequest":
      if self.debate and not self.swarm_mode:
          raise ValueError(
              "debate=True requires swarm_mode=True (verifier runs after peer fan-out)"
          )
      return self
  ```
  Fails fast at request boundary. Clearest API contract; no surprising server-side flips.

### Forced-disagree audit signal

- **D-11:** **Two-channel signal** — When SC1 forces `agree` → `disagree` because
  `evidence_chunk_ids` is empty:
    1. Emit `VerifierDisagreementEvent(reason="forced_no_evidence", ...)` for live observers.
    2. Audit row uses the existing `AGENT` `AuditAction` with metadata key
       `forced_disagree=true` (no new enum value, no DB migration).
  Aligns with v1.3 audit + v1.4 SSE patterns. Post-hoc DB queries can filter
  `metadata->>'forced_disagree' = 'true'` to count override frequency.

### Carrying forward (locked by roadmap / STATE — NOT re-asked)

- **CF-01:** Verifier-role pattern (single sub-agent reads N answers) — STATE Q#3 chose (a).
- **CF-02:** Opt-in trigger via `req.debate=True` — STATE Q#4 chose opt-in.
- **CF-03:** `BaseLLMClient.call_agentic_turn` text-only (no tools) — SC1.
- **CF-04:** Forced-disagree rule: `verdict=="agree"` AND empty `evidence_chunk_ids` →
  override to `disagree` — SC1.
- **CF-05:** Three new SSE events (`verifier.start`, `verifier.complete`,
  `verifier.disagreement`) as frozen Pydantic V2 subclasses of `AgentEvent` — SC3.
- **CF-06:** Latency contract: `total ≤ max(peer_latency) + verifier_latency + small_overhead`
  (verifier sequential after `asyncio.gather`) — SC2.
- **CF-07:** `synthesizer.final` remains terminal in all paths — SC3.
- **CF-08:** Backward compat: `debate=False` runs unchanged; SC5 forbids production-code
  changes when `debate=False`.
- **CF-09:** v1.3 carry-forward: `BaseException` (not `Exception`) for failure isolation;
  sub-agents do NOT inherit chat history; `parallel_tool_calls=True` / `disable_parallel_tool_use=False`
  remain explicit at the LLM client layer.
- **CF-10:** RLS isolates tenants; audit log records verifier sub-agent calls with same
  fields as v1.3 swarm; combined coverage stays ≥ 70% — SC5.

### Claude's Discretion

- **Verifier system prompt wording** — D-03's "forbid inventing facts" is the locked intent.
  Exact prose chosen by planner; should at minimum: (a) instruct the model to cite only
  chunk IDs from the supplied evidence list, (b) instruct it to write `proposed_answer` in
  the same language as the user query (P-11 carry-forward from Phase 20 deferred), (c)
  instruct it to emit JSON matching `VerifierVerdict` schema (use `response_format`
  JSON-mode where provider supports it).
- **`evidence_chunk_ids` validation** — D-01's `evidence_chunk_ids: list[str]` are by
  contract drawn from the chunks supplied to the verifier. Implementation may optionally
  filter the verifier's response to drop IDs not in the supplied set (defensive); minimum
  bar is the SC1 forced-disagree rule.
- **`reasoning` field length cap** — `str`, no hard ceiling at the model level. Verifier
  system prompt should request "1-2 sentences"; planner picks any pragmatic truncation.
- **Verifier hop placement in `run_streaming`** — SwarmQueryPipeline currently has only
  `run()` (no `run_streaming` for swarm; v1.4 SSE streaming lives in `AgentQueryPipeline`).
  Planner confirms which method needs the verifier hop and whether a parallel
  `run_streaming` for swarm is in scope (likely not — `synthesizer.final` event is the
  terminal marker for the swarm-debate path; full SSE streaming for swarm is a v1.6+ topic).
- **Test layout** — Carry v1.3 conventions: unit tests in `tests/unit/test_verifier.py`,
  integration in `tests/integration/test_swarm_debate_e2e.py`. Mock at consumer path
  (`services.pipeline.<dep>`) per v1.3 Phase 13 / 15. Latency assertion uses synthetic
  delays in mocks.
- **`Settings.verifier_provider` validation** — If `verifier_provider="anthropic"` and
  `ANTHROPIC_API_KEY` is unset, fail at startup (mirrors existing v1.0+ provider checks).
  Planner picks the exact validation seam.
- **Audit metadata key naming** — `verifier_failed` (D-06) and `forced_disagree` (D-11) are
  the locked semantics. Exact JSON layout under the audit row's metadata dict is planner's
  choice; suggestion: nested `{"agent_05": {"verifier_failed": true, ...}}` to namespace.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 21 source artifacts
- `.planning/phases/21-agent-05-multi-agent-debate-sub-agent-verifier/21-CONTEXT.md` — this file (decisions D-01..D-11 + CF-01..CF-10)
- `.planning/phases/21-agent-05-multi-agent-debate-sub-agent-verifier/21-DISCUSSION-LOG.md` — audit trail of options considered (human reference only)
- `.planning/ROADMAP.md` §"Phase 21: AGENT-05 Multi-Agent Debate / Sub-Agent Verifier" — goal + 5 success criteria + canonical refs
- `.planning/REQUIREMENTS.md` §"Multi-Agent Debate / Sub-Agent Verify (AGENT)" — AGENT-05, AGENT-14, AGENT-15
- `.planning/STATE.md` §"Open Questions Carried into v1.5 Planning" — Q#3 (verifier-role pattern), Q#4 (opt-in trigger)
- `.planning/STATE.md` §"Carry-Forward Decisions (still in force)" — CF-09 sources

### Code anchors (read before editing)
- `services/pipeline.py:997 SwarmQueryPipeline` — verifier hop integration site
  - `services/pipeline.py:1068 _run_sub_agent` — peer execution shape (read for `_SubAgentResult` contract; note naming mismatch with roadmap's `SubAgentAnswer` — planner reconciles)
  - `services/pipeline.py:1192 SwarmQueryPipeline.run()` — main entry; `asyncio.gather` at line 1230; verifier hop is appended AFTER this gather
  - `services/pipeline.py:_synthesize` (internal to swarm class) — extend with `verifier_verdict: VerifierVerdict | None = None` kwarg per D-04
  - `services/pipeline.py:710 _dedup_chunks` — applied to gathered peer results before verifier sees them
- `services/generator/llm_client.py::BaseLLMClient.call_agentic_turn` — provider-neutral verifier LLM call (CF-03); existing tenacity covered (D-07)
- `utils/models.py:537 AgentEvent` (frozen Pydantic V2) + 6 existing subclasses (`PlannerPlanEvent`, `ToolSpanStartEvent`, `ToolSpanEndEvent`, `ToolSpanErrorEvent`, `ExecutorParallelEvent`, `SynthesizerFinalEvent`) — pattern to mirror for D-08/D-09 events
- `utils/models.py:205 GenerationRequest` — add `debate: bool = False` field next to `swarm_mode`; add D-10 model_validator
- `utils/models.py:180 RetrievedChunk` — chunks supplied to verifier; `chunk_id` is the field referenced by `evidence_chunk_ids`
- `controllers/api.py:259 /agent/v1/run/stream (agent_run_stream)` — pure passthrough route; no change required for new event types (events serialize via `event_type` ClassVar discriminator at `services/agent/_demo_runner.py:89 emit_sse_frame`)
- `services/audit/audit_service.py:25 AuditAction` enum — reuse existing `AGENT` action; D-11 uses metadata key, no enum migration
- `config/settings.py` — add `verifier_model` / `verifier_provider` per D-05 (mirror existing `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` pattern)
- `docs/agent-architecture.md` §"Event Schema Reference" (line 245) — extend with three new subsections (`### verifier.start`, `### verifier.complete`, `### verifier.disagreement`) + example payloads + backward-compat note

### Precedent CONTEXT.md (read once for orientation)
- `.planning/phases/20-websearchtool-real-implementation-tavily/20-CONTEXT.md` — most recent; same milestone; established the `ToolResult` + audit + retry conventions Phase 21 carries forward
- Earlier phase CONTEXT.md files are not present under `.planning/phases/` (older milestones used different layout); STATE.md `Carry-Forward Decisions` is the canonical summary instead

### Test references
- `tests/unit/test_swarm_pipeline.py` — existing swarm unit test surface; verifier unit tests slot into `tests/unit/test_verifier.py`
- `tests/integration/test_swarm_pipeline_e2e.py` — existing swarm e2e; verifier integration into `tests/integration/test_swarm_debate_e2e.py` (planner picks)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`AgentEvent` base + 6 subclasses** (`utils/models.py:537+`): frozen Pydantic V2 model with
  `trace_id` / `seq` / `ts_ms` common fields and `event_type: ClassVar[str]` discriminator.
  D-08 / D-09 events plug in zero-friction (just add three subclasses).
- **`emit_sse_frame` at `services/agent/_demo_runner.py:89`**: serializes any `AgentEvent`
  via `model_dump_json()` + `event_type` ClassVar. Three new event subclasses serialize
  through this same path with no change.
- **`SwarmQueryPipeline._audit` (line 997+)**: `get_audit_service()` already wired into the
  swarm pipeline `__init__`. D-06 / D-11 audit metadata writes reuse `self._audit.log(AuditEvent(...))`
  exactly like the existing v1.3 swarm path at `pipeline.py:371`.
- **`BaseLLMClient.call_agentic_turn`**: provider-neutral text-only call. Verifier passes
  `tools=[]` (or omits the kwarg per signature) so no tool-loop is exercised.
- **`get_llm_client()` factory pattern**: D-05's optional `verifier_model` / `verifier_provider`
  resolves through this factory exactly the way swarm peers do today.
- **`@model_validator(mode="after")` on Pydantic models**: existing pattern in v1.x request
  models (e.g., `GenerationRequest.strip_query` `field_validator`); D-10 adds a sibling
  cross-field validator next to it.

### Established Patterns
- **Frozen Pydantic V2 models everywhere on the agent surface** (Phase 16/17 D-01 placement
  convention) — `VerifierVerdict` and the 3 events follow.
- **`asyncio.gather` for fan-out, sequential single calls for joins** (v1.2 Phase 11) — verifier
  is the join (sequential, after gather). Latency contract `max(peer) + verifier` is structural,
  not just a test assertion.
- **Mock at consumer path** (`services.pipeline.<dep>`) per v1.3 Phase 13 / 15 — verifier
  unit tests mock `services.pipeline.get_llm_client` (or wherever the planner places the seam),
  not the underlying provider SDK.
- **Audit metadata as JSON dict** — existing v1.3/v1.4 pattern; D-06 / D-11 add namespaced
  keys, no schema migration.
- **`event_type: ClassVar[str]` discriminator** — every concrete `AgentEvent` subclass
  declares its own; ClassVar is excluded from `model_dump()` automatically (Pydantic V2
  default). Three new events follow.
- **System-prompt parity sacred** — Phase 20 D-02 carry-forward: changes to `_AGENT_SYSTEM`
  break v1.3/v1.4 prompt-parity fixtures. Verifier has its OWN system prompt; do NOT touch
  `_AGENT_SYSTEM`.

### Integration Points
- `services/agent/verifier.py` (NEW) — `Verifier` class, ≤ 150 lines; one public `verify()`
  method, one private prompt builder, one private response parser.
- `utils/models.py` — append `VerifierVerdict` + `VerifierStartEvent` + `VerifierCompleteEvent`
  + `VerifierDisagreementEvent`; add `debate: bool = False` field on `GenerationRequest` +
  D-10 model_validator. Touch ≤ 80 lines.
- `services/pipeline.py:1192-1240 SwarmQueryPipeline.run()` — append verifier hop after
  `asyncio.gather`; emit start/complete/disagreement events; pass `verifier_verdict` to
  `_synthesize`. Touch ≤ 80 lines including the audit row.
- `services/pipeline.py:_synthesize` — accept `verifier_verdict: VerifierVerdict | None = None`
  kwarg; add `_format_disagree(verdict, sub_results)` helper. Touch ≤ 40 lines.
- `config/settings.py` — append `verifier_model` / `verifier_provider` settings. Touch ≤ 6 lines.
- `controllers/api.py` — NO change. Routes are pure passthroughs of the new event types.
- `docs/agent-architecture.md` §"Event Schema Reference" — append three subsections + payloads
  + backward-compat note. Touch ~80 lines of doc.
- `tests/unit/test_verifier.py` (NEW) — verifier unit: agree path, disagree path, forced-disagree
  rule (SC1), `proposed_answer` always populated (D-02), invalid-JSON response, LLM raises (D-06).
- `tests/integration/test_swarm_debate_e2e.py` (NEW) — SC2 latency assertion (synthetic peer
  delays + verifier delay → assert `total ≤ max(peer) + verifier + small_overhead`); SSE event
  sequence assertion; D-10 422 path.
- `tests/unit/test_models.py` — extend with D-10 cross-field validator test; D-08/D-09 event
  shape tests.

</code_context>

<specifics>
## Specific Ideas

- **`proposed_answer` is the single source of truth on disagree** (D-01/D-04) — synthesizer
  does NOT regenerate. This means the verifier's quality bar IS the user-visible answer
  bar on the disagree path. Verifier system prompt must be written carefully (Claude's
  discretion above).
- **Divergence note text is locked** (D-03) — the Chinese banner template is the contract.
  Future-Claude editing this string must update the test assertion AND the language-matching
  rule (P-11 carry-forward from Phase 20).
- **Three `reason` values exhaust DisagreementEvent triggers** (D-08) — `peers_diverge`,
  `forced_no_evidence`, `verifier_failed`. Adding a fourth requires a Literal bump and a
  doc update; planner should treat the Literal as a closed set for v1.5.
- **No `Synthesizer` class extraction in this phase** (D-04) — keeps SC5's "no production
  change when `debate=False`" structurally true. A future `Synthesizer` extraction is a
  v1.6+ refactor with its own design discussion.
- **Audit metadata namespacing** — D-06 (`verifier_failed=true`) and D-11 (`forced_disagree=true`)
  share the audit row's metadata dict. Suggestion (Claude's discretion): nest under
  `{"agent_05": {...}}` to keep verifier-related keys together and grep-friendly.
- **Verifier sees DEDUPED chunks** (`pipeline.py:710 _dedup_chunks` runs pre-synthesis in v1.3
  swarm path) — verifier's `evidence_chunk_ids` reference deduped chunk_ids; planner confirms
  exact ordering of dedup vs verifier hop.

</specifics>

<deferred>
## Deferred Ideas

### To v1.6+
- **Iterative peer-debate** (N rounds of mutual critique) — STATE Q#3 chose (a) verifier role
  for v1.5; (b) peer-debate is a separate phase with its own latency model.
- **Always-on debate trigger** — opt-in is locked for v1.5 (CF-02); deferred until cost &
  quality data justify auto-on.
- **`Synthesizer` class extraction** — D-04 inlines composition into `_synthesize`; future
  refactor pulls out a dedicated class behind frozen contracts (probably alongside swarm-streaming).
- **Swarm `run_streaming` for SSE** — current `SwarmQueryPipeline` has only `run()`; full SSE
  streaming for swarm-debate (vs single `synthesizer.final` event) is a v1.6+ topic.
- **`proposed_answer_preview` on `VerifierCompleteEvent`** — kept off the wire (D-09) to
  avoid PII echo and frame bloat; revisit when production traffic shows observers need it.
- **Verifier-side per-tool retry/timeout config** (Phase 17/20 deferred) — verifier is text-only
  for v1.5, so this is N/A here; revisit when verifier tool-use is reconsidered.
- **UI banner / toast for divergence** — text-only divergence note in answer prose for v1.5
  (D-03); first-class UI surface deferred.
- **Dedicated `AuditAction.AGENT_VERIFIER_*` enum values** — D-11 reuses `AGENT` + metadata
  key; if filter ergonomics become painful, promote to enum in v1.6+.
- **`diverging_peer_indices` on DisagreementEvent** — D-08 omits per-peer tagging; planner can
  add later if UI needs to highlight specific peers.

### To Phase 22 (Per-Module 70% Coverage Lift)
- **`SwarmQueryPipeline` line-coverage lift** — Phase 21 introduces ~120 new lines on the
  swarm class; Phase 22's pipeline.py coverage target absorbs them. Phase 21 ships its own
  unit + integration tests covering the new lines (≥ 70% diff-cover); Phase 22 closes the
  whole-file gap.
- **`Verifier` class coverage** — new file lands at ≥ 70% in Phase 21; Phase 22 hardens
  branch coverage if needed.

</deferred>

---

*Phase: 21-AGENT-05 Multi-Agent Debate / Sub-Agent Verifier*
*Context gathered: 2026-05-10*
