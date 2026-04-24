"""Shared asyncio task helpers.

log_task_error: done_callback for asyncio.create_task() that logs unhandled
exceptions via the project structured logger. Used to close ERR-02 — every
background task must surface failures rather than silently drop them.
"""
from __future__ import annotations

import asyncio

from utils.logger import logger


def log_task_error(task: asyncio.Task) -> None:
    """done_callback — logs unhandled task exceptions to structured logger.

    Safe against cancelled tasks (returns silently). Never re-raises —
    re-raising from a done_callback would surface as an 'exception was never
    retrieved' warning only, which is the bug this helper fixes.

    Per D-08, D-09 of phase 3 context decisions.
    """
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    except asyncio.InvalidStateError:
        return
    if exc is not None:
        logger.error(
            "Background task raised unhandled exception",
            task_name=task.get_name(),
            exc_info=exc,
        )
