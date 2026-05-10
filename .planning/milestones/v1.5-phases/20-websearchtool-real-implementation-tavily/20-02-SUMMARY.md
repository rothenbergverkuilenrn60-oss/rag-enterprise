---
phase: 20-websearchtool-real-implementation-tavily
plan: 02
subsystem: agent-tool-real-impl
status: complete
type: tdd
tasks_completed: 3
tags: [websearch, tavily, tdd, error-handling, retrievedchunk-mapping, async, redaction]
gates:
  red:
    commit: dd4e5af
    message: "test(20-02): RED — failing tests for real WebSearchTool (Tavily)"
  green:
    commit: edf7a67
    message: "feat(20-02): GREEN — Tavily-backed WebSearchTool real impl"
  refactor:
    commit: 57485a1
    message: "refactor(20-02): extract _map_tavily_result + _ERROR_CONTENT dict"
prep:
  - commit: 4a10a91
    message: "chore(20-02): sync tavily-python into pyproject.toml + uv.lock"
requires:
  - "Plan 20-01 — Settings.tavily_api_key / tavily_search_depth / tavily_max_results"
  - "Plan 20-01 — tavily-python>=0.7.24,<0.8 pin in requirements.txt"
provides:
  - "WebSearchTool.run() — Tavily AsyncTavilyClient real impl, 3 typed-error branches"
  - "_tavily_search — sole tenacity-wrapped retry boundary in services.agent.tools.web_search"
  - "get_tavily_client — lazy AsyncTavilyClient singleton factory"
  - "_ERROR_CONTENT — single source of truth for D-13 user-facing strings"
  - "_map_tavily_result — Tavily result → RetrievedChunk mapper (D-09..D-12)"
  - "WebSearchTool.description — D-02 steering wording (Plan 20-03 reads it)"
affects:
  - "Plan 20-03 — adds web_search to AGENT_TOOL_ALLOWLIST + integration test"
  - "Plan 20-04 — UI render branch reads chunk_type='web' on RetrievedChunks"
tech-stack:
  added: ["tavily.AsyncTavilyClient (Phase 20 first import)", "tavily.UsageLimitExceededError"]
  patterns:
    - "Tenacity inner-helper retry (CONTEXT D-08; mirrors embedder._embed_single)"
    - "Lazy module-level singleton factory (D-05; mirrors get_tool_registry)"
    - "Module-level settings import (D-07; mirrors llm_client.py)"
    - "Inline typed-error ToolResult construction (D-15; bypasses BaseTool._build_error_result)"
key-files:
  modified:
    - path: services/agent/tools/web_search.py
      role: "Real Tavily-backed WebSearchTool body, _tavily_search retry helper, _map_tavily_result mapper, _ERROR_CONTENT dict, get_tavily_client factory"
      lines_total: 268
    - path: tests/unit/test_web_search_tool.py
      role: "Real-impl unit tests (15 total: 4 registration + 9 run-behavior + 2 helper)"
      lines_total: 486
    - path: pyproject.toml
      role: "tavily-python>=0.7.24,<0.8 added to dependencies"
    - path: uv.lock
      role: "tavily-python==0.7.24 resolution recorded"
decisions:
  - "Tenacity retry_if_exception_type narrowed to (httpx.HTTPStatusError, httpx.HTTPError) so 429 (UsageLimitExceededError) is NOT retried — quota exhaustion exits the boundary on attempt 1 rather than burning 3 quota points"
  - "429 error class is tavily.UsageLimitExceededError, NOT httpx.HTTPStatusError as the plan sketch suggested — verified at execute-time from tavily/async_tavily.py:178-179. Tests + impl reflect actual SDK behavior"
  - "test_tavily_search_is_tenacity_wrapped introspects retrying.stop.max_attempt_number directly because tenacity's stop_after_attempt default __repr__ does not embed the attempt count"
  - "REFACTOR introduced _ERROR_CONTENT[kind] lookup centralized in WebSearchTool._error_result staticmethod — collapses 3× 7-line ToolResult constructors into 3× 4-line call sites; eliminates literal-string drift risk"
metrics:
  duration_minutes: ~9
  completed_date: "2026-05-10"
  files_touched: 4
  lines_added_web_search_py: 209
  lines_added_test_py: 411
  test_count_total: 15
  test_count_added: 11  # 4 reg preserved/updated + 9 run + 2 helper - 5 placeholder removed
  coverage_percent: 94.8
  full_unit_suite: "790 passed, 1 skipped"
---

