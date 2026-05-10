# Phase 11: Provider-Agnostic Agentic Layer + Parallel Tool-Call Burst — Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Two coupled deliverables shipped as a single phase per office-hours design D14 (2026-05-08):

**Step 0 — provider-agnostic agentic layer:**
- Add `AgenticTurn` + `ToolCall` dataclasses (provider-neutral return shape) to `utils/models.py`.
- Add `BaseLLMClient.call_agentic_turn(messages, tools, system, max_tokens, parallel_tool_calls=True) -> AgenticTurn` (non-abstract default raises `NotImplementedError("agent_mode not supported by {provider}")`).
- Implement `AnthropicLLMClient.call_agentic_turn` and `OpenAILLMClient.call_agentic_turn`. `OllamaLLMClient` inherits the default raise.
- Refactor `services/pipeline.py:514-748` (`AgentQueryPipeline`) to drive its tool-use loop via `await self._llm.call_agentic_turn(...)` instead of direct `self._llm._client.messages.create(...)`.
- Remove the `services/pipeline.py:599-604` Anthropic-only fallback; replace with structured-log warning + `QueryPipeline` fallback only when `call_agentic_turn` raises `NotImplementedError` (Ollama).

**v0 — parallel tool-call burst:**
- When LLM returns N ≥ 2 tool calls in a single turn, execute them concurrently via `asyncio.gather(return_exceptions=True)`.
- One failed tool → `tool_result is_error=True` shipped back to LLM (LLM-resilient; pipeline-resilient).
- Tool result correlation preserved via `tool_use_id` → `tool_call.id`.
- Audit log per turn records parallelism factor.

**In scope:**
- `utils/models.py`: `AgenticTurn`, `ToolCall` dataclasses
- `services/generator/llm_client.py`: `BaseLLMClient.call_agentic_turn` default + 2 adapter implementations
- `services/pipeline.py`: AgentQueryPipeline refactor + parallel `asyncio.gather` execution
- `tests/unit/test_llm_client_agentic.py` (new): parametrized over both adapters with mock wire fixtures
- `tests/integration/test_agent_pipeline_parallel.py` (new): live OpenAI through OneAPI gateway
- README differentiator: short "Parallel agentic tool calls" section

**Out of scope (explicit):**
- `OllamaLLMClient.call_agentic_turn` implementation (B1 lock — inherits default raise; deferred req)
- True swarm with fork agents (AGENT-03 / v1 — deferred to v1.3)
- LLM-based filter extractor fallback (v1.2 candidate, deferred to v1.3)
- Streaming SSE for agentic responses (own complexity surface, defer)
- Agent-mode router that auto-picks single-turn vs multi-turn (manual flag only)
- Removing `agent_mode: bool = False` field on `utils/models.py:215` (stays as user toggle)
- Live Anthropic integration tests if no `ANTHROPIC_API_KEY` (skip-gated, mock-tested instead)
- VCR cassettes (C1 lock — pure mock with hand-curated wire fixtures)
- Anthropic prompt-caching adjustments (existing `_cached_system` stays as-is)

</domain>

<decisions>
## Implementation Decisions

### A) AgenticTurn dataclass location
- **D-01:** `AgenticTurn` and `ToolCall` dataclasses live in `utils/models.py`.
  - **Why:** `utils/models.py` is the project's central hub for cross-layer types (`GenerationRequest`, `GenerationResponse`, `ChunkMetadata`, `RetrievedChunk`, etc.). Both producers (adapters in `services/generator/`) and consumers (`AgentQueryPipeline` in `services/pipeline.py`) already import from `utils/models`. Single import surface, matches existing convention. Three-layer arch rule holds (`utils/` is the lowest layer, never imports from `services/` or `controllers/`).
  - **How agents apply:** Planner adds `AgenticTurn` + `ToolCall` to `utils/models.py` near the existing response types. Executors import as `from utils.models import AgenticTurn, ToolCall`. Do NOT create `services/generator/agentic_turn.py`.

