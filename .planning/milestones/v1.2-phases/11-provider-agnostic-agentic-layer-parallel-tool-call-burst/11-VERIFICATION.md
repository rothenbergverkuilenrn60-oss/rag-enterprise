---
phase: 11-provider-agnostic-agentic-layer-parallel-tool-call-burst
verified: 2026-05-08T00:00:00Z
status: passed
score: 5/5 ROADMAP SCs verified · 11/11 REQ ACs verified · 6/6 D-locks honored
verdict: PASS
runtime_evidence:
  unit_tests:
    command: ".venv/bin/python -m pytest tests/unit/test_agentic_turn_models.py tests/unit/test_base_llm_client_agentic.py tests/unit/test_llm_client_agentic.py tests/unit/test_agent_pipeline_refactor.py -v"
    result: "38 passed, 22 warnings in 3.58s"
    breakdown: "9 (turn models) + 5 (base default-raise) + 13 (adapter parametrize) + 11 (pipeline refactor)"
  ruff:
    command: ".venv/bin/python -m ruff check utils/models.py services/generator/llm_client.py tests/unit/test_agentic_turn_models.py tests/unit/test_base_llm_client_agentic.py tests/unit/test_llm_client_agentic.py tests/unit/test_agent_pipeline_refactor.py tests/integration/test_agent_pipeline_parallel.py"
    result: "All checks passed!"
  pre_existing_lint_noise:
    file: services/pipeline.py
    issues: "F401 NLUResult (line 53), F401 MemoryContext (line 56)"
    origin: "Both present at master tip (17c91bc) — pre-existing v1.1 carry-over, NOT introduced by Phase 11"
deferred_runtime:
  - "Live OpenAI integration test (tests/integration/test_agent_pipeline_parallel.py) — deferred to PR CI / post-merge per phase plan; structurally sound; build-step-1 probe at /tmp/probe_oai_parallel.py confirmed gpt-4o-mini emits parallel tool_calls through OneAPI gateway"
---

# Phase 11: Provider-Agnostic Agentic Layer + Parallel Tool-Call Burst — Verification Report

**Phase Goal:** `AgentQueryPipeline` with `agent_mode=True` runs the real tool-use loop on both OpenAI and Anthropic providers; a single LLM turn returning N ≥ 2 tool calls executes them concurrently — closing the OpenAI silent-fallback gap from `services/pipeline.py:599-604` and adding parallel-burst latency reduction.

**Verified:** 2026-05-08
**Status:** **PASS**
**Re-verification:** No — initial verification

---

## ROADMAP Success Criteria (5 SCs)

