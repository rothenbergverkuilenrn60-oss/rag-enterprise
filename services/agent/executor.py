"""Executor — runs a ToolPlan via asyncio.gather (AGENT-06).

Walks ``ToolPlan.parallel_groups`` and dispatches each group concurrently
through ``services.agent.tool_executor.execute_tool_call``. Uses
``BaseException`` for ``asyncio.gather`` isolation (v1.3 Phase 12 D-01) so
``CancelledError`` / ``TimeoutError`` propagation does NOT crash siblings.

The Executor runs exactly one ToolPlan per call — outer-loop iteration
(``MAX_ITERATIONS``) is the orchestrator's responsibility per Phase 16
CONTEXT.md D-12.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from loguru import logger

from services.agent.tool_executor import execute_tool_call
from services.generator.llm_client import get_llm_client
from services.retriever.retriever import get_retriever
from utils.models import GenerationRequest, RetrievedChunk, ToolCall, ToolPlan


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
    ) -> list[tuple[list[RetrievedChunk], str] | BaseException]:
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

        results: list[tuple[list[RetrievedChunk], str] | BaseException | None] = [
            None
        ] * len(plan.steps)

        for group in plan.parallel_groups:
            t0 = time.perf_counter()
            coros = [
                self._dispatch_one(plan.steps[idx], tf, req)
                for idx in group
            ]
            group_results: list[tuple[list[RetrievedChunk], str] | BaseException] = (
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

    async def _dispatch_one(
        self,
        tc: ToolCall,
        tf: dict[str, Any],
        req: GenerationRequest,
    ) -> tuple[list[RetrievedChunk], str]:
        return await execute_tool_call(tc, tf, req, self._retriever, self._llm)


_executor_instance: Executor | None = None


def get_executor() -> Executor:
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = Executor()
    return _executor_instance