### B) Ollama / unimplemented provider handling
- **D-02:** `BaseLLMClient.call_agentic_turn` is **non-abstract** with a default body that raises `NotImplementedError(f"agent_mode not supported by {self.__class__.__name__}")`.
- **D-03:** `AgentQueryPipeline.run` catches `NotImplementedError` from `call_agentic_turn`, emits a structured-log warning (`logger.warning("[Agent] provider lacks call_agentic_turn — falling back", provider=type(self._llm).__name__)`), and falls back to `QueryPipeline`.
  - **Why:** Preserves the user-visible behavior of the existing Anthropic-only gate (Ollama users get fixed-pipeline answers, not crashes) without Anthropic-specific code path. Generic mechanism. Matches CLAUDE.md narrow-except rule (catches `NotImplementedError` specifically, not bare `except`). Anthropic + OpenAI override the default; Ollama inherits it. Future providers (Azure, Bedrock, etc.) can opt in by overriding without breaking concrete subclass instantiation.
  - **How agents apply:** Planner specifies `BaseLLMClient.call_agentic_turn` body as the default raise; both `AnthropicLLMClient` and `OpenAILLMClient` MUST override it; `OllamaLLMClient` MUST NOT override it (the default raise is the contract). Pipeline adds the `try/except NotImplementedError` block in place of the deleted lines 599-604.

### C) Anthropic test strategy without API key
- **D-04:** Pure mock with recorded wire shapes. Test fixtures live in `tests/unit/fixtures/agentic_turn/` as `.json` files (one per scenario: `anthropic_text_only.json`, `anthropic_single_tool_use.json`, `anthropic_two_parallel_tool_use.json`, `anthropic_max_iterations.json`, `openai_text_only.json`, `openai_single_tool_call.json`, `openai_two_parallel_tool_calls.json`).
- **D-05:** Live Anthropic integration test is skip-gated on `ANTHROPIC_API_KEY` env presence; absence → `pytest.skip(reason="ANTHROPIC_API_KEY not set; mock tests cover wire shape")`. Live OpenAI test runs unconditionally via OneAPI gateway (existing `OPENAI_API_KEY` setup verified working in build-step-1 probe at `/tmp/probe_oai_parallel.py`).
  - **Why:** Project doesn't have a CI-side Anthropic key right now; pure mock is deterministic, free, CI-friendly, no extra deps. Hand-curated fixtures are manageable for ~7 files. VCR cassette adds a dep + maintenance cost not justified for this scope. Office-hours design D12 already accepted "no Anthropic side live test in v0."
  - **How agents apply:** Planner adds fixture files under `tests/unit/fixtures/agentic_turn/` with realistic Anthropic + OpenAI wire JSON. Unit tests parametrize over (provider, fixture_name) tuples and assert the adapter's `call_agentic_turn` returns the expected `AgenticTurn` shape. The Anthropic live integration test uses `pytest.mark.skipif(not os.getenv("ANTHROPIC_API_KEY"), ...)`.

### D) Cost guard / opt-in semantics
- **D-06:** Parallel burst inherits the existing `agent_mode: bool` gate on `GenerationRequest` (`utils/models.py:215`). No new flag.
  - **Why:** `agent_mode=True` is the user-facing opt-in for "I want the smarter, more expensive agent path." Parallel burst IS what `agent_mode=True` buys in v1.2 (single user-facing toggle, simplest API surface). Office-hours D4's 15× tokens warning is already satisfied by `agent_mode` itself being opt-in (default `False`). A separate `parallel_burst: bool` flag would create a 4-cell matrix (agent_mode × parallel_burst) with 3 cells that don't make product sense (`agent_mode=False, parallel_burst=True` → undefined).
  - **How agents apply:** When `agent_mode=True`, `AgentQueryPipeline.run` calls `call_agentic_turn(..., parallel_tool_calls=True)` and uses `asyncio.gather` to execute returned tool calls. When `agent_mode=False`, the request never reaches `AgentQueryPipeline` (existing `controllers/api.py:200` dispatch unchanged). NO new env var, NO new settings field, NO new request field.

### Claude's Discretion (planner / executor decide HOW)

