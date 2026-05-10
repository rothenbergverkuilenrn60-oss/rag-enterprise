---
phase: 21-agent-05-multi-agent-debate-sub-agent-verifier
plan: 04
subsystem: pipeline
status: complete
tasks_completed: 2
tags: [pipeline, synthesizer, divergence, frozen-locked-string, tdd, agent-05, agent-14, sc5-byte-identity, p-08]
requires:
  - "VerifierVerdict (Plan 21-02) — utils/models.py:654-669"
  - "_SubAgentResult (AGENT-03 baseline) — services/pipeline.py:546-555 (already in module)"
provides:
  - "_DISAGREE_BANNER_TEMPLATE module constant — services/pipeline.py:592-600 (D-03 locked Chinese banner; Pitfall P-08 single-symbol-edit hoist)"
  - "SwarmQueryPipeline._synthesize signature: +verifier_verdict: VerifierVerdict | None = None — services/pipeline.py:1158-1175 (D-04; SC5/CF-08 byte-identity preserved)"
  - "SwarmQueryPipeline._synthesize divergence dispatch — services/pipeline.py:1183-1203 (zero LLM calls on disagree; reconstructs minimal _SubAgentResult placeholders from answers list)"
  - "SwarmQueryPipeline._format_disagree(verdict, sub_results) static helper — services/pipeline.py:1230-1252 (D-04 W7-verbatim signature; emits proposed_answer + locked banner)"
affects:
  - "Plan 21-05 — SwarmQueryPipeline.run() will call `await self._synthesize(req.query, sub_questions, answers, verifier_verdict=verdict)`; no need to plumb the original `successful: list[_SubAgentResult]` through (the disagree branch reconstructs placeholders internally)"
  - "Plan 21-06 — docs reference `_DISAGREE_BANNER_TEMPLATE` as the locked-string contract for the disagreement banner"
tech-stack:
  added: []
  patterns:
    - "Module-level locked-string constant for i18n single-symbol-edit (Pitfall P-08); test-pinned byte-identity"
    - "Default-None kwarg for opt-in extension preserving SC5 byte-identity on the unchanged path (CF-08)"
    - "@staticmethod helper colocated with the consumer method; no instance state added"
    - "AsyncMock(side_effect=AssertionError(...)) as a 'must-not-be-called' contract on a single mocked method"
key-files:
  modified:
    - path: services/pipeline.py
      lines: "75-93, 591-600, 1157-1252"
      role: "+VerifierVerdict to utils.models import; +_DISAGREE_BANNER_TEMPLATE module constant; +verifier_verdict kwarg + divergence dispatch on _synthesize; +_format_disagree static helper"
    - path: tests/unit/test_swarm_pipeline.py
      lines: "9, 13, 18, 26, 366-499"
      role: "+inspect import; +_SubAgentResult/VerifierVerdict imports; +5 RED→GREEN tests + helpers under '# ─── Phase 21 — _synthesize divergence branch' section header"
  created: []
decisions:
  - "Disagree dispatch placed BEFORE the Pitfall-5 graceful-degrade check inside _synthesize — verifier verdict supersedes the all-sub-agents-failed fallback; Plan 21-05 only invokes the verifier when at least one peer succeeded so the ordering is observationally equivalent (cleaner to read)"
  - "_format_disagree built as @staticmethod (not @classmethod, not module function) — colocated with SwarmQueryPipeline for grep-ability; no need for cls or self"
  - "Disagree branch reconstructs minimal _SubAgentResult placeholders (turns=0, tool_calls_count=0, chunks=[]) from the `answers: list[str]` parameter — keeps Plan 21-05's call site to a single new kwarg pass-through (_format_disagree only reads len(sub_results))"
  - "Test-side _DISAGREE_BANNER_LOCKED constant duplicates the production string; case 5 cross-checks byte-identity against the production constant. The duplication is intentional: production drift breaks the test, test drift would silently track production"
  - "Test verification used a broader -k filter (`synthesize_default_kwarg or synthesize_agree_kwarg or synthesize_disagree or format_disagree`) than the plan's literal `synthesize and (...)` — the synchronous test names (`test_format_disagree_*`) do not contain `synthesize`, so the plan's filter under-counted from 5 to 3. All 5 named tests collect and run via pytest's broader filter; the plan's literal grep-count gate (5 names present in file) was met verbatim"
metrics:
  duration_minutes: ~12
  completed_date: "2026-05-10"
  files_touched: 2
  lines_added: 201   # 63 services/pipeline.py + 138 tests/unit/test_swarm_pipeline.py
  tests_added: 5
  test_runtime_ms: 640
---

# Phase 21 Plan 04: _synthesize Divergence Branch + DISAGREE_BANNER_TEMPLATE Summary

**One-liner:** `SwarmQueryPipeline._synthesize` gains a `verifier_verdict: VerifierVerdict | None = None` kwarg with a zero-LLM-call disagree dispatch into a new `_format_disagree(verdict, sub_results)` static helper that emits the locked D-03 Chinese banner via a module-level `_DISAGREE_BANNER_TEMPLATE` constant — landed via clean RED→GREEN TDD with 5 tests covering D-03 / D-04 / Pitfall P-08, all pre-existing AGENT-03 swarm tests still green (SC5/CF-08 byte-identity proof).

