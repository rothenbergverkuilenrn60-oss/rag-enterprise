"""Unit tests for RecallTool — MEM-08 behavioral contract (Phase 24-03, RED gate).

Tests describe the RecallTool.run() contract BEFORE the implementation lands.
RED gate: tests 1, 4-14 fail against the Plan 01 stub. Tests 2-3 pass against
the stub (ClassVars already present) but are included for completeness.

Branches under test (PLAN 24-03 D-C2/D-C3/D-C4):
  - Registration exactly-once guard (Pitfall 4)
  - ClassVar content matches ROADMAP D-C4 strings
  - parameters_schema dict equality to MEM-08 literal
  - Happy path: facts -> bullet-list ToolResult (is_error=False)
  - Empty return: get_relevant_facts==[] -> empty marker (is_error=False, NOT error)
  - Error isolation: 4 narrow exception types -> error marker (is_error=True)
  - Auth precondition: missing user_id/tenant_id/query -> empty marker, no recall call
  - Query resolution: args["query"] overrides ctx.req.query; fallback works
  - Latency metadata present in happy path
  - Error path uses stable _ERROR_MARKER, never exception class name (D-C3)
  - Static guard: run() source must not reach into mem._long (T3 / Decision-2)

Mocking idiom: patch consumer path services.agent.tools.recall.get_memory_service,
NOT services.memory.memory_service.get_memory_service directly.
"""
from __future__ import annotations

import os

os.environ.setdefault("MODEL_DIR", "/tmp/models")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")

import inspect
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import httpx
import pytest

from utils.models import GenerationRequest, ToolContext, ToolResult


# ---------------------------------------------------------------------------
# Reusable _ctx helper (PATTERNS analog 10 §Reusable ctx helper)
# ---------------------------------------------------------------------------

def _ctx(
    user_id: str = "u1",
    tenant_id: str = "t1",
    query: str = "q",
) -> ToolContext:
    return ToolContext(
        req=GenerationRequest(query=query or "placeholder", user_id=user_id, tenant_id=tenant_id),
        tf={},
        retriever=object(),
        llm=object(),
    )


def _ctx_no_query(user_id: str = "u1", tenant_id: str = "t1") -> ToolContext:
    """For missing-query tests: build ctx with a query value we override via args={}."""
    # GenerationRequest requires query with min_length=1, so we supply a stub
    # and rely on args={} so the tool falls back to ctx.req.query, which we
    # then test by comparing behavior not by setting query="" directly here.
    return ToolContext(
        req=GenerationRequest(query="to-be-ignored", user_id=user_id, tenant_id=tenant_id),
        tf={},
        retriever=object(),
        llm=object(),
    )


# ---------------------------------------------------------------------------
# Helper — build a fake MemoryService with get_relevant_facts AsyncMock
# ---------------------------------------------------------------------------

def _fake_mem(return_value: list[str] | None = None, side_effect: Exception | None = None) -> MagicMock:
    mem = MagicMock()
    if side_effect is not None:
        mem.get_relevant_facts = AsyncMock(side_effect=side_effect)
    else:
        mem.get_relevant_facts = AsyncMock(return_value=return_value or [])
    return mem


# ---------------------------------------------------------------------------
# Test 1: registered exactly once (Pitfall 4)
# ---------------------------------------------------------------------------

def test_recall_tool_registered_once() -> None:
    """Importing services.agent.tools.recall registers recall_memory exactly once."""
    import services.agent.tools.recall  # noqa: F401 — side-effect import
    from services.agent.tools.registry import get_tool_registry

    count = get_tool_registry().list().count("recall_memory")
    assert count == 1, (
        f"Expected recall_memory registered exactly once, got {count}. "
        "Check for duplicate imports or missing @get_tool_registry().register decorator."
    )


# ---------------------------------------------------------------------------
# Test 2: ClassVars match ROADMAP / D-C4 strings
# ---------------------------------------------------------------------------

def test_recall_tool_classvars_match_roadmap() -> None:
    """RecallTool.name and .description match the D-C4 required strings."""
    from services.agent.tools.recall import RecallTool

    assert RecallTool.name == "recall_memory"
    assert "Recall durable facts the agent has previously learned" in RecallTool.description
    assert "Skip when conversation pivots to a new topic" in RecallTool.description


# ---------------------------------------------------------------------------
# Test 3: parameters_schema is MEM-08 literal (no extra keys)
# ---------------------------------------------------------------------------

def test_parameters_schema_is_mem_08_literal() -> None:
    """parameters_schema must equal the MEM-08 dict exactly — no additional keys."""
    from services.agent.tools.recall import RecallTool

    expected = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    assert RecallTool.parameters_schema == expected


# ---------------------------------------------------------------------------
# Test 4: happy path — bullets format
# ---------------------------------------------------------------------------

