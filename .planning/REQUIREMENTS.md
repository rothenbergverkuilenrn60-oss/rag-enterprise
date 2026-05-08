# Requirements — v1.2 Agentic Layer + Swarm

**Defined:** 2026-05-08
**Status:** Active

---

## v1 Requirements

### Track E — Agentic Layer

#### REQ E-1 (AGENT-01): Provider-agnostic agentic tool-use layer

**As a** maintainer running EnterpriseRAG with `llm_provider="openai"` (the project default)
**I want** `AgentQueryPipeline` to actually execute the tool-use loop instead of silently falling back to `QueryPipeline` for non-Anthropic providers
**So that** `agent_mode=True` is a real product feature for both Anthropic and OpenAI users, not Anthropic-only dead code in production

**Background:** Currently `services/pipeline.py:599-604` short-circuits the entire agent loop when the LLM client is not `AnthropicLLMClient`. Project default `settings.py:265` is `llm_provider="openai"`, so `AgentQueryPipeline` has never run a real tool-use cycle in production. The OpenAI Tool Use wire format is structurally similar to Anthropic's but the call sites differ — `parallel_tool_calls`, `tool_choice`, `tool_call.id` correlation, and the message-list shape are provider-specific.

**Acceptance criteria:**
1. `BaseLLMClient` (or equivalent abstract base in `utils/llm_client.py` / `services/generator/llm_client.py`) defines an abstract method `call_agentic_turn(messages, tools, ...) -> AgentTurnResult` with a provider-neutral return shape (text content + tool calls + finish reason).
2. `AnthropicLLMClient.call_agentic_turn` and `OpenAILLMClient.call_agentic_turn` both implement the same contract; differences in wire format (Anthropic `tool_use` block vs OpenAI `tool_calls` array) are absorbed inside each adapter.
3. `services/pipeline.py:599-604` Anthropic-only fallback is removed. `AgentQueryPipeline.run` works end-to-end with both providers; `MAX_ITERATIONS = 5` is honored identically.
4. Unit tests exercise both adapters' `call_agentic_turn` against mock provider responses (parametrized over OpenAI + Anthropic wire shapes), covering: text-only response, single tool call, two parallel tool calls, max-iterations termination.
5. Integration test against live OpenAI (via OneAPI gateway, `gpt-4o-mini`) submits an `agent_mode=True` query through `/api/v1/query` and verifies the pipeline executed at least one tool call (not the fallback). Anthropic side is mock-tested if no Anthropic key available; live test gated on key presence.

#### REQ E-2 (AGENT-02): Parallel tool-call burst within a single turn

**As a** user issuing a multi-dimension question (e.g., "审计上月所有未结案件的产假天数、病假规定、加班补偿政策")
**I want** the agent to emit multiple tool calls in a single LLM turn and have them execute concurrently
**So that** independent sub-questions don't serialize behind each other and total latency drops proportionally to the parallelism factor

**Background:** Both providers support parallel tool calls natively (OpenAI: `parallel_tool_calls=True` is the default; Anthropic: `disable_parallel_tool_use=False` is the default). The OpenAI probe at `/tmp/probe_oai_parallel.py` already verified `gpt-4o-mini` returns 3 parallel `tool_calls` in a single response when prompted with three independent sub-questions. What's missing is the consumer-side change in `AgentQueryPipeline` to execute the returned tool calls with `asyncio.gather` instead of one at a time.

**Acceptance criteria:**
1. In a turn that returns N ≥ 2 tool calls, `AgentQueryPipeline` executes all N concurrently via `asyncio.gather` (or equivalent), not serially.
2. `parallel_tool_calls=True` is explicit in the OpenAI adapter's `call_agentic_turn` invocation; `disable_parallel_tool_use=False` is explicit in the Anthropic adapter (defaults exist on both, but explicit makes the contract auditable).
3. Tool result correlation is preserved: each tool result is bound to its triggering `tool_call.id`; the next LLM turn's message list contains all N tool results in the right order.
4. Audit log entry per turn records the parallelism factor (number of tool calls executed in parallel).
5. End-to-end integration test: submit a query that prompts ≥ 2 parallel tool calls; assert (a) the pipeline executed them concurrently (timing-based or via test-double tool with controllable latency), (b) all N results made it back to the LLM in the next turn, (c) the final answer references content from all N parallel results.
6. README adds a short "Parallel agentic tool calls" section under features, linking to the test that demonstrates it.

---

## Future Requirements (deferred to v1.3+)

- **AGENT-03**: True swarm with fork agents — multi-agent orchestration (spawn N parallel agents per query, each with isolated context, each pursuing different sub-question). References `claude-code` `forkedAgent.ts` pattern (filesystem-loaded `AgentDefinition` registry + `agentType` string lookup + cache-safe params for prompt cache sharing). Deeper architectural change than parallel tool calls within a single agent.
- **NLU-02**: LLM-based filter extractor fallback — extends `services/nlu/filter_extractor.py` with an LLM call when regex misses; cost-controlled via cache + heuristics gating.
- **UI-02**: Frontend modernization — JS / CSS extraction from `static/ui.html`; potentially React / Vue; possibly build step + npm.
- **TEST-04**: Integration-test coverage merging via `coverage combine` — extends Phase 10 gate.
- **TEST-05**: Per-file `# coverage:ignore-diff` overrides — escape hatch for boot-code.
- **TEST-06**: Raise legacy 46% global coverage floor.

---

## Out of Scope (v1.2)

- Implementing AGENT-03 swarm in this milestone (deferred — see Future Requirements). Reason: Step 0 abstraction + v0 parallel burst are tightly coupled (the abstraction must be validated by the first consumer). Swarm is a deeper architectural change (fork agents, inter-agent coordination, stop conditions) that benefits from a clean Step 0 baseline first.
- Anthropic live integration tests if no Anthropic API key available. Mock tests cover the wire format; live test gated on `ANTHROPIC_API_KEY` presence.
- Removing `agent_mode: bool = False` field in `utils/models.py:215`. Stays as the user-facing toggle; only the internal Anthropic-gate fallback is removed.
- LLM router that automatically picks between `agent_mode=False` (single-turn) and `agent_mode=True` (multi-turn agent) based on query complexity. Manual flag only in v1.2.
- Streaming SSE for agentic responses. SSE exists for non-agent queries; agent SSE is its own complexity surface — defer.
