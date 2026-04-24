"""Unit tests for utils.tasks.log_task_error done_callback helper.

Covers ERR-02: every background task must surface failures via structured logging
rather than silently dropping exceptions.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Test 1 — successful task: no error is logged
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_log_task_error_no_log_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given a task that completed successfully, log_task_error must NOT call logger.error."""
    mock_logger = MagicMock()
    monkeypatch.setattr("utils.tasks.logger", mock_logger)

    from utils.tasks import log_task_error  # import after monkeypatch

    async def _ok() -> str:
        return "done"

    task = asyncio.create_task(_ok())
    await task

    log_task_error(task)

    mock_logger.error.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2 — failed task: logger.error called once with task_name and exc_info
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_log_task_error_logs_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given a task that raised RuntimeError, log_task_error must call logger.error exactly once."""
    mock_logger = MagicMock()
    monkeypatch.setattr("utils.tasks.logger", mock_logger)

    from utils.tasks import log_task_error

    async def _fail() -> None:
        raise RuntimeError("boom")

    task = asyncio.create_task(_fail(), name="test-fail-task")
    # Suppress 'exception was never retrieved' warning by awaiting with expected error
    with pytest.raises(RuntimeError):
        await task

    log_task_error(task)

    mock_logger.error.assert_called_once()
    call_kwargs = mock_logger.error.call_args
    # exc_info must be the RuntimeError instance
    assert isinstance(call_kwargs.kwargs.get("exc_info"), RuntimeError)
    # task_name must be passed
    assert call_kwargs.kwargs.get("task_name") == "test-fail-task"


# ---------------------------------------------------------------------------
# Test 3 — cancelled task: returns silently without logging
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_log_task_error_silent_on_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Given a cancelled task, log_task_error must return silently without calling logger.error."""
    mock_logger = MagicMock()
    monkeypatch.setattr("utils.tasks.logger", mock_logger)

    from utils.tasks import log_task_error

    async def _forever() -> None:
        await asyncio.sleep(9999)

    task = asyncio.create_task(_forever())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    log_task_error(task)

    mock_logger.error.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4 — never re-raises: calling after a failed task must not propagate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_log_task_error_never_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    """log_task_error must NOT re-raise the task exception to its caller."""
    mock_logger = MagicMock()
    monkeypatch.setattr("utils.tasks.logger", mock_logger)

    from utils.tasks import log_task_error

    async def _fail() -> None:
        raise ValueError("should not propagate")

    task = asyncio.create_task(_fail())
    with pytest.raises(ValueError):
        await task

    # Must not raise — calling log_task_error is always safe
    try:
        log_task_error(task)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"log_task_error re-raised an exception: {exc}")
