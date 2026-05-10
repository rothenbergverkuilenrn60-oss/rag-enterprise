"""Unit tests for WebSearchTool real impl (Phase 20-02).

Tests describe the Tavily-backed contract BEFORE implementation lands.
RED gate: every test in TestWebSearchToolRun fails until Task 2 (GREEN)
rewrites services/agent/tools/web_search.py.

Branches under test (CONTEXT D-02..D-15):
  - tavily_disabled short-circuit (empty key, no network call)
  - 200 happy path → mapped RetrievedChunks (chunk_id/doc_id/metadata shape)
  - 429 → kind="quota_exhausted" via tavily.UsageLimitExceededError
  - 5xx final attempt → kind="web_search_failed" via httpx.HTTPStatusError
  - 5xx-then-200 retry succeeds (tenacity 3-attempt boundary)
  - Source-side redaction: no Authorization / tvly- / Bearer / response.text
    substrings reach result.model_dump_json()
  - _tavily_search is the SOLE tenacity-wrapped function (run() not retried)
  - get_tavily_client is a lazy module-level singleton
  - description ClassVar steers to current/real-time (no "Placeholder")

Mocking idiom (CONTEXT D-04, D-05, D-07): patch the consumer path
(services.agent.tools.web_search.settings + .get_tavily_client),
NEVER tavily.AsyncTavilyClient itself.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import httpx
import pytest

from services.agent.tools import WebSearchTool, get_tool_registry
from services.agent.tools.web_search import (
    _ERROR_CONTENT,
    _map_tavily_result,
    _tavily_search,
    get_tavily_client,
)
from utils.models import GenerationRequest, ToolContext


def _ctx() -> ToolContext:
    return ToolContext(
        req=GenerationRequest(query="q"),
        tf={},
        retriever=object(),
        llm=object(),
    )


# ---------------------------------------------------------------------------
# Test doubles (CONTEXT D-05 / D-07 — patch consumer path, not SDK)
# ---------------------------------------------------------------------------


class _StubSettings:
    """Mirrors the three tavily_* fields read by web_search.py."""

    tavily_api_key: str = "fake-key"
    tavily_search_depth: str = "basic"
    tavily_max_results: int = 5


class _StubTavilyClient:
    """Duck-types AsyncTavilyClient.search().

    `raise_each` is a list of exceptions (or None for "return response") that
    pop one-per-call so a test can scenario "first 500, second 200" simply
    by passing `[exc500, None]`.
    """

    def __init__(
        self,
        *,
        response: dict[str, Any] | None = None,
        raise_each: list[Exception | None] | None = None,
    ) -> None:
        self._response: dict[str, Any] = response if response is not None else {"results": []}
        self._raise_each: list[Exception | None] = list(raise_each or [])
        self.calls: int = 0

    async def search(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self._raise_each:
            exc = self._raise_each.pop(0)
            if exc is not None:
                raise exc
        return self._response


def _make_500_error() -> httpx.HTTPStatusError:
    """Build an httpx.HTTPStatusError matching what response.raise_for_status()
    raises inside the Tavily SDK at status_code 500."""
    req = httpx.Request("POST", "https://api.tavily.com/search")
    resp = httpx.Response(
        500,
        request=req,
        # Headers + body mimic a leaky proxy echo — the redaction test
        # asserts none of these strings reach ToolResult.model_dump_json().
        headers={"Authorization": "Bearer tvly-LEAK", "X-Foo": "bar"},
        text='{"error":"server"}',
    )
    return httpx.HTTPStatusError("500 Internal Server Error", request=req, response=resp)


def _make_429_error() -> Exception:
    """The Tavily SDK raises tavily.UsageLimitExceededError on HTTP 429,
    NOT httpx.HTTPStatusError (verified at execute-time from
    tavily/async_tavily.py:178-179). Test 4 asserts the run() error mapping
    catches this exception class."""
    from tavily import UsageLimitExceededError

    return UsageLimitExceededError("quota exhausted")


# ---------------------------------------------------------------------------
# Registration class — preserved verbatim (Plan 17-02 contract)
# ---------------------------------------------------------------------------


class TestWebSearchToolRegistration:
    def test_web_search_tool_registered(self) -> None:
        """WebSearchTool is registered under name='web_search'."""
        assert "web_search" in get_tool_registry().list()

    def test_web_search_tool_name_classvar(self) -> None:
        """WebSearchTool.name == 'web_search'."""
        assert WebSearchTool.name == "web_search"

    def test_web_search_tool_description_steers_to_realtime(self) -> None:
        """Description carries D-02 steering bias (current/real-time), no placeholder text."""
        desc = WebSearchTool.description
        assert "Placeholder" not in desc
        assert "current" in desc

    def test_web_search_tool_parameters_schema_nonempty(self) -> None:
        """parameters_schema is a non-empty JSON Schema with required=['query']."""
        schema = WebSearchTool.parameters_schema
        assert isinstance(schema, dict)
        assert len(schema) > 0
        assert schema.get("required") == ["query"]


# ---------------------------------------------------------------------------
# Real-impl behavior class — RED gate target
# ---------------------------------------------------------------------------


class TestWebSearchToolRun:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each test starts with a fresh _tavily_client singleton."""
        monkeypatch.setattr(
            "services.agent.tools.web_search._tavily_client", None, raising=False
        )

    @pytest.mark.asyncio
    async def test_settings_disabled_short_circuits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty tavily_api_key → kind=tavily_disabled, NO network call."""

        class _Disabled:
            tavily_api_key: str = ""
            tavily_search_depth: str = "basic"
            tavily_max_results: int = 5

        monkeypatch.setattr(
            "services.agent.tools.web_search.settings", _Disabled()
        )

        # Spy: get_tavily_client must NOT be called.
        def _must_not_call() -> Any:
            pytest.fail("get_tavily_client called on disabled path")

        monkeypatch.setattr(
            "services.agent.tools.web_search.get_tavily_client", _must_not_call
        )

        result = await WebSearchTool().run({"query": "x"}, _ctx())

        assert result.is_error is True
        assert result.chunks == []
        assert result.metadata.get("kind") == "tavily_disabled"
        assert result.metadata.get("error") is True
        assert isinstance(result.metadata.get("latency_ms"), int)
        assert (
            result.content
            == "Web search not configured. Answer from the knowledge base only."
        )

    @pytest.mark.asyncio
    async def test_happy_path_maps_results(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """200 OK → list[RetrievedChunk] with full D-09..D-12 shape."""
        response = {
            "query": "q",
            "results": [
                {
                    "title": "T1",
                    "url": "https://example.com/a",
                    "content": "snippet",
                    "score": 0.91,
                    "raw_content": "...",
                    "favicon": "...",
                },
                {
                    "title": "T2",
                    "url": "https://x.org/b",
                    "content": "s2",
                    "score": 0.7,
                },
            ],
            "response_time": 0.42,
        }
        client = _StubTavilyClient(response=response)
        monkeypatch.setattr(
            "services.agent.tools.web_search.settings", _StubSettings()
        )
        monkeypatch.setattr(
            "services.agent.tools.web_search.get_tavily_client", lambda: client
        )

        result = await WebSearchTool().run({"query": "q"}, _ctx())

        assert result.is_error is False
        assert len(result.chunks) == 2

        c0 = result.chunks[0]
        expected_id = (
            "web:" + hashlib.sha1(b"https://example.com/a").hexdigest()[:16]
        )
        assert c0.chunk_id == expected_id
        assert re.fullmatch(r"web:[0-9a-f]{16}", c0.chunk_id) is not None
        assert c0.doc_id == "web"
        assert c0.content == "snippet"
        assert c0.metadata.source == "https://example.com/a"
        assert c0.metadata.title == "T1"
        assert c0.metadata.chunk_type == "web"
        assert c0.metadata.page_number is None
        assert c0.final_score == pytest.approx(0.91)
        assert c0.retrieval_method == "web"

        c1 = result.chunks[1]
        assert c1.metadata.source == "https://x.org/b"
        assert c1.final_score == pytest.approx(0.7)

        assert "kind" not in result.metadata

    @pytest.mark.asyncio
    async def test_429_returns_quota_exhausted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tavily 429 → UsageLimitExceededError → kind=quota_exhausted (no retry).

        429 is NOT a transient/5xx — tenacity retry_if_exception_type
        excludes it (D-08); the run() error mapping must catch
        UsageLimitExceededError on the first attempt.
        """
        client = _StubTavilyClient(raise_each=[_make_429_error()])
        monkeypatch.setattr(
            "services.agent.tools.web_search.settings", _StubSettings()
        )
        monkeypatch.setattr(
            "services.agent.tools.web_search.get_tavily_client", lambda: client
        )

        result = await WebSearchTool().run({"query": "q"}, _ctx())

        assert result.is_error is True
        assert result.metadata.get("kind") == "quota_exhausted"
        assert result.metadata.get("error") is True
        assert result.chunks == []
        assert (
            result.content
            == "Web search quota exhausted today. Answer from the knowledge base only."
        )

    @pytest.mark.asyncio
    async def test_5xx_then_200_recovers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First call 500, second call 200 → tenacity recovers, mapped chunks."""
        ok_response = {
            "results": [
                {
                    "title": "OK",
                    "url": "https://ok.example.com/p",
                    "content": "yes",
                    "score": 0.5,
                },
            ],
        }
        client = _StubTavilyClient(
            response=ok_response, raise_each=[_make_500_error(), None]
        )
        monkeypatch.setattr(
            "services.agent.tools.web_search.settings", _StubSettings()
        )
        monkeypatch.setattr(
            "services.agent.tools.web_search.get_tavily_client", lambda: client
        )

        result = await WebSearchTool().run({"query": "q"}, _ctx())

        assert client.calls == 2
        assert result.is_error is False
        assert len(result.chunks) == 1
        assert "kind" not in result.metadata

    @pytest.mark.asyncio
    async def test_5xx_final_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three consecutive 500s → tenacity exhausts → kind=web_search_failed."""
        client = _StubTavilyClient(
            raise_each=[
                _make_500_error(),
                _make_500_error(),
                _make_500_error(),
            ]
        )
        monkeypatch.setattr(
            "services.agent.tools.web_search.settings", _StubSettings()
        )
        monkeypatch.setattr(
            "services.agent.tools.web_search.get_tavily_client", lambda: client
        )

        result = await WebSearchTool().run({"query": "q"}, _ctx())

        assert client.calls == 3  # 3 attempts (stop_after_attempt(3))
        assert result.is_error is True
        assert result.metadata.get("kind") == "web_search_failed"
        assert result.chunks == []
        assert (
            result.content
            == "Web search temporarily unavailable. Answer from the knowledge base only."
        )

    @pytest.mark.asyncio
    async def test_metadata_redaction_no_auth_or_tvly_substrings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D-15: leaky 5xx response headers/text never reach ToolResult JSON.

        Reuses Test 5's stub (3× HTTPStatusError with headers={Authorization: Bearer tvly-LEAK}).
        Asserts that result.model_dump_json() contains zero forbidden substrings.
        """
        client = _StubTavilyClient(
            raise_each=[
                _make_500_error(),
                _make_500_error(),
                _make_500_error(),
            ]
        )
        monkeypatch.setattr(
            "services.agent.tools.web_search.settings", _StubSettings()
        )
        monkeypatch.setattr(
            "services.agent.tools.web_search.get_tavily_client", lambda: client
        )

        result = await WebSearchTool().run({"query": "q"}, _ctx())
        serialized = result.model_dump_json()

        for forbidden in (
            "Authorization",
            "tvly-LEAK",
            "Bearer",
            '{"error":"server"}',
            "Traceback",
            "X-Foo",
        ):
            assert forbidden not in serialized, (
                f"redaction leak: {forbidden!r} appeared in serialized result"
            )

    @pytest.mark.asyncio
    async def test_short_circuit_not_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tenacity wraps ONLY _tavily_search — disabled path is not retried.

        Spy: get_tavily_client raises if invoked. Disabled-path returns the
        typed-error result without calling the spy at all.
        """

        class _Disabled:
            tavily_api_key: str = ""
            tavily_search_depth: str = "basic"
            tavily_max_results: int = 5

        invocation_count = {"n": 0}

        def _spy() -> Any:
            invocation_count["n"] += 1
            pytest.fail("get_tavily_client called on disabled path")

        monkeypatch.setattr(
            "services.agent.tools.web_search.settings", _Disabled()
        )
        monkeypatch.setattr(
            "services.agent.tools.web_search.get_tavily_client", _spy
        )

        result = await WebSearchTool().run({"query": "q"}, _ctx())

        assert invocation_count["n"] == 0
        assert result.metadata.get("kind") == "tavily_disabled"

    def test_tavily_search_is_tenacity_wrapped(self) -> None:
        """`_tavily_search` carries a tenacity Retrying object (decorator marker)."""
        # Tenacity attaches `.retry` (the Retrying object) to the decorated callable.
        retrying = getattr(_tavily_search, "retry", None)
        assert retrying is not None, (
            "_tavily_search must be wrapped with @retry; .retry attribute missing"
        )
        # stop=stop_after_attempt(3) — verify class name + max_attempt_number attr.
        # Default repr of stop_after_attempt does not embed the count, so we
        # introspect the attribute instead of substring-matching the repr.
        stop = retrying.stop
        assert stop.__class__.__name__ == "stop_after_attempt"
        assert getattr(stop, "max_attempt_number", None) == 3

    def test_get_tavily_client_is_lazy_singleton(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two calls return the same instance (singleton identity)."""
        monkeypatch.setattr(
            "services.agent.tools.web_search.settings", _StubSettings()
        )
        # Reset module-level cache so first call constructs.
        monkeypatch.setattr(
            "services.agent.tools.web_search._tavily_client", None, raising=False
        )

        a = get_tavily_client()
        b = get_tavily_client()
        assert a is b


# ---------------------------------------------------------------------------
# REFACTOR-introduced helper coverage (Task 3)
# ---------------------------------------------------------------------------


class TestWebSearchToolHelpers:
    def test_error_content_dict_keys_are_the_three_documented_kinds(self) -> None:
        """``_ERROR_CONTENT`` is the single source of truth for D-13 strings.

        Drift between this dict and the run() error branches would mean the
        planner LLM receives inconsistent re-plan guidance. Asserting key
        identity makes future additions explicit.
        """
        assert set(_ERROR_CONTENT.keys()) == {
            "tavily_disabled",
            "quota_exhausted",
            "web_search_failed",
        }
        # Each entry is a non-empty user-facing string.
        for kind, msg in _ERROR_CONTENT.items():
            assert isinstance(msg, str) and msg, f"empty content for {kind!r}"

    def test_map_tavily_result_produces_expected_shape(self) -> None:
        """``_map_tavily_result`` round-trips one Tavily JSON dict to a chunk."""
        result = {
            "title": "Page",
            "url": "https://example.org/path",
            "content": "snippet text",
            "score": 0.42,
        }
        chunk = _map_tavily_result(result)
        expected_id = (
            "web:" + hashlib.sha1(b"https://example.org/path").hexdigest()[:16]
        )
        assert chunk.chunk_id == expected_id
        assert chunk.doc_id == "web"
        assert chunk.content == "snippet text"
        assert chunk.metadata.source == "https://example.org/path"
        assert chunk.metadata.title == "Page"
        assert chunk.metadata.chunk_type == "web"
        assert chunk.metadata.page_number is None
        assert chunk.final_score == pytest.approx(0.42)
        assert chunk.retrieval_method == "web"