## Tasks Completed

### Task 1 — RED: 5 failing tests (commit `96e8af2`)

Appended to `tests/unit/test_swarm_pipeline.py` under section header `# ─── Phase 21 — _synthesize divergence branch ─────────────────────────────`:

**Imports added:** `inspect`, `_SubAgentResult` (from services.pipeline), `VerifierVerdict` (from utils.models)
**Helpers added:** `_verdict(...)` → `VerifierVerdict`, `_peer(...)` → `_SubAgentResult`
**Locked reference constant:** `_DISAGREE_BANNER_LOCKED` (verbatim D-03 string for cross-check in case 5)

| # | Test name (B-id) | Branch | Pass condition |
|---|------------------|--------|----------------|
| 1 | `test_synthesize_default_kwarg_byte_identical` (B-24) | `verifier_verdict` kwarg omitted (default None) | `_llm.chat.await_count == 1` AND `result == "synthesized output"` AND `inspect.signature` contains the kwarg |
| 2 | `test_synthesize_agree_kwarg_byte_identical` (B-25) | `verifier_verdict.verdict == "agree"` | Same as case 1 — falls through to existing synthesis body |
| 3 | `test_synthesize_disagree_uses_proposed_answer_no_llm` (B-26) | `verifier_verdict.verdict == "disagree"` | `_llm.chat` configured with `AsyncMock(side_effect=AssertionError(...))` — would raise if called; result starts with `verdict.proposed_answer`; banner present with N=M=2 (`len(answers)`) and `chunk_count=3` (`len(verdict.evidence_chunk_ids)`) |
| 4 | `test_format_disagree_exact_template_substitution` (B-27) | Static helper called directly | EXACT byte-identity: `"ans\n\n⚠️ 子代理间存在分歧（3 个同伴中的 3 个提出差异回答）。以上回答基于验证者引用的证据（1 个块）。"` |
| 5 | `test_format_disagree_module_constant_present` (P-08) | `from services.pipeline import _DISAGREE_BANNER_TEMPLATE` | Constant is a string at module level; contains `{N}`, `{M}`, `{chunk_count}` placeholders; cross-check byte-identity against `_DISAGREE_BANNER_LOCKED` |

**RED gate confirmed:**

```
FAILED test_synthesize_default_kwarg_byte_identical
  → AssertionError: assert 'verifier_verdict' in mappingproxy({'self': ..., 'original_query': ...})
FAILED test_synthesize_agree_kwarg_byte_identical
  → TypeError: SwarmQueryPipeline._synthesize() got an unexpected keyword argument 'verifier_verdict'
FAILED test_synthesize_disagree_uses_proposed_answer_no_llm
  → TypeError: SwarmQueryPipeline._synthesize() got an unexpected keyword argument 'verifier_verdict'
FAILED test_format_disagree_exact_template_substitution
  → AttributeError: type object 'SwarmQueryPipeline' has no attribute '_format_disagree'
FAILED test_format_disagree_module_constant_present
  → ImportError: cannot import name '_DISAGREE_BANNER_TEMPLATE' from 'services.pipeline'
```

All four expected error types from the plan acceptance gate fired (`AssertionError` on signature inspect, `TypeError` on unknown kwarg, `AttributeError` on missing helper, `ImportError` on missing constant).

### Task 2 — GREEN: 3 surgical edits to `services/pipeline.py` (commit `a381c5a`)

**Edit 1 (lines 75-93):** Append `VerifierVerdict` to the existing `from utils.models import (...)` block (alphabetic-after-`Vee` neighbours; one-line addition with `Phase 21 / Plan 21-02 — kwarg type for _synthesize (D-04)` inline comment).

**Edit 2 (lines 591-600):** Add module-level constant `_DISAGREE_BANNER_TEMPLATE` directly below `_SYNTHESIS_SYSTEM`. Multi-line implicit string concatenation; comment block names D-03 + Pitfall P-08; comment warns about test-pinned byte-identity to deter casual edits.

**Edit 3 (lines 1157-1252):** Two sub-changes inside `SwarmQueryPipeline`:
1. Extend `_synthesize` signature with `verifier_verdict: VerifierVerdict | None = None`. Add an extended docstring paragraph explaining the D-04 semantics. Insert the divergence dispatch as the FIRST executable statement (before the Pitfall-5 graceful-degrade `if`). Dispatch reconstructs minimal placeholders: `[_SubAgentResult(answer=a, turns=0, tool_calls_count=0, chunks=[]) for a in answers]` so `peer_count == len(answers)` by construction. Returns `self._format_disagree(verifier_verdict, sub_results)`.
2. Append `@staticmethod _format_disagree(verdict: VerifierVerdict, sub_results: list[_SubAgentResult]) -> str` immediately after `_synthesize`. Body computes `peer_count = len(sub_results)`, builds banner via `_DISAGREE_BANNER_TEMPLATE.format(N=peer_count, M=peer_count, chunk_count=len(verdict.evidence_chunk_ids))`, returns `f"{verdict.proposed_answer}\n\n{banner}"`.