async def test_happy_path_bullets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: get_relevant_facts returns facts -> bullet-list content, is_error=False."""
    from services.agent.tools.recall import RecallTool

    fake = _fake_mem(return_value=["fact1", "fact2", "fact3"])
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", lambda: fake)

    ctx = _ctx(user_id="u", tenant_id="t", query="q")
    result = await RecallTool().run({"query": "q"}, ctx)

    assert isinstance(result, ToolResult)
    assert result.content == "- fact1\n- fact2\n- fact3"
    assert result.is_error is False
    assert result.metadata["fact_count"] == 3
    assert "latency_ms" in result.metadata
    assert result.metadata["query"] == "q"


# ---------------------------------------------------------------------------
# Test 5: empty marker — is_error=False (D-C2)
# ---------------------------------------------------------------------------

async def test_empty_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty result: get_relevant_facts==[] -> empty marker, is_error=False (NOT error)."""
    from services.agent.tools.recall import RecallTool, _EMPTY_MARKER

    fake = _fake_mem(return_value=[])
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", lambda: fake)

    ctx = _ctx(user_id="u", tenant_id="t", query="q")
    result = await RecallTool().run({"query": "q"}, ctx)

    assert result.content == _EMPTY_MARKER
    assert result.is_error is False
    assert result.metadata.get("fact_count") == 0


