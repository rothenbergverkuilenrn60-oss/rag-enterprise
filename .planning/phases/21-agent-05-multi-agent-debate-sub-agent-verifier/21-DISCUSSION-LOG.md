# Phase 21: AGENT-05 Multi-Agent Debate / Sub-Agent Verifier - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-10
**Phase:** 21-agent-05-multi-agent-debate-sub-agent-verifier
**Areas discussed:** VerifierVerdict schema fields, Synthesizer divergence composition, Verifier LLM model choice, Verifier failure isolation, DisagreementEvent payload shape, debate=True without swarm_mode, Forced-disagree audit signal

---

## VerifierVerdict schema fields

### Q1: VerifierVerdict shape — which fields beyond `verdict` and `evidence_chunk_ids`?

| Option | Description | Selected |
|--------|-------------|----------|
| verdict + evidence_chunk_ids + reasoning + proposed_answer | Full set. Verifier emits its own evidence-supported answer text. Synthesizer reads proposed_answer on disagree — no second LLM call. Lower latency, single source of truth on disagreement. | ✓ |
| verdict + evidence_chunk_ids + reasoning (no proposed_answer) | Verifier only judges. Synthesizer regenerates final answer from peers + verdict + reasoning. Adds one more LLM hop on disagree (extra latency). | |
| verdict + evidence_chunk_ids only (minimal) | Pure judge. Synthesizer picks 'best' peer based on verdict + cited chunks. No reasoning surfaced. Simplest but opaque on disagreement. | |
| verdict + evidence_chunk_ids + reasoning + chosen_peer_index | Verifier picks WHICH peer was correct (or -1 for none). Synthesizer uses that peer's answer verbatim. No new generated text from verifier. | |

**User's choice:** verdict + evidence_chunk_ids + reasoning + proposed_answer
**Notes:** Locked as D-01. Frozen Pydantic V2 model in `utils/models.py` per Phase 16/17 D-01 placement convention. `latency_ms` added.

### Q2: `proposed_answer` field requirement — always populated or disagree-only?

| Option | Description | Selected |
|--------|-------------|----------|
| Always populated | Even on agree, verifier states the consensus answer. Simpler schema (str, not str \| None). Synthesizer always has a fallback. Forces verifier to commit — catches lazy 'agree' verdicts. | ✓ |
| Required only on disagree (Optional[str]) | On agree, peers' consensus stands; verifier saves tokens. Smaller verifier prompt. Synthesizer must branch on verdict to know whether to read it. | |
| Always populated + max_length=2000 | Same as #1 but bounds the field. Matches GenerationRequest.query max_length=2000 ceiling. Defends against runaway verifier output. | |

**User's choice:** Always populated
**Notes:** Locked as D-02. No length ceiling at the model level; system prompt enforces brevity.

---

## Synthesizer divergence composition

### Q3: On disagreement, what does the final answer text look like?

| Option | Description | Selected |
|--------|-------------|----------|
| Verifier's proposed_answer + divergence note | Use verifier's evidence-supported answer as primary; append short note flagging peer disagreement. Compact, decisive, evidence-led. | ✓ |
| Verifier proposed_answer + per-peer summary | Show verifier answer first, then collapsible 'sub-agent answers' block listing each peer's answer (verbose; UI-style). | |
| All peer answers + verifier reconciliation | Show all N peer answers as bullets, then verifier's resolution. Maximum transparency, longest output. | |
| Verifier answer only (silent on divergence) | Just emit verifier.proposed_answer; rely on VerifierDisagreementEvent for observers. Cleanest text, divergence visible only via SSE. | |

**User's choice:** Verifier's proposed_answer + divergence note
**Notes:** Locked as D-03. Chinese banner template is the contract. Final answer text language matches user query (P-11 carry-forward from Phase 20 deferred).

### Q4: Where does the disagreement composition logic live?

| Option | Description | Selected |
|--------|-------------|----------|
| Extend SwarmQueryPipeline._synthesize with debate branch | Pass verifier_verdict as optional kw to existing _synthesize; if present and disagree, format using verifier.proposed_answer + divergence note. Minimal new surface. | ✓ |
| Add new _synthesize_with_verdict method | Keep _synthesize untouched. New method called from run() only when debate=True. Clearer separation but duplicate prefix/suffix logic. | |
| Extract Synthesizer class to services/agent/synthesizer.py | Refactor: pull synthesis logic into a new class behind frozen contracts. Larger blast radius; touches v1.3 paths. Better long-term, risks SC5 'no production change when debate=False'. | |