**GREEN gate confirmed:**

```
$ uv run python -m pytest tests/unit/test_swarm_pipeline.py \
    -k "synthesize_default_kwarg or synthesize_agree_kwarg or synthesize_disagree or format_disagree" -v
================= 5 passed, 8 deselected, 13 warnings in 0.62s =================
```

**Full-file regression check (SC5/CF-08 byte-identity proof):**

```
$ uv run python -m pytest tests/unit/test_swarm_pipeline.py
======================= 13 passed, 13 warnings in 0.64s ========================
```

All 8 pre-existing AGENT-03 swarm tests (test 1 N=1 fallback, test 2 isolated histories, test 3 concurrency, test 4 MAX_SWARM_AGENTS, test 5 partial failure, test 6 references all sub-answers, test 7 audit fields, test 8 main-model coordinator) pass unchanged.

## W7 Resolution

`_format_disagree` signature matches CONTEXT D-04 verbatim: `_format_disagree(verdict: VerifierVerdict, sub_results: list[_SubAgentResult]) -> str`. Plan-checker iter-1 W7 fix preserved end-to-end:

- Caller side (in-`_synthesize` dispatch) constructs `sub_results` from the `answers: list[str]` parameter rather than requiring Plan 21-05's verifier hop to plumb the original `successful: list[_SubAgentResult]` through to `_synthesize`. Plan 21-05's call site stays simple: `await self._synthesize(req.query, sub_questions, answers, verifier_verdict=verdict)` — a single new kwarg pass-through.
- Helper side reads `len(sub_results)` (not a separate `peer_count: int` parameter), keeping the int-coupling concern off the public-ish helper signature.
- `peer_count == len(answers)` by construction (the caller maps 1:1 from `answers` → placeholder `_SubAgentResult`s), so the contract `N=M=peer_count` is structurally true regardless of which call site invokes the helper.

## Hand-off Note for Plan 21-05

Verifier-hop integration in `SwarmQueryPipeline.run()` reads:

```python
# After existing asyncio.gather + answer collation:
synth_t0 = time.perf_counter()
final_answer = await self._synthesize(
    req.query,
    sub_questions,
    answers,
    verifier_verdict=verdict,        # NEW: only when req.debate=True; else None
)
synthesis_latency_ms = round((time.perf_counter() - synth_t0) * 1000, 1)
```

Plan 21-05 does NOT need to pass `successful` (the typed `list[_SubAgentResult]` it builds for audit metadata) into `_synthesize` — the disagree branch reconstructs placeholders internally from the `answers: list[str]` it already receives. This keeps the verifier-hop's `_synthesize` invocation byte-identical to the v1.4 swarm call shape except for the one new kwarg.

When `req.debate=False`, leave `verifier_verdict` unset (or pass `None` explicitly) and the call falls through to the existing synthesis body — SC5/CF-08 byte-identity preserved.

## Self-Check: PASSED

- `services/pipeline.py` — verified present (modified, lines 75-93, 591-600, 1157-1252).
- `tests/unit/test_swarm_pipeline.py` — verified present (modified, lines 9, 13, 18, 26, 366-499; 13 tests including 5 new).
- `.planning/phases/21-agent-05-multi-agent-debate-sub-agent-verifier/21-04-SUMMARY.md` — verified present (this file).
- Commit `96e8af2` (RED) — verified in `git log --oneline -5`.
- Commit `a381c5a` (GREEN) — verified in `git log --oneline -5`.

## Acceptance Gates

| Gate | Status |
|------|--------|
| 5 RED tests fail with expected error types (AssertionError / TypeError / AttributeError / ImportError) | ✓ |
| All 5 RED tests pass after GREEN | ✓ |
| Full `tests/unit/test_swarm_pipeline.py` (13 tests) green | ✓ — SC5/CF-08 byte-identity verified |
| `_DISAGREE_BANNER_TEMPLATE` is module-level string with `{N}`, `{M}`, `{chunk_count}` placeholders | ✓ — case 5 + module-level grep |
| `_synthesize` signature has `verifier_verdict: VerifierVerdict \| None = None` (default None) | ✓ — case 1 inspect.signature guard |
| `_format_disagree` signature matches D-04 verbatim (`sub_results: list[_SubAgentResult]`) | ✓ — W7 preserved |
| Disagree branch makes ZERO `_llm.chat` calls | ✓ — case 3 AsyncMock(side_effect=AssertionError) |
| `ruff check services/pipeline.py` — clean | ✓ — `All checks passed!` |
| `mypy --strict services/pipeline.py` — zero NEW errors vs baseline | ✓ — pre-existing errors at lines 466/766/809/986/992/998/1285/1328/1365 (none touched by this plan) |
| Pre-commit hook for `tvly-` regex did not block (Phase 20 SC5 carry-forward) | ✓ — no Tavily key strings in this plan's diff |
