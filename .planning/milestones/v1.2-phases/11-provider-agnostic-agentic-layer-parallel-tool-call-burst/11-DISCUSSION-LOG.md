# Phase 11: Provider-Agnostic Agentic Layer + Parallel Tool-Call Burst — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 11-provider-agnostic-agentic-layer-parallel-tool-call-burst
**Areas discussed:** AgenticTurn dataclass location, Ollama / unimpl provider handling, Anthropic test strategy, Cost guard semantics

---

## Area A — AgenticTurn dataclass location

| Option | Description | Selected |
|--------|-------------|----------|
| A1) `utils/models.py` (project central hub) | Single import surface; matches existing convention; both adapters AND pipeline.py already import from here; honors three-layer arch | ✓ |
| A2) `services/generator/agentic_turn.py` (new file) | Own module, no risk; cost: extra file, breaks "co-locate small types" convention; only justified if dataclass grows | |
| A3) `services/generator/llm_client.py` (top of file) | Co-located with adapters; cost: pipeline.py imports feel adapter-internal; pollutes llm_client.py top | |

**User's choice:** A1
**Notes:** `utils/models.py` is already the cross-layer types hub (`GenerationRequest/Response`, `ChunkMetadata`, `RetrievedChunk`, `agent_mode` field). Three-layer arch (`utils/` → `services/` → `controllers/`) holds; lowest layer never imports upward, so circular-import risk is non-existent.

---

## Area B — Ollama / unimplemented provider handling

| Option | Description | Selected |
|--------|-------------|----------|
| B1) Default `raise NotImplementedError` on `BaseLLMClient.call_agentic_turn` | Generic mechanism; preserves Anthropic-only-fallback behavior for Ollama users without Anthropic-specific code; matches narrow-except + structured-logging | ✓ |
| B2) Implement `OllamaLLMClient.call_agentic_turn` now (via OpenAI-compat shim) | Reuses OpenAI adapter wire format; cost: extra ~80 LOC + integration test; goes beyond Step 0 + v0 scope | |
| B3) Keep `call_agentic_turn` abstract; force every BaseLLMClient subclass to implement | Strictest contract; immediately breaks Ollama users at startup time | |

**User's choice:** B1
**Notes:** `AgentQueryPipeline.run` catches `NotImplementedError` from `call_agentic_turn`, logs structured warning with `provider=type(self._llm).__name__`, falls back to `QueryPipeline`. Generic replacement for the deleted Anthropic-only gate.

---

## Area C — Anthropic test strategy without API key

| Option | Description | Selected |
|--------|-------------|----------|
| C1) Pure mock with recorded wire shapes | Hand-curated `.json` fixtures in `tests/unit/fixtures/agentic_turn/`; deterministic, free, CI-friendly; live Anthropic test skip-gated on `ANTHROPIC_API_KEY` | ✓ |
| C2) VCR cassette (record-once, replay-many) | Higher fidelity; cost: extra dep, cassette maintenance, key required for re-record | |
| C3) Require `ANTHROPIC_API_KEY` in CI; skip if absent | Live tests only; simplest code; cost: CI flakes on Anthropic outages, consumes tokens, no key on this CI right now | |

**User's choice:** C1
**Notes:** Office-hours D12 already accepted "no Anthropic side live test in v0"; mock fixtures cover wire shape parity. ~7 fixture files needed (text-only, single tool, two parallel tools, max-iterations × OpenAI + Anthropic shapes). Live OpenAI test runs unconditionally via OneAPI gateway (build-step-1 probe verified).

---

## Area D — Cost guard / opt-in semantics for parallel burst

| Option | Description | Selected |
|--------|-------------|----------|
| D1) Parallel burst inherits existing `agent_mode` gate | Single user-facing toggle; office-hours D4 (15× tokens warn) already satisfied by `agent_mode` being opt-in default-False; simplest API | ✓ |
| D2) Separate `parallel_burst: bool = False` field | Two flags = 4-cell matrix; 3 cells don't make product sense | |
| D3) `settings.parallel_burst_enabled` env-level kill-switch | Less per-tenant flexibility; useful only as emergency disable | |

**User's choice:** D1
**Notes:** `agent_mode=True` already requires user opt-in via `GenerationRequest`; parallel burst becomes the value `agent_mode=True` delivers in v1.2. NO new field, NO new env var, NO new settings entry. `controllers/api.py:200` dispatch unchanged.

---

## Claude's Discretion (planner / executor decide HOW)

- Exact line placement of `AgenticTurn` / `ToolCall` in `utils/models.py`
- Mock fixture JSON content (must be realistic; planner reads Anthropic + OpenAI tool-use docs)
- Full rewrite of `pipeline.py:599-717` vs surgical edit (planner picks based on diff readability)
- `asyncio.gather(return_exceptions=True)` exception → `tool_result is_error=True` conversion shape
- Audit log field name for parallelism factor (suggest `agent_parallelism_factor`)
- Move `seen_ids` chunk-dedup from inside-loop to outside-gather (refactor side-effect)
- README copy for "Parallel agentic tool calls" section
- `dataclasses.dataclass(frozen=True)` vs Pydantic V2 model for AgenticTurn
- `stop_reason` Literal mapping finalization (Anthropic + OpenAI → AgenticTurn)

## Deferred Ideas

1. `OllamaLLMClient.call_agentic_turn` implementation (B2) — v1.3 if requested
2. VCR cassette test strategy (C2) — if mock fixtures become maintenance burden
3. Separate `parallel_burst: bool` flag (D2) — if real product use case emerges
4. `settings.parallel_burst_enabled` kill-switch (D3) — emergency disable only
5. True swarm with fork agents (AGENT-03 / v1) — v1.3
6. Streaming SSE for agentic responses — v1.3+
7. Agent-mode auto-router (auto-pick single-turn vs multi-turn) — v1.3+
8. Removing `agent_mode: bool` field entirely — only after auto-router proves itself
9. Anthropic prompt-caching adjustments for `call_agentic_turn` path
10. Live OpenAI integration test in CI matrix (multi-region, model-fallback)
