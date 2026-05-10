"""TDD RED tests for Phase 21 (AGENT-05) — VerifierVerdict + 3 events + GenerationRequest.debate.

Covers CONTEXT decisions D-01 (VerifierVerdict shape), D-08 (VerifierDisagreementEvent reasons),
D-09 (verifier.start / verifier.complete shapes, ClassVar discriminators), D-10 (debate cross-field).

These tests MUST fail before Plan 21-02 GREEN lands (ImportError on the four new symbols and
AttributeError on GenerationRequest.debate). After GREEN, all 13 cases pass without test edits.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from utils.models import (
    AgentEvent,
    GenerationRequest,
    VerifierCompleteEvent,
    VerifierDisagreementEvent,
    VerifierStartEvent,
    VerifierVerdict,
)


# ─── Phase 21: VerifierVerdict + 3 events + GenerationRequest.debate ─────


# ══════════════════════════════════════════════════════════════════════════
# Group A — VerifierVerdict (D-01) — 4 cases
# ══════════════════════════════════════════════════════════════════════════

def test_verifier_verdict_construct_happy() -> None:
    """D-01: all five fields populate via model_validate."""
    v = VerifierVerdict.model_validate({
        "verdict": "agree",
        "evidence_chunk_ids": ["c1", "c2"],
        "reasoning": "r",
        "proposed_answer": "a",
        "latency_ms": 100,
    })
    assert v.verdict == "agree"
    assert v.evidence_chunk_ids == ["c1", "c2"]
    assert v.reasoning == "r"
    assert v.proposed_answer == "a"
    assert v.latency_ms == 100


def test_verifier_verdict_literal_violation() -> None:
    """D-01: verdict Literal is closed — 'maybe' must raise."""
    with pytest.raises(ValidationError) as exc_info:
        VerifierVerdict.model_validate({
            "verdict": "maybe",
            "evidence_chunk_ids": [],
            "reasoning": "r",
            "proposed_answer": "a",
            "latency_ms": 0,
        })
    assert "verdict" in str(exc_info.value)


def test_verifier_verdict_frozen() -> None:
    """frozen=True surfaces mutation as ValidationError (Pydantic V2 contract)."""
    v = VerifierVerdict(
        verdict="agree",
        evidence_chunk_ids=["c1"],
        reasoning="r",
        proposed_answer="a",
        latency_ms=10,
    )
    with pytest.raises(ValidationError):
        v.verdict = "disagree"  # type: ignore[misc]


def test_verifier_verdict_model_copy_for_forced_disagree() -> None:
    """CF-04 forced-disagree path uses model_copy(update=...) — must yield NEW frozen instance."""
    original = VerifierVerdict(
        verdict="agree",
        evidence_chunk_ids=["c1"],
        reasoning="r",
        proposed_answer="a",
        latency_ms=10,
    )
    forced = original.model_copy(update={"verdict": "disagree"})
    assert forced.verdict == "disagree"
    assert original.verdict == "agree"  # original unmodified
    assert forced is not original


# ══════════════════════════════════════════════════════════════════════════
# Group B — 3 AgentEvent subclasses (D-08, D-09) — 5 cases
# ══════════════════════════════════════════════════════════════════════════

def test_verifier_start_event_shape() -> None:
    """D-09: VerifierStartEvent has peer_count + model fields; event_type ClassVar='verifier.start'."""
    evt = VerifierStartEvent(
        trace_id="t1",
        seq=0,
        ts_ms=1,
        peer_count=3,
        model="gpt-4o",
    )
    assert evt.event_type == "verifier.start"
    assert isinstance(evt, AgentEvent)
    assert evt.peer_count == 3
    assert evt.model == "gpt-4o"


def test_verifier_start_event_classvar_excluded_from_json() -> None:
    """Pydantic V2: ClassVar fields are excluded from model_dump_json output."""
    evt = VerifierStartEvent(
        trace_id="t1",
        seq=0,
        ts_ms=1,
        peer_count=3,
        model="gpt-4o",
    )
    parsed = json.loads(evt.model_dump_json())
    assert "event_type" not in parsed
    assert parsed["peer_count"] == 3
    assert parsed["model"] == "gpt-4o"


def test_verifier_complete_event_round_trip() -> None:
    """D-09: VerifierCompleteEvent shape + JSON round-trip; event_type ClassVar='verifier.complete'."""
    evt = VerifierCompleteEvent(
        trace_id="t1",
        seq=1,
        ts_ms=2,
        verdict="agree",
        evidence_chunk_count=2,
        latency_ms=150,
    )
    blob = evt.model_dump_json()
    again = VerifierCompleteEvent.model_validate_json(blob)
    assert again.trace_id == "t1"
    assert again.seq == 1
    assert again.ts_ms == 2
    assert again.verdict == "agree"
    assert again.evidence_chunk_count == 2
    assert again.latency_ms == 150
    assert evt.event_type == "verifier.complete"


def test_verifier_disagreement_event_default_error_type_none() -> None:
    """D-08: error_type defaults to None; populated only when reason='verifier_failed'."""
    evt = VerifierDisagreementEvent(
        trace_id="t1",
        seq=2,
        ts_ms=3,
        reason="peers_diverge",
        summary="x",
        evidence_chunk_ids=["c1"],
        peer_count=3,
    )
    assert evt.error_type is None
    assert evt.event_type == "verifier.disagreement"


@pytest.mark.parametrize("reason", ["peers_diverge", "forced_no_evidence", "verifier_failed"])
def test_verifier_disagreement_event_reason_literal(reason: str) -> None:
    """D-08: reason Literal is closed; only the three specified values are valid."""
    evt = VerifierDisagreementEvent(
        trace_id="t1",
        seq=2,
        ts_ms=3,
        reason=reason,  # type: ignore[arg-type]
        summary="x",
        evidence_chunk_ids=["c1"],
        peer_count=3,
    )
    assert evt.reason == reason

    with pytest.raises(ValidationError):
        VerifierDisagreementEvent(
            trace_id="t1",
            seq=2,
            ts_ms=3,
            reason="invalid_reason",  # type: ignore[arg-type]
            summary="x",
            evidence_chunk_ids=["c1"],
            peer_count=3,
        )


# ══════════════════════════════════════════════════════════════════════════
# Group C — GenerationRequest.debate field + D-10 cross-field validator — 4 cases
# ══════════════════════════════════════════════════════════════════════════

def test_debate_field_default_false() -> None:
    """D-10: debate field exists, defaults to False."""
    req = GenerationRequest(query="q")
    assert req.debate is False


def test_debate_requires_swarm_mode() -> None:
    """D-10: debate=True without swarm_mode=True raises (ValidationError wraps the ValueError)."""
    with pytest.raises(ValidationError) as exc_info:
        GenerationRequest(query="q", debate=True, swarm_mode=False)
    assert "debate=True requires swarm_mode=True" in str(exc_info.value)


def test_debate_with_swarm_mode_constructs() -> None:
    """D-10: debate=True with swarm_mode=True is the valid combination."""
    req = GenerationRequest(query="q", debate=True, swarm_mode=True)
    assert req.debate is True
    assert req.swarm_mode is True


def test_debate_false_swarm_false_constructs() -> None:
    """D-10: default case (both False) is unchanged from pre-Phase-21 behavior."""
    req = GenerationRequest(query="q", debate=False, swarm_mode=False)
    assert req.debate is False
    assert req.swarm_mode is False
