---
phase: 21-agent-05-multi-agent-debate-sub-agent-verifier
plan: 02
subsystem: utils-models
status: complete
tasks_completed: 2
tags: [pydantic-v2, frozen, agent-event, generation-request, model-validator, tdd, agent-05, agent-14, agent-15]
requires:
  - "Settings.verifier_model + Settings.verifier_provider (Plan 21-01) — not consumed in this plan, kept here for handoff to 21-03/21-05"
provides:
  - "VerifierVerdict (frozen, 5 fields, Literal['agree','disagree']) — utils/models.py:654-669"
  - "VerifierStartEvent (AgentEvent subclass, peer_count + model) — utils/models.py:672-678"
  - "VerifierCompleteEvent (AgentEvent subclass, verdict + counts + latency) — utils/models.py:681-692"
  - "VerifierDisagreementEvent (AgentEvent subclass, 3-value reason Literal, error_type|None) — utils/models.py:695-709"
  - "GenerationRequest.debate: bool = False — utils/models.py:216"
  - "_check_debate_requires_swarm @model_validator(mode='after') — utils/models.py:227-233"
affects:
  - "Plan 21-03 — services/agent/verifier.py imports VerifierVerdict as Verifier.verify() return type; CF-04 forced-disagree uses .model_copy(update={'verdict':'disagree'})"
  - "Plan 21-04 — services/agent/_synthesize.py imports VerifierVerdict; _format_disagree reads verdict.proposed_answer + verdict.evidence_chunk_ids"
  - "Plan 21-05 — services/pipeline.py SwarmQueryPipeline.run() emits the 3 new events via existing emit_sse_frame; gates verifier hop on req.debate (now a typed field)"
  - "Plan 21-06 — docs reference verifier.start / verifier.complete / verifier.disagreement event_type strings verbatim"
tech-stack:
  added: []
  patterns:
    - "Pydantic V2 frozen models with model_config = ConfigDict(frozen=True) — match existing AgentEvent subclass convention (each subclass redeclares the config)"
    - "ClassVar[str] discriminator on AgentEvent subclasses — auto-excluded from model_dump_json() per Pydantic V2 default"
    - "model_validator(mode='after') for cross-field constraints — mirrors config/settings.py::_validate_security pattern"
key-files:
  modified:
    - path: utils/models.py
      lines: "12, 216, 227-233, 645-709"
      role: "+model_validator import; +debate field on GenerationRequest; +D-10 cross-field validator; +4 new model classes after SynthesizerFinalEvent"
  created:
    - path: tests/unit/test_phase21_models.py
      lines: "1-214"
      role: "13 RED test functions (15 collected items including 3 parametrize cases) — Group A VerifierVerdict (4), Group B 3 events (5), Group C debate field/validator (4)"
decisions:
  - "Used existing AgentEvent subclass convention (each subclass redeclares model_config = ConfigDict(frozen=True)) — does NOT rely on inheritance per CONTEXT plan constraint"
  - "VerifierCompleteEvent has NO proposed_answer_preview field per D-09 (PII echo concern; full text only via SynthesizerFinalEvent)"
  - "VerifierDisagreementEvent.error_type: str | None = None — populated only when reason='verifier_failed' per D-06; default None mandatory"
  - "_check_debate_requires_swarm raises ValueError (not ValidationError directly) — Pydantic V2 wraps it into ValidationError → FastAPI returns 422 to client"
  - "Test file path deviation: plan literal `tests/unit/test_models.py` does not exist; created `tests/unit/test_phase21_models.py` to match repo's granular per-feature test convention (test_agent_event_models.py, test_agentic_turn_models.py)"
metrics:
  duration_minutes: ~10
  completed_date: "2026-05-10"
  files_touched: 2
  lines_added: 292   # 78 utils/models.py + 214 test file
  tests_added: 13    # 15 collected (3 parametrize cases on reason Literal)
---

# Phase 21 Plan 02: VerifierVerdict + 3 Events + GenerationRequest.debate Summary