# Phase 20 Plan 02: WebSearchTool Real Implementation (Tavily) Summary

**One-liner:** Tavily-backed `WebSearchTool.run()` built TDD-strict — async-throughout via `AsyncTavilyClient`, tenacity-narrow retry on `_tavily_search` (429 not retried), three typed-error kinds with D-15 source-side redaction, RetrievedChunk mapping in the D-09..D-12 shape so the existing source-citation flow renders web rows without a UI rewrite.

## TDD Gate Sequence

| Gate | Commit | Lines added | Tests state |
|------|--------|-------------|-------------|
| RED  | `dd4e5af` | tests +384 / -79 | 1 ImportError (collection halts — `_tavily_search` symbol missing) |
| GREEN | `edf7a67` | source +197, tests +20 | 13/13 passing, ruff/mypy clean |
| REFACTOR | `57485a1` | source +59, tests +59 | 15/15 passing, 94.8% coverage |

Pre-gate `chore(20-02): sync tavily-python into pyproject.toml + uv.lock` (`4a10a91`) — Plan 20-01 added the requirements.txt pin only; this commit synced uv's project manifest so `uv sync` would resolve the SDK before GREEN tests need to import it. Not part of the TDD gate sequence; recorded under `prep:` in frontmatter.

## Tasks Completed

### Task 1 — RED: failing real-impl tests (commit `dd4e5af`)

Replaced `tests/unit/test_web_search_tool.py` with the contract for the real impl. Preserved (and updated wording on) the four-test `TestWebSearchToolRegistration` class; replaced placeholder `TestWebSearchToolRun` (5 placeholder-content tests) with 8 real-impl tests against the not-yet-existing surface:

| Test | Branch under contract |
|------|----------------------|
| `test_settings_disabled_short_circuits` | empty `tavily_api_key` → `kind=tavily_disabled`, NO `get_tavily_client` call (spy via `pytest.fail`) |
| `test_happy_path_maps_results` | 200 → `RetrievedChunk` with `chunk_id=f"web:{sha1(url)[:16]}"`, `doc_id="web"`, `chunk_type="web"`, `final_score==tavily_score`, `retrieval_method="web"`, `page_number=None` |
| `test_429_returns_quota_exhausted` | `tavily.UsageLimitExceededError` → `kind=quota_exhausted` |
| `test_5xx_then_200_recovers` | `httpx.HTTPStatusError(500)` then `{"results":[...]}` → tenacity retries, returns 1 mapped chunk |
| `test_5xx_final_failure` | three consecutive `httpx.HTTPStatusError(500)` → `kind=web_search_failed`, `client.calls == 3` |
| `test_metadata_redaction_no_auth_or_tvly_substrings` | leaky 5xx response (`Authorization: Bearer tvly-LEAK`, body `{"error":"server"}`) → `result.model_dump_json()` contains zero forbidden substrings |
| `test_short_circuit_not_retried` | disabled path bypasses retry boundary entirely |
| `test_tavily_search_is_tenacity_wrapped` | `_tavily_search.retry` is the tenacity `Retrying` marker; `retry.stop.max_attempt_number == 3` |
| `test_get_tavily_client_is_lazy_singleton` | two calls → same instance |