- Exact line placement of `AgenticTurn` / `ToolCall` definitions in `utils/models.py` (existing file ordering preserved)
- Mock fixture JSON content (must be realistic wire-format; planner reads Anthropic + OpenAI docs)
- Where in `services/pipeline.py` to land the refactored loop (full rewrite of lines 599-717 OR surgical edit; planner picks based on diff readability)
- Exact `asyncio.gather` exception-handling shape (`return_exceptions=True` is locked; how to convert the exception to `tool_result is_error=True` is impl detail)
- Audit log field names for parallelism factor (suggest `agent_parallelism_factor` to namespace; planner picks)
- Whether to keep or rewrite the existing `seen_ids` chunk-dedup loop in `pipeline.py:692-698` (it's currently inside the per-tool loop; in parallel mode it must move outside the gather)
- README copy for "Parallel agentic tool calls" section (planner writes; matches existing README voice)
- Whether to use `dataclasses.dataclass(frozen=True)` (suggested in office-hours design) or Pydantic V2 model (project default elsewhere) — planner verifies which mixes better with `messages.create()` return parsing
- Adapter return for `stop_reason` mapping (Anthropic's `end_turn` / `tool_use` / `max_tokens` / `stop_sequence` → AgenticTurn `stop_reason`; OpenAI's `stop` / `tool_calls` / `length` → AgenticTurn `stop_reason`). Office-hours design proposes `Literal["text_only", "tool_use", "max_tokens", "error"]` — planner finalizes.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 11 spec
- `.planning/REQUIREMENTS.md` §"REQ E-1 (AGENT-01)" + §"REQ E-2 (AGENT-02)" — 5 + 6 acceptance criteria
- `.planning/ROADMAP.md` §"Phase 11" — 5 success criteria + phase-grouping rationale

### Office-hours design (drives this phase)
- `/home/ubuntu/.gstack/projects/rothenbergverkuilenrn60-oss-rag-enterprise/ubuntu-gsd-phase-8-multimodal-metadata-query-filter-design-20260508-161905.md` — APPROVED design doc with full rationale, premises (1-5), Step 0 abstraction shape (lines ~70-110), v0 parallel burst shape, Eureka-deferred-to-v1 note. **READ BEFORE PLANNING.** D12 (no Anthropic live test), D13 (agent_mode dead code in OpenAI mode), D14 (merge Step 0 + v0 into Phase 11) all originate here.

### Existing code (to be EXTENDED / REFACTORED)
- `services/generator/llm_client.py:102` — `BaseLLMClient` ABC; lines 109/116 are existing abstract methods. New `call_agentic_turn` lives below them as a non-abstract default-raise method.
- `services/generator/llm_client.py:166` — `OllamaLLMClient` (inherits default raise; do NOT override)
- `services/generator/llm_client.py:235` — `OpenAILLMClient` (overrides — adds `call_agentic_turn` impl)
- `services/generator/llm_client.py:345` — `AnthropicLLMClient` (overrides — adds `call_agentic_turn` impl; the existing tool-use loop in `AgentQueryPipeline` becomes this method's body, generalized)
- `services/pipeline.py:514-748` — `AgentQueryPipeline` (full refactor — provider gate removed, loop driven by `call_agentic_turn`, tool execution via `asyncio.gather`)
- `services/pipeline.py:599-604` — DELETE these 6 lines; replace with the generic `try/except NotImplementedError` fallback
- `services/pipeline.py:639-717` — REWRITE the Anthropic-specific tool-use loop into a provider-neutral one
- `services/pipeline.py:692-698` — chunk-dedup `seen_ids` loop; must move outside the parallel gather block
- `utils/models.py:215` — `agent_mode: bool = False` (preserved as user toggle; D-06)
- `controllers/api.py:200` — sole `AgentQueryPipeline` dispatch site (`pipeline = get_agent_pipeline() if req.agent_mode else get_query_pipeline()`); UNCHANGED

### v1.1 carry-forward (DO NOT BREAK)
- `services/nlu/filter_extractor.py:extract_filters()` — used inside AgentQueryPipeline.run line ~620 (`extraction = extract_filters(req.query)`); refactor preserves this call. QUERY-01 contract intact.
- `services/vectorizer/vector_store.py:_build_filter_where()` — META-02 filtered search; tool-driven `retriever.retrieve()` call inside the loop must keep passing `effective_filter` per Phase 8 D-04 (image caption inheritance).
- `.github/workflows/ci.yml` — Phase 10 `diff-cover` step on `unit-tests` job MUST remain green. All Phase 11 PR diffs need ≥ 80 % unit-test coverage on changed lines.

### Build-step-1 evidence (delete from /tmp before ship; reference only)
- `/tmp/probe_oai_parallel.py` — verified `gpt-4o-mini` returns 3 parallel `tool_calls` in single response through OneAPI gateway. Output: `PARALLEL_OK=True count=3 finish_reason=tool_calls`. This is the live evidence backing AGENT-02 acceptance #1.

### External docs (planner reads inline)
- Anthropic Tool Use API — https://docs.anthropic.com/claude/docs/tool-use (single source of truth for `disable_parallel_tool_use`, `tool_use` content block shape, `stop_reason` values)
- OpenAI Function Calling — https://platform.openai.com/docs/guides/function-calling (single source of truth for `parallel_tool_calls`, `tool_calls` array, `finish_reason` values)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `BaseLLMClient` ABC pattern at `services/generator/llm_client.py:102` — already has 2 abstract methods (lines 109, 116) and 3 concrete impls. Adding non-abstract method follows existing pattern.
- `AnthropicLLMClient._cached_system` at line ~360 — used by current AgentQueryPipeline tool-use loop (`pipeline.py:644`); preserve via the new adapter so prompt-caching savings stay intact.
- `_report_usage(resp, "anthropic", ...)` from `services/generator/llm_client.py` — used by current loop; new `call_agentic_turn` impl must keep calling this so token-usage metrics keep flowing.
- `extract_filters` from `services/nlu/filter_extractor.py` — Phase 8 QUERY-01 product; AgentQueryPipeline already calls it (`pipeline.py:~620`); refactor preserves.
- Existing `_AGENT_TOOLS` definition + `_AGENT_SYSTEM` prompt at `pipeline.py:514-580` — these are the tool definitions passed to `call_agentic_turn(..., tools=_AGENT_TOOLS, system=_AGENT_SYSTEM)`. Provider-neutral already (Anthropic/OpenAI both accept the same JSON-schema shape with minor wrapping).
- `controllers/api.py:200` dispatch — `agent_mode` toggle remains the entry point. NO controller changes.

### Established Patterns

- **Three-layer arch:** `utils/` → `services/` → `controllers/`. `AgenticTurn` in `utils/models.py` honors this (lowest layer, no service imports).
- **Tenacity retry on external calls:** Existing adapters wrap `messages.create` / `chat.completions.create` in tenacity decorators (see `services/generator/llm_client.py:381` Anthropic stream method); `call_agentic_turn` impl must preserve the same retry surface.
- **Structured logging:** Existing AgentQueryPipeline uses `logger.info("[Agent] iter=...")` patterns. New parallel-burst log line follows: `logger.info("[Agent] iter=N parallel_factor=M tools=[...]")`.
- **Audit log integration:** `self._audit.write(...)` calls exist throughout pipeline. Parallelism factor recorded as a structured field (planner picks key name).
- **Pydantic V2 / dataclass mix:** Project uses both. `utils/models.py` has Pydantic models (`GenerationRequest`, etc.) and frozen dataclasses (`RetrievedChunk` is a Pydantic model; `ChunkMetadata` is a Pydantic model). Office-hours design proposes `dataclasses.dataclass(frozen=True)` for AgenticTurn — planner verifies whether Pydantic V2 mixes better given the wire-parsing context.

### Out-of-the-way patterns to NOT propagate

- The existing line 692-698 `seen_ids` dedup-inside-the-loop pattern is correct for serial tool execution but breaks under parallel execution (race-free in single-thread asyncio but conceptually misplaced). Move dedup OUTSIDE the parallel `gather` (after all tool results return, before next-turn message append).
- The current `for block in resp.content: if block.type != "tool_use": continue` pattern (line ~660) is Anthropic-specific. Replace with iteration over `agentic_turn.tool_calls: list[ToolCall]` (provider-neutral).
- Do NOT propagate the Anthropic-specific `messages.append({"role": "assistant", "content": resp.content})` shape (line ~656). Use `agentic_turn.raw_assistant_msg` instead — adapter normalizes the message for next-turn append.

</code_context>

## Deferred Ideas

Captured per D-01..D-06 decisions:

1. **`OllamaLLMClient.call_agentic_turn` implementation** (B2 alternative; ~80 LOC + Ollama tool-use integration) — promote to v1.3 phase if Ollama users request agentic mode.
2. **VCR cassette test strategy** (C2 alternative) — only if hand-curated fixtures become a maintenance burden as wire formats evolve.
3. **Separate `parallel_burst: bool` flag** (D2 alternative) — only if a user actually wants `agent_mode=True` + serial tool execution; not a real product use case today.
4. **`settings.parallel_burst_enabled` env-level kill-switch** (D3 alternative) — only as emergency disable if parallel burst surfaces an unexpected production issue.
5. **True swarm with fork agents** (AGENT-03) — v1.3 phase. References `claude-code` `forkedAgent.ts` pattern (filesystem-loaded `AgentDefinition` registry + `agentType` string lookup + cache-safe params for prompt cache sharing).
6. **Streaming SSE for agentic responses** — own complexity surface; v1.3+.
7. **Agent-mode auto-router** (auto-pick single-turn vs multi-turn based on query complexity) — v1.3+.
8. **Removing `agent_mode: bool` field entirely** — only after auto-router lands and proves itself.
9. **Anthropic prompt-caching adjustments for the new `call_agentic_turn` path** — existing `_cached_system` is preserved unchanged; revisit if cache-hit-rate metrics drop.
10. **Live OpenAI integration test in CI matrix expansion** — currently single OneAPI gateway; v1.3+ if multi-region or model-fallback testing becomes valuable.
