"""Phase 23 / MEM-04 — `SwarmQueryPipeline` wire-in test (Plan 23-05 Task 3).

Deviation note (Rule 1 fix): the plan narrative says "SwarmQueryPipeline.run
post-save_turn block (~line 1619–1626)", but on the working tree
`SwarmQueryPipeline.run` (line 1698) is a thin dispatcher that delegates to
``_run_with_state`` (line 1463). The save_turn block at line 1619 actually
lives in ``_run_with_state``. The line-number guide is authoritative; the
wire-in goes into `_run_with_state` (which `run` invokes for N>1) and the
structural test inspects that method's source.

The full SwarmQueryPipeline orchestrates planner, executor, synthesizer,
peer fan-out, optional verifier, etc. Mocking every collaborator to reach
the post-`save_turn` block exceeds the 50-LOC fixture ceiling (Plan 23-05
Task 3 §implementation realism caveat) — so this test uses the structural
``inspect.getsource`` fallback explicitly authorised by the plan. Plan 23-06
(integration) exercises the real run path end-to-end.

The structural check verifies:
  1. `dispatch_extraction(` appears in `SwarmQueryPipeline._run_with_state`.
  2. The A2 kwarg form `user_turn=user_turn, ai_turn=ai_turn` is used.
  3. The call lives AFTER the `save_turn` line (post-save_turn placement).
"""
from __future__ import annotations

import os

os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault(
    "SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c"
)

import inspect


def test_swarm_run_dispatches_extractor():
    """Structural fallback per Plan 05 Task 3 §implementation realism caveat:
    full-mock SwarmQueryPipeline setup exceeds 50 LOC, so verify the
    wire-in via source-text containment on `_run_with_state` (where the
    post-save_turn block actually lives per the working tree). Integration
    test in Plan 06 covers the real run path."""
    from services.pipeline import SwarmQueryPipeline

    src = inspect.getsource(SwarmQueryPipeline._run_with_state)
    assert "dispatch_extraction(" in src, (
        "SwarmQueryPipeline._run_with_state is missing dispatch_extraction wire-in."
    )
    assert "user_turn=user_turn, ai_turn=ai_turn" in src, (
        "SwarmQueryPipeline._run_with_state dispatch_extraction call must use A2 kwarg form."
    )

    # Placement check: dispatch_extraction MUST appear AFTER save_turn.
    save_idx = src.find("save_turn(")
    dispatch_idx = src.find("dispatch_extraction(")
    assert save_idx != -1 and dispatch_idx != -1
    assert dispatch_idx > save_idx, (
        "dispatch_extraction must be called AFTER save_turn (post-save_turn block)."
    )