Helper stubs at module top:
- `_StubSettings` — three tavily_* fields with default `tavily_api_key="fake-key"`.
- `_StubTavilyClient(*, response, raise_each)` — duck-types `AsyncTavilyClient.search`; `raise_each` is a list popped per call so a test can scenario "first 500, second 200" simply by passing `[exc500, None]`.
- `_make_500_error()` — builds `httpx.HTTPStatusError` with leaky headers + body to feed the redaction test.
- `_make_429_error()` — returns `tavily.UsageLimitExceededError` (the actual SDK exception class for HTTP 429, **not** `httpx.HTTPStatusError` as the plan's exception-type hint suggested).

Mocking idiom strictly per CONTEXT D-04/D-05/D-07: `monkeypatch.setattr("services.agent.tools.web_search.{settings,get_tavily_client,_tavily_client}", ...)` — the SDK class itself (`tavily.AsyncTavilyClient`) is never patched.

**RED evidence (pytest output):**

```
tests/unit/test_web_search_tool.py:33: in <module>
    from services.agent.tools.web_search import (
E   ImportError: cannot import name '_tavily_search' from 'services.agent.tools.web_search'
==================== Interrupted: 1 error during collection ====================
```

Collection itself halts because the placeholder body lacks the `_tavily_search` helper the test module imports. `pytest -x` exits non-zero — RED gate confirmed.

### Task 2 — GREEN: real Tavily-backed implementation (commit `edf7a67`)

Replaced the Phase-17 placeholder body of `services/agent/tools/web_search.py` with the production wiring:

1. **Lazy `AsyncTavilyClient` singleton** (`get_tavily_client`) — module-level `_tavily_client: AsyncTavilyClient | None = None` cache, mirrors the `get_tool_registry` shape.
2. **Tenacity-wrapped `_tavily_search` helper** — the SOLE retry boundary. Decorator: `stop_after_attempt(3) + wait_random_exponential(multiplier=1, max=10) + reraise=True + retry_if_exception_type((httpx.HTTPStatusError, httpx.HTTPError))`. The `retry_if_exception_type` narrowing ensures `UsageLimitExceededError` (429) is NOT retried — the planner re-plans on attempt 1 rather than burning three more quota points.
3. **`WebSearchTool.run()` body** with three branches:
   - **Disabled short-circuit** — `if not settings.tavily_api_key: return ToolResult(kind="tavily_disabled", ...)` BEFORE the retry boundary, BEFORE `get_tavily_client` is called.
   - **Try `_tavily_search`** — catch `UsageLimitExceededError` → `kind="quota_exhausted"`; catch `httpx.HTTPStatusError` (5xx after retries) → `kind="web_search_failed"`; catch `httpx.HTTPError`/`TimeoutError` (transport-layer) → `kind="web_search_failed"`. Every error metadata: only `{error: True, kind, latency_ms}`. Logs only `exc.__class__.__name__` plus HTTP status code — never response headers, body, or stringified exception.
   - **Happy path** — `[_map_tavily_result(r) for r in resp.get("results", [])]`, `chunk_id = f"web:{sha1(url)[:16]}"`, `doc_id="web"`, `metadata.{source,title,chunk_type=web,page_number=None}`, `final_score = tavily_score`, `retrieval_method="web"`, `content = "Web search returned N result(s)."`.
4. **D-02 steering description** — `WebSearchTool.description` rewritten to *"Search the public web for current/real-time information, news, recent events, or topics not covered by the internal knowledge base. Prefer search_knowledge_base for indexed corpus questions."* — Plan 20-03's integration test asserts the steering wording.
5. **`BaseTool._build_error_result` deliberately NOT used** — D-15: it would echo the raw exception in `content`; risks leaking auth-header bytes from a wrapped Tavily SDK exception via the planner-visible string.

**Test fixup during GREEN run:** `test_tavily_search_is_tenacity_wrapped` initially asserted `"3" in repr(retrying.stop)`, but tenacity's `stop_after_attempt.__repr__` does not embed the count (it shows only `<tenacity.stop.stop_after_attempt object at 0x...>`). Switched to introspecting `retrying.stop.max_attempt_number == 3` directly. Filed under Rule 1 (test-side bug) — implementation is correct; the repr-substring assertion was the wrong way to verify the contract.

**Acceptance grep gates (all pass):**

```
@retry( = 1                  stop_after_attempt(3) = 1
reraise=True = 1             _build_error_result = 0
exc.response.(headers|text) = 0   f"{exc}"|format_exc = 0
Placeholder = 0              current/real-time = 1
chunk_type="web" = 1         retrieval_method="web" = 1
doc_id="web" = 1             hashlib.sha1 >= 1
git diff services/pipeline.py = empty (D-01 byte-identity)
```

ruff: `All checks passed!`. mypy --strict: 0 errors in `services/agent/tools/web_search.py` (with one `# type: ignore[import-untyped]` on the `tavily` import — the SDK ships no `py.typed` marker).

### Task 3 — REFACTOR: extract helpers, centralize error strings (commit `57485a1`)

Pure structural cleanup; observable behavior unchanged (all 13 RED→GREEN tests still pass; 2 new helper-coverage tests added bringing the total to 15).

| Helper | Purpose |
|--------|---------|
| `_ERROR_CONTENT: dict[str, str]` | Single source of truth for the three D-13 user-facing strings keyed by error kind. Eliminates literal-string drift between `run()` error branches. |
| `_map_tavily_result(result) -> RetrievedChunk` | Extracted from the happy-path comprehension into a named helper. Single-purpose, easier to coverage-test in isolation (Phase 22 hook). |
| `WebSearchTool._error_result(*, kind, latency_ms)` (staticmethod) | Builds the typed-error `ToolResult` by kind, looking up content from `_ERROR_CONTENT`. Replaces three near-identical 7-line `ToolResult(...)` constructors with three 4-line call sites. |

New tests in `TestWebSearchToolHelpers`:
- `test_error_content_dict_keys_are_the_three_documented_kinds` — guards against future kinds slipping in without explicit review.
- `test_map_tavily_result_produces_expected_shape` — covers the helper in isolation.

**Coverage:** `pytest --cov=services.agent.tools.web_search` → **94.8%** line coverage (target ≥ 90%, floor 70%). Missed lines: 225-231 — the `(httpx.HTTPError, TimeoutError)` transport-error branch. The typed `httpx.HTTPStatusError` and `UsageLimitExceededError` branches catch first, so the transport-error branch is not exercised by the current test suite. Acceptable — the branch's content/metadata shape is identical to the 5xx branch (already covered).

## Plan Verification Block — All Pass

```
pytest tests/unit/test_web_search_tool.py -v          → 15 passed
pytest tests/unit/                                    → 790 passed, 1 skipped
pytest --cov=services.agent.tools.web_search          → 94.8%
ruff check services/agent/tools/web_search.py         → All checks passed!
mypy --strict services/agent/tools/web_search.py      → 0 errors in module
git diff services/pipeline.py                         → empty (D-01 invariant)
git log --oneline | grep -E '^[0-9a-f]+ (test|feat|refactor)\(20-02\)'  → 3 commits in RED→GREEN→REFACTOR order
grep -c '_ERROR_CONTENT' services/agent/tools/web_search.py     → 4 (>= 3)
grep -c '_map_tavily_result' services/agent/tools/web_search.py → 3 (>= 2)
grep -c 'tvly-' services/agent/tools/web_search.py tests/unit/test_web_search_tool.py
  tests/unit/test_web_search_tool.py: 2 occurrences — both in REDACTION fixture body
  ("Bearer tvly-LEAK" header / "tvly-LEAK" assert) — these are the test
  payload that the redaction assertion proves is NOT echoed back. SC5
  applies to source-tracked secrets, not to a fixture string the test
  itself uses to prove redaction works.
  services/agent/tools/web_search.py: 0 (clean)
```

## Deviations from Plan

### D1. 429 SDK exception class is `tavily.UsageLimitExceededError`, not `httpx.HTTPStatusError` (Rule 1 — auto-fix)

**Found during:** Pre-RED inspection of the Tavily SDK.

The plan's `<interfaces>` section, the `<task type="auto">` block for Task 1, and the example mocking code all suggested catching `httpx.HTTPStatusError(status_code=429)` for the quota-exhausted path. Verification at execute-time via `inspect.getsource(tavily.async_tavily)` showed:

```python
# tavily/async_tavily.py:178-187
if response.status_code == 429:
    raise UsageLimitExceededError(detail)        # ← typed exception
elif response.status_code in [403,432,433]:
    raise ForbiddenError(detail)
elif response.status_code == 401:
    raise InvalidAPIKeyError(detail)
elif response.status_code == 400:
    raise BadRequestError(detail)
else:
    raise response.raise_for_status()            # ← httpx.HTTPStatusError ONLY for >=500
```

So the SDK raises `tavily.UsageLimitExceededError` on 429 and `httpx.HTTPStatusError` only on 5xx (via `raise_for_status()`). The implementation catches both classes separately; the test's `_make_429_error()` returns the correct `UsageLimitExceededError`. Rule 1 (auto-fix bugs) — the plan's example would have been incorrect; the implementation reflects actual SDK behavior.

**Effect on plan acceptance:** the `quota_exhausted` and `web_search_failed` kinds are mapped from the correct exception classes. Plan must_haves "Tavily 429 → kind=quota_exhausted; 5xx after 3 retries → kind=web_search_failed" is satisfied with the right wiring.

### D2. Pre-gate `chore` commit for pyproject.toml + uv.lock sync (Rule 3 — blocking issue fix)

**Found during:** Pre-RED `import tavily` failure (`ModuleNotFoundError: No module named 'tavily'`).

Plan 20-01 added the pin to `requirements.txt` only; the project also uses `uv` and a `pyproject.toml` `[project] dependencies` array. `uv add 'tavily-python>=0.7.24,<0.8'` mirrored the constraint into `pyproject.toml` and recorded the resolution (0.7.24) in `uv.lock`. Without this, `uv sync` and CI installs would not surface the SDK and tests/source could not import `tavily.AsyncTavilyClient`.

Committed BEFORE the RED gate as `chore(20-02): sync tavily-python into pyproject.toml + uv.lock` (`4a10a91`). Recorded in frontmatter under `prep:` so the TDD gate sequence (`test → feat → refactor`) is unambiguous in `git log`.

### D3. Test-side bug fixed during GREEN (Rule 1 — auto-fix)

**Found during:** Task 2 GREEN run.

`test_tavily_search_is_tenacity_wrapped` initially asserted `"3" in repr(retrying.stop)`, but tenacity's `stop_after_attempt.__repr__` does not embed the attempt count. Fixed by introspecting `retrying.stop.max_attempt_number == 3` directly (the SDK exposes the field as a public attribute on the stop strategy). The contract being verified is unchanged ("retry stops after 3 attempts"); only the verification mechanism changed.

## Threat Flags

None — the threat register's T-20-05/T-20-06/T-20-08/T-20-09 mitigations are all in place and verified by:
- T-20-05 / T-20-06 (`Authorization` / response-body / response-headers leaks): `test_metadata_redaction_no_auth_or_tvly_substrings` asserts the leaky 5xx fixture's `Authorization: Bearer tvly-LEAK` + body `{"error":"server"}` strings appear zero times in `result.model_dump_json()`.
- T-20-08 (429 retry-storm): tenacity `retry_if_exception_type((httpx.HTTPStatusError, httpx.HTTPError))` excludes `UsageLimitExceededError` so 429 exits on attempt 1; `test_429_returns_quota_exhausted` proves a single client.search call.
- T-20-09 (search query in error logs): all `logger.error(...)` calls log only the exception class name + HTTP status code; the `query` string never appears on the error path.

## Hand-Off Note for Plan 20-03 / 20-04

**Plan 20-03** (allowlist + integration test) reads:

```python
WebSearchTool.description
# → "Search the public web for current/real-time information, news,
#    recent events, or topics not covered by the internal knowledge
#    base. Prefer search_knowledge_base for indexed corpus questions."
```

The exact wording is the contract — Plan 20-03's integration test fixture asserts the planner LLM's `tool_use` block's `name == "web_search"` for real-time queries, which depends on this steering text.

**Plan 20-04** (UI render branch) reads:

```python
chunk = WebSearchTool().run(...).chunks[i]
chunk.metadata.chunk_type   # == "web"
chunk.metadata.source       # == the Tavily URL
```

The `static/ui.js` `chunk_type === "web"` ternary will key off `metadata.chunk_type`. The mapping in `_map_tavily_result` always sets this to `"web"`; the literal is the wire contract.

## Self-Check: PASSED

**Files claimed:**
- `services/agent/tools/web_search.py` (268 lines) — FOUND
- `tests/unit/test_web_search_tool.py` (486 lines) — FOUND
- `pyproject.toml` (tavily dep added) — FOUND
- `uv.lock` (tavily resolved) — FOUND

**Commits claimed:**
- `4a10a91` (prep, chore) — FOUND in `git log`
- `dd4e5af` (RED, test) — FOUND in `git log`
- `edf7a67` (GREEN, feat) — FOUND in `git log`
- `57485a1` (REFACTOR) — FOUND in `git log`

**TDD gate compliance:**
- `git log --grep="^test(20-02):"` → 1 commit (RED `dd4e5af`)
- `git log --grep="^feat(20-02):"` → 1 commit (GREEN `edf7a67`)
- `git log --grep="^refactor(20-02):"` → 1 commit (REFACTOR `57485a1`)
- Order in git log: RED → GREEN → REFACTOR (verified `git log --oneline -4`)

**Plan must_haves contract:**
- Truth 1 (`AsyncTavilyClient` happy-path → mapped `RetrievedChunk`s) — ✓
- Truth 2 (empty key short-circuits to `kind=tavily_disabled` BEFORE network) — ✓
- Truth 3 (429 → `quota_exhausted`; 5xx after 3 retries → `web_search_failed`) — ✓
- Truth 4 (tenacity wraps ONLY `_tavily_search`, NOT mapping or short-circuit) — ✓
- Truth 5 (error metadata: only `error/kind/latency_ms`; never headers/body/traceback) — ✓
- Truth 6 (RetrievedChunk shape exact: chunk_id/doc_id/metadata/final_score/retrieval_method) — ✓

All 8 artifacts (`services/agent/tools/web_search.py` ± symbols and `tests/unit/test_web_search_tool.py` ± method) declared in the plan's `must_haves.artifacts` are present.