**User's choice:** Extend SwarmQueryPipeline._synthesize with debate branch
**Notes:** Locked as D-04. SC5 byte-identical-when-debate=False holds. NO new Synthesizer class; deferred to v1.6+.

---

## Verifier LLM model choice

### Q5: Which LLM does the verifier call?

| Option | Description | Selected |
|--------|-------------|----------|
| Configurable via settings (default = same as peer LLM) | New Settings.verifier_model: str \| None = None. None → reuse peer model/provider. Cost-control knob without forcing a choice now. Matches v1.0+ env-driven model selection. | ✓ |
| Same model as peers, no override | Verifier uses the same provider/model as swarm peers. Zero new config. Simplest. Cost = N+1 same-tier calls per debate query. | |
| Hardcoded cheaper model (e.g., haiku-4-5) | Verifier always uses a smaller/cheaper model regardless of peer model. Lower cost but couples to specific provider/model. | |
| Configurable + force smaller default (e.g., haiku-4-5) | Default to a cheap model; allow override. Optimizes default cost. Risks quality regression if cheap model misjudges. | |

**User's choice:** Configurable via settings (default = same as peer LLM)
**Notes:** Locked as D-05. `Settings.verifier_model` and `Settings.verifier_provider` both default to None; resolution through existing `get_llm_client()` factory.

---

## Verifier failure isolation

### Q6: Verifier LLM call raises — what happens?

