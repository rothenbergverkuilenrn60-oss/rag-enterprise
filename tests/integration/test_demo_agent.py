"""Integration test for `make demo-agent` (Phase 19, AGENT-08, ROADMAP SC3+SC4).

Asserts the in-process demo runner emits the exact 11-event sequence + 4-way
parallel fan-out + max-not-sum latency bound. Also exercises the subprocess
invocation for the Make target.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from typing import Any, ClassVar

import pytest

from services.agent._demo_stubs import (
    DEMO_QUERY,
    DemoStubPlanner,
    build_demo_registry,
    make_fake_retrieve_tool,
)
from services.agent.executor import Executor
from services.agent.tools.base import BaseTool
from services.pipeline import AgentQueryPipeline
from utils.models import (
    AgentEvent,
    ExecutorParallelEvent,
    GenerationRequest,
    SynthesizerFinalEvent,
)

# ── fixture (copy of tests/unit/test_agent_sse.py::patch_pipeline_singletons) ──

@pytest.fixture
def patch_pipeline_singletons(monkeypatch: pytest.MonkeyPatch):
    """Patch all singleton accessors AgentQueryPipeline.__init__ touches.

    Promoted (copied — NOT imported) from tests/unit/test_agent_sse.py
    so this integration suite is self-contained. Returns a callable that
    the test passes the planner + tool classes to.
    """
    def _do(planner: Any, *tool_classes: type[BaseTool]) -> AgentQueryPipeline:
        class _NoMem:
            async def load_context(self, *a: Any, **kw: Any) -> Any:
                class _C:
                    short_term: list[Any] = []
                return _C()

            async def save_turn(self, *a: Any, **kw: Any) -> None:
                return None

        class _NoAudit:
            async def log_query(self, *a: Any, **kw: Any) -> None:
                return None

        class _NoTenant:
            def get_tenant_filter(self, tenant_id: str) -> dict[str, Any]:
                return {}

        class _NoFilter:
            async def extract(self, q: str) -> Any:
                class _E:
                    filters: dict[str, Any] = {}
                    semantic_query: str = q
                return _E()

        registry = build_demo_registry(*tool_classes)

        monkeypatch.setattr("services.pipeline.get_memory_service",   lambda: _NoMem())
        monkeypatch.setattr("services.pipeline.get_audit_service",    lambda: _NoAudit())
        monkeypatch.setattr("services.pipeline.get_tenant_service",   lambda: _NoTenant())
        monkeypatch.setattr("services.pipeline.get_filter_extractor", lambda: _NoFilter())
        monkeypatch.setattr("services.pipeline.get_planner",          lambda: planner)

        monkeypatch.setattr(
            "services.agent.executor.get_tool_registry",
            lambda: registry,
        )
        executor = Executor(
            retriever=object(),
            llm=type("LLM", (), {"provider_name": "openai"})(),
        )
        monkeypatch.setattr("services.pipeline.get_executor", lambda: executor)
        monkeypatch.setattr(
            "services.pipeline.get_tool_registry",
            lambda: registry,
        )

        class _LLM:
            provider_name: ClassVar[str] = "openai"

        monkeypatch.setattr("services.pipeline.get_llm_client", lambda: _LLM())
        monkeypatch.setattr("services.pipeline.get_retriever",  lambda: object())

        return AgentQueryPipeline()

    return _do


# ── helpers ────────────────────────────────────────────────────────────

def _demo_req() -> GenerationRequest:
    return GenerationRequest(
        query=DEMO_QUERY,
        session_id="demo-session",
        tenant_id="demo-tenant",
        user_id="demo-user",
        top_k=5,
    )


# ── Test 1: event-type counts (in-process) ─────────────────────────────

@pytest.mark.asyncio
async def test_demo_runner_emits_expected_event_sequence_in_process(
    patch_pipeline_singletons,
) -> None:
    """11 events: 1 PlannerPlan + 4 ToolSpanStart + 4 ToolSpanEnd + 1 ExecutorParallel + 1 SynthesizerFinal."""
    from services.agent._demo_runner import run_demo  # RED: import must fail

    planner = DemoStubPlanner()
    Tool = make_fake_retrieve_tool("search_knowledge_base", sleep_s=0.5)
    # Wire the same patches the runner will install — but pytest's monkeypatch
    # is the canonical surface here; the runner uses unittest.mock.patch
    # (verified in Test 5/6).
    pipeline = patch_pipeline_singletons(planner, Tool)

    events: list[AgentEvent] = [evt async for evt in pipeline.run_streaming(_demo_req())]
    types = [type(e).__name__ for e in events]

    assert types.count("PlannerPlanEvent")      == 1, types
    assert types.count("ToolSpanStartEvent")    == 4, types
    assert types.count("ToolSpanEndEvent")      == 4, types
    assert types.count("ExecutorParallelEvent") == 1, types
    assert types.count("SynthesizerFinalEvent") == 1, types
    assert len(events) == 11, types

    # Also assert the runner's run_demo() returns a structurally identical
    # sequence (same stub planner + tool factory under the hood).
    events_runner: list[AgentEvent] = await run_demo()
    types_runner = [type(e).__name__ for e in events_runner]
    assert len(events_runner) == 11, types_runner
    assert types_runner.count("PlannerPlanEvent")      == 1
    assert types_runner.count("ToolSpanStartEvent")    == 4
    assert types_runner.count("ToolSpanEndEvent")      == 4
    assert types_runner.count("ExecutorParallelEvent") == 1
    assert types_runner.count("SynthesizerFinalEvent") == 1


# ── Test 2: latency bound (max not sum) ────────────────────────────────

@pytest.mark.asyncio
async def test_demo_runner_latency_bounded_by_max_not_sum() -> None:
    """4 × 0.5s parallel — total elapsed ∈ (450, 700) ms, NOT 4 × 500 = 2000."""
    from services.agent._demo_runner import run_demo  # RED: import must fail

    t0 = time.perf_counter()
    events = await run_demo()
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    assert 450 < elapsed_ms < 700, (
        f"expected 450 < elapsed_ms < 700, got {elapsed_ms} (n_events={len(events)})"
    )


# ── Test 3: ExecutorParallelEvent.fan_out == 4 ─────────────────────────

@pytest.mark.asyncio
async def test_demo_runner_executor_parallel_fan_out_is_four() -> None:
    """The single ExecutorParallelEvent reports fan_out=4 and group_latency_ms<700."""
    from services.agent._demo_runner import run_demo  # RED: import must fail

    events = await run_demo()
    parallel = [e for e in events if isinstance(e, ExecutorParallelEvent)]
    assert len(parallel) == 1, [type(e).__name__ for e in events]
    assert parallel[0].fan_out == 4, parallel[0]
    assert parallel[0].group_latency_ms < 700, parallel[0]


# ── Test 4: terminal SynthesizerFinalEvent has non-empty answer ────────

@pytest.mark.asyncio
async def test_demo_runner_synthesizer_final_answer_non_empty() -> None:
    """The terminal SynthesizerFinalEvent.answer is a non-empty string."""
    from services.agent._demo_runner import run_demo  # RED: import must fail

    events = await run_demo()
    finals = [e for e in events if isinstance(e, SynthesizerFinalEvent)]
    assert len(finals) == 1, [type(e).__name__ for e in events]
    assert isinstance(finals[0].answer, str)
    assert finals[0].answer.strip() != "", finals[0]


# ── Test 5: main() writes SSE frames to stdout ─────────────────────────

def test_demo_runner_main_writes_sse_frames_to_stdout(capsys) -> None:
    """main() prints SSE-formatted lines (event:/data: pairs) for each event."""
    from services.agent._demo_runner import main  # RED: import must fail

    rc = main()
    captured = capsys.readouterr()
    out = captured.out

    assert rc == 0, captured.err
    assert out.count("event: ") >= 11, out
    assert out.count("data: ") >= 11, out
    # All 5 distinct event types are present in the SSE wire stream.
    assert "event: planner.plan"      in out
    assert "event: tool.span.start"   in out
    assert "event: tool.span.end"     in out
    assert "event: executor.parallel" in out
    assert "event: synthesizer.final" in out


# ── Test 6: subprocess invocation exits 0 with synthesizer.final on stdout ──

def test_demo_runner_exit_code_zero_on_success() -> None:
    """`python -m services.agent._demo_runner` exits 0 within 10s.

    Subprocess inherits the parent env (T-19-02-03 — accepted). Captures
    stdout/stderr; no secrets leak — fixture-only stubs, placeholder IDs.
    """
    # Plan 19-01 deviation #1 (Rule 3 adaptation): the project has no conda
    # binary; use sys.executable (the running interpreter) instead.
    if shutil.which(sys.executable) is None:
        pytest.skip("python interpreter unavailable for subprocess invocation")

    env = os.environ.copy()
    env.setdefault("APP_MODEL_DIR", "/tmp")
    env.setdefault("SECRET_KEY", "test-secret-key-for-integration-test-only")

    proc = subprocess.run(
        [sys.executable, "-m", "services.agent._demo_runner"],
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    )
    assert proc.returncode == 0, (
        f"returncode={proc.returncode}\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
    )
    assert "event: synthesizer.final" in proc.stdout, proc.stdout[-2000:]