**One-liner:** Four Pydantic V2 wire-surface artifacts (`VerifierVerdict` frozen verdict + 3 frozen `AgentEvent` subclasses) plus the `GenerationRequest.debate: bool = False` field with the D-10 cross-field `model_validator` — landed via clean RED→GREEN TDD with 13 tests (15 collected) covering CONTEXT D-01 / D-08 / D-09 / D-10.

## Tasks Completed

### Task 1 — RED: 13 failing tests (commit `a2cfdcf`)

Created `tests/unit/test_phase21_models.py` (214 lines, single `# ─── Phase 21:` section header) with 13 test functions in three groups:

**Group A — VerifierVerdict (D-01) — 4 cases:**
- `test_verifier_verdict_construct_happy` — `model_validate({...all 5 fields...})` round-trip
- `test_verifier_verdict_literal_violation` — `verdict="maybe"` raises `ValidationError`
- `test_verifier_verdict_frozen` — assignment raises `ValidationError` (Pydantic V2 frozen contract, NOT `dataclasses.FrozenInstanceError`)
- `test_verifier_verdict_model_copy_for_forced_disagree` — `model_copy(update={"verdict":"disagree"})` returns NEW instance, original unchanged (CF-04 path)

**Group B — 3 AgentEvent subclasses (D-08, D-09) — 5 cases:**
- `test_verifier_start_event_shape` — `event_type == "verifier.start"`, `peer_count`/`model` populated, `isinstance(evt, AgentEvent)`
- `test_verifier_start_event_classvar_excluded_from_json` — `model_dump_json()` does NOT contain `event_type` key (Pydantic V2 ClassVar default exclusion)
- `test_verifier_complete_event_round_trip` — JSON round-trip preserves verdict + counts + latency; `event_type == "verifier.complete"`
- `test_verifier_disagreement_event_default_error_type_none` — `error_type` defaults to `None`
- `test_verifier_disagreement_event_reason_literal` — parametrized over the 3 valid reasons (`peers_diverge`, `forced_no_evidence`, `verifier_failed`); also asserts `"invalid_reason"` raises

**Group C — GenerationRequest.debate field + D-10 cross-field validator — 4 cases:**
- `test_debate_field_default_false` — `GenerationRequest(query="q").debate is False`
- `test_debate_requires_swarm_mode` — `debate=True, swarm_mode=False` raises `ValidationError`; message includes `"debate=True requires swarm_mode=True"`
- `test_debate_with_swarm_mode_constructs` — `debate=True, swarm_mode=True` constructs successfully
- `test_debate_false_swarm_false_constructs` — default case unchanged (regression guard)

**RED gate confirmed:** `pytest tests/unit/test_phase21_models.py -x` exited with status 2 (collection ImportError on `VerifierCompleteEvent` — none of the four model symbols existed yet in `utils/models.py`).

### Task 2 — GREEN: Implementation (commit `2c12fb9`)

Three edits to `utils/models.py`:

**Edit 1 — Add `model_validator` to existing pydantic import (line 12):**
```python
# Before:
from pydantic import BaseModel, ConfigDict, Field, field_validator
# After:
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
```

**Edit 2 — Add `debate` field + cross-field validator to `GenerationRequest` (lines 216, 227-233):**

Inserted `debate: bool = False` directly after `swarm_mode: bool = False`. Appended the `_check_debate_requires_swarm` `model_validator` AFTER the existing `strip_query` `field_validator`:

```python
debate:       bool                          = False   # AGENT-14 — opt-in verifier hop after peer fan-out (CF-02)

@model_validator(mode="after")
def _check_debate_requires_swarm(self) -> "GenerationRequest":
    """D-10: debate=True requires swarm_mode=True (verifier runs after peer fan-out)."""
    if self.debate and not self.swarm_mode:
        raise ValueError(
            "debate=True requires swarm_mode=True (verifier runs after peer fan-out)"
        )
    return self
```

**Edit 3 — Append 4 new model classes after `SynthesizerFinalEvent` (lines 645-709):**