| # | Criterion | Evidence | Status |
|---|---|---|---|
| 1 | `BaseLLMClient.call_agentic_turn(messages, tools, ...)` exists with provider-neutral return shape (text + tool_calls + finish_reason); `AnthropicLLMClient` and `OpenAILLMClient` both implement it | `services/generator/llm_client.py:153` (Base default-raise) + `:364` (OpenAI override) + `:616` (Anthropic override). `grep -c "async def call_agentic_turn"` = 3. Returns `AgenticTurn` (defined `utils/models.py:261`) with `text` + `tool_calls: list[ToolCall]` + `stop_reason: Literal["text_only","tool_use","max_tokens","error"]` (`utils/models.py:284-285`). | ✓ VERIFIED |
| 2 | `services/pipeline.py:599-604` Anthropic-only fallback REMOVED; OpenAI mode runs real tool-use loop end-to-end honoring `MAX_ITERATIONS = 5` | `grep -c "if not isinstance(self._llm, AnthropicLLMClient)" services/pipeline.py` = 0. `grep -c "AnthropicLLMClient" services/pipeline.py` = 0. New body at `services/pipeline.py:609-788` calls `await self._llm.call_agentic_turn(...)` (line 645) inside `for iteration in range(self.MAX_ITERATIONS)` loop (line 643). `MAX_ITERATIONS = 5` preserved at line 541. | ✓ VERIFIED |
| 3 | When LLM returns N ≥ 2 tool calls in single turn, `AgentQueryPipeline` executes them concurrently via `asyncio.gather`; total latency bounded by slowest tool, not sum | `services/pipeline.py:716`: `tool_outputs = await asyncio.gather(*tool_coros, return_exceptions=True)`. `tool_coros` constructed from `[self._execute_tool_call(tc, tf or {}, req) for tc in turn.tool_calls]` (lines 712-715). Per-tool helper `_execute_tool_call` at line 790 — side-effect-free, gather-safe. `tests/unit/test_agent_pipeline_refactor.py::test_two_tool_calls_run_concurrently` uses an asyncio.Event two-event pattern that would deadlock on a serial path; PASSES. | ✓ VERIFIED |
| 4 | Audit log per turn records the parallelism factor | `services/pipeline.py:708-710`: `logger.info(f"[Agent] iter={iteration+1} parallel_factor={parallelism} tools={tool_names}")`. Per-turn structured log line emitted ONCE per turn that issues tool calls. `tests/unit/test_agent_pipeline_refactor.py::test_per_turn_structured_log_records_parallel_factor` asserts log shape AND `intent="agent"` literal kwarg on AuditService.log_query call. | ✓ VERIFIED |
| 5 | Live integration test against OpenAI (OneAPI gateway, `gpt-4o-mini`) submits multi-dimension `agent_mode=True` query, verifies ≥ 2 tool calls executed concurrently + all results in next turn | `tests/integration/test_agent_pipeline_parallel.py` exists. Module-level marker `pytestmark = [pytest.mark.integration]`. NO `pytest.mark.skipif` on `OPENAI_API_KEY` (verified — only `skipif` substring matches are inline comments, lines 12 + 26). Multi-dimension query at lines 59-62; assertions: `assert not any("falling back" in line for line in captured)` (line 85), `assert any(f >= 2 for f in factors)` (line 103), `assert matches >= 2` of (产假/病假/加班) (line 119). Build-step-1 probe at `/tmp/probe_oai_parallel.py` confirmed `PARALLEL_OK=True count=3 finish_reason=tool_calls` for gpt-4o-mini through OneAPI. Live runtime execution deferred to PR CI per phase plan. | ✓ VERIFIED (test exists + structurally sound; runtime deferred) |

---

## REQ E-1 / AGENT-01 Acceptance Criteria (5 ACs)