# ---------------------------------------------------------------------------
# Test 6: error isolation — parametrized over 4 exception types (D-C3)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exc",
    [
        asyncpg.PostgresError("pg"),
        httpx.HTTPError("net"),
        RuntimeError("rt"),
        OSError("os"),
    ],
)
async def test_error_isolation_parametrized(
    exc: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error path: narrow exception types -> error marker, is_error=True, no propagation."""
    from services.agent.tools.recall import RecallTool

    fake = _fake_mem(side_effect=exc)
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", lambda: fake)

    ctx = _ctx(user_id="u", tenant_id="t", query="q")
    # Must NOT raise — best-effort isolation
    result = await RecallTool().run({"query": "q"}, ctx)

    assert result.content == "Memory unavailable; proceed without recall."
    assert result.is_error is True
    assert result.metadata.get("error") is True


# ---------------------------------------------------------------------------
# Test 7: missing user_id -> empty marker, no recall call
# ---------------------------------------------------------------------------

async def test_missing_user_id_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth precondition: empty user_id -> empty marker, get_memory_service NOT called."""
    from services.agent.tools.recall import RecallTool, _EMPTY_MARKER

    factory_spy = MagicMock()
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", factory_spy)

    ctx = _ctx(user_id="", tenant_id="t", query="q")
    result = await RecallTool().run({"query": "q"}, ctx)

    factory_spy.assert_not_called()
    assert result.content == _EMPTY_MARKER
    assert result.is_error is False
    assert result.metadata.get("reason") == "missing_user_or_tenant_id"


# ---------------------------------------------------------------------------
# Test 8: missing tenant_id -> empty marker, no recall call
# ---------------------------------------------------------------------------

async def test_missing_tenant_id_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auth precondition: empty tenant_id -> empty marker, get_memory_service NOT called."""
    from services.agent.tools.recall import RecallTool, _EMPTY_MARKER

    factory_spy = MagicMock()
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", factory_spy)

    ctx = _ctx(user_id="u", tenant_id="", query="q")
    result = await RecallTool().run({"query": "q"}, ctx)

    factory_spy.assert_not_called()
    assert result.content == _EMPTY_MARKER
    assert result.is_error is False
    assert result.metadata.get("reason") == "missing_user_or_tenant_id"


# ---------------------------------------------------------------------------
# Test 9: missing query (args={} + ctx.req.query empty-ish) -> empty marker
# ---------------------------------------------------------------------------

async def test_missing_query_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """No resolvable query (args with whitespace-only, ctx query also stripped) -> empty marker.

    The tool resolves query as: (args.get("query") or ctx.req.query or "").strip()
    Passing args={"query": "  "} (whitespace) AND ctx.req.query="  " (whitespace) gives
    a query_str of "" after stripping, triggering the auth precondition short-circuit.

    Since GenerationRequest.strip_query strips the query at validation time (min_length=1
    after strip), we cannot set ctx.req.query to whitespace directly via Pydantic.
    Instead, we supply a real ctx but pass args={"query": "  "} so the resolution is:
    ("  " or ctx.req.query or "").strip() == "  ".strip() == "".
    Note: "  " is truthy in Python (non-empty string), so it wins the `or` chain.
    The strip() applied at the end makes query_str == "", triggering the precondition.
    """
    from services.agent.tools.recall import RecallTool, _EMPTY_MARKER

    factory_spy = MagicMock()
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", factory_spy)

    ctx = _ctx(user_id="u", tenant_id="t", query="fallback")
    # args["query"] = "  " (whitespace-only) — truthy so wins `or` chain, but strips to ""
    result = await RecallTool().run({"query": "  "}, ctx)

    factory_spy.assert_not_called()
    assert result.content == _EMPTY_MARKER
    assert result.is_error is False


# ---------------------------------------------------------------------------
# Test 10: args["query"] overrides ctx.req.query
# ---------------------------------------------------------------------------

async def test_args_query_overrides_ctx_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """args['query'] takes precedence over ctx.req.query when both are present."""
    from services.agent.tools.recall import RecallTool

    fake = _fake_mem(return_value=["fact"])
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", lambda: fake)

    ctx = _ctx(user_id="u", tenant_id="t", query="fallback")
    await RecallTool().run({"query": "explicit"}, ctx)

    call_args = fake.get_relevant_facts.call_args
    # Third positional arg is the query string
    actual_query = call_args.args[2]
    assert actual_query == "explicit"


# ---------------------------------------------------------------------------
# Test 11: args missing "query" -> falls back to ctx.req.query
# ---------------------------------------------------------------------------

async def test_args_missing_falls_back_to_ctx_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """When args has no 'query' key, the tool falls back to ctx.req.query."""
    from services.agent.tools.recall import RecallTool

    fake = _fake_mem(return_value=["fact"])
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", lambda: fake)

    ctx = _ctx(user_id="u", tenant_id="t", query="fallback")
    await RecallTool().run({}, ctx)

    call_args = fake.get_relevant_facts.call_args
    actual_query = call_args.args[2]
    assert actual_query == "fallback"


# ---------------------------------------------------------------------------
# Test 12: latency_ms metadata present and non-negative (happy path)
# ---------------------------------------------------------------------------

async def test_latency_metadata_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: metadata must contain latency_ms as a non-negative int."""
    from services.agent.tools.recall import RecallTool

    fake = _fake_mem(return_value=["fact"])
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", lambda: fake)

    ctx = _ctx(user_id="u", tenant_id="t", query="q")
    result = await RecallTool().run({"query": "q"}, ctx)

    assert "latency_ms" in result.metadata
    assert isinstance(result.metadata["latency_ms"], int)
    assert result.metadata["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# Test 13: error path content is stable marker, not exception text (D-C3)
# ---------------------------------------------------------------------------

async def test_error_path_uses_stable_marker_not_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error path: content must not leak exception class names per D-C3."""
    from services.agent.tools.recall import RecallTool

    fake = _fake_mem(side_effect=asyncpg.PostgresError("internal db error"))
    monkeypatch.setattr("services.agent.tools.recall.get_memory_service", lambda: fake)

    ctx = _ctx(user_id="u", tenant_id="t", query="q")
    result = await RecallTool().run({"query": "q"}, ctx)

    assert "asyncpg" not in result.content
    assert "PostgresError" not in result.content
    assert "internal db error" not in result.content


# ---------------------------------------------------------------------------
# Test 14: static guard — run() must not reach into mem._long (T3 / Decision-2)
# ---------------------------------------------------------------------------

def test_no_long_private_attr_reach() -> None:
    """Static guard: RecallTool.run executable code must not reach into mem._long.*

    T3 (eng-review 2026-05-16 / Decision-2): the tool calls only the public
    passthrough mem.get_relevant_facts(). Reaching into _long is banned.

    We strip docstrings before checking so documentation comments about _long
    (explaining the guard) don't trigger the assertion — only executable code matters.
    """
    import ast
    import textwrap
    from services.agent.tools.recall import RecallTool

    full_src = inspect.getsource(RecallTool.run)
    # Strip the leading docstring from the source so documentation text
    # explaining the _long constraint doesn't self-trigger the guard.
    # We do this by parsing the AST and reconstructing just the non-docstring lines.
    dedented = textwrap.dedent(full_src)
    try:
        tree = ast.parse(dedented)
        func_def = tree.body[0]
        # Identify the docstring node (first Expr node with a Constant string value)
        docstring_end_line = 0
        if (
            isinstance(func_def, ast.AsyncFunctionDef)
            and func_def.body
            and isinstance(func_def.body[0], ast.Expr)
            and isinstance(func_def.body[0].value, ast.Constant)
            and isinstance(func_def.body[0].value.value, str)
        ):
            docstring_end_line = func_def.body[0].end_lineno or 0
        lines = dedented.splitlines()
        # Keep only lines beyond the docstring
        code_lines = lines[docstring_end_line:]
        code_only = "\n".join(code_lines)
    except SyntaxError:
        # Fallback: use the raw source if AST parse fails
        code_only = full_src

    assert "_long." not in code_only, (
        "RecallTool.run executable code reaches into private _long attribute — "
        "use mem.get_relevant_facts() public passthrough instead (T3 / Decision-2)."
    )
    assert "mem._long" not in code_only, (
        "RecallTool.run executable code uses mem._long directly — forbidden by T3 / Decision-2."
    )
