"""tests/unit/test_memory_service_passthrough.py — Phase 24 / T2 (Decision-2).

Covers the new public ``MemoryService.get_relevant_facts`` passthrough method:

  Test 1 (test_memory_service_get_relevant_facts_signature): signature mirrors
          LongTermMemory.get_relevant_facts exactly — same param names, same
          default limit=5, return annotation list[str].
  Test 2 (test_memory_service_get_relevant_facts_delegates_to_long): delegates
          to self._long.get_relevant_facts with correct args; returns the
          delegate's return value.
  Test 3 (test_memory_service_get_relevant_facts_returns_list_str): result is
          a list where every element is a str (runtime type check).

Plan 03 RecallTool calls ``mem_svc.get_relevant_facts(...)`` via this method
rather than reaching into the private ``_long`` attribute directly.
"""
from __future__ import annotations

import os

# Env-var setdefault BEFORE any services.* import (Phase 23 shared pattern)
os.environ.setdefault("APP_MODEL_DIR", "/tmp")
os.environ.setdefault("SECRET_KEY", "a-very-secure-key-for-testing-that-is-long-32c")

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.memory.memory_service import MemoryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_memory_singleton(monkeypatch):
    """Reset the _memory_service singleton between tests."""
    import services.memory.memory_service as mod

    yield
    monkeypatch.setattr(mod, "_memory_service", None, raising=False)


def _make_service_with_mock_long(return_value: list[str]) -> tuple[MemoryService, AsyncMock]:
    """Construct MemoryService with _long.get_relevant_facts mocked."""
    svc = MemoryService.__new__(MemoryService)
    svc._short = MagicMock()
    svc._long = MagicMock()
    mock = AsyncMock(return_value=return_value)
    svc._long.get_relevant_facts = mock
    return svc, mock


# ---------------------------------------------------------------------------
# Test 1: signature mirrors LongTermMemory
# ---------------------------------------------------------------------------
def test_memory_service_get_relevant_facts_signature():
    """Passthrough signature must mirror LongTermMemory.get_relevant_facts."""
    sig = inspect.signature(MemoryService.get_relevant_facts)
    params = list(sig.parameters.keys())
    assert params == ["self", "user_id", "tenant_id", "query", "limit"], (
        f"Signature drift: {params}"
    )
    assert sig.parameters["limit"].default == 5, (
        f"limit default must be 5, got {sig.parameters['limit'].default!r}"
    )
    # Return annotation must be list[str]
    ann = sig.return_annotation
    # Allow both inspect.Parameter.empty and list[str]; must NOT be empty.
    assert ann is not inspect.Parameter.empty, "Return annotation missing"
    assert ann == list[str], f"Return annotation must be list[str], got {ann!r}"


# ---------------------------------------------------------------------------
# Test 2: delegates to self._long.get_relevant_facts
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_memory_service_get_relevant_facts_delegates_to_long():
    """Passthrough must delegate to _long.get_relevant_facts with exact args."""
    svc, mock = _make_service_with_mock_long(["f1", "f2"])

    result = await svc.get_relevant_facts("u1", "t1", "test query")

    mock.assert_awaited_once()
    call_args = mock.call_args
    # Positional args
    assert call_args.args == ("u1", "t1", "test query"), (
        f"Expected positional args ('u1', 't1', 'test query'), got {call_args.args!r}"
    )
    # limit passed as keyword
    assert call_args.kwargs.get("limit") == 5, (
        f"Expected limit=5 keyword, got kwargs={call_args.kwargs!r}"
    )
    assert result == ["f1", "f2"]


# ---------------------------------------------------------------------------
# Test 3: result is list[str]
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_memory_service_get_relevant_facts_returns_list_str():
    """Return value must be a list where every element is a str."""
    svc, _ = _make_service_with_mock_long(["alpha", "beta", "gamma"])

    result = await svc.get_relevant_facts("u1", "t1", "q")

    assert isinstance(result, list), f"Expected list, got {type(result)!r}"
    assert all(isinstance(x, str) for x in result), (
        f"All elements must be str; got {[type(x) for x in result]!r}"
    )
