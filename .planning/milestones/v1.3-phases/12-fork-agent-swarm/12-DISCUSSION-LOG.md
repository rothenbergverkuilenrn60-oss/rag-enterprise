# Phase 12: Fork-Agent Swarm - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 12-fork-agent-swarm
**Areas discussed:** Architecture, Swarm trigger, Memory context inheritance, Partial failure handling

---

## Architecture

| Option | Description | Selected |
|--------|-------------|----------|
| New SwarmQueryPipeline class | Separate class; AgentQueryPipeline untouched; swarm calls single-agent coroutine per sub-agent; clean separation, easy to test | ✓ |
| Extend AgentQueryPipeline | Add swarm logic into existing class; fewer classes but fat class with two very different execution paths | |
| You decide | Claude picks architecture | |

**User's choice:** New `SwarmQueryPipeline` class

---

| Option | Description | Selected |
|--------|-------------|----------|
| Keep get_agent_pipeline() + add get_swarm_pipeline() | Separate factory; existing routing unchanged; swarm is explicit entry point | ✓ |
| Replace get_agent_pipeline() to return SwarmQueryPipeline | Transparent swap; existing callers auto-get swarm; N=1 fallback adds complexity inside SwarmQueryPipeline | |

**User's choice:** Keep `get_agent_pipeline()` unchanged, add `get_swarm_pipeline()` separately

---

## Swarm Trigger

| Option | Description | Selected |
|--------|-------------|----------|
| Caller sets swarm_mode=True on GenerationRequest | Explicit opt-in; no wasted coordinator LLM call on single-dimension queries | ✓ |
| Auto-detect: coordinator always decomposes | Every agent_mode=True request pays coordinator LLM call; N=1 falls back | |
| Hybrid: swarm_mode flag + coordinator validates N | Flag triggers coordinator; if N=1 result, fallback | |

**User's choice:** `swarm_mode: bool = False` on `GenerationRequest`

---

| Option | Description | Selected |
|--------|-------------|----------|
| LLM call with structured output (JSON list) | Coordinator prompt → LLM returns JSON sub-questions; capped at MAX_SWARM_AGENTS | ✓ |
| Caller passes sub_questions list | Add sub_questions: list[str] to GenerationRequest; no coordinator LLM call | |

**User's choice:** Coordinator LLM call returning JSON list of sub-questions

---

## Memory Context Inheritance

| Option | Description | Selected |
|--------|-------------|----------|
| Sub-agents start clean (sub-question only) | messages = [{role: user, content: sub_question}]; true isolation; matches AGENT-03 AC#1 | ✓ |
| Sub-agents inherit session history | short_term[-6:] prepended; better coherence but reduces isolation and bloats context | |

**User's choice:** Clean context — no chat history in sub-agents

---

## Partial Failure Handling

| Option | Description | Selected |
|--------|-------------|----------|
| return_exceptions=True — synthesize partial results | gather collects all; failed agents produce error marker; synthesis receives partial + notes gap; audit records failures | ✓ |
| return_exceptions=False — first exception fails whole swarm | Cleaner error path; but one flaky agent silences all valid answers | |

**User's choice:** `return_exceptions=True` with error marker strings for failed sub-agents

---

## Claude's Discretion

None — user provided explicit choices for all areas.

## Deferred Ideas

None — discussion stayed within phase scope.
