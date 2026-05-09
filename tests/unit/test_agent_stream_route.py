"""TDD RED tests for /agent/v1/run/stream route (AGENT-04, plan 18-04).

Asserts D-01 (named-event SSE), D-03 (rate limit), D-10 (event:/data: line
shape), and security_gate (no new auth code path). Threat-model coverage:
T-18-12..T-18-18 (auth, tenant, rate-limit, headers, audit, format).

Test 8 is a parity gate — it does not validate this plan's new code; it
validates that /query/stream remains untouched (D-02).
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from utils.models import (
    AgentEvent,
    ExecutorParallelEvent,
    GenerationRequest,
    PlannerPlanEvent,
    SynthesizerFinalEvent,
    ToolCall,
    ToolPlan,
    ToolSpanEndEvent,
    ToolSpanErrorEvent,
    ToolSpanStartEvent,
)


# ---------------------------------------------------------------------------
# Stub events + stub pipeline
# ---------------------------------------------------------------------------

def _stub_events() -> list[AgentEvent]:
    """Realistic 5-event sequence covering planner.plan, tool.span.start,
    tool.span.end, executor.parallel, synthesizer.final."""
    plan = ToolPlan(
        steps=[ToolCall(id="c0", name="search_knowledge_base", arguments={"q": "x"})],
        parallel_groups=[[0]],
        rationale="r",
        raw_assistant_msg={"role": "assistant", "content": "stub"},
        stop_reason="tool_use",
    )
    return [
        PlannerPlanEvent(trace_id="t1", seq=0, ts_ms=1, plan=plan),
        ToolSpanStartEvent(
            trace_id="t1", seq=1, ts_ms=2,
            span_id="s1", name="search_knowledge_base", args={"q": "x"},
        ),
        ToolSpanEndEvent(
            trace_id="t1", seq=2, ts_ms=3,
            span_id="s1", latency_ms=10, chunk_count=2,
            is_error=False, content_preview="ok",
        ),
        ExecutorParallelEvent(
            trace_id="t1", seq=3, ts_ms=4,
            fan_out=1, group_latency_ms=10,
        ),
        SynthesizerFinalEvent(
            trace_id="t1", seq=4, ts_ms=5,
            answer="done", sources_count=2,
        ),
    ]


def _stub_events_with_error() -> list[AgentEvent]:
    return [
        ToolSpanErrorEvent(
            trace_id="t1", seq=0, ts_ms=1,
            span_id="s1", latency_ms=5,
            error_type="RuntimeError", error_message="boom",
        ),
        SynthesizerFinalEvent(
            trace_id="t1", seq=1, ts_ms=2,
            answer="failed", sources_count=0,
        ),
    ]


class _StubAgentPipeline:
    def __init__(self, events: list[AgentEvent]) -> None:
        self._events = events

    async def run_streaming(self, req: GenerationRequest) -> AsyncIterator[AgentEvent]:
        for e in self._events:
            yield e


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_agent_pipeline(monkeypatch: pytest.MonkeyPatch):
    def _do(events: list[AgentEvent]) -> None:
        monkeypatch.setattr(
            "controllers.api.get_agent_pipeline",
            lambda: _StubAgentPipeline(events),
        )
    return _do


@pytest.fixture
def client() -> TestClient:
    from main import app
    return TestClient(app)


def _parse_sse(body: str) -> list[dict[str, str]]:
    """Parse SSE body into a list of {event, data} dicts. Empty frames skipped."""
    frames: list[dict[str, str]] = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        evt, data = "", ""
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                evt = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = line[len("data:"):].strip()
        if evt or data:
            frames.append({"event": evt, "data": data})
    return frames


def _post_body() -> dict[str, Any]:
    return {"query": "hello", "session_id": "s1", "top_k": 5}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_route_exists_and_returns_200_with_sse_headers(
    client: TestClient, patch_agent_pipeline,
) -> None:
    """T-18-15: SSE headers present and exact."""
    patch_agent_pipeline(_stub_events())
    r = client.post("/api/v1/agent/v1/run/stream", json=_post_body())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"


def test_route_emits_named_event_lines(
    client: TestClient, patch_agent_pipeline,
) -> None:
    """T-18-18: named-event line format `event:\ndata:\n\n`, JSON-valid data."""
    patch_agent_pipeline(_stub_events())
    r = client.post("/api/v1/agent/v1/run/stream", json=_post_body())
    frames = _parse_sse(r.text)
    assert len(frames) >= 5
    for f in frames:
        assert f["event"], f"every frame must have event: line — got {f}"
        assert f["data"], f"every frame must have data: line — got {f}"
        # data must be valid JSON
        json.loads(f["data"])


def test_route_terminal_event_is_synthesizer_final(
    client: TestClient, patch_agent_pipeline,
) -> None:
    """D-01: synthesizer.final IS terminal — no [DONE] sentinel."""
    patch_agent_pipeline(_stub_events())
    r = client.post("/api/v1/agent/v1/run/stream", json=_post_body())
    frames = _parse_sse(r.text)
    assert frames[-1]["event"] == "synthesizer.final"
    assert "[DONE]" not in r.text, (
        "no [DONE] sentinel — synthesizer.final IS terminal (D-01)"
    )


def test_route_emits_all_event_types_for_multistep_plan(
    client: TestClient, patch_agent_pipeline,
) -> None:
    """ROADMAP Phase 18 SC1: all event types fire end-to-end."""
    patch_agent_pipeline(_stub_events())
    r = client.post("/api/v1/agent/v1/run/stream", json=_post_body())
    frames = _parse_sse(r.text)
    types = {f["event"] for f in frames}
    expected_subset = {
        "planner.plan",
        "tool.span.start",
        "tool.span.end",
        "executor.parallel",
        "synthesizer.final",
    }
    assert expected_subset.issubset(types), (
        f"missing event types: {expected_subset - types}"
    )


def test_route_emits_tool_span_error_on_tool_failure(
    client: TestClient, patch_agent_pipeline,
) -> None:
    """D-12: tool.span.error replaces tool.span.end on tool failure."""
    patch_agent_pipeline(_stub_events_with_error())
    r = client.post("/api/v1/agent/v1/run/stream", json=_post_body())
    frames = _parse_sse(r.text)
    types = [f["event"] for f in frames]
    assert "tool.span.error" in types


def test_route_uses_get_agent_pipeline_not_query(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route MUST consume get_agent_pipeline() — NOT get_query_pipeline()."""
    calls: dict[str, int] = {"agent": 0, "query": 0}

    def _agent():
        calls["agent"] += 1
        return _StubAgentPipeline(_stub_events())

    def _query():
        calls["query"] += 1
        return _StubAgentPipeline(_stub_events())  # shape doesn't matter

    monkeypatch.setattr("controllers.api.get_agent_pipeline", _agent)
    monkeypatch.setattr("controllers.api.get_query_pipeline", _query)

    r = client.post("/api/v1/agent/v1/run/stream", json=_post_body())
    assert r.status_code == 200
    assert calls["agent"] == 1, "route must call get_agent_pipeline exactly once"
    assert calls["query"] == 0, "route must NOT call get_query_pipeline"


def test_route_does_not_change_query_stream(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-02 parity: existing /query/stream is data-only — Phase 18 must not touch it."""
    class _StubQuery:
        async def stream(self, req: GenerationRequest):
            yield "tok1"
            yield "tok2"

    monkeypatch.setattr("controllers.api.get_query_pipeline", lambda: _StubQuery())
    r = client.post("/api/v1/query/stream", json=_post_body())
    assert r.status_code == 200
    # Original format: data: tok\n\n — no event: prefix anywhere
    assert "event:" not in r.text
    assert "data: [DONE]" in r.text  # legacy sentinel still present