Section divider `# Phase 21 — AGENT-05 Multi-Agent Debate / Sub-Agent Verifier` followed by:
- `VerifierVerdict` (lines 654-669) — frozen, 5 fields per D-01
- `VerifierStartEvent` (lines 672-678) — `event_type: ClassVar[str] = "verifier.start"`, `peer_count: int`, `model: str`
- `VerifierCompleteEvent` (lines 681-692) — `event_type = "verifier.complete"`, `verdict + evidence_chunk_count + latency_ms`. NO `proposed_answer_preview` per D-09.
- `VerifierDisagreementEvent` (lines 695-709) — `event_type = "verifier.disagreement"`, `reason: Literal[...3 values...]`, `summary + evidence_chunk_ids + peer_count`, `error_type: str | None = None`

**GREEN gate confirmed:**
- `pytest tests/unit/test_phase21_models.py -x -v` → 15 passed (13 unique tests + 3 parametrize cases on the reason Literal) in 0.05s
- 40-test regression on Phase 21 + AgentEvent + AgenticTurn → all pass
- 13-test regression on `GenerationRequest` consumers (query_pipeline, agent_pipeline) → all pass

## Verification

```bash
$ uv run python -m pytest tests/unit/test_phase21_models.py -v
============================== 15 passed in 0.05s ==============================

$ uv run python -m pytest tests/unit/test_agent_event_models.py tests/unit/test_agentic_turn_models.py
======================== 25 passed, 2 warnings in 0.07s ========================

$ uv run ruff check utils/models.py
All checks passed!

$ uv run mypy --strict utils/models.py
utils/models.py:92: error: Missing type parameters for generic type "dict"  [type-arg]
Found 1 error in 1 file (checked 1 source file)
```

The single mypy error is **pre-existing baseline** (`tables: list[dict]` at line 92 on `ExtractedContent`, untouched by Phase 21). Verified by stashing the changes and re-running mypy — same error reproduces. Acceptance criterion "zero NEW mypy errors vs baseline" satisfied.

## Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| `pytest tests/unit/test_phase21_models.py -k "verifier or debate" -x` exits 0 | PASS (15/15) |
| Pre-existing tests in `test_agent_event_models.py` unchanged | PASS (16/16) |
| `grep -c "^class VerifierVerdict" utils/models.py` returns 1 | PASS |
| `grep -c "^class VerifierStartEvent" utils/models.py` returns 1 | PASS |
| `grep -c "^class VerifierCompleteEvent" utils/models.py` returns 1 | PASS |
| `grep -c "^class VerifierDisagreementEvent" utils/models.py` returns 1 | PASS |
| `grep -c "debate:.*bool.*= False" utils/models.py` returns 1 | PASS |
| `grep -c "_check_debate_requires_swarm" utils/models.py` returns 1 | PASS |
| `grep -c "model_validator" utils/models.py` returns ≥ 1 | PASS (2: import + decorator) |
| Imports succeed: `VerifierVerdict, VerifierStartEvent, VerifierCompleteEvent, VerifierDisagreementEvent` | PASS |
| `GenerationRequest(query='q', debate=True, swarm_mode=True).debate` is `True` | PASS |
| `GenerationRequest(query='q', debate=True, swarm_mode=False)` raises with D-10 message | PASS |
| `mypy --strict utils/models.py` shows zero NEW errors vs baseline | PASS |
| `ruff check utils/models.py` clean | PASS |

## Deviations from Plan

### Test File Path

**[Rule 3 — Blocking issue]** Plan literal target `tests/unit/test_models.py` does not exist in this repo.

- **Found during:** Task 1 RED setup (`ls tests/unit/test_models.py` returned no such file)
- **Issue:** Plan acceptance criteria reference a file that has never existed in the repo; Phase 18 plan 18-01 used `tests/unit/test_agent_event_models.py` instead, and `tests/unit/test_agentic_turn_models.py` follows the same per-feature granular convention
- **Fix:** Created `tests/unit/test_phase21_models.py` (214 lines, all 13 cases) — matches repo convention, isolates Phase 21 cases for grep-ability, satisfies all acceptance criteria semantics (only the literal grep paths in the plan need mental substitution)
- **Files modified:** `tests/unit/test_phase21_models.py` (new)
- **Commit:** `a2cfdcf`
- **Impact on downstream plans:** None — the test file exists, all 13 cases pass, models are importable; Plan 21-05's verification grep on `test_verifier_*` / `test_debate_*` patterns will hit `test_phase21_models.py` identically.

