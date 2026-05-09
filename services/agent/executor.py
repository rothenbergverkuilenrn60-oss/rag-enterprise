"""Executor — runs a ToolPlan via asyncio.gather (AGENT-06).

Walks ``ToolPlan.parallel_groups`` and dispatches each group concurrently
through the ``ToolRegistry``. Uses ``BaseException`` for
``asyncio.gather`` isolation (v1.3 Phase 12 D-01) so ``CancelledError`` /
``TimeoutError`` propagation does NOT crash siblings.

The Executor runs exactly one ToolPlan per call — outer-loop iteration
(``MAX_ITERATIONS``) is the orchestrator's responsibility per Phase 16
CONTEXT.md D-12.

Phase 17 (v1.4 AGENT-07): ``_dispatch_one`` now routes through
``get_tool_registry().get(name).run(args, ctx)``; ``execute_tool_call``
from the deleted ``tool_executor.py`` is no longer referenced here.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

from loguru import logger

from services.agent.tools import get_tool_registry
from services.generator.llm_client import get_llm_client
from services.retriever.retriever import get_retriever
from utils.models import (
    AgentEvent,
    ExecutorParallelEvent,
    GenerationRequest,
    ToolCall,
    ToolContext,
    ToolPlan,
    ToolResult,
    ToolSpanEndEvent,
    ToolSpanErrorEvent,
    ToolSpanStartEvent,
)


class Executor:
    """Walks ToolPlan.parallel_groups, dispatches via asyncio.gather."""

    def __init__(
        self,
        retriever: Any | None = None,
        llm: Any | None = None,
    ) -> None:
        self._retriever = retriever if retriever is not None else get_retriever()
        self._llm = llm if llm is not None else get_llm_client()

    async def execute_plan(
        self,
        plan: ToolPlan,
        tf: dict[str, Any],
        req: GenerationRequest,
    ) -> list[ToolResult | BaseException]:
        """Run every step in plan.parallel_groups order.

        Returns a list in step-index order (NOT group order — caller can
        re-correlate via plan.steps[i].id). Length equals len(plan.steps).

        Per-tool errors are returned as ``BaseException`` entries rather than
        raised; this mirrors the v1.3 ``asyncio.gather(return_exceptions=True)``
        pattern and preserves the orchestrator's ``is_error=True`` tool-result
        construction for resilient multi-tool turns (Phase 16 Wave-3, test 4).
        CancelledError / TimeoutError are **not** re-raised here; the
        orchestrator receives them as error entries and builds an error
        tool_result (v1.3 Phase 12 D-01 isolation guarantee maintained).
        """
        if not plan.steps:
            return []

        results: list[ToolResult | BaseException | None] = [
            None
        ] * len(plan.steps)

        for group in plan.parallel_groups:
            t0 = time.perf_counter()
            coros = [
                self._dispatch_one(plan.steps[idx], tf, req)
                for idx in group
            ]
            group_results: list[ToolResult | BaseException] = (
                await asyncio.gather(*coros, return_exceptions=True)
            )
            for idx, res in zip(group, group_results):
                if isinstance(res, BaseException):
                    logger.error(
                        f"[Executor] step_idx={idx} name={plan.steps[idx].name} "
                        f"failed: {res!r}"
                    )
                results[idx] = res

            logger.info(
                f"[Executor] group_size={len(group)} parallel_factor={len(group)} "
                f"latency_ms={int((time.perf_counter() - t0) * 1000)}"
            )

        return [r for r in results if r is not None]

    async def execute_plan_streaming(
        self,
        plan: ToolPlan,
        tf: dict[str, Any],
        req: GenerationRequest,
        *,
        trace_id: str,
        seq_counter: Iterator[int],
    ) -> AsyncIterator[AgentEvent | ToolResult | BaseException]:
        """Streaming sibling of ``execute_plan`` — yields events + results interleaved.

        Yields ``AgentEvent`` instances at lifecycle boundaries (start of each
        dispatch, end-or-error of each dispatch, end of each parallel group)
        AND yields the bare ``ToolResult`` / ``BaseException`` results as they
        resolve, so the orchestrator (plan 18-03) can collect them by step
        index via the ``isinstance(item, AgentEvent)`` discriminator
        (Phase 18 D-05).

        Ordering invariants per group:
          1. ALL ``ToolSpanStartEvent`` for the group are yielded BEFORE any
             coroutine in that group awaits (start-events-before-gather).
          2. As each task resolves, yield ``ToolSpanEndEvent`` (or
             ``ToolSpanErrorEvent``) THEN the bare result — using
             ``asyncio.as_completed`` so events surface in completion order
             (NOT step-index order).
          3. After all tasks in the group resolve, yield exactly one
             ``ExecutorParallelEvent`` with both ``fan_out`` and
             ``group_latency_ms`` populated (plan 18-01 ``planner_decision``
             reconciliation: emit at group END so ``group_latency_ms`` is
             always real).

        BaseException isolation (v1.3 Phase 12 D-01) preserved verbatim: a
        raising coroutine yields a ``ToolSpanErrorEvent`` + ``BaseException``
        result; sibling tasks keep running. ``CancelledError`` /
        ``TimeoutError`` are collected like
        ``gather(return_exceptions=True)`` does — caught at the per-task
        wrapper, not at the ``as_completed`` loop, so ordering is stable
        even when the FIRST task raises.

        The orchestrator threads ``seq_counter`` (an ``itertools.count()``
        instance) so ``seq`` is monotonic across pipeline + executor events.
        Each ``span_id = uuid.uuid4().hex[:8]`` (Phase 16 trace_id pattern).
        """
        if not plan.steps:
            return

        for group in plan.parallel_groups:
            t_group = time.perf_counter()

            # 1. Pre-emit ToolSpanStartEvent for every idx in the group.
            #    This MUST happen before any await — invariant (1) above.
            span_id_by_idx: dict[int, str] = {idx: uuid.uuid4().hex[:8] for idx in group}
            for idx in group:
                tc: ToolCall = plan.steps[idx]
                yield ToolSpanStartEvent(
                    trace_id=trace_id,
                    seq=next(seq_counter),
                    ts_ms=int(time.time() * 1000),
                    span_id=span_id_by_idx[idx],
                    name=tc.name,
                    args=dict(tc.arguments) if tc.arguments else {},
                )

            # 2. Schedule tasks; per-task timing recorded in a wrapper coro
            #    that itself catches BaseException so as_completed never raises.
            async def _timed(
                idx: int,
            ) -> tuple[int, ToolResult | BaseException, int]:
                t_task = time.perf_counter()
                try:
                    res: ToolResult | BaseException = await self._dispatch_one(
                        plan.steps[idx], tf, req,
                    )
                except BaseException as exc:  # noqa: BLE001 — preserve v1.3 D-01 isolation
                    logger.error(
                        f"[Executor] step_idx={idx} name={plan.steps[idx].name} "
                        f"failed: {exc!r}"
                    )
                    res = exc
                latency_ms = int((time.perf_counter() - t_task) * 1000)
                return idx, res, latency_ms

            tasks = [asyncio.create_task(_timed(idx)) for idx in group]

            # 3. as_completed — emit end/error event + bare result per task.
            for fut in asyncio.as_completed(tasks):
                idx, res, latency_ms = await fut
                span_id = span_id_by_idx[idx]
                if isinstance(res, BaseException):
                    yield ToolSpanErrorEvent(
                        trace_id=trace_id,
                        seq=next(seq_counter),
                        ts_ms=int(time.time() * 1000),
                        span_id=span_id,
                        latency_ms=latency_ms,
                        error_type=type(res).__name__,
                        error_message=str(res)[:200],
                    )
                else:
                    chunk_count = (
                        res.metadata.get("chunk_count", len(res.chunks))
                        if res.metadata
                        else len(res.chunks)
                    )
                    yield ToolSpanEndEvent(
                        trace_id=trace_id,
                        seq=next(seq_counter),
                        ts_ms=int(time.time() * 1000),
                        span_id=span_id,
                        latency_ms=latency_ms,
                        chunk_count=int(chunk_count),
                        is_error=res.is_error,
                        content_preview=res.content[:200] if res.content else "",
                    )
                yield res

            # 4. Group end — single ExecutorParallelEvent (plan 18-01 planner_decision).
            group_latency_ms = int((time.perf_counter() - t_group) * 1000)
            yield ExecutorParallelEvent(
                trace_id=trace_id,
                seq=next(seq_counter),
                ts_ms=int(time.time() * 1000),
                fan_out=len(group),
                group_latency_ms=group_latency_ms,
            )

            logger.info(
                f"[Executor] group_size={len(group)} parallel_factor={len(group)} "
                f"latency_ms={group_latency_ms} streaming=True"
            )

    async def _dispatch_one(
        self,
        tc: ToolCall,
        tf: dict[str, Any],
        req: GenerationRequest,
    ) -> ToolResult:
        ctx = ToolContext(
            req=req,
            tf=tf,
            retriever=self._retriever,
            llm=self._llm,
        )
        tool = get_tool_registry().get(tc.name)
        return await tool.run(args=tc.arguments or {}, ctx=ctx)


_executor_instance: Executor | None = None


def get_executor() -> Executor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = Executor()
    return _executor_instance