| Option | Description | Selected |
|--------|-------------|----------|
| Degrade: fall through to non-debate synth, emit DisagreementEvent with error reason | User still gets an answer (peers' consensus). VerifierDisagreementEvent emitted with reason='verifier_failed' + error_type. Audit row records failure. Latency stays bounded. | ✓ |
| Raise — fail the whole request | Strict mode: verifier failure = request failure. User sees 5xx. Forces ops to notice. Risks unavailability when verifier provider hiccups. | |
| Degrade silently (no DisagreementEvent on error) | Fall through to non-debate synth. No error event surfaced. Simplest but observers can't tell debate degraded vs ran cleanly. | |
| Tenacity retry then degrade | Apply v1.0+ tenacity pattern (3 attempts, exp backoff). On final failure, degrade like option 1. Adds resilience to transient errors but extends latency on bad provider. | |

**User's choice:** Degrade: fall through to non-debate synth, emit DisagreementEvent with error reason
**Notes:** Locked as D-06. `BaseException` (CF-09 carry-forward); audit row uses metadata key `verifier_failed=true` (no enum migration).

### Q7: Tenacity-wrap the verifier call at the Verifier class level?

| Option | Description | Selected |
|--------|-------------|----------|
| No additional retry — trust call_agentic_turn | BaseLLMClient already has retry built into provider clients. Adding another layer compounds latency on bad days. Verifier failure path (D4.1) handles whatever falls out. | ✓ |
| Tenacity 3-attempt exp backoff at Verifier level | Mirror v1.0+ external-call pattern explicitly on the verifier seam. Belt-and-suspenders; risks 30s+ latency when provider is degraded. | |
| Single retry on transient classes only (timeout, 5xx) | Tight scope: retry once for timeout/5xx, raise rest. Catches one-off blips, bounded latency cost. | |

**User's choice:** No additional retry — trust call_agentic_turn
**Notes:** Locked as D-07.

---

## DisagreementEvent payload shape

### Q8: VerifierDisagreementEvent wire payload — which fields?

| Option | Description | Selected |
|--------|-------------|----------|
| reason + summary + evidence_chunk_ids + peer_count + error_type | Full observability. Explains WHY (reason), WHAT (summary text ≤200 chars), EVIDENCE (chunk ids), CONTEXT (peer count), ERRORS (optional). Mirrors tool.span.error pattern. | ✓ |
| Minimal: reason + summary only | Smallest wire surface. Future fields require schema bump. Easier to lock now. | |
| reason + summary + evidence_chunk_ids + diverging_peer_indices | Identifies WHICH peers disagreed (by index in fan-out). UI can highlight specific peers. More verbose, requires verifier prompt to reason about peer indices. | |

**User's choice:** reason + summary + evidence_chunk_ids + peer_count + error_type
**Notes:** Locked as D-08. Three `reason` Literal values: `peers_diverge`, `forced_no_evidence`, `verifier_failed`. Treated as a closed set for v1.5.

### Q9: VerifierStartEvent + VerifierCompleteEvent shapes — lock to default or refine?

| Option | Description | Selected |
|--------|-------------|----------|
| Default shapes per pattern | Mirrors tool.span.start/end pattern. Concise, observable, no extra prompt-engineering cost. | ✓ |
| Minimal: only verdict + latency_ms on complete; no payload on start | Smallest possible. Loses model + peer_count observability. | |
| Add proposed_answer_preview to complete (≤ 200 chars) | Surface what the verifier wrote on the wire. Bigger frames; possible PII echo. | |

**User's choice:** Default shapes per pattern
**Notes:** Locked as D-09. No `proposed_answer_preview` (PII / frame-size).

---

## debate=True without swarm_mode

### Q10: Request with `debate=True` but `swarm_mode=False` — what happens?

| Option | Description | Selected |
|--------|-------------|----------|
| 422 validation error at Pydantic level | Add field_validator on GenerationRequest: debate=True requires swarm_mode=True. Fail fast at request boundary, clearest API contract. | ✓ |
| Silently ignore debate when swarm_mode=False | Don't run verifier; treat as agent-only path. No error. Risk: client thinks debate ran. | |
| Auto-enable swarm_mode when debate=True | If debate=True and swarm_mode=False, server flips swarm_mode to True. Convenient but surprising side-effect. | |

**User's choice:** 422 validation error at Pydantic level
**Notes:** Locked as D-10. `model_validator(mode="after")` on `GenerationRequest`.

---

## Forced-disagree audit signal

### Q11: Forced-disagree (SC1 override) audit observability — where does it surface?

| Option | Description | Selected |
|--------|-------------|----------|
| DisagreementEvent.reason='forced_no_evidence' + audit row marks override | Two-channel: SSE event for live observers, audit log row records the override fact (reused AGENT audit action + extra metadata key forced_disagree=true). Aligns with v1.3 audit + v1.4 SSE patterns. | ✓ |
| DisagreementEvent.reason only — no extra audit field | SSE event is the only signal. Saves audit schema change. Loses post-hoc DB query ability. | |
| Add new AuditAction.AGENT_VERIFIER_FORCED_OVERRIDE | Dedicated audit action enum. Clearest filtering. Larger surface (enum migration + tests). | |

**User's choice:** DisagreementEvent.reason='forced_no_evidence' + audit row marks override
**Notes:** Locked as D-11. Reuses existing `AGENT` action; metadata key `forced_disagree=true`.

---

## Claude's Discretion

Areas left to Claude / planner:
- Verifier system prompt exact wording (forbid-inventing-facts intent + JSON-mode + language matching are locked).
- `evidence_chunk_ids` defensive filtering (optional drop of IDs not in supplied set; SC1 forced-disagree is the minimum bar).
- `reasoning` field length cap (system-prompt level only, no model ceiling).
- Verifier hop placement in any future `run_streaming` for swarm (not in scope this phase).
- Test layout under existing v1.3 conventions (`tests/unit/test_verifier.py`, `tests/integration/test_swarm_debate_e2e.py`).
- `Settings.verifier_provider` validation seam (mirror existing v1.0+ provider key check).
- Audit metadata JSON key namespacing (suggestion: nest under `agent_05`).

## Deferred Ideas

To v1.6+:
- Iterative peer-debate (N rounds mutual critique).
- Always-on debate trigger.
- `Synthesizer` class extraction.
- Swarm `run_streaming` for full SSE.
- `proposed_answer_preview` on `VerifierCompleteEvent`.
- Verifier-side per-tool retry/timeout config.
- UI banner / toast for divergence.
- Dedicated `AuditAction.AGENT_VERIFIER_*` enum values.
- `diverging_peer_indices` on DisagreementEvent.

To Phase 22 (Per-Module 70% Coverage Lift):
- `SwarmQueryPipeline` line-coverage lift (Phase 21 ships ≥ 70% diff-cover on the new lines; Phase 22 closes whole-file gap).
- `Verifier` class branch-coverage hardening if needed.
