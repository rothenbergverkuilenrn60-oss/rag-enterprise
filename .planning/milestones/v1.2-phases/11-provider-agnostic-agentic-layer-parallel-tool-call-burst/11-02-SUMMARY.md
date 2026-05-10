---
phase: 11-provider-agnostic-agentic-layer-parallel-tool-call-burst
plan: 02
subsystem: tests/fixtures
tags: [test-fixtures, agentic, anthropic, openai, wire-format]
dependency_graph:
  requires: []
  provides:
    - "tests/unit/fixtures/agentic_turn/__init__.py (package marker)"
    - "tests/unit/fixtures/agentic_turn/anthropic_text_only.json (Messages stop_reason=end_turn)"
    - "tests/unit/fixtures/agentic_turn/anthropic_single_tool_use.json (Messages stop_reason=tool_use, 1 block)"
    - "tests/unit/fixtures/agentic_turn/anthropic_two_parallel_tool_use.json (Messages stop_reason=tool_use, 2 blocks)"
    - "tests/unit/fixtures/agentic_turn/anthropic_max_iterations.json (Messages stop_reason=max_tokens)"
    - "tests/unit/fixtures/agentic_turn/openai_text_only.json (ChatCompletion finish_reason=stop)"
    - "tests/unit/fixtures/agentic_turn/openai_single_tool_call.json (ChatCompletion finish_reason=tool_calls, 1 call)"
    - "tests/unit/fixtures/agentic_turn/openai_two_parallel_tool_calls.json (ChatCompletion finish_reason=tool_calls, 2 calls)"
  affects:
    - "Plan 11-03 unit tests (test_llm_client_agentic.py) consume these fixtures via json.load"
tech_stack:
  added: []
  patterns:
    - "Hand-curated wire-format JSON fixtures (per D-04 lock — no VCR cassettes)"
    - "OpenAI function.arguments as JSON-encoded string (matches SDK wire contract)"
    - "Anthropic content blocks (text + tool_use) inside Messages envelope"
key_files:
  created:
    - "tests/unit/fixtures/agentic_turn/__init__.py"
    - "tests/unit/fixtures/agentic_turn/anthropic_text_only.json"
    - "tests/unit/fixtures/agentic_turn/anthropic_single_tool_use.json"
    - "tests/unit/fixtures/agentic_turn/anthropic_two_parallel_tool_use.json"
    - "tests/unit/fixtures/agentic_turn/anthropic_max_iterations.json"
    - "tests/unit/fixtures/agentic_turn/openai_text_only.json"
    - "tests/unit/fixtures/agentic_turn/openai_single_tool_call.json"
    - "tests/unit/fixtures/agentic_turn/openai_two_parallel_tool_calls.json"
  modified: []
decisions:
  - "Followed D-04 (pure-mock fixtures, NO VCR) and the exact JSON shapes specified in 11-02-PLAN.md"
  - "OpenAI tool_calls[].function.arguments preserved as JSON-encoded STRING (not dict) — matches OpenAI wire contract; Plan 11-03 adapter must json.loads to materialize dict"
  - "Anthropic Messages envelope includes id/type/role/model/content/stop_reason/stop_sequence/usage — matches Anthropic Messages API response shape"
  - "OpenAI ChatCompletion envelope includes id/object/created/model/choices/usage — matches OpenAI Chat Completions response shape"
metrics:
  duration_min: 5
  completed_date: "2026-05-08"
requirements: [AGENT-01]
---

# Phase 11 Plan 02: Hand-Curated Wire Fixtures for Agentic Turn Adapters

Seven realistic provider wire-format JSON fixtures (4 Anthropic Messages, 3 OpenAI ChatCompletions) plus a `__init__.py` package marker, all under `tests/unit/fixtures/agentic_turn/`, replayable by Plan 11-03's mock-driven unit tests for `AnthropicLLMClient.call_agentic_turn` / `OpenAILLMClient.call_agentic_turn`.

## What Was Built

| File | Provider | Scenario | stop_reason / finish_reason | tool blocks |
|---|---|---|---|---|
| `anthropic_text_only.json` | Anthropic | Plain answer, no tool calls | `end_turn` | 0 |
| `anthropic_single_tool_use.json` | Anthropic | Single tool call | `tool_use` | 1 |
| `anthropic_two_parallel_tool_use.json` | Anthropic | Two parallel tool calls in one turn | `tool_use` | 2 |
| `anthropic_max_iterations.json` | Anthropic | Output token cap hit | `max_tokens` | 0 |
| `openai_text_only.json` | OpenAI | Plain answer, no tool calls | `stop` | 0 |
| `openai_single_tool_call.json` | OpenAI | Single tool call | `tool_calls` | 1 |
| `openai_two_parallel_tool_calls.json` | OpenAI | Two parallel tool calls in one turn | `tool_calls` | 2 |