| # | Acceptance | Evidence | Status |
|---|---|---|---|
| 1 | `BaseLLMClient` defines abstract method `call_agentic_turn(messages, tools, ...) -> AgentTurnResult` with provider-neutral return shape | `services/generator/llm_client.py:153-177`: `async def call_agentic_turn` defined as **non-abstract default-raise** per D-02 (Anthropic-side decision: D-02 honored — abstract was relaxed to non-abstract for Ollama inheritance). Return type `AgenticTurn` (provider-neutral). Signature `(self, messages, tools, system, max_tokens=1024, parallel_tool_calls=True)`. | ✓ VERIFIED |
| 2 | Anthropic + OpenAI both implement; differences absorbed inside adapters | `OpenAILLMClient.call_agentic_turn` at `services/generator/llm_client.py:364-484` — converts tools from Anthropic-shape to OpenAI-shape (lines 397-406), prepends system as first message (line 409), `json.loads` decodes `function.arguments` JSON-string to dict, maps `finish_reason → stop_reason`. `AnthropicLLMClient.call_agentic_turn` at `:616-714` — uses `self._cached_system(system)` for Prompt Caching, parses `content` blocks (text + tool_use), maps Anthropic `stop_reason → AgenticTurn.stop_reason`. Both return identical `AgenticTurn` shape. | ✓ VERIFIED |
| 3 | `services/pipeline.py:599-604` fallback removed | Verified above (SC#2). 6 lines deleted. Replacement: generic `except NotImplementedError` block at `services/pipeline.py:652-660` falls back via `return await get_query_pipeline().run(req)` with structured-log warning. | ✓ VERIFIED |
| 4 | Unit tests parametrized over both adapters with mock provider responses | `tests/unit/test_llm_client_agentic.py` — 13 tests. 4 anthropic-parametrized (text_only / single_tool_use / two_parallel / max_iterations) + 3 openai-parametrized (text_only / single_tool_call / two_parallel) + 6 cross-cutting (parallel-flag, system-prepended, tools-shape, _cached_system, _RAW_DICT_FIELDS lock, Ollama default-raise regression). `_RAW_DICT_FIELDS = {"input"}` at line 33. **All 13 PASS.** | ✓ VERIFIED |
| 5 | Live OpenAI integration test (skip-gate on Anthropic key) | `tests/integration/test_agent_pipeline_parallel.py` exists; **NO skipif on OPENAI_API_KEY** (D-05 / W-6). Anthropic side mock-tested via the 4 anthropic fixtures in `test_llm_client_agentic.py`. Anthropic live test absent by design (D-05: skip-gated; CI has no Anthropic key). | ✓ VERIFIED |

---

## REQ E-2 / AGENT-02 Acceptance Criteria (6 ACs)

| # | Acceptance | Evidence | Status |
|---|---|---|---|
| 1 | N ≥ 2 tool calls execute concurrently via `asyncio.gather` | `services/pipeline.py:716`: `await asyncio.gather(*tool_coros, return_exceptions=True)`. `tests/unit/test_agent_pipeline_refactor.py::test_two_tool_calls_run_concurrently` uses 2-event handshake pattern; PASSES. | ✓ VERIFIED |
| 2 | `parallel_tool_calls=True` (OpenAI) / `disable_parallel_tool_use=False` (Anthropic) explicit | OpenAI: `services/generator/llm_client.py:416` — `parallel_tool_calls=parallel_tool_calls` explicit kwarg (caller passes `True`). Anthropic: `:659` — `disable_parallel_tool_use=(not parallel_tool_calls)` explicit kwarg. Both adapters' tests assert kwargs were passed explicitly. | ✓ VERIFIED |
| 3 | Tool result correlation via `tool_call.id` preserved | `services/pipeline.py:719-738`: `for tc, output in zip(turn.tool_calls, tool_outputs)` builds `tool_results` with `"tool_use_id": tc.id` per result. Order preserved via zip. `tests/unit/test_agent_pipeline_refactor.py::test_chunk_dedup_runs_after_gather_not_inside` confirms dedup runs once per turn after results aggregate. | ✓ VERIFIED |
| 4 | Audit log per turn records the parallelism factor | Same as ROADMAP SC#4. `services/pipeline.py:708-710` structured-log line. | ✓ VERIFIED |
| 5 | End-to-end test verifies concurrent execution + all results returned + final answer references all N | `tests/integration/test_agent_pipeline_parallel.py` — asserts (a) no `"falling back"` log line (real loop ran), (b) `parallel_factor >= 2` in at least one log line, (c) final `resp.answer` contains ≥ 2 of (产假/病假/加班) keyword classes. Live runtime deferred to PR CI. | ✓ VERIFIED (structural; runtime deferred) |
| 6 | README "Parallel agentic tool calls" section added | `README.md:18-34`: "Parallel agentic tool calls" section. Documents provider neutrality, parallel execution, per-turn audit trail, live demo command, NotImplementedError fallback semantics. | ✓ VERIFIED |

---

## Locked Decision Honor (D-01 .. D-06)

| # | Decision | Evidence | Honored? |
|---|---|---|---|
| D-01 | `AgenticTurn` + `ToolCall` live in `utils/models.py` (NOT `services/generator/agentic_turn.py`) | `utils/models.py:244` (`class ToolCall`) + `:261` (`class AgenticTurn`). `services/generator/agentic_turn.py` does not exist. `from utils.models import AgenticTurn` at `services/generator/llm_client.py:29`; `from utils.models import ... AgenticTurn ... ToolCall` at `services/pipeline.py:30+38`. | ✓ |
| D-02 | `BaseLLMClient.call_agentic_turn` non-abstract default-raise (NOT `@abstractmethod`) | `services/generator/llm_client.py:153-177` — no `@abstractmethod` decorator; raises `NotImplementedError(f"agent_mode not supported by {self.__class__.__name__}")`. `OllamaLLMClient` at line 193 has NO override (inherits default). `tests/unit/test_base_llm_client_agentic.py` confirms `__abstractmethods__` count unchanged (still 2: chat, stream_chat). | ✓ |
| D-03 | `AgentQueryPipeline` catches `NotImplementedError` → fallback to `QueryPipeline` with structured-log warning | `services/pipeline.py:652-660` — `except NotImplementedError:` block emits `logger.warning(f"[Agent] provider lacks call_agentic_turn — falling back: provider={type(self._llm).__name__}")` then `return await get_query_pipeline().run(req)`. `tests/unit/test_agent_pipeline_refactor.py::test_pipeline_falls_back_when_call_agentic_turn_raises` PASSES. | ✓ |
| D-04 | Pure-mock fixtures (NOT VCR cassettes) | `tests/unit/fixtures/agentic_turn/` — 7 hand-curated `.json` files + `__init__.py`. Total ~4 KB. No `vcrpy` / `pytest-vcr` dependency added. `test_llm_client_agentic.py` loads via `json.loads((FIXTURE_DIR / name).read_text())`. | ✓ |
| D-05 | OpenAI live test runs unconditionally; Anthropic skip-gated | `tests/integration/test_agent_pipeline_parallel.py`: NO `skipif` on OPENAI_API_KEY (verified via grep — only inline comment matches). No live Anthropic integration test ships in this phase (acceptable per D-05; mock fixtures cover Anthropic wire shape). | ✓ |
| D-06 | `agent_mode` is the only toggle (no new flag/env/setting); `controllers/api.py:200` UNCHANGED | `git log --oneline 17c91bc..HEAD -- controllers/api.py` returns empty (zero Phase 11 commits to controllers/api.py). `grep agent_mode controllers/api.py` confirms dispatch site at line 200 intact: `pipeline = get_agent_pipeline() if req.agent_mode else get_query_pipeline()`. `utils/models.py:215` `agent_mode: bool = False` field unchanged. NO new field added to `GenerationRequest`. NO new env var. NO new `settings.parallel_burst_enabled` etc. | ✓ |

---

## Critical Refactor Verification

| Check | Expected | Observed | Status |
|---|---|---|---|
| `services/pipeline.py:599-604` Anthropic-only fallback deleted | 0 matches | `grep "if not isinstance(self._llm, AnthropicLLMClient)"` → 0; `grep "AnthropicLLMClient"` (file-wide) → 0 | ✓ |
| `asyncio.gather` present in AgentQueryPipeline body | ≥ 1 | Line 716: `asyncio.gather(*tool_coros, return_exceptions=True)` | ✓ |
| `return_exceptions=True` (gotcha #5) | required | Line 716 explicit | ✓ |
| `seen_ids` dedup OUTSIDE gather (gotcha #1) | dedup post-gather, single pass | Lines 740-747: `seen_ids: set[str] = set()` initialized AFTER `asyncio.gather` (line 716) and AFTER per-output for-loop (lines 720-738); runs once per turn | ✓ |
| Narrow except tuple per ERR-01 (B-1) | `(anthropic.APIError, openai.APIError, httpx.HTTPError, asyncio.TimeoutError)` | Lines 661-666 verbatim. No bare `except Exception` in agent body. RuntimeError bubbles per `test_narrow_except_does_not_catch_runtime_error`. | ✓ |
| `intent="agent"` literal preserved (W-3) | literal string, no f-string | Line 773: `intent="agent"` literal kwarg in `AuditService.log_query` call | ✓ |
| `controllers/api.py:200` UNCHANGED across Phase 11 | empty diff | `git log 17c91bc..HEAD -- controllers/api.py` empty | ✓ |
| No `AnthropicLLMClient` references inside class body (W-4 type leakage) | 0 in class body | File-wide: 0 matches (broader than W-4 — even imports gone) | ✓ |
| `import anthropic` / `import openai` only used inside narrow except tuple | imports at module-top with `# noqa: F401`, no class-body reference | Lines 23-25: module-top imports with explanatory `# noqa: F401` comments. Only `except (anthropic.APIError, openai.APIError, ...)` references them. NOT used as type checks (no `isinstance` against provider classes). | ✓ |
| `extract_filters(req.query)` preserved (gotcha #2 — QUERY-01 contract intact) | call survives at top of run | Line 618: `extraction = extract_filters(req.query)` | ✓ |
| `MAX_ITERATIONS = 5` preserved (gotcha #7) | unchanged | Line 541 | ✓ |
| `parallel_factor=` substring present in structured log | ≥ 1 active log call | Line 709 active + line 768 comment | ✓ |
| `_execute_tool_call` private helper exists (gather-safe, side-effect-free) | new method | Lines 790-831; takes `(tc: ToolCall, tf: dict, req: GenerationRequest)`, returns `(chunks, ctx_text)` | ✓ |

---

## Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| AGENT-01 (E-1) | 11-01, 11-02, 11-03, 11-04 | Provider-agnostic agentic tool-use layer | ✓ SATISFIED | All 5 ACs verified above; 38 unit tests pass |
| AGENT-02 (E-2) | 11-04 | Parallel tool-call burst within single turn | ✓ SATISFIED | All 6 ACs verified above; integration test ships; runtime deferred to CI |

**Orphaned requirements:** none. ROADMAP §"Coverage Validation" maps both AGENT-IDs to Phase 11 only; both REQ-IDs claimed by plan frontmatter.

---

## Anti-Patterns Scan

| File | Issue | Severity | Disposition |
|---|---|---|---|
| `services/pipeline.py:53` | `F401 NLUResult` unused import | Info (pre-existing) | Origin: master tip 17c91bc — NOT introduced by Phase 11. Out of scope per "surgical changes" rule. |
| `services/pipeline.py:56` | `F401 MemoryContext` unused import | Info (pre-existing) | Same as above. |

No new TODO/FIXME/HACK/PLACEHOLDER markers introduced. No bare `except Exception`. No hardcoded secrets. No console.log/print debugging. No empty handlers.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| AgenticTurn + ToolCall importable from utils.models | `.venv/bin/python -c "from utils.models import AgenticTurn, ToolCall"` | (implicit — pytest collects + runs without ImportError) | ✓ PASS |
| BaseLLMClient.call_agentic_turn raises NotImplementedError on Ollama | `pytest tests/unit/test_llm_client_agentic.py::test_ollama_inherits_default_raise` | passes (1/1) | ✓ PASS |
| Anthropic adapter parses 4 wire fixtures | `pytest tests/unit/test_llm_client_agentic.py -k anthropic_parametrize` | passes (4/4) | ✓ PASS |
| OpenAI adapter parses 3 wire fixtures | `pytest tests/unit/test_llm_client_agentic.py -k openai_parametrize` | passes (3/3) | ✓ PASS |
| AgentQueryPipeline.run uses asyncio.gather for ≥ 2 tool calls (concurrency proof) | `pytest tests/unit/test_agent_pipeline_refactor.py::test_two_tool_calls_run_concurrently` | passes — 2-event handshake would deadlock on serial path | ✓ PASS |
| AgentQueryPipeline.run falls back to QueryPipeline on NotImplementedError | `pytest tests/unit/test_agent_pipeline_refactor.py::test_pipeline_falls_back_when_call_agentic_turn_raises` | passes | ✓ PASS |
| MAX_ITERATIONS = 5 honored (no infinite loop) | `pytest tests/unit/test_agent_pipeline_refactor.py::test_max_iterations_is_5` | passes | ✓ PASS |
| Narrow except — RuntimeError bubbles | `pytest tests/unit/test_agent_pipeline_refactor.py::test_narrow_except_does_not_catch_runtime_error` | passes (`pytest.raises(RuntimeError)`) | ✓ PASS |
| Ruff clean on Phase 11 net code | `.venv/bin/python -m ruff check utils/models.py services/generator/llm_client.py tests/.../test_*agentic*.py tests/.../test_agent_pipeline_*.py` | All checks passed! | ✓ PASS |
| Live OpenAI integration test against gpt-4o-mini through OneAPI | `pytest tests/integration/test_agent_pipeline_parallel.py -v` | NOT EXECUTED in verifier env | ? SKIP — deferred to PR CI per phase plan; build-step-1 probe at /tmp/probe_oai_parallel.py confirmed wire-level evidence (PARALLEL_OK=True count=3) |

**Aggregate:** 9/10 PASS, 1 SKIP (live integration — not a gap; deferred by design).

---

## Verdict: PASS

All 5 ROADMAP Success Criteria verified. All 11 REQ acceptance criteria verified (5 AGENT-01 + 6 AGENT-02). All 6 locked decisions (D-01..D-06) honored. Critical refactor checks all green: 599-604 deletion, asyncio.gather + return_exceptions=True, post-gather seen_ids dedup, narrow except tuple, intent="agent" literal, controllers/api.py UNCHANGED, no provider type leakage in class body. 38/38 Phase 11 unit tests pass. Ruff clean on net new code. Pre-existing F401 noise on `services/pipeline.py:53,56` is out-of-scope master-tip carry-over (not introduced by this phase).

**One deferred runtime confirmation:** the live OpenAI integration test (`tests/integration/test_agent_pipeline_parallel.py`) is structurally complete — pytestmark integration, no skipif on OPENAI_API_KEY, multi-dimension query, parallel-factor + keyword-class assertions — but actual end-to-end execution against gpt-4o-mini through the OneAPI gateway is deferred to PR CI / post-merge per the phase plan. The build-step-1 probe at `/tmp/probe_oai_parallel.py` already confirmed wire-level evidence that gpt-4o-mini emits parallel `tool_calls` through the gateway (`PARALLEL_OK=True count=3 finish_reason=tool_calls`), so the parallel-execution gate is grounded in observed model behavior. Test pass/fail post-merge depends on the test pgvector store containing 产假/病假/加班 corpus content (the W-2 keyword-class assertion); empty corpus would surface as a hard fail, not a silent skip — the test design protects this.

---

## Notes for Ship / PR Description

- **Goal-backward verification: PASS.** All ROADMAP SCs + REQ ACs satisfied; all locked decisions (D-01..D-06) honored.
- **Test evidence:** 38/38 Phase 11 unit tests pass (`pytest tests/unit/test_agentic_turn_models.py tests/unit/test_base_llm_client_agentic.py tests/unit/test_llm_client_agentic.py tests/unit/test_agent_pipeline_refactor.py`). Plan SUMMARYs flagged "sandbox-blocked" runtime gaps; verifier ran the suite from the project root and confirmed all pass.
- **Ruff:** Clean on Phase 11 net code. Two pre-existing F401 imports in `services/pipeline.py:53,56` (`NLUResult`, `MemoryContext`) are master-tip carry-over from v1.1, NOT introduced by this phase. Out-of-scope per the surgical-changes rule. Suggest a one-line follow-up cleanup PR.
- **Live integration test:** `tests/integration/test_agent_pipeline_parallel.py` ships. Module-level `pytestmark = [pytest.mark.integration]`; collected only by integration runs. NO skipif on OPENAI_API_KEY (per D-05 / W-6 — missing key is a config error, not a skip). Runtime confirmation against the OneAPI gateway is the natural next step at PR CI / post-merge.
- **Phase 11 commit chain (TDD discipline preserved):**
  - 11-01: `80b42c3` (RED) → `e0ba4b1` (GREEN) → `55ecac8` (RED) → `b0e7b85` (GREEN)
  - 11-02: `9225955` + `75ef6f8` (fixture additions)
  - 11-03: `7fd7f31` (RED) → `a4c1c90` (GREEN) → `03d6c1b` (RED) → `6e3921e` (GREEN) → `8ec5672` (polish — Ollama regression)
  - 11-04: `faceb67` (RED) → `f5275ae` (GREEN) → `e82e603` (polish — integration test + README)
  - Worktree-base drift recovered via `git pull . <base> --ff-only` on plans 11-03 + 11-04 (sandbox-permitted; no content lost; same recovered code shipped).
- **Deferred to v1.3 per CONTEXT.md:** Ollama `call_agentic_turn` impl (B2 alt), VCR cassettes (C2 alt), separate `parallel_burst: bool` flag (D2 alt), `settings.parallel_burst_enabled` env kill-switch (D3 alt), true swarm with fork agents (AGENT-03), streaming SSE for agentic, agent-mode auto-router, removal of `agent_mode: bool` field, Anthropic prompt-caching adjustments, multi-region OpenAI CI matrix.

---

_Verified: 2026-05-08_
_Verifier: Claude (gsd-verifier)_