No other deviations. Auto-fix Rules 1, 2, 4 not triggered.

## Hand-off Notes

**To Plan 21-03 (Verifier sub-agent — `services/agent/verifier.py`):**
```python
from utils.models import RetrievedChunk, VerifierVerdict
# Verifier.verify(query, candidate_answer, peer_chunks) -> VerifierVerdict
# CF-04 forced-disagree path:
#   verdict.model_copy(update={"verdict": "disagree", "reasoning": "no shared evidence"})
# evidence_chunk_ids must be a strict subset of [c.chunk_id for c in peer_chunks].
```

**To Plan 21-04 (`_synthesize` — `services/agent/_synthesize.py`):**
```python
from utils.models import VerifierVerdict
# _synthesize(..., verifier_verdict: VerifierVerdict | None = None) -> str
# When verdict.verdict == "disagree":
#   _format_disagree(verdict.proposed_answer, verdict.evidence_chunk_ids, ...)
```

**To Plan 21-05 (`SwarmQueryPipeline.run` debate hop + SSE — `services/pipeline.py`):**
```python
from utils.models import (
    AgentEvent,
    VerifierStartEvent,
    VerifierCompleteEvent,
    VerifierDisagreementEvent,
    VerifierVerdict,
)
# Gate: `if req.debate:` (the new GenerationRequest field)
# Emit:
#   yield VerifierStartEvent(trace_id=..., seq=..., ts_ms=..., peer_count=N, model=resolved_model)
#   yield VerifierCompleteEvent(trace_id=..., seq=..., ts_ms=..., verdict=v.verdict, evidence_chunk_count=len(v.evidence_chunk_ids), latency_ms=v.latency_ms)
# OR (on disagree paths):
#   yield VerifierDisagreementEvent(trace_id=..., seq=..., ts_ms=..., reason="peers_diverge"|"forced_no_evidence"|"verifier_failed", summary=str(...)[:200], evidence_chunk_ids=[...], peer_count=N, error_type=None|"RuntimeError")
# emit_sse_frame at services/agent/_demo_runner.py:89-94 already serializes any AgentEvent — zero serializer change required.
```

**To Plan 21-06 (docs):**
- `event_type` strings on the wire: `verifier.start`, `verifier.complete`, `verifier.disagreement` (verbatim, dot-separated, lowercase — matches Phase 18 convention)
- D-10 client-facing semantics: 422 with body `{"detail": [..., "msg": "...debate=True requires swarm_mode=True..."]}` when client sets `debate=True` without `swarm_mode=True`

## Self-Check: PASSED

**Files created:**
- `tests/unit/test_phase21_models.py` — exists (214 lines)

**Files modified:**
- `utils/models.py` — debate field at 216, validator at 227-233, 4 new classes 645-709

**Commits exist:**
- `a2cfdcf` (RED) — `git log --oneline | grep a2cfdcf` confirms
- `2c12fb9` (GREEN) — `git log --oneline | grep 2c12fb9` confirms

**Verification commands all green:** 15/15 Phase 21 tests pass; 25/25 sibling AgentEvent + AgenticTurn tests pass; 13/13 GenerationRequest consumer regression passes; ruff clean; mypy zero NEW errors.

## TDD Gate Compliance

- RED gate: commit `a2cfdcf` is `test(21-02): RED — failing tests for VerifierVerdict + 3 events + GenerationRequest.debate (D-01/D-08/D-09/D-10)` — confirmed test-first with non-zero exit on first run.
- GREEN gate: commit `2c12fb9` is `feat(21-02): GREEN — VerifierVerdict + 3 events + GenerationRequest.debate (D-01/D-08/D-09/D-10)` — confirmed all 15 tests pass after implementation.
- REFACTOR gate: skipped (plan explicitly notes "REFACTOR is a no-op (tight scope)" — 78 LOC implementation needs no cleanup).