Total fixture footprint: **~4 KB** (well under the 10 KB ceiling specified in the plan's verification block).

## Wire-Shape Realism Check

**Anthropic Messages API envelope (matches `anthropic.types.Message`):**
- Top-level keys: `id`, `type="message"`, `role="assistant"`, `model`, `content[]`, `stop_reason`, `stop_sequence`, `usage`
- `content[]` blocks: `{"type":"text","text":"..."}` and `{"type":"tool_use","id":"toolu_...","name":"...","input":{...}}`
- `tool_use.input` is a **nested object** (Anthropic wire shape — not a JSON-encoded string)
- `stop_reason` covers all 3 enum values needed by Plan 11-03's adapter mapping table: `end_turn` → `text_only`, `tool_use` → `tool_use`, `max_tokens` → `max_tokens`
- `usage`: `input_tokens` + `output_tokens` keys present on every fixture

**OpenAI Chat Completions envelope (matches `openai.types.chat.ChatCompletion`):**
- Top-level keys: `id`, `object="chat.completion"`, `created`, `model`, `choices[]`, `usage`
- `choices[]` shape: `{"index":0,"message":{...},"finish_reason":"...","logprobs":null}`
- `message` shape: `{"role":"assistant","content":...,"refusal":null,"tool_calls":[...]}`
  - When `tool_calls` is present, `content=null` (per OpenAI contract)
  - When no tools, `tool_calls` field is omitted (per OpenAI contract)
- `tool_calls[i]` shape: `{"id":"call_...","type":"function","function":{"name":"...","arguments":"<JSON string>"}}`
- **`function.arguments` is intentionally a JSON-encoded STRING, not a dict** — matches the OpenAI Python SDK wire contract. Plan 11-03's adapter must `json.loads(tool_call.function.arguments)` to materialize the `ToolCall.arguments` dict.
- `finish_reason` covers both enum values needed: `stop` → `text_only`, `tool_calls` → `tool_use`
- `usage`: `prompt_tokens` + `completion_tokens` + `total_tokens` keys present on every fixture

## Verification

| Check | Command | Result |
|---|---|---|
| 7 JSON files exist | `ls tests/unit/fixtures/agentic_turn/*.json \| wc -l` | `7` |
| Every file parses | `find ... -name "*.json" -exec python3 -c "import json,sys; json.load(open(sys.argv[1]))" {} \;` | All pass |
| `__init__.py` exists | `ls tests/unit/fixtures/agentic_turn/__init__.py` | exists (empty) |
| Anthropic stop_reasons | inspect `stop_reason` per file | end_turn / tool_use / tool_use / max_tokens (all match plan) |
| OpenAI finish_reasons | inspect `choices[0].finish_reason` per file | stop / tool_calls / tool_calls (all match plan) |
| tool_use block counts (Anthropic) | count `content[i].type=="tool_use"` | 0 / 1 / 2 / 0 (all match plan) |
| tool_calls counts (OpenAI) | count `choices[0].message.tool_calls` | 0 / 1 / 2 (all match plan) |
| OpenAI args is JSON string | `isinstance(tc['function']['arguments'], str)` | `True`; `json.loads(...)` round-trips to dict |
| Scope orthogonality (vs 11-01) | `git diff --name-only base..HEAD` | only `tests/unit/fixtures/agentic_turn/*` (no `utils/`, `services/`, or test code touched) |
| Total size budget | `du -sb tests/unit/fixtures/agentic_turn/` | 4 007 bytes (< 10 KB) |

## Deviations from Plan

**None.** All 7 fixtures and `__init__.py` were created with the exact JSON contents specified in the plan's `<action>` blocks. No structural changes, no extra fields, no field removals.

## Commits

| Task | Hash | Message |
|---|---|---|
| Task 1 | `9225955` | `test(11-02): add 4 Anthropic Messages API wire fixtures` |
| Task 2 | `75ef6f8` | `test(11-02): add 3 OpenAI Chat Completions wire fixtures` |

## Downstream Hand-off (Plan 11-03)

Plan 11-03's unit tests (`tests/unit/test_llm_client_agentic.py`) load these fixtures via:

```python
from pathlib import Path
import json
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "agentic_turn"
data = json.loads((FIXTURE_DIR / "anthropic_two_parallel_tool_use.json").read_text(encoding="utf-8"))
```

The adapter test then wraps the loaded dict in a `SimpleNamespace`-style shim (or feeds it through `anthropic.types.Message.model_validate(...)` / `openai.types.chat.ChatCompletion.model_validate(...)`) and asserts that:

- `AnthropicLLMClient.call_agentic_turn` returns `AgenticTurn` with `stop_reason="text_only"` for `anthropic_text_only.json`, `"tool_use"` with `len(tool_calls)==1` for `anthropic_single_tool_use.json`, `"tool_use"` with `len(tool_calls)==2` for `anthropic_two_parallel_tool_use.json`, and `"max_tokens"` for `anthropic_max_iterations.json`.
- `OpenAILLMClient.call_agentic_turn` returns `AgenticTurn` with `stop_reason="text_only"` for `openai_text_only.json`, `"tool_use"` with `len(tool_calls)==1` for `openai_single_tool_call.json`, and `"tool_use"` with `len(tool_calls)==2` for `openai_two_parallel_tool_calls.json`.
- For both providers, each `ToolCall.arguments` is a `dict` (after the OpenAI adapter `json.loads()` step) — provider-neutral consumption shape.

## Self-Check: PASSED

- `tests/unit/fixtures/agentic_turn/__init__.py` — FOUND
- `tests/unit/fixtures/agentic_turn/anthropic_text_only.json` — FOUND
- `tests/unit/fixtures/agentic_turn/anthropic_single_tool_use.json` — FOUND
- `tests/unit/fixtures/agentic_turn/anthropic_two_parallel_tool_use.json` — FOUND
- `tests/unit/fixtures/agentic_turn/anthropic_max_iterations.json` — FOUND
- `tests/unit/fixtures/agentic_turn/openai_text_only.json` — FOUND
- `tests/unit/fixtures/agentic_turn/openai_single_tool_call.json` — FOUND
- `tests/unit/fixtures/agentic_turn/openai_two_parallel_tool_calls.json` — FOUND
- Commit `9225955` — FOUND in `git log`
- Commit `75ef6f8` — FOUND in `git log`
