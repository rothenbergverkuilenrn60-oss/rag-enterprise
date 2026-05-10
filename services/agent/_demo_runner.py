"""CLI runner for `make demo-agent` (Phase 19, AGENT-08).

Wires the Phase 19 demo stubs (`_demo_stubs.py`) into
``AgentQueryPipeline.run_streaming`` via runtime monkey-patching of singleton
accessors at consumer paths (v1.3 D-16). Iterates the event stream and prints
each event as an SSE frame (``event: <type>\\ndata: <json>\\n\\n``) to stdout.
Exit 0 on success; non-zero on shape mismatch (CONTEXT.md D-06).
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import ExitStack
from typing import Any, ClassVar
from unittest.mock import patch

from services.agent._demo_stubs import (
    DEMO_QUERY,
    DemoStubPlanner,
    build_demo_registry,
    make_fake_retrieve_tool,
)
from services.agent.executor import Executor
from services.pipeline import AgentQueryPipeline
from utils.models import AgentEvent, GenerationRequest

# No-op singleton stubs (runtime equiv. of test_agent_sse.py::patch_pipeline_singletons).

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

class _LLM:
    provider_name: ClassVar[str] = "openai"


async def run_demo() -> list[AgentEvent]:
    """Run the demo pipeline in-process and return the full event sequence."""
    planner = DemoStubPlanner()
    Tool = make_fake_retrieve_tool("search_knowledge_base", sleep_s=0.5)
    registry = build_demo_registry(Tool)
    executor = Executor(retriever=object(), llm=_LLM())

    with ExitStack() as stack:
        # Consumer-path patches (v1.3 D-16; mirrors test_agent_sse.py:141-169).
        stack.enter_context(patch("services.pipeline.get_memory_service",      lambda: _NoMem()))
        stack.enter_context(patch("services.pipeline.get_audit_service",       lambda: _NoAudit()))
        stack.enter_context(patch("services.pipeline.get_tenant_service",      lambda: _NoTenant()))
        stack.enter_context(patch("services.pipeline.get_filter_extractor",    lambda: _NoFilter()))
        stack.enter_context(patch("services.pipeline.get_planner",             lambda: planner))
        stack.enter_context(patch("services.agent.executor.get_tool_registry", lambda: registry))
        stack.enter_context(patch("services.pipeline.get_executor",            lambda: executor))
        stack.enter_context(patch("services.pipeline.get_tool_registry",       lambda: registry))
        stack.enter_context(patch("services.pipeline.get_llm_client",          lambda: _LLM()))
        stack.enter_context(patch("services.pipeline.get_retriever",           lambda: object()))

        req = GenerationRequest(
            query=DEMO_QUERY,
            session_id="demo-session",
            tenant_id="demo-tenant",
            user_id="demo-user",
            top_k=5,
        )
        pipeline = AgentQueryPipeline()
        events: list[AgentEvent] = [e async for e in pipeline.run_streaming(req)]
    return events


def emit_sse_frame(evt: AgentEvent) -> str:
    """Format one event as an SSE wire frame (verbatim from controllers/api.py:282)."""
    # ``event_type`` is a ``ClassVar[str]`` on every concrete AgentEvent subclass
    # (utils/models.py:552-628); the base class omits it abstract-by-convention.
    event_type: str = evt.event_type  # type: ignore[attr-defined]
    return f"event: {event_type}\ndata: {evt.model_dump_json()}\n\n"


_EXPECTED_COUNTS: dict[str, int] = {
    "PlannerPlanEvent": 1, "ToolSpanStartEvent": 4, "ToolSpanEndEvent": 4,
    "ExecutorParallelEvent": 1, "SynthesizerFinalEvent": 1,
}


def validate_event_shape(events: list[AgentEvent]) -> None:
    """Assert the expected demo event counts; raise on mismatch (D-06)."""
    counts: dict[str, int] = {k: 0 for k in _EXPECTED_COUNTS}
    for e in events:
        counts[type(e).__name__] = counts.get(type(e).__name__, 0) + 1
    if counts != _EXPECTED_COUNTS:
        raise RuntimeError(f"Unexpected event sequence: got={counts} expected={_EXPECTED_COUNTS}")


def main() -> int:
    """Synchronous entrypoint: run demo, print SSE frames, exit 0 on success."""
    try:
        events = asyncio.run(run_demo())
        for evt in events:
            print(emit_sse_frame(evt), end="")
        validate_event_shape(events)
        return 0
    except RuntimeError as e:
        print(f"DEMO FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
